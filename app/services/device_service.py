"""
Simplified Device Service - Direct ZKTeco Operations

ARCHITECTURE NOTE (Cache-First Design):
- Frontend API requests DO NOT call this service directly
- Frontend requests are served from device_cache_service (cached data)
- Background scheduler calls this service every 5 minutes to refresh cache
- This ensures minimal device connections and fast API responses

Usage:
- background_scheduler.py -> device_service.py -> ZKTeco Device (every 5 minutes)
- Frontend API -> device_cache_service.py -> Cached Data (instant response)
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import time
from zk import ZK
from sqlalchemy.orm import Session

from app.models.models import Device, AttendanceRecord, Employee
from app.core.database import get_db
from app.services.logging_service import app_logger

logger = logging.getLogger(__name__)


class SimpleDeviceService:
    """Simplified device service with connection caching to reduce device load"""

    def __init__(self):
        self.max_retries = int(os.getenv('DEVICE_MAX_RETRIES', '3'))
        self.timeout = int(os.getenv('DEVICE_TIMEOUT', '5'))

        # Cache for device status to reduce connection frequency (5 minutes to match frontend)
        self._status_cache = {}
        self._status_cache_lock = threading.Lock()
        self._cache_duration = 300  # 5 minutes in seconds to match frontend health check interval

        # Cache for device time (1 minute to allow more frequent time checks)
        self._time_cache = {}
        self._time_cache_lock = threading.Lock()
        self._time_cache_duration = 60  # 1 minute for time cache
    
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
    
    def connect_to_device(self, device: Device, caller: str = None) -> Optional[Any]:
        """Simple device connection with basic retry

        Note: QR terminals don't require connections since they're web-based.
        Returns None for QR terminals without error.

        Args:
            device: Device to connect to
            caller: Optional caller identification for logging (e.g., 'get_device_status', 'get_device_time')
        """
        # Auto-detect caller if not provided
        if caller is None:
            import inspect
            frame = inspect.currentframe()
            if frame and frame.f_back:
                caller = frame.f_back.f_code.co_name

        # Skip connection for QR terminals (they don't have IP addresses)
        if device.device_type == 'qr_terminal' or not device.ip_address:
            logger.debug(f"[{caller}] Skipping connection for {device.device_type} device: {device.name}")
            return None

        start_time = datetime.now()

        for attempt in range(self.max_retries):
            try:
                zk = ZK(
                    device.ip_address,
                    port=device.port or 4370,  # Use default port if None
                    timeout=self.timeout,
                    password=device.password,
                    force_udp=False,
                    ommit_ping=True
                )
                conn = zk.connect()
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                logger.info(f"[{caller}] Device {device.name} ({device.ip_address}) connected")
                app_logger.log_device_connection(
                    device_id=device.id,
                    device_name=device.name,
                    ip_address=device.ip_address,
                    success=True,
                    caller=caller
                )
                return conn

            except Exception as e:
                logger.warning(f"[{caller}] Connection attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    logger.error(f"[{caller}] Failed to connect to device after {self.max_retries} attempts")
                    app_logger.log_device_connection(
                        device_id=device.id,
                        device_name=device.name,
                        ip_address=device.ip_address,
                        success=False,
                        error=str(e),
                        caller=caller
                    )
                    return None
        return None
    
    def get_attendance_records(self, device: Device) -> List[Dict[str, Any]]:
        """Get all attendance records from device"""
        conn = self.connect_to_device(device)
        if not conn:
            return []

        try:
            # Get all attendance records
            logger.info(f"Retrieving attendance records from device {device.name}")
            records_to_process = conn.get_attendance()
            logger.info(f"Retrieved {len(records_to_process)} attendance records from device")

            # Convert to simple format
            attendance_data = []
            current_year = datetime.now().year
            current_date = datetime.now().date()

            for record in records_to_process:
                timestamp = record.timestamp

                # Validate timestamp - only accept records from 2010 to current year
                # and not from future dates
                current_year = datetime.now().year
                if timestamp.year < 2010 or timestamp.year > current_year:
                    logger.warning(f"Skipping record with invalid year: {timestamp} for user {record.user_id}")
                    continue

                # Skip future dates
                if timestamp.date() > current_date:
                    logger.warning(f"Skipping future date: {timestamp} for user {record.user_id}")
                    continue

                attendance_data.append({
                    'user_id': str(record.user_id),
                    'timestamp': timestamp,
                    'punch_type': record.punch,  # ZKTeco library uses 'punch' not 'punch_type'
                    'status': record.status
                })

            return attendance_data
            
        except Exception as e:
            logger.error(f"Failed to get attendance records from device {device.name}: {e}")
            logger.error(f"Error type: {type(e).__name__}, Details: {str(e)}")
            # Log specific network errors for debugging
            if 'TCP packet invalid' in str(e):
                logger.error("Network communication error - device may need restart or network is unstable")
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
        """Smart sync of attendance data with checkpoint-based approach"""
        device = self.get_default_device()
        if not device:
            error_msg = "No device configured"
            app_logger.log_sync_failed(device_id=None, error=error_msg)
            return {"success": False, "message": error_msg}

        start_time = datetime.now()

        try:
            # Log sync start
            app_logger.log_sync_start(device_id=device.id, sync_type="full")

            # Get all records from device
            records = self.get_attendance_records(device)

            # Always update last sync time when sync is attempted, regardless of new records
            self.update_last_sync()

            if not records:
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                # Check if this was due to connection failure or genuinely no records
                logger.warning(f"No records retrieved during sync - check device connectivity")
                app_logger.log_sync_completed(
                    device_id=device.id,
                    synced_count=0,
                    total_processed=0,
                    sync_type="full",
                    duration_ms=duration_ms
                )
                return {"success": True, "message": "ไม่มีบันทึกใหม่", "synced": 0, "total_processed": 0}
            
            # Store in database
            db = next(get_db())
            synced_count = 0
            logger.info(f"Processing {len(records)} records for database storage")

            try:
                for record in records:
                    # ZKTeco device returns Bangkok time (UTC+7), convert to UTC first
                    bangkok_time = record['timestamp']
                    utc_time = bangkok_time.replace(tzinfo=timezone(timedelta(hours=7))).astimezone(timezone.utc).replace(tzinfo=None)

                    # Check if record already exists (using UTC time)
                    existing = db.query(AttendanceRecord).filter(
                        AttendanceRecord.employee_badge_number == record['user_id'],
                        AttendanceRecord.timestamp == utc_time  # Check against UTC time
                    ).first()

                    if not existing:
                        # Create new record
                        new_record = AttendanceRecord(
                            employee_badge_number=record['user_id'],
                            device_id=device.id,
                            timestamp=utc_time,  # Store as UTC
                            punch_type=record['punch_type'],
                            status=record['status'],
                            sync_status='synced'
                        )
                        db.add(new_record)
                        synced_count += 1
                
                db.commit()

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                app_logger.log_sync_completed(
                    device_id=device.id,
                    synced_count=synced_count,
                    total_processed=len(records),
                    sync_type="full",
                    duration_ms=duration_ms
                )

                return {
                    "success": True,
                    "message": f"ซิงค์แล้ว {synced_count} บันทึกใหม่",
                    "synced": synced_count,
                    "total_processed": len(records)
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            app_logger.log_sync_failed(
                device_id=device.id if device else None,
                error=str(e),
                sync_type="full"
            )
            return {"success": False, "message": f"การซิงค์ล้มเหลว: {str(e)}"}
    
    def get_device_status(self) -> Dict[str, Any]:
        """
        Get simple device status

        Returns device connection status and basic info.
        Connection success is determined by successful connection,
        not by firmware query success.
        """
        device = self.get_default_device()
        if not device:
            return {"connected": False, "message": "ไม่ได้ตั้งค่าเครื่อง"}

        conn = self.connect_to_device(device)
        if conn:
            firmware_version = "N/A"
            try:
                # Try to get firmware info (optional, not critical for connection status)
                firmware_version = conn.get_firmware_version()
            except Exception as e:
                # Firmware query failed, but device is still connected
                logger.warning(f"Connected to device but firmware query failed: {e}")
                firmware_version = "Unknown"

            try:
                conn.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting from device: {e}")

            # Return success - connection worked even if firmware query didn't
            return {
                "connected": True,
                "device_name": device.name,
                "ip_address": device.ip_address,
                "firmware": firmware_version,
                "last_sync": device.last_sync.isoformat() if device.last_sync else None
            }
        else:
            return {"connected": False, "message": "ไม่สามารถเชื่อมต่อเครื่องได้"}
    
    def get_device_time(self, auto_sync: bool = True) -> Dict[str, Any]:
        """Get device clock time with optional auto-sync when difference > 30 seconds"""
        device = self.get_default_device()
        if not device:
            return {"success": False, "message": "ไม่ได้ตั้งค่าเครื่อง"}
        
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
                return {"success": False, "message": f"ไม่สามารถดึงเวลาเครื่องได้: {str(e)}"}
        else:
            return {"success": False, "message": "ไม่สามารถเชื่อมต่อเครื่องได้"}
    
    def set_device_time(self, target_time: Optional[datetime] = None) -> Dict[str, Any]:
        """Set device clock time"""
        device = self.get_default_device()
        if not device:
            return {"success": False, "message": "ไม่ได้ตั้งค่าเครื่อง"}

        # Use current server time if no target time specified
        if target_time is None:
            target_time = datetime.now()

        start_time = datetime.now()
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
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                success = abs(time_diff) < 5

                # Log the time sync operation
                app_logger.log_action(
                    level="INFO" if success else "WARNING",
                    category="system",
                    action="time_sync",
                    message=f"Device time sync {'successful' if success else 'completed with drift'} - {time_diff:.1f}s difference",
                    device_id=device.id,
                    duration_ms=duration_ms,
                    success=success,
                    details={
                        "old_time": old_device_time.isoformat(),
                        "target_time": target_time.isoformat(),
                        "new_time": new_device_time.isoformat(),
                        "time_difference_seconds": time_diff
                    }
                )

                conn.disconnect()
                return {
                    "success": True,
                    "message": "อัปเดตเวลาเครื่องสำเร็จแล้ว",
                    "old_time": old_device_time.isoformat(),
                    "target_time": target_time.isoformat(),
                    "new_time": new_device_time.isoformat(),
                    "time_difference_seconds": time_diff,
                    "synchronized": success
                }
            except Exception as e:
                logger.error(f"Failed to set device time: {e}")
                app_logger.log_action(
                    level="ERROR",
                    category="system",
                    action="time_sync_failed",
                    message=f"Failed to set device time: {str(e)}",
                    device_id=device.id,
                    success=False,
                    details={"error": str(e), "target_time": target_time.isoformat()}
                )
                try:
                    conn.disconnect()
                except:
                    pass
                return {"success": False, "message": f"ไม่สามารถตั้งเวลาเครื่องได้: {str(e)}"}
        else:
            app_logger.log_action(
                level="ERROR",
                category="system",
                action="time_sync_failed",
                message="Could not connect to device for time sync",
                device_id=device.id,
                success=False
            )
            return {"success": False, "message": "ไม่สามารถเชื่อมต่อเครื่องได้"}

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
                    device.last_sync = datetime.now(timezone.utc)
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