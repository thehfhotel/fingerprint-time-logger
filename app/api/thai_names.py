"""
Thai Name Management API Endpoints
Provides CRUD operations for managing employee Thai name mappings
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, Field, validator

from app.core.database import get_db
from app.models.models import EmployeeThaiName, AttendanceRecord

router = APIRouter(prefix="/api/thai-names", tags=["Thai Names"])


# Pydantic Models
class ThaiNameBase(BaseModel):
    badge_number: str = Field(..., min_length=1, max_length=50, description="Employee badge number")
    thai_name: str = Field(..., min_length=1, max_length=100, description="Thai name for employee")
    
    @validator('thai_name')
    def validate_thai_name(cls, v):
        if not v.strip():
            raise ValueError('Thai name cannot be empty')
        return v.strip()
    
    @validator('badge_number')
    def validate_badge_number(cls, v):
        if not v.strip():
            raise ValueError('Badge number cannot be empty')
        return v.strip()


class ThaiNameCreate(ThaiNameBase):
    pass


class ThaiNameUpdate(BaseModel):
    thai_name: str = Field(..., min_length=1, max_length=100, description="Updated Thai name")
    
    @validator('thai_name')
    def validate_thai_name(cls, v):
        if not v.strip():
            raise ValueError('Thai name cannot be empty')
        return v.strip()


class ThaiNameResponse(ThaiNameBase):
    id: int
    is_active: bool
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


class ThaiNameBulkUpdate(BaseModel):
    updates: List[ThaiNameBase] = Field(..., description="List of Thai name updates")


class ThaiNameSyncResponse(BaseModel):
    success: bool
    new_badge_numbers: List[str]
    total_synced: int
    message: str


# API Endpoints
@router.get("/", response_model=List[ThaiNameResponse])
def get_all_thai_names(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Retrieve all Thai name mappings with optional search and pagination
    """
    # Debug: Check total count first
    total_count = db.query(EmployeeThaiName).count()
    active_count = db.query(EmployeeThaiName).filter(EmployeeThaiName.is_active == True).count()
    print(f"DEBUG: Total Thai names: {total_count}, Active: {active_count}")
    
    query = db.query(EmployeeThaiName).filter(EmployeeThaiName.is_active == True)
    
    # Add search filter if provided
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (EmployeeThaiName.badge_number.ilike(search_term)) |
            (EmployeeThaiName.thai_name.ilike(search_term))
        )
    
    # Order by badge number (try numeric, fallback to string)
    try:
        query = query.order_by(func.cast(EmployeeThaiName.badge_number, 'INTEGER').asc())
    except:
        query = query.order_by(EmployeeThaiName.badge_number.asc())
    
    thai_names = query.offset(skip).limit(limit).all()
    
    # Convert datetime to string for JSON serialization
    result = []
    for thai_name in thai_names:
        thai_name_dict = {
            "id": thai_name.id,
            "badge_number": thai_name.badge_number,
            "thai_name": thai_name.thai_name,
            "is_active": thai_name.is_active,
            "created_at": thai_name.created_at.isoformat() if thai_name.created_at else None,
            "updated_at": thai_name.updated_at.isoformat() if thai_name.updated_at else None
        }
        result.append(thai_name_dict)
    
    return result


@router.get("/{badge_number}", response_model=ThaiNameResponse)
def get_thai_name(badge_number: str, db: Session = Depends(get_db)):
    """
    Get Thai name for a specific badge number
    """
    thai_name = db.query(EmployeeThaiName).filter(
        EmployeeThaiName.badge_number == badge_number,
        EmployeeThaiName.is_active == True
    ).first()
    
    if not thai_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thai name not found for badge number: {badge_number}"
        )
    
    return {
        "id": thai_name.id,
        "badge_number": thai_name.badge_number,
        "thai_name": thai_name.thai_name,
        "is_active": thai_name.is_active,
        "created_at": thai_name.created_at.isoformat() if thai_name.created_at else None,
        "updated_at": thai_name.updated_at.isoformat() if thai_name.updated_at else None
    }


@router.post("/", response_model=ThaiNameResponse)
def create_thai_name(thai_name_data: ThaiNameCreate, db: Session = Depends(get_db)):
    """
    Create a new Thai name mapping
    """
    # Check if badge number already exists
    existing = db.query(EmployeeThaiName).filter(
        EmployeeThaiName.badge_number == thai_name_data.badge_number
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Thai name already exists for badge number: {thai_name_data.badge_number}"
        )
    
    # Create new Thai name record
    db_thai_name = EmployeeThaiName(
        badge_number=thai_name_data.badge_number,
        thai_name=thai_name_data.thai_name,
        is_active=True
    )
    
    db.add(db_thai_name)
    db.commit()
    db.refresh(db_thai_name)
    
    return {
        "id": db_thai_name.id,
        "badge_number": db_thai_name.badge_number,
        "thai_name": db_thai_name.thai_name,
        "is_active": db_thai_name.is_active,
        "created_at": db_thai_name.created_at.isoformat() if db_thai_name.created_at else None,
        "updated_at": db_thai_name.updated_at.isoformat() if db_thai_name.updated_at else None
    }


@router.put("/{badge_number}", response_model=ThaiNameResponse)
def update_thai_name(
    badge_number: str, 
    thai_name_update: ThaiNameUpdate, 
    db: Session = Depends(get_db)
):
    """
    Update Thai name for a specific badge number
    """
    thai_name = db.query(EmployeeThaiName).filter(
        EmployeeThaiName.badge_number == badge_number,
        EmployeeThaiName.is_active == True
    ).first()
    
    if not thai_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thai name not found for badge number: {badge_number}"
        )
    
    # Update Thai name
    thai_name.thai_name = thai_name_update.thai_name
    thai_name.updated_at = func.now()
    
    db.commit()
    db.refresh(thai_name)
    
    return {
        "id": thai_name.id,
        "badge_number": thai_name.badge_number,
        "thai_name": thai_name.thai_name,
        "is_active": thai_name.is_active,
        "created_at": thai_name.created_at.isoformat() if thai_name.created_at else None,
        "updated_at": thai_name.updated_at.isoformat() if thai_name.updated_at else None
    }


@router.put("/", response_model=dict)
def bulk_update_thai_names(bulk_update: ThaiNameBulkUpdate, db: Session = Depends(get_db)):
    """
    Bulk update multiple Thai names in a single transaction
    """
    if not bulk_update.updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No updates provided"
        )
    
    updated_count = 0
    errors = []
    
    try:
        # Process all updates in a single transaction
        for update in bulk_update.updates:
            thai_name = db.query(EmployeeThaiName).filter(
                EmployeeThaiName.badge_number == update.badge_number,
                EmployeeThaiName.is_active == True
            ).first()
            
            if thai_name:
                thai_name.thai_name = update.thai_name
                thai_name.updated_at = func.now()
                updated_count += 1
            else:
                # Create new record if it doesn't exist
                new_thai_name = EmployeeThaiName(
                    badge_number=update.badge_number,
                    thai_name=update.thai_name,
                    is_active=True
                )
                db.add(new_thai_name)
                updated_count += 1
        
        db.commit()
        
        return {
            "success": True,
            "updated_count": updated_count,
            "message": f"Successfully updated {updated_count} Thai names",
            "errors": errors
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk update failed: {str(e)}"
        )


@router.delete("/{badge_number}", response_model=dict)
def delete_thai_name(badge_number: str, db: Session = Depends(get_db)):
    """
    Soft delete a Thai name (mark as inactive)
    """
    thai_name = db.query(EmployeeThaiName).filter(
        EmployeeThaiName.badge_number == badge_number,
        EmployeeThaiName.is_active == True
    ).first()
    
    if not thai_name:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thai name not found for badge number: {badge_number}"
        )
    
    # Soft delete (mark as inactive)
    thai_name.is_active = False
    thai_name.updated_at = func.now()
    
    db.commit()
    
    return {
        "success": True,
        "message": f"Thai name for badge number {badge_number} has been deleted"
    }


@router.post("/sync", response_model=ThaiNameSyncResponse)
def sync_badge_numbers_from_attendance(db: Session = Depends(get_db)):
    """
    Auto-discover new badge numbers from attendance records and create default Thai names
    """
    try:
        # Get all unique employee IDs from attendance records
        attendance_badge_numbers = db.query(AttendanceRecord.employee_id).distinct().all()
        attendance_badge_numbers = [row[0] for row in attendance_badge_numbers]
        
        # Get existing badge numbers from Thai names
        existing_badge_numbers = db.query(EmployeeThaiName.badge_number).all()
        existing_badge_numbers = [row[0] for row in existing_badge_numbers]
        
        # Find new badge numbers that don't have Thai names
        new_badge_numbers = [
            badge for badge in attendance_badge_numbers 
            if badge not in existing_badge_numbers
        ]
        
        # Create default Thai names for new badge numbers
        created_count = 0
        for badge_number in new_badge_numbers:
            default_thai_name = f"พนักงาน {badge_number}"
            
            new_thai_name = EmployeeThaiName(
                badge_number=badge_number,
                thai_name=default_thai_name,
                is_active=True
            )
            
            db.add(new_thai_name)
            created_count += 1
        
        db.commit()
        
        return ThaiNameSyncResponse(
            success=True,
            new_badge_numbers=new_badge_numbers,
            total_synced=created_count,
            message=f"Successfully synced {created_count} new badge numbers"
        )
        
    except Exception as e:
        db.rollback()
        return ThaiNameSyncResponse(
            success=False,
            new_badge_numbers=[],
            total_synced=0,
            message=f"Sync failed: {str(e)}"
        )


@router.get("/export/csv", response_model=dict)
def export_thai_names_csv(db: Session = Depends(get_db)):
    """
    Export Thai names to CSV format for backup
    """
    thai_names = db.query(EmployeeThaiName).filter(
        EmployeeThaiName.is_active == True
    ).order_by(EmployeeThaiName.badge_number).all()
    
    csv_data = "Badgenumber,USERID,ชื่อ\n"
    for thai_name in thai_names:
        csv_data += f"{thai_name.badge_number},{thai_name.badge_number},{thai_name.thai_name}\n"
    
    return {
        "success": True,
        "csv_data": csv_data,
        "total_records": len(thai_names),
        "message": "CSV export completed successfully"
    }