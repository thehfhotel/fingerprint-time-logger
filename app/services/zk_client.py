"""
ZkClient — single point of access to the ZKTeco fingerprint device.

All pyzk usage in this codebase goes through this module. A module-level
threading.Lock serializes the entire connect → operate → disconnect cycle,
which eliminates the concurrent-session collisions that surface as
`TCP packet invalid` (pyzk's ZKNetworkError raised from
`base.py:_test_tcp_top` when an unexpected frame header arrives mid-read).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, List, Optional

from zk import ZK
from zk.exception import ZKError, ZKErrorConnection, ZKNetworkError

logger = logging.getLogger(__name__)

_DEVICE_LOCK = threading.Lock()

# pyzk raises a generic Exception("TCP packet invalid") in older releases and
# ZKNetworkError in newer ones. Match both.
_RETRYABLE_MESSAGES = ("TCP packet invalid", "unpack requires", "timed out")
_RETRYABLE_TYPES = (ZKNetworkError, ZKErrorConnection, ConnectionError, OSError)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE_TYPES):
        return True
    msg = str(exc)
    return any(token in msg for token in _RETRYABLE_MESSAGES)


class ZkClient:
    """
    Serialized client for one ZKTeco device.

    Concurrency model:
      * Every public method takes _DEVICE_LOCK before touching pyzk.
      * The lock is held across the entire (connect, op, disconnect) cycle —
        not just the connect call — so reads/writes never interleave on the
        wire even if pyzk's underlying socket would otherwise allow it.
      * Callers in async contexts MUST wrap calls in `asyncio.to_thread` so the
        event loop is not blocked while waiting for the lock or the device.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[int] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_backoff_seconds: float = 3.0,
    ):
        self.host = host or os.getenv("ZKTECO_HOST", "192.168.100.209")
        self.port = int(port if port is not None else os.getenv("ZKTECO_PORT", "4370"))
        self.password = int(password if password is not None else os.getenv("ZKTECO_PASSWORD", "0"))
        self.timeout = int(timeout if timeout is not None else os.getenv("DEVICE_TIMEOUT", "5"))
        self.max_retries = int(
            max_retries if max_retries is not None else os.getenv("DEVICE_MAX_RETRIES", "3")
        )
        self.retry_backoff_seconds = retry_backoff_seconds

    # ------------------------------------------------------------------ internals

    @contextmanager
    def _session(self, op: str) -> Iterator[Any]:
        """
        Acquire the global lock and yield a connected pyzk session.

        Retries the entire connect-and-yield path on retryable errors so that
        callers don't see a transient `TCP packet invalid` (most resolve in <3s).
        On final failure, raises the last exception.
        """
        last_exc: Optional[BaseException] = None
        with _DEVICE_LOCK:
            for attempt in range(1, self.max_retries + 1):
                conn = None
                try:
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
                    logger.info(f"[zk_client.{op}] connected (attempt {attempt}/{self.max_retries})")
                    try:
                        yield conn
                    finally:
                        try:
                            conn.disconnect()
                        except Exception as disc_exc:
                            logger.warning(f"[zk_client.{op}] disconnect error: {disc_exc}")
                    return
                except BaseException as exc:
                    last_exc = exc
                    # If conn was created but yield raised, try to clean up.
                    if conn is not None:
                        try:
                            conn.disconnect()
                        except Exception:
                            pass
                    if not _is_retryable(exc) or attempt == self.max_retries:
                        logger.error(
                            f"[zk_client.{op}] failed permanently after {attempt} attempt(s): {exc}"
                        )
                        raise
                    logger.warning(
                        f"[zk_client.{op}] attempt {attempt} failed ({exc}); "
                        f"retrying in {self.retry_backoff_seconds}s"
                    )
                    time.sleep(self.retry_backoff_seconds)
            # Should be unreachable, but satisfy type checkers.
            assert last_exc is not None
            raise last_exc

    # ------------------------------------------------------------------ public API

    def get_status(self) -> dict:
        """Return basic device status. Connects, fetches firmware, disconnects."""
        try:
            with self._session("get_status") as conn:
                try:
                    firmware = conn.get_firmware_version()
                except Exception as fw_exc:
                    logger.warning(f"[zk_client.get_status] firmware query failed: {fw_exc}")
                    firmware = "Unknown"
                return {
                    "connected": True,
                    "host": self.host,
                    "port": self.port,
                    "firmware": firmware,
                }
        except Exception as exc:
            return {
                "connected": False,
                "host": self.host,
                "port": self.port,
                "error": str(exc),
            }

    def get_time(self) -> dict:
        """Read current device clock. Does not modify device state."""
        try:
            with self._session("get_time") as conn:
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
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def set_time(self, target: Optional[datetime] = None) -> dict:
        """Set device clock to `target` (defaults to current server time)."""
        if target is None:
            target = datetime.now()
        try:
            with self._session("set_time") as conn:
                old_time = conn.get_time()
                conn.set_time(target)
                new_time = conn.get_time()
                diff = (new_time - target).total_seconds()
                success = abs(diff) <= 5.0
                return {
                    "success": success,
                    "old_time": old_time.isoformat(),
                    "target_time": target.isoformat(),
                    "new_time": new_time.isoformat(),
                    "time_difference_seconds": diff,
                    "synchronized": success,
                }
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def sync_time(self, target_tz: Optional[timezone] = None) -> dict:
        """
        Read device time, set to target (default: now in Bangkok), verify.

        Returns the same keys as `set_time` plus `time_diff_before` so callers
        (e.g. the Slack notifier) can tell how badly the device had drifted.
        Performed in a single locked session — there is no window for another
        op to interleave between the read, the write, and the verification.
        """
        try:
            from zoneinfo import ZoneInfo

            tz = target_tz or ZoneInfo("Asia/Bangkok")
            target = datetime.now(tz).replace(tzinfo=None)

            with self._session("sync_time") as conn:
                old_time = conn.get_time()
                time_diff_before = abs((old_time - target).total_seconds())

                conn.set_time(target)
                # Small wait: the device commits the write asynchronously
                # and `get_time()` immediately after can race with that commit.
                time.sleep(1)

                new_time = conn.get_time()
                time_diff_after = abs((new_time - target).total_seconds())
                success = time_diff_after <= 5.0

                return {
                    "success": success,
                    "old_time": old_time.isoformat(),
                    "new_time": new_time.isoformat(),
                    "target_time": target.isoformat(),
                    "time_diff_before": time_diff_before,
                    "time_diff_after": time_diff_after,
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def pull_attendance(
        self, since_timestamp: Optional[datetime] = None
    ) -> List[dict]:
        """
        Fetch attendance records, optionally filtered to those strictly newer
        than `since_timestamp`. pyzk does not expose a server-side cursor
        (see `base.py:read_with_buffer`), so the filtering happens client-side
        after the full fetch — but we still avoid the 26k DB existence
        checks that the previous implementation did on every cycle.
        """
        with self._session("pull_attendance") as conn:
            records = conn.get_attendance()
            current_year = datetime.now().year
            current_date = datetime.now().date()
            out: List[dict] = []
            skipped_invalid = 0
            skipped_old = 0
            for r in records:
                ts = r.timestamp
                if ts.year < 2010 or ts.year > current_year or ts.date() > current_date:
                    skipped_invalid += 1
                    continue
                if since_timestamp is not None and ts <= since_timestamp:
                    skipped_old += 1
                    continue
                out.append(
                    {
                        "user_id": str(r.user_id),
                        "timestamp": ts,
                        "punch_type": r.punch,
                        "status": r.status,
                    }
                )
            logger.info(
                f"[zk_client.pull_attendance] fetched={len(records)} new={len(out)} "
                f"skipped_old={skipped_old} skipped_invalid={skipped_invalid}"
            )
            return out

    def get_users(self) -> List[dict]:
        """Return the user list from the device."""
        with self._session("get_users") as conn:
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


# Module-level singleton — same pattern as the existing `device_service`.
zk_client = ZkClient()
