"""
Background Sync Service for Offline-First Architecture

This service orchestrates background synchronization operations,
managing the sync worker, handling retries, and coordinating
between the sync queue and device connections.
"""

import asyncio
import threading
import signal
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from dataclasses import dataclass
import json
import time
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from app.models.models import Device, AttendanceRecord, Employee, EmployeeThaiName, SyncQueue, ErrorEvent
from app.services.sync_queue_manager import SyncQueueManager, SyncOperationType, SyncStatus
from app.services.connection_manager import DeviceConnectionManager, CircuitBreakerConfig
from app.services.cache_service import CacheService
from app.services.error_classifier import ZKTecoErrorClassifier, ErrorSeverity
from app.core.database import get_db
from app.core.config import settings
from app.core.feature_flags import FeatureFlags


class SyncWorkerState(Enum):
    """Background sync worker states"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class SyncWorkerConfig:
    """Configuration for background sync worker"""
    worker_interval_seconds: int = 30        # How often to check for work
    max_concurrent_operations: int = 3       # Max parallel sync operations
    device_health_check_interval: int = 300  # Health check every 5 minutes
    queue_cleanup_interval: int = 3600       # Cleanup every hour
    max_operation_timeout: int = 300         # Max time for single operation (5 minutes)
    enable_incremental_sync: bool = True     # Use incremental sync when possible
    retry_failed_operations: bool = True     # Automatically retry failed operations


class BackgroundSyncService:
    """
    Background service that processes sync queue operations
    
    Features:
    - Asynchronous operation processing
    - Automatic retry with exponential backoff
    - Device health monitoring
    - Graceful shutdown handling
    - Performance metrics tracking
    """
    
    def __init__(self, config: SyncWorkerConfig = None):
        self.config = config or SyncWorkerConfig()
        self.state = SyncWorkerState.STOPPED
        self.worker_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        
        # Initialize database connection
        self.engine = create_engine(settings.database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Initialize services
        self._init_services()
        
        # Initialize error classifier
        self.error_classifier = ZKTecoErrorClassifier()
        
        # Performance tracking
        self.metrics = {
            "operations_processed": 0,
            "operations_succeeded": 0,
            "operations_failed": 0,
            "total_sync_time": 0,
            "avg_operation_time": 0,
            "last_activity": None,
            "start_time": None,
            "devices_synced": set(),
            "error_count": 0,
            "informational_events": 0,
            "recoverable_errors": 0,
            "critical_errors": 0
        }
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        print("🚀 BackgroundSyncService initialized")
    
    def _init_services(self) -> None:
        """Initialize service dependencies"""
        try:
            db = self.SessionLocal()
            self.sync_queue_manager = SyncQueueManager(db)
            self.connection_manager = DeviceConnectionManager(db, CircuitBreakerConfig())
            self.cache_service = CacheService(db)
            db.close()
            print("✅ Services initialized successfully")
        except Exception as e:
            print(f"❌ Failed to initialize services: {e}")
            raise
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        print(f"\n🛑 Received signal {signum}, initiating graceful shutdown...")
        self.stop()
    
    def start(self) -> bool:
        """Start the background sync service"""
        if self.state != SyncWorkerState.STOPPED:
            print(f"⚠️  Service already running (state: {self.state.value})")
            return False
        
        try:
            self.state = SyncWorkerState.STARTING
            self.stop_event.clear()
            
            # Start worker thread
            self.worker_thread = threading.Thread(
                target=self._worker_loop,
                name="BackgroundSyncWorker",
                daemon=True
            )
            self.worker_thread.start()
            
            # Wait for worker to start
            time.sleep(1)
            
            if self.state == SyncWorkerState.RUNNING:
                self.metrics["start_time"] = datetime.now()
                print("✅ Background sync service started successfully")
                return True
            else:
                print("❌ Failed to start background sync service")
                return False
                
        except Exception as e:
            print(f"❌ Error starting background sync service: {e}")
            self.state = SyncWorkerState.ERROR
            return False
    
    def stop(self) -> bool:
        """Stop the background sync service gracefully"""
        if self.state == SyncWorkerState.STOPPED:
            print("⚠️  Service already stopped")
            return True
        
        try:
            print("🛑 Stopping background sync service...")
            self.state = SyncWorkerState.STOPPING
            self.stop_event.set()
            
            # Wait for worker thread to finish
            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=30)  # 30 second timeout
                
                if self.worker_thread.is_alive():
                    print("⚠️  Worker thread did not stop gracefully within timeout")
                else:
                    print("✅ Worker thread stopped gracefully")
            
            # Cleanup connections
            self._cleanup_connections()
            
            self.state = SyncWorkerState.STOPPED
            print("✅ Background sync service stopped")
            return True
            
        except Exception as e:
            print(f"❌ Error stopping background sync service: {e}")
            self.state = SyncWorkerState.ERROR
            return False
    
    def pause(self) -> bool:
        """Pause the background sync service"""
        if self.state == SyncWorkerState.RUNNING:
            self.state = SyncWorkerState.PAUSED
            print("⏸️  Background sync service paused")
            return True
        return False
    
    def resume(self) -> bool:
        """Resume the background sync service"""
        if self.state == SyncWorkerState.PAUSED:
            self.state = SyncWorkerState.RUNNING
            print("▶️  Background sync service resumed")
            return True
        return False
    
    def _worker_loop(self) -> None:
        """Main worker loop that processes sync operations"""
        try:
            self.state = SyncWorkerState.RUNNING
            print("🔄 Background sync worker loop started")
            
            last_health_check = datetime.now()
            last_cleanup = datetime.now()
            
            while not self.stop_event.is_set():
                try:
                    # Skip processing if paused
                    if self.state == SyncWorkerState.PAUSED:
                        time.sleep(5)
                        continue
                    
                    # Process sync queue operations
                    self._process_sync_queue()
                    
                    # Periodic health checks
                    if (datetime.now() - last_health_check).total_seconds() >= self.config.device_health_check_interval:
                        self._perform_health_checks()
                        last_health_check = datetime.now()
                    
                    # Periodic cleanup
                    if (datetime.now() - last_cleanup).total_seconds() >= self.config.queue_cleanup_interval:
                        self._perform_cleanup()
                        last_cleanup = datetime.now()
                    
                    # Update activity timestamp
                    self.metrics["last_activity"] = datetime.now()
                    
                    # Sleep before next iteration
                    time.sleep(self.config.worker_interval_seconds)
                    
                except Exception as e:
                    print(f"❌ Error in worker loop: {e}")
                    self.metrics["error_count"] += 1
                    time.sleep(10)  # Longer sleep on error
            
            print("🔄 Background sync worker loop stopped")
            
        except Exception as e:
            print(f"❌ Fatal error in worker loop: {e}")
            self.state = SyncWorkerState.ERROR
    
    def _process_sync_queue(self) -> None:
        """Process pending sync queue operations"""
        try:
            db = self.SessionLocal()
            sync_queue_manager = SyncQueueManager(db)
            
            # Get next batch of operations
            operations = sync_queue_manager.get_next_operations(
                limit=self.config.max_concurrent_operations
            )
            
            if not operations:
                db.close()
                return
            
            print(f"📋 Processing {len(operations)} sync operations")
            
            # Process operations concurrently
            for operation in operations:
                if self.stop_event.is_set():
                    break
                
                self._process_single_operation(operation, db)
            
            db.close()
            
        except Exception as e:
            print(f"❌ Error processing sync queue: {e}")
    
    def _process_single_operation(self, operation: Dict, db: Session) -> None:
        """Process a single sync operation"""
        operation_id = operation["id"]
        operation_type = operation["operation_type"]
        start_time = time.time()
        
        try:
            print(f"🔄 Processing operation {operation_id}: {operation_type}")
            
            # Mark as processing
            sync_queue_manager = SyncQueueManager(db)
            sync_queue_manager.mark_processing(operation_id)
            
            # Process based on operation type
            success = False
            result_data = {}
            
            if operation_type == SyncOperationType.SYNC_ATTENDANCE.value:
                success, result_data = self._sync_attendance_data(operation, db)
            elif operation_type == SyncOperationType.SYNC_USERS.value:
                success, result_data = self._sync_user_data(operation, db)
            elif operation_type == SyncOperationType.DEVICE_HEALTH_CHECK.value:
                success, result_data = self._perform_device_health_check(operation, db)
            elif operation_type == SyncOperationType.MANUAL_ATTENDANCE.value:
                success, result_data = self._sync_manual_attendance(operation, db)
            elif operation_type == SyncOperationType.FULL_SYNC.value:
                success, result_data = self._perform_full_sync(operation, db)
            else:
                print(f"⚠️  Unknown operation type: {operation_type}")
                success = False
                result_data = {"error": f"Unknown operation type: {operation_type}"}
            
            # Update operation status
            if success:
                sync_queue_manager.mark_completed(operation_id, result_data)
                self.metrics["operations_succeeded"] += 1
                print(f"✅ Operation {operation_id} completed successfully")
            else:
                error_message = result_data.get("error", "Unknown error")
                sync_queue_manager.mark_failed(operation_id, error_message)
                self.metrics["operations_failed"] += 1
                print(f"❌ Operation {operation_id} failed: {error_message}")
            
            # Update metrics
            operation_time = time.time() - start_time
            self.metrics["operations_processed"] += 1
            self.metrics["total_sync_time"] += operation_time
            self.metrics["avg_operation_time"] = self.metrics["total_sync_time"] / self.metrics["operations_processed"]
            
        except Exception as e:
            # Check if error classification is enabled
            if FeatureFlags.is_error_classification_enabled():
                # Classify the error using new system
                error_context = {
                    "operation_id": operation_id,
                    "operation_type": operation_type,
                    "device_id": operation.get("payload", {}).get("device_id") if operation.get("payload") else None
                }
                classification = self.error_classifier.classify_exception(e, error_context)
            
            # Log with appropriate severity
            if classification.severity == ErrorSeverity.INFORMATIONAL:
                print(f"ℹ️  Informational: {classification.message}")
                self.metrics["informational_events"] += 1
            elif classification.severity == ErrorSeverity.WARNING:
                print(f"⚠️  Warning: {classification.message}")
            elif classification.severity == ErrorSeverity.RECOVERABLE:
                print(f"🔄 Recoverable error: {classification.message}")
                self.metrics["recoverable_errors"] += 1
            elif classification.severity == ErrorSeverity.CRITICAL:
                print(f"❌ Critical error: {classification.message}")
                self.metrics["critical_errors"] += 1
            else:  # FATAL
                print(f"💀 Fatal error: {classification.message}")
                self.metrics["critical_errors"] += 1
            
            # Store error event in database if it should count as failure
            if classification.should_count_as_failure:
                try:
                    error_event = ErrorEvent(
                        device_id=error_context.get("device_id"),
                        operation_type=operation_type,
                        severity=classification.severity.value,
                        category=classification.category.value,
                        error_message=classification.message,
                        context_data=classification.context,
                        timestamp=classification.timestamp,
                        should_count_as_failure=classification.should_count_as_failure,
                        user_visible=classification.user_visible,
                        suggested_recovery_time=classification.suggested_recovery_time,
                        pattern_hash=classification.pattern_hash
                    )
                    db.add(error_event)
                    db.commit()
                except Exception as db_error:
                    print(f"⚠️  Failed to store error event: {db_error}")
            
            # Update sync queue based on error classification
            try:
                sync_queue_manager = SyncQueueManager(db)
                
                if classification.should_count_as_failure:
                    # Mark as failed with appropriate retry logic
                    sync_queue_manager.mark_failed(
                        operation_id, 
                        classification.message,
                        retry_delay_seconds=classification.suggested_recovery_time
                    )
                    self.metrics["operations_failed"] += 1
                    self.metrics["error_count"] += 1
                else:
                    # Mark as completed for informational events
                    sync_queue_manager.mark_completed(
                        operation_id, 
                        {"message": classification.message, "severity": "informational"}
                    )
                    self.metrics["operations_succeeded"] += 1
                    
            except:
                pass  # Don't let cleanup errors propagate
                
            else:
                # Legacy error handling when feature flag is disabled
                error_message = str(e)
                print(f"❌ Exception processing operation {operation_id}: {error_message}")
                
                try:
                    sync_queue_manager = SyncQueueManager(db)
                    sync_queue_manager.mark_failed(operation_id, error_message)
                    self.metrics["operations_failed"] += 1
                    self.metrics["error_count"] += 1
                except:
                    pass  # Don't let cleanup errors propagate
    
    def _sync_attendance_data(self, operation: Dict, db: Session) -> tuple[bool, Dict]:
        """Sync attendance data from device"""
        try:
            payload = operation.get("payload", {})
            device_id = payload.get("device_id")
            sync_type = payload.get("sync_type", "incremental")
            since_timestamp = payload.get("since_timestamp")
            
            if not device_id:
                return False, {"error": "No device_id in payload"}
            
            # Get device connection
            connection_manager = DeviceConnectionManager(db)
            conn = asyncio.run(connection_manager.get_device_connection(device_id))
            
            if not conn:
                return False, {"error": f"Could not connect to device {device_id}"}
            
            # Get attendance data from device
            attendance_records = conn.get_attendance()
            
            if not attendance_records:
                return True, {"records_synced": 0, "message": "No attendance records found"}
            
            # Filter records if incremental sync
            if sync_type == "incremental" and since_timestamp:
                since_dt = datetime.fromisoformat(since_timestamp)
                attendance_records = [
                    record for record in attendance_records
                    if record.timestamp > since_dt
                ]
            
            # Process and store records
            records_synced = 0
            cache_service = CacheService(db)
            
            for record in attendance_records:
                try:
                    # Check if record already exists
                    existing = db.query(AttendanceRecord).filter(
                        AttendanceRecord.employee_id == str(record.user_id),
                        AttendanceRecord.device_id == device_id,
                        AttendanceRecord.timestamp == record.timestamp
                    ).first()
                    
                    if not existing:
                        # Create new attendance record
                        new_record = AttendanceRecord(
                            employee_id=str(record.user_id),
                            device_id=device_id,
                            timestamp=record.timestamp,
                            punch_type=record.punch,
                            status=record.status,
                            sync_status="synced",
                            created_locally=False
                        )
                        db.add(new_record)
                        records_synced += 1
                
                except Exception as e:
                    print(f"⚠️  Error processing attendance record: {e}")
                    continue
            
            db.commit()
            
            # Cache the synced data
            attendance_data = [
                {
                    "employee_id": str(record.user_id),
                    "timestamp": record.timestamp.isoformat(),
                    "punch_type": record.punch,
                    "status": record.status
                }
                for record in attendance_records
            ]
            cache_service.cache_attendance_data(attendance_data, device_id)
            
            # Update device last sync time
            device = db.query(Device).filter(Device.id == device_id).first()
            if device:
                device.last_sync = datetime.now()
                db.commit()
            
            # Track synced device
            self.metrics["devices_synced"].add(device_id)
            
            return True, {
                "records_synced": records_synced,
                "total_records": len(attendance_records),
                "sync_type": sync_type,
                "device_id": device_id
            }
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def _sync_user_data(self, operation: Dict, db: Session) -> tuple[bool, Dict]:
        """Sync user data from device"""
        try:
            payload = operation.get("payload", {})
            device_id = payload.get("device_id")
            
            if not device_id:
                return False, {"error": "No device_id in payload"}
            
            # Get device connection
            connection_manager = DeviceConnectionManager(db)
            conn = asyncio.run(connection_manager.get_device_connection(device_id))
            
            if not conn:
                return False, {"error": f"Could not connect to device {device_id}"}
            
            # Get users from device
            users = conn.get_users()
            
            if not users:
                return True, {"users_synced": 0, "message": "No users found on device"}
            
            # Process and store users
            users_synced = 0
            
            for user in users:
                try:
                    # Check if employee already exists
                    existing = db.query(Employee).filter(
                        Employee.employee_id == str(user.user_id)
                    ).first()
                    
                    if not existing:
                        # Create new employee record
                        new_employee = Employee(
                            employee_id=str(user.user_id),
                            name=user.name or f"User {user.user_id}",
                            is_active=True
                        )
                        db.add(new_employee)
                        users_synced += 1
                    else:
                        # Update existing employee if needed
                        if user.name and existing.name != user.name:
                            existing.name = user.name
                            users_synced += 1
                
                except Exception as e:
                    print(f"⚠️  Error processing user record: {e}")
                    continue
            
            db.commit()
            
            return True, {
                "users_synced": users_synced,
                "total_users": len(users),
                "device_id": device_id
            }
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def _perform_device_health_check(self, operation: Dict, db: Session) -> tuple[bool, Dict]:
        """Perform device health check"""
        try:
            payload = operation.get("payload", {})
            device_id = payload.get("device_id")
            
            if not device_id:
                return False, {"error": "No device_id in payload"}
            
            # Perform health check
            connection_manager = DeviceConnectionManager(db)
            health_data = asyncio.run(connection_manager.health_check(device_id))
            
            return health_data["healthy"], health_data
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def _sync_manual_attendance(self, operation: Dict, db: Session) -> tuple[bool, Dict]:
        """Sync manually entered attendance to device"""
        try:
            payload = operation.get("payload", {})
            
            # For now, just mark as successful since we store locally
            # In future, this could sync to device if needed
            return True, {"message": "Manual attendance stored locally"}
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def _perform_full_sync(self, operation: Dict, db: Session) -> tuple[bool, Dict]:
        """Perform full device synchronization"""
        try:
            payload = operation.get("payload", {})
            device_id = payload.get("device_id")
            
            if not device_id:
                return False, {"error": "No device_id in payload"}
            
            results = {}
            
            # Sync users first
            user_success, user_result = self._sync_user_data(operation, db)
            results["users"] = user_result
            
            # Then sync attendance
            attendance_success, attendance_result = self._sync_attendance_data(operation, db)
            results["attendance"] = attendance_result
            
            # Health check
            health_success, health_result = self._perform_device_health_check(operation, db)
            results["health"] = health_result
            
            overall_success = user_success and attendance_success and health_success
            
            return overall_success, {
                "full_sync_completed": overall_success,
                "results": results,
                "device_id": device_id
            }
            
        except Exception as e:
            return False, {"error": str(e)}
    
    def _perform_health_checks(self) -> None:
        """Perform periodic health checks on all active devices"""
        try:
            db = self.SessionLocal()
            devices = db.query(Device).filter(Device.is_active == True).all()
            
            sync_queue_manager = SyncQueueManager(db)
            
            for device in devices:
                # Queue health check operation
                sync_queue_manager.queue_device_health_check(device.id)
            
            db.close()
            
            if devices:
                print(f"🏥 Queued health checks for {len(devices)} devices")
                
        except Exception as e:
            print(f"❌ Error performing health checks: {e}")
    
    def _perform_cleanup(self) -> None:
        """Perform periodic cleanup tasks"""
        try:
            db = self.SessionLocal()
            
            # Cleanup completed operations
            sync_queue_manager = SyncQueueManager(db)
            cleaned_ops = sync_queue_manager.cleanup_completed_operations(older_than_hours=48)
            
            # Cleanup expired cache
            cache_service = CacheService(db)
            cleaned_cache = cache_service.clear_expired_cache()
            
            # Cleanup inactive connections
            connection_manager = DeviceConnectionManager(db)
            cleaned_connections = connection_manager.cleanup_inactive_connections()
            
            db.close()
            
            if cleaned_ops > 0 or cleaned_cache > 0 or cleaned_connections > 0:
                print(f"🧹 Cleanup completed: {cleaned_ops} operations, {cleaned_cache} cache entries, {cleaned_connections} connections")
                
        except Exception as e:
            print(f"❌ Error performing cleanup: {e}")
    
    def _cleanup_connections(self) -> None:
        """Cleanup all active connections"""
        try:
            db = self.SessionLocal()
            connection_manager = DeviceConnectionManager(db)
            
            # Get all active connections and disconnect them
            for device_id in list(connection_manager.active_connections.keys()):
                connection_manager.disconnect_device(device_id)
            
            db.close()
            print("🔌 All connections cleaned up")
            
        except Exception as e:
            print(f"❌ Error cleaning up connections: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current service status and metrics"""
        return {
            "state": self.state.value,
            "worker_thread_alive": self.worker_thread.is_alive() if self.worker_thread else False,
            "config": {
                "worker_interval_seconds": self.config.worker_interval_seconds,
                "max_concurrent_operations": self.config.max_concurrent_operations,
                "device_health_check_interval": self.config.device_health_check_interval
            },
            "metrics": {
                **self.metrics,
                "devices_synced": list(self.metrics["devices_synced"]),
                "start_time": self.metrics["start_time"].isoformat() if self.metrics["start_time"] else None,
                "last_activity": self.metrics["last_activity"].isoformat() if self.metrics["last_activity"] else None,
                "uptime_seconds": (datetime.now() - self.metrics["start_time"]).total_seconds() if self.metrics["start_time"] else 0
            }
        }
    
    def force_sync_device(self, device_id: int) -> str:
        """Force immediate sync for a specific device"""
        try:
            db = self.SessionLocal()
            sync_queue_manager = SyncQueueManager(db)
            
            operation_id = sync_queue_manager.queue_full_sync(device_id)
            db.close()
            
            if operation_id:
                print(f"🚀 Forced sync queued for device {device_id}")
                return operation_id
            else:
                print(f"❌ Failed to queue sync for device {device_id}")
                return None
                
        except Exception as e:
            print(f"❌ Error forcing sync for device {device_id}: {e}")
            return None


# Global service instance
_sync_service_instance: Optional[BackgroundSyncService] = None

def get_sync_service(config: SyncWorkerConfig = None) -> BackgroundSyncService:
    """Get singleton instance of background sync service"""
    global _sync_service_instance
    
    if _sync_service_instance is None:
        _sync_service_instance = BackgroundSyncService(config)
    
    return _sync_service_instance

def start_sync_service(config: SyncWorkerConfig = None) -> bool:
    """Start the global background sync service"""
    service = get_sync_service(config)
    return service.start()

def stop_sync_service() -> bool:
    """Stop the global background sync service"""
    global _sync_service_instance
    
    if _sync_service_instance:
        result = _sync_service_instance.stop()
        _sync_service_instance = None
        return result
    
    return True