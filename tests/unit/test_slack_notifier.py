"""
Tests for app/services/slack_notifier.py — confirmed-failure paging.

Background: the ZK device evicts our TCP session whenever another TCP
client connects, which used to look like a sync failure on the very next
5-min tick and paged the owner for something that self-heals within one
cycle. `page_after_failures` (default 2 = 10 min of real downtime)
requires a streak of consecutive failures before paging; a shorter blip
is silent; a page is always paired with a recovery message.

No network: `requests.post` is monkeypatched to a fake that records the
JSON payload and returns status_code 200. Time is controlled via the
notifier's overridable `_now_bangkok()` / `_monotonic()` methods rather
than patching the `datetime`/`time` modules.
"""

from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.slack_notifier import SlackSyncNotifier

_BANGKOK = ZoneInfo("Asia/Bangkok")


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class FakePoster:
    """Records every payload posted; never touches the network."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, json=None, timeout=None, headers=None):
        self.calls.append(json)
        return FakeResponse(200, "")


class Clock:
    """Drives both the notifier's Bangkok wall-clock and monotonic reads."""

    def __init__(self, start_monotonic=1000.0, start_dt=None):
        self.monotonic_value = start_monotonic
        self.dt = start_dt or datetime(2026, 9, 5, 10, 0, 0, tzinfo=_BANGKOK)

    def advance(self, seconds):
        self.monotonic_value += seconds
        self.dt = self.dt.fromtimestamp(self.dt.timestamp() + seconds, tz=_BANGKOK)

    def set_hour(self, hour, minute=0):
        self.dt = self.dt.replace(hour=hour, minute=minute)


def make_notifier(monkeypatch, clock: Clock, **kwargs):
    poster = FakePoster()
    monkeypatch.setattr("app.services.slack_notifier.requests.post", poster)
    kwargs.setdefault("webhook_url", "https://hooks.example/fake")
    kwargs.setdefault("heartbeat_hour", 23)  # off by default unless a test wants it
    notifier = SlackSyncNotifier(**kwargs)
    notifier._now_bangkok = lambda: clock.dt
    notifier._monotonic = lambda: clock.monotonic_value
    return notifier, poster


def fail(error="device unreachable"):
    return {"success": False, "error": error}


def ok(before=1.0, after=0.1):
    return {
        "success": True,
        "new_time": "2026-09-05T10:00:00",
        "time_diff_before": before,
        "time_diff_after": after,
    }


# --------------------------------------------------------------------- failure streak / paging

def test_single_failure_sends_nothing(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock)
    sent = notifier.notify_sync_result(fail())
    assert sent is False
    assert poster.calls == []


def test_second_consecutive_failure_pages_once(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock)
    clock.set_hour(14, 30)
    notifier.notify_sync_result(fail())
    sent = notifier.notify_sync_result(fail("device unreachable"))
    assert sent is True
    assert len(poster.calls) == 1
    text = poster.calls[0]["attachments"][0]["text"]
    assert notifier.mention_on_error in text
    assert "FAILED 2 consecutive checks since 14:30" in text
    assert "device unreachable" in text


def test_third_failure_within_suppress_window_sends_nothing_then_repages_after(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock, failure_suppress_seconds=1800)
    notifier.notify_sync_result(fail())
    notifier.notify_sync_result(fail())
    assert len(poster.calls) == 1

    clock.advance(60)
    sent = notifier.notify_sync_result(fail())
    assert sent is False
    assert len(poster.calls) == 1

    clock.advance(1800)
    sent = notifier.notify_sync_result(fail())
    assert sent is True
    assert len(poster.calls) == 2
    text = poster.calls[1]["attachments"][0]["text"]
    assert "FAILED 4 consecutive checks" in text


# --------------------------------------------------------------------- concurrency
# Regression coverage for the "commit before send" fix: the paging (and
# recovery, and degraded-note) decision now writes _paged/_last_failure_at/
# _last_degraded_at back to the notifier's state *inside* the same lock
# scope that made the decision, before the `_send` network call runs —
# previously that commit happened only after `_send` returned, leaving a
# window where two callers crossing the threshold at the same time could
# both observe the pre-send state and both page/recover for one outage.
# Not reachable via the real scheduler today (APScheduler's job runs with
# max_instances=1) but latent if any other caller (a manual "force sync"
# endpoint, a health check) ever calls these methods concurrently with it.
# A small sleep in the fake poster widens the send window so these tests
# would reliably have caught the pre-fix race.

def test_concurrent_failures_crossing_threshold_page_exactly_once(monkeypatch):
    import time as time_module

    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock)
    def slow_post(*args, **kwargs):
        time_module.sleep(0.05)
        return poster(*args, **kwargs)

    monkeypatch.setattr("app.services.slack_notifier.requests.post", slow_post)
    notifier.notify_sync_result(fail())  # streak=1, primes below default threshold of 2

    results = []

    def call():
        results.append(notifier.notify_sync_result(fail()))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert results.count(True) == 1, "exactly one of the two concurrent calls should page"
    assert len(poster.calls) == 1


def test_concurrent_blip_during_failed_recovery_send_still_pages_all_clear(monkeypatch):
    """Regression for the HIGH finding fixed by the `_commit_gen` generation
    counter: a recovery whose `_send` fails used to be permanently dropped
    if an unrelated sub-threshold failure blip raced in and incremented
    `_consecutive_failures` while the recovery's send was in flight — the
    old rollback guard (`_consecutive_failures == 0 and not _paged`) then
    read False and skipped the rollback, so the paged outage never got its
    all-clear. Exact interleave: page (streak reaches threshold) -> a real
    recovery whose fake `_send` returns False WHILE a concurrent
    sub-threshold failure blip increments the counter -> the recovery must
    roll back so a later success tick sends exactly one recovery message.
    Ordered deterministically with events, no real sleep."""
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock)

    # Reach the default page_after_failures=2 threshold.
    notifier.notify_sync_result(fail())
    notifier.notify_sync_result(fail())
    assert len(poster.calls) == 1, "page expected"

    blip_done = threading.Event()
    recovery_send_seen = threading.Event()
    real_send = notifier._send

    def send_with_interleave(message, is_error, mention=None, color=None, title=None):
        if not is_error and "recovered" in message:
            # This is the recovery's own network send. Let the concurrent
            # sub-threshold blip's _handle_failure call run to completion
            # (it must NOT bump _commit_gen) before simulating the
            # recovery POST itself failing.
            recovery_send_seen.set()
            assert blip_done.wait(timeout=5), "blip thread did not complete in time"
            return False
        return real_send(message, is_error, mention=mention, color=color, title=title)

    notifier._send = send_with_interleave

    def blip_thread_target():
        assert recovery_send_seen.wait(timeout=5), "recovery send never started"
        sent = notifier.notify_sync_result(fail())  # sub-threshold blip
        assert sent is False
        blip_done.set()

    blip_thread = threading.Thread(target=blip_thread_target)
    blip_thread.start()

    sent = notifier.notify_sync_result(ok(before=3.2, after=0.05))
    blip_thread.join(timeout=5)
    notifier._send = real_send  # restore for the follow-up check below

    assert sent is False, "the recovery's own send failed and must report False"
    assert len(poster.calls) == 1, "no recovery message should have reached Slack yet"

    # The paged outage must still get its all-clear: a later success tick
    # sends exactly one recovery message.
    sent2 = notifier.notify_sync_result(ok(before=3.2, after=0.05))
    assert sent2 is True
    assert len(poster.calls) == 2
    text = poster.calls[1]["attachments"][0]["text"]
    assert "recovered" in text


def test_concurrent_recoveries_after_page_send_exactly_once(monkeypatch):
    import time as time_module

    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock)
    notifier.notify_sync_result(fail())
    notifier.notify_sync_result(fail())  # streak=2, pages
    assert len(poster.calls) == 1

    def slow_post(*args, **kwargs):
        time_module.sleep(0.05)
        return poster(*args, **kwargs)

    monkeypatch.setattr("app.services.slack_notifier.requests.post", slow_post)

    results = []

    def call():
        results.append(notifier.notify_sync_result(ok()))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert results.count(True) == 1, "exactly one of the two concurrent calls should send recovery"
    assert len(poster.calls) == 2


def test_concurrent_first_successes_send_startup_once(monkeypatch):
    """_handle_normal_success now commits `_last_success = True` under the
    same lock scope that decides "startup", before the network `_send`
    call — regression coverage for the fourth (and final) "commit before
    send" site, closing the same race class already fixed for paging,
    recovery, and the degraded-note rate limit."""
    import time as time_module

    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock)

    def slow_post(*args, **kwargs):
        time_module.sleep(0.05)
        return poster(*args, **kwargs)

    monkeypatch.setattr("app.services.slack_notifier.requests.post", slow_post)

    results = []

    def call():
        results.append(notifier.notify_sync_result(ok()))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert results.count(True) == 1, "exactly one of the two concurrent first successes should post startup"
    assert len(poster.calls) == 1
    assert "1/1 OK" in poster.calls[0]["attachments"][0]["text"]


def test_concurrent_heartbeat_successes_send_once(monkeypatch):
    """Same race class at the heartbeat decision: two concurrent successes
    at the heartbeat hour must send exactly one heartbeat message, and a
    later success the same day must send nothing."""
    import time as time_module

    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock, heartbeat_hour=9)
    # Prime past startup: already succeeded once, heartbeat not yet sent today.
    notifier._last_success = True
    notifier._last_heartbeat_date = "2026-09-04"
    clock.set_hour(9, 0)

    def slow_post(*args, **kwargs):
        time_module.sleep(0.05)
        return poster(*args, **kwargs)

    monkeypatch.setattr("app.services.slack_notifier.requests.post", slow_post)

    results = []

    def call():
        results.append(notifier.notify_sync_result(ok()))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert results.count(True) == 1, "exactly one of the two concurrent heartbeat successes should post"
    assert len(poster.calls) == 1

    # A later success the same day sends nothing.
    sent = notifier.notify_sync_result(ok())
    assert sent is False
    assert len(poster.calls) == 1


def test_notify_degraded_concurrent_in_window_sends_once(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock, degraded_suppress_seconds=3600)

    send_started = threading.Event()
    release_send = threading.Event()
    real_send = notifier._send
    calls = {"n": 0}

    def send_with_delay(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            send_started.set()
            assert release_send.wait(timeout=5), "test did not release the delayed send in time"
            return False  # first send fails, so the retry path below can be exercised
        return real_send(*args, **kwargs)

    notifier._send = send_with_delay

    results = []

    def call():
        results.append(notifier.notify_degraded(3, 60))

    t1 = threading.Thread(target=call)
    t1.start()
    assert send_started.wait(timeout=5), "first notify_degraded never reached _send"

    # Second concurrent call, still inside the suppress window: must be
    # rejected by the rate-limit check (the first call already committed
    # `_last_degraded_at` before its send even started).
    sent2 = notifier.notify_degraded(4, 60)
    assert sent2 is False

    release_send.set()
    t1.join(timeout=5)

    notifier._send = real_send
    assert results == [False], "the delayed send failed, so the first call reports False"
    assert len(poster.calls) == 0, "no degraded message reached Slack yet"

    # Rollback let the rate limit clear: a later in-window call retries and sends.
    sent3 = notifier.notify_degraded(5, 60)
    assert sent3 is True
    assert len(poster.calls) == 1


# --------------------------------------------------------------------- recovery

def test_success_after_page_sends_one_recovery_and_resets_streak(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock)
    notifier.notify_sync_result(fail())
    notifier.notify_sync_result(fail())
    assert len(poster.calls) == 1

    clock.set_hour(15, 5)
    sent = notifier.notify_sync_result(ok(before=3.2, after=0.05))
    assert sent is True
    assert len(poster.calls) == 2
    text = poster.calls[1]["attachments"][0]["text"]
    assert "recovered" in text
    assert "after 2 failed checks" in text
    assert notifier.mention_on_error not in text

    # streak reset: a later single failure is silent again.
    sent = notifier.notify_sync_result(fail())
    assert sent is False
    assert len(poster.calls) == 2


def test_success_after_unpaged_blip_sends_nothing(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock, heartbeat_hour=9)
    clock.set_hour(14, 0)  # not the heartbeat hour
    notifier.notify_sync_result(ok())  # startup success, consumes the "first ever" slot
    assert len(poster.calls) == 1

    notifier.notify_sync_result(fail())  # unpaged blip
    assert len(poster.calls) == 1

    sent = notifier.notify_sync_result(ok())
    assert sent is False
    assert len(poster.calls) == 1


# --------------------------------------------------------------------- startup / heartbeat (unchanged behaviour)

def test_startup_posts_once_then_second_success_same_hour_silent(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock, heartbeat_hour=9)
    clock.set_hour(14, 0)
    sent = notifier.notify_sync_result(ok())
    assert sent is True
    assert len(poster.calls) == 1
    assert "1/1 OK" in poster.calls[0]["attachments"][0]["text"]

    sent = notifier.notify_sync_result(ok())
    assert sent is False
    assert len(poster.calls) == 1


def test_heartbeat_posts_once_per_day(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock, heartbeat_hour=9)
    clock.set_hour(14, 0)
    notifier.notify_sync_result(ok())  # startup post
    assert len(poster.calls) == 1

    clock.set_hour(9, 0)
    sent = notifier.notify_sync_result(ok())
    assert sent is True
    assert len(poster.calls) == 2

    clock.set_hour(9, 30)
    sent = notifier.notify_sync_result(ok())
    assert sent is False
    assert len(poster.calls) == 2

    clock.advance(24 * 3600)
    clock.set_hour(9, 0)
    sent = notifier.notify_sync_result(ok())
    assert sent is True
    assert len(poster.calls) == 3


# --------------------------------------------------------------------- page_after_failures=1 (legacy behaviour)

def test_page_after_failures_one_restores_page_on_first_failure(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock, page_after_failures=1)
    clock.set_hour(11, 0)
    sent = notifier.notify_sync_result(fail("timeout"))
    assert sent is True
    assert len(poster.calls) == 1
    assert "FAILED 1 consecutive checks since 11:00" in poster.calls[0]["attachments"][0]["text"]


# --------------------------------------------------------------------- notify_degraded

def test_notify_degraded_posts_once_then_rate_limited_then_again_after_window(monkeypatch):
    clock = Clock()
    notifier, poster = make_notifier(monkeypatch, clock, degraded_suppress_seconds=3600)

    sent = notifier.notify_degraded(3, 60)
    assert sent is True
    assert len(poster.calls) == 1
    attachment = poster.calls[0]["attachments"][0]
    assert attachment["color"] == "#ffa500"
    assert "Degraded" in attachment["title"]
    assert "evicted 3×" in attachment["text"]
    assert notifier.mention_on_error not in attachment["text"]

    clock.advance(1000)
    sent = notifier.notify_degraded(4, 60)
    assert sent is False
    assert len(poster.calls) == 1

    clock.advance(3600)
    sent = notifier.notify_degraded(5, 60)
    assert sent is True
    assert len(poster.calls) == 2


# --------------------------------------------------------------------- env default / clamping

def test_env_default_page_after_failures(monkeypatch):
    monkeypatch.setenv("ZK_SYNC_PAGE_AFTER_FAILURES", "3")
    notifier = SlackSyncNotifier(webhook_url="https://hooks.example/fake")
    assert notifier.page_after_failures == 3


def test_page_after_failures_clamps_to_minimum_one(monkeypatch):
    notifier = SlackSyncNotifier(webhook_url="https://hooks.example/fake", page_after_failures=0)
    assert notifier.page_after_failures == 1

    notifier2 = SlackSyncNotifier(webhook_url="https://hooks.example/fake", page_after_failures=-5)
    assert notifier2.page_after_failures == 1

    monkeypatch.setenv("ZK_SYNC_PAGE_AFTER_FAILURES", "not-a-number")
    notifier3 = SlackSyncNotifier(webhook_url="https://hooks.example/fake")
    assert notifier3.page_after_failures >= 1
