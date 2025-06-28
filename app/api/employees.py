from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee
from app.schemas.schemas import (
    Employee as EmployeeSchema,
    EmployeeCreate,
    EmployeeUpdate
)

router = APIRouter()


@router.get("/", response_model=List[EmployeeSchema])
async def get_employees(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    is_active: Optional[bool] = None,
    department: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retrieve all employees with optional filtering.
    """
    query = db.query(Employee)
    
    if is_active is not None:
        query = query.filter(Employee.is_active == is_active)
    if department:
        query = query.filter(Employee.department == department)
    
    employees = query.offset(skip).limit(limit).all()
    return employees


@router.get("/{employee_id}", response_model=EmployeeSchema)
async def get_employee(employee_id: str, db: Session = Depends(get_db)):
    """
    Get a specific employee by employee_id.
    """
    employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.get("/id/{id}", response_model=EmployeeSchema)
async def get_employee_by_id(id: int, db: Session = Depends(get_db)):
    """
    Get a specific employee by database ID.
    """
    employee = db.query(Employee).filter(Employee.id == id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.post("/", response_model=EmployeeSchema)
async def create_employee(employee: EmployeeCreate, db: Session = Depends(get_db)):
    """
    Create a new employee.
    """
    # Check if employee_id already exists
    existing_employee = db.query(Employee).filter(
        Employee.employee_id == employee.employee_id
    ).first()
    if existing_employee:
        raise HTTPException(
            status_code=400, 
            detail=f"Employee with ID {employee.employee_id} already exists"
        )
    
    db_employee = Employee(**employee.dict())
    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)
    return db_employee


@router.put("/{employee_id}", response_model=EmployeeSchema)
async def update_employee(
    employee_id: str,
    employee_update: EmployeeUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing employee.
    """
    db_employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    update_data = employee_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_employee, field, value)
    
    db.commit()
    db.refresh(db_employee)
    return db_employee


@router.delete("/{employee_id}")
async def delete_employee(employee_id: str, db: Session = Depends(get_db)):
    """
    Delete an employee.
    """
    db_employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Check if employee has attendance records
    if db_employee.attendance_records:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete employee with existing attendance records"
        )
    
    db.delete(db_employee)
    db.commit()
    return {"message": "Employee deleted successfully"}


@router.post("/{employee_id}/activate")
async def activate_employee(employee_id: str, db: Session = Depends(get_db)):
    """
    Activate an employee.
    """
    db_employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    db_employee.is_active = True
    db.commit()
    db.refresh(db_employee)
    return {"message": "Employee activated successfully", "employee": db_employee}


@router.post("/{employee_id}/deactivate")
async def deactivate_employee(employee_id: str, db: Session = Depends(get_db)):
    """
    Deactivate an employee.
    """
    db_employee = db.query(Employee).filter(Employee.employee_id == employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    db_employee.is_active = False
    db.commit()
    db.refresh(db_employee)
    return {"message": "Employee deactivated successfully", "employee": db_employee}


@router.get("/search/{search_term}", response_model=List[EmployeeSchema])
async def search_employees(
    search_term: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Search employees by name or employee_id.
    """
    search_pattern = f"%{search_term}%"
    employees = db.query(Employee).filter(
        (Employee.name.ilike(search_pattern)) |
        (Employee.employee_id.ilike(search_pattern))
    ).offset(skip).limit(limit).all()
    
    return employees


@router.get("/department/{department}", response_model=List[EmployeeSchema])
async def get_employees_by_department(
    department: str,
    is_active: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """
    Get all employees in a specific department.
    """
    query = db.query(Employee).filter(Employee.department == department)
    
    if is_active is not None:
        query = query.filter(Employee.is_active == is_active)
    
    employees = query.offset(skip).limit(limit).all()
    return employees


@router.get("/stats/summary")
async def get_employee_stats(db: Session = Depends(get_db)):
    """
    Get employee statistics summary.
    """
    total_employees = db.query(Employee).count()
    active_employees = db.query(Employee).filter(Employee.is_active == True).count()
    inactive_employees = db.query(Employee).filter(Employee.is_active == False).count()
    
    # Get department distribution
    departments = db.query(Employee.department).distinct().all()
    department_stats = []
    for dept in departments:
        if dept[0]:  # Skip null departments
            count = db.query(Employee).filter(Employee.department == dept[0]).count()
            department_stats.append({"department": dept[0], "count": count})
    
    return {
        "total_employees": total_employees,
        "active_employees": active_employees,
        "inactive_employees": inactive_employees,
        "departments": department_stats
    }