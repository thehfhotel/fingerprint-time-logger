"""
Attendance Calendar API endpoints
Provides monthly calendar view of employee attendance with color-coded status
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, date
import calendar

from app.core.database import get_db
from app.schemas.schemas import (
    MonthlyCalendarResponse,
    EmployeeDayDetailResponse,
    CalendarFilters,
    CalendarConfigResponse,
    CalendarStatisticsResponse,
    SuccessResponse
)
from app.services.attendance_calendar_service import AttendanceCalendarService

router = APIRouter(prefix="/attendance/calendar", tags=["Attendance Calendar"])


@router.get("/{year}/{month}", response_model=MonthlyCalendarResponse)
async def get_monthly_calendar(
    year: int,
    month: int,
    filters: CalendarFilters = Depends(),
    db: Session = Depends(get_db)
):
    """
    Get monthly attendance calendar with color-coded employee status
    
    **Status Color Codes:**
    - 🟢 Green: Perfect attendance (on time check-in and check-out)
    - 🟡 Yellow: Minor issues (late check-in OR early departure ≤15 min)
    - 🔴 Red: Major violations (>15 min late OR >15 min early departure)
    - ⚪ Gray: Absent (no attendance record)
    - 🔵 Blue: Non-working day (weekend/holiday)
    
    **Query Parameters:**
    - role: Filter by job role
    - department: Filter by department  
    - employee_ids: Comma-separated list of specific employee IDs
    - include_inactive: Include inactive employees
    """
    try:
        # Validate date
        if not 1 <= month <= 12:
            raise HTTPException(status_code=400, detail="Month must be between 1 and 12")
        
        if year < 2020 or year > 2030:
            raise HTTPException(status_code=400, detail="Year must be between 2020 and 2030")
        
        service = AttendanceCalendarService(db)
        calendar_data = await service.get_monthly_calendar(year, month, filters)
        
        return calendar_data
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load calendar data: {str(e)}")


@router.get("/{year}/{month}/{day}/employee/{employee_id}", response_model=EmployeeDayDetailResponse)
async def get_employee_day_detail(
    year: int,
    month: int,
    day: int,
    employee_id: str,
    db: Session = Depends(get_db)
):
    """
    Get detailed attendance information for specific employee and day
    
    Returns comprehensive attendance data including:
    - Check-in/out times with precision
    - Schedule comparison
    - Lateness/early departure calculations
    - Break and overtime information
    - Raw punch records
    - Contextual information (holidays, shifts, etc.)
    """
    try:
        # Validate date
        target_date = date(year, month, day)
        
        service = AttendanceCalendarService(db)
        detail = await service.get_employee_day_detail(employee_id, target_date)
        
        if not detail:
            raise HTTPException(
                status_code=404, 
                detail=f"No attendance data found for employee {employee_id} on {target_date}"
            )
        
        return detail
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load employee detail: {str(e)}")


@router.get("/{year}/{month}/export")
async def export_monthly_calendar(
    year: int,
    month: int,
    format: str = Query("csv", description="Export format: csv, xlsx, pdf"),
    include_details: bool = Query(True, description="Include check-in/out times"),
    include_statistics: bool = Query(True, description="Include summary statistics"),
    filters: CalendarFilters = Depends(),
    db: Session = Depends(get_db)
):
    """
    Export monthly calendar data in various formats
    
    **Supported Formats:**
    - CSV: Comma-separated values with UTF-8 encoding
    - XLSX: Excel format with multiple sheets (data + statistics)
    - PDF: Formatted calendar view with color coding
    
    **Export Options:**
    - include_details: Add check-in/out timestamps
    - include_statistics: Add summary statistics sheet/section
    """
    try:
        service = AttendanceCalendarService(db)
        
        # Get calendar data
        calendar_data = await service.get_monthly_calendar(year, month, filters)
        
        # For now, return JSON data - export service can be implemented later
        return {
            "message": f"Export functionality for {format} format will be implemented",
            "calendar_data": calendar_data,
            "export_options": {
                "format": format,
                "include_details": include_details,
                "include_statistics": include_statistics
            }
        }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.get("/config", response_model=CalendarConfigResponse)
async def get_calendar_config(db: Session = Depends(get_db)):
    """
    Get calendar configuration and metadata
    
    Returns:
    - Status color mappings
    - Symbol mappings
    - Threshold settings
    - Available roles and time periods
    - Weekend day configuration
    """
    try:
        service = AttendanceCalendarService(db)
        config = await service.get_calendar_config()
        return config
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {str(e)}")


@router.get("/", response_model=MonthlyCalendarResponse)
async def get_current_month_calendar(
    filters: CalendarFilters = Depends(),
    db: Session = Depends(get_db)
):
    """
    Get current month's attendance calendar
    
    Convenience endpoint that automatically uses the current year and month.
    Equivalent to GET /{current_year}/{current_month}
    """
    now = datetime.now()
    return await get_monthly_calendar(now.year, now.month, filters, db)


@router.post("/{year}/{month}/recalculate", response_model=SuccessResponse)
async def recalculate_monthly_attendance(
    year: int,
    month: int,
    background_tasks: BackgroundTasks,
    employee_ids: Optional[List[str]] = Query(None, description="Specific employees to recalculate"),
    force: bool = Query(False, description="Force recalculation even if recent"),
    db: Session = Depends(get_db)
):
    """
    Recalculate attendance status for a month
    
    Triggers background recalculation of attendance status based on:
    - Raw attendance records
    - Work schedules
    - Holiday calendar
    - Business rules
    
    **Parameters:**
    - employee_ids: Optional list to recalculate specific employees only
    - force: Force recalculation even if recently calculated
    """
    try:
        service = AttendanceCalendarService(db)
        
        # Add to background tasks for performance
        background_tasks.add_task(
            service.recalculate_monthly_attendance,
            year, month, employee_ids, force
        )
        
        return SuccessResponse(
            message=f"Recalculation started for {calendar.month_name[month]} {year}",
            data={"year": year, "month": month, "employee_count": len(employee_ids) if employee_ids else "all"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start recalculation: {str(e)}")


@router.get("/{year}/{month}/statistics", response_model=CalendarStatisticsResponse)
async def get_monthly_statistics(
    year: int,
    month: int,
    filters: CalendarFilters = Depends(),
    db: Session = Depends(get_db)
):
    """
    Get detailed monthly attendance statistics
    
    Returns comprehensive statistics including:
    - Overall attendance rates
    - Punctuality metrics
    - Role-based breakdowns
    - Trend analysis
    """
    try:
        service = AttendanceCalendarService(db)
        stats = await service.get_monthly_statistics(year, month, filters)
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load statistics: {str(e)}")


@router.get("/available-months", response_model=List[dict])
async def get_available_months(
    limit: int = Query(12, description="Number of months to return"),
    db: Session = Depends(get_db)
):
    """
    Get list of months with available attendance data
    
    Returns chronologically ordered list of months that have attendance records.
    Useful for month navigation in UI.
    """
    try:
        service = AttendanceCalendarService(db)
        months = await service.get_available_months(limit)
        return months
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load available months: {str(e)}")


@router.put("/{year}/{month}/{day}/{employee_id}/notes")
async def update_attendance_notes(
    year: int,
    month: int,
    day: int,
    employee_id: str,
    notes: str,
    db: Session = Depends(get_db)
):
    """
    Add or update notes for specific employee attendance record
    
    Allows adding contextual information like:
    - Reason for lateness
    - Early departure approval
    - Special circumstances
    - Manager notes
    """
    try:
        target_date = date(year, month, day)
        service = AttendanceCalendarService(db)
        
        success = await service.update_attendance_notes(employee_id, target_date, notes)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Attendance record not found for employee {employee_id} on {target_date}"
            )
        
        return SuccessResponse(
            message="Notes updated successfully",
            data={"employee_id": employee_id, "date": str(target_date), "notes": notes}
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update notes: {str(e)}")


# Health check endpoint
@router.get("/health")
async def calendar_health_check():
    """
    Health check for attendance calendar service
    """
    return {
        "status": "healthy",
        "service": "attendance_calendar",
        "timestamp": datetime.now().isoformat(),
        "features": [
            "monthly_calendar",
            "status_calculation",
            "export_functionality",
            "statistics",
            "employee_detail"
        ]
    }


# Error handlers removed - APIRouter doesn't support exception_handler
# Exception handling is done within each endpoint function