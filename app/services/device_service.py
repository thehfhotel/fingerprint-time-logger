"""
Simplified Device Service - Direct ZKTeco Operations
Replaces complex connection management, circuit breakers, and enterprise patterns
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
import os
from zk import ZK
from sqlalchemy.orm import Session

from app.models.models import Device, AttendanceRecord, Employee
from app.core.database import get_db

logger = logging.getLogger(__name__)


class SimpleDeviceService:
    """Simplified device service with basic retry logic"""
    
    def __init__(self):
        self.max_retries = int(os.getenv('DEVICE_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('DEVICE_TIMEOUT', '5'))
    
    def get_default_device(self) -> Optional[Device]:
        """Get the default ZKTeco device"""
        db = next(get_db())
        try:
            device = db.query(Device).filter(Device.is_active == True).first()
            if not device:
                # Create default device if none exists
                device = Device(
                    name=os.getenv('DEVICE_NAME', 'ZKTeco Device'),
                    ip_address=os.getenv('ZKTECO_HOST', '192.168.100.209'),
                    port=int(os.getenv('ZKTECO_PORT', '4370')),
                    password=int(os.getenv('ZKTECO_PASSWORD', '0')),
                    is_active=True
                )
                db.add(device)
                db.commit()
                db.refresh(device)
            return device
        finally:
            db.close()
    
    def connect_to_device(self, device: Device) -> Optional[Any]:
        """Simple device connection with basic retry"""
        for attempt in range(self.max_retries):
            try:
                zk = ZK(
                    device.ip_address,
                    port=device.port,
                    timeout=self.timeout,
                    password=device.password,
                    force_udp=False,
                    ommit_ping=True
                )
                conn = zk.connect()
                logger.info(f"Connected to device {device.name}")
                return conn
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    logger.error(f"Failed to connect to device after {self.max_retries} attempts")
                    return None
        return None
    
    def get_attendance_records(self, device: Device) -> List[Dict[str, Any]]:
        """Get attendance records from device"""
        conn = self.connect_to_device(device)
        if not conn:
            return []
        
        try:
            # Get attendance records
            records = conn.get_attendance()
            
            # Convert to simple format
            attendance_data = []
            for record in records:
                attendance_data.append({
                    'user_id': str(record.user_id),
                    'timestamp': record.timestamp,
                    'punch_type': record.punch,  # ZKTeco library uses 'punch' not 'punch_type'
                    'status': record.status
                })
            
            logger.info(f"Retrieved {len(attendance_data)} attendance records")
            return attendance_data
            
        except Exception as e:
            logger.error(f"Error getting attendance records: {e}")
            return []
        finally:
            try:
                conn.disconnect()
            except:
                pass
    
    def get_users(self, device: Device) -> List[Dict[str, Any]]:
        """Get users from device"""
        conn = self.connect_to_device(device)
        if not conn:
            return []
        
        try:
            users = conn.get_users()
            user_data = []
            for user in users:
                user_data.append({
                    'user_id': str(user.user_id),
                    'name': user.name or f"User {user.user_id}",
                    'privilege': user.privilege,
                    'password': user.password,
                    'group_id': user.group_id,
                    'user_id_int': user.user_id
                })
            
            logger.info(f"Retrieved {len(user_data)} users")
            return user_data
            
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []
        finally:
            try:
                conn.disconnect()
            except:
                pass
    
    def sync_attendance_data(self) -> Dict[str, Any]:
        """Simple sync of attendance data from device to database"""
        device = self.get_default_device()
        if not device:
            return {"success": False, "message": "No device configured"}
        
        try:
            # Get records from device
            records = self.get_attendance_records(device)
            
            # Always update last sync time when sync is attempted, regardless of new records
            self.update_last_sync()
            
            if not records:
                return {"success": True, "message": "No new records", "synced": 0, "total_processed": 0}
            
            # Store in database
            db = next(get_db())
            synced_count = 0
            
            try:
                for record in records:
                    # Check if record already exists
                    existing = db.query(AttendanceRecord).filter(
                        AttendanceRecord.employee_badge_number == record['user_id'],
                        AttendanceRecord.timestamp == record['timestamp']
                    ).first()
                    
                    if not existing:
                        # Create new record
                        new_record = AttendanceRecord(
                            employee_badge_number=record['user_id'],
                            device_id=device.id,
                            timestamp=record['timestamp'],
                            punch_type=record['punch_type'],
                            status=record['status'],
                            sync_status='synced'
                        )
                        db.add(new_record)
                        synced_count += 1
                
                db.commit()
                
                return {
                    "success": True,
                    "message": f"Synced {synced_count} new records",
                    "synced": synced_count,
                    "total_processed": len(records)
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return {"success": False, "message": f"Sync failed: {str(e)}"}
    
    def get_device_status(self) -> Dict[str, Any]:
        """Get simple device status"""
        device = self.get_default_device()
        if not device:
            return {"connected": False, "message": "No device configured"}
        
        conn = self.connect_to_device(device)
        if conn:
            try:
                # Basic device info
                firmware_version = conn.get_firmware_version()
                conn.disconnect()
                return {
                    "connected": True,
                    "device_name": device.name,
                    "ip_address": device.ip_address,
                    "firmware": firmware_version,
                    "last_sync": device.last_sync.isoformat() if device.last_sync else None
                }
            except:
                try:
                    conn.disconnect()
                except:
                    pass
                return {"connected": False, "message": "Device connection failed"}
        else:
            return {"connected": False, "message": "Could not connect to device"}
    
    def get_device_time(self, auto_sync: bool = True) -> Dict[str, Any]:
        """Get device clock time with optional auto-sync when difference > 30 seconds"""
        device = self.get_default_device()
        if not device:
            return {"success": False, "message": "No device configured"}
        
        conn = self.connect_to_device(device)
        if conn:
            try:
                # Get device time
                device_time = conn.get_time()
                server_time = datetime.now()
                
                # Calculate time difference
                time_diff = (device_time - server_time).total_seconds()
                original_time_diff = time_diff  # Store original difference
                auto_synced = False
                
                # Auto-sync if difference is more than 30 seconds
                if auto_sync and abs(time_diff) > 30:
                    logger.warning(f"Device time differs by {time_diff:.1f} seconds. Auto-syncing...")
                    try:
                        # Set device time to server time
                        conn.set_time(server_time)
                        
                        # Verify the sync
                        new_device_time = conn.get_time()
                        new_time_diff = (new_device_time - server_time).total_seconds()
                        
                        logger.info(f"Auto-sync completed. New difference: {new_time_diff:.1f} seconds")
                        auto_synced = True
                        
                        # Update variables with new values
                        device_time = new_device_time
                        time_diff = new_time_diff
                        
                    except Exception as sync_error:
                        logger.error(f"Auto-sync failed: {sync_error}")
                        # Continue with original values if sync fails
                
                conn.disconnect()
                result = {
                    "success": True,
                    "device_time": device_time.isoformat(),
                    "server_time": server_time.isoformat(),
                    "time_difference_seconds": time_diff,
                    "synchronized": abs(time_diff) < 60,  # Consider synchronized if within 1 minute
                    "auto_synced": auto_synced
                }
                
                if auto_synced:
                    result["message"] = f"Device time was automatically synchronized (was {original_time_diff:.1f}s off)"
                
                return result
                
            except Exception as e:
                logger.error(f"Failed to get device time: {e}")
                try:
                    conn.disconnect()
                except:
                    pass
                return {"success": False, "message": f"Failed to get device time: {str(e)}"}
        else:
            return {"success": False, "message": "Could not connect to device"}
    
    def set_device_time(self, target_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Set device clock time"""
        device = self.get_default_device()
        if not device:
            return {"success": False, "message": "No device configured"}
        
        # Use current server time if no target time specified
        if target_time is None:
            target_time = datetime.now()
        
        conn = self.connect_to_device(device)
        if conn:
            try:
                # Get current device time before setting
                old_device_time = conn.get_time()
                
                # Set new device time
                conn.set_time(target_time)
                
                # Verify the time was set by reading it back
                new_device_time = conn.get_time()
                
                # Calculate time difference
                time_diff = (new_device_time - target_time).total_seconds()
                
                conn.disconnect()
                return {
                    "success": True,
                    "message": "Device time updated successfully",
                    "old_time": old_device_time.isoformat(),
                    "target_time": target_time.isoformat(),
                    "new_time": new_device_time.isoformat(),
                    "time_difference_seconds": time_diff,
                    "synchronized": abs(time_diff) < 5  # Consider synchronized if within 5 seconds
                }
            except Exception as e:
                logger.error(f"Failed to set device time: {e}")
                try:
                    conn.disconnect()
                except:
                    pass
                return {"success": False, "message": f"Failed to set device time: {str(e)}"}
        else:
            return {"success": False, "message": "Could not connect to device"}

    def sync_time_to_device(self) -> Dict[str, Any]:
        """Sync current system time to device"""
        result = self.set_device_time()
        if result.get("success"):
            self.update_last_sync()
        return result
    
    def update_last_sync(self):
        """Update the device's last sync timestamp"""
        try:
            db = next(get_db())
            try:
                device = db.query(Device).filter(Device.is_active == True).first()
                if device:
                    device.last_sync = datetime.now()
                    db.commit()
                    logger.info(f"Updated last sync time for device {device.name}")
                else:
                    logger.warning("No active device found to update sync time")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to update last sync time: {e}")


# Global service instance
device_service = SimpleDeviceService()