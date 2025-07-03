"""
Employee Management API - Comprehensive employee operations
Replaces and extends Thai Names functionality with role management
"""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc
from pydantic import BaseModel, Field
from enum import Enum

from app.core.database import get_db
from app.models.models import Employee, JobRole, AttendanceRecord
from app.services.device_service import device_service

router = APIRouter()


# Pydantic Models
class EmployeeRole(str, Enum):
    MAID = "maid"
    OFFICE = "office"
    RECEPTION = "reception"
    MAINTENANCE = "maintenance"
    MANAGEMENT = "management"


class EmployeeManagementResponse(BaseModel):
    id: int
    badge_number: str
    nickname: str  # thai_name or display_name
    english_name: Optional[str] = None
    role: Optional[str] = None  # role_name from JobRole
    role_display_name: Optional[str] = None
    is_active: bool
    is_hidden: bool
    last_attendance: Optional[str] = None  # Latest attendance timestamp
    last_attendance_type: Optional[str] = None  # "Check-in" or "Check-out"
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


class EmployeeManagementUpdate(BaseModel):
    nickname: Optional[str] = Field(None, min_length=1, max_length=100)
    role: Optional[EmployeeRole] = None
    is_active: Optional[bool] = None
    is_hidden: Optional[bool] = None


class BulkUpdateRequest(BaseModel):
    badge_numbers: List[str] = Field(..., description="List of badge numbers to update")
    updates: EmployeeManagementUpdate = Field(..., description="Updates to apply to all selected employees")


class RoleResponse(BaseModel):
    role_name: str
    display_name: str
    description: str
    has_shifts: bool
    icon: str


class DeviceSyncResponse(BaseModel):
    success: bool
    new_employees: int
    updated_employees: int
    total_employees: int
    message: str


# API Endpoints

@router.get("/", response_model=List[EmployeeManagementResponse])
async def get_all_employees(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: Optional[str] = Query(None, description="Search badge number, nickname, or role"),
    role_filter: Optional[EmployeeRole] = Query(None, description="Filter by specific role"),
    status_filter: Optional[str] = Query(None, description="Filter by active status: 'active', 'inactive'"),
    show_hidden: bool = Query(False, description="Include hidden employees"),
    db: Session = Depends(get_db)
):
    """
    Get all employees with comprehensive management information including roles and last attendance
    """
    # Build query with joins
    query = db.query(Employee).options(
        joinedload(Employee.job_role),
        joinedload(Employee.attendance_records)
    )
    
    # Apply filters
    if not show_hidden:
        query = query.filter(Employee.is_hidden == False)
    
    if role_filter:
        query = query.join(JobRole).filter(JobRole.role_name == role_filter.value)
    
    if status_filter == "active":
        query = query.filter(Employee.is_active == True)
    elif status_filter == "inactive":
        query = query.filter(Employee.is_active == False)
    
    if search:
        search_term = f"%{search}%"
        query = query.outerjoin(JobRole).filter(
            (Employee.badge_number.ilike(search_term)) |
            (Employee.thai_name.ilike(search_term)) |
            (Employee.display_name.ilike(search_term)) |
            (JobRole.display_name.ilike(search_term))
        )
    
    # Order by badge number
    try:
        query = query.order_by(func.cast(Employee.badge_number, 'INTEGER').asc())
    except:
        query = query.order_by(Employee.badge_number.asc())
    
    employees = query.offset(skip).limit(limit).all()
    
    # Build response with last attendance info
    result = []
    for employee in employees:
        # Get latest attendance record
        # Get latest attendance, filtering out future dates
        from datetime import datetime
        current_year = datetime.now().year
        max_year = current_year + 5  # Allow up to 5 years in the future for clock skew
        latest_attendance = db.query(AttendanceRecord)\
            .filter(AttendanceRecord.employee_badge_number == employee.badge_number)\
            .filter(AttendanceRecord.timestamp < datetime(max_year, 1, 1))\
            .order_by(desc(AttendanceRecord.timestamp))\
            .first()
        
        last_attendance = None
        last_attendance_type = None
        if latest_attendance:
            last_attendance = latest_attendance.timestamp.isoformat()
            last_attendance_type = "Check-in" if latest_attendance.punch_type == 0 else "Check-out"
        
        employee_data = EmployeeManagementResponse(
            id=employee.id,
            badge_number=employee.badge_number,
            nickname=employee.thai_name or employee.display_name,
            english_name=employee.english_name,
            role=employee.job_role.role_name if employee.job_role else None,
            role_display_name=employee.job_role.display_name if employee.job_role else None,
            is_active=employee.is_active,
            is_hidden=employee.is_hidden,
            last_attendance=last_attendance,
            last_attendance_type=last_attendance_type,
            created_at=employee.created_at.isoformat() if employee.created_at else None,
            updated_at=employee.updated_at.isoformat() if employee.updated_at else None
        )
        result.append(employee_data)
    
    return result


@router.get("/roles", response_model=List[RoleResponse])
async def get_available_roles(db: Session = Depends(get_db)):
    """
    Get all available job roles with their icons for UI display
    """
    role_icons = {
        'maid': '🧹',
        'office': '🏢', 
        'reception': '📞',
        'maintenance': '🔧',
        'management': '👔'
    }
    
    roles = db.query(JobRole).filter(JobRole.is_active == True).order_by(JobRole.role_name).all()
    
    return [
        RoleResponse(
            role_name=role.role_name,
            display_name=role.display_name,
            description=role.description,
            has_shifts=role.has_shifts,
            icon=role_icons.get(role.role_name, '👤')
        )
        for role in roles
    ]


@router.get("/{badge_number}", response_model=EmployeeManagementResponse)
async def get_employee_by_badge(badge_number: str, db: Session = Depends(get_db)):
    """
    Get detailed information for a specific employee
    """
    employee = db.query(Employee).options(
        joinedload(Employee.job_role)
    ).filter(
        Employee.badge_number == badge_number
    ).first()
    
    if not employee:
        raise HTTPException(
            status_code=404, 
            detail=f"Employee not found for badge number: {badge_number}. The employee may not exist in the database."
        )
    
    # Get latest attendance
    latest_attendance = db.query(AttendanceRecord)\
        .filter(AttendanceRecord.employee_badge_number == employee.badge_number)\
        .order_by(desc(AttendanceRecord.timestamp))\
        .first()
    
    last_attendance = None
    last_attendance_type = None
    if latest_attendance:
        last_attendance = latest_attendance.timestamp.isoformat()
        last_attendance_type = "Check-in" if latest_attendance.punch_type == 0 else "Check-out"
    
    return EmployeeManagementResponse(
        id=employee.id,
        badge_number=employee.badge_number,
        nickname=employee.thai_name or employee.display_name,
        english_name=employee.english_name,
        role=employee.job_role.role_name if employee.job_role else None,
        role_display_name=employee.job_role.display_name if employee.job_role else None,
        is_active=employee.is_active,
        is_hidden=employee.is_hidden,
        last_attendance=last_attendance,
        last_attendance_type=last_attendance_type,
        created_at=employee.created_at.isoformat() if employee.created_at else None,
        updated_at=employee.updated_at.isoformat() if employee.updated_at else None
    )


@router.put("/{badge_number}", response_model=EmployeeManagementResponse)
async def update_employee(
    badge_number: str,
    updates: EmployeeManagementUpdate,
    db: Session = Depends(get_db)
):
    """
    Update individual employee information
    """
    employee = db.query(Employee).filter(
        Employee.badge_number == badge_number
    ).first()
    
    if not employee:
        raise HTTPException(
            status_code=404,
            detail=f"Employee not found for badge number: {badge_number}. The employee may not exist in the database."
        )
    
    # Update fields if provided
    if updates.nickname is not None:
        employee.thai_name = updates.nickname.strip()
        employee.display_name = updates.nickname.strip()
    
    if updates.role is not None:
        # Get job role ID
        job_role = db.query(JobRole).filter(
            JobRole.role_name == updates.role.value,
            JobRole.is_active == True
        ).first()
        if job_role:
            employee.job_role_id = job_role.id
        else:
            raise HTTPException(status_code=400, detail=f"Invalid role: {updates.role.value}")
    
    if updates.is_active is not None:
        employee.is_active = updates.is_active
    
    if updates.is_hidden is not None:
        employee.is_hidden = updates.is_hidden
    
    employee.updated_at = func.now()
    
    db.commit()
    db.refresh(employee)
    
    # Return updated employee data
    return await get_employee_by_badge(badge_number, db)


@router.post("/bulk-update")
async def bulk_update_employees(
    bulk_request: BulkUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Bulk update multiple employees with the same changes
    """
    if not bulk_request.badge_numbers:
        raise HTTPException(status_code=400, detail="No badge numbers provided")
    
    # Verify all employees exist
    employees = db.query(Employee).filter(
        Employee.badge_number.in_(bulk_request.badge_numbers)
    ).all()
    
    found_badges = [emp.badge_number for emp in employees]
    missing_badges = set(bulk_request.badge_numbers) - set(found_badges)
    if missing_badges:
        raise HTTPException(
            status_code=404,
            detail=f"Employees not found for badge numbers: {list(missing_badges)}"
        )
    
    updated_count = 0
    updates = bulk_request.updates
    
    try:
        # Get job role if role update is requested
        job_role_id = None
        if updates.role is not None:
            job_role = db.query(JobRole).filter(
                JobRole.role_name == updates.role.value,
                JobRole.is_active == True
            ).first()
            if job_role:
                job_role_id = job_role.id
            else:
                raise HTTPException(status_code=400, detail=f"Invalid role: {updates.role.value}")
        
        # Apply updates to all employees
        for employee in employees:
            if updates.nickname is not None:
                employee.thai_name = updates.nickname.strip()
                employee.display_name = updates.nickname.strip()
            
            if job_role_id is not None:
                employee.job_role_id = job_role_id
            
            if updates.is_active is not None:
                employee.is_active = updates.is_active
            
            if updates.is_hidden is not None:
                employee.is_hidden = updates.is_hidden
            
            employee.updated_at = func.now()
            updated_count += 1
        
        db.commit()
        
        return {
            "success": True,
            "updated_count": updated_count,
            "message": f"Successfully updated {updated_count} employees",
            "updated_badge_numbers": bulk_request.badge_numbers
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Bulk update failed: {str(e)}"
        )


@router.post("/sync-from-device", response_model=DeviceSyncResponse)
async def sync_employees_from_device(db: Session = Depends(get_db)):
    """
    Sync employees from ZK device and auto-discover new badge numbers
    """
    try:
        # Get device and users
        device = device_service.get_default_device()
        if not device:
            raise HTTPException(status_code=500, detail="No device configured")
        
        device_users = device_service.get_users(device)
        if not device_users:
            return DeviceSyncResponse(
                success=True,
                new_employees=0,
                updated_employees=0,
                total_employees=0,
                message="No users found on device"
            )
        
        # Get existing employees
        existing_employees = db.query(Employee).all()
        existing_badges = {emp.badge_number for emp in existing_employees}
        
        new_count = 0
        updated_count = 0
        
        # Process device users
        for user in device_users:
            badge_number = str(user['user_id'])
            user_name = user.get('name', '')
            
            if badge_number in existing_badges:
                # Update existing employee if name is better
                employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
                if user_name and user_name != f"User {badge_number}" and not employee.english_name:
                    employee.english_name = user_name
                    employee.updated_at = func.now()
                    updated_count += 1
            else:
                # Create new employee
                display_name = user_name if user_name and user_name != f"User {badge_number}" else f"พนักงาน {badge_number}"
                
                new_employee = Employee(
                    badge_number=badge_number,
                    english_name=user_name if user_name and user_name != f"User {badge_number}" else None,
                    thai_name=display_name if display_name.startswith('พนักงาน') else None,
                    display_name=display_name,
                    is_active=True,
                    is_hidden=False
                )
                db.add(new_employee)
                new_count += 1
        
        db.commit()
        
        total_employees = len(existing_employees) + new_count
        
        return DeviceSyncResponse(
            success=True,
            new_employees=new_count,
            updated_employees=updated_count,
            total_employees=total_employees,
            message=f"Synced {new_count} new employees and updated {updated_count} existing employees from device"
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Device sync failed: {str(e)}"
        )


@router.get("/stats/summary")
async def get_employee_stats(db: Session = Depends(get_db)):
    """
    Get employee statistics for dashboard
    """
    total_employees = db.query(Employee).filter(Employee.is_active == True).count()
    active_employees = db.query(Employee).filter(
        Employee.is_active == True,
        Employee.is_hidden == False
    ).count()
    hidden_employees = db.query(Employee).filter(
        Employee.is_active == True,
        Employee.is_hidden == True
    ).count()
    
    # Role distribution
    role_stats = db.query(JobRole.display_name, func.count(Employee.id))\
        .join(Employee, Employee.job_role_id == JobRole.id, isouter=True)\
        .filter(Employee.is_active == True)\
        .group_by(JobRole.id, JobRole.display_name)\
        .all()
    
    role_distribution = {role: count for role, count in role_stats if role}
    unassigned_roles = total_employees - sum(role_distribution.values())
    if unassigned_roles > 0:
        role_distribution['Unassigned'] = unassigned_roles
    
    return {
        "total_employees": total_employees,
        "active_employees": active_employees,
        "hidden_employees": hidden_employees,
        "role_distribution": role_distribution,
        "last_updated": datetime.now().isoformat()
    }