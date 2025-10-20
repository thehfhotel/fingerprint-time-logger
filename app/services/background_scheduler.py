"""
Background Scheduler Service - Scheduled device data refresh
CACHE-FIRST ARCHITECTURE with split intervals:
- Device metadata (status, time, summary): 5 minutes
- Fingerprint data sync: 30 minutes (configurable via AUTO_IMPORT_INTERVAL_MINUTES)
"""
import logging
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

logger = logging.getLogger(__name__)


class BackgroundSchedulerService:
    """
    Background scheduler for device data refresh

    Architecture:
    - Device metadata jobs: 5-minute intervals (lightweight, responsive UI)
    - Fingerprint sync job: 30-minute interval (heavy operation, minimal device load)
    - Zero dependency on frontend requests
    - Ensures cache is always fresh for frontend queries
    """

    def __init__(self):
        self.scheduler = BackgroundScheduler(
            job_defaults={
                'coalesce': True,  # Combine multiple missed runs
                'max_instances': 1,  # Only one instance per job
                'misfire_grace_time': 60  # Allow 60s grace for missed jobs
            },
            timezone='Asia/Bangkok'
        )
        self._running = False

        # Add event listeners for monitoring
        self.scheduler.add_listener(self._job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error, EVENT_JOB_ERROR)

        logger.info("Background scheduler service created")

    def _job_executed(self, event):
        """Log successful job execution"""
        logger.info(f"✓ Scheduled job completed: {event.job_id}")

    def _job_error(self, event):
        """Log job execution errors"""
        logger.error(f"✗ Scheduled job failed: {event.job_id}, error: {event.exception}")

    def start(self) -> None:
        """Start background scheduler and register refresh jobs"""
        if self._running:
            logger.warning("Background scheduler already running")
            return

        logger.info("Starting background scheduler...")

        # Register all refresh jobs (split intervals: 5 min metadata, 30 min sync)
        self._register_jobs()

        # Start scheduler
        self.scheduler.start()
        self._running = True

        sync_interval = int(os.getenv('AUTO_IMPORT_INTERVAL_MINUTES', '30'))
        logger.info(f"Background scheduler started successfully")
        logger.info(f"  - Device metadata refresh: 5 minutes")
        logger.info(f"  - Fingerprint sync: {sync_interval} minutes")
        logger.info(f"Scheduled jobs: {len(self.scheduler.get_jobs())}")

    def _register_jobs(self) -> None:
        """
        Register all scheduled refresh jobs

        CACHE-FIRST ARCHITECTURE - Split Intervals:
        - Device metadata (status, time, summary): 5 minutes (lightweight queries)
        - Fingerprint data sync: 30 minutes (heavy device operation, configurable)

        This split prevents overloading the ZKTeco device while keeping UI responsive
        """

        # Job 1: Refresh device status (5 minutes)
        self.scheduler.add_job(
            func=self._refresh_device_status,
            trigger=IntervalTrigger(minutes=5),
            id='refresh_device_status',
            name='Refresh Device Status',
            replace_existing=True
        )
        logger.info("✓ Registered job: refresh_device_status (every 5 minutes)")

        # Job 2: Refresh device time (5 minutes)
        self.scheduler.add_job(
            func=self._refresh_device_time,
            trigger=IntervalTrigger(minutes=5),
            id='refresh_device_time',
            name='Refresh Device Time',
            replace_existing=True
        )
        logger.info("✓ Registered job: refresh_device_time (every 5 minutes)")

        # Job 3: Refresh attendance summary (5 minutes)
        self.scheduler.add_job(
            func=self._refresh_attendance_summary,
            trigger=IntervalTrigger(minutes=5),
            id='refresh_attendance_summary',
            name='Refresh Attendance Summary',
            replace_existing=True
        )
        logger.info("✓ Registered job: refresh_attendance_summary (every 5 minutes)")

        # Job 4: Sync attendance data (30 minutes) - HEAVY OPERATION
        # Import interval from environment variable with 30-minute default
        sync_interval = int(os.getenv('AUTO_IMPORT_INTERVAL_MINUTES', '30'))

        self.scheduler.add_job(
            func=self._sync_attendance_data,
            trigger=IntervalTrigger(minutes=sync_interval),
            id='sync_attendance_data',
            name='Sync Attendance Data',
            replace_existing=True
        )
        logger.info(f"✓ Registered job: sync_attendance_data (every {sync_interval} minutes)")

    def _refresh_device_status(self) -> None:
        """
        Refresh device status cache

        Fetches fresh device status from ZKTeco device and updates cache
        """
        try:
            logger.info("🔄 [Scheduler: refresh_device_status] Starting device status refresh...")
            start_time = datetime.now()

            from app.services.device_service import device_service
            from app.services.device_cache_service import device_cache_service

            # Fetch fresh status from device
            status = device_service.get_device_status()

            # Update cache
            device_cache_service.set('device_status', status)

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✓ [Scheduler: refresh_device_status] Device status refreshed ({elapsed:.2f}s)")

        except Exception as e:
            logger.error(f"✗ [Scheduler: refresh_device_status] Failed to refresh device status: {e}")

    def _refresh_device_time(self) -> None:
        """
        Refresh device time cache

        Fetches fresh device time from ZKTeco device and updates cache
        """
        try:
            logger.info("🔄 [Scheduler: refresh_device_time] Starting device time refresh...")
            start_time = datetime.now()

            from app.services.device_service import device_service
            from app.services.device_cache_service import device_cache_service

            # Fetch fresh time from device
            time_data = device_service.get_device_time()

            # Update cache
            device_cache_service.set('device_time', time_data)

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✓ [Scheduler: refresh_device_time] Device time refreshed ({elapsed:.2f}s)")

        except Exception as e:
            logger.error(f"✗ [Scheduler: refresh_device_time] Failed to refresh device time: {e}")

    def _refresh_attendance_summary(self) -> None:
        """
        Refresh attendance summary cache

        Fetches fresh attendance summary from database and updates cache
        """
        try:
            logger.info("🔄 [Scheduler: refresh_attendance_summary] Starting attendance summary refresh...")
            start_time = datetime.now()

            from app.services.attendance_service import attendance_service
            from app.services.device_cache_service import device_cache_service

            # Fetch fresh summary from database
            summary = attendance_service.get_attendance_summary()

            # Update cache
            device_cache_service.set('attendance_summary', summary)

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✓ [Scheduler: refresh_attendance_summary] Attendance summary refreshed ({elapsed:.2f}s)")

        except Exception as e:
            logger.error(f"✗ [Scheduler: refresh_attendance_summary] Failed to refresh attendance summary: {e}")

    def _sync_attendance_data(self) -> None:
        """
        Sync attendance data from device to database

        This replaces the old auto_import_fingerprint_logs background task
        """
        try:
            logger.info("🔄 [Scheduler: sync_attendance_data] Starting attendance data sync...")
            start_time = datetime.now()

            from app.services.device_service import device_service
            from app.services.attendance_service import attendance_service
            from app.services.device_cache_service import device_cache_service

            # Sync data from device to database
            result = device_service.sync_attendance_data()

            if result["success"]:
                synced = result.get('synced', 0)
                logger.info(f"✓ [Scheduler: sync_attendance_data] Attendance data synced: {synced} records")

                # Refresh attendance summary cache immediately after sync
                summary = attendance_service.get_attendance_summary()
                device_cache_service.set('attendance_summary', summary)

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✓ [Scheduler: sync_attendance_data] Attendance sync complete ({elapsed:.2f}s)")

        except Exception as e:
            logger.error(f"✗ [Scheduler: sync_attendance_data] Failed to sync attendance data: {e}")

    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown background scheduler

        Args:
            wait: Wait for running jobs to complete
        """
        if not self._running:
            logger.warning("Background scheduler not running")
            return

        logger.info("Shutting down background scheduler...")

        self.scheduler.shutdown(wait=wait)
        self._running = False

        logger.info("Background scheduler stopped")

    def get_jobs(self) -> list:
        """Get list of scheduled jobs"""
        return self.scheduler.get_jobs()

    def get_job_status(self) -> dict:
        """
        Get status of all scheduled jobs

        Returns:
            Dictionary with job status information
        """
        jobs = self.scheduler.get_jobs()
        status = {
            'running': self._running,
            'total_jobs': len(jobs),
            'jobs': []
        }

        for job in jobs:
            status['jobs'].append({
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            })

        return status


# Global scheduler service instance
background_scheduler = BackgroundSchedulerService()
