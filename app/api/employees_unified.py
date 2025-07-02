"""
Unified Employee API - Consolidates Employee and Thai Names functionality

This API replaces both the original employees.py and thai_names.py APIs
with a single unified interface for the consolidated Employee model.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.core.database import get_db
from app.models.models import Employee, JobRole
from app.schemas.schemas import Employee as EmployeeSchema, EmployeeCreate, EmployeeUpdate
from app.services.employee_csv_service import get_employee_csv_service

router = APIRouter()


@router.get("/", response_model=List[EmployeeSchema])
async def get_employees(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    department: Optional[str] = None,
    job_role_id: Optional[int] = None,
    include_hidden: bool = False,
    include_inactive: bool = False,
    db: Session = Depends(get_db)
):
    """
    Get employees with unified search across Thai and English names
    
    - **search**: Search in badge_number, thai_name, english_name, or display_name
    - **department**: Filter by department
    - **job_role_id**: Filter by job role
    - **include_hidden**: Include employees marked as hidden
    - **include_inactive**: Include inactive employees
    """
    query = db.query(Employee)
    
    # Apply filters
    if not include_inactive:
        query = query.filter(Employee.is_active == True)
    
    if not include_hidden:
        query = query.filter(Employee.is_hidden == False)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Employee.badge_number.ilike(search_term),
                Employee.thai_name.ilike(search_term),
                Employee.english_name.ilike(search_term),
                Employee.display_name.ilike(search_term)
            )
        )
    
    if department:
        query = query.filter(Employee.department.ilike(f"%{department}%"))
    
    if job_role_id:
        query = query.filter(Employee.job_role_id == job_role_id)
    
    employees = query.offset(skip).limit(limit).all()
    return employees


@router.get("/{badge_number}", response_model=EmployeeSchema)
async def get_employee(badge_number: str, db: Session = Depends(get_db)):
    """Get employee by badge number"""
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"Employee with badge number {badge_number} not found")
    return employee


@router.post("/", response_model=EmployeeSchema)
async def create_employee(employee_data: EmployeeCreate, db: Session = Depends(get_db)):
    """
    Create new employee
    
    Automatically generates display_name based on thai_name preference
    """
    # Check if badge number already exists
    existing = db.query(Employee).filter(Employee.badge_number == employee_data.badge_number).first()
    if existing:
        raise HTTPException(
            status_code=400, 
            detail=f"Employee with badge number {employee_data.badge_number} already exists"
        )
    
    # Generate display name
    display_name = (
        employee_data.thai_name if employee_data.thai_name 
        else f"พนักงาน {employee_data.badge_number}"
    )
    
    # Create employee
    employee = Employee(
        badge_number=employee_data.badge_number,
        english_name=employee_data.english_name,
        thai_name=employee_data.thai_name,
        display_name=display_name,
        department=employee_data.department,
        position=employee_data.position,
        job_role_id=employee_data.job_role_id,
        is_active=employee_data.is_active,
        is_hidden=employee_data.is_hidden
    )
    
    db.add(employee)
    db.commit()
    db.refresh(employee)
    
    return employee


@router.put("/{badge_number}", response_model=EmployeeSchema)
async def update_employee(
    badge_number: str, 
    employee_update: EmployeeUpdate, 
    db: Session = Depends(get_db)
):
    """
    Update employee information
    
    Automatically updates display_name if thai_name is changed
    """
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"Employee with badge number {badge_number} not found")
    
    # Update fields that are provided
    update_data = employee_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(employee, field, value)
    
    # Auto-update display name if thai_name was changed
    if 'thai_name' in update_data:
        employee.display_name = (
            employee.thai_name if employee.thai_name 
            else f"พนักงาน {employee.badge_number}"
        )
    
    db.commit()
    db.refresh(employee)
    
    return employee


@router.delete("/{badge_number}")
async def delete_employee(badge_number: str, db: Session = Depends(get_db)):
    """
    Delete employee (soft delete - mark as inactive)
    
    Checks for existing attendance records before allowing deletion
    """
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"Employee with badge number {badge_number} not found")
    
    # Check if employee has attendance records
    from app.models.models import AttendanceRecord
    attendance_count = db.query(AttendanceRecord).filter(
        AttendanceRecord.employee_badge_number == badge_number
    ).count()
    
    if attendance_count > 0:
        # Soft delete - mark as inactive instead of hard delete
        employee.is_active = False
        db.commit()
        return {
            "message": f"Employee {badge_number} marked as inactive (has {attendance_count} attendance records)"
        }
    else:
        # Hard delete if no attendance records
        db.delete(employee)
        db.commit()
        return {"message": f"Employee {badge_number} deleted successfully"}


@router.post("/sync-from-csv")
async def sync_employees_from_csv(
    csv_file_path: str = Query("userid.csv", description="Path to CSV file"),
    db: Session = Depends(get_db)
):
    """
    Sync employees from CSV file (userid.csv format)
    
    Expected CSV format: USERID,Badgenumber,Name,ชื่อไทย
    """
    csv_service = get_employee_csv_service(db)
    
    try:
        results = csv_service.import_from_userid_csv(csv_file_path)
        return {
            "message": "CSV sync completed",
            "results": results
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"CSV file not found: {csv_file_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error syncing CSV: {str(e)}")


@router.post("/sync-display-names")
async def sync_display_names(db: Session = Depends(get_db)):
    """
    Sync display names for all employees based on Thai name preference
    """
    csv_service = get_employee_csv_service(db)
    updated_count = csv_service.sync_display_names()
    
    return {
        "message": f"Updated display names for {updated_count} employees",
        "updated_count": updated_count
    }


@router.get("/stats/summary")
async def get_employee_summary(db: Session = Depends(get_db)):
    """Get summary statistics of employee data"""
    csv_service = get_employee_csv_service(db)
    summary = csv_service.get_employees_summary()
    
    return {
        "message": "Employee statistics",
        "statistics": summary
    }


@router.get("/by-role/{role_id}", response_model=List[EmployeeSchema])
async def get_employees_by_role(
    role_id: int, 
    include_hidden: bool = False,
    db: Session = Depends(get_db)
):
    """Get all employees assigned to a specific job role"""
    query = db.query(Employee).filter(
        and_(
            Employee.job_role_id == role_id,
            Employee.is_active == True
        )
    )
    
    if not include_hidden:
        query = query.filter(Employee.is_hidden == False)
    
    employees = query.all()
    return employees


@router.put("/{badge_number}/role")
async def assign_employee_role(
    badge_number: str,
    role_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Assign or remove job role for employee"""
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"Employee with badge number {badge_number} not found")
    
    if role_id is not None:
        # Validate role exists
        role = db.query(JobRole).filter(JobRole.id == role_id).first()
        if not role:
            raise HTTPException(status_code=404, detail=f"Job role with ID {role_id} not found")
    
    employee.job_role_id = role_id
    db.commit()
    db.refresh(employee)
    
    return {
        "message": f"Employee {badge_number} role updated",
        "employee": employee
    }


@router.put("/{badge_number}/visibility")
async def toggle_employee_visibility(
    badge_number: str,
    is_hidden: bool,
    db: Session = Depends(get_db)
):
    """Show or hide employee from normal views"""
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"Employee with badge number {badge_number} not found")
    
    employee.is_hidden = is_hidden
    db.commit()
    
    return {
        "message": f"Employee {badge_number} {'hidden' if is_hidden else 'visible'}",
        "is_hidden": is_hidden
    }