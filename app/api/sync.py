from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.models.models import Device, SyncLog, SyncQueue, DeviceStatusLog
from app.schemas.schemas import (
    SyncLog as SyncLogSchema,
    SyncRequest,
    SyncResponse
)
from app.services.cache_service import CacheService
from app.services.sync_queue_manager import SyncQueueManager, SyncOperationType
from app.services.connection_manager import DeviceConnectionManager, CircuitBreakerConfig
from app.services.conflict_resolver import ConflictResolver
from app.services.background_sync_service import get_sync_service

router = APIRouter()


async def perform_device_sync(device_id: int, sync_type: str, db: Session):
    """
    Background task to perform device synchronization.
    This is a placeholder for the actual sync logic that would use pyzk library.
    """
    sync_log = SyncLog(
        device_id=device_id,
        sync_type=sync_type,
        status="started",
        started_at=datetime.now()
    )
    db.add(sync_log)
    db.commit()
    
    try:
        # Implement actual device sync logic using pyzk library
        from zk import ZK
        from app.models.models import AttendanceRecord
        
        # Get device details
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise Exception(f"Device {device_id} not found")
        
        # Connect to ZKTeco device
        zk = ZK(device.ip_address, port=device.port, timeout=5, password=device.password or 0, force_udp=False, ommit_ping=False)
        conn = None
        records_synced = 0
        
        try:
            conn = zk.connect()
            conn.disable_device()
            
            # Get attendance records from device
            attendance_data = conn.get_attendance()
            
            # Process and store records
            for record in attendance_data:
                # Check if record already exists
                existing_record = db.query(AttendanceRecord).filter(
                    AttendanceRecord.employee_id == record.user_id,
                    AttendanceRecord.device_id == device_id,
                    AttendanceRecord.timestamp == record.timestamp
                ).first()
                
                if not existing_record:
                    # Create new attendance record
                    new_record = AttendanceRecord(
                        employee_id=record.user_id,
                        device_id=device_id,
                        timestamp=record.timestamp,
                        punch_type=record.punch,
                        is_valid=True
                    )
                    db.add(new_record)
                    records_synced += 1
            
            # Commit all new records
            db.commit()
            
        finally:
            if conn:
                conn.enable_device()
                conn.disconnect()
        
        # Update sync log
        sync_log.status = "success"
        sync_log.records_synced = records_synced
        sync_log.completed_at = datetime.now()
        
        # Update device last_sync timestamp
        device = db.query(Device).filter(Device.id == device_id).first()
        if device:
            device.last_sync = datetime.now()
        
        db.commit()
        
    except Exception as e:
        # Update sync log with error
        sync_log.status = "failed"
        sync_log.error_message = str(e)
        sync_log.completed_at = datetime.now()
        db.commit()
        raise


@router.post("/start", response_model=SyncResponse)
async def start_sync(
    sync_request: SyncRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Start a synchronization process for a device.
    """
    # Verify device exists and is active
    device = db.query(Device).filter(Device.id == sync_request.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.is_active:
        raise HTTPException(status_code=400, detail="Device is not active")
    
    # Check if there's already an ongoing sync for this device
    ongoing_sync = db.query(SyncLog).filter(
        SyncLog.device_id == sync_request.device_id,
        SyncLog.status == "started"
    ).first()
    
    if ongoing_sync:
        raise HTTPException(
            status_code=400,
            detail="Sync already in progress for this device"
        )
    
    # Add sync task to background
    background_tasks.add_task(
        perform_device_sync,
        sync_request.device_id,
        sync_request.sync_type,
        db
    )
    
    return SyncResponse(
        message=f"Sync started for device {device.name}",
        sync_log_id=None,
        records_synced=None
    )


@router.post("/all", response_model=List[SyncResponse])
async def sync_all_devices(
    background_tasks: BackgroundTasks,
    sync_type: str = "full",
    db: Session = Depends(get_db)
):
    """
    Start synchronization for all active devices.
    """
    active_devices = db.query(Device).filter(Device.is_active == True).all()
    
    if not active_devices:
        raise HTTPException(status_code=404, detail="No active devices found")
    
    responses = []
    for device in active_devices:
        # Check if device has ongoing sync
        ongoing_sync = db.query(SyncLog).filter(
            SyncLog.device_id == device.id,
            SyncLog.status == "started"
        ).first()
        
        if not ongoing_sync:
            background_tasks.add_task(
                perform_device_sync,
                device.id,
                sync_type,
                db
            )
            responses.append(
                SyncResponse(
                    message=f"Sync started for device {device.name}",
                    sync_log_id=None,
                    records_synced=None
                )
            )
        else:
            responses.append(
                SyncResponse(
                    message=f"Sync already in progress for device {device.name}",
                    sync_log_id=ongoing_sync.id,
                    records_synced=None
                )
            )
    
    return responses


@router.get("/logs", response_model=List[SyncLogSchema])
async def get_sync_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    device_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retrieve sync logs with optional filtering.
    """
    query = db.query(SyncLog)
    
    if device_id:
        query = query.filter(SyncLog.device_id == device_id)
    if status:
        query = query.filter(SyncLog.status == status)
    
    logs = query.order_by(SyncLog.started_at.desc()).offset(skip).limit(limit).all()
    return logs


@router.get("/logs/{sync_log_id}", response_model=SyncLogSchema)
async def get_sync_log(sync_log_id: int, db: Session = Depends(get_db)):
    """
    Get a specific sync log by ID.
    """
    sync_log = db.query(SyncLog).filter(SyncLog.id == sync_log_id).first()
    if not sync_log:
        raise HTTPException(status_code=404, detail="Sync log not found")
    return sync_log


@router.get("/status")
async def get_sync_status(db: Session = Depends(get_db)):
    """
    Get overall synchronization status for all devices.
    """
    devices = db.query(Device).all()
    device_status = []
    
    for device in devices:
        # Get latest sync log for device
        latest_sync = db.query(SyncLog).filter(
            SyncLog.device_id == device.id
        ).order_by(SyncLog.started_at.desc()).first()
        
        # Check for ongoing sync
        ongoing_sync = db.query(SyncLog).filter(
            SyncLog.device_id == device.id,
            SyncLog.status == "started"
        ).first()
        
        device_status.append({
            "device_id": device.id,
            "device_name": device.name,
            "is_active": device.is_active,
            "last_sync": device.last_sync,
            "sync_in_progress": ongoing_sync is not None,
            "latest_sync_status": latest_sync.status if latest_sync else None,
            "latest_sync_time": latest_sync.completed_at if latest_sync else None
        })
    
    return {
        "total_devices": len(devices),
        "active_devices": len([d for d in devices if d.is_active]),
        "devices": device_status
    }


@router.delete("/logs/old")
async def delete_old_sync_logs(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    """
    Delete sync logs older than specified days.
    """
    cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff_date = cutoff_date.replace(day=cutoff_date.day - days)
    
    deleted_count = db.query(SyncLog).filter(
        SyncLog.completed_at < cutoff_date
    ).delete()
    
    db.commit()
    
    return {
        "message": f"Deleted {deleted_count} sync logs older than {days} days",
        "deleted_count": deleted_count
    }


# Enhanced offline-first sync endpoints

@router.get("/health", response_model=Dict[str, Any])
async def get_sync_health(db: Session = Depends(get_db)):
    """
    Get overall synchronization system health using error classification
    """
    from app.core.feature_flags import FeatureFlags
    from app.services.health_calculator import HealthCalculator
    
    # Use intelligent health calculation if error classification is enabled
    if FeatureFlags.is_error_classification_enabled():
        # NEW: Use error classification for intelligent health assessment
        health_calculator = HealthCalculator(db)
        health_data = health_calculator.calculate_system_health(time_window_hours=1)
        
        return {
            "overall_health": health_data["overall_health"],
            "timestamp": datetime.now().isoformat(),
            "error_classification_enabled": True,
            "health_score": health_data["health_score"],
            "error_analysis": health_data["error_analysis"],
            "recommendation": health_data["recommendation"],
            "assessment_method": "error_classification"
        }
    
    else:
        # LEGACY: Original health calculation when feature flag is disabled
        cache_service = CacheService(db)
        sync_manager = SyncQueueManager(db)
        
        # Get queue statistics
        queue_stats = sync_manager.get_queue_statistics()
        
        # Get cache status
        cache_status = cache_service.get_cache_status()
        
        # Get background sync service status
        sync_service = get_sync_service()
        service_status = sync_service.get_status()
        
        # Calculate health score using legacy method
        total_operations = queue_stats.get("pending_count", 0) + queue_stats.get("completed_count", 0) + queue_stats.get("failed_count", 0)
        success_rate = (queue_stats.get("completed_count", 0) / max(total_operations, 1)) * 100
        
        health_score = "healthy"
        if success_rate < 50:
            health_score = "critical"
        elif success_rate < 80:
            health_score = "degraded"
        elif queue_stats.get("failed_count", 0) > 10:
            health_score = "warning"
        
        return {
            "overall_health": health_score,
            "timestamp": datetime.now().isoformat(),
            "error_classification_enabled": False,
            "sync_service": {
                "status": service_status["state"],
                "uptime_seconds": service_status["metrics"]["uptime_seconds"],
                "operations_processed": service_status["metrics"]["operations_processed"],
                "success_rate_percent": round(success_rate, 2)
            },
            "queue_status": queue_stats,
            "cache_status": {
                "active_entries": cache_status.get("active_entries", 0),
                "size_estimate_mb": round(cache_status.get("estimated_size_bytes", 0) / 1024 / 1024, 2),
                "expired_entries": cache_status.get("expired_entries", 0)
            },
            "assessment_method": "legacy_queue_stats"
        }


@router.get("/devices/{device_id}/health", response_model=Dict[str, Any])
async def get_device_health(
    device_id: int,
    include_history: bool = Query(False, description="Include recent health history"),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive device health status
    """
    # Verify device exists
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    connection_manager = DeviceConnectionManager(db, CircuitBreakerConfig())
    cache_service = CacheService(db)
    sync_manager = SyncQueueManager(db)
    
    # Perform live health check
    health_data = await connection_manager.health_check(device_id)
    
    # Get recent device operations
    recent_operations = sync_manager.get_operations_by_device(device_id, limit=10)
    
    return {
        "device_id": device_id,
        "device_name": device.name,
        "ip_address": device.ip_address,
        "current_health": health_data,
        "last_sync": device.last_sync.isoformat() if device.last_sync else None,
        "recent_operations": {
            "total": len(recent_operations),
            "successful": len([op for op in recent_operations if op.get("status") == "completed"]),
            "failed": len([op for op in recent_operations if op.get("status") == "failed"]),
            "pending": len([op for op in recent_operations if op.get("status") == "pending"])
        }
    }


@router.get("/queue", response_model=Dict[str, Any])
async def get_sync_queue_status(
    device_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, regex="^(pending|processing|completed|failed)$"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Get sync queue status and operations
    """
    sync_manager = SyncQueueManager(db)
    
    # Get queue statistics
    queue_stats = sync_manager.get_queue_statistics()
    
    # Get operations with filters
    if device_id:
        operations = sync_manager.get_operations_by_device(device_id, limit)
    else:
        operations = sync_manager.get_next_operations(limit)
    
    # Filter by status if requested
    if status_filter:
        operations = [op for op in operations if op.get("status") == status_filter]
    
    return {
        "queue_statistics": queue_stats,
        "operations": operations,
        "filters_applied": {
            "device_id": device_id,
            "status": status_filter,
            "limit": limit
        },
        "timestamp": datetime.now().isoformat()
    }


@router.post("/queue/retry-failed", response_model=Dict[str, Any])
async def retry_failed_operations(
    device_id: Optional[int] = None,
    operation_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retry failed sync operations
    """
    sync_manager = SyncQueueManager(db)
    
    retry_count = sync_manager.retry_failed_operations(
        operation_type=operation_type,
        device_id=device_id
    )
    
    return {
        "success": True,
        "operations_retried": retry_count,
        "filters": {
            "device_id": device_id,
            "operation_type": operation_type
        },
        "message": f"Retried {retry_count} failed operations"
    }


@router.post("/devices/{device_id}/force-sync", response_model=Dict[str, Any])
async def force_device_sync(
    device_id: int,
    sync_type: str = Query("incremental", regex="^(incremental|full)$"),
    db: Session = Depends(get_db)
):
    """
    Force immediate device synchronization
    """
    # Verify device exists
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    sync_manager = SyncQueueManager(db)
    
    # Queue appropriate sync operation
    if sync_type == "full":
        operation_id = sync_manager.queue_full_sync(device_id)
    else:
        last_sync = device.last_sync
        operation_id = sync_manager.queue_attendance_sync(device_id, last_sync)
    
    if operation_id:
        return {
            "sync_initiated": True,
            "operation_id": operation_id,
            "device_id": device_id,
            "sync_type": sync_type,
            "message": f"{sync_type.title()} sync queued for device {device_id}"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to queue sync operation"
        )


@router.get("/cache/status", response_model=Dict[str, Any])
async def get_cache_status(db: Session = Depends(get_db)):
    """
    Get cache status and statistics
    """
    cache_service = CacheService(db)
    
    cache_status = cache_service.get_cache_status()
    
    return {
        "cache_status": cache_status,
        "storage_usage": {
            "size_mb": round(cache_status.get("estimated_size_bytes", 0) / 1024 / 1024, 2),
            "entries": cache_status.get("total_cache_entries", 0),
            "active_entries": cache_status.get("active_entries", 0),
            "expired_entries": cache_status.get("expired_entries", 0)
        },
        "timestamp": datetime.now().isoformat()
    }


@router.post("/cache/refresh", response_model=Dict[str, Any])
async def refresh_cache(
    device_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Refresh cache entries and trigger sync
    """
    cache_service = CacheService(db)
    refreshed_count = 0
    
    if device_id:
        # Force refresh device-specific cache
        cache_service.delete_cache(f"attendance_data_device_{device_id}")
        refreshed_count += 1
        
        # Trigger background sync
        sync_manager = SyncQueueManager(db)
        operation_id = sync_manager.queue_attendance_sync(device_id)
        
        return {
            "success": True,
            "cache_entries_refreshed": refreshed_count,
            "sync_triggered": operation_id is not None,
            "operation_id": operation_id,
            "message": f"Cache refreshed and sync triggered for device {device_id}"
        }
    
    return {
        "success": True,
        "cache_entries_refreshed": refreshed_count,
        "message": "No device specified for cache refresh"
    }