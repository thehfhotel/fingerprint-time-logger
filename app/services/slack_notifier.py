"""
Slack notifier for ZK time-sync events.

Ported from `zk-time-sync/sync_service.py` (send_slack_notification +
format_sync_summary) and extended with state-change throttling so that
moving the time-sync schedule from every 30 min → every 5 min does not
flood the channel: only post on transitions (OK→fail or fail→OK), plus a
single daily heartbeat at the configured time.

Confirmed-failure paging (2026-09): the device evicts our TCP session
whenever another TCP client connects, which used to look like a sync
failure on the very next 5-min tick and paged the owner for something
that self-heals within one cycle. `page_after_failures` (default 2, i.e.
10 min of real downtime) requires a *streak* of consecutive failures
before paging, a single blip logs quietly and resets, and a page is
always paired with a recovery message when the streak clears — see
estate alerting policy: page only on confirmed/unrecoverable failures.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

_BANGKOK = ZoneInfo("Asia/Bangkok")


class SlackSyncNotifier:
    """
    Decides whether a given sync result should produce a Slack message and
    sends it. Thread-safe — the time-sync scheduler may call into this from
    a worker thread.

    Throttling rules:
      * Failure: only pages once the consecutive-failure streak reaches
        `page_after_failures` (a shorter streak is a silent "blip" that
        self-heals — logged, not paged). Once paged, re-paging while the
        streak continues is suppressed for `failure_suppress_seconds`.
      * Success following a page: notify (recovery signal), resets the
        streak and the paged flag.
      * Success following an unpaged blip: resets the streak silently,
        sends nothing for the blip itself, then falls through to the
        normal startup/heartbeat evaluation below.
      * Success following a success: notify only if `heartbeat_hour`
        matches the current Bangkok hour and we haven't already
        heartbeated today, or this is the very first tick since startup.

    All wall-clock/monotonic reads go through `_now_bangkok()` /
    `_monotonic()` so tests can control time deterministically instead of
    monkeypatching the `datetime`/`time` modules directly.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        channel: str = "#zk-time-sync",
        username: str = "ZK Time Sync Bot",
        mention_on_error: str = "@winut.hf",
        heartbeat_hour: int = 9,
        failure_suppress_seconds: int = 1800,
        page_after_failures: Optional[int] = None,
        degraded_suppress_seconds: int = 3600,
    ):
        self.webhook_url = webhook_url or os.getenv("ZK_SYNC_SLACK_WEBHOOK_URL", "")
        self.channel = channel
        self.username = username
        self.mention_on_error = mention_on_error
        self.heartbeat_hour = heartbeat_hour
        self.failure_suppress_seconds = failure_suppress_seconds

        if page_after_failures is None:
            try:
                page_after_failures = int(os.getenv("ZK_SYNC_PAGE_AFTER_FAILURES", "2"))
            except (TypeError, ValueError):
                page_after_failures = 2
        self.page_after_failures = max(1, page_after_failures)
        self.degraded_suppress_seconds = degraded_suppress_seconds

        self._lock = threading.Lock()
        self._last_success: Optional[bool] = None
        self._last_heartbeat_date: Optional[str] = None
        self._last_failure_at: Optional[float] = None
        self._consecutive_failures: int = 0
        self._failure_streak_started: Optional[str] = None
        self._paged: bool = False
        self._last_degraded_at: Optional[float] = None
        # Generation counter for the "commit-before-send, roll back if send
        # fails" pattern used by _handle_failure, _send_recovery, and
        # notify_degraded — see _commit() below.
        self._commit_gen: int = 0

    # ------------------------------------------------------------------ time (overridable for tests)

    def _now_bangkok(self) -> datetime:
        return datetime.now(_BANGKOK)

    def _monotonic(self) -> float:
        return time.monotonic()

    # ------------------------------------------------------------------ commit-before-send supersession token

    def _commit(self) -> int:
        """Bump and return the commit generation.

        Call this while holding `self._lock`, immediately after writing the
        optimistic state for a "commit before send" site (paging, recovery,
        degraded-note rate limit) — never for a plain sub-threshold failure
        blip, which only increments `_consecutive_failures` and must not be
        treated as a commit.

        After the network `_send(...)` call returns, the caller reacquires
        `self._lock` and rolls back its optimistic write only if
        `self._commit_gen` is still equal to the value captured here — i.e.
        nothing else has committed-before-send in the meantime. This
        replaces the old fragile proxies (`self._last_failure_at == now`,
        `self._consecutive_failures == 0 and not self._paged`,
        `self._last_degraded_at == now`), which could misfire when an
        unrelated sub-threshold blip mutated `_consecutive_failures` while a
        send was in flight.
        """
        self._commit_gen += 1
        return self._commit_gen

    # ------------------------------------------------------------------ public

    def notify_sync_result(self, result: dict, device_name: str = "Main Fingerprint Device") -> bool:
        """Decide-and-send. Returns True if a message was actually sent."""
        success = bool(result.get("success"))
        if not success:
            return self._handle_failure(result, device_name)
        return self._handle_success(result, device_name)

    def notify_degraded(self, kicks: int, window_minutes: int = 60, device_name: str = "Main Fingerprint Device") -> bool:
        """Non-paging heads-up that the live-capture session keeps getting
        evicted (another TCP client is contending for the reader). Sync
        self-heals via backoff+reconnect, so this is informational only —
        rate-limited to `degraded_suppress_seconds` between posts."""
        with self._lock:
            now = self._monotonic()
            if self._last_degraded_at is not None and now - self._last_degraded_at < self.degraded_suppress_seconds:
                return False
            # Commit the rate-limit timestamp before the network call below,
            # same "commit before send" pattern as the failure/recovery
            # paths — otherwise two concurrent degraded checks inside the
            # suppress window could both pass the check above and both send.
            # Rolled back if the send fails so the next check can retry.
            self._last_degraded_at = now
            my_gen = self._commit()

        text = (
            f"⚠️ ZK reader session evicted {kicks}× in the last {window_minutes} min - "
            f"{device_name}. Another TCP client is hitting the reader; sync self-heals, "
            f"no action unless it persists."
        )
        sent = self._send(
            text,
            is_error=False,
            mention=False,
            color="#ffa500",
            title="⚠️ ZK Time Sync Degraded",
        )
        if not sent:
            with self._lock:
                if self._commit_gen == my_gen:
                    self._last_degraded_at = None
        return sent

    def notify_error(self, error_message: str) -> bool:
        """Send a freeform error message (e.g. scheduler-level crash)."""
        return self._send(error_message, is_error=True)

    # ------------------------------------------------------------------ failure path

    def _handle_failure(self, result: dict, device_name: str) -> bool:
        with self._lock:
            self._consecutive_failures += 1
            streak = self._consecutive_failures
            if streak == 1:
                self._failure_streak_started = self._now_bangkok().strftime("%H:%M")
            start = self._failure_streak_started
            threshold = self.page_after_failures

            if streak < threshold:
                self._last_success = False
                logger.info(f"[slack_notifier] blip {streak}/{threshold} suppressed")
                return False

            now = self._monotonic()
            should_page = not self._paged or (
                self._last_failure_at is not None
                and now - self._last_failure_at >= self.failure_suppress_seconds
            )
            self._last_success = False
            if not should_page:
                logger.debug(f"[slack_notifier] re-page suppressed (streak={streak})")
                return False

            # Commit the paging decision *before* releasing the lock and
            # making the (slow, network) `_send` call below. Deciding under
            # the lock but committing `_paged`/`_last_failure_at` only after
            # `_send` returns left a window where two concurrent callers
            # both crossing the threshold would both observe `_paged is
            # False` and both send a page for the same outage. Setting it
            # here means a concurrent caller sees `_paged=True` immediately
            # and backs off; rolled back below if the send itself fails so
            # a later tick can still retry paging.
            self._paged = True
            self._last_failure_at = now
            my_gen = self._commit()

        err = result.get("error") or result.get("message") or "unknown error"
        message = f"🚨 ZK Sync FAILED {streak} consecutive checks since {start} - {device_name}: {err}"
        sent = self._send(message, is_error=True)
        if not sent:
            with self._lock:
                # Only roll back if nothing newer has already committed
                # before its own send since (e.g. a concurrent success
                # already cleared _paged and bumped the generation, or a
                # later page attempt superseded us). A plain sub-threshold
                # failure blip never bumps `_commit_gen`, so it can never
                # block this rollback.
                if self._commit_gen == my_gen:
                    self._paged = False
                    self._last_failure_at = None
        # Note: once `_send` above returns True, the page has already gone
        # out on the wire and cannot be un-sent. Under a genuinely
        # concurrent caller (not today's single-threaded APScheduler job),
        # Slack message ORDER is therefore best-effort — a recovery and a
        # page could in principle land out of order depending on which
        # `_send` call completes first — while internal STATE
        # (`_paged` / `_consecutive_failures` / `_commit_gen`) stays
        # consistent because every writer serializes through `self._lock`.
        # Acceptable given the single-threaded caller; no speculative
        # ordering machinery is added here.
        return sent

    # ------------------------------------------------------------------ success path

    def _handle_success(self, result: dict, device_name: str) -> bool:
        my_gen = None
        with self._lock:
            was_paged = self._paged
            streak = self._consecutive_failures
            streak_started = self._failure_streak_started
            if was_paged:
                # Same "commit before send" pattern as _handle_failure: clear
                # `_paged` here, under the lock, before the network call below
                # — otherwise two concurrent success ticks could both observe
                # `_paged is True` and both send a recovery message for the
                # same outage. Rolled back if `_send` fails so a later success
                # tick retries the recovery notice instead of losing it.
                self._paged = False
                self._consecutive_failures = 0
                self._failure_streak_started = None
                my_gen = self._commit()

        if was_paged:
            return self._send_recovery(result, device_name, streak, streak_started, my_gen)

        if streak > 0:
            with self._lock:
                self._consecutive_failures = 0
                self._failure_streak_started = None
            logger.info(f"[slack_notifier] blip resolved after {streak} check(s) without paging")

        return self._handle_normal_success(result, device_name)

    def _send_recovery(
        self,
        result: dict,
        device_name: str,
        streak: int,
        streak_started: Optional[str] = None,
        my_gen: Optional[int] = None,
    ) -> bool:
        hhmm = self._now_bangkok().strftime("%H:%M")
        device_time = self._extract_device_time(result)
        before = result.get("time_diff_before", 0)
        after = result.get("time_diff_after", 0)
        message = (
            f"✅ ZK Sync recovered at {hhmm} after {streak} failed checks - "
            f"{device_name}:{device_time}({before:.1f}s→{after:.1f}s)"
        )
        sent = self._send(message, is_error=False, mention=False)
        with self._lock:
            if sent:
                self._last_success = True
            else:
                # Roll back the optimistic commit made in _handle_success so
                # a later success tick retries sending the recovery message
                # — unless something else has committed-before-send since
                # (a later failure streak reaching threshold again, or a
                # second concurrent recovery attempt). Guarded by the
                # generation counter rather than
                # `_consecutive_failures == 0 and not _paged`: that old
                # proxy read False (blocking the rollback) whenever an
                # unrelated sub-threshold failure blip raced in during the
                # send and bumped `_consecutive_failures`, permanently
                # dropping the recovery for a real, still-paged outage. A
                # plain blip never calls `_commit()`, so it can never block
                # this rollback.
                if my_gen is not None and self._commit_gen == my_gen:
                    self._paged = True
                    self._consecutive_failures = streak
                    self._failure_streak_started = streak_started
        return sent

    def _handle_normal_success(self, result: dict, device_name: str) -> bool:
        my_gen = None
        prev_heartbeat_date = None
        with self._lock:
            prev_last_success = self._last_success
            today = self._now_bangkok().date().isoformat()
            now_hour = self._now_bangkok().hour

            if prev_last_success is None:
                reason = "startup"
            elif now_hour == self.heartbeat_hour and self._last_heartbeat_date != today:
                reason = "heartbeat"
            else:
                reason = "noop"

            if reason == "noop":
                self._last_success = True
                return False

            # Commit the decision *before* releasing the lock and making the
            # (slow, network) `_send` call below — same "commit before send"
            # pattern as _handle_failure/_send_recovery/notify_degraded.
            # Committing only after `_send` returned left a window where two
            # concurrent callers could both see `_last_success is None` (both
            # decide "startup") or both see `_last_heartbeat_date != today`
            # (both decide "heartbeat") and both send a duplicate benign "1/1
            # OK" message. Setting `_last_success = True` here for startup
            # means a concurrent caller no longer sees `None` and falls
            # through to "noop"; staging `_last_heartbeat_date = today` here
            # for heartbeat means a concurrent caller sees it already equal
            # to today and also falls through to "noop". Rolled back (for
            # heartbeat only) below if the send fails, so a later tick can
            # still retry.
            self._last_success = True
            if reason == "heartbeat":
                prev_heartbeat_date = self._last_heartbeat_date
                self._last_heartbeat_date = today
            my_gen = self._commit()

        message = self._format_success(result, device_name)
        sent = self._send(message, is_error=False, mention=False)
        with self._lock:
            # `_last_success` is already True from the commit above and
            # stays True regardless of send outcome — that's the existing
            # startup/heartbeat state semantics, and leaving it set is
            # harmless even if the send failed.
            if reason == "heartbeat" and not sent:
                # Only roll back if nothing newer has already committed
                # before its own send since (e.g. a concurrent notifier
                # state change bumped the generation). A plain rollback
                # guarded only by equality-to-today would misfire the same
                # way the old proxies did on the other three sites.
                if self._commit_gen == my_gen:
                    self._last_heartbeat_date = prev_heartbeat_date
        return sent

    # ------------------------------------------------------------------ formatting

    def _extract_device_time(self, result: dict) -> str:
        new_iso = result.get("new_time", "")
        device_time = "??"
        if "T" in new_iso:
            try:
                device_time = new_iso.split("T")[1][:5]
            except Exception:
                pass
        return device_time

    def _format_success(self, result: dict, device_name: str) -> str:
        bangkok_time = self._now_bangkok().strftime("%H:%M")
        time_diff_before = result.get("time_diff_before", 0)
        time_diff_after = result.get("time_diff_after", 0)
        device_time = self._extract_device_time(result)
        return (
            f"✅ ZK Sync 1/1 OK at {bangkok_time} - "
            f"{device_name}:{device_time}({time_diff_before:.1f}s→{time_diff_after:.1f}s)"
        )

    # ------------------------------------------------------------------ transport

    def _send(
        self,
        message: str,
        is_error: bool,
        mention: Optional[bool] = None,
        color: Optional[str] = None,
        title: Optional[str] = None,
    ) -> bool:
        if not self.webhook_url:
            logger.warning("[slack_notifier] no webhook configured; dropping message")
            return False
        if mention is None:
            mention = is_error
        text = f"<{self.mention_on_error}> {message}" if mention else message
        if color is None:
            color = "#ff0000" if is_error else "#36a64f"
        if title is None:
            title = f"{'❌' if is_error else '✅'} ZK Time Sync {'Error' if is_error else 'Notification'}"
        payload = {
            "username": self.username,
            "channel": self.channel,
            "attachments": [
                {
                    "color": color,
                    "title": title,
                    "text": text,
                    "footer": "ZK Time Sync Service",
                    "ts": int(time.time()),
                }
            ],
        }
        try:
            r = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 200:
                return True
            logger.error(f"[slack_notifier] slack returned HTTP {r.status_code}: {r.text[:200]}")
            return False
        except Exception as exc:
            logger.error(f"[slack_notifier] post failed: {exc}")
            return False


slack_notifier = SlackSyncNotifier()
