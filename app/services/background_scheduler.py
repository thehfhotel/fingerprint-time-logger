"""
Background scheduler for ZKTeco device interactions.

Replaces the old `auto_import_fingerprint_logs` asyncio loop in
`main_unified.py` AND the standalone `zk-time-sync` Docker container with
one APScheduler instance whose jobs all go through the locked `ZkClient`.

Three jobs:
  * `refresh_status`        — every 5 min, writes `device_status` cache.
  * `refresh_time_and_sync` — every 5 min, reads device clock, re-aligns to
                              Bangkok if drift > tolerance, writes
                              `device_time` cache, sends Slack on state
                              change. This is the job that replaces
                              `zk-time-sync/sync_service.py`.
  * `import_attendance`     — every AUTO_IMPORT_INTERVAL_MINUTES (default 30),
                              pulls records newer than the in-DB watermark,
                              inserts them, broadcasts a WebSocket update.

Serialization is guaranteed by the module-level lock inside `ZkClient`, not
by APScheduler — APScheduler's `max_instances=1` only prevents one job from
overlapping *itself*, not different jobs from overlapping each other.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from app.services.zk_client import zk_client
from app.services.device_cache_service import device_cache_service
from app.services.slack_notifier import slack_notifier

logger = logging.getLogger(__name__)

# Drift tolerance: re-align the device only if it has drifted by more than
# this many seconds. Matches the success threshold used by the old
# `zk-time-sync` service (5s).
_DRIFT_TOLERANCE_SECONDS = float(os.getenv("ZK_DRIFT_TOLERANCE_SECONDS", "5"))


class BackgroundSchedulerService:
    """Async scheduler that owns all periodic device interactions."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 60,
            },
            timezone="Asia/Bangkok",
        )
        self._running = False
        self._broadcast_callback = None  # set by start()
        self.scheduler.add_listener(self._on_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._on_error, EVENT_JOB_ERROR)

    # ------------------------------------------------------------------ lifecycle

    def start(self, broadcast_callback=None) -> None:
        """
        Start the scheduler.

        Args:
            broadcast_callback: Optional async callable invoked as
                `await broadcast_callback(message_dict)` after each successful
                attendance import. Wired to the WebSocket manager by
                `main_unified.py`.
        """
        if self._running:
            logger.warning("Background scheduler already running")
            return

        self._broadcast_callback = broadcast_callback
        self._register_jobs()
        self.scheduler.start()
        self._running = True

        sync_interval = int(os.getenv("AUTO_IMPORT_INTERVAL_MINUTES", "30"))
        logger.info(
            f"Background scheduler started: status/time every 5 min, "
            f"attendance import every {sync_interval} min, drift tolerance "
            f"{_DRIFT_TOLERANCE_SECONDS}s"
        )

    def shutdown(self, wait: bool = True) -> None:
        if not self._running:
            return
        self.scheduler.shutdown(wait=wait)
        self._running = False
        logger.info("Background scheduler stopped")

    def get_job_status(self) -> dict:
        jobs = self.scheduler.get_jobs() if self._running else []
        return {
            "running": self._running,
            "total_jobs": len(jobs),
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
                    "trigger": str(j.trigger),
                }
                for j in jobs
            ],
        }

    async def run_attendance_import_now(self) -> dict:
        """Trigger the attendance import immediately (e.g. from POST /sync/attendance)."""
        return await self._import_attendance(initial=False, on_demand=True)

    # ------------------------------------------------------------------ jobs

    def _register_jobs(self) -> None:
        self.scheduler.add_job(
            self._refresh_status,
            IntervalTrigger(minutes=5),
            id="refresh_status",
            name="Refresh device status",
            replace_existing=True,
            next_run_time=datetime.now(),  # run once on startup
        )
        self.scheduler.add_job(
            self._refresh_time_and_sync,
            IntervalTrigger(minutes=5),
            id="refresh_time_and_sync",
            name="Refresh device time + sync if drifted",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=10),
        )
        sync_interval = int(os.getenv("AUTO_IMPORT_INTERVAL_MINUTES", "30"))
        self.scheduler.add_job(
            self._import_attendance,
            IntervalTrigger(minutes=sync_interval),
            id="import_attendance",
            name="Import attendance records",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=20),
        )

    async def _refresh_status(self) -> None:
        status = await asyncio.to_thread(zk_client.get_status)
        device_cache_service.set("device_status", status)
        connected = status.get("connected")
        logger.info(f"[scheduler.refresh_status] connected={connected}")

    async def _refresh_time_and_sync(self) -> None:
        # First, read the current drift without writing.
        time_info = await asyncio.to_thread(zk_client.get_time)
        if not time_info.get("success"):
            device_cache_service.set("device_time", time_info)
            slack_notifier.notify_sync_result(
                {"success": False, "error": time_info.get("message", "device unreachable")},
            )
            return

        drift = abs(time_info.get("time_difference_seconds") or 0)
        if drift <= _DRIFT_TOLERANCE_SECONDS:
            device_cache_service.set("device_time", time_info)
            logger.info(
                f"[scheduler.refresh_time_and_sync] drift={drift:.1f}s within "
                f"tolerance — no resync"
            )
            # Treat in-tolerance reads as a successful sync result for the
            # notifier's state machine so it can heartbeat from this path.
            slack_notifier.notify_sync_result(
                {
                    "success": True,
                    "new_time": time_info.get("device_time", ""),
                    "time_diff_before": drift,
                    "time_diff_after": drift,
                }
            )
            return

        # Drifted — resync.
        logger.warning(
            f"[scheduler.refresh_time_and_sync] drift={drift:.1f}s exceeds "
            f"tolerance {_DRIFT_TOLERANCE_SECONDS}s — resyncing"
        )
        sync_result = await asyncio.to_thread(zk_client.sync_time)
        # Build a cache entry that looks like `get_time()` output so
        # `/api/devices/time` consumers see consistent shape.
        cache_payload = {
            "success": sync_result.get("success", False),
            "device_time": sync_result.get("new_time"),
            "server_time": datetime.now().isoformat(),
            "time_difference_seconds": sync_result.get("time_diff_after", 0),
            "synchronized": sync_result.get("success", False),
            "auto_synced": True,
        }
        device_cache_service.set("device_time", cache_payload)
        slack_notifier.notify_sync_result(sync_result)

    async def _import_attendance(self, initial: bool = False, on_demand: bool = False) -> dict:
        from app.services.attendance_service import attendance_service
        from app.core.database import get_db
        from app.models.models import AttendanceRecord, Device
        from sqlalchemy import func

        # Look up watermark + default device id in a short DB session.
        db = next(get_db())
        try:
            device = db.query(Device).filter(Device.is_active == True).first()
            if not device:
                logger.warning("[scheduler.import_attendance] no active device configured")
                return {"success": False, "message": "No active device"}

            watermark_utc = db.query(func.max(AttendanceRecord.timestamp)).scalar()
        finally:
            db.close()

        # Convert watermark from stored UTC back to Bangkok-naive for comparison
        # with the device's local timestamps.
        since_bangkok = None
        if watermark_utc is not None:
            since_bangkok = (
                watermark_utc.replace(tzinfo=timezone.utc)
                .astimezone(timezone(timedelta(hours=7)))
                .replace(tzinfo=None)
            )

        try:
            new_records = await asyncio.to_thread(zk_client.pull_attendance, since_bangkok)
        except Exception as exc:
            logger.error(f"[scheduler.import_attendance] pull failed: {exc}")
            return {"success": False, "message": str(exc)}

        synced = 0
        if new_records:
            db = next(get_db())
            try:
                for r in new_records:
                    bangkok_time = r["timestamp"]
                    utc_time = (
                        bangkok_time.replace(tzinfo=timezone(timedelta(hours=7)))
                        .astimezone(timezone.utc)
                        .replace(tzinfo=None)
                    )
                    # Still check for duplicates — the watermark filter is at
                    # second granularity and a single punch could land exactly
                    # on the boundary.
                    exists = (
                        db.query(AttendanceRecord)
                        .filter(
                            AttendanceRecord.employee_badge_number == r["user_id"],
                            AttendanceRecord.timestamp == utc_time,
                        )
                        .first()
                    )
                    if exists:
                        continue
                    db.add(
                        AttendanceRecord(
                            employee_badge_number=r["user_id"],
                            device_id=device.id,
                            timestamp=utc_time,
                            punch_type=r["punch_type"],
                            status=r["status"],
                            sync_status="synced",
                        )
                    )
                    synced += 1

                device.last_sync = datetime.now(timezone.utc)
                db.commit()
            finally:
                db.close()

        logger.info(
            f"[scheduler.import_attendance] watermark={since_bangkok} "
            f"pulled={len(new_records)} synced={synced} on_demand={on_demand}"
        )

        # Refresh the attendance_summary cache so the dashboard's next query
        # reflects the new data.
        try:
            summary = attendance_service.get_attendance_summary()
            device_cache_service.set("attendance_summary", summary)
        except Exception as exc:
            logger.warning(f"[scheduler.import_attendance] summary refresh failed: {exc}")
            summary = None

        if synced and self._broadcast_callback is not None and summary is not None:
            try:
                await self._broadcast_callback(
                    {
                        "type": "auto_import_update",
                        "data": summary,
                        "synced_records": synced,
                        "timestamp": datetime.now().isoformat(),
                        "message": f"นำเข้าอัตโนมัติ {synced} บันทึก",
                    }
                )
            except Exception as exc:
                logger.warning(f"[scheduler.import_attendance] broadcast failed: {exc}")

        return {"success": True, "synced": synced, "total_processed": len(new_records)}

    # ------------------------------------------------------------------ listeners

    def _on_executed(self, event) -> None:
        logger.debug(f"[scheduler] job ok: {event.job_id}")

    def _on_error(self, event) -> None:
        logger.error(f"[scheduler] job failed: {event.job_id}: {event.exception}")


background_scheduler = BackgroundSchedulerService()
