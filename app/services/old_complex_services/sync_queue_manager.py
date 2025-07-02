"""
Sync Queue Management System for Offline-First Architecture

This service manages the background synchronization queue, handling operations
that need to be performed when device connectivity is restored.
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_

from app.models.models import SyncQueue, AttendanceRecord, Device
from app.services.cache_service import CacheService


class SyncOperationType(Enum):
    """Types of sync operations"""
    SYNC_ATTENDANCE = "sync_attendance"
    SYNC_USERS = "sync_users"
    SYNC_DEVICE_TIME = "sync_device_time"
    MANUAL_ATTENDANCE = "manual_attendance"
    DEVICE_HEALTH_CHECK = "device_health_check"
    FULL_SYNC = "full_sync"


class SyncPriority(Enum):
    """Priority levels for sync operations"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class SyncStatus(Enum):
    """Status of sync operations"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SyncQueueManager:
    """Manages background sync operations queue"""
    
    def __init__(self, db: Session):
        self.db = db
        self.cache_service = CacheService(db)
    
    # Queue Management Methods
    
    def queue_operation(self, 
                       operation_type: Union[SyncOperationType, str],
                       target_table: str,
                       record_id: str = None,
                       payload: Dict = None,
                       priority: SyncPriority = SyncPriority.NORMAL,
                       max_retries: int = 3,
                       delay_seconds: int = 0) -> Optional[str]:
        """
        Queue a sync operation for background processing
        
        Args:
            operation_type: Type of sync operation to perform
            target_table: Database table this operation targets
            record_id: Optional specific record ID
            payload: Operation-specific data
            priority: Operation priority level
            max_retries: Maximum retry attempts
            delay_seconds: Delay before first execution
            
        Returns:
            str: Operation ID if successful, None otherwise
        """
        try:
            operation_id = str(uuid.uuid4())
            
            # Convert enum to string if needed
            if isinstance(operation_type, SyncOperationType):
                operation_type = operation_type.value
            
            # Calculate scheduled time
            scheduled_at = datetime.now() + timedelta(seconds=delay_seconds)
            
            sync_operation = SyncQueue(
                operation_type=operation_type,
                target_table=target_table,
                record_id=record_id,
                payload=json.dumps(payload) if payload else None,
                max_retries=max_retries,
                status=SyncStatus.PENDING.value,
                scheduled_at=scheduled_at
            )
            
            self.db.add(sync_operation)
            self.db.commit()
            
            # Cache operation for quick access
            self.cache_service.set_cache(
                f"sync_op_{sync_operation.id}",
                {
                    "id": sync_operation.id,
                    "operation_type": operation_type,
                    "priority": priority.value,
                    "scheduled_at": scheduled_at.isoformat(),
                    "status": SyncStatus.PENDING.value
                },
                expires_in_hours=24
            )
            
            print(f"✅ Queued sync operation: {operation_type} for {target_table}")
            return operation_id
            
        except Exception as e:
            print(f"❌ Error queueing sync operation: {e}")
            self.db.rollback()
            return None
    
    def get_next_operations(self, limit: int = 5) -> List[Dict]:
        """
        Get next operations to process, ordered by priority and schedule
        
        Args:
            limit: Maximum number of operations to retrieve
            
        Returns:
            List of operation dictionaries
        """
        try:
            # Get pending and failed operations that haven't exceeded retry limit
            operations = self.db.query(SyncQueue).filter(
                and_(
                    SyncQueue.status.in_([SyncStatus.PENDING.value, SyncStatus.FAILED.value]),
                    SyncQueue.retry_count < SyncQueue.max_retries,
                    SyncQueue.scheduled_at <= datetime.now()
                )
            ).order_by(
                SyncQueue.scheduled_at.asc()
            ).limit(limit).all()
            
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
                    "created_at": op.created_at,
                    "last_error": op.last_error
                }
                for op in operations
            ]
            
        except Exception as e:
            print(f"❌ Error getting next operations: {e}")
            return []
    
    def mark_processing(self, operation_id: int) -> bool:
        """Mark operation as currently being processed"""
        try:
            operation = self.db.query(SyncQueue).filter(SyncQueue.id == operation_id).first()
            if operation:
                operation.status = SyncStatus.PROCESSING.value
                self.db.commit()
                
                # Update cache
                self.cache_service.set_cache(
                    f"sync_op_{operation_id}",
                    {"status": SyncStatus.PROCESSING.value, "processing_at": datetime.now().isoformat()},
                    expires_in_hours=1
                )
                
                return True
            return False
        except Exception as e:
            print(f"❌ Error marking operation as processing: {e}")
            self.db.rollback()
            return False
    
    def mark_completed(self, operation_id: int, result_data: Dict = None) -> bool:
        """Mark operation as successfully completed"""
        try:
            operation = self.db.query(SyncQueue).filter(SyncQueue.id == operation_id).first()
            if operation:
                operation.status = SyncStatus.COMPLETED.value
                operation.completed_at = datetime.now()
                
                # Store result data if provided
                if result_data:
                    current_payload = json.loads(operation.payload) if operation.payload else {}
                    current_payload['result'] = result_data
                    operation.payload = json.dumps(current_payload)
                
                self.db.commit()
                
                # Update cache
                self.cache_service.set_cache(
                    f"sync_op_{operation_id}",
                    {
                        "status": SyncStatus.COMPLETED.value, 
                        "completed_at": datetime.now().isoformat(),
                        "result": result_data
                    },
                    expires_in_hours=48  # Keep completed operations in cache longer
                )
                
                print(f"✅ Operation {operation_id} completed successfully")
                return True
            return False
        except Exception as e:
            print(f"❌ Error marking operation as completed: {e}")
            self.db.rollback()
            return False
    
    def mark_failed(self, operation_id: int, error_message: str, retry_delay_seconds: int = None) -> bool:
        """Mark operation as failed and schedule retry if applicable"""
        try:
            operation = self.db.query(SyncQueue).filter(SyncQueue.id == operation_id).first()
            if operation:
                operation.retry_count += 1
                operation.last_error = error_message
                
                # Check if we should retry
                if operation.retry_count < operation.max_retries:
                    operation.status = SyncStatus.PENDING.value
                    
                    # Calculate exponential backoff delay
                    if retry_delay_seconds is None:
                        retry_delay_seconds = min(300, 30 * (2 ** operation.retry_count))  # Max 5 minutes
                    
                    operation.scheduled_at = datetime.now() + timedelta(seconds=retry_delay_seconds)
                    
                    print(f"⚠️  Operation {operation_id} failed, retrying in {retry_delay_seconds}s (attempt {operation.retry_count + 1}/{operation.max_retries})")
                else:
                    operation.status = SyncStatus.FAILED.value
                    print(f"❌ Operation {operation_id} permanently failed after {operation.retry_count} attempts")
                
                self.db.commit()
                
                # Update cache
                self.cache_service.set_cache(
                    f"sync_op_{operation_id}",
                    {
                        "status": operation.status,
                        "retry_count": operation.retry_count,
                        "last_error": error_message,
                        "next_retry": operation.scheduled_at.isoformat() if operation.status == SyncStatus.PENDING.value else None
                    },
                    expires_in_hours=24
                )
                
                return True
            return False
        except Exception as e:
            print(f"❌ Error marking operation as failed: {e}")
            self.db.rollback()
            return False
    
    def cancel_operation(self, operation_id: int, reason: str = None) -> bool:
        """Cancel a pending operation"""
        try:
            operation = self.db.query(SyncQueue).filter(SyncQueue.id == operation_id).first()
            if operation and operation.status in [SyncStatus.PENDING.value, SyncStatus.FAILED.value]:
                operation.status = SyncStatus.CANCELLED.value
                operation.last_error = f"Cancelled: {reason}" if reason else "Cancelled by user"
                self.db.commit()
                
                # Update cache
                self.cache_service.delete_cache(f"sync_op_{operation_id}")
                
                print(f"🚫 Operation {operation_id} cancelled")
                return True
            return False
        except Exception as e:
            print(f"❌ Error cancelling operation: {e}")
            self.db.rollback()
            return False
    
    # Specialized Queue Operations
    
    def queue_attendance_sync(self, device_id: int, since_timestamp: datetime = None) -> Optional[str]:
        """Queue attendance data synchronization"""
        payload = {
            "device_id": device_id,
            "sync_type": "incremental" if since_timestamp else "full",
            "since_timestamp": since_timestamp.isoformat() if since_timestamp else None
        }
        
        return self.queue_operation(
            operation_type=SyncOperationType.SYNC_ATTENDANCE,
            target_table="attendance_records",
            record_id=f"device_{device_id}",
            payload=payload,
            priority=SyncPriority.HIGH
        )
    
    def queue_manual_attendance(self, employee_id: str, device_id: int, timestamp: datetime, punch_type: int) -> Optional[str]:
        """Queue manual attendance entry to be synced to device"""
        payload = {
            "employee_id": employee_id,
            "device_id": device_id,
            "timestamp": timestamp.isoformat(),
            "punch_type": punch_type,
            "source": "manual_entry"
        }
        
        return self.queue_operation(
            operation_type=SyncOperationType.MANUAL_ATTENDANCE,
            target_table="attendance_records",
            record_id=f"manual_{employee_id}_{int(timestamp.timestamp())}",
            payload=payload,
            priority=SyncPriority.URGENT
        )
    
    def queue_device_health_check(self, device_id: int) -> Optional[str]:
        """Queue device health check"""
        payload = {
            "device_id": device_id,
            "check_type": "connectivity",
            "timestamp": datetime.now().isoformat()
        }
        
        return self.queue_operation(
            operation_type=SyncOperationType.DEVICE_HEALTH_CHECK,
            target_table="devices",
            record_id=f"device_{device_id}",
            payload=payload,
            priority=SyncPriority.NORMAL,
            max_retries=2
        )
    
    def queue_full_sync(self, device_id: int) -> Optional[str]:
        """Queue full device synchronization"""
        payload = {
            "device_id": device_id,
            "sync_type": "full",
            "include_users": True,
            "include_attendance": True,
            "timestamp": datetime.now().isoformat()
        }
        
        return self.queue_operation(
            operation_type=SyncOperationType.FULL_SYNC,
            target_table="all",
            record_id=f"device_{device_id}",
            payload=payload,
            priority=SyncPriority.HIGH,
            max_retries=5
        )
    
    # Queue Analytics and Management
    
    def get_queue_statistics(self) -> Dict:
        """Get comprehensive queue statistics"""
        try:
            stats = {}
            
            # Count by status
            for status in SyncStatus:
                count = self.db.query(SyncQueue).filter(SyncQueue.status == status.value).count()
                stats[f"{status.value}_count"] = count
            
            # Count by operation type
            operation_types = self.db.query(SyncQueue.operation_type).distinct().all()
            for (op_type,) in operation_types:
                count = self.db.query(SyncQueue).filter(SyncQueue.operation_type == op_type).count()
                stats[f"type_{op_type}_count"] = count
            
            # Age statistics
            oldest_pending = self.db.query(SyncQueue).filter(
                SyncQueue.status == SyncStatus.PENDING.value
            ).order_by(SyncQueue.created_at.asc()).first()
            
            if oldest_pending:
                age = datetime.now() - oldest_pending.created_at
                stats["oldest_pending_age_seconds"] = int(age.total_seconds())
            
            # Failed operations needing attention
            failed_ops = self.db.query(SyncQueue).filter(
                and_(
                    SyncQueue.status == SyncStatus.FAILED.value,
                    SyncQueue.retry_count >= SyncQueue.max_retries
                )
            ).count()
            stats["permanently_failed_count"] = failed_ops
            
            # Operations ready to process
            ready_ops = self.db.query(SyncQueue).filter(
                and_(
                    SyncQueue.status.in_([SyncStatus.PENDING.value, SyncStatus.FAILED.value]),
                    SyncQueue.retry_count < SyncQueue.max_retries,
                    SyncQueue.scheduled_at <= datetime.now()
                )
            ).count()
            stats["ready_to_process_count"] = ready_ops
            
            return stats
            
        except Exception as e:
            print(f"❌ Error getting queue statistics: {e}")
            return {"error": str(e)}
    
    def cleanup_completed_operations(self, older_than_hours: int = 48) -> int:
        """Remove completed operations older than specified time"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
            
            deleted_count = self.db.query(SyncQueue).filter(
                and_(
                    SyncQueue.status == SyncStatus.COMPLETED.value,
                    SyncQueue.completed_at < cutoff_time
                )
            ).delete()
            
            self.db.commit()
            
            print(f"🧹 Cleaned up {deleted_count} completed operations older than {older_than_hours} hours")
            return deleted_count
            
        except Exception as e:
            print(f"❌ Error cleaning up completed operations: {e}")
            self.db.rollback()
            return 0
    
    def get_operations_by_device(self, device_id: int, limit: int = 20) -> List[Dict]:
        """Get recent operations for a specific device"""
        try:
            operations = self.db.query(SyncQueue).filter(
                or_(
                    SyncQueue.record_id == f"device_{device_id}",
                    SyncQueue.payload.like(f'%"device_id": {device_id}%')
                )
            ).order_by(desc(SyncQueue.created_at)).limit(limit).all()
            
            return [
                {
                    "id": op.id,
                    "operation_type": op.operation_type,
                    "status": op.status,
                    "created_at": op.created_at,
                    "completed_at": op.completed_at,
                    "retry_count": op.retry_count,
                    "last_error": op.last_error
                }
                for op in operations
            ]
            
        except Exception as e:
            print(f"❌ Error getting operations by device: {e}")
            return []
    
    def retry_failed_operations(self, operation_type: str = None, device_id: int = None) -> int:
        """Retry failed operations with optional filtering"""
        try:
            query = self.db.query(SyncQueue).filter(
                SyncQueue.status == SyncStatus.FAILED.value,
                SyncQueue.retry_count < SyncQueue.max_retries
            )
            
            if operation_type:
                query = query.filter(SyncQueue.operation_type == operation_type)
            
            if device_id:
                query = query.filter(
                    or_(
                        SyncQueue.record_id == f"device_{device_id}",
                        SyncQueue.payload.like(f'%"device_id": {device_id}%')
                    )
                )
            
            operations = query.all()
            
            retry_count = 0
            for op in operations:
                op.status = SyncStatus.PENDING.value
                op.scheduled_at = datetime.now()
                retry_count += 1
            
            self.db.commit()
            
            print(f"🔄 Retrying {retry_count} failed operations")
            return retry_count
            
        except Exception as e:
            print(f"❌ Error retrying failed operations: {e}")
            self.db.rollback()
            return 0


# Convenience function
def get_sync_queue_manager(db: Session) -> SyncQueueManager:
    """Get a sync queue manager instance"""
    return SyncQueueManager(db)