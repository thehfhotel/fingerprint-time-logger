from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Device
from app.schemas.schemas import (
    Device as DeviceSchema,
    DeviceCreate,
    DeviceUpdate
)

router = APIRouter()


@router.get("/", response_model=List[DeviceSchema])
async def get_devices(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    Retrieve all devices with optional filtering.
    """
    query = db.query(Device)
    
    if is_active is not None:
        query = query.filter(Device.is_active == is_active)
    
    devices = query.offset(skip).limit(limit).all()
    return devices


@router.get("/{device_id}", response_model=DeviceSchema)
async def get_device(device_id: int, db: Session = Depends(get_db)):
    """
    Get a specific device by ID.
    """
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.post("/", response_model=DeviceSchema)
async def create_device(device: DeviceCreate, db: Session = Depends(get_db)):
    """
    Create a new device.
    """
    # Check if device with same IP already exists
    existing_device = db.query(Device).filter(Device.ip_address == device.ip_address).first()
    if existing_device:
        raise HTTPException(
            status_code=400, 
            detail=f"Device with IP address {device.ip_address} already exists"
        )
    
    db_device = Device(**device.dict())
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    return db_device


@router.put("/{device_id}", response_model=DeviceSchema)
async def update_device(
    device_id: int,
    device_update: DeviceUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing device.
    """
    db_device = db.query(Device).filter(Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    update_data = device_update.dict(exclude_unset=True)
    
    # Check if updating IP to an already existing one
    if "ip_address" in update_data and update_data["ip_address"] != db_device.ip_address:
        existing_device = db.query(Device).filter(
            Device.ip_address == update_data["ip_address"],
            Device.id != device_id
        ).first()
        if existing_device:
            raise HTTPException(
                status_code=400,
                detail=f"Device with IP address {update_data['ip_address']} already exists"
            )
    
    for field, value in update_data.items():
        setattr(db_device, field, value)
    
    db.commit()
    db.refresh(db_device)
    return db_device


@router.delete("/{device_id}")
async def delete_device(device_id: int, db: Session = Depends(get_db)):
    """
    Delete a device.
    """
    db_device = db.query(Device).filter(Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Check if device has attendance records
    if db_device.attendance_records:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete device with existing attendance records"
        )
    
    db.delete(db_device)
    db.commit()
    return {"message": "Device deleted successfully"}


@router.post("/{device_id}/activate")
async def activate_device(device_id: int, db: Session = Depends(get_db)):
    """
    Activate a device.
    """
    db_device = db.query(Device).filter(Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    db_device.is_active = True
    db.commit()
    db.refresh(db_device)
    return {"message": "Device activated successfully", "device": db_device}


@router.post("/{device_id}/deactivate")
async def deactivate_device(device_id: int, db: Session = Depends(get_db)):
    """
    Deactivate a device.
    """
    db_device = db.query(Device).filter(Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    db_device.is_active = False
    db.commit()
    db.refresh(db_device)
    return {"message": "Device deactivated successfully", "device": db_device}


@router.get("/{device_id}/status")
async def get_device_status(device_id: int, db: Session = Depends(get_db)):
    """
    Get device status including last sync time and active status.
    """
    db_device = db.query(Device).filter(Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    return {
        "id": db_device.id,
        "name": db_device.name,
        "ip_address": db_device.ip_address,
        "is_active": db_device.is_active,
        "last_sync": db_device.last_sync,
        "attendance_record_count": len(db_device.attendance_records),
        "sync_log_count": len(db_device.sync_logs)
    }