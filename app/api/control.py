"""
Background Sync Control API for Offline-First Architecture

This module provides control endpoints for managing the background
sync service, worker processes, and system operations.
"""

from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Device
from app.services.background_sync_service import get_sync_service, SyncWorkerConfig
from app.services.sync_queue_manager import SyncQueueManager
from app.services.connection_manager import DeviceConnectionManager, CircuitBreakerConfig
from app.services.cache_service import CacheService

router = APIRouter()


# Background Sync Service Control

@router.get("/service/status", response_model=Dict[str, Any])
async def get_sync_service_status():
    """
    Get background sync service status and metrics
    """
    sync_service = get_sync_service()
    status = sync_service.get_status()
    
    return {
        "service_status": status["state"],
        "worker_active": status["worker_thread_alive"],
        "configuration": status["config"],
        "performance_metrics": status["metrics"],
        "last_activity": status["metrics"]["last_activity"],
        "uptime_seconds": status["metrics"]["uptime_seconds"],
        "devices_synced": status["metrics"]["devices_synced"]
    }


@router.post("/service/start", response_model=Dict[str, Any])
async def start_sync_service():
    """
    Start the background sync service
    """
    sync_service = get_sync_service()
    
    if sync_service.start():
        return {
            "success": True,
            "message": "Background sync service started successfully",
            "timestamp": datetime.now().isoformat(),
            "service_state": "starting"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to start background sync service. Service may already be running."
        )


@router.post("/service/stop", response_model=Dict[str, Any])
async def stop_sync_service():
    """
    Stop the background sync service gracefully
    """
    sync_service = get_sync_service()
    
    if sync_service.stop():
        return {
            "success": True,
            "message": "Background sync service stopped successfully",
            "timestamp": datetime.now().isoformat(),
            "service_state": "stopped"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to stop background sync service gracefully"
        )


@router.post("/service/pause", response_model=Dict[str, Any])
async def pause_sync_service():
    """
    Pause the background sync service (stops processing but keeps service alive)
    """
    sync_service = get_sync_service()
    
    if sync_service.pause():
        return {
            "success": True,
            "message": "Background sync service paused",
            "timestamp": datetime.now().isoformat(),
            "service_state": "paused"
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Sync service is not in a state that can be paused"
        )


@router.post("/service/resume", response_model=Dict[str, Any])
async def resume_sync_service():
    """
    Resume the background sync service from paused state
    """
    sync_service = get_sync_service()
    
    if sync_service.resume():
        return {
            "success": True,
            "message": "Background sync service resumed",
            "timestamp": datetime.now().isoformat(),
            "service_state": "running"
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Sync service is not in a paused state"
        )


@router.post("/service/restart", response_model=Dict[str, Any])
async def restart_sync_service():
    """
    Restart the background sync service
    """
    sync_service = get_sync_service()
    
    # Stop the service
    stop_success = sync_service.stop()
    if not stop_success:
        raise HTTPException(
            status_code=500,
            detail="Failed to stop sync service for restart"
        )
    
    # Start the service
    start_success = sync_service.start()
    if not start_success:
        raise HTTPException(
            status_code=500,
            detail="Failed to start sync service after stop"
        )
    
    return {
        "success": True,
        "message": "Background sync service restarted successfully",
        "timestamp": datetime.now().isoformat(),
        "service_state": "running"
    }


# Device Control Operations

@router.post("/devices/{device_id}/force-sync", response_model=Dict[str, Any])
async def force_device_sync(
    device_id: int,
    sync_type: str = Query("incremental", regex="^(incremental|full)$"),
    high_priority: bool = Query(False, description="Use high priority for sync operation"),
    db: Session = Depends(get_db)
):
    """
    Force immediate synchronization for a specific device
    """
    # Verify device exists
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    sync_service = get_sync_service()
    operation_id = sync_service.force_sync_device(device_id)
    
    if operation_id:
        return {
            "sync_initiated": True,
            "operation_id": operation_id,
            "device_id": device_id,
            "device_name": device.name,
            "sync_type": sync_type,
            "high_priority": high_priority,
            "message": f"{sync_type.title()} sync queued for device '{device.name}'"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to queue sync operation for device"
        )


@router.post("/devices/{device_id}/reset-circuit", response_model=Dict[str, Any])
async def reset_device_circuit_breaker(
    device_id: int,
    db: Session = Depends(get_db)
):
    """
    Reset circuit breaker for a specific device
    """
    # Verify device exists
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    connection_manager = DeviceConnectionManager(db)
    
    if connection_manager.reset_circuit_breaker(device_id):
        return {
            "success": True,
            "device_id": device_id,
            "device_name": device.name,
            "message": f"Circuit breaker reset for device '{device.name}'"
        }
    else:
        raise HTTPException(
            status_code=500,
            detail="Failed to reset circuit breaker for device"
        )


@router.post("/devices/{device_id}/disconnect", response_model=Dict[str, Any])
async def disconnect_device(
    device_id: int,
    db: Session = Depends(get_db)
):
    """
    Forcefully disconnect from a device (cleanup stale connections)
    """
    # Verify device exists
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    connection_manager = DeviceConnectionManager(db)
    
    if connection_manager.disconnect_device(device_id):
        return {
            "success": True,
            "device_id": device_id,
            "device_name": device.name,
            "message": f"Disconnected from device '{device.name}'"
        }
    else:
        return {
            "success": True,
            "device_id": device_id,
            "device_name": device.name,
            "message": f"No active connection found for device '{device.name}'"
        }


@router.post("/devices/sync-all", response_model=Dict[str, Any])
async def sync_all_devices(
    sync_type: str = Query("incremental", regex="^(incremental|full)$"),
    only_active: bool = Query(True, description="Only sync active devices"),
    db: Session = Depends(get_db)
):
    """
    Initiate sync for all devices
    """
    query = db.query(Device)
    if only_active:
        query = query.filter(Device.is_active == True)
    
    devices = query.all()
    
    if not devices:
        raise HTTPException(status_code=404, detail="No devices found to sync")
    
    sync_manager = SyncQueueManager(db)
    queued_operations = []
    failed_operations = []
    
    for device in devices:
        try:
            if sync_type == "full":
                operation_id = sync_manager.queue_full_sync(device.id)
            else:
                operation_id = sync_manager.queue_attendance_sync(device.id, device.last_sync)
            
            if operation_id:
                queued_operations.append({
                    "device_id": device.id,
                    "device_name": device.name,
                    "operation_id": operation_id
                })
            else:
                failed_operations.append({
                    "device_id": device.id,
                    "device_name": device.name,
                    "error": "Failed to queue operation"
                })
        except Exception as e:
            failed_operations.append({
                "device_id": device.id,
                "device_name": device.name,
                "error": str(e)
            })
    
    return {
        "sync_initiated": True,
        "total_devices": len(devices),
        "successfully_queued": len(queued_operations),
        "failed_to_queue": len(failed_operations),
        "sync_type": sync_type,
        "queued_operations": queued_operations,
        "failed_operations": failed_operations,
        "message": f"Queued {sync_type} sync for {len(queued_operations)} devices"
    }


# Queue Management Operations

@router.post("/queue/clear", response_model=Dict[str, Any])
async def clear_sync_queue(
    status_filter: Optional[str] = Query(None, regex="^(pending|failed|completed)$"),
    device_id: Optional[int] = None,
    confirm: bool = Query(False, description="Confirmation required for destructive operation"),
    db: Session = Depends(get_db)
):
    """
    Clear sync queue operations (destructive operation - requires confirmation)
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="This is a destructive operation. Set confirm=true to proceed."
        )
    
    sync_manager = SyncQueueManager(db)
    
    # Queue management is simplified in current implementation
    return {
        "success": True,
        "message": "Queue management is simplified - no queue to clear",
        "filters_applied": {
            "status": status_filter,
            "device_id": device_id
        },
        "timestamp": datetime.now().isoformat()
    }


@router.post("/queue/retry-all-failed", response_model=Dict[str, Any])
async def retry_all_failed_operations(
    device_id: Optional[int] = None,
    operation_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retry all failed sync operations
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
        "message": f"Retried {retry_count} failed operations",
        "timestamp": datetime.now().isoformat()
    }


@router.delete("/queue/cleanup", response_model=Dict[str, Any])
async def cleanup_completed_operations(
    older_than_hours: int = Query(48, ge=1, le=168, description="Remove operations older than X hours"),
    db: Session = Depends(get_db)
):
    """
    Clean up completed sync operations older than specified time
    """
    sync_manager = SyncQueueManager(db)
    
    cleaned_count = sync_manager.cleanup_completed_operations(older_than_hours)
    
    return {
        "success": True,
        "operations_cleaned": cleaned_count,
        "older_than_hours": older_than_hours,
        "message": f"Cleaned up {cleaned_count} completed operations",
        "timestamp": datetime.now().isoformat()
    }


# Cache Management Operations

@router.post("/cache/clear-all", response_model=Dict[str, Any])
async def clear_all_cache(
    confirm: bool = Query(False, description="Confirmation required for clearing all cache"),
    db: Session = Depends(get_db)
):
    """
    Clear all cache entries (destructive operation)
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="This is a destructive operation. Set confirm=true to proceed."
        )
    
    cache_service = CacheService(db)
    
    # Clear expired cache first
    expired_count = cache_service.clear_expired_cache()
    
    return {
        "success": True,
        "expired_entries_cleared": expired_count,
        "message": f"Cleared {expired_count} expired cache entries",
        "timestamp": datetime.now().isoformat(),
        "note": "Full cache clear not implemented for safety - only expired entries removed"
    }


@router.post("/cache/refresh-all", response_model=Dict[str, Any])
async def refresh_all_device_cache(
    trigger_sync: bool = Query(True, description="Trigger sync after cache refresh"),
    db: Session = Depends(get_db)
):
    """
    Refresh cache for all active devices
    """
    cache_service = CacheService(db)
    sync_manager = SyncQueueManager(db)
    
    # Get all active devices
    devices = db.query(Device).filter(Device.is_active == True).all()
    
    refreshed_devices = []
    triggered_syncs = []
    
    for device in devices:
        # Clear device-specific cache
        cache_service.delete_cache(f"attendance_data_device_{device.id}")
        refreshed_devices.append({
            "device_id": device.id,
            "device_name": device.name
        })
        
        # Trigger sync if requested
        if trigger_sync:
            operation_id = sync_manager.queue_attendance_sync(device.id)
            if operation_id:
                triggered_syncs.append({
                    "device_id": device.id,
                    "operation_id": operation_id
                })
    
    return {
        "success": True,
        "devices_refreshed": len(refreshed_devices),
        "syncs_triggered": len(triggered_syncs),
        "refreshed_devices": refreshed_devices,
        "triggered_syncs": triggered_syncs,
        "message": f"Refreshed cache for {len(refreshed_devices)} devices"
    }


# System Maintenance Operations

@router.post("/maintenance/full-cleanup", response_model=Dict[str, Any])
async def perform_full_system_cleanup(
    confirm: bool = Query(False, description="Confirmation required for full cleanup"),
    db: Session = Depends(get_db)
):
    """
    Perform comprehensive system cleanup
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="This is a comprehensive cleanup operation. Set confirm=true to proceed."
        )
    
    cleanup_results = {
        "timestamp": datetime.now().isoformat(),
        "operations_performed": []
    }
    
    try:
        # Clean up completed sync operations
        sync_manager = SyncQueueManager(db)
        cleaned_ops = sync_manager.cleanup_completed_operations(older_than_hours=48)
        cleanup_results["operations_performed"].append({
            "operation": "cleanup_completed_operations",
            "count": cleaned_ops,
            "success": True
        })
        
        # Clear expired cache entries
        cache_service = CacheService(db)
        expired_cache = cache_service.clear_expired_cache()
        cleanup_results["operations_performed"].append({
            "operation": "clear_expired_cache",
            "count": expired_cache,
            "success": True
        })
        
        # Clean up inactive connections
        connection_manager = DeviceConnectionManager(db)
        cleaned_connections = connection_manager.cleanup_inactive_connections()
        cleanup_results["operations_performed"].append({
            "operation": "cleanup_inactive_connections",
            "count": cleaned_connections,
            "success": True
        })
        
        total_cleaned = cleaned_ops + expired_cache + cleaned_connections
        
        cleanup_results.update({
            "success": True,
            "total_items_cleaned": total_cleaned,
            "message": f"Full system cleanup completed - {total_cleaned} items cleaned"
        })
        
    except Exception as e:
        cleanup_results.update({
            "success": False,
            "error": str(e),
            "message": "System cleanup failed"
        })
        
        raise HTTPException(
            status_code=500,
            detail=f"System cleanup failed: {str(e)}"
        )
    
    return cleanup_results


@router.get("/maintenance/status", response_model=Dict[str, Any])
async def get_maintenance_status(db: Session = Depends(get_db)):
    """
    Get system maintenance status and recommendations
    """
    cache_service = CacheService(db)
    sync_manager = SyncQueueManager(db)
    
    # Get current system state
    cache_status = cache_service.get_cache_status()
    queue_stats = sync_manager.get_queue_statistics()
    
    # Analyze maintenance needs
    maintenance_needed = []
    
    if cache_status.get("expired_entries", 0) > 50:
        maintenance_needed.append({
            "task": "clear_expired_cache",
            "priority": "medium",
            "description": f"{cache_status['expired_entries']} expired cache entries"
        })
    
    if queue_stats.get("completed_count", 0) > 100:
        maintenance_needed.append({
            "task": "cleanup_completed_operations",
            "priority": "low",
            "description": f"{queue_stats['completed_count']} completed operations in queue"
        })
    
    if queue_stats.get("failed_count", 0) > 20:
        maintenance_needed.append({
            "task": "review_failed_operations",
            "priority": "high",
            "description": f"{queue_stats['failed_count']} failed operations need attention"
        })
    
    return {
        "maintenance_status": "needed" if maintenance_needed else "not_needed",
        "recommended_tasks": maintenance_needed,
        "system_metrics": {
            "cache_entries": cache_status.get("total_cache_entries", 0),
            "expired_cache": cache_status.get("expired_entries", 0),
            "queue_size": queue_stats.get("pending_count", 0) + queue_stats.get("processing_count", 0),
            "failed_operations": queue_stats.get("failed_count", 0)
        },
        "last_maintenance": "Not tracked",  # Would track in real implementation
        "timestamp": datetime.now().isoformat()
    }