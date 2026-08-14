"""
Background scheduler for ZKTeco device interactions.

Replaces the old `auto_import_fingerprint_logs` asyncio loop in
`main_unified.py` AND the standalone `zk-time-sync` Docker container with
one APScheduler instance whose jobs all go through `zk_session`.

Jobs:
  * `refresh_status_and_time`   — every 5 min, ONE device connection window
                                  (`zk_session.get_status_and_time()`) that
                                  reads both status and clock, writes the
                                  `device_status` + `device_time` caches,
                                  re-aligns to Bangkok if drift > tolerance,
                                  and sends Slack on state change. Replaces
                                  the old `refresh_status` +
                                  `refresh_time_and_sync` pair (was two
                                  separate device round trips / teardowns
                                  of the live_capture stream every 5 min;
                                  now one). Also the job that replaces
                                  `zk-time-sync/sync_service.py`.
  * `refresh_attendance_summary` — every 5 min, pure-DB cache refresh.
  * `import_attendance`          — every AUTO_IMPORT_INTERVAL_MINUTES
                                  (default 30), delegates to
                                  `zk_session.catch_up_now()` — per-device
                                  watermark + lookback-window backfill, not
                                  a plain "since last import" pull.
  * `reconcile_staff_oa_menus`   — hourly, no device contact. Safety net for
                                  the event-driven Employee Hub Role Menu
                                  provisioning (see
                                  `app/services/staff_oa_provision.py`):
                                  re-runs every active, LINE-linked employee
                                  through the same per-user path so a grant
                                  written directly in the DB, a menu deleted
                                  by hand, or a LINE outage at grant time all
                                  converge on their own. Strictly ADDITIVE —
                                  it never deletes a rich menu and never
                                  touches the channel default; those stay in
                                  scripts/staff_oa_sync.py. No-ops entirely
                                  while the feature is dark.

Serialization of device access is owned by `zk_session`'s single daemon
thread + op queue, not by APScheduler — APScheduler's `max_instances=1`
only prevents one job from overlapping *itself*, not different jobs from
overlapping each other.
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
from apscheduler.jobstores.base import ConflictingIdError

from app.services import staff_oa_provision, staff_oa_service, zk_session
from app.services.device_cache_service import device_cache_service
from app.services.slack_notifier import slack_notifier

logger = logging.getLogger(__name__)

# Drift tolerance: re-align the device only if it has drifted by more than
# this many seconds. Matches the success threshold used by the old
# `zk-time-sync` service (5s).
_DRIFT_TOLERANCE_SECONDS = float(os.getenv("ZK_DRIFT_TOLERANCE_SECONDS", "5"))

# After a power outage the ZK device may take longer to boot than this
# service. Until the first attendance import succeeds, a failed import
# reschedules itself for this many minutes from now (instead of waiting
# for the regular 30-min interval).
_STARTUP_RETRY_MINUTES = float(os.getenv("ZK_STARTUP_RETRY_MINUTES", "3"))

# How often to sweep every LINE-linked employee's Employee Hub Role Menu.
#
# HOURLY, deliberately. This is a safety net, not the delivery mechanism:
# the three event triggers (grant change, LINE link, onboarding approval)
# are what make a grant seamless in seconds, and this job only exists to
# converge what they missed. That makes the interval a cost/latency trade
# with nothing riding on it being tight — an hour bounds the worst case
# "LINE was down exactly when the admin saved" to something a maid would
# experience as "it showed up later that shift", while keeping the LINE API
# traffic trivial (a rich-menu list + a link per linked employee per hour;
# the estate is dozens of employees, not thousands, and LINE's limits are
# per-minute). Faster buys nothing the event path does not already give;
# much slower would leave a maid without her tool for most of a working day.
_STAFF_OA_RECONCILE_MINUTES = float(
    os.getenv("STAFF_OA_RECONCILE_INTERVAL_MINUTES", "60")
)


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
        # Startup-retry state: until the first attendance import succeeds, a
        # failed import schedules a one-shot retry in
        # `_STARTUP_RETRY_MINUTES` instead of waiting for the regular 30-min
        # interval. Recovers quickly after a power outage when the ZK device
        # boots slower than this service. Ported from the host-only commit
        # 238655e6 (which modified the now-deleted zk-time-sync container).
        self._first_import_succeeded = False
        self._startup_retry_count = 0
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
            f"Background scheduler started: status+time (merged) every 5 min, "
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

    async def run_attendance_import_now(self, full: bool = False) -> dict:
        """Trigger the attendance import immediately (e.g. from POST /sync/attendance).
        `full=True` bypasses the per-device watermark floor (dedup-only
        reconcile of the whole device log) — the one-time post-deploy
        backfill / `?full=true` sync endpoint.

        `full=True` does NOT run inline: a full reconcile walks the entire
        device log (thousands of records via `conn.get_attendance()`) and
        can run well past a typical HTTP request/proxy timeout. Instead it
        schedules a one-shot job and returns immediately.
        `replace_existing=False` means a request that arrives while a
        backfill is already scheduled/running gets `already_running` back
        rather than stacking a second job behind it. The job has no
        recurring trigger, so APScheduler drops it from the store once it
        fires — no cleanup needed here. `full=False` is unchanged: awaited
        inline, same as before."""
        if not full:
            return await self._import_attendance(initial=False, on_demand=True, full=False)

        try:
            self.scheduler.add_job(
                self._import_attendance,
                id="manual_full_backfill",
                kwargs={"initial": False, "on_demand": True, "full": True},
                replace_existing=False,
                next_run_time=datetime.now(),
            )
        except ConflictingIdError:
            return {
                "success": False,
                "already_running": True,
                "message": "A full backfill is already scheduled or running",
            }

        return {
            "success": True,
            "scheduled": True,
            "message": "Full backfill scheduled to run now",
        }

    # ------------------------------------------------------------------ jobs

    def _register_jobs(self) -> None:
        self.scheduler.add_job(
            self._refresh_status_and_time,
            IntervalTrigger(minutes=5),
            id="refresh_status_and_time",
            name="Refresh device status + time (and resync if drifted)",
            replace_existing=True,
            next_run_time=datetime.now(),  # run once on startup
        )
        # DB-only refresh of the attendance_summary cache. Without this
        # the summary entry's 5-min TTL expires long before the 30-min
        # import job touches it again, so `is_healthy()` reports stale
        # and the dashboard's "auto-import working" indicator flips to
        # ❌. No device contact — just a DB aggregation.
        self.scheduler.add_job(
            self._refresh_attendance_summary,
            IntervalTrigger(minutes=5),
            id="refresh_attendance_summary",
            name="Refresh attendance summary cache",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=5),
        )
        sync_interval = int(os.getenv("AUTO_IMPORT_INTERVAL_MINUTES", "30"))
        self.scheduler.add_job(
            self._import_attendance,
            IntervalTrigger(minutes=sync_interval),
            id="import_attendance",
            name="Import attendance records",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=20),
            # Longer than the 60s default: a missed misfire here means a
            # full watermark-floor backfill import gets silently dropped
            # instead of running late — worth tolerating up to 5 min of
            # scheduler lag before APScheduler gives up on the run.
            misfire_grace_time=300,
        )
        # Employee Hub Role Menu safety net. No device contact — DB reads plus
        # LINE Messaging API calls — so it does not contend with anything
        # above for the ZK device. The first run is deliberately NOT at
        # startup: a container restart is the least likely moment for menus to
        # have drifted, and firing a LINE sweep while the app is still warming
        # up buys nothing. Two minutes in is soon enough to catch a restart
        # that followed a failed grant save.
        self.scheduler.add_job(
            self._reconcile_staff_oa_menus,
            IntervalTrigger(minutes=_STAFF_OA_RECONCILE_MINUTES),
            id="reconcile_staff_oa_menus",
            name="Reconcile Employee Hub Role Menus (staff LINE OA)",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(minutes=2),
        )

    async def _reconcile_staff_oa_menus(self) -> None:
        """Converge every active, LINE-linked employee's Role Menu.

        Guarded twice over, because this job's whole reason for existing is
        that the event-driven path can fail:

          * the dark check short-circuits before any work when
            STAFF_OA_CHANNEL_* are unset — which is the state on every dev
            machine, in CI, and in production until the staff OA secrets are
            delivered, so it must cost nothing there;
          * `reconcile_all()` already swallows per-employee and whole-sweep
            failures, and the try/except here is belt-and-braces so a LINE
            outage can never surface as an APScheduler job error (which the
            `_on_error` listener logs at ERROR and would otherwise make look
            like a device fault).

        The blocking LINE/PIL work runs in a thread — never on the event loop.
        This service shares its loop with the whole FastAPI app, and blocking
        LINE calls made on the loop are what stalled /oidc/token earlier
        today.
        """
        try:
            if not staff_oa_service.is_enabled():
                logger.debug(
                    "[scheduler.reconcile_staff_oa_menus] staff OA is dark — skipped"
                )
                return
            await asyncio.to_thread(staff_oa_provision.reconcile_all)
            logger.info("[scheduler.reconcile_staff_oa_menus] reconcile complete")
        except Exception as exc:
            logger.warning(f"[scheduler.reconcile_staff_oa_menus] failed: {exc}")

    async def _refresh_attendance_summary(self) -> None:
        """Recompute the attendance summary from the DB and refresh its cache
        entry. Pure DB query — no device contact."""
        try:
            from app.services.attendance_service import attendance_service
            summary = await asyncio.to_thread(attendance_service.get_attendance_summary)
            device_cache_service.set("attendance_summary", summary)
            logger.info("[scheduler.refresh_attendance_summary] cache refreshed")
        except Exception as exc:
            logger.warning(f"[scheduler.refresh_attendance_summary] failed: {exc}")

    async def _refresh_status_and_time(self) -> None:
        """Merged status+time refresh: ONE device connection window via
        `zk_session.get_status_and_time()` instead of the old two separate
        5-min jobs (each its own device round trip / live_capture
        teardown). Writes both `device_status` and `device_time` caches
        with the same shapes `get_status()`/`get_time()` produced
        standalone, and keeps the existing drift/resync + Slack
        state-change logic unchanged."""
        result = await asyncio.to_thread(zk_session.get_status_and_time)
        status = result.get("status") or {"connected": False}
        time_info = result.get("time") or {"success": False}

        device_cache_service.set("device_status", status)

        # "users" is None when the device op failed — leave the existing
        # device_users cache entry alone rather than clobbering it with an
        # empty list (consumed by consolidated_employees's from_device=true
        # branch, which now reads this cache instead of calling the device
        # live on every admin page load).
        users = result.get("users")
        if isinstance(users, list):
            device_cache_service.set("device_users", users)

        connected = status.get("connected")
        logger.info(f"[scheduler.refresh_status_and_time] connected={connected}")

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
                f"[scheduler.refresh_status_and_time] drift={drift:.1f}s within "
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
            f"[scheduler.refresh_status_and_time] drift={drift:.1f}s exceeds "
            f"tolerance {_DRIFT_TOLERANCE_SECONDS}s — resyncing"
        )
        sync_result = await asyncio.to_thread(zk_session.sync_time)
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

    async def _import_attendance(
        self, initial: bool = False, on_demand: bool = False, full: bool = False
    ) -> dict:
        """Backstop catch-up. live_capture in ZkSession is the primary path;
        this 30-min sweep is a safety net for outages and bugs.
        Delegates to `zk_session.catch_up_now()` so the same dedup + watermark
        + WebSocket-broadcast logic runs through one code path."""
        from app.services.attendance_service import attendance_service

        try:
            synced = await asyncio.to_thread(zk_session.catch_up_now, full=full)
        except Exception as exc:
            logger.error(f"[scheduler.import_attendance] catch_up failed: {exc!r}")
            self._maybe_schedule_startup_retry(reason=repr(exc))
            return {"success": False, "message": repr(exc)}

        # Any non-raising run replenishes the fast-retry budget — not just
        # the first successful import after boot. Without this, a device
        # outage months into uptime (long after `_startup_retry_count` was
        # exhausted on some earlier blip) would fall straight to the
        # 30-min interval instead of getting fast retries again.
        self._startup_retry_count = 0

        logger.info(
            f"[scheduler.import_attendance] synced={synced} on_demand={on_demand} full={full}"
        )

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

        # Only positive evidence of a working device read (synced>0) disarms
        # the startup retry — a `synced=0` run (e.g. no active device
        # configured, or genuinely nothing new) must NOT permanently
        # disarm it, or the fast-retry window effectively never applies
        # since most cycles are legitimately synced=0 in steady state.
        if synced and not self._first_import_succeeded:
            self._first_import_succeeded = True
            logger.info("[scheduler.import_attendance] first import OK; startup retry disarmed")

        return {"success": True, "synced": synced, "total_processed": synced}

    def _maybe_schedule_startup_retry(self, reason: str) -> None:
        """
        Schedule a one-shot retry of the attendance import.

        Active only until the first successful import after boot — after that
        the standard 30-min interval is fast enough. Concrete scenario this
        protects against: power outage where the ZK device boots slower than
        this service, so the first scheduled import fails. Without this,
        we'd wait up to 30 min before retrying.
        """
        if self._first_import_succeeded or not self._running:
            return
        # Cap the retry chain. After this many attempts, fall back to the
        # regular 30-min interval — chained retries against a persistently-
        # unreachable device only spam the logs and Slack.
        if self._startup_retry_count >= 3:
            logger.warning(
                f"[scheduler.import_attendance] retry budget exhausted "
                f"({self._startup_retry_count}); falling back to interval schedule"
            )
            return
        self._startup_retry_count += 1
        run_at = datetime.now() + timedelta(minutes=_STARTUP_RETRY_MINUTES)
        job_id = f"startup_retry_{int(run_at.timestamp())}"
        try:
            self.scheduler.add_job(
                self._import_attendance,
                "date",
                run_date=run_at,
                id=job_id,
                misfire_grace_time=120,
                replace_existing=False,
            )
            logger.warning(
                f"[scheduler.import_attendance] failed ({reason}); "
                f"startup retry scheduled at {run_at.isoformat()}"
            )
        except Exception as exc:
            # Already scheduled for the same minute, or scheduler shutting down.
            logger.debug(f"[scheduler.import_attendance] retry not scheduled: {exc}")

    # ------------------------------------------------------------------ listeners

    def _on_executed(self, event) -> None:
        logger.debug(f"[scheduler] job ok: {event.job_id}")

    def _on_error(self, event) -> None:
        logger.error(f"[scheduler] job failed: {event.job_id}: {event.exception}")


background_scheduler = BackgroundSchedulerService()
