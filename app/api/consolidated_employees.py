"""
Consolidated Employees API - All employee management in one place
Replaces: employees_unified.py, employees.py, thai_names.py, roles.py
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, File, UploadFile, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.models import Employee
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
    is_active: bool = True
    is_hidden: bool = False


class EmployeeUpdate(BaseModel):
    english_name: Optional[str] = None
    thai_name: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    is_active: Optional[bool] = None
    is_hidden: Optional[bool] = None


# Role schemas removed - simplifying employee management


# ============================================================================
# EMPLOYEE MANAGEMENT - Basic CRUD
# ============================================================================

@router.put("/{badge_number}/nickname")
async def update_employee_nickname(
    badge_number: str,
    nickname_data: dict,
    db: Session = Depends(get_db)
):
    """Update employee nickname only - creates employee if not exists"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        
        if not employee:
            # Create new employee if doesn't exist (from ZK device)
            display_name = nickname_data.get("nickname") or nickname_data.get("display_name") or f"User {badge_number}"
            employee = Employee(
                badge_number=badge_number,
                display_name=display_name,
                is_active=True,
                is_hidden=False
            )
            db.add(employee)
            db.commit()
            db.refresh(employee)
            
            return {
                "success": True,
                "message": "Employee created and nickname set successfully",
                "badge_number": badge_number,
                "nickname": employee.display_name,
                "display_name": employee.display_name,
                "created": True
            }
        else:
            # Update existing employee nickname
            employee.display_name = nickname_data.get("nickname") or nickname_data.get("display_name") or ""
            db.commit()
            
            return {
                "success": True,
                "message": "Nickname updated successfully",
                "badge_number": badge_number,
                "nickname": employee.display_name,
                "display_name": employee.display_name,
                "created": False
            }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{badge_number}/status")
async def update_employee_status(
    badge_number: str,
    status_data: dict,
    db: Session = Depends(get_db)
):
    """Update employee active/inactive status - creates employee if not exists"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        
        if not employee:
            # Create new employee if doesn't exist (from ZK device)
            is_active = status_data.get("is_active", True)
            employee = Employee(
                badge_number=badge_number,
                display_name=f"User {badge_number}",
                is_active=is_active,
                is_hidden=False
            )
            db.add(employee)
            db.commit()
            db.refresh(employee)
        else:
            # Update existing employee status
            employee.is_active = status_data.get("is_active", employee.is_active)
            db.commit()
        
        return {
            "success": True,
            "message": f"Employee status updated to {'active' if employee.is_active else 'inactive'}",
            "badge_number": badge_number,
            "is_active": employee.is_active
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{badge_number}/hidden")
async def update_employee_hidden_status(
    badge_number: str,
    hidden_data: dict,
    db: Session = Depends(get_db)
):
    """Update employee hidden/visible status - creates employee if not exists"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        
        if not employee:
            # Create new employee if doesn't exist (from ZK device)
            is_hidden = hidden_data.get("is_hidden", False)
            employee = Employee(
                badge_number=badge_number,
                display_name=f"User {badge_number}",
                is_active=True,
                is_hidden=is_hidden
            )
            db.add(employee)
            db.commit()
            db.refresh(employee)
        else:
            # Update existing employee hidden status
            employee.is_hidden = hidden_data.get("is_hidden", employee.is_hidden)
            db.commit()
        
        return {
            "success": True,
            "message": f"Employee visibility updated to {'hidden' if employee.is_hidden else 'visible'}",
            "badge_number": badge_number,
            "is_hidden": employee.is_hidden
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def get_employees(
    include_hidden: bool = False,
    include_inactive: bool = False,
    from_device: bool = False,
    db: Session = Depends(get_db)
):
    """Get all employees with optional filtering, including from ZK device"""
    try:
        if from_device:
            # Get users from ZK device and merge with database records
            return await get_employees_from_device(include_hidden, include_inactive, db)
        
        query = db.query(Employee)
        
        if not include_hidden:
            query = query.filter(Employee.is_hidden == False)
        
        if not include_inactive:
            query = query.filter(Employee.is_active == True)
        
        employees = query.all()
        
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
                "is_active": emp.is_active,
                "is_hidden": emp.is_hidden,
                "created_at": emp.created_at.isoformat() if emp.created_at else None,
                "in_database": True
            })
        
        return {"employees": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def get_employees_from_device(include_hidden: bool, include_inactive: bool, db: Session) -> Dict[str, Any]:
    """Get employees from ZK device and merge with database records"""
    try:
        # Get users from ZK device
        device = device_service.get_default_device()
        if not device:
            raise HTTPException(status_code=400, detail="No device configured")
        
        zk_users = device_service.get_users(device)
        
        # Get all employees from database for merging
        db_employees = {}
        query = db.query(Employee)
        if not include_hidden:
            query = query.filter(Employee.is_hidden == False)
        if not include_inactive:
            query = query.filter(Employee.is_active == True)
        
        for emp in query.all():
            db_employees[emp.badge_number] = emp
        
        # Merge ZK users with database records
        result = []
        
        for zk_user in zk_users:
            badge_number = zk_user['user_id']
            db_employee = db_employees.get(badge_number)
            
            if db_employee:
                # Employee exists in database - use database data
                if not include_hidden and db_employee.is_hidden:
                    continue
                if not include_inactive and not db_employee.is_active:
                    continue
                    
                result.append({
                    "badge_number": db_employee.badge_number,
                    "name": db_employee.display_name or "",
                    "english_name": db_employee.english_name,
                    "thai_name": db_employee.thai_name, 
                    "display_name": db_employee.display_name,
                    "department": db_employee.department,
                    "position": db_employee.position,
                        "is_active": db_employee.is_active,
                    "is_hidden": db_employee.is_hidden,
                    "created_at": db_employee.created_at.isoformat() if db_employee.created_at else None,
                    "in_database": True,
                    "zk_name": zk_user.get('name', '')
                })
            else:
                # Employee only exists in ZK device - create new record representation
                result.append({
                    "badge_number": badge_number,
                    "name": zk_user.get('name', ''),
                    "english_name": None,
                    "thai_name": None,
                    "display_name": zk_user.get('name', f"User {badge_number}"),
                    "department": None,
                    "position": None,
                        "is_active": True,  # Assume active if in ZK device
                    "is_hidden": False, # Default to visible
                    "created_at": None,
                    "in_database": False,
                    "zk_name": zk_user.get('name', '')
                })
        
        # Sort by badge number (numeric sort)
        result.sort(key=lambda x: int(x['badge_number']) if x['badge_number'].isdigit() else float('inf'))
        
        return {"employees": result}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching from device: {str(e)}")


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
            "is_active": employee.is_active,
            "is_hidden": employee.is_hidden,
            "created_at": employee.created_at.isoformat() if employee.created_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Employee creation endpoint removed - not used by frontend


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
        if employee_data.is_active is not None:
            employee.is_active = employee_data.is_active
        if employee_data.is_hidden is not None:
            employee.is_hidden = employee_data.is_hidden
        
        # Update display name
        employee.display_name = employee.thai_name or employee.english_name or f"พนักงาน {badge_number}"
        
        db.commit()
        db.refresh(employee)

        return {
            "success": True,
            "message": "Employee updated successfully",
            "badge_number": employee.badge_number,
            "english_name": employee.english_name,
            "thai_name": employee.thai_name,
            "display_name": employee.display_name,
            "department": employee.department,
            "position": employee.position,
            "is_active": employee.is_active,
            "is_hidden": employee.is_hidden
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
                "display_name": emp.display_name
            }
            for emp in employees
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/thai-names/{badge_number}")
async def update_thai_name(badge_number: str, thai_name_data: dict, db: Session = Depends(get_db)):
    """Update Thai name for an employee"""
    try:
        employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        thai_name = thai_name_data.get("thai_name", "")
        employee.thai_name = thai_name
        employee.display_name = thai_name_data.get("display_name", thai_name)
        db.commit()

        return {
            "success": True,
            "message": "Thai name updated successfully",
            "thai_name": employee.thai_name,
            "display_name": employee.display_name
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CSV IMPORT/EXPORT - REMOVED
# ============================================================================

# Import/export endpoints removed - not used by frontend


# Role management removed - simplifying employee management


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

# Health endpoint moved above /{badge_number} to avoid route conflicts