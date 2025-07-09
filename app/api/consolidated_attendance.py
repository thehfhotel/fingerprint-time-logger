"""
Consolidated Attendance API - All attendance operations in one place
Replaces: attendance.py, attendance_calendar.py, calendar_api.py, simple_calendar.py
"""

from datetime import datetime, date
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import csv
import io

from app.core.database import get_db
from app.models.models import AttendanceRecord, Employee, AttendanceAdjustment
from app.services.attendance_service import attendance_service
from app.services.device_service import device_service
from app.services.export_service import export_service
from app.schemas.schemas import AttendanceAdjustmentCreate, AttendanceAdjustmentUpdate

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
            # Check if record has late marking adjustment
            late_adjustment = None
            if hasattr(record, 'adjustments') and record.adjustments:
                late_adjustment = next((adj for adj in record.adjustments if adj.adjustment_type == 'late_marking'), None)
            
            record_list.append({
                "id": record.id,
                "employee_badge_number": record.employee_badge_number,
                "timestamp": record.timestamp,
                "punch_type": record.punch_type,
                "status": record.status,
                "device_id": record.device_id,
                "sync_status": record.sync_status,
                "is_marked_late": late_adjustment.is_marked_late if late_adjustment else False,
                "late_reason": late_adjustment.late_reason if late_adjustment else None,
                "adjustment_id": late_adjustment.id if late_adjustment else None
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


# Manual record creation endpoint removed - not used by frontend


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


# ============================================================================
# LATE MARKING & ADJUSTMENTS
# ============================================================================

@router.post("/records/{record_id}/mark-late")
async def mark_attendance_late(
    record_id: int,
    adjustment_data: AttendanceAdjustmentCreate,
    db: Session = Depends(get_db)
):
    """Mark an attendance record as late"""
    try:
        # Verify attendance record exists
        record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Attendance record not found")
        
        # Check if late marking already exists
        existing_adjustment = db.query(AttendanceAdjustment).filter(
            AttendanceAdjustment.attendance_record_id == record_id,
            AttendanceAdjustment.adjustment_type == 'late_marking'
        ).first()
        
        if existing_adjustment:
            # Update existing adjustment
            existing_adjustment.is_marked_late = adjustment_data.is_marked_late
            existing_adjustment.late_reason = adjustment_data.late_reason
            existing_adjustment.notes = adjustment_data.notes
            existing_adjustment.adjusted_by = adjustment_data.adjusted_by
            existing_adjustment.adjustment_timestamp = datetime.now()
            db.commit()
            
            return {
                "success": True,
                "message": "Late marking updated successfully",
                "adjustment_id": existing_adjustment.id,
                "record_id": record_id
            }
        else:
            # Create new adjustment
            adjustment = AttendanceAdjustment(
                attendance_record_id=record_id,
                adjustment_type='late_marking',
                is_marked_late=adjustment_data.is_marked_late,
                late_reason=adjustment_data.late_reason,
                adjusted_by=adjustment_data.adjusted_by,
                adjustment_timestamp=datetime.now(),
                notes=adjustment_data.notes
            )
            
            db.add(adjustment)
            db.commit()
            db.refresh(adjustment)
            
            return {
                "success": True,
                "message": "Late marking created successfully",
                "adjustment_id": adjustment.id,
                "record_id": record_id
            }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/records/{record_id}/adjustments")
async def get_attendance_adjustments(
    record_id: int,
    db: Session = Depends(get_db)
):
    """Get all adjustments for an attendance record"""
    try:
        # Verify attendance record exists
        record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Attendance record not found")
        
        adjustments = db.query(AttendanceAdjustment).filter(
            AttendanceAdjustment.attendance_record_id == record_id
        ).all()
        
        return {
            "record_id": record_id,
            "adjustments": [
                {
                    "id": adj.id,
                    "adjustment_type": adj.adjustment_type,
                    "is_marked_late": adj.is_marked_late,
                    "late_reason": adj.late_reason,
                    "adjusted_by": adj.adjusted_by,
                    "adjustment_timestamp": adj.adjustment_timestamp.isoformat(),
                    "notes": adj.notes,
                    "created_at": adj.created_at.isoformat()
                }
                for adj in adjustments
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/records/{record_id}/adjustments/{adjustment_id}")
async def delete_attendance_adjustment(
    record_id: int,
    adjustment_id: int,
    db: Session = Depends(get_db)
):
    """Delete an attendance adjustment"""
    try:
        adjustment = db.query(AttendanceAdjustment).filter(
            AttendanceAdjustment.id == adjustment_id,
            AttendanceAdjustment.attendance_record_id == record_id
        ).first()
        
        if not adjustment:
            raise HTTPException(status_code=404, detail="Adjustment not found")
        
        db.delete(adjustment)
        db.commit()
        
        return {
            "success": True,
            "message": "Adjustment deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))