"""
Consolidated Attendance API - All attendance operations in one place
Replaces: attendance.py, attendance_calendar.py, calendar_api.py, simple_calendar.py
"""

from datetime import datetime, date
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import AttendanceRecord, Employee
from app.services.attendance_service import attendance_service
from app.services.device_service import device_service

router = APIRouter()


# ============================================================================
# ATTENDANCE RECORDS - Basic CRUD Operations
# ============================================================================

@router.get("/", response_model=Dict[str, Any])
async def get_attendance_records(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    employee_badge: Optional[str] = Query(None, description="Employee badge filter"),
    limit: int = Query(100, description="Maximum records to return")
):
    """Get attendance records with optional filtering"""
    try:
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            employee_badge=employee_badge,
            limit=limit
        )
        
        # Convert to list format for API response
        record_list = []
        for record in records:
            record_list.append({
                "id": record.id,
                "employee_badge_number": record.employee_badge_number,
                "timestamp": record.timestamp,
                "punch_type": record.punch_type,
                "status": record.status,
                "device_id": record.device_id,
                "sync_status": record.sync_status
            })
        
        return {
            "records": record_list,
            "total": len(record_list),
            "filters": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "employee_badge": employee_badge
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_attendance_summary():
    """Get attendance summary for dashboard"""
    try:
        summary = attendance_service.get_attendance_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/")
async def create_attendance_record(
    employee_badge: str,
    punch_type: int,
    timestamp: Optional[datetime] = None,
    device_id: Optional[int] = None
):
    """Create a new attendance record"""
    try:
        if timestamp is None:
            timestamp = datetime.now()
        
        if device_id is None:
            device = device_service.get_default_device()
            device_id = device.id if device else 1
        
        record = attendance_service.create_attendance_record(
            employee_badge=employee_badge,
            timestamp=timestamp,
            punch_type=punch_type,
            device_id=device_id
        )
        
        return {
            "success": True,
            "record_id": record.id,
            "message": "Attendance record created successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employee/{employee_badge}")
async def get_employee_attendance(
    employee_badge: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(100)
):
    """Get attendance records for a specific employee"""
    try:
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            employee_badge=employee_badge,
            limit=limit
        )
        
        return {
            "employee_badge": employee_badge,
            "records": [
                {
                    "id": record.id,
                    "timestamp": record.timestamp,
                    "punch_type": record.punch_type,
                    "status": record.status,
                    "device_id": record.device_id
                }
                for record in records
            ],
            "total": len(records)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CALENDAR VIEWS - Simplified calendar functionality
# ============================================================================

@router.get("/calendar/config")
async def get_calendar_config():
    """Get calendar display configuration"""
    return {
        "violation_threshold_minutes": 15,
        "status_colors": {
            "perfect": "#22c55e",
            "minor_issue": "#eab308", 
            "violation": "#ef4444",
            "absent": "#9ca3af",
            "non_working": "#3b82f6"
        },
        "working_days": [1, 2, 3, 4, 5]  # Monday to Friday
    }


@router.get("/calendar/{year}/{month}")
async def get_calendar_data(year: int, month: int):
    """Get attendance data for calendar view"""
    try:
        # Get start and end dates for the month
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        
        # Get all attendance records for the month
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            limit=10000
        )
        
        # Group by employee and date
        calendar_data = {}
        for record in records:
            employee_badge = record.employee_badge_number
            record_date = record.timestamp.date().isoformat()
            
            if employee_badge not in calendar_data:
                calendar_data[employee_badge] = {}
            
            if record_date not in calendar_data[employee_badge]:
                calendar_data[employee_badge][record_date] = []
            
            calendar_data[employee_badge][record_date].append({
                "time": record.timestamp.strftime("%H:%M"),
                "type": "check-in" if record.punch_type == 0 else "check-out",
                "status": record.status
            })
        
        return {
            "year": year,
            "month": month,
            "calendar_data": calendar_data,
            "total_records": len(records)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/today")
async def get_today_attendance():
    """Get today's attendance records"""
    try:
        today = date.today()
        records = attendance_service.get_attendance_records(
            start_date=today,
            end_date=today,
            limit=1000
        )
        
        return {
            "date": today.isoformat(),
            "records": [
                {
                    "employee_badge": record.employee_badge_number,
                    "timestamp": record.timestamp,
                    "punch_type": record.punch_type,
                    "status": record.status
                }
                for record in records
            ],
            "total": len(records)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SYNC & DEVICE INTEGRATION
# ============================================================================

@router.post("/sync")
async def sync_attendance_from_device():
    """Sync attendance data from ZKTeco device"""
    try:
        result = device_service.sync_attendance_data()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync/status")
async def get_sync_status():
    """Get sync status and device information"""
    try:
        device_status = device_service.get_device_status()
        device = device_service.get_default_device()
        
        return {
            "device_status": device_status,
            "last_sync": device.last_sync.isoformat() if device and device.last_sync else None,
            "sync_available": device_status.get("connected", False)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# VALIDATION & STATISTICS
# ============================================================================

@router.get("/stats/daily")
async def get_daily_stats(target_date: Optional[date] = Query(None)):
    """Get daily attendance statistics"""
    try:
        if target_date is None:
            target_date = date.today()
        
        records = attendance_service.get_attendance_records(
            start_date=target_date,
            end_date=target_date,
            limit=1000
        )
        
        # Calculate basic stats
        check_ins = sum(1 for r in records if r.punch_type == 0)
        check_outs = sum(1 for r in records if r.punch_type == 1)
        unique_employees = len(set(r.employee_badge_number for r in records))
        
        return {
            "date": target_date.isoformat(),
            "total_records": len(records),
            "check_ins": check_ins,
            "check_outs": check_outs,
            "unique_employees": unique_employees,
            "completion_rate": round((check_outs / check_ins * 100) if check_ins > 0 else 0, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate/{record_id}")
async def validate_attendance_record(record_id: int, db: Session = Depends(get_db)):
    """Validate a specific attendance record"""
    try:
        record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")
        
        validation = attendance_service.validate_attendance_record(record)
        return validation
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HEALTH & STATUS
# ============================================================================

@router.get("/health")
async def attendance_health_check():
    """Health check for attendance system"""
    try:
        device_status = device_service.get_device_status()
        recent_records = attendance_service.get_attendance_records(limit=1)
        
        return {
            "status": "healthy",
            "device_connected": device_status.get("connected", False),
            "has_recent_data": len(recent_records) > 0,
            "last_record": recent_records[0].timestamp.isoformat() if recent_records else None
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }