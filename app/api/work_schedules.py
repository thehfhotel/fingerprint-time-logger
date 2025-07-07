"""
Work Schedule Management API - Job roles, schedules, and shifts
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.models import JobRole, WorkSchedule, WorkShift
from app.schemas.schemas import (
    JobRoleWithSchedule, JobRole as JobRoleSchema,
    WorkSchedule as WorkScheduleSchema, WorkScheduleUpdate,
    WorkShift as WorkShiftSchema, WorkShiftCreate, WorkShiftUpdate
)

router = APIRouter()


@router.get("/job-roles", response_model=List[JobRoleWithSchedule])
async def get_job_roles_with_schedules(db: Session = Depends(get_db)):
    """
    Get all job roles with their work schedules and shifts
    """
    job_roles = db.query(JobRole).filter(JobRole.is_active == True).all()
    
    result = []
    for role in job_roles:
        role_data = {
            "id": role.id,
            "role_name": role.role_name,
            "display_name": role.display_name,
            "description": role.description,
            "has_shifts": role.has_shifts,
            "is_active": role.is_active,
            "created_at": role.created_at,
            "updated_at": role.updated_at,
            "work_schedule": None,
            "work_shifts": []
        }
        
        if role.has_shifts:
            # Get shifts for reception role
            shifts = db.query(WorkShift).filter(
                WorkShift.job_role_id == role.id,
                WorkShift.is_active == True
            ).order_by(WorkShift.sort_order).all()
            role_data["work_shifts"] = shifts
        else:
            # Get schedule for non-shift roles
            schedule = db.query(WorkSchedule).filter(
                WorkSchedule.job_role_id == role.id,
                WorkSchedule.is_active == True
            ).first()
            role_data["work_schedule"] = schedule
        
        result.append(role_data)
    
    return result


@router.get("/job-roles/{role_name}", response_model=JobRoleWithSchedule)
async def get_job_role_by_name(role_name: str, db: Session = Depends(get_db)):
    """
    Get specific job role with its schedule/shifts
    """
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    role_data = {
        "id": role.id,
        "role_name": role.role_name,
        "display_name": role.display_name,
        "description": role.description,
        "has_shifts": role.has_shifts,
        "is_active": role.is_active,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
        "work_schedule": None,
        "work_shifts": []
    }
    
    if role.has_shifts:
        shifts = db.query(WorkShift).filter(
            WorkShift.job_role_id == role.id,
            WorkShift.is_active == True
        ).order_by(WorkShift.sort_order).all()
        role_data["work_shifts"] = shifts
    else:
        schedule = db.query(WorkSchedule).filter(
            WorkSchedule.job_role_id == role.id,
            WorkSchedule.is_active == True
        ).first()
        role_data["work_schedule"] = schedule
    
    return role_data


@router.put("/job-roles/{role_name}/schedule", response_model=WorkScheduleSchema)
async def update_work_schedule(
    role_name: str,
    schedule_update: WorkScheduleUpdate,
    db: Session = Depends(get_db)
):
    """
    Update work schedule for a job role (non-shift roles only)
    """
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    if role.has_shifts:
        raise HTTPException(
            status_code=400, 
            detail="This role uses shifts, not schedules. Use shift endpoints instead."
        )
    
    # Get existing schedule or create new one
    schedule = db.query(WorkSchedule).filter(
        WorkSchedule.job_role_id == role.id,
        WorkSchedule.is_active == True
    ).first()
    
    if not schedule:
        # Create new schedule
        schedule = WorkSchedule(job_role_id=role.id)
        db.add(schedule)
    
    # Update schedule fields
    update_data = schedule_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(schedule, field, value)
    
    db.commit()
    db.refresh(schedule)
    
    return schedule


@router.get("/job-roles/{role_name}/shifts", response_model=List[WorkShiftSchema])
async def get_work_shifts(role_name: str, db: Session = Depends(get_db)):
    """
    Get work shifts for a job role (shift-based roles only)
    """
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    if not role.has_shifts:
        raise HTTPException(
            status_code=400,
            detail="This role uses schedules, not shifts. Use schedule endpoints instead."
        )
    
    shifts = db.query(WorkShift).filter(
        WorkShift.job_role_id == role.id,
        WorkShift.is_active == True
    ).order_by(WorkShift.sort_order).all()
    
    return shifts


@router.put("/job-roles/{role_name}/shifts/{shift_id}", response_model=WorkShiftSchema)
async def update_work_shift(
    role_name: str,
    shift_id: int,
    shift_update: WorkShiftUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a specific work shift
    """
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    if not role.has_shifts:
        raise HTTPException(
            status_code=400,
            detail="This role uses schedules, not shifts."
        )
    
    shift = db.query(WorkShift).filter(
        WorkShift.id == shift_id,
        WorkShift.job_role_id == role.id,
        WorkShift.is_active == True
    ).first()
    
    if not shift:
        raise HTTPException(status_code=404, detail="Work shift not found")
    
    # Update shift fields
    update_data = shift_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(shift, field, value)
    
    db.commit()
    db.refresh(shift)
    
    return shift


@router.put("/job-roles/{role_name}/shifts", response_model=List[WorkShiftSchema])
async def update_all_shifts(
    role_name: str,
    shifts_update: List[WorkShiftUpdate],
    db: Session = Depends(get_db)
):
    """
    Update all shifts for a role at once (for reception role)
    """
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    if not role.has_shifts:
        raise HTTPException(
            status_code=400,
            detail="This role uses schedules, not shifts."
        )
    
    if role_name != "reception":
        raise HTTPException(
            status_code=400,
            detail="Bulk shift update only available for reception role"
        )
    
    # Get existing shifts
    shifts = db.query(WorkShift).filter(
        WorkShift.job_role_id == role.id,
        WorkShift.is_active == True
    ).order_by(WorkShift.sort_order).all()
    
    if len(shifts_update) != len(shifts):
        raise HTTPException(
            status_code=400,
            detail=f"Expected {len(shifts)} shift updates, got {len(shifts_update)}"
        )
    
    # Update each shift
    updated_shifts = []
    for i, shift_update in enumerate(shifts_update):
        shift = shifts[i]
        update_data = shift_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(shift, field, value)
        updated_shifts.append(shift)
    
    db.commit()
    
    # Refresh all shifts
    for shift in updated_shifts:
        db.refresh(shift)
    
    return updated_shifts


@router.post("/job-roles/{role_name}/shifts", response_model=WorkShiftSchema)
async def create_work_shift(
    role_name: str,
    shift_create: WorkShiftCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new work shift for a role
    """
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    if not role.has_shifts:
        raise HTTPException(
            status_code=400,
            detail="This role uses schedules, not shifts."
        )
    
    # Get the next sort order
    max_sort_order = db.query(func.max(WorkShift.sort_order)).filter(
        WorkShift.job_role_id == role.id,
        WorkShift.is_active == True
    ).scalar() or 0
    
    # Create new shift
    new_shift = WorkShift(
        job_role_id=role.id,
        shift_name=shift_create.shift_name,
        start_time=shift_create.start_time,
        end_time=shift_create.end_time,
        break_duration_minutes=shift_create.break_duration_minutes or 0,
        working_days=shift_create.working_days,
        color=shift_create.color,
        sort_order=max_sort_order + 1,
        is_active=True
    )
    
    db.add(new_shift)
    db.commit()
    db.refresh(new_shift)
    
    return new_shift


@router.delete("/job-roles/{role_name}/shifts/{shift_id}")
async def delete_work_shift(
    role_name: str,
    shift_id: int,
    db: Session = Depends(get_db)
):
    """
    Delete a work shift
    """
    role = db.query(JobRole).filter(
        JobRole.role_name == role_name,
        JobRole.is_active == True
    ).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    shift = db.query(WorkShift).filter(
        WorkShift.id == shift_id,
        WorkShift.job_role_id == role.id,
        WorkShift.is_active == True
    ).first()
    
    if not shift:
        raise HTTPException(status_code=404, detail="Work shift not found")
    
    # Soft delete by setting is_active to False
    shift.is_active = False
    db.commit()
    
    return {"detail": "Work shift deleted successfully"}