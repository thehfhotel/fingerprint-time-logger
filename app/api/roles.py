"""
Roles API

API endpoints for managing employee role assignments and job roles.
Integrates with the existing Thai names management system.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import JobRole, Employee
from app.schemas.schemas import (
    JobRoleResponse, JobRoleCreate, JobRoleUpdate,
    EmployeeRoleAssignmentResponse, EmployeeRoleAssignmentUpdate,
    BulkRoleAssignmentRequest, BulkRoleAssignmentResponse
)

router = APIRouter(prefix="/api/roles", tags=["roles"])


@router.get("/job-roles", response_model=List[JobRoleResponse])
async def get_job_roles(
    include_inactive: bool = Query(False, description="Include inactive roles"),
    db: Session = Depends(get_db)
):
    """Get all job roles"""
    query = db.query(JobRole)
    
    if not include_inactive:
        query = query.filter(JobRole.is_active == True)
    
    roles = query.order_by(JobRole.role_name).all()
    return roles


@router.get("/job-roles/{role_id}", response_model=JobRoleResponse)
async def get_job_role(role_id: int, db: Session = Depends(get_db)):
    """Get a specific job role by ID"""
    role = db.query(JobRole).filter(JobRole.id == role_id).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    return role


@router.post("/job-roles", response_model=JobRoleResponse)
async def create_job_role(role_data: JobRoleCreate, db: Session = Depends(get_db)):
    """Create a new job role"""
    # Check if role name already exists
    existing_role = db.query(JobRole).filter(JobRole.role_name == role_data.role_name).first()
    if existing_role:
        raise HTTPException(status_code=400, detail="Role name already exists")
    
    role = JobRole(**role_data.dict())
    db.add(role)
    db.commit()
    db.refresh(role)
    
    return role


@router.put("/job-roles/{role_id}", response_model=JobRoleResponse)
async def update_job_role(
    role_id: int, 
    role_data: JobRoleUpdate, 
    db: Session = Depends(get_db)
):
    """Update an existing job role"""
    role = db.query(JobRole).filter(JobRole.id == role_id).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    # Update fields if provided
    update_data = role_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(role, field, value)
    
    db.commit()
    db.refresh(role)
    
    return role


@router.delete("/job-roles/{role_id}")
async def delete_job_role(role_id: int, db: Session = Depends(get_db)):
    """Soft delete a job role (set is_active to False)"""
    role = db.query(JobRole).filter(JobRole.id == role_id).first()
    
    if not role:
        raise HTTPException(status_code=404, detail="Job role not found")
    
    # Check if role has assigned employees
    assigned_employees = db.query(Employee).filter(
        Employee.job_role_id == role_id,
        Employee.is_active == True
    ).count()
    
    if assigned_employees > 0:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete role: {assigned_employees} employees currently assigned to this role"
        )
    
    role.is_active = False
    db.commit()
    
    return {"message": "Job role deleted successfully"}


@router.get("/employee-assignments", response_model=List[EmployeeRoleAssignmentResponse])
async def get_employee_role_assignments(
    role_id: Optional[int] = Query(None, description="Filter by role ID"),
    include_unassigned: bool = Query(False, description="Include employees without role assignments"),
    db: Session = Depends(get_db)
):
    """Get employee role assignments"""
    query = db.query(Employee).filter(Employee.is_active == True)
    
    if role_id:
        query = query.filter(Employee.job_role_id == role_id)
    elif not include_unassigned:
        query = query.filter(Employee.job_role_id.isnot(None))
    
    employees = query.order_by(Employee.badge_number).all()
    
    result = []
    for employee in employees:
        result.append({
            "badge_number": employee.badge_number,
            "thai_name": employee.thai_name,
            "job_role_id": employee.job_role_id,
            "role_name": employee.job_role.role_name if employee.job_role else None,
            "role_display_name": employee.job_role.display_name if employee.job_role else None,
            "is_active": employee.is_active,
            "is_hidden": employee.is_hidden
        })
    
    return result


@router.get("/employee-assignments/{badge_number}", response_model=EmployeeRoleAssignmentResponse)
async def get_employee_role_assignment(badge_number: str, db: Session = Depends(get_db)):
    """Get role assignment for a specific employee"""
    employee = db.query(Employee).filter(
        Employee.badge_number == badge_number,
        Employee.is_active == True
    ).first()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    return {
        "badge_number": employee.badge_number,
        "thai_name": employee.thai_name,
        "job_role_id": employee.job_role_id,
        "role_name": employee.job_role.role_name if employee.job_role else None,
        "role_display_name": employee.job_role.display_name if employee.job_role else None,
        "is_active": employee.is_active,
        "is_hidden": employee.is_hidden
    }


@router.put("/employee-assignments/{badge_number}")
async def update_employee_role_assignment(
    badge_number: str,
    assignment_data: EmployeeRoleAssignmentUpdate,
    db: Session = Depends(get_db)
):
    """Update role assignment for a specific employee"""
    employee = db.query(Employee).filter(
        Employee.badge_number == badge_number,
        Employee.is_active == True
    ).first()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Validate that the role exists if provided
    if assignment_data.job_role_id:
        role = db.query(JobRole).filter(
            JobRole.id == assignment_data.job_role_id,
            JobRole.is_active == True
        ).first()
        
        if not role:
            raise HTTPException(status_code=400, detail="Invalid job role ID")
    
    # Update the role assignment
    employee.job_role_id = assignment_data.job_role_id
    db.commit()
    db.refresh(employee)
    
    return {
        "message": "Role assignment updated successfully",
        "badge_number": employee.badge_number,
        "job_role_id": employee.job_role_id,
        "role_name": employee.job_role.role_name if employee.job_role else None
    }


@router.post("/bulk-assign", response_model=BulkRoleAssignmentResponse)
async def bulk_assign_roles(
    assignment_data: BulkRoleAssignmentRequest,
    db: Session = Depends(get_db)
):
    """Bulk assign roles to multiple employees"""
    if not assignment_data.assignments:
        raise HTTPException(status_code=400, detail="No assignments provided")
    
    # Validate all employees and roles exist
    badge_numbers = [assignment.badge_number for assignment in assignment_data.assignments]
    employees = db.query(Employee).filter(
        Employee.badge_number.in_(badge_numbers),
        Employee.is_active == True
    ).all()
    
    employee_dict = {emp.badge_number: emp for emp in employees}
    
    role_ids = [assignment.job_role_id for assignment in assignment_data.assignments if assignment.job_role_id]
    roles = db.query(JobRole).filter(
        JobRole.id.in_(role_ids),
        JobRole.is_active == True
    ).all()
    
    role_dict = {role.id: role for role in roles}
    
    successful_assignments = []
    failed_assignments = []
    
    for assignment in assignment_data.assignments:
        try:
            # Check if employee exists
            if assignment.badge_number not in employee_dict:
                failed_assignments.append({
                    "badge_number": assignment.badge_number,
                    "error": "Employee not found"
                })
                continue
            
            # Check if role exists (if provided)
            if assignment.job_role_id and assignment.job_role_id not in role_dict:
                failed_assignments.append({
                    "badge_number": assignment.badge_number,
                    "error": "Invalid job role ID"
                })
                continue
            
            # Update the assignment
            employee = employee_dict[assignment.badge_number]
            employee.job_role_id = assignment.job_role_id
            
            successful_assignments.append({
                "badge_number": assignment.badge_number,
                "job_role_id": assignment.job_role_id,
                "role_name": role_dict[assignment.job_role_id].role_name if assignment.job_role_id else None
            })
            
        except Exception as e:
            failed_assignments.append({
                "badge_number": assignment.badge_number,
                "error": str(e)
            })
    
    # Commit all successful assignments
    db.commit()
    
    return {
        "total_requested": len(assignment_data.assignments),
        "successful_assignments": len(successful_assignments),
        "failed_assignments": len(failed_assignments),
        "successful": successful_assignments,
        "failed": failed_assignments
    }


@router.delete("/employee-assignments/{badge_number}")
async def remove_employee_role_assignment(badge_number: str, db: Session = Depends(get_db)):
    """Remove role assignment from an employee"""
    employee = db.query(Employee).filter(
        Employee.badge_number == badge_number,
        Employee.is_active == True
    ).first()
    
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    employee.job_role_id = None
    db.commit()
    
    return {"message": "Role assignment removed successfully"}


@router.get("/statistics")
async def get_role_assignment_statistics(db: Session = Depends(get_db)):
    """Get role assignment statistics"""
    # Total active employees
    total_employees = db.query(Employee).filter(
        Employee.is_active == True
    ).count()
    
    # Employees with role assignments
    assigned_employees = db.query(Employee).filter(
        Employee.is_active == True,
        Employee.job_role_id.isnot(None)
    ).count()
    
    # Employees without role assignments
    unassigned_employees = total_employees - assigned_employees
    
    # Role distribution
    role_distribution = db.query(
        JobRole.role_name,
        JobRole.display_name,
        db.func.count(Employee.id).label('employee_count')
    ).outerjoin(
        Employee, 
        db.and_(
            Employee.job_role_id == JobRole.id,
            Employee.is_active == True
        )
    ).filter(
        JobRole.is_active == True
    ).group_by(
        JobRole.id, JobRole.role_name, JobRole.display_name
    ).all()
    
    return {
        "total_employees": total_employees,
        "assigned_employees": assigned_employees,
        "unassigned_employees": unassigned_employees,
        "assignment_percentage": round((assigned_employees / total_employees * 100) if total_employees > 0 else 0, 1),
        "role_distribution": [
            {
                "role_name": role.role_name,
                "display_name": role.display_name,
                "employee_count": role.employee_count
            }
            for role in role_distribution
        ]
    }