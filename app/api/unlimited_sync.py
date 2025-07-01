"""
Enhanced Sync API with Unlimited Historical Data Support
Provides endpoints for complete dataset synchronization
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.models.models import Device, SyncLog
from app.services.unlimited_sync_service import (
    UnlimitedSyncService, 
    SyncConfiguration, 
    SyncMetrics,
    ProcessingStrategy,
    sync_device_full_historical,
    sync_device_incremental
)

router = APIRouter()

# Global progress tracking
active_syncs: Dict[str, SyncMetrics] = {}


class SyncRequest(BaseModel):
    device_id: int
    chunk_size: int = Field(default=100, description="Records per processing chunk")
    batch_commit_size: int = Field(default=500, description="Database commit batch size")
    processing_strategy: str = Field(default="balanced", description="Processing strategy (memory_efficient, speed_optimized, balanced)")


class DateRangeSyncRequest(SyncRequest):
    start_date: datetime = Field(description="Start date for sync (ISO format)")
    end_date: datetime = Field(description="End date for sync (ISO format)")


class SyncResponse(BaseModel):
    sync_id: str
    message: str
    device_name: str
    estimated_records: Optional[int] = None
    progress_url: str


class SyncProgressResponse(BaseModel):
    sync_id: str
    device_name: str
    metrics: Dict[str, Any]
    is_running: bool
    completion_percentage: float
    estimated_time_remaining: Optional[str] = None


# Background task functions
async def execute_full_historical_sync_task(sync_id: str, device: Device, db: Session, config: SyncConfiguration):
    """Background task for full historical sync"""
    try:
        sync_service = UnlimitedSyncService(device, db, config)
        metrics = await sync_service.sync_full_historical_data()
        active_syncs[sync_id] = metrics
    except Exception as e:
        error_metrics = SyncMetrics(
            device_name=device.name,
            is_running=False,
            error_message=str(e)
        )
        active_syncs[sync_id] = error_metrics


async def execute_incremental_sync_task(sync_id: str, device: Device, db: Session, config: SyncConfiguration):
    """Background task for incremental sync"""
    try:
        sync_service = UnlimitedSyncService(device, db, config)
        metrics = await sync_service.sync_incremental_updates()
        active_syncs[sync_id] = metrics
    except Exception as e:
        error_metrics = SyncMetrics(
            device_name=device.name,
            is_running=False,
            error_message=str(e)
        )
        active_syncs[sync_id] = error_metrics


async def execute_date_range_sync_task(
    sync_id: str, 
    device: Device, 
    db: Session, 
    config: SyncConfiguration,
    start_date: datetime,
    end_date: datetime
):
    """Background task for date range sync"""
    try:
        sync_service = UnlimitedSyncService(device, db, config)
        metrics = await sync_service.sync_date_range(start_date, end_date)
        active_syncs[sync_id] = metrics
    except Exception as e:
        error_metrics = SyncMetrics(
            device_name=device.name,
            is_running=False,
            error_message=str(e)
        )
        active_syncs[sync_id] = error_metrics


@router.post("/unlimited/full-historical/{device_id}", response_model=SyncResponse)
async def start_full_historical_sync(
    device_id: int,
    background_tasks: BackgroundTasks,
    chunk_size: int = Query(default=100, description="Records per processing chunk"),
    batch_commit_size: int = Query(default=500, description="Database commit batch size"),
    processing_strategy: str = Query(default="balanced", description="Processing strategy"),
    db: Session = Depends(get_db)
):
    """
    Start unlimited full historical data synchronization
    Retrieves ALL records from device without limitations
    """
    # Validate device
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.is_active:
        raise HTTPException(status_code=400, detail="Device is not active")
    
    # Check for ongoing sync
    ongoing_sync = db.query(SyncLog).filter(
        SyncLog.device_id == device_id,
        SyncLog.status == "in_progress"
    ).first()
    
    if ongoing_sync:
        raise HTTPException(
            status_code=400,
            detail="Sync already in progress for this device"
        )
    
    # Generate sync ID
    sync_id = f"full_historical_{device_id}_{int(datetime.now().timestamp())}"
    
    # Create configuration
    strategy_map = {
        "memory_efficient": ProcessingStrategy.MEMORY_EFFICIENT,
        "speed_optimized": ProcessingStrategy.SPEED_OPTIMIZED,
        "balanced": ProcessingStrategy.BALANCED
    }
    
    config = SyncConfiguration(
        chunk_size=chunk_size,
        batch_commit_size=batch_commit_size,
        processing_strategy=strategy_map.get(processing_strategy, ProcessingStrategy.BALANCED),
        enable_detailed_logging=True
    )
    
    # Start background sync
    background_tasks.add_task(
        execute_full_historical_sync_task,
        sync_id, device, db, config
    )
    
    return SyncResponse(
        sync_id=sync_id,
        message=f"Full historical sync started for device {device.name}",
        device_name=device.name,
        progress_url=f"/api/unlimited-sync/progress/{sync_id}"
    )


@router.post("/unlimited/incremental/{device_id}", response_model=SyncResponse)
async def start_incremental_sync(
    device_id: int,
    background_tasks: BackgroundTasks,
    chunk_size: int = Query(default=50, description="Records per processing chunk"),
    stop_on_duplicates: int = Query(default=3, description="Stop after N consecutive duplicate chunks"),
    db: Session = Depends(get_db)
):
    """
    Start incremental synchronization
    Only syncs new records since last successful sync
    """
    # Validate device
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.is_active:
        raise HTTPException(status_code=400, detail="Device is not active")
    
    # Generate sync ID
    sync_id = f"incremental_{device_id}_{int(datetime.now().timestamp())}"
    
    # Create configuration optimized for incremental sync
    config = SyncConfiguration(
        chunk_size=chunk_size,
        batch_commit_size=200,  # Smaller batches for incremental
        stop_on_duplicate_threshold=stop_on_duplicates,
        processing_strategy=ProcessingStrategy.SPEED_OPTIMIZED,
        enable_detailed_logging=False  # Less logging for frequent incremental syncs
    )
    
    # Start background sync
    background_tasks.add_task(
        execute_incremental_sync_task,
        sync_id, device, db, config
    )
    
    return SyncResponse(
        sync_id=sync_id,
        message=f"Incremental sync started for device {device.name}",
        device_name=device.name,
        progress_url=f"/api/unlimited-sync/progress/{sync_id}"
    )


@router.post("/unlimited/date-range/{device_id}", response_model=SyncResponse)
async def start_date_range_sync(
    device_id: int,
    request: DateRangeSyncRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Start date range synchronization
    Sync records within specific date range
    """
    # Validate device
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.is_active:
        raise HTTPException(status_code=400, detail="Device is not active")
    
    # Validate date range
    if request.start_date >= request.end_date:
        raise HTTPException(status_code=400, detail="Start date must be before end date")
    
    # Generate sync ID
    sync_id = f"date_range_{device_id}_{int(datetime.now().timestamp())}"
    
    # Create configuration
    strategy_map = {
        "memory_efficient": ProcessingStrategy.MEMORY_EFFICIENT,
        "speed_optimized": ProcessingStrategy.SPEED_OPTIMIZED,
        "balanced": ProcessingStrategy.BALANCED
    }
    
    config = SyncConfiguration(
        chunk_size=request.chunk_size,
        batch_commit_size=request.batch_commit_size,
        processing_strategy=strategy_map.get(request.processing_strategy, ProcessingStrategy.BALANCED)
    )
    
    # Start background sync
    background_tasks.add_task(
        execute_date_range_sync_task,
        sync_id, device, db, config, request.start_date, request.end_date
    )
    
    return SyncResponse(
        sync_id=sync_id,
        message=f"Date range sync started for device {device.name} ({request.start_date.date()} to {request.end_date.date()})",
        device_name=device.name,
        progress_url=f"/api/unlimited-sync/progress/{sync_id}"
    )


@router.get("/progress/{sync_id}", response_model=SyncProgressResponse)
async def get_sync_progress(sync_id: str):
    """
    Get real-time progress of a sync operation
    """
    if sync_id not in active_syncs:
        raise HTTPException(status_code=404, detail="Sync operation not found or expired")
    
    metrics = active_syncs[sync_id]
    
    # Calculate estimated time remaining
    estimated_time_remaining = None
    if metrics.is_running and metrics.records_per_second > 0:
        remaining_records = metrics.total_device_records - metrics.processed_records
        if remaining_records > 0:
            remaining_seconds = remaining_records / metrics.records_per_second
            estimated_time_remaining = f"{int(remaining_seconds // 60)}m {int(remaining_seconds % 60)}s"
    
    return SyncProgressResponse(
        sync_id=sync_id,
        device_name=metrics.device_name or "Unknown",
        metrics=metrics.to_dict(),
        is_running=metrics.is_running,
        completion_percentage=metrics.completion_percentage,
        estimated_time_remaining=estimated_time_remaining
    )


@router.get("/status/{device_id}")
async def get_device_sync_status(device_id: int, db: Session = Depends(get_db)):
    """
    Get current sync status for a device
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Get recent sync logs
    recent_syncs = db.query(SyncLog).filter(
        SyncLog.device_id == device_id
    ).order_by(SyncLog.started_at.desc()).limit(5).all()
    
    # Check for active sync
    active_sync = None
    for sync_id, metrics in active_syncs.items():
        if sync_id.endswith(str(device_id)) and metrics.is_running:
            active_sync = {
                "sync_id": sync_id,
                "progress": metrics.completion_percentage,
                "records_processed": metrics.processed_records
            }
            break
    
    return {
        "device_id": device_id,
        "device_name": device.name,
        "last_sync": device.last_sync.isoformat() if device.last_sync else None,
        "active_sync": active_sync,
        "recent_syncs": [
            {
                "id": sync.id,
                "sync_type": sync.sync_type,
                "status": sync.status,
                "started_at": sync.started_at.isoformat(),
                "completed_at": sync.completed_at.isoformat() if sync.completed_at else None,
                "records_synced": sync.records_synced,
                "error_message": sync.error_message
            }
            for sync in recent_syncs
        ]
    }


@router.delete("/cancel/{sync_id}")
async def cancel_sync_operation(sync_id: str):
    """
    Cancel an active sync operation
    """
    if sync_id not in active_syncs:
        raise HTTPException(status_code=404, detail="Sync operation not found")
    
    metrics = active_syncs[sync_id]
    if not metrics.is_running:
        raise HTTPException(status_code=400, detail="Sync operation is not running")
    
    # Mark as cancelled (the background task will check this)
    metrics.is_running = False
    metrics.error_message = "Cancelled by user"
    
    return {"message": "Sync operation cancelled", "sync_id": sync_id}


@router.get("/active-syncs")
async def get_active_syncs():
    """
    Get list of all active sync operations
    """
    active_list = []
    for sync_id, metrics in active_syncs.items():
        if metrics.is_running:
            active_list.append({
                "sync_id": sync_id,
                "device_name": metrics.device_name,
                "sync_mode": metrics.sync_mode,
                "progress": metrics.completion_percentage,
                "records_processed": metrics.processed_records,
                "started_at": metrics.start_time.isoformat() if metrics.start_time else None
            })
    
    return {"active_syncs": active_list}


@router.post("/cleanup-completed")
async def cleanup_completed_syncs():
    """
    Clean up completed sync operations from memory
    """
    completed_syncs = []
    for sync_id, metrics in list(active_syncs.items()):
        if not metrics.is_running:
            completed_syncs.append(sync_id)
            del active_syncs[sync_id]
    
    return {
        "message": f"Cleaned up {len(completed_syncs)} completed sync operations",
        "cleaned_sync_ids": completed_syncs
    }