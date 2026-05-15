"""
ZkSession — single long-lived session that streams attendance via pyzk's
live_capture and serializes one-shot ops on the same connection.

One daemon thread owns the pyzk connection. live_capture(new_timeout=2) is
the steady state; between yields the thread drains a queue of submitted
ops (status checks, time sync, manual catch-up) against the same conn so
the K40's single-TCP-session limit is respected.

External callers MUST go through `zk_session.submit(...)` or the
module-level convenience wrappers. No other code path may import pyzk.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine, List, Optional, TypeVar

from zk import ZK
from zk.exception import ZKError, ZKErrorConnection, ZKNetworkError

logger = logging.getLogger(__name__)

T = TypeVar("T")

_BANGKOK_TZ = timezone(timedelta(hours=7))
_LIVE_CAPTURE_IDLE_SECONDS = float(os.getenv("ZK_LIVE_CAPTURE_TIMEOUT", "2"))
_BACKOFF_MIN_SECONDS = 5.0
_BACKOFF_MAX_SECONDS = 60.0


def _bangkok_naive_to_utc_naive(ts: datetime) -> datetime:
    """Device emits Bangkok-naive timestamps; DB stores UTC-naive."""
    return ts.replace(tzinfo=_BANGKOK_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _utc_naive_to_bangkok_naive(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc).astimezone(_BANGKOK_TZ).replace(tzinfo=None)


class _OpEnvelope:
    __slots__ = ("op", "future")

    def __init__(self, op: Callable[[Any], Any], future: "Future"):
        self.op = op
        self.future = future


class ZkSession:
    """Long-lived ZKTeco session with queued one-shot op execution."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[int] = None,
        timeout: Optional[int] = None,
    ):
        self.host = host or os.getenv("ZKTECO_HOST", "192.168.100.209")
        self.port = int(port if port is not None else os.getenv("ZKTECO_PORT", "4370"))
        self.password = int(
            password if password is not None else os.getenv("ZKTECO_PASSWORD", "0")
        )
        self.timeout = int(timeout if timeout is not None else os.getenv("DEVICE_TIMEOUT", "5"))
        self.max_retries = int(os.getenv("DEVICE_MAX_RETRIES", "3"))

        self._op_queue: "queue.Queue[_OpEnvelope]" = queue.Queue()
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._broadcast: Optional[Callable[[dict], Coroutine]] = None
        self._started = False

    # ------------------------------------------------------------------ lifecycle

    def start(
        self,
        main_loop: asyncio.AbstractEventLoop,
        broadcast: Callable[[dict], Coroutine],
    ) -> None:
        if self._started:
            logger.warning("[zk_session] start() called but already running")
            return
        self._main_loop = main_loop
        self._broadcast = broadcast
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._run, name="zk-session", daemon=True
        )
        self._thread.start()
        self._started = True
        logger.info("[zk_session] daemon thread started")

    def shutdown(self, wait: bool = True) -> None:
        if not self._started:
            return
        logger.info("[zk_session] shutdown requested")
        self._shutdown.set()
        if wait and self._thread is not None:
            self._thread.join(timeout=10)
        self._started = False

    # ------------------------------------------------------------------ public ops

    def submit(self, op: Callable[[Any], T], timeout: float = 30.0) -> T:
        """Run op against the live conn inside the session thread. Blocks."""
        if not self._started:
            # Allow synchronous fallback only when the session thread isn't running
            # (tests, CLI invocations). Open a one-shot connection.
            return self._run_op_one_shot(op)
        future: "Future[T]" = Future()
        self._op_queue.put(_OpEnvelope(op, future))
        return future.result(timeout=timeout)

    def _run_op_one_shot(self, op: Callable[[Any], T]) -> T:
        zk = ZK(
            self.host,
            port=self.port,
            timeout=self.timeout,
            password=self.password,
            force_udp=False,
            ommit_ping=True,
        )
        conn = zk.connect()
        if not conn:
            raise ZKErrorConnection(f"connect() returned None for {self.host}:{self.port}")
        try:
            return op(conn)
        finally:
            try:
                conn.disconnect()
            except Exception:
                pass

    # ------------------------------------------------------------------ session thread

    def _connect(self) -> Any:
        zk = ZK(
            self.host,
            port=self.port,
            timeout=self.timeout,
            password=self.password,
            force_udp=False,
            ommit_ping=True,
        )
        conn = zk.connect()
        if not conn:
            raise ZKErrorConnection(f"connect() returned None for {self.host}:{self.port}")
        return conn

    def _run(self) -> None:
        import traceback
        backoff = _BACKOFF_MIN_SECONDS
        # catch_up does a full `get_attendance()` (~30s on a device with
        # thousands of records). Running it every cycle starves the op
        # queue and times out periodic jobs. Only catch up after a
        # disruption; the 30-min import_attendance backstop covers
        # steady-state gap recovery.
        needs_catch_up = True
        # Startup grace: K40 firmware doesn't immediately release the
        # previous TCP session on disconnect. A fresh container that
        # connects within ~1-2s of the prior container's shutdown gets
        # "timed out" on its first command because the device still
        # thinks the old session is alive. Wait 2s before the first
        # connect to give the device time to drop the prior session.
        self._shutdown.wait(2.0)
        while not self._shutdown.is_set():
            stream_conn = None
            try:
                stream_conn = self._connect_with_log("stream")
                backoff = _BACKOFF_MIN_SECONDS
            except BaseException as exc:
                # Couldn't even connect — this is the only failure mode that
                # poisons queued ops, because we can't run them anywhere.
                tb = traceback.format_exc(limit=4)
                logger.error(f"[zk_session] connect failed: {exc!r}\n{tb}")
                self._fail_queued_ops(exc)
                needs_catch_up = True
                if self._shutdown.is_set():
                    break
                logger.warning(f"[zk_session] reconnecting in {backoff:.0f}s")
                if self._shutdown.wait(backoff):
                    break
                backoff = min(backoff * 2, _BACKOFF_MAX_SECONDS)
                continue

            # Phase A — streaming session. live_capture owns this conn.
            # Catch_up and stream errors are isolated to this conn; queued
            # ops still get a clean shot on phase B's fresh conn.
            if needs_catch_up:
                try:
                    inserted = self._catch_up(stream_conn)
                    logger.info(f"[zk_session] catch_up inserted={inserted}")
                    needs_catch_up = False
                except BaseException as exc:
                    logger.warning(
                        f"[zk_session] catch_up failed (will retry next cycle): {exc!r}"
                    )
            self._stream(stream_conn)
            self._disconnect_quiet(stream_conn, "stream")
            if self._shutdown.is_set():
                break

            # Phase B — ops session on a fresh conn. pyzk's live_capture
            # cleanup is not bit-clean (leftover event bytes confuse the
            # next command's ACK read — "broken ACK N /M"), so we never
            # multiplex commands with streaming on the same socket. Brief
            # pause: K40 firmware is slow to release the previous session;
            # back-to-back connects can have the device drop the first
            # command on the floor and we'd see a "timed out" socket error.
            if not self._op_queue.empty():
                time.sleep(1.0)
                try:
                    op_conn = self._connect_with_log("ops")
                except Exception as exc:
                    logger.warning(
                        f"[zk_session] ops connect failed (queue persists): {exc!r}"
                    )
                    needs_catch_up = True
                    continue
                try:
                    drained = self._drain_op_queue(op_conn)
                    if drained:
                        logger.info(f"[zk_session] drained {drained} ops")
                finally:
                    self._disconnect_quiet(op_conn, "ops")
        logger.info("[zk_session] thread exiting")

    def _connect_with_log(self, phase: str) -> Any:
        logger.info(f"[zk_session.{phase}] connecting to {self.host}:{self.port}")
        conn = self._connect()
        logger.info(f"[zk_session.{phase}] connected")
        return conn

    def _disconnect_quiet(self, conn: Any, phase: str) -> None:
        try:
            conn.disconnect()
        except Exception as disc_exc:
            logger.warning(f"[zk_session.{phase}] disconnect error: {disc_exc}")

    def _stream(self, conn: Any) -> None:
        logger.info("[zk_session] streaming via live_capture")
        try:
            for event in conn.live_capture(new_timeout=_LIVE_CAPTURE_IDLE_SECONDS):
                if event is not None:
                    try:
                        self._handle_punch(event)
                    except Exception as punch_exc:
                        logger.error(f"[zk_session] handle_punch error: {punch_exc!r}")
                if self._should_break(conn):
                    conn.end_live_capture = True
        except Exception as exc:
            # pyzk's live_capture wraps the socket directly; its cleanup
            # (`reg_event(0)`, `cancel_capture()`) can raise when framing
            # gets out of sync — e.g. "cant' reg events 0" when the device
            # returns a malformed ACK. The streaming session is ending
            # anyway; swallow so the outer loop proceeds to the ops phase
            # on a fresh conn. Don't poison queued ops with this error.
            logger.warning(f"[zk_session] live_capture error (continuing): {exc!r}")

    def _should_break(self, conn: Any) -> bool:
        return self._shutdown.is_set() or not self._op_queue.empty()

    def _drain_op_queue(self, conn: Any) -> int:
        count = 0
        while True:
            try:
                envelope = self._op_queue.get_nowait()
            except queue.Empty:
                return count
            try:
                result = envelope.op(conn)
                envelope.future.set_result(result)
            except BaseException as exc:
                envelope.future.set_exception(exc)
            count += 1

    def _fail_queued_ops(self, exc: BaseException) -> None:
        while True:
            try:
                envelope = self._op_queue.get_nowait()
            except queue.Empty:
                return
            if not envelope.future.done():
                envelope.future.set_exception(exc)

    # ------------------------------------------------------------------ punches

    def _handle_punch(self, att: Any) -> None:
        from app.core.database import get_db
        from app.models.models import AttendanceRecord, Device, Employee
        from app.services.attendance_service import attendance_service
        from app.services.device_cache_service import device_cache_service

        bangkok_ts = att.timestamp
        utc_ts = _bangkok_naive_to_utc_naive(bangkok_ts)
        badge_number = str(att.user_id)
        punch_type = att.punch
        status = att.status

        db = next(get_db())
        try:
            employee = (
                db.query(Employee)
                .filter(Employee.badge_number == badge_number)
                .first()
            )
            if employee is None:
                logger.warning(
                    f"[zk_session.handle_punch] unknown badge_number={badge_number}; skipping"
                )
                return

            device = db.query(Device).filter(Device.is_active == True).first()
            if device is None:
                logger.warning("[zk_session.handle_punch] no active device; skipping")
                return

            exists = (
                db.query(AttendanceRecord)
                .filter(
                    AttendanceRecord.employee_badge_number == badge_number,
                    AttendanceRecord.timestamp == utc_ts,
                )
                .first()
            )
            if exists:
                logger.debug(
                    f"[zk_session.handle_punch] duplicate badge={badge_number} ts={utc_ts}"
                )
                return

            db.add(
                AttendanceRecord(
                    employee_badge_number=badge_number,
                    device_id=device.id,
                    timestamp=utc_ts,
                    punch_type=punch_type,
                    status=status,
                    sync_status="synced",
                )
            )
            device.last_sync = datetime.now(timezone.utc)
            db.commit()

            display_name = employee.english_name or employee.display_name
            logger.info(
                f"[zk_session.handle_punch] inserted badge={badge_number} "
                f"name={display_name} ts={utc_ts.isoformat()} punch={punch_type}"
            )
        finally:
            db.close()

        try:
            summary = attendance_service.get_attendance_summary()
            device_cache_service.set("attendance_summary", summary)
        except Exception as cache_exc:
            logger.warning(f"[zk_session.handle_punch] summary refresh failed: {cache_exc}")
            summary = None

        self._broadcast_realtime(
            badge_number=badge_number,
            display_name=display_name,
            utc_ts=utc_ts,
            punch_type=punch_type,
            summary=summary,
        )

    def _broadcast_realtime(
        self,
        badge_number: str,
        display_name: str,
        utc_ts: datetime,
        punch_type: int,
        summary: Optional[dict],
    ) -> None:
        if self._broadcast is None or self._main_loop is None:
            return
        message = {
            "type": "attendance_realtime",
            "badge_number": badge_number,
            "display_name": display_name,
            "timestamp": utc_ts.isoformat(),
            "punch_type": punch_type,
            "data": summary,
            "synced_records": 1,
            "message": f"บันทึกใหม่: {display_name}",
        }
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._main_loop)
        except RuntimeError as exc:
            logger.warning(f"[zk_session.broadcast] event loop unavailable: {exc}")

    # ------------------------------------------------------------------ catch-up

    def _catch_up(self, conn: Any) -> int:
        from app.core.database import get_db
        from app.models.models import AttendanceRecord, Device, Employee
        from sqlalchemy import func

        db = next(get_db())
        try:
            device = db.query(Device).filter(Device.is_active == True).first()
            if device is None:
                logger.warning("[zk_session.catch_up] no active device configured")
                return 0
            watermark_utc = db.query(func.max(AttendanceRecord.timestamp)).scalar()
            device_id = device.id
        finally:
            db.close()

        watermark_bangkok = None
        if watermark_utc is not None:
            watermark_bangkok = _utc_naive_to_bangkok_naive(watermark_utc)

        records = conn.get_attendance()
        current_year = datetime.now().year
        current_date = datetime.now().date()

        inserted = 0
        db = next(get_db())
        try:
            for record in records:
                ts = record.timestamp
                if ts.year < 2010 or ts.year > current_year or ts.date() > current_date:
                    continue
                if watermark_bangkok is not None and ts <= watermark_bangkok:
                    continue

                badge_number = str(record.user_id)
                utc_ts = _bangkok_naive_to_utc_naive(ts)

                employee = (
                    db.query(Employee)
                    .filter(Employee.badge_number == badge_number)
                    .first()
                )
                if employee is None:
                    logger.warning(
                        f"[zk_session.catch_up] unknown badge_number={badge_number}; skipping"
                    )
                    continue

                exists = (
                    db.query(AttendanceRecord)
                    .filter(
                        AttendanceRecord.employee_badge_number == badge_number,
                        AttendanceRecord.timestamp == utc_ts,
                    )
                    .first()
                )
                if exists:
                    continue

                db.add(
                    AttendanceRecord(
                        employee_badge_number=badge_number,
                        device_id=device_id,
                        timestamp=utc_ts,
                        punch_type=record.punch,
                        status=record.status,
                        sync_status="synced",
                    )
                )
                inserted += 1

            if inserted:
                db.commit()
        finally:
            db.close()

        return inserted


# Module-level singleton + legacy-API convenience wrappers
zk_session = ZkSession()


def _op_get_status(conn: Any) -> dict:
    try:
        firmware = conn.get_firmware_version()
    except Exception as fw_exc:
        logger.warning(f"[zk_session.get_status] firmware query failed: {fw_exc}")
        firmware = "Unknown"
    return {
        "connected": True,
        "host": zk_session.host,
        "port": zk_session.port,
        "firmware": firmware,
    }


def _describe_exc(exc: BaseException) -> str:
    """str(exc) often returns empty for bare pyzk Exception()s. repr gives
    `Exception()` which is more useful but ugly; prefer the type name."""
    s = str(exc).strip()
    if s:
        return s
    return f"{type(exc).__name__}()"


def get_status() -> dict:
    try:
        # Longer than default 30s for the same reason as `sync_time`: at
        # startup the daemon thread can be 30s+ into its initial catch_up
        # (full `get_attendance` over thousands of records). A tighter
        # timeout would fire a false-failure status while the daemon is
        # healthy, then recover the next cycle.
        return zk_session.submit(_op_get_status, timeout=120.0)
    except Exception as exc:
        return {
            "connected": False,
            "host": zk_session.host,
            "port": zk_session.port,
            "error": _describe_exc(exc),
        }


def _op_get_time(conn: Any) -> dict:
    device_time = conn.get_time()
    server_time = datetime.now()
    diff = (device_time - server_time).total_seconds()
    return {
        "success": True,
        "device_time": device_time.isoformat(),
        "server_time": server_time.isoformat(),
        "time_difference_seconds": diff,
        "synchronized": abs(diff) < 60,
    }


def get_time() -> dict:
    try:
        # Same 120s timeout as sync_time/get_status: get_time is the very
        # first thing `_refresh_time_and_sync` calls, and the periodic job
        # fires 5s after container start — long before the daemon's
        # initial catch_up has freed the op queue. A 30s timeout here
        # triggered the 14:13 "TimeoutError()" Slack alert on the
        # 14:12 deploy.
        return zk_session.submit(_op_get_time, timeout=120.0)
    except Exception as exc:
        return {"success": False, "message": _describe_exc(exc)}


def _op_sync_time(conn: Any) -> dict:
    from zoneinfo import ZoneInfo

    target = datetime.now(ZoneInfo("Asia/Bangkok")).replace(tzinfo=None)
    old_time = conn.get_time()
    time_diff_before = abs((old_time - target).total_seconds())
    conn.set_time(target)
    time.sleep(1)
    new_time = conn.get_time()
    time_diff_after = abs((new_time - target).total_seconds())
    return {
        "success": time_diff_after <= 5.0,
        "old_time": old_time.isoformat(),
        "new_time": new_time.isoformat(),
        "target_time": target.isoformat(),
        "time_diff_before": time_diff_before,
        "time_diff_after": time_diff_after,
    }


def sync_time() -> dict:
    try:
        # Longer timeout than the default 30s: at startup the daemon thread
        # may be 30s+ into its initial catch_up; a tight client-side
        # timeout here would fire a false-failure Slack alert while the
        # daemon is still healthy.
        return zk_session.submit(_op_sync_time, timeout=120.0)
    except Exception as exc:
        return {"success": False, "error": _describe_exc(exc)}


def pull_attendance(since_timestamp: Optional[datetime] = None) -> List[dict]:
    def op(conn: Any) -> List[dict]:
        records = conn.get_attendance()
        current_year = datetime.now().year
        current_date = datetime.now().date()
        out: List[dict] = []
        for r in records:
            ts = r.timestamp
            if ts.year < 2010 or ts.year > current_year or ts.date() > current_date:
                continue
            if since_timestamp is not None and ts <= since_timestamp:
                continue
            out.append(
                {
                    "user_id": str(r.user_id),
                    "timestamp": ts,
                    "punch_type": r.punch,
                    "status": r.status,
                }
            )
        return out

    return zk_session.submit(op)


def get_users() -> List[dict]:
    def op(conn: Any) -> List[dict]:
        users = conn.get_users()
        return [
            {
                "user_id": str(u.user_id),
                "name": u.name or f"User {u.user_id}",
                "privilege": u.privilege,
                "password": u.password,
                "group_id": u.group_id,
            }
            for u in users
        ]

    return zk_session.submit(op)


def catch_up_now() -> int:
    """Run the watermark-based catch-up against the live session.
    Generous timeout — a full `get_attendance()` over thousands of records
    can take 60s+; submit's default 30s would TimeoutError mid-fetch."""
    return zk_session.submit(lambda conn: zk_session._catch_up(conn), timeout=180.0)
