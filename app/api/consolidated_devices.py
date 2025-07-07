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


# ============================================================================
# DEVICE MANAGEMENT
# ============================================================================

@router.get("/")
async def get_devices(db: Session = Depends(get_db)):
    """Get all devices"""
    try:
        devices = db.query(Device).all()
        return [
            {
                "id": device.id,
                "name": device.name,
                "ip_address": device.ip_address,
                "port": device.port,
                "password": device.password,
                "is_active": device.is_active,
                "last_sync": device.last_sync.isoformat() if device.last_sync else None,
                "created_at": device.created_at.isoformat() if device.created_at else None
            }
            for device in devices
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/default")
async def get_default_device():
    """Get the default/primary device"""
    try:
        device = device_service.get_default_device()
        if not device:
            return {"message": "No default device configured"}
        
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


@router.post("/")
async def create_device(device_data: DeviceCreate, db: Session = Depends(get_db)):
    """Create a new device"""
    try:
        device = Device(
            name=device_data.name,
            ip_address=device_data.ip_address,
            port=device_data.port,
            password=device_data.password,
            is_active=device_data.is_active
        )
        
        db.add(device)
        db.commit()
        db.refresh(device)
        
        return {
            "success": True,
            "message": "Device created successfully",
            "device_id": device.id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{device_id}")
async def update_device(device_id: int, device_data: DeviceUpdate, db: Session = Depends(get_db)):
    """Update a device"""
    try:
        device = db.query(Device).filter(Device.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        if device_data.name is not None:
            device.name = device_data.name
        if device_data.ip_address is not None:
            device.ip_address = device_data.ip_address
        if device_data.port is not None:
            device.port = device_data.port
        if device_data.password is not None:
            device.password = device_data.password
        if device_data.is_active is not None:
            device.is_active = device_data.is_active
        
        db.commit()
        
        return {
            "success": True,
            "message": "Device updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DEVICE CONNECTION & STATUS
# ============================================================================

@router.get("/status")
async def get_device_status():
    """Get device connection status"""
    try:
        status = device_service.get_device_status()
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
                    "message": "Connection successful",
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
                    "message": "Connected but failed to get device info",
                    "warning": str(e)
                }
        else:
            return {
                "success": False,
                "message": "Failed to connect to device"
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
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync/users")
async def get_device_users():
    """Get users from device"""
    try:
        device = device_service.get_default_device()
        if not device:
            raise HTTPException(status_code=400, detail="No device configured")
        
        users = device_service.get_users(device)
        return {
            "users": users,
            "total": len(users)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync/attendance-preview")
async def preview_attendance_data():
    """Preview attendance data from device without saving"""
    try:
        device = device_service.get_default_device()
        if not device:
            raise HTTPException(status_code=400, detail="No device configured")
        
        records = device_service.get_attendance_records(device)
        
        # Return preview of recent records
        preview_records = []
        for record in records[-50:]:  # Last 50 records
            preview_records.append({
                "user_id": record["user_id"],
                "timestamp": record["timestamp"].isoformat(),
                "punch_type": "check-in" if record["punch_type"] == 0 else "check-out",
                "status": record["status"]
            })
        
        return {
            "preview": preview_records,
            "total_available": len(records),
            "showing": len(preview_records)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/time")
async def get_device_time(auto_sync: bool = Query(True, description="Automatically sync if difference > 30 seconds")):
    """Get device clock time with optional auto-sync"""
    try:
        result = device_service.get_device_time(auto_sync=auto_sync)
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


class SetTimeRequest(BaseModel):
    target_time: str

@router.post("/time/set")
async def set_device_time(request: SetTimeRequest):
    """Set device time to specific timestamp (ISO format)"""
    try:
        from datetime import datetime
        # Parse the ISO timestamp
        target_datetime = datetime.fromisoformat(request.target_time.replace('Z', '+00:00'))
        result = device_service.set_device_time(target_datetime)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# DEVICE CONFIGURATION
# ============================================================================

@router.get("/config")
async def get_device_config():
    """Get device configuration"""
    try:
        device = device_service.get_default_device()
        if not device:
            return {"message": "No device configured"}
        
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
            return {"status": "no_device", "message": "No device configured"}
        
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
# HEALTH CHECK
# ============================================================================

@router.get("/health")
async def devices_health_check():
    """Lightweight health check to avoid device overload"""
    try:
        device = device_service.get_default_device()
        if not device:
            return {
                "status": "warning", 
                "device_connected": False,
                "message": "No device configured"
            }
        
        # Lightweight check - just test basic connectivity without data retrieval
        try:
            conn = device_service.connect_to_device(device)
            if conn:
                # Just verify connection and disconnect immediately
                conn.disconnect()
                connected = True
            else:
                connected = False
        except Exception:
            connected = False
        
        response = {
            "status": "healthy" if connected else "unhealthy",
            "device_connected": connected,
            "device_name": device.name,
            "ip": device.ip_address,
            "last_sync": device.last_sync.isoformat() if device.last_sync else None
        }
        
        # Add lightweight device info without overwhelming queries
        if connected:
            # Get device time efficiently (lightweight operation)
            try:
                time_info = device_service.get_device_time(auto_sync=False)
                device_time = time_info.get("device_time", "Unknown")
            except Exception:
                device_time = "Unavailable"
            
            # Get actual counts from database for better accuracy
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