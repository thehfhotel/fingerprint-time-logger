"""
Consolidated Employees API - All employee management in one place
Replaces: employees_unified.py, employees.py, thai_names.py, roles.py
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, File, UploadFile, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.models import Employee, JobRole
from app.services.attendance_service import attendance_service
from app.services.device_service import device_service

router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class EmployeeCreate(BaseModel):
    badge_number: str
    english_name: Optional[str] = None
    thai_name: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    job_role_id: Optional[int] = None
    is_active: bool = True
    is_hidden: bool = False


class EmployeeUpdate(BaseModel):
    english_name: Optional[str] = None
    thai_name: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    job_role_id: Optional[int] = None
    is_active: Optional[bool] = None
    is_hidden: Optional[bool] = None


class RoleCreate(BaseModel):
    role_name: str
    display_name: str
    description: Optional[str] = None
    has_shifts: bool = False
    is_active: bool = True


# ============================================================================
# EMPLOYEE MANAGEMENT - Basic CRUD
# ============================================================================

@router.put("/{badge_number}/nickname")
async def update_employee_nickname(
    badge_number: str,
    nickname_data: dict,
    db: Session = Depends(get_db)
):
    """Update employee nickname only"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        # Update nickname (use display_name for nickname storage)
        employee.display_name = nickname_data.get("nickname", "")
        db.commit()
        
        return {
            "success": True,
            "message": "Nickname updated successfully",
            "badge_number": badge_number,
            "nickname": employee.display_name
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def get_employees(
    include_hidden: bool = False,
    role_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Get all employees with optional filtering"""
    try:
        query = db.query(Employee)
        
        if not include_hidden:
            query = query.filter(Employee.is_hidden == False)
        
        if role_id:
            query = query.filter(Employee.job_role_id == role_id)
        
        employees = query.filter(Employee.is_active == True).all()
        
        result = []
        for emp in employees:
            result.append({
                "badge_number": emp.badge_number,
                "name": emp.display_name or "",  # Use display_name for nickname
                "english_name": emp.english_name,
                "thai_name": emp.thai_name,
                "display_name": emp.display_name,
                "department": emp.department,
                "position": emp.position,
                "job_role_id": emp.job_role_id,
                "is_active": emp.is_active,
                "is_hidden": emp.is_hidden,
                "created_at": emp.created_at.isoformat() if emp.created_at else None
            })
        
        return {"employees": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{badge_number}")
async def get_employee(badge_number: str, db: Session = Depends(get_db)):
    """Get a specific employee by badge number"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        return {
            "badge_number": employee.badge_number,
            "english_name": employee.english_name,
            "thai_name": employee.thai_name,
            "display_name": employee.display_name,
            "department": employee.department,
            "position": employee.position,
            "job_role_id": employee.job_role_id,
            "is_active": employee.is_active,
            "is_hidden": employee.is_hidden,
            "created_at": employee.created_at.isoformat() if employee.created_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/")
async def create_employee(employee_data: EmployeeCreate, db: Session = Depends(get_db)):
    """Create a new employee"""
    try:
        # Check if employee already exists
        existing = db.query(Employee).filter(Employee.badge_number == employee_data.badge_number).first()
        if existing:
            raise HTTPException(status_code=400, detail="Employee with this badge number already exists")
        
        # Generate display name
        display_name = employee_data.thai_name or employee_data.english_name or f"พนักงาน {employee_data.badge_number}"
        
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
        
        return {
            "success": True,
            "message": "Employee created successfully",
            "badge_number": employee.badge_number
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{badge_number}")
async def update_employee(badge_number: str, employee_data: EmployeeUpdate, db: Session = Depends(get_db)):
    """Update an existing employee"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        # Update fields
        if employee_data.english_name is not None:
            employee.english_name = employee_data.english_name
        if employee_data.thai_name is not None:
            employee.thai_name = employee_data.thai_name
        if employee_data.department is not None:
            employee.department = employee_data.department
        if employee_data.position is not None:
            employee.position = employee_data.position
        if employee_data.job_role_id is not None:
            employee.job_role_id = employee_data.job_role_id
        if employee_data.is_active is not None:
            employee.is_active = employee_data.is_active
        if employee_data.is_hidden is not None:
            employee.is_hidden = employee_data.is_hidden
        
        # Update display name
        employee.display_name = employee.thai_name or employee.english_name or f"พนักงาน {badge_number}"
        
        db.commit()
        
        return {
            "success": True,
            "message": "Employee updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{badge_number}")
async def delete_employee(badge_number: str, db: Session = Depends(get_db)):
    """Soft delete an employee (mark as inactive)"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        employee.is_active = False
        db.commit()
        
        return {
            "success": True,
            "message": "Employee deactivated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# THAI NAMES MANAGEMENT
# ============================================================================

@router.get("/thai-names/")
async def get_thai_names(db: Session = Depends(get_db)):
    """Get all employees with Thai names"""
    try:
        employees = db.query(Employee).filter(
            Employee.thai_name.isnot(None),
            Employee.is_active == True
        ).all()
        
        return [
            {
                "badge_number": emp.badge_number,
                "thai_name": emp.thai_name,
                "display_name": emp.display_name,
                "job_role_id": emp.job_role_id
            }
            for emp in employees
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/thai-names/{badge_number}")
async def update_thai_name(badge_number: str, thai_name: str, db: Session = Depends(get_db)):
    """Update Thai name for an employee"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")
        
        employee.thai_name = thai_name
        employee.display_name = thai_name
        db.commit()
        
        return {
            "success": True,
            "message": "Thai name updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CSV IMPORT/EXPORT
# ============================================================================

@router.post("/import-csv")
async def import_employees_from_csv():
    """Import employees from userid.csv file"""
    try:
        result = attendance_service.import_from_csv("userid.csv")
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-from-device")
async def sync_employees_from_device():
    """Sync employees discovered from ZKTeco device"""
    try:
        device = device_service.get_default_device()
        if not device:
            raise HTTPException(status_code=400, detail="No device configured")
        
        users = device_service.get_users(device)
        result = attendance_service.sync_employees_from_device(users)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ROLE MANAGEMENT - Simplified
# ============================================================================

@router.get("/roles/")
async def get_roles(db: Session = Depends(get_db)):
    """Get all job roles"""
    try:
        roles = db.query(JobRole).filter(JobRole.is_active == True).all()
        return [
            {
                "id": role.id,
                "role_name": role.role_name,
                "display_name": role.display_name,
                "description": role.description,
                "has_shifts": role.has_shifts,
                "is_active": role.is_active
            }
            for role in roles
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/roles/")
async def create_role(role_data: RoleCreate, db: Session = Depends(get_db)):
    """Create a new job role"""
    try:
        # Check if role already exists
        existing = db.query(JobRole).filter(JobRole.role_name == role_data.role_name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Role with this name already exists")
        
        role = JobRole(
            role_name=role_data.role_name,
            display_name=role_data.display_name,
            description=role_data.description,
            has_shifts=role_data.has_shifts,
            is_active=role_data.is_active
        )
        
        db.add(role)
        db.commit()
        db.refresh(role)
        
        return {
            "success": True,
            "message": "Role created successfully",
            "role_id": role.id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-role/{role_id}")
async def get_employees_by_role(role_id: int, db: Session = Depends(get_db)):
    """Get all employees with a specific role"""
    try:
        employees = db.query(Employee).filter(
            Employee.job_role_id == role_id,
            Employee.is_active == True
        ).all()
        
        return [
            {
                "badge_number": emp.badge_number,
                "display_name": emp.display_name,
                "thai_name": emp.thai_name,
                "english_name": emp.english_name,
                "department": emp.department,
                "position": emp.position
            }
            for emp in employees
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# STATISTICS & REPORTING
# ============================================================================

@router.get("/stats/summary")
async def get_employee_summary(db: Session = Depends(get_db)):
    """Get employee statistics summary"""
    try:
        total_employees = db.query(Employee).filter(Employee.is_active == True).count()
        with_thai_names = db.query(Employee).filter(
            Employee.is_active == True,
            Employee.thai_name.isnot(None)
        ).count()
        
        # Group by department
        departments = db.query(Employee.department).filter(
            Employee.is_active == True,
            Employee.department.isnot(None)
        ).distinct().all()
        
        dept_counts = {}
        for dept in departments:
            count = db.query(Employee).filter(
                Employee.is_active == True,
                Employee.department == dept[0]
            ).count()
            dept_counts[dept[0]] = count
        
        return {
            "total_employees": total_employees,
            "with_thai_names": with_thai_names,
            "departments": dept_counts,
            "completion_rate": round((with_thai_names / total_employees * 100) if total_employees > 0 else 0, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# HEALTH & STATUS
# ============================================================================

@router.get("/health")
async def employees_health_check(db: Session = Depends(get_db)):
    """Health check for employee system"""
    try:
        total_employees = db.query(Employee).filter(Employee.is_active == True).count()
        
        return {
            "status": "healthy",
            "total_employees": total_employees,
            "has_employees": total_employees > 0
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }