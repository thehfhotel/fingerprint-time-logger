from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.core.database import get_db
from app.models.models import AttendanceRecord, Employee
from app.schemas.schemas import (
    AttendanceRecord as AttendanceRecordSchema,
    AttendanceRecordCreate,
    AttendanceRecordUpdate,
    AttendanceFilter
)

router = APIRouter()


@router.get("/", response_model=List[AttendanceRecordSchema])
async def get_attendance_records(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    employee_id: Optional[str] = None,
    device_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    punch_type: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Retrieve attendance records with optional filtering.
    """
    query = db.query(AttendanceRecord)
    
    # Apply filters
    filters = []
    if employee_id:
        filters.append(AttendanceRecord.employee_id == employee_id)
    if device_id:
        filters.append(AttendanceRecord.device_id == device_id)
    if start_date:
        filters.append(AttendanceRecord.timestamp >= start_date)
    if end_date:
        filters.append(AttendanceRecord.timestamp <= end_date)
    if punch_type is not None:
        filters.append(AttendanceRecord.punch_type == punch_type)
    
    if filters:
        query = query.filter(and_(*filters))
    
    records = query.offset(skip).limit(limit).all()
    return records


@router.get("/{record_id}", response_model=AttendanceRecordSchema)
async def get_attendance_record(record_id: int, db: Session = Depends(get_db)):
    """
    Get a specific attendance record by ID.
    """
    record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    return record


@router.post("/", response_model=AttendanceRecordSchema)
async def create_attendance_record(
    record: AttendanceRecordCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new attendance record.
    """
    # Verify employee exists
    employee = db.query(Employee).filter(Employee.employee_id == record.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    db_record = AttendanceRecord(**record.dict())
    db.add(db_record)
    db.commit()
    db.refresh(db_record)
    return db_record


@router.put("/{record_id}", response_model=AttendanceRecordSchema)
async def update_attendance_record(
    record_id: int,
    record_update: AttendanceRecordUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing attendance record.
    """
    db_record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    update_data = record_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_record, field, value)
    
    db.commit()
    db.refresh(db_record)
    return db_record


@router.delete("/{record_id}")
async def delete_attendance_record(record_id: int, db: Session = Depends(get_db)):
    """
    Delete an attendance record.
    """
    db_record = db.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not db_record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    db.delete(db_record)
    db.commit()
    return {"message": "Attendance record deleted successfully"}


@router.get("/employee/{employee_id}", response_model=List[AttendanceRecordSchema])
async def get_employee_attendance(
    employee_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: Session = Depends(get_db)
):
    """
    Get all attendance records for a specific employee.
    """
    query = db.query(AttendanceRecord).filter(AttendanceRecord.employee_id == employee_id)
    
    if start_date:
        query = query.filter(AttendanceRecord.timestamp >= start_date)
    if end_date:
        query = query.filter(AttendanceRecord.timestamp <= end_date)
    
    records = query.order_by(AttendanceRecord.timestamp.desc()).offset(skip).limit(limit).all()
    return records


@router.get("/today/", response_model=List[AttendanceRecordSchema])
async def get_today_attendance(
    device_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Get today's attendance records.
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
    
    query = db.query(AttendanceRecord).filter(
        and_(
            AttendanceRecord.timestamp >= today_start,
            AttendanceRecord.timestamp <= today_end
        )
    )
    
    if device_id:
        query = query.filter(AttendanceRecord.device_id == device_id)
    
    records = query.order_by(AttendanceRecord.timestamp.desc()).all()
    return records