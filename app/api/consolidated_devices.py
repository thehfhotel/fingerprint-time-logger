"""
Consolidated Devices API - Simple device management and sync
Replaces: devices.py, sync.py, unlimited_sync.py, control.py, diagnostics.py
"""

from typing import List, Dict, Any, Optional
import os
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.models import Device
from app.services.device_service import device_service

router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class DeviceCreate(BaseModel):
    name: str
    ip_address: str
    port: int = 4370
    password: int = 0
    is_active: bool = True


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    password: Optional[int] = None
    is_active: Optional[bool] = None
    device_type: Optional[str] = None
    device_metadata: Optional[str] = None  # JSON string for GPS and other metadata


# ============================================================================
# DEVICE MANAGEMENT
# ============================================================================

@router.get("/")
async def get_devices(db: Session = Depends(get_db)):
    """Get all devices"""
    try:
        devices = db.query(Device).all()
        return {
            "devices": [
                {
                    "id": device.id,
                    "name": device.name,
                    "ip_address": device.ip_address,
                    "port": device.port,
                    "password": device.password,
                    "is_active": device.is_active,
                    "device_type": device.device_type,
                    "device_metadata": device.device_metadata,
                    "last_sync": device.last_sync.isoformat() if device.last_sync else None,
                    "created_at": device.created_at.isoformat() if device.created_at else None
                }
                for device in devices
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/default")
async def get_default_device():
    """Get the default/primary device"""
    try:
        device = device_service.get_default_device()
        if not device:
            return {"message": "ไม่ได้ตั้งค่าเครื่องเริ่มต้น"}
        
        return {
            "id": device.id,
            "name": device.name,
            "ip_address": device.ip_address,
            "port": device.port,
            "is_active": device.is_active,
            "last_sync": device.last_sync.isoformat() if device.last_sync else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Device creation endpoint removed - not used by frontend


# ============================================================================
# HEALTH CHECK (must come before /{device_id} to avoid route conflict)
# ============================================================================

@router.get("/health")
async def devices_health_check():
    """Lightweight health check with caching to reduce device load"""
    try:
        # Use cached device service to reduce frequent connections
        from app.services.device_service_cached import cached_device_service

        # Get cached device status (10-minute cache)
        device_status = cached_device_service.get_device_status()

        if not device_status:
            return {
                "status": "warning",
                "device_connected": False,
                "message": "ไม่ได้ตั้งค่าเครื่อง"
            }

        connected = device_status.get("connected", False)

        response = {
            "status": "healthy" if connected else "unhealthy",
            "device_connected": connected,
            "device_name": device_status.get("device_name", "Unknown"),
            "ip": device_status.get("ip_address", "Unknown"),
            "cache_age_seconds": device_status.get("cache_age_seconds", 0)
        }

        # Add lightweight device info using cached data only
        if connected:
            # Get device time with caching (no auto-sync to avoid connections)
            try:
                time_info = cached_device_service.get_device_time(auto_sync=False)
                device_time = time_info.get("device_time", "Unknown")
                response["device_time"] = device_time
                response["time_cache_age"] = time_info.get("cache_age_seconds", 0)
            except Exception:
                response["device_time"] = "Unavailable"

            # Get counts from database only (no device queries)
            db = next(get_db())
            try:
                from app.models.models import Employee, AttendanceRecord
                users_count = db.query(Employee).count()
                records_count = db.query(AttendanceRecord).count()
            except Exception:
                users_count = "Unknown"
                records_count = "Unknown"
            finally:
                db.close()

            response.update({
                "users_count": users_count,
                "records_count": records_count,
                "device_time": device_time,
                "info_note": "Counts from database - sync for latest device data"
            })

        return response
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# ============================================================================
# DEVICE CONNECTION & STATUS
# ============================================================================

@router.get("/status")
async def get_device_status():
    """Get device connection status (uses 10-minute cache to reduce device connections)"""
    try:
        from app.services.device_service_cached import cached_device_service
        status = cached_device_service.get_device_status()
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-connection")
async def test_device_connection():
    """Test connection to the default device"""
    try:
        device = device_service.get_default_device()
        if not device:
            raise HTTPException(status_code=400, detail="No device configured")
        
        conn = device_service.connect_to_device(device)
        if conn:
            try:
                # Get basic device info
                users_count = len(device_service.get_users(device))
                records_count = len(device_service.get_attendance_records(device))
                
                return {
                    "success": True,
                    "message": "เชื่อมต่อสำเร็จ",
                    "device_info": {
                        "name": device.name,
                        "ip_address": device.ip_address,
                        "users_count": users_count,
                        "records_count": records_count
                    }
                }
            except Exception as e:
                return {
                    "success": True,
                    "message": "เชื่อมต่อแล้วแต่ไม่สามารถดึงข้อมูลเครื่องได้",
                    "warning": str(e)
                }
        else:
            return {
                "success": False,
                "message": "ไม่สามารถเชื่อมต่อเครื่องได้"
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DATA SYNCHRONIZATION
# ============================================================================

@router.post("/sync-time")
async def sync_device_time():
    """Sync system time to device"""
    try:
        result = device_service.sync_time_to_device()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Time sync failed: {str(e)}")

@router.post("/sync/attendance")
async def sync_attendance():
    """Sync attendance data from device"""
    try:
        result = device_service.sync_attendance_data()

        # Broadcast update to WebSocket clients
        if result.get("success"):
            try:
                from app.main_unified import manager
                from app.services.attendance_service import attendance_service
                from datetime import datetime

                attendance_data = attendance_service.get_attendance_summary()
                await manager.broadcast({
                    "type": "manual_import_update",
                    "data": attendance_data,
                    "synced_records": result.get('synced', 0),
                    "timestamp": datetime.now().isoformat(),
                    "message": f"นำเข้าด้วยตนเอง: ซิงค์แล้ว {result.get('synced', 0)} บันทึก"
                })
            except Exception as broadcast_error:
                # Log but don't fail the request if broadcast fails
                import logging
                logging.warning(f"Failed to broadcast manual import update: {broadcast_error}")

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Device users endpoint removed - not used by frontend


# Attendance preview endpoint removed - not used by frontend


@router.get("/time")
async def get_device_time(auto_sync: bool = Query(False, description="Automatically sync if difference > 30 seconds")):
    """Get device clock time (uses 1-minute cache to reduce device connections)"""
    try:
        from app.services.device_service_cached import cached_device_service
        result = cached_device_service.get_device_time(auto_sync=auto_sync)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/time/sync")
async def sync_device_time():
    """Sync device time to current server time"""
    try:
        result = device_service.set_device_time()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Device time set endpoint removed - not used by frontend


# ============================================================================
# DEVICE CONFIGURATION
# ============================================================================

@router.get("/config")
async def get_device_config():
    """Get device configuration"""
    try:
        device = device_service.get_default_device()
        if not device:
            return {"message": "ไม่ได้ตั้งค่าเครื่อง"}
        
        return {
            "device": {
                "name": device.name,
                "ip_address": device.ip_address,
                "port": device.port,
                "timeout": device_service.timeout,
                "max_retries": device_service.max_retries
            },
            "sync_settings": {
                "auto_sync": False,  # Simplified - no background sync
                "last_sync": device.last_sync.isoformat() if device.last_sync else None
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CONFIGURATION API
# ============================================================================

@router.get("/app-config")
async def get_app_configuration():
    """Get application configuration for frontend"""
    return {
        "api": {
            "baseUrl": "/api",
            "timeout": int(os.getenv('API_TIMEOUT', '30000')),
            "retryAttempts": int(os.getenv('API_RETRY_ATTEMPTS', '3'))
        },
        "websocket": {
            "reconnectAttempts": int(os.getenv('WS_RECONNECT_ATTEMPTS', '5')),
            "reconnectDelay": int(os.getenv('WS_RECONNECT_DELAY', '1000')),
            "pingInterval": int(os.getenv('WS_PING_INTERVAL', '30000'))
        },
        "ui": {
            "refreshInterval": int(os.getenv('UI_REFRESH_INTERVAL', '120000')),
            "healthCheckInterval": int(os.getenv('UI_HEALTH_CHECK_INTERVAL', '60000')),
            "dateFormat": os.getenv('UI_DATE_FORMAT', 'en-US'),
            "timeFormat": {
                "hour12": os.getenv('UI_TIME_HOUR12', 'false').lower() == 'true'
            }
        },
        "device": {
            "defaultTimeout": int(os.getenv('DEVICE_TIMEOUT', '5')),
            "maxRetries": int(os.getenv('DEVICE_MAX_RETRIES', '3'))
        }
    }


# ============================================================================
# SIMPLE DIAGNOSTICS
# ============================================================================

@router.get("/diagnostics")
async def get_device_diagnostics():
    """Get basic device diagnostics"""
    try:
        device = device_service.get_default_device()
        if not device:
            return {"status": "no_device", "message": "ไม่ได้ตั้งค่าเครื่อง"}
        
        # Test connection
        conn = device_service.connect_to_device(device)
        if not conn:
            return {
                "status": "connection_failed",
                "device": {
                    "name": device.name,
                    "ip_address": device.ip_address,
                    "port": device.port
                },
                "last_sync": device.last_sync.isoformat() if device.last_sync else None
            }
        
        try:
            # Get basic info
            users = device_service.get_users(device)
            records = device_service.get_attendance_records(device)
            
            return {
                "status": "healthy",
                "device": {
                    "name": device.name,
                    "ip_address": device.ip_address,
                    "port": device.port,
                    "connected": True
                },
                "data": {
                    "users_count": len(users),
                    "records_count": len(records),
                    "last_sync": device.last_sync.isoformat() if device.last_sync else None
                },
                "performance": {
                    "connection_time": f"{device_service.timeout}s timeout",
                    "max_retries": device_service.max_retries
                }
            }
        except Exception as e:
            return {
                "status": "connected_but_error",
                "device": {
                    "name": device.name,
                    "ip_address": device.ip_address,
                    "connected": True
                },
                "error": str(e)
            }
        finally:
            try:
                conn.disconnect()
            except:
                pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DEVICE CRUD OPERATIONS (Path Parameters)
# Note: These routes MUST be defined last to avoid catching specific routes
# ============================================================================

@router.get("/{device_id}")
async def get_device_by_id(
    device_id: int,
    db: Session = Depends(get_db)
):
    """Get a specific device by ID"""
    try:
        device = db.query(Device).filter(Device.id == device_id).first()

        if not device:
            raise HTTPException(status_code=404, detail=f"Device ID {device_id} not found")

        return {
            "id": device.id,
            "name": device.name,
            "ip_address": device.ip_address,
            "port": device.port,
            "password": device.password,
            "is_active": device.is_active,
            "device_type": device.device_type,
            "device_metadata": device.device_metadata,
            "last_sync": device.last_sync.isoformat() if device.last_sync else None,
            "created_at": device.created_at.isoformat() if device.created_at else None,
            "updated_at": device.updated_at.isoformat() if device.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{device_id}")
async def update_device(
    device_id: int,
    device_update: DeviceUpdate,
    db: Session = Depends(get_db)
):
    """
    Update device information

    Supports updating GPS metadata for QR terminals via device_metadata field
    """
    try:
        device = db.query(Device).filter(Device.id == device_id).first()

        if not device:
            raise HTTPException(status_code=404, detail=f"Device ID {device_id} not found")

        # Update fields if provided
        update_data = device_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(device, field, value)

        db.commit()
        db.refresh(device)

        return {
            "success": True,
            "message": f"Device {device.name} updated successfully",
            "device": {
                "id": device.id,
                "name": device.name,
                "ip_address": device.ip_address,
                "port": device.port,
                "is_active": device.is_active,
                "device_type": device.device_type,
                "device_metadata": device.device_metadata,
                "updated_at": device.updated_at.isoformat() if device.updated_at else None
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update device: {str(e)}")


@router.delete("/{device_id}")
async def delete_device(
    device_id: int,
    db: Session = Depends(get_db)
):
    """Delete a device by ID"""
    try:
        from app.models.models import AttendanceRecord

        device = db.query(Device).filter(Device.id == device_id).first()

        if not device:
            raise HTTPException(status_code=404, detail=f"Device ID {device_id} not found")

        # Check if device has attendance records
        attendance_count = db.query(AttendanceRecord).filter(
            AttendanceRecord.device_id == device_id
        ).count()

        if attendance_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete device with {attendance_count} attendance records. Delete records first or deactivate device instead."
            )

        device_name = device.name
        db.delete(device)
        db.commit()

        return {
            "success": True,
            "message": f"Device {device_name} deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete device: {str(e)}")
