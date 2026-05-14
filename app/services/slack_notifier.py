"""
Slack notifier for ZK time-sync events.

Ported from `zk-time-sync/sync_service.py` (send_slack_notification +
format_sync_summary) and extended with state-change throttling so that
moving the time-sync schedule from every 30 min → every 5 min does not
flood the channel: only post on transitions (OK→fail or fail→OK), plus a
single daily heartbeat at the configured time.
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
      * Failure (first or recovered-then-failed-again): notify.
      * Failure within `_FAILURE_SUPPRESS_SECONDS` of the last failure notice:
        skip. Prevents a 5-min poll cadence from posting 12 alerts an hour
        when the device is persistently unreachable.
      * Success following a failure: notify (recovery signal).
      * Success following a success: notify only if `heartbeat_hour` matches
        the current Bangkok hour and we haven't already heartbeated today.
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        channel: str = "#zk-time-sync",
        username: str = "ZK Time Sync Bot",
        mention_on_error: str = "@winut.hf",
        heartbeat_hour: int = 9,
        failure_suppress_seconds: int = 1800,
    ):
        self.webhook_url = webhook_url or os.getenv("ZK_SYNC_SLACK_WEBHOOK_URL", "")
        self.channel = channel
        self.username = username
        self.mention_on_error = mention_on_error
        self.heartbeat_hour = heartbeat_hour
        self.failure_suppress_seconds = failure_suppress_seconds

        self._lock = threading.Lock()
        self._last_success: Optional[bool] = None
        self._last_heartbeat_date: Optional[str] = None
        self._last_failure_at: Optional[float] = None

    # ------------------------------------------------------------------ public

    def notify_sync_result(self, result: dict, device_name: str = "Main Fingerprint Device") -> bool:
        """Decide-and-send. Returns True if a message was actually sent."""
        success = bool(result.get("success"))
        should_send, reason = self._should_send(success)
        if not should_send:
            logger.debug(f"[slack_notifier] skipping (last={self._last_success}, success={success})")
            return False

        message = self._format(result, device_name, success)
        sent = self._send(message, is_error=not success)
        if sent:
            with self._lock:
                self._last_success = success
                if reason == "heartbeat":
                    self._last_heartbeat_date = datetime.now(_BANGKOK).date().isoformat()
                if not success:
                    self._last_failure_at = time.monotonic()
        return sent

    def notify_error(self, error_message: str) -> bool:
        """Send a freeform error message (e.g. scheduler-level crash)."""
        return self._send(error_message, is_error=True)

    # ------------------------------------------------------------------ internals

    def _should_send(self, success: bool) -> tuple[bool, str]:
        with self._lock:
            today = datetime.now(_BANGKOK).date().isoformat()
            now_hour = datetime.now(_BANGKOK).hour

            if not success:
                # First failure (or first after recovery) — always notify.
                # Consecutive failures within the suppress window — drop.
                if (
                    self._last_success is False
                    and self._last_failure_at is not None
                    and time.monotonic() - self._last_failure_at < self.failure_suppress_seconds
                ):
                    return False, "failure-suppressed"
                return True, "failure"
            if self._last_success is False:
                return True, "recovery"
            if self._last_success is None:
                # First run after startup — let the operator know we're alive.
                return True, "startup"
            if (
                now_hour == self.heartbeat_hour
                and self._last_heartbeat_date != today
            ):
                return True, "heartbeat"
            return False, "noop"

    def _format(self, result: dict, device_name: str, success: bool) -> str:
        bangkok_time = datetime.now(_BANGKOK).strftime("%H:%M")
        if not success:
            err = result.get("error") or result.get("message") or "unknown error"
            return f"🚨 ZK Sync 0/1 OK at {bangkok_time} - {device_name}: {err}"

        time_diff_before = result.get("time_diff_before", 0)
        time_diff_after = result.get("time_diff_after", 0)
        new_iso = result.get("new_time", "")
        # Try to extract HH:MM from the device's "new_time" timestamp.
        device_time = "??"
        if "T" in new_iso:
            try:
                device_time = new_iso.split("T")[1][:5]
            except Exception:
                pass
        return (
            f"✅ ZK Sync 1/1 OK at {bangkok_time} - "
            f"{device_name}:{device_time}({time_diff_before:.1f}s→{time_diff_after:.1f}s)"
        )

    def _send(self, message: str, is_error: bool) -> bool:
        if not self.webhook_url:
            logger.warning("[slack_notifier] no webhook configured; dropping message")
            return False
        text = f"<{self.mention_on_error}> {message}" if is_error else message
        payload = {
            "username": self.username,
            "channel": self.channel,
            "attachments": [
                {
                    "color": "#ff0000" if is_error else "#36a64f",
                    "title": f"{'❌' if is_error else '✅'} ZK Time Sync "
                    f"{'Error' if is_error else 'Notification'}",
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
