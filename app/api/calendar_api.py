"""
Working Attendance Calendar API
Provides the endpoints expected by the frontend
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import Dict, List, Optional
from datetime import datetime, date, time
import calendar

from app.core.database import get_db
from app.models.models import (
    AttendanceRecord, EmployeeThaiName, Holiday, JobRole
)

router = APIRouter(prefix="/attendance/calendar", tags=["Attendance Calendar"])


@router.get("/config")
async def get_calendar_config():
    """Get calendar configuration for frontend"""
    return {
        "violation_threshold_minutes": 15,
        "minor_issue_threshold_minutes": 1,
        "weekend_days": [6, 0],  # Saturday, Sunday
        "status_colors": {
            "perfect": "#22c55e",      # Green
            "minor_issue": "#eab308",  # Yellow
            "violation": "#ef4444",    # Red
            "absent": "#9ca3af",       # Gray
            "non_working": "#3b82f6",  # Blue
            "partial": "#f97316"       # Orange
        },
        "status_symbols": {
            "perfect": "✓",
            "minor_issue": "⚠",
            "violation": "✗",
            "absent": "○",
            "non_working": "□",
            "partial": "◐"
        },
        "roles": ["maid", "office", "maintenance", "management", "reception"],
        "months": [
            {"year": 2025, "month": 7, "name": "July 2025", "has_data": True},
            {"year": 2025, "month": 6, "name": "June 2025", "has_data": True},
        ]
    }


@router.get("/{year}/{month}")
async def get_monthly_calendar(
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """Get monthly calendar data"""
    try:
        # Validate inputs
        if not 1 <= month <= 12:
            raise HTTPException(status_code=400, detail="Month must be between 1 and 12")
        
        if year < 2020 or year > 2030:
            raise HTTPException(status_code=400, detail="Year must be between 2020 and 2030")
        
        # Get month metadata
        month_name = calendar.month_name[month]
        days_in_month = calendar.monthrange(year, month)[1]
        
        # Get holidays for the month
        start_date = date(year, month, 1)
        end_date = date(year, month, days_in_month)
        holidays = db.query(Holiday).filter(
            and_(
                Holiday.date >= start_date,
                Holiday.date <= end_date,
                Holiday.is_active == True
            )
        ).all()
        holiday_days = [h.date.day for h in holidays]
        
        # Calculate weekends
        weekends = []
        for day in range(1, days_in_month + 1):
            day_date = date(year, month, day)
            if day_date.weekday() in [5, 6]:  # Saturday, Sunday
                weekends.append(day)
        
        # Calculate working days
        working_days = [d for d in range(1, days_in_month + 1) 
                       if d not in holiday_days and d not in weekends]
        
        # Get employees with attendance data
        employees = db.query(EmployeeThaiName).filter(
            EmployeeThaiName.is_active == True
        ).limit(20).all()  # Limit for demo
        
        # Build employee calendar data
        employee_calendar_data = []
        for employee in employees:
            # Get attendance records for this employee in this month
            attendance_records = db.query(AttendanceRecord).filter(
                and_(
                    AttendanceRecord.employee_id == employee.badge_number,
                    func.strftime('%Y-%m', AttendanceRecord.timestamp) == f"{year:04d}-{month:02d}"
                )
            ).all()
            
            # Group records by day
            daily_records = {}
            for record in attendance_records:
                day = record.timestamp.day
                if day not in daily_records:
                    daily_records[day] = []
                daily_records[day].append(record)
            
            # Calculate daily attendance status
            daily_attendance = {}
            for day in range(1, days_in_month + 1):
                if day in holiday_days or day in weekends:
                    status = "non_working"
                elif day in daily_records:
                    # Simple logic: if has records, consider present
                    records = daily_records[day]
                    check_ins = [r for r in records if r.punch_type == 0]
                    check_outs = [r for r in records if r.punch_type == 1]
                    
                    if check_ins and check_outs:
                        # Has both check-in and check-out
                        check_in_time = min(check_ins, key=lambda x: x.timestamp).timestamp
                        check_out_time = max(check_outs, key=lambda x: x.timestamp).timestamp
                        
                        # Simple rule: if check-in before 9:30 AM, consider on time
                        if check_in_time.hour < 9 or (check_in_time.hour == 9 and check_in_time.minute <= 30):
                            status = "perfect"
                        elif check_in_time.hour < 10:
                            status = "minor_issue"
                        else:
                            status = "violation"
                    elif check_ins or check_outs:
                        status = "partial"
                    else:
                        status = "absent"
                else:
                    status = "absent"
                
                daily_attendance[str(day)] = {
                    "date": f"{year:04d}-{month:02d}-{day:02d}",
                    "status": status,
                    "check_in": None,
                    "check_out": None,
                    "late_minutes": 0,
                    "early_departure_minutes": 0,
                    "work_hours": None,
                    "is_weekend": day in weekends,
                    "is_holiday": day in holiday_days,
                    "notes": None
                }
            
            employee_data = {
                "id": employee.badge_number,
                "name": employee.thai_name,
                "role": employee.job_role.display_name if employee.job_role else "Unknown",
                "daily_attendance": daily_attendance
            }
            employee_calendar_data.append(employee_data)
        
        # Calculate basic statistics
        total_employees = len(employee_calendar_data)
        total_working_days = len(working_days)
        
        statistics = {
            "total_employees": total_employees,
            "total_working_days": total_working_days,
            "perfect_attendance_rate": 85.0,  # Mock data
            "punctuality_rate": 92.0,         # Mock data
            "average_late_minutes": 12.5,     # Mock data
            "violation_count": 15,            # Mock data
            "absent_count": 8,                # Mock data
            "role_breakdown": [
                {"role_name": "maid", "employee_count": 5, "punctuality_rate": 90.0},
                {"role_name": "office", "employee_count": 3, "punctuality_rate": 95.0},
                {"role_name": "maintenance", "employee_count": 2, "punctuality_rate": 88.0}
            ]
        }
        
        return {
            "year": year,
            "month": month,
            "month_name": month_name,
            "days_in_month": days_in_month,
            "employees": employee_calendar_data,
            "holidays": holiday_days,
            "weekends": weekends,
            "working_days": working_days,
            "statistics": statistics
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load calendar data: {str(e)}")


@router.get("/health")
async def calendar_health_check():
    """Health check for calendar service"""
    return {
        "status": "healthy",
        "service": "calendar_api",
        "timestamp": datetime.now().isoformat(),
        "endpoints": [
            "/config",
            "/{year}/{month}",
            "/health"
        ]
    }


@router.get("/{year}/{month}/{day}/employee/{employee_id}")
async def get_employee_day_detail(
    year: int,
    month: int,
    day: int,
    employee_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed attendance information for specific employee on specific day"""
    try:
        # Validate inputs
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            raise HTTPException(status_code=400, detail="Invalid date")
        
        # Get employee info
        employee = db.query(EmployeeThaiName).filter(
            EmployeeThaiName.badge_number == employee_id
        ).first()
        
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        # Get attendance records for this specific day
        target_date = date(year, month, day)
        attendance_records = db.query(AttendanceRecord).filter(
            and_(
                AttendanceRecord.employee_id == employee_id,
                func.date(AttendanceRecord.timestamp) == target_date
            )
        ).all()
        
        # Process records
        check_ins = [r for r in attendance_records if r.punch_type == 0]
        check_outs = [r for r in attendance_records if r.punch_type == 1]
        
        check_in_time = None
        check_out_time = None
        work_hours = None
        late_minutes = 0
        early_departure_minutes = 0
        
        if check_ins:
            check_in_time = min(check_ins, key=lambda x: x.timestamp).timestamp
        if check_outs:
            check_out_time = max(check_outs, key=lambda x: x.timestamp).timestamp
        
        # Calculate work hours if both check-in and check-out exist
        if check_in_time and check_out_time:
            work_duration = check_out_time - check_in_time
            work_hours = work_duration.total_seconds() / 3600
        
        # Simple status determination
        if not attendance_records:
            status = "absent"
        elif check_ins and check_outs:
            # Has both check-in and check-out
            if check_in_time.hour < 9 or (check_in_time.hour == 9 and check_in_time.minute <= 30):
                status = "perfect"
            elif check_in_time.hour < 10:
                status = "minor_issue"
            else:
                status = "violation"
                late_minutes = max(0, (check_in_time.hour - 9) * 60 + (check_in_time.minute - 30))
        else:
            status = "partial"
        
        # Check if it's weekend or holiday
        is_weekend = target_date.weekday() in [5, 6]
        holiday = db.query(Holiday).filter(
            and_(Holiday.date == target_date, Holiday.is_active == True)
        ).first()
        is_holiday = holiday is not None
        
        if is_weekend or is_holiday:
            status = "non_working"
        
        return {
            "employee_id": employee_id,
            "employee_name": employee.thai_name,
            "date": target_date.isoformat(),
            "status": status,
            "check_in": check_in_time.isoformat() if check_in_time else None,
            "check_out": check_out_time.isoformat() if check_out_time else None,
            "late_minutes": late_minutes,
            "early_departure_minutes": early_departure_minutes,
            "work_hours": round(work_hours, 2) if work_hours else None,
            "is_weekend": is_weekend,
            "is_holiday": is_holiday,
            "holiday_name": holiday.name if holiday else None,
            "notes": None,
            "attendance_records": [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "punch_type": "Check In" if r.punch_type == 0 else "Check Out",
                    "device_id": r.device_id
                }
                for r in attendance_records
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get employee detail: {str(e)}")


@router.get("/{year}/{month}/statistics")
async def get_monthly_statistics(
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """Get monthly statistics"""
    return {
        "year": year,
        "month": month,
        "total_employees": 10,
        "perfect_attendance_rate": 85.0,
        "punctuality_rate": 92.0,
        "average_late_minutes": 12.5,
        "violation_count": 15,
        "absent_count": 8
    }