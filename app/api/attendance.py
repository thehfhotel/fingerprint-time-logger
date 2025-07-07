from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
import uuid

from app.core.database import get_db
from app.models.models import AttendanceRecord, Employee, Device
from app.schemas.schemas import (
    AttendanceRecord as AttendanceRecordSchema,
    AttendanceRecordCreate,
    AttendanceRecordUpdate,
    AttendanceFilter
)
from app.services.cache_service import CacheService
from app.services.sync_queue_manager import SyncQueueManager, SyncOperationType
from app.services.export_service import SimpleExportService as AttendanceExportService

router = APIRouter()


@router.get("/", response_model=Dict[str, Any])
async def get_attendance_records(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    employee_id: Optional[str] = None,
    device_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    punch_type: Optional[int] = None,
    include_offline: bool = Query(True, description="Include cached offline data"),
    max_age_hours: int = Query(24, description="Maximum age of cached data in hours"),
    db: Session = Depends(get_db)
):
    """
    Retrieve attendance records with offline support.
    - Returns cached data if device offline
    - Includes freshness indicators
    - Supports filtering by data age
    """
    cache_service = CacheService(db)
    
    # Try to get fresh data from database first
    query = db.query(AttendanceRecord)
    
    # Apply filters
    filters = []
    if employee_id:
        filters.append(AttendanceRecord.employee_id == employee_id)
    if device_id:
        filters.append(AttendanceRecord.device_id == device_id)
    if start_date:
        filters.append(AttendanceRecord.timestamp >= start_date)
    if end_date:
        filters.append(AttendanceRecord.timestamp <= end_date)
    if punch_type is not None:
        filters.append(AttendanceRecord.punch_type == punch_type)
    
    if filters:
        query = query.filter(and_(*filters))
    
    # Get records from database
    db_records = query.order_by(desc(AttendanceRecord.timestamp)).offset(skip).limit(limit).all()
    
    # Convert to dict for response
    records_data = []
    for record in db_records:
        record_dict = {
            "id": record.id,
            "employee_id": record.employee_id,
            "device_id": record.device_id,
            "timestamp": record.timestamp.isoformat(),
            "punch_type": record.punch_type,
            "status": record.status,
            "sync_status": record.sync_status,
            "created_locally": record.created_locally,
            "created_at": record.created_at.isoformat() if record.created_at else None
        }
        records_data.append(record_dict)
    
    # Get cache status for data freshness
    cache_status = cache_service.get_cache_status()
    
    # Check if we should include cached data
    cached_data = None
    if include_offline and device_id:
        cached_attendance = cache_service.get_cached_attendance_data(device_id)
        if cached_attendance:
            cached_timestamp = datetime.fromisoformat(cached_attendance["cached_at"])
            age_hours = (datetime.now() - cached_timestamp).total_seconds() / 3600
            
            if age_hours <= max_age_hours:
                cached_data = {
                    "records": cached_attendance["records"],
                    "cached_at": cached_attendance["cached_at"],
                    "age_hours": round(age_hours, 2),
                    "record_count": cached_attendance["record_count"]
                }
    
    # Determine data freshness
    freshness_status = "fresh"
    if db_records:
        latest_record = db_records[0]
        if latest_record.created_at:
            age = (datetime.now() - latest_record.created_at).total_seconds() / 3600
            if age > 1:
                freshness_status = "recent" if age <= 24 else "stale"
        else:
            freshness_status = "unknown"
    
    return {
        "records": records_data,
        "total_count": len(records_data),
        "skip": skip,
        "limit": limit,
        "filters_applied": {
            "employee_id": employee_id,
            "device_id": device_id,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "punch_type": punch_type
        },
        "data_freshness": freshness_status,
        "offline_data_available": cached_data is not None,
        "cached_data": cached_data,
        "sync_status": {
            "pending_operations": cache_status.get("pending_sync_operations", 0),
            "cache_entries": cache_status.get("active_entries", 0)
        }
    }


@router.get("/{record_id}", response_model=AttendanceRecordSchema)
async def get_attendance_record(record_id: int, db: Session = Depends(get_db)):
    """
    Get a specific attendance record by ID.
    """
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    return record


@router.post("/", response_model=Dict[str, Any])
async def create_attendance_record(
    record: AttendanceRecordCreate,
    is_manual: bool = Query(False, description="Mark as manually created"),
    queue_sync: bool = Query(True, description="Queue for device sync"),
    db: Session = Depends(get_db)
):
    """
    Create a new attendance record with offline support.
    - Stores locally immediately
    - Queues for device sync when online
    - Returns local ID for tracking
    """
    # Verify employee exists
    employee = db.query(Employee).filter(Employee.employee_id == record.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Verify device exists
    device = db.query(Device).filter(Device.id == record.device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Create record with offline-first fields
    record_data = record.dict()
    record_data.update({
        "sync_status": "pending" if queue_sync else "local_only",
        "local_id": str(uuid.uuid4()),
        "created_locally": is_manual
    })
    
    db_record = AttendanceRecord(**record_data)
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    
    # Queue for sync if requested and manual
    operation_id = None
    if queue_sync and is_manual:
        sync_manager = SyncQueueManager(db)
        operation_id = sync_manager.queue_manual_attendance(
            employee_id=record.employee_id,
            device_id=record.device_id,
            timestamp=record.timestamp,
            punch_type=record.punch_type
        )
    
    # Cache the new record
    cache_service = CacheService(db)
    cached_data = cache_service.get_cached_attendance_data(record.device_id)
    if cached_data:
        # Add new record to cache
        new_record_data = {
            "employee_id": record.employee_id,
            "timestamp": record.timestamp.isoformat(),
            "punch_type": record.punch_type,
            "status": record.status or 0,
            "created_locally": is_manual
        }
        cached_data["records"].insert(0, new_record_data)
        cached_data["record_count"] += 1
        cache_service.cache_attendance_data(cached_data["records"], record.device_id)
    
    return {
        "record": {
            "id": db_record.id,
            "employee_id": db_record.employee_id,
            "device_id": db_record.device_id,
            "timestamp": db_record.timestamp.isoformat(),
            "punch_type": db_record.punch_type,
            "status": db_record.status,
            "sync_status": db_record.sync_status,
            "local_id": db_record.local_id,
            "created_locally": db_record.created_locally,
            "created_at": db_record.created_at.isoformat()
        },
        "sync_queued": operation_id is not None,
        "operation_id": operation_id,
        "message": "Attendance record created successfully"
    }


@router.put("/{record_id}", response_model=AttendanceRecordSchema)
async def update_attendance_record(
    record_id: int,
    record_update: AttendanceRecordUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing attendance record.
    """
    db_record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    update_data = record_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_record, field, value)
    
    db.commit()
    db.refresh(db_record)
    return db_record


@router.get("/export/csv")
async def export_attendance_csv(
    start_date: Optional[datetime] = Query(None, description="Start date for export (YYYY-MM-DD)"),
    end_date: Optional[datetime] = Query(None, description="End date for export (YYYY-MM-DD)"),
    employee_ids: Optional[List[str]] = Query(None, description="Filter by employee IDs"),
    device_ids: Optional[List[int]] = Query(None, description="Filter by device IDs"),
    punch_types: Optional[List[int]] = Query(None, description="Filter by punch types (0=check_in, 1=check_out)"),
    include_employee_names: bool = Query(True, description="Include Thai employee names"),
    include_device_names: bool = Query(True, description="Include device names"),
    format: str = Query("detailed", regex="^(detailed|summary|raw)$", description="Export format"),
    streaming: bool = Query(False, description="Enable streaming for large datasets"),
    batch_size: int = Query(1000, ge=100, le=10000, description="Records per batch when streaming"),
    max_records: Optional[int] = Query(None, ge=1, description="Optional limit on total records (None = unlimited)"),
    db: Session = Depends(get_db)
) -> StreamingResponse:
    """
    Export attendance records as CSV file with support for unlimited records
    
    Format options:
    - detailed: Full employee and device info with Thai names
    - summary: Daily summary with work hours calculation
    - raw: Database raw format for technical analysis
    
    Streaming is automatically enabled for exports > 10,000 records
    """
    try:
        export_service = AttendanceExportService(db)
        
        # Count total records to determine if streaming is needed
        total_records = export_service.count_records(
            start_date=start_date,
            end_date=end_date,
            employee_ids=employee_ids,
            device_ids=device_ids,
            punch_types=punch_types
        )
        
        # Auto-enable streaming for large datasets
        use_streaming = streaming or total_records > export_service.STREAMING_THRESHOLD
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"attendance_{format}_{timestamp}.csv"
        
        headers = {
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-Type": "text/csv; charset=utf-8",
            "X-Total-Records": str(total_records),
            "X-Export-Mode": "streaming" if use_streaming else "standard"
        }
        
        if use_streaming:
            # Use streaming for large exports
            def generate():
                yield from export_service.export_to_csv_streaming(
                    start_date=start_date,
                    end_date=end_date,
                    employee_ids=employee_ids,
                    device_ids=device_ids,
                    punch_types=punch_types,
                    format_type=format,
                    include_employee_names=include_employee_names,
                    include_device_names=include_device_names,
                    batch_size=batch_size,
                    max_records=max_records
                )
            
            return StreamingResponse(
                generate(),
                media_type="text/csv",
                headers=headers
            )
        else:
            # Use standard export for smaller datasets
            return export_service.export_to_csv(
                start_date=start_date,
                end_date=end_date,
                employee_ids=employee_ids,
                device_ids=device_ids,
                punch_types=punch_types,
                format_type=format,
                include_employee_names=include_employee_names,
                include_device_names=include_device_names
            )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Export failed: {str(e)}"
        )


@router.delete("/{record_id}")
async def delete_attendance_record(record_id: int, db: Session = Depends(get_db)):
    """
    Delete an attendance record.
    """
    db_record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    db.delete(db_record)
    db.commit()
    return {"message": "Attendance record deleted successfully"}


@router.get("/employee/{employee_id}", response_model=List[AttendanceRecordSchema])
async def get_employee_attendance(
    employee_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    """
    Get all attendance records for a specific employee.
    """
    query = db.query(AttendanceRecord).filter(AttendanceRecord.employee_id == employee_id)
    
    if start_date:
        query = query.filter(AttendanceRecord.timestamp >= start_date)
    if end_date:
        query = query.filter(AttendanceRecord.timestamp <= end_date)
    
    records = query.order_by(AttendanceRecord.timestamp.desc()).offset(skip).limit(limit).all()
    
    # Convert to response format with offline status
    records_data = []
    for record in records:
        record_dict = {
            "id": record.id,
            "employee_id": record.employee_id,
            "device_id": record.device_id,
            "timestamp": record.timestamp.isoformat(),
            "punch_type": record.punch_type,
            "status": record.status,
            "sync_status": getattr(record, 'sync_status', 'synced'),
            "created_locally": getattr(record, 'created_locally', False),
            "created_at": record.created_at.isoformat() if record.created_at else None
        }
        records_data.append(record_dict)
    
    return records_data


@router.get("/today/", response_model=List[AttendanceRecordSchema])
async def get_today_attendance(
    device_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Get today's attendance records.
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
    
    query = db.query(AttendanceRecord).filter(
        and_(
            AttendanceRecord.timestamp >= today_start,
            AttendanceRecord.timestamp <= today_end
        )
    )
    
    if device_id:
        query = query.filter(AttendanceRecord.device_id == device_id)
    
    records = query.order_by(AttendanceRecord.timestamp.desc()).all()
    
    # Convert to response format with offline status
    records_data = []
    for record in records:
        record_dict = {
            "id": record.id,
            "employee_id": record.employee_id,
            "device_id": record.device_id,
            "timestamp": record.timestamp.isoformat(),
            "punch_type": record.punch_type,
            "status": record.status,
            "sync_status": getattr(record, 'sync_status', 'synced'),
            "created_locally": getattr(record, 'created_locally', False),
            "created_at": record.created_at.isoformat() if record.created_at else None
        }
        records_data.append(record_dict)
    
    return records_data


# New offline-first endpoints

@router.get("/sync-status", response_model=Dict[str, Any])
async def get_attendance_sync_status(
    device_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Get synchronization status for attendance data
    - Last sync time
    - Pending operations count
    - Device connectivity status
    - Data freshness indicators
    """
    cache_service = CacheService(db)
    sync_manager = SyncQueueManager(db)
    
    # Get overall sync statistics
    sync_stats = sync_manager.get_queue_statistics()
    cache_status = cache_service.get_cache_status()
    
    response = {
        "sync_status": {
            "pending_operations": sync_stats.get("pending_count", 0),
            "completed_operations": sync_stats.get("completed_count", 0),
            "failed_operations": sync_stats.get("failed_count", 0),
            "ready_to_process": sync_stats.get("ready_to_process_count", 0)
        },
        "cache_status": {
            "active_entries": cache_status.get("active_entries", 0),
            "expired_entries": cache_status.get("expired_entries", 0),
            "estimated_size_bytes": cache_status.get("estimated_size_bytes", 0)
        },
        "data_freshness": {
            "last_updated": datetime.now().isoformat(),
            "stale_threshold_hours": 24
        }
    }
    
    # Add device-specific information if device_id provided
    if device_id:
        device_status = cache_service.get_device_status(device_id)
        device_operations = sync_manager.get_operations_by_device(device_id, limit=10)
        cached_attendance = cache_service.get_cached_attendance_data(device_id)
        
        response["device_status"] = {
            "device_id": device_id,
            "last_sync": device_status.get("last_successful_sync") if device_status else None,
            "status": device_status.get("status") if device_status else "unknown",
            "recent_operations": len(device_operations),
            "cached_records_available": cached_attendance is not None,
            "cached_record_count": cached_attendance.get("record_count", 0) if cached_attendance else 0
        }
    
    return response


@router.post("/manual", response_model=Dict[str, Any])
async def create_manual_attendance(
    employee_id: str,
    device_id: int,
    punch_type: int,
    timestamp: Optional[datetime] = None,
    queue_for_sync: bool = Query(True, description="Queue for device sync"),
    db: Session = Depends(get_db)
):
    """
    Create manual attendance entry (offline capable)
    - Stores locally immediately
    - Queues for device sync when online
    - Returns local ID for tracking
    """
    if timestamp is None:
        timestamp = datetime.now()
    
    # Verify employee exists
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Verify device exists
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Create manual attendance record
    db_record = AttendanceRecord(
        employee_id=employee_id,
        device_id=device_id,
        timestamp=timestamp,
        punch_type=punch_type,
        status=0,  # Normal status
        sync_status="pending" if queue_for_sync else "local_only",
        local_id=str(uuid.uuid4()),
        created_locally=True
    )
    
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    
    # Queue for sync if requested
    operation_id = None
    if queue_for_sync:
        sync_manager = SyncQueueManager(db)
        operation_id = sync_manager.queue_manual_attendance(
            employee_id=employee_id,
            device_id=device_id,
            timestamp=timestamp,
            punch_type=punch_type
        )
    
    return {
        "record_id": db_record.id,
        "local_id": db_record.local_id,
        "employee_id": employee_id,
        "device_id": device_id,
        "timestamp": timestamp.isoformat(),
        "punch_type": punch_type,
        "sync_queued": operation_id is not None,
        "operation_id": operation_id,
        "message": "Manual attendance entry created successfully"
    }


@router.get("/pending-sync", response_model=Dict[str, Any])
async def get_pending_sync_records(
    device_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Get attendance records pending synchronization
    """
    query = db.query(AttendanceRecord).filter(
        AttendanceRecord.sync_status.in_(["pending", "failed"])
    )
    
    if device_id:
        query = query.filter(AttendanceRecord.device_id == device_id)
    
    pending_records = query.order_by(desc(AttendanceRecord.created_at)).limit(limit).all()
    
    # Get sync operations for these records
    sync_manager = SyncQueueManager(db)
    operations = sync_manager.get_queue_statistics()
    
    records_data = []
    for record in pending_records:
        record_dict = {
            "id": record.id,
            "local_id": record.local_id,
            "employee_id": record.employee_id,
            "device_id": record.device_id,
            "timestamp": record.timestamp.isoformat(),
            "punch_type": record.punch_type,
            "sync_status": record.sync_status,
            "created_locally": record.created_locally,
            "created_at": record.created_at.isoformat() if record.created_at else None
        }
        records_data.append(record_dict)
    
    return {
        "pending_records": records_data,
        "total_pending": len(records_data),
        "queue_status": {
            "pending_operations": operations.get("pending_count", 0),
            "failed_operations": operations.get("failed_count", 0),
            "processing_operations": operations.get("processing_count", 0)
        },
        "last_updated": datetime.now().isoformat()
    }


@router.post("/force-sync/{device_id}", response_model=Dict[str, Any])
async def force_attendance_sync(
    device_id: int,
    sync_type: str = Query("incremental", regex="^(incremental|full)$"),
    db: Session = Depends(get_db)
):
    """
    Force immediate attendance synchronization for device
    """
    # Verify device exists
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    sync_manager = SyncQueueManager(db)
    
    # Queue sync operation based on type
    if sync_type == "full":
        operation_id = sync_manager.queue_full_sync(device_id)
    else:
        # Get last sync time for incremental sync
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


@router.get("/offline-data/{device_id}", response_model=Dict[str, Any])
async def get_offline_attendance_data(
    device_id: int,
    max_age_hours: int = Query(48, description="Maximum age of cached data in hours"),
    db: Session = Depends(get_db)
):
    """
    Get cached attendance data for offline access
    """
    cache_service = CacheService(db)
    
    # Get cached attendance data
    cached_data = cache_service.get_cached_attendance_data(device_id)
    
    if not cached_data:
        return {
            "device_id": device_id,
            "offline_data_available": False,
            "message": "No cached data available for this device"
        }
    
    # Check data age
    cached_timestamp = datetime.fromisoformat(cached_data["cached_at"])
    age_hours = (datetime.now() - cached_timestamp).total_seconds() / 3600
    
    if age_hours > max_age_hours:
        return {
            "device_id": device_id,
            "offline_data_available": False,
            "cached_age_hours": round(age_hours, 2),
            "max_age_hours": max_age_hours,
            "message": f"Cached data is too old ({age_hours:.1f} hours)"
        }
    
    return {
        "device_id": device_id,
        "offline_data_available": True,
        "records": cached_data["records"],
        "record_count": cached_data["record_count"],
        "cached_at": cached_data["cached_at"],
        "age_hours": round(age_hours, 2),
        "freshness": "fresh" if age_hours < 1 else "recent" if age_hours < 24 else "stale"
    }