"""
Tests for app/services/zk_client.py.

The key invariants under test:
  1. Public methods acquire and release the module-level lock.
  2. Concurrent callers never produce overlapping connect/disconnect brackets
     (this is the property whose absence in the old design caused
     `TCP packet invalid`).
  3. Retryable errors trigger a retry; non-retryable errors propagate.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.services import zk_client as zk_module
from app.services.zk_client import ZkClient, _is_retryable
from zk.exception import ZKNetworkError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeConn:
    """
    Stand-in for the connection object pyzk's `ZK.connect()` returns.

    Records every connect/disconnect in `events` so tests can assert
    bracket ordering. Optionally raises on a specific method to exercise
    retry/error paths.
    """

    def __init__(
        self,
        events: List[tuple],
        device_time: Optional[datetime] = None,
        attendance: Optional[list] = None,
        raise_on: Optional[str] = None,
        raise_exc: Optional[Exception] = None,
    ):
        self.events = events
        self.device_time = device_time or datetime(2024, 1, 1, 12, 0, 0)
        self.attendance = attendance or []
        self._connected = False
        self._raise_on = raise_on
        self._raise_exc = raise_exc or ZKNetworkError("TCP packet invalid")

    # pyzk's `ZK.connect()` is what hands the conn back — see _make_zk_factory.
    def _connect(self):
        self._connected = True
        self.events.append(("connect", time.monotonic()))
        return self

    def disconnect(self):
        if self._connected:
            self.events.append(("disconnect", time.monotonic()))
            self._connected = False

    def _maybe_raise(self, name: str):
        if self._raise_on == name:
            raise self._raise_exc

    def get_firmware_version(self):
        self._maybe_raise("get_firmware_version")
        return "Ver 6.60 Jun 18 2018"

    def get_time(self):
        self._maybe_raise("get_time")
        return self.device_time

    def set_time(self, target):
        self._maybe_raise("set_time")
        self.device_time = target

    def get_attendance(self):
        self._maybe_raise("get_attendance")
        return self.attendance

    def get_users(self):
        self._maybe_raise("get_users")
        return []


def _make_zk_factory(conn_or_factory):
    """
    Build a patch target that mimics `zk.ZK(...)` returning an object whose
    `.connect()` yields our FakeConn. Accepts either a fixed FakeConn or a
    zero-arg callable that returns one (so each `ZK(...)` constructor can
    produce a fresh conn — needed for retry tests).
    """

    def factory(*args, **kwargs):
        conn = conn_or_factory() if callable(conn_or_factory) else conn_or_factory
        zk_instance = MagicMock()
        zk_instance.connect.side_effect = conn._connect
        return zk_instance

    return factory


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------


def test_is_retryable_recognizes_tcp_packet_invalid():
    assert _is_retryable(Exception("TCP packet invalid"))
    assert _is_retryable(ZKNetworkError("anything"))
    assert _is_retryable(OSError("connection reset"))


def test_is_retryable_rejects_value_error():
    assert not _is_retryable(ValueError("bad input"))


# ---------------------------------------------------------------------------
# Basic happy-path operations
# ---------------------------------------------------------------------------


def test_get_status_returns_firmware_when_connected():
    events: List[tuple] = []
    conn = FakeConn(events)
    with patch.object(zk_module, "ZK", _make_zk_factory(conn)):
        client = ZkClient(max_retries=1)
        status = client.get_status()
    assert status["connected"] is True
    assert status["firmware"] == "Ver 6.60 Jun 18 2018"
    # Connect happens before disconnect, and there's exactly one of each.
    kinds = [e[0] for e in events]
    assert kinds == ["connect", "disconnect"]


def test_get_status_returns_error_on_connect_failure():
    def boom_factory():
        c = FakeConn([])

        def fail():
            raise ZKNetworkError("can't reach device")

        c._connect = fail
        return c

    with patch.object(zk_module, "ZK", _make_zk_factory(boom_factory)):
        client = ZkClient(max_retries=1)
        status = client.get_status()
    assert status["connected"] is False
    assert "can't reach device" in status["error"]


def test_sync_time_reads_writes_and_verifies():
    events: List[tuple] = []
    conn = FakeConn(events, device_time=datetime(2024, 1, 1, 11, 59, 0))
    with patch.object(zk_module, "ZK", _make_zk_factory(conn)):
        client = ZkClient(max_retries=1)
        result = client.sync_time()
    assert result["success"] is True
    # After set_time, the conn's device_time reflects "now" — drift should be small.
    assert result["time_diff_after"] < 5.0
    assert result["time_diff_before"] >= 0
    assert [e[0] for e in events] == ["connect", "disconnect"]


def test_pull_attendance_filters_by_since_timestamp():
    now = datetime.now()
    rec_old = MagicMock(timestamp=now - timedelta(hours=2), user_id=1, punch=0, status=0)
    rec_new = MagicMock(timestamp=now - timedelta(minutes=5), user_id=2, punch=1, status=0)
    rec_invalid_year = MagicMock(timestamp=datetime(2009, 1, 1), user_id=3, punch=0, status=0)
    conn = FakeConn([], attendance=[rec_old, rec_new, rec_invalid_year])
    with patch.object(zk_module, "ZK", _make_zk_factory(conn)):
        client = ZkClient(max_retries=1)
        out = client.pull_attendance(since_timestamp=now - timedelta(hours=1))
    user_ids = [r["user_id"] for r in out]
    assert user_ids == ["2"]  # old + invalid_year filtered out


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------


def test_session_retries_on_zknetworkerror_then_succeeds():
    """First connect attempt raises TCP packet invalid; second succeeds."""
    events: List[tuple] = []
    attempts = {"n": 0}

    def factory():
        c = FakeConn(events)
        orig_connect = c._connect

        def maybe_fail():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ZKNetworkError("TCP packet invalid")
            return orig_connect()

        c._connect = maybe_fail
        return c

    with patch.object(zk_module, "ZK", _make_zk_factory(factory)):
        client = ZkClient(max_retries=3, retry_backoff_seconds=0)  # no sleep in tests
        status = client.get_status()
    assert status["connected"] is True
    assert attempts["n"] == 2  # one fail, one success


def test_session_does_not_retry_on_non_retryable_error_inside_get_users():
    """ValueError is not retryable — pull_attendance should bubble it."""
    conn = FakeConn([], raise_on="get_users", raise_exc=ValueError("bad input"))
    with patch.object(zk_module, "ZK", _make_zk_factory(conn)):
        client = ZkClient(max_retries=3, retry_backoff_seconds=0)
        with pytest.raises(ValueError, match="bad input"):
            client.get_users()


def test_session_exhausts_retries_then_raises():
    """Every attempt raises a retryable error; after max_retries we get it back."""

    def factory():
        c = FakeConn([])

        def always_fail():
            raise ZKNetworkError("TCP packet invalid")

        c._connect = always_fail
        return c

    with patch.object(zk_module, "ZK", _make_zk_factory(factory)):
        client = ZkClient(max_retries=2, retry_backoff_seconds=0)
        # get_status swallows the exception and returns a dict.
        status = client.get_status()
    assert status["connected"] is False
    assert "TCP packet invalid" in status["error"]


# ---------------------------------------------------------------------------
# Lock invariant — the redesign's reason to exist
# ---------------------------------------------------------------------------


def test_concurrent_calls_never_overlap_on_the_wire():
    """
    Spawn N threads, each calling a different ZkClient method. Each fake
    connection records its connect/disconnect timestamps. The invariant:
    when sorted by time, events must alternate connect, disconnect, connect,
    disconnect, ... — never two connects in a row.
    """
    events: List[tuple] = []
    events_lock = threading.Lock()

    def make_conn():
        c = FakeConn([], device_time=datetime(2024, 1, 1, 12, 0, 0))
        orig_connect = c._connect
        orig_disconnect = c.disconnect

        def slow_connect():
            r = orig_connect()
            time.sleep(0.02)  # widen the window where overlap could happen
            with events_lock:
                events.append(("connect", time.monotonic()))
            return r

        def slow_disconnect():
            time.sleep(0.02)
            with events_lock:
                events.append(("disconnect", time.monotonic()))
            orig_disconnect()

        c._connect = slow_connect
        c.disconnect = slow_disconnect
        c.events = []  # we use the outer list instead
        return c

    methods_run = []

    def worker(method_name: str):
        client = ZkClient(max_retries=1, retry_backoff_seconds=0)
        method = getattr(client, method_name)
        result = method()
        methods_run.append((method_name, result))

    with patch.object(zk_module, "ZK", _make_zk_factory(make_conn)):
        threads = [
            threading.Thread(target=worker, args=("get_status",)),
            threading.Thread(target=worker, args=("get_time",)),
            threading.Thread(target=worker, args=("get_status",)),
            threading.Thread(target=worker, args=("sync_time",)),
            threading.Thread(target=worker, args=("get_status",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

    # Sort by timestamp and verify strict alternation.
    sorted_events = sorted(events, key=lambda e: e[1])
    expected = ["connect", "disconnect"] * (len(sorted_events) // 2)
    kinds = [e[0] for e in sorted_events]
    assert kinds == expected, f"events did not alternate: {kinds}"
    assert len(methods_run) == 5
