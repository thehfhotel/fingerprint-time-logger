"""
Time Check API

API endpoints for time validation, punctuality checking, and attendance reporting.
Integrates with the time validation service and role-based schedules.
"""

from datetime import date, datetime, time
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import AttendanceRecord, TimeCheckConfig, DailyAttendanceSummary
from app.services.time_validation_service import TimeValidationService
from app.schemas.schemas import (
    TimeCheckConfigResponse, TimeCheckConfigUpdate,
    AttendanceValidationResponse, BulkValidationRequest, BulkValidationResponse,
    LateEmployeeReportResponse, PunctualityReportResponse
)

router = APIRouter(prefix="/api/time-check", tags=["time-check"])


@router.get("/config", response_model=TimeCheckConfigResponse)
async def get_time_check_config(db: Session = Depends(get_db)):
    """Get time checking configuration"""
    config = db.query(TimeCheckConfig).first()
    
    if not config:
        # Create default config if none exists
        config = TimeCheckConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    
    return config


@router.put("/config", response_model=TimeCheckConfigResponse)
async def update_time_check_config(
    config_data: TimeCheckConfigUpdate,
    db: Session = Depends(get_db)
):
    """Update time checking configuration"""
    config = db.query(TimeCheckConfig).first()
    
    if not config:
        config = TimeCheckConfig()
        db.add(config)
    
    # Update fields if provided
    update_data = config_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)
    
    db.commit()
    db.refresh(config)
    
    return config


@router.post("/validate-attendance/{record_id}", response_model=AttendanceValidationResponse)
async def validate_attendance_record(record_id: int, db: Session = Depends(get_db)):
    """Validate a specific attendance record"""
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    validation_service = TimeValidationService(db)
    result = validation_service.validate_and_update_attendance_record(record)
    
    db.commit()
    
    return {
        "record_id": record.id,
        "employee_id": record.employee_id,
        "timestamp": record.timestamp,
        "punch_type": record.punch_type,
        "validation_status": result.status,
        "lateness_minutes": result.lateness_minutes,
        "early_minutes": result.early_minutes,
        "expected_time": result.expected_time,
        "message": result.message,
        "validated_at": record.validated_at
    }


@router.post("/bulk-validate", response_model=BulkValidationResponse)
async def bulk_validate_attendance(
    validation_request: BulkValidationRequest,
    db: Session = Depends(get_db)
):
    """Bulk validate attendance records for a date range"""
    validation_service = TimeValidationService(db)
    
    results = validation_service.bulk_validate_attendance_records(
        start_date=validation_request.start_date,
        end_date=validation_request.end_date,
        badge_numbers=validation_request.badge_numbers
    )
    
    return results


@router.get("/validate-employee/{badge_number}")
async def validate_employee_attendance(
    badge_number: str,
    start_date: date = Query(..., description="Start date for validation"),
    end_date: date = Query(..., description="End date for validation"),
    db: Session = Depends(get_db)
):
    """Validate attendance records for a specific employee"""
    validation_service = TimeValidationService(db)
    
    results = validation_service.bulk_validate_attendance_records(
        start_date=start_date,
        end_date=end_date,
        badge_numbers=[badge_number]
    )
    
    # Get detailed records for this employee
    records = db.query(AttendanceRecord).filter(
        AttendanceRecord.employee_id == badge_number,
        AttendanceRecord.timestamp >= datetime.combine(start_date, time.min),
        AttendanceRecord.timestamp <= datetime.combine(end_date, time.max)
    ).order_by(AttendanceRecord.timestamp.desc()).all()
    
    detailed_records = []
    for record in records:
        detailed_records.append({
            "id": record.id,
            "timestamp": record.timestamp,
            "punch_type": record.punch_type,
            "validation_status": record.validation_status,
            "lateness_minutes": record.lateness_minutes,
            "early_minutes": record.early_minutes,
            "expected_time": record.expected_time,
            "schedule_type": record.schedule_type,
            "validation_message": record.validation_message,
            "validated_at": record.validated_at
        })
    
    return {
        "badge_number": badge_number,
        "validation_summary": results,
        "detailed_records": detailed_records
    }


@router.get("/late-report", response_model=LateEmployeeReportResponse)
async def get_late_employees_report(
    report_date: date = Query(..., description="Date for the late report"),
    min_lateness: int = Query(0, description="Minimum lateness in minutes to include"),
    include_warnings: bool = Query(True, description="Include warning status (<=15 min late)"),
    db: Session = Depends(get_db)
):
    """Get late employees report for a specific date"""
    validation_service = TimeValidationService(db)
    
    late_employees = validation_service.get_late_employees_report(report_date)
    
    # Filter based on criteria
    if not include_warnings:
        late_employees = [emp for emp in late_employees if emp['status'] == 'late']
    
    if min_lateness > 0:
        late_employees = [emp for emp in late_employees if emp['lateness_minutes'] >= min_lateness]
    
    # Calculate summary statistics
    total_late = len([emp for emp in late_employees if emp['status'] == 'late'])
    total_warnings = len([emp for emp in late_employees if emp['status'] == 'warning'])
    avg_lateness = sum(emp['lateness_minutes'] for emp in late_employees) / len(late_employees) if late_employees else 0
    
    return {
        "report_date": report_date,
        "total_employees": len(late_employees),
        "total_late": total_late,
        "total_warnings": total_warnings,
        "average_lateness_minutes": round(avg_lateness, 1),
        "employees": late_employees
    }


@router.get("/punctuality-report", response_model=PunctualityReportResponse)
async def get_punctuality_report(
    start_date: date = Query(..., description="Start date for the report"),
    end_date: date = Query(..., description="End date for the report"),
    badge_number: Optional[str] = Query(None, description="Specific employee badge number"),
    db: Session = Depends(get_db)
):
    """Get punctuality report for a date range"""
    # Build query for attendance records
    query = db.query(AttendanceRecord).filter(
        AttendanceRecord.timestamp >= datetime.combine(start_date, time.min),
        AttendanceRecord.timestamp <= datetime.combine(end_date, time.max),
        AttendanceRecord.punch_type == 0,  # Check-in only
        AttendanceRecord.validation_status.isnot(None)
    )
    
    if badge_number:
        query = query.filter(AttendanceRecord.employee_id == badge_number)
    
    records = query.all()
    
    # Calculate statistics
    total_check_ins = len(records)
    on_time = len([r for r in records if r.validation_status == 'on_time'])
    warnings = len([r for r in records if r.validation_status == 'warning'])
    late = len([r for r in records if r.validation_status == 'late'])
    
    # Calculate percentages
    on_time_percentage = (on_time / total_check_ins * 100) if total_check_ins > 0 else 0
    warning_percentage = (warnings / total_check_ins * 100) if total_check_ins > 0 else 0
    late_percentage = (late / total_check_ins * 100) if total_check_ins > 0 else 0
    
    # Calculate average lateness
    late_records = [r for r in records if r.lateness_minutes and r.lateness_minutes > 0]
    avg_lateness = sum(r.lateness_minutes for r in late_records) / len(late_records) if late_records else 0
    
    # Daily breakdown
    daily_stats = {}
    for record in records:
        day = record.timestamp.date()
        if day not in daily_stats:
            daily_stats[day] = {'on_time': 0, 'warning': 0, 'late': 0}
        
        daily_stats[day][record.validation_status] += 1
    
    daily_breakdown = [
        {
            "date": day,
            "on_time": stats['on_time'],
            "warning": stats['warning'],
            "late": stats['late'],
            "total": sum(stats.values())
        }
        for day, stats in sorted(daily_stats.items())
    ]
    
    return {
        "start_date": start_date,
        "end_date": end_date,
        "badge_number": badge_number,
        "summary": {
            "total_check_ins": total_check_ins,
            "on_time": on_time,
            "warnings": warnings,
            "late": late,
            "on_time_percentage": round(on_time_percentage, 1),
            "warning_percentage": round(warning_percentage, 1),
            "late_percentage": round(late_percentage, 1),
            "average_lateness_minutes": round(avg_lateness, 1)
        },
        "daily_breakdown": daily_breakdown
    }


@router.get("/schedule-info/{badge_number}")
async def get_employee_schedule_info(
    badge_number: str,
    target_date: date = Query(..., description="Date to check schedule for"),
    db: Session = Depends(get_db)
):
    """Get schedule information for an employee on a specific date"""
    validation_service = TimeValidationService(db)
    
    schedule = validation_service.resolve_employee_schedule(badge_number, target_date)
    
    if not schedule:
        raise HTTPException(status_code=404, detail="No schedule found for employee on this date")
    
    return {
        "badge_number": badge_number,
        "date": target_date,
        "start_time": schedule.start_time,
        "end_time": schedule.end_time,
        "schedule_type": schedule.schedule_type,
        "role_name": schedule.role_name,
        "is_working_day": schedule.is_working_day
    }


@router.post("/revalidate-date")
async def revalidate_attendance_for_date(
    target_date: date = Query(..., description="Date to revalidate"),
    db: Session = Depends(get_db)
):
    """Revalidate all attendance records for a specific date"""
    validation_service = TimeValidationService(db)
    
    results = validation_service.bulk_validate_attendance_records(
        start_date=target_date,
        end_date=target_date
    )
    
    return {
        "target_date": target_date,
        "validation_results": results,
        "message": f"Revalidated attendance records for {target_date}"
    }


@router.get("/validation-stats")
async def get_validation_statistics(
    days_back: int = Query(30, description="Number of days back to analyze"),
    db: Session = Depends(get_db)
):
    """Get validation statistics for recent attendance"""
    end_date = date.today()
    start_date = end_date - datetime.timedelta(days=days_back)
    
    # Get all validated records in the period
    records = db.query(AttendanceRecord).filter(
        AttendanceRecord.timestamp >= datetime.combine(start_date, time.min),
        AttendanceRecord.timestamp <= datetime.combine(end_date, time.max),
        AttendanceRecord.validation_status.isnot(None)
    ).all()
    
    # Calculate various statistics
    total_records = len(records)
    check_ins = [r for r in records if r.punch_type == 0]
    check_outs = [r for r in records if r.punch_type == 1]
    
    # Status distribution for check-ins
    check_in_stats = {
        'on_time': len([r for r in check_ins if r.validation_status == 'on_time']),
        'warning': len([r for r in check_ins if r.validation_status == 'warning']),
        'late': len([r for r in check_ins if r.validation_status == 'late']),
        'no_schedule': len([r for r in check_ins if r.validation_status == 'no_schedule']),
        'not_working_day': len([r for r in check_ins if r.validation_status == 'not_working_day'])
    }
    
    # Average lateness
    late_check_ins = [r for r in check_ins if r.lateness_minutes and r.lateness_minutes > 0]
    avg_lateness = sum(r.lateness_minutes for r in late_check_ins) / len(late_check_ins) if late_check_ins else 0
    
    return {
        "period": {
            "start_date": start_date,
            "end_date": end_date,
            "days_analyzed": days_back
        },
        "totals": {
            "total_records": total_records,
            "check_ins": len(check_ins),
            "check_outs": len(check_outs)
        },
        "check_in_statistics": check_in_stats,
        "punctuality": {
            "punctual_percentage": round((check_in_stats['on_time'] / len(check_ins) * 100) if check_ins else 0, 1),
            "warning_percentage": round((check_in_stats['warning'] / len(check_ins) * 100) if check_ins else 0, 1),
            "late_percentage": round((check_in_stats['late'] / len(check_ins) * 100) if check_ins else 0, 1),
            "average_lateness_minutes": round(avg_lateness, 1)
        }
    }