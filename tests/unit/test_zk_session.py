"""
Tests for app/services/zk_session.py.

Invariants:
  1. submit() runs ops against the live conn in the session thread.
  2. live_capture yields are routed to _handle_punch and produce DB inserts
     + broadcast messages.
  3. Reconnect-after-error happens with backoff.
  4. shutdown() exits the thread promptly even mid-stream.
  5. submit() coexists with streaming — it doesn't deadlock.
"""

from __future__ import annotations

import asyncio
import threading
import time as _time
from datetime import datetime, timedelta
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.services import zk_session as zk_session_module
from app.services.zk_session import ZkSession
from app.models.models import AttendanceRecord, Device, Employee
from tests.fixtures.zkteco_simulator import MockZKConnection, ZKTecoSimulatorFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_session():
    """Build a fresh ZkSession (don't reuse the module singleton across tests)."""
    return ZkSession(host="127.0.0.1", port=4370, password=0, timeout=1)


def _bind_zk_session_db_to(test_engine):
    """Make `get_db` inside zk_session use the test engine.

    zk_session imports `from app.core.database import get_db` at call time
    (inside _handle_punch and _catch_up), so we patch the source.
    """
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def fake_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    return patch("app.core.database.get_db", fake_get_db)


def _seed_active_device_and_employee(test_db, badge="0001"):
    device = Device(name="Test K40", ip_address="127.0.0.1", port=4370, password=0, is_active=True)
    test_db.add(device)
    test_db.flush()
    emp = Employee(badge_number=badge, english_name="Alice", display_name="Alice")
    test_db.add(emp)
    test_db.commit()
    test_db.refresh(device)
    test_db.refresh(emp)
    return device, emp


# ---------------------------------------------------------------------------
# submit() behavior
# ---------------------------------------------------------------------------


def _make_live_conn():
    """Build a mocked conn that's already 'connected' (skips connect handshake)."""
    conn = MockZKConnection(ZKTecoSimulatorFactory.create_healthy_device())
    conn.simulator.connect()
    conn._connected = True
    conn._live_capture_idle_override = 0.01
    return conn


def _stub_catch_up(self, _conn):
    """Skip DB-dependent catch-up in tests that don't need it."""
    return 0


def test_submit_runs_op_and_returns_result():
    """submit() executes the closure against the live conn and returns its value."""
    session = _new_session()
    mock_conn = _make_live_conn()

    with patch.object(zk_session_module, "ZK") as mock_zk_ctor, \
         patch.object(zk_session_module.ZkSession, "_catch_up", _stub_catch_up):
        zk_instance = MagicMock()
        zk_instance.connect.return_value = mock_conn
        mock_zk_ctor.return_value = zk_instance

        loop = asyncio.new_event_loop()

        async def noop_broadcast(_msg):
            return None

        session.start(loop, noop_broadcast)
        try:
            result = session.submit(lambda conn: conn.get_firmware_version(), timeout=5)
            assert result == "6.60.00"
        finally:
            session.shutdown(wait=True)
            loop.close()


def test_submit_propagates_op_exception():
    session = _new_session()
    mock_conn = _make_live_conn()

    with patch.object(zk_session_module, "ZK") as mock_zk_ctor, \
         patch.object(zk_session_module.ZkSession, "_catch_up", _stub_catch_up):
        zk_instance = MagicMock()
        zk_instance.connect.return_value = mock_conn
        mock_zk_ctor.return_value = zk_instance

        loop = asyncio.new_event_loop()

        async def noop_broadcast(_msg):
            return None

        session.start(loop, noop_broadcast)
        try:
            def boom(_conn):
                raise ValueError("nope")

            with pytest.raises(ValueError, match="nope"):
                session.submit(boom, timeout=5)
        finally:
            session.shutdown(wait=True)
            loop.close()


# ---------------------------------------------------------------------------
# _handle_punch insert + broadcast
# ---------------------------------------------------------------------------


def test_queued_punch_inserts_record_and_broadcasts(test_engine, test_db):
    device, employee = _seed_active_device_and_employee(test_db, badge="0001")
    bangkok_ts = datetime(2026, 5, 14, 9, 0, 0)

    mock_conn = _make_live_conn()
    mock_conn.queue_punch(badge_number="0001", timestamp=bangkok_ts, punch_type=0, status=0)

    broadcasts: List[dict] = []
    broadcasts_lock = threading.Lock()
    broadcast_event = threading.Event()

    async def capture(msg):
        with broadcasts_lock:
            broadcasts.append(msg)
        broadcast_event.set()

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    session = _new_session()

    with _bind_zk_session_db_to(test_engine), patch.object(zk_session_module, "ZK") as mock_zk_ctor:
        zk_instance = MagicMock()
        zk_instance.connect.return_value = mock_conn
        mock_zk_ctor.return_value = zk_instance

        session.start(loop, capture)
        try:
            assert broadcast_event.wait(timeout=5), "broadcast never fired"
        finally:
            session.shutdown(wait=True)
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=3)
            loop.close()

    # The punch should have inserted exactly one row.
    TestSession = sessionmaker(bind=test_engine)
    db = TestSession()
    try:
        rows = db.query(AttendanceRecord).filter(
            AttendanceRecord.employee_badge_number == "0001"
        ).all()
        assert len(rows) == 1
        # Bangkok 09:00 → UTC 02:00.
        assert rows[0].timestamp == datetime(2026, 5, 14, 2, 0, 0)
        assert rows[0].punch_type == 0
    finally:
        db.close()

    with broadcasts_lock:
        assert len(broadcasts) == 1
        msg = broadcasts[0]
    assert msg["type"] == "attendance_realtime"
    assert msg["badge_number"] == "0001"
    assert msg["display_name"] == "Alice"
    assert msg["punch_type"] == 0


# ---------------------------------------------------------------------------
# Reconnect on error
# ---------------------------------------------------------------------------


def test_reconnects_after_loop_error():
    """When connect raises once, the daemon thread retries (no sleep in test)."""
    session = _new_session()

    attempts = {"n": 0}
    good_conn = _make_live_conn()

    def fake_connect():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("first attempt fails")
        return good_conn

    with patch.object(zk_session_module, "ZK") as mock_zk_ctor, \
         patch("threading.Event.wait", return_value=False):
        zk_instance = MagicMock()
        zk_instance.connect.side_effect = fake_connect
        mock_zk_ctor.return_value = zk_instance

        loop = asyncio.new_event_loop()

        async def noop_broadcast(_msg):
            return None

        session.start(loop, noop_broadcast)
        try:
            deadline = _time.monotonic() + 5
            while attempts["n"] < 2 and _time.monotonic() < deadline:
                _time.sleep(0.05)
            assert attempts["n"] >= 2, f"did not reconnect; attempts={attempts['n']}"
        finally:
            session.shutdown(wait=False)
            # Force-exit live_capture to let the thread quit.
            good_conn.end_live_capture = True
            loop.close()


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


def test_shutdown_exits_thread_within_5s():
    session = _new_session()
    mock_conn = _make_live_conn()
    mock_conn._live_capture_idle_override = 0.05

    with patch.object(zk_session_module, "ZK") as mock_zk_ctor:
        zk_instance = MagicMock()
        zk_instance.connect.return_value = mock_conn
        mock_zk_ctor.return_value = zk_instance

        loop = asyncio.new_event_loop()

        async def noop_broadcast(_msg):
            return None

        session.start(loop, noop_broadcast)
        _time.sleep(0.2)
        start = _time.monotonic()
        session.shutdown(wait=True)
        elapsed = _time.monotonic() - start
        loop.close()
        assert elapsed < 5.0, f"shutdown took {elapsed:.2f}s"
        assert session._thread is not None and not session._thread.is_alive()


# ---------------------------------------------------------------------------
# Coexistence: submit while live_capture is yielding
# ---------------------------------------------------------------------------


def test_submit_completes_during_streaming():
    session = _new_session()
    mock_conn = _make_live_conn()
    mock_conn._live_capture_idle_override = 0.05

    with patch.object(zk_session_module, "ZK") as mock_zk_ctor, \
         patch.object(zk_session_module.ZkSession, "_catch_up", _stub_catch_up):
        zk_instance = MagicMock()
        zk_instance.connect.return_value = mock_conn
        mock_zk_ctor.return_value = zk_instance

        loop = asyncio.new_event_loop()

        async def noop_broadcast(_msg):
            return None

        session.start(loop, noop_broadcast)
        try:
            # Give the thread a moment to enter live_capture.
            _time.sleep(0.1)
            result = session.submit(lambda conn: conn.get_firmware_version(), timeout=5)
            assert result == "6.60.00"
        finally:
            session.shutdown(wait=True)
            loop.close()
