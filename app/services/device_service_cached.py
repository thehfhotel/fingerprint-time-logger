"""
Device Service with Connection Caching - Reduces device load by caching status/time data
This version implements 10-minute device status caching to prevent overwhelming the ZK device
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import time
from zk import ZK
from sqlalchemy.orm import Session

from app.models.models import Device, AttendanceRecord, Employee
from app.core.database import get_db
from app.services.logging_service import app_logger

logger = logging.getLogger(__name__)


class CachedDeviceService:
    """Device service with connection caching to reduce device load"""

    def __init__(self):
        self.max_retries = int(os.getenv('DEVICE_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('DEVICE_TIMEOUT', '5'))

        # Cache for device status to reduce connection frequency (5 minutes to match frontend)
        self._status_cache = {}
        self._status_cache_lock = threading.Lock()
        self._cache_duration = 300  # 5 minutes in seconds to match frontend health check interval

        # Cache for device time (1 minute to allow more frequent time checks)
        self._time_cache = {}
        self._time_cache_lock = threading.Lock()
        self._time_cache_duration = 60  # 1 minute for time cache

    def get_device_status(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get device status with caching to reduce connection frequency"""
        cache_key = "device_status"

        # Check cache first unless force refresh
        if not force_refresh:
            with self._status_cache_lock:
                if cache_key in self._status_cache:
                    cached_data, cache_time = self._status_cache[cache_key]
                    cache_age = time.time() - cache_time
                    if cache_age < self._cache_duration:
                        logger.debug(f"Using cached device status (age: {int(cache_age)}s)")
                        cached_data["cache_age_seconds"] = int(cache_age)
                        return cached_data

        # Cache miss or expired, get fresh status
        logger.info("Fetching fresh device status (cache miss or expired)")
        # Use original device service for actual connection
        from app.services.device_service import device_service as original_service
        status = original_service.get_device_status()
        status["cache_age_seconds"] = 0

        # Update cache
        with self._status_cache_lock:
            self._status_cache[cache_key] = (status, time.time())

        return status

    def get_device_time(self, auto_sync: bool = True, force_refresh: bool = False) -> Dict[str, Any]:
        """Get device time with caching to reduce connection frequency"""
        cache_key = "device_time"

        # Check cache first unless force refresh or auto-sync is enabled
        if not force_refresh and not auto_sync:
            with self._time_cache_lock:
                if cache_key in self._time_cache:
                    cached_data, cache_time = self._time_cache[cache_key]
                    cache_age = time.time() - cache_time
                    if cache_age < self._time_cache_duration:
                        # Update server time in cached data
                        cached_data["server_time"] = datetime.now(timezone.utc).isoformat()
                        cached_data["cache_age_seconds"] = int(cache_age)
                        logger.debug(f"Using cached device time (age: {int(cache_age)}s)")
                        return cached_data

        logger.info("Fetching fresh device time")
        # Use original device service for actual connection
        from app.services.device_service import device_service as original_service
        result = original_service.get_device_time(auto_sync=auto_sync)

        if result.get("success"):
            result["cache_age_seconds"] = 0
            # Cache the result if not auto-synced (auto-sync invalidates cache)
            if not auto_sync:
                with self._time_cache_lock:
                    self._time_cache[cache_key] = (result.copy(), time.time())

        return result

    def clear_cache(self):
        """Clear all cached data"""
        with self._status_cache_lock:
            self._status_cache.clear()
        with self._time_cache_lock:
            self._time_cache.clear()
        logger.info("Device cache cleared")


# Global cached service instance
cached_device_service = CachedDeviceService()