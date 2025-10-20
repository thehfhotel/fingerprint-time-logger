"""
Device Cache Service - Comprehensive caching for ZKTeco device data
Provides cache-first architecture to minimize device connections
"""
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with metadata"""
    data: Any
    cached_at: datetime
    ttl_seconds: int
    key: str

    @property
    def age_seconds(self) -> int:
        """Get cache age in seconds"""
        return int((datetime.now() - self.cached_at).total_seconds())

    @property
    def is_stale(self) -> bool:
        """Check if cache entry is stale (expired TTL)"""
        return self.age_seconds > self.ttl_seconds

    @property
    def next_refresh(self) -> datetime:
        """Get next scheduled refresh time"""
        return self.cached_at + timedelta(seconds=self.ttl_seconds)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with metadata"""
        return {
            'data': self.data,
            'cache_metadata': {
                'cached_at': self.cached_at.isoformat(),
                'age_seconds': self.age_seconds,
                'ttl_seconds': self.ttl_seconds,
                'next_refresh': self.next_refresh.isoformat(),
                'stale': self.is_stale
            }
        }


class DeviceCacheService:
    """
    Comprehensive cache service for ZKTeco device data

    Architecture:
    - Frontend -> Backend API -> Cache Service (this) <- Background Scheduler
    - All frontend requests served from cache
    - Background scheduler refreshes cache every 5 minutes
    - Zero direct device connections from API requests
    """

    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._initialized = False

        # Cache configuration (TTL in seconds)
        self._cache_config = {
            'device_status': 300,      # 5 minutes
            'device_time': 300,        # 5 minutes
            'device_health': 300,      # 5 minutes
            'attendance_summary': 300, # 5 minutes
            'attendance_today': 300,   # 5 minutes
            'device_users': 300,       # 5 minutes
            'device_records': 300,     # 5 minutes
        }

        logger.info("Device cache service created")

    async def initialize(self) -> None:
        """Initialize cache service"""
        with self._lock:
            if self._initialized:
                logger.warning("Cache service already initialized")
                return

            logger.info("Initializing device cache service...")
            self._initialized = True
            logger.info("Device cache service initialized successfully")

    async def warm_cache(self) -> None:
        """
        Warm up cache on startup by loading all data
        This ensures immediate availability for frontend requests
        """
        logger.info("Starting cache warm-up...")

        try:
            from app.services.device_service import device_service

            # Warm up device status
            try:
                status = device_service.get_device_status()
                self.set('device_status', status)
                logger.info("✓ Warmed device_status cache")
            except Exception as e:
                logger.warning(f"Failed to warm device_status: {e}")

            # Warm up device time
            try:
                time_data = device_service.get_device_time()
                self.set('device_time', time_data)
                logger.info("✓ Warmed device_time cache")
            except Exception as e:
                logger.warning(f"Failed to warm device_time: {e}")

            # Warm up attendance summary
            try:
                from app.services.attendance_service import attendance_service
                summary = attendance_service.get_attendance_summary()
                self.set('attendance_summary', summary)
                logger.info("✓ Warmed attendance_summary cache")
            except Exception as e:
                logger.warning(f"Failed to warm attendance_summary: {e}")

            logger.info("Cache warm-up complete")

        except Exception as e:
            logger.error(f"Cache warm-up failed: {e}")

    def set(self, key: str, data: Any) -> None:
        """
        Set cache entry

        Args:
            key: Cache key (must exist in _cache_config)
            data: Data to cache
        """
        if key not in self._cache_config:
            logger.warning(f"Unknown cache key: {key}, using default TTL of 300s")
            ttl = 300
        else:
            ttl = self._cache_config[key]

        with self._lock:
            entry = CacheEntry(
                data=data,
                cached_at=datetime.now(),
                ttl_seconds=ttl,
                key=key
            )
            self._cache[key] = entry

            logger.debug(f"Cache set: {key} (TTL: {ttl}s)")

    def get(self, key: str, include_metadata: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get cache entry

        Args:
            key: Cache key
            include_metadata: Include cache metadata in response

        Returns:
            Cached data with metadata or None if not found/stale
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                logger.debug(f"Cache miss: {key} (not found)")
                return None

            # Return data even if stale (graceful degradation)
            # Background scheduler will refresh stale data
            if entry.is_stale:
                logger.warning(f"Cache stale: {key} (age: {entry.age_seconds}s, TTL: {entry.ttl_seconds}s)")

            if include_metadata:
                return entry.to_dict()
            else:
                return entry.data

    def get_raw(self, key: str) -> Optional[Any]:
        """Get raw cached data without metadata"""
        result = self.get(key, include_metadata=False)
        return result

    def invalidate(self, key: str) -> bool:
        """
        Invalidate (remove) cache entry

        Args:
            key: Cache key to invalidate

        Returns:
            True if entry was found and removed
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.info(f"Cache invalidated: {key}")
                return True
            return False

    def invalidate_all(self) -> None:
        """Invalidate all cache entries"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"All cache invalidated ({count} entries)")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Dictionary with cache stats
        """
        with self._lock:
            stats = {
                'total_entries': len(self._cache),
                'entries': {},
                'stale_count': 0,
                'fresh_count': 0
            }

            for key, entry in self._cache.items():
                stats['entries'][key] = {
                    'age_seconds': entry.age_seconds,
                    'ttl_seconds': entry.ttl_seconds,
                    'stale': entry.is_stale,
                    'cached_at': entry.cached_at.isoformat(),
                    'next_refresh': entry.next_refresh.isoformat()
                }

                if entry.is_stale:
                    stats['stale_count'] += 1
                else:
                    stats['fresh_count'] += 1

            return stats

    def get_stale_keys(self) -> List[str]:
        """
        Get list of stale cache keys that need refresh

        Returns:
            List of stale cache keys
        """
        with self._lock:
            return [key for key, entry in self._cache.items() if entry.is_stale]

    def is_healthy(self) -> bool:
        """
        Check if cache service is healthy

        Returns:
            True if cache has fresh data for critical keys
        """
        critical_keys = ['device_status', 'device_time', 'attendance_summary']

        with self._lock:
            for key in critical_keys:
                entry = self._cache.get(key)
                if entry is None or entry.is_stale:
                    return False
            return True


# Global cache service instance
device_cache_service = DeviceCacheService()
