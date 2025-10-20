"""
Consolidated Attendance API - All attendance operations in one place
Replaces: attendance.py, attendance_calendar.py, calendar_api.py, simple_calendar.py
"""

from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import csv
import io

from app.core.database import get_db
from app.models.models import AttendanceRecord, Employee
from app.services.attendance_service import attendance_service
from app.services.device_service import device_service
from app.services.export_service import export_service

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
                "timestamp": record.timestamp.replace(tzinfo=timezone.utc).isoformat() if record.timestamp else None,
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
    """
    Get attendance summary for dashboard

    CACHE-FIRST ARCHITECTURE:
    - Serves data from cache (refreshed every 5 minutes by background scheduler)
    - No database query overhead, instant response from memory cache
    """
    try:
        from app.services.device_cache_service import device_cache_service

        # Get cached summary (includes metadata)
        cached_data = device_cache_service.get('attendance_summary', include_metadata=True)

        if cached_data is None:
            # Cache miss - fallback to direct query (graceful degradation)
            summary = attendance_service.get_attendance_summary()
            return {
                "data": summary,
                "cache_metadata": {
                    "cached_at": None,
                    "age_seconds": 0,
                    "stale": True,
                    "source": "direct_query"
                }
            }

        return cached_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Manual record creation endpoint removed - not used by frontend


@router.get("/employee/{employee_id}")
async def get_employee_attendance_by_id(
    employee_id: int,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db)
):
    """Get attendance records for a specific employee by ID (for individual attendance page)"""
    try:
        # Get employee by ID
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        # Get attendance records
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            employee_badge=employee.badge_number,
            limit=1000  # Higher limit for individual view
        )

        # Format records for the individual attendance page
        formatted_records = []
        for record in records:
            formatted_records.append({
                "id": record.id,
                "check_in_time": record.timestamp.isoformat() if record.punch_type == "IN" else None,
                "check_out_time": record.timestamp.isoformat() if record.punch_type == "OUT" else None,
                "punch_type": record.punch_type,
                "timestamp": record.timestamp.isoformat()
            })

        return {
            "employee_id": employee_id,
            "employee_name": employee.display_name,
            "records": formatted_records,
            "total": len(formatted_records)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employee/badge/{employee_badge}")
async def get_employee_attendance(
    employee_badge: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db)
):
    """Get attendance records for a specific employee by badge"""
    try:
        # Check if employee exists first
        employee = db.query(Employee).filter(Employee.badge_number == employee_badge).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

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
                    "timestamp": record.timestamp.replace(tzinfo=timezone.utc).isoformat() if record.timestamp else None,
                    "punch_type": record.punch_type,
                    "status": record.status,
                    "device_id": record.device_id,
                    "validation_message": record.validation_message  # Include for QR check-in detection
                }
                for record in records
            ],
            "total": len(records)
        }
    except HTTPException:
        raise
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
                    "timestamp": record.timestamp.replace(tzinfo=timezone.utc).isoformat() if record.timestamp else None,
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
    """Get sync status and device information (uses 10-minute cache to reduce device connections)"""
    try:
        from app.services.device_service_cached import cached_device_service
        device_status = cached_device_service.get_device_status()
        device = device_service.get_default_device()
        
        return {
            "status": "healthy" if device_status.get("connected", False) else "unhealthy",
            "device_status": device_status,
            "last_sync": device.last_sync.isoformat() if device and device.last_sync else None,
            "sync_available": device_status.get("connected", False),
            "last": device.last_sync.isoformat() if device and device.last_sync else None,  # Alternative field name
            "sync": device_status.get("connected", False)  # Alternative field name
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# EXPORT FUNCTIONALITY
# ============================================================================

@router.get("/export/csv")
async def export_attendance_csv(
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    streaming: bool = Query(False, description="Enable streaming for large datasets"),
    batch_size: int = Query(1000, description="Batch size for streaming"),
    db: Session = Depends(get_db)
):
    """Export attendance records as CSV file"""
    try:
        # Create export service instance
        service = export_service.__class__(db)
        
        # Convert dates to datetime for compatibility
        start_datetime = datetime.combine(start_date, datetime.min.time()) if start_date else None
        end_datetime = datetime.combine(end_date, datetime.max.time()) if end_date else None
        
        # Count records
        total_records = service.count_records(
            start_date=start_datetime,
            end_date=end_datetime
        )
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"attendance_export_{timestamp}.csv"
        
        # Return CSV response
        return service.export_to_csv(
            start_date=start_datetime,
            end_date=end_datetime,
            format_type="detailed",
            include_employee_names=True,
            include_device_names=True
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


# ============================================================================
# VALIDATION & STATISTICS
# ============================================================================

# Daily statistics endpoint removed - not used by frontend


# Record validation endpoint removed - not used by frontend


# ============================================================================
# HEALTH & STATUS
# ============================================================================

@router.get("/health")
async def attendance_health_check():
    """Health check for attendance system"""
    try:
        from app.services.device_service_cached import cached_device_service
        device_status = cached_device_service.get_device_status()
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



