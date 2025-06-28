from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Device, SyncLog
from app.schemas.schemas import (
    SyncLog as SyncLogSchema,
    SyncRequest,
    SyncResponse
)

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
        # TODO: Implement actual device sync logic using pyzk library
        # This would involve:
        # 1. Connecting to the device using pyzk
        # 2. Fetching attendance records
        # 3. Syncing employee data if needed
        # 4. Storing records in the database
        
        # For now, we'll simulate a successful sync
        records_synced = 0
        
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