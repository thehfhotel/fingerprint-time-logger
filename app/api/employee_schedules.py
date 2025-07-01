"""
Employee Schedule Management API - Monthly calendars and time configurations
"""

from typing import List, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel, Field
from datetime import datetime, date
import calendar

from app.core.database import get_db
from app.models.models import (
    JobRole, EmployeeThaiName, EmployeeMonthlySchedule, 
    ReceptionShiftAssignment, WorkShift
)

router = APIRouter()

# Pydantic Models
class TimeSettings(BaseModel):
    start_time: str = Field(..., description="Start time in HH:MM format")
    end_time: str = Field(..., description="End time in HH:MM format")

class EmployeeBasic(BaseModel):
    badge_number: str
    thai_name: str

class EmployeeWithStatus(EmployeeBasic):
    is_assigned: bool = False

class EmployeeSchedule(EmployeeBasic):
    work_days: List[int] = Field(default=[], description="Array of day numbers")

class MonthlyScheduleResponse(BaseModel):
    role: str
    year: int
    month: int
    days_in_month: int
    schedules: List[EmployeeSchedule]

class MonthlyScheduleUpdate(BaseModel):
    role_name: str
    schedules: List[EmployeeSchedule]

class ReceptionShift(BaseModel):
    id: int
    shift_name: str
    start_time: str
    end_time: str
    color: str
    is_overnight: bool

class ReceptionEmployeeSchedule(EmployeeBasic):
    shift_assignments: Dict[str, int] = Field(default={}, description="day -> shift_id mapping")

class ReceptionMonthlyResponse(BaseModel):
    year: int
    month: int
    days_in_month: int
    shifts: List[ReceptionShift]
    assignments: List[ReceptionEmployeeSchedule]

class ReceptionMonthlyUpdate(BaseModel):
    assignments: List[ReceptionEmployeeSchedule]


# Role Time Configuration Endpoints
@router.get("/roles/{role_name}/time-settings", response_model=TimeSettings)
async def get_role_time_settings(role_name: str, db: Session = Depends(get_db)):
    """Get simplified time settings for a role"""
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    if role.has_shifts:
        # For reception, return first shift as default
        shift = db.query(WorkShift).filter(
            WorkShift.job_role_id == role.id,
            WorkShift.is_active == True
        ).first()
        
        if shift:
            return TimeSettings(
                start_time=shift.start_time.strftime("%H:%M"),
                end_time=shift.end_time.strftime("%H:%M")
            )
    else:
        # For standard roles, get from work schedule
        from app.models.models import WorkSchedule
        schedule = db.query(WorkSchedule).filter(
            WorkSchedule.job_role_id == role.id,
            WorkSchedule.is_active == True
        ).first()
        
        if schedule:
            return TimeSettings(
                start_time=schedule.start_time.strftime("%H:%M"),
                end_time=schedule.end_time.strftime("%H:%M")
            )
    
    # Default times
    return TimeSettings(start_time="08:00", end_time="17:00")


@router.put("/roles/{role_name}/time-settings", response_model=TimeSettings)
async def update_role_time_settings(
    role_name: str, 
    time_settings: TimeSettings, 
    db: Session = Depends(get_db)
):
    """Update simplified time settings for a role"""
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Convert time strings to time objects
    from datetime import time
    start_time = time.fromisoformat(f"{time_settings.start_time}:00")
    end_time = time.fromisoformat(f"{time_settings.end_time}:00")
    
    if not role.has_shifts:
        # Update work schedule for standard roles
        from app.models.models import WorkSchedule
        schedule = db.query(WorkSchedule).filter(
            WorkSchedule.job_role_id == role.id,
            WorkSchedule.is_active == True
        ).first()
        
        if schedule:
            schedule.start_time = start_time
            schedule.end_time = end_time
        else:
            # Create new schedule
            schedule = WorkSchedule(
                job_role_id=role.id,
                start_time=start_time,
                end_time=end_time,
                working_days=["monday", "tuesday", "wednesday", "thursday", "friday"]
            )
            db.add(schedule)
    
    db.commit()
    return time_settings


# Employee Assignment Endpoints
@router.get("/roles/{role_name}/assigned-employees", response_model=List[EmployeeBasic])
async def get_assigned_employees(role_name: str, db: Session = Depends(get_db)):
    """Get employees assigned to a role with Thai names"""
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    # Get employees who have schedules for this role
    assigned_badges = db.query(EmployeeMonthlySchedule.employee_badge_number).filter(
        EmployeeMonthlySchedule.job_role_id == role.id
    ).distinct().all()
    
    # If reception, also check shift assignments
    if role.has_shifts:
        reception_badges = db.query(ReceptionShiftAssignment.employee_badge_number).distinct().all()
        assigned_badges.extend(reception_badges)
    
    badge_numbers = list(set([badge[0] for badge in assigned_badges]))
    
    # Get Thai names
    employees = db.query(EmployeeThaiName).filter(
        EmployeeThaiName.badge_number.in_(badge_numbers),
        EmployeeThaiName.is_active == True,
        EmployeeThaiName.is_hidden == False
    ).all()
    
    return [
        EmployeeBasic(badge_number=emp.badge_number, thai_name=emp.thai_name)
        for emp in employees
    ]


@router.get("/roles/{role_name}/available-employees", response_model=List[EmployeeBasic])
async def get_available_employees(role_name: str, db: Session = Depends(get_db)):
    """Get all employees available for assignment to role"""
    employees = db.query(EmployeeThaiName).filter(
        EmployeeThaiName.is_active == True,
        EmployeeThaiName.is_hidden == False
    ).all()
    
    return [
        EmployeeBasic(badge_number=emp.badge_number, thai_name=emp.thai_name)
        for emp in employees
    ]


# Monthly Schedule Endpoints - Standard Roles
@router.get("/monthly/{year}/{month}", response_model=MonthlyScheduleResponse)
async def get_monthly_schedule(
    year: int, 
    month: int, 
    role: str, 
    db: Session = Depends(get_db)
):
    """Get monthly schedule for standard roles"""
    job_role = db.query(JobRole).filter(
        JobRole.role_name == role,
        JobRole.is_active == True
    ).first()
    
    if not job_role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    if job_role.has_shifts:
        raise HTTPException(status_code=400, detail="Use reception endpoint for shift-based roles")
    
    # Get schedules for this role/month
    schedules = db.query(EmployeeMonthlySchedule).filter(
        EmployeeMonthlySchedule.job_role_id == job_role.id,
        EmployeeMonthlySchedule.year == year,
        EmployeeMonthlySchedule.month == month
    ).all()
    
    # Get Thai names
    employee_schedules = []
    for schedule in schedules:
        thai_name_obj = db.query(EmployeeThaiName).filter(
            EmployeeThaiName.badge_number == schedule.employee_badge_number,
            EmployeeThaiName.is_active == True,
            EmployeeThaiName.is_hidden == False
        ).first()
        
        if thai_name_obj:
            employee_schedules.append(EmployeeSchedule(
                badge_number=schedule.employee_badge_number,
                thai_name=thai_name_obj.thai_name,
                work_days=schedule.work_days or []
            ))
    
    days_in_month = calendar.monthrange(year, month)[1]
    
    return MonthlyScheduleResponse(
        role=role,
        year=year,
        month=month,
        days_in_month=days_in_month,
        schedules=employee_schedules
    )


@router.put("/monthly/{year}/{month}")
async def save_monthly_schedule(
    year: int,
    month: int,
    schedule_data: MonthlyScheduleUpdate,
    db: Session = Depends(get_db)
):
    """Save monthly schedule for standard roles"""
    job_role = db.query(JobRole).filter(
        JobRole.role_name == schedule_data.role_name,
        JobRole.is_active == True
    ).first()
    
    if not job_role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    if job_role.has_shifts:
        raise HTTPException(status_code=400, detail="Use reception endpoint for shift-based roles")
    
    # Get all existing schedules for this role/month
    existing_schedules = db.query(EmployeeMonthlySchedule).filter(
        EmployeeMonthlySchedule.job_role_id == job_role.id,
        EmployeeMonthlySchedule.year == year,
        EmployeeMonthlySchedule.month == month
    ).all()
    
    # Create a set of badge numbers from the incoming data
    incoming_badges = {emp.badge_number for emp in schedule_data.schedules}
    
    # Delete schedules for employees not in the incoming data
    for existing in existing_schedules:
        if existing.employee_badge_number not in incoming_badges:
            db.delete(existing)
    
    # Update or create schedules
    for emp_schedule in schedule_data.schedules:
        existing = db.query(EmployeeMonthlySchedule).filter(
            EmployeeMonthlySchedule.employee_badge_number == emp_schedule.badge_number,
            EmployeeMonthlySchedule.job_role_id == job_role.id,
            EmployeeMonthlySchedule.year == year,
            EmployeeMonthlySchedule.month == month
        ).first()
        
        if existing:
            existing.work_days = emp_schedule.work_days
        else:
            new_schedule = EmployeeMonthlySchedule(
                employee_badge_number=emp_schedule.badge_number,
                job_role_id=job_role.id,
                year=year,
                month=month,
                work_days=emp_schedule.work_days
            )
            db.add(new_schedule)
    
    db.commit()
    return {"message": "Schedule saved successfully"}


# Reception Shift Endpoints
@router.get("/reception/shifts", response_model=List[ReceptionShift])
async def get_reception_shifts(db: Session = Depends(get_db)):
    """Get all reception shifts with overnight flag"""
    reception_role = db.query(JobRole).filter(
        JobRole.role_name == "reception",
        JobRole.is_active == True
    ).first()
    
    if not reception_role:
        raise HTTPException(status_code=404, detail="Reception role not found")
    
    shifts = db.query(WorkShift).filter(
        WorkShift.job_role_id == reception_role.id,
        WorkShift.is_active == True
    ).order_by(WorkShift.sort_order).all()
    
    return [
        ReceptionShift(
            id=shift.id,
            shift_name=shift.shift_name,
            start_time=shift.start_time.strftime("%H:%M"),
            end_time=shift.end_time.strftime("%H:%M"),
            color=shift.color,
            is_overnight=shift.is_overnight
        )
        for shift in shifts
    ]


@router.get("/reception/monthly/{year}/{month}", response_model=ReceptionMonthlyResponse)
async def get_reception_monthly_schedule(year: int, month: int, db: Session = Depends(get_db)):
    """Get reception monthly shift assignments"""
    reception_role = db.query(JobRole).filter(
        JobRole.role_name == "reception",
        JobRole.is_active == True
    ).first()
    
    if not reception_role:
        raise HTTPException(status_code=404, detail="Reception role not found")
    
    # Get shifts
    shifts = db.query(WorkShift).filter(
        WorkShift.job_role_id == reception_role.id,
        WorkShift.is_active == True
    ).order_by(WorkShift.sort_order).all()
    
    shift_list = [
        ReceptionShift(
            id=shift.id,
            shift_name=shift.shift_name,
            start_time=shift.start_time.strftime("%H:%M"),
            end_time=shift.end_time.strftime("%H:%M"),
            color=shift.color,
            is_overnight=shift.is_overnight
        )
        for shift in shifts
    ]
    
    # Get assignments for this month
    start_date = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    end_date = date(year, month, days_in_month)
    
    assignments = db.query(ReceptionShiftAssignment).filter(
        ReceptionShiftAssignment.work_date >= start_date,
        ReceptionShiftAssignment.work_date <= end_date
    ).all()
    
    # Group by employee
    employee_assignments = {}
    for assignment in assignments:
        badge = assignment.employee_badge_number
        day = assignment.work_date.day
        
        if badge not in employee_assignments:
            employee_assignments[badge] = {}
        
        employee_assignments[badge][str(day)] = assignment.shift_id
    
    # Get Thai names and build response
    assignment_list = []
    for badge_number, shift_assignments in employee_assignments.items():
        thai_name_obj = db.query(EmployeeThaiName).filter(
            EmployeeThaiName.badge_number == badge_number,
            EmployeeThaiName.is_active == True,
            EmployeeThaiName.is_hidden == False
        ).first()
        
        if thai_name_obj:
            assignment_list.append(ReceptionEmployeeSchedule(
                badge_number=badge_number,
                thai_name=thai_name_obj.thai_name,
                shift_assignments=shift_assignments
            ))
    
    return ReceptionMonthlyResponse(
        year=year,
        month=month,
        days_in_month=days_in_month,
        shifts=shift_list,
        assignments=assignment_list
    )


@router.put("/reception/monthly/{year}/{month}")
async def save_reception_monthly_schedule(
    year: int,
    month: int,
    schedule_data: ReceptionMonthlyUpdate,
    db: Session = Depends(get_db)
):
    """Save reception monthly shift assignments"""
    start_date = date(year, month, 1)
    days_in_month = calendar.monthrange(year, month)[1]
    end_date = date(year, month, days_in_month)
    
    # Get all existing assignments for this month
    existing_assignments = db.query(ReceptionShiftAssignment).filter(
        ReceptionShiftAssignment.work_date >= start_date,
        ReceptionShiftAssignment.work_date <= end_date
    ).all()
    
    # Create a set of badge numbers from the incoming data
    incoming_badges = {emp.badge_number for emp in schedule_data.assignments}
    
    # Delete assignments for employees not in the incoming data
    for existing in existing_assignments:
        if existing.employee_badge_number not in incoming_badges:
            db.delete(existing)
    
    for emp_assignment in schedule_data.assignments:
        # Delete existing assignments for this employee in this month
        db.query(ReceptionShiftAssignment).filter(
            ReceptionShiftAssignment.employee_badge_number == emp_assignment.badge_number,
            ReceptionShiftAssignment.work_date >= start_date,
            ReceptionShiftAssignment.work_date <= end_date
        ).delete()
        
        # Create new assignments
        for day_str, shift_id in emp_assignment.shift_assignments.items():
            work_date = date(year, month, int(day_str))
            
            new_assignment = ReceptionShiftAssignment(
                employee_badge_number=emp_assignment.badge_number,
                work_date=work_date,
                shift_id=shift_id
            )
            db.add(new_assignment)
    
    db.commit()
    return {"message": "Reception schedule saved successfully"}