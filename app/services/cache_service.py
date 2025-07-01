"""
Offline data caching service for the fingerprint time logger

This service manages data caching for offline-first functionality,
ensuring the application can function when the ZKTeco device is unavailable.
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.models import DataCache, AttendanceRecord, DeviceStatusLog, SyncQueue
from app.core.database import get_db


class CacheService:
    """Service for managing offline data cache"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # Cache Management Methods
    
    def set_cache(self, key: str, data: Any, expires_in_hours: int = 24) -> bool:
        """
        Store data in cache with expiration
        
        Args:
            key: Unique cache key
            data: Data to cache (will be JSON serialized)
            expires_in_hours: Cache expiration time in hours
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            expires_at = datetime.now() + timedelta(hours=expires_in_hours)
            json_data = json.dumps(data, default=str)  # default=str handles datetime objects
            
            # Check if key already exists
            existing = self.db.query(DataCache).filter(DataCache.cache_key == key).first()
            
            if existing:
                # Update existing cache entry
                existing.cache_data = json_data
                existing.expires_at = expires_at
                existing.updated_at = datetime.now()
            else:
                # Create new cache entry
                cache_entry = DataCache(
                    cache_key=key,
                    cache_data=json_data,
                    expires_at=expires_at
                )
                self.db.add(cache_entry)
            
            self.db.commit()
            return True
            
        except Exception as e:
            print(f"Error setting cache for key {key}: {e}")
            self.db.rollback()
            return False
    
    def get_cache(self, key: str) -> Optional[Any]:
        """
        Retrieve data from cache
        
        Args:
            key: Cache key to retrieve
            
        Returns:
            Cached data if found and not expired, None otherwise
        """
        try:
            cache_entry = self.db.query(DataCache).filter(DataCache.cache_key == key).first()
            
            if not cache_entry:
                return None
            
            # Check if cache has expired
            if cache_entry.expires_at and cache_entry.expires_at < datetime.now():
                # Cache expired - remove it
                self.db.delete(cache_entry)
                self.db.commit()
                return None
            
            # Return cached data
            return json.loads(cache_entry.cache_data)
            
        except Exception as e:
            print(f"Error getting cache for key {key}: {e}")
            return None
    
    def delete_cache(self, key: str) -> bool:
        """Delete cache entry by key"""
        try:
            cache_entry = self.db.query(DataCache).filter(DataCache.cache_key == key).first()
            if cache_entry:
                self.db.delete(cache_entry)
                self.db.commit()
                return True
            return False
        except Exception as e:
            print(f"Error deleting cache for key {key}: {e}")
            return False
    
    def clear_expired_cache(self) -> int:
        """Remove all expired cache entries"""
        try:
            expired_count = self.db.query(DataCache).filter(
                DataCache.expires_at < datetime.now()
            ).count()
            
            self.db.query(DataCache).filter(
                DataCache.expires_at < datetime.now()
            ).delete()
            
            self.db.commit()
            return expired_count
            
        except Exception as e:
            print(f"Error clearing expired cache: {e}")
            return 0
    
    # Attendance Data Caching
    
    def cache_attendance_data(self, attendance_records: List[Dict], device_id: int = None) -> bool:
        """Cache attendance data for offline access"""
        cache_key = f"attendance_data_device_{device_id}" if device_id else "attendance_data_all"
        
        cache_data = {
            "records": attendance_records,
            "cached_at": datetime.now().isoformat(),
            "device_id": device_id,
            "record_count": len(attendance_records)
        }
        
        return self.set_cache(cache_key, cache_data, expires_in_hours=48)
    
    def get_cached_attendance_data(self, device_id: int = None) -> Optional[Dict]:
        """Retrieve cached attendance data"""
        cache_key = f"attendance_data_device_{device_id}" if device_id else "attendance_data_all"
        return self.get_cache(cache_key)
    
    def cache_thai_names(self, thai_names: List[Dict]) -> bool:
        """Cache Thai name mappings for offline access"""
        cache_data = {
            "thai_names": thai_names,
            "cached_at": datetime.now().isoformat(),
            "count": len(thai_names)
        }
        
        return self.set_cache("thai_names_mapping", cache_data, expires_in_hours=168)  # 7 days
    
    def get_cached_thai_names(self) -> Optional[Dict]:
        """Retrieve cached Thai name mappings"""
        return self.get_cache("thai_names_mapping")
    
    # Device Status Management
    
    def log_device_status(self, device_id: int, status: str, error_message: str = None, metadata: Dict = None) -> bool:
        """Log device connectivity status"""
        try:
            status_log = DeviceStatusLog(
                device_id=device_id,
                status=status,
                last_attempt=datetime.now(),
                error_message=error_message,
                device_metadata=json.dumps(metadata) if metadata else None
            )
            
            if status == 'online':
                status_log.last_successful_sync = datetime.now()
            
            self.db.add(status_log)
            self.db.commit()
            return True
            
        except Exception as e:
            print(f"Error logging device status: {e}")
            self.db.rollback()
            return False
    
    def get_device_status(self, device_id: int) -> Optional[Dict]:
        """Get latest device status"""
        try:
            latest_status = self.db.query(DeviceStatusLog).filter(
                DeviceStatusLog.device_id == device_id
            ).order_by(desc(DeviceStatusLog.created_at)).first()
            
            if latest_status:
                return {
                    "status": latest_status.status,
                    "last_attempt": latest_status.last_attempt,
                    "last_successful_sync": latest_status.last_successful_sync,
                    "error_message": latest_status.error_message,
                    "metadata": json.loads(latest_status.device_metadata) if latest_status.device_metadata else None,
                    "logged_at": latest_status.created_at
                }
            
            return None
            
        except Exception as e:
            print(f"Error getting device status: {e}")
            return None
    
    def is_device_online(self, device_id: int, timeout_minutes: int = 5) -> bool:
        """Check if device is considered online based on recent status"""
        status = self.get_device_status(device_id)
        
        if not status:
            return False
        
        if status["status"] != "online":
            return False
        
        # Check if last successful sync was within timeout period
        if status["last_successful_sync"]:
            time_diff = datetime.now() - status["last_successful_sync"]
            return time_diff.total_seconds() < (timeout_minutes * 60)
        
        return False
    
    # Sync Queue Management
    
    def queue_sync_operation(self, operation_type: str, target_table: str, record_id: str = None, 
                           payload: Dict = None, max_retries: int = 3) -> str:
        """Queue a sync operation for background processing"""
        try:
            operation_id = str(uuid.uuid4())
            
            sync_operation = SyncQueue(
                operation_type=operation_type,
                target_table=target_table,
                record_id=record_id,
                payload=json.dumps(payload) if payload else None,
                max_retries=max_retries,
                status='pending'
            )
            
            self.db.add(sync_operation)
            self.db.commit()
            
            return operation_id
            
        except Exception as e:
            print(f"Error queueing sync operation: {e}")
            self.db.rollback()
            return None
    
    def get_pending_sync_operations(self, limit: int = 10) -> List[Dict]:
        """Get pending sync operations"""
        try:
            operations = self.db.query(SyncQueue).filter(
                SyncQueue.status.in_(['pending', 'failed'])
            ).filter(
                SyncQueue.retry_count < SyncQueue.max_retries
            ).order_by(SyncQueue.scheduled_at).limit(limit).all()
            
            return [
                {
                    "id": op.id,
                    "operation_type": op.operation_type,
                    "target_table": op.target_table,
                    "record_id": op.record_id,
                    "payload": json.loads(op.payload) if op.payload else None,
                    "retry_count": op.retry_count,
                    "max_retries": op.max_retries,
                    "status": op.status,
                    "scheduled_at": op.scheduled_at,
                    "last_error": op.last_error
                }
                for op in operations
            ]
            
        except Exception as e:
            print(f"Error getting pending sync operations: {e}")
            return []
    
    def mark_sync_operation_completed(self, operation_id: int) -> bool:
        """Mark sync operation as completed"""
        try:
            operation = self.db.query(SyncQueue).filter(SyncQueue.id == operation_id).first()
            if operation:
                operation.status = 'completed'
                operation.completed_at = datetime.now()
                self.db.commit()
                return True
            return False
        except Exception as e:
            print(f"Error marking sync operation completed: {e}")
            return False
    
    def mark_sync_operation_failed(self, operation_id: int, error_message: str) -> bool:
        """Mark sync operation as failed and increment retry count"""
        try:
            operation = self.db.query(SyncQueue).filter(SyncQueue.id == operation_id).first()
            if operation:
                operation.retry_count += 1
                operation.last_error = error_message
                operation.status = 'failed' if operation.retry_count >= operation.max_retries else 'pending'
                self.db.commit()
                return True
            return False
        except Exception as e:
            print(f"Error marking sync operation failed: {e}")
            return False
    
    # Utility Methods
    
    def get_cache_status(self) -> Dict:
        """Get cache statistics and status"""
        try:
            total_entries = self.db.query(DataCache).count()
            expired_entries = self.db.query(DataCache).filter(
                DataCache.expires_at < datetime.now()
            ).count()
            
            # Get storage usage estimate (rough)
            cache_size_query = self.db.query(DataCache).all()
            total_size = sum(len(entry.cache_data.encode('utf-8')) for entry in cache_size_query)
            
            pending_syncs = self.db.query(SyncQueue).filter(
                SyncQueue.status == 'pending'
            ).count()
            
            return {
                "total_cache_entries": total_entries,
                "expired_entries": expired_entries,
                "active_entries": total_entries - expired_entries,
                "estimated_size_bytes": total_size,
                "pending_sync_operations": pending_syncs,
                "cache_hit_rate": "Not implemented",  # TODO: Implement hit rate tracking
                "last_cleanup": datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"Error getting cache status: {e}")
            return {"error": str(e)}


# Convenience function for getting cache service
def get_cache_service(db: Session = None) -> CacheService:
    """Get a cache service instance"""
    if db is None:
        db = next(get_db())
    return CacheService(db)