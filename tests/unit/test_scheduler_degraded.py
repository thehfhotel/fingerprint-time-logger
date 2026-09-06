"""
Unit tests for the scheduler's eviction-degraded Slack signal.

Covers section C of the zk-session-kick-alerting spec:
  * `_refresh_status_and_time` reads `zk_session.stream_kicks_in()`, stashes
    it on the cached `device_status` entry, and calls
    `slack_notifier.notify_degraded(kicks, 60)` once kicks reach
    `ZK_KICK_DEGRADED_THRESHOLD` — on the failure path AND both success
    paths (in-tolerance and resync).
  * A raising `notify_degraded` never breaks the job.

No DB, no network: `zk_session.get_status_and_time` / `stream_kicks_in` and
`slack_notifier.notify_sync_result` / `notify_degraded` are all monkeypatched.
"""

import asyncio
import importlib
import os

import pytest

from app.services import background_scheduler as scheduler_module
from app.services.background_scheduler import background_scheduler
from app.services.device_cache_service import device_cache_service


def _healthy_result():
    return {
        "status": {"connected": True},
        "time": {
            "success": True,
            "time_difference_seconds": 1.0,
            "device_time": "2026-09-05T21:00:00",
        },
        "users": None,
    }


def _failure_result():
    return {
        "status": {"connected": False},
        "time": {"success": False, "message": "device unreachable"},
        "users": None,
    }


@pytest.fixture(autouse=True)
def _stub_dependencies(monkeypatch):
    """Baseline stubs shared by every test: healthy result, no-op notifiers."""
    monkeypatch.setattr(
        scheduler_module.zk_session, "get_status_and_time", lambda: _healthy_result()
    )
    monkeypatch.setattr(
        scheduler_module.zk_session, "stream_kicks_in", lambda window_seconds=3600.0: 0,
        raising=False,
    )
    monkeypatch.setattr(
        scheduler_module.slack_notifier, "notify_sync_result", lambda *a, **k: False
    )
    monkeypatch.setattr(
        scheduler_module.slack_notifier, "notify_degraded", lambda *a, **k: False,
        raising=False,
    )
    yield


def _run_refresh():
    asyncio.run(background_scheduler._refresh_status_and_time())


class TestDegradedThreshold:
    def test_notify_degraded_called_at_threshold(self, monkeypatch):
        """kicks == threshold (3) fires notify_degraded(kicks, 60)."""
        calls = []
        monkeypatch.setattr(
            scheduler_module.zk_session, "stream_kicks_in", lambda window_seconds=3600.0: 3,
            raising=False,
        )
        monkeypatch.setattr(
            scheduler_module.slack_notifier,
            "notify_degraded",
            lambda *a, **k: calls.append((a, k)),
            raising=False,
        )

        _run_refresh()

        assert len(calls) == 1
        assert calls[0][0] == (3, 60)

    def test_notify_degraded_not_called_below_threshold(self, monkeypatch):
        """kicks == 2 (below the default threshold of 3) fires nothing."""
        calls = []
        monkeypatch.setattr(
            scheduler_module.zk_session, "stream_kicks_in", lambda window_seconds=3600.0: 2,
            raising=False,
        )
        monkeypatch.setattr(
            scheduler_module.slack_notifier,
            "notify_degraded",
            lambda *a, **k: calls.append((a, k)),
            raising=False,
        )

        _run_refresh()

        assert calls == []

    def test_notify_degraded_called_on_failure_path(self, monkeypatch):
        """Above-threshold kicks fire notify_degraded even when the time
        check itself fails (device unreachable)."""
        calls = []
        monkeypatch.setattr(
            scheduler_module.zk_session, "get_status_and_time", lambda: _failure_result()
        )
        monkeypatch.setattr(
            scheduler_module.zk_session, "stream_kicks_in", lambda window_seconds=3600.0: 4,
            raising=False,
        )
        monkeypatch.setattr(
            scheduler_module.slack_notifier,
            "notify_degraded",
            lambda *a, **k: calls.append((a, k)),
            raising=False,
        )

        _run_refresh()

        assert len(calls) == 1
        assert calls[0][0] == (4, 60)


class TestDeviceStatusCache:
    def test_stream_kicks_last_hour_stashed_on_cache(self, monkeypatch):
        monkeypatch.setattr(
            scheduler_module.zk_session, "stream_kicks_in", lambda window_seconds=3600.0: 5,
            raising=False,
        )

        _run_refresh()

        cached = device_cache_service.get_raw("device_status")
        assert cached is not None
        assert cached["stream_kicks_last_hour"] == 5


class TestNotifierNeverBreaksJob:
    def test_raising_notify_degraded_does_not_propagate(self, monkeypatch):
        monkeypatch.setattr(
            scheduler_module.zk_session, "stream_kicks_in", lambda window_seconds=3600.0: 10,
            raising=False,
        )

        def _boom(*a, **k):
            raise RuntimeError("webhook down")

        monkeypatch.setattr(
            scheduler_module.slack_notifier, "notify_degraded", _boom, raising=False
        )

        # Must not raise.
        _run_refresh()

        cached = device_cache_service.get_raw("device_status")
        assert cached["stream_kicks_last_hour"] == 10


class TestThresholdEnvVar:
    def test_threshold_reads_env_var(self, monkeypatch):
        """ZK_KICK_DEGRADED_THRESHOLD controls the module constant via
        importlib.reload; restore the module afterwards so later tests in
        this process see the default again."""
        monkeypatch.setenv("ZK_KICK_DEGRADED_THRESHOLD", "7")
        try:
            reloaded = importlib.reload(scheduler_module)
            assert reloaded._KICK_DEGRADED_THRESHOLD == 7
        finally:
            monkeypatch.delenv("ZK_KICK_DEGRADED_THRESHOLD", raising=False)
            importlib.reload(scheduler_module)
