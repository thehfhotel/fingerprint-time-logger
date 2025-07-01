from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
from zk import ZK
from sqlalchemy.orm import Session

from app.models.models import Device, AttendanceRecord, Employee, SyncLog
from app.core.config import settings

logger = logging.getLogger(__name__)


class DeviceService:
    def __init__(self, device: Device):
        self.device = device
        self.zk = None
        self.conn = None
    
    def connect(self) -> bool:
        """Establish connection to ZKTeco device"""
        try:
            # Use default timeout of 5 seconds if device doesn't have timeout field
            timeout_value = getattr(self.device, 'timeout', 5)
            
            self.zk = ZK(
                self.device.ip_address, 
                port=self.device.port,
                timeout=timeout_value,
                password=self.device.password,
                force_udp=False,
                ommit_ping=False
            )
            self.conn = self.zk.connect()
            logger.info(f"Connected to device {self.device.name} at {self.device.ip_address}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to device {self.device.name}: {str(e)}")
            return False
    
    def disconnect(self):
        """Disconnect from ZKTeco device"""
        if self.conn:
            self.conn.disconnect()
            logger.info(f"Disconnected from device {self.device.name}")
    
    def get_users(self) -> List[Dict[str, Any]]:
        """Get all users from device"""
        if not self.conn:
            raise Exception("Not connected to device")
        
        try:
            users = self.conn.get_users()
            return [
                {
                    "uid": user.uid,
                    "user_id": user.user_id,
                    "name": user.name,
                    "privilege": user.privilege,
                    "password": user.password,
                    "group_id": user.group_id,
                    "card": user.card,
                }
                for user in users
            ]
        except Exception as e:
            logger.error(f"Failed to get users: {str(e)}")
            raise
    
    def get_attendance(self) -> List[Dict[str, Any]]:
        """Get attendance records from device"""
        if not self.conn:
            raise Exception("Not connected to device")
        
        try:
            attendances = self.conn.get_attendance()
            return [
                {
                    "user_id": att.user_id,
                    "timestamp": att.timestamp,
                    "status": att.status,
                    "punch": att.punch,
                }
                for att in attendances
            ]
        except Exception as e:
            logger.error(f"Failed to get attendance: {str(e)}")
            raise
    
    def clear_attendance(self) -> bool:
        """Clear attendance records from device"""
        if not self.conn:
            raise Exception("Not connected to device")
        
        try:
            self.conn.clear_attendance()
            logger.info(f"Cleared attendance records from device {self.device.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear attendance: {str(e)}")
            return False
    
    def sync_attendance(self, db: Session, clear_after_sync: bool = False) -> Dict[str, Any]:
        """Sync attendance records from device to database"""
        sync_log = SyncLog(
            device_id=self.device.id,
            sync_start=datetime.utcnow(),
            status="in_progress"
        )
        db.add(sync_log)
        db.commit()
        
        try:
            if not self.connect():
                raise Exception("Failed to connect to device")
            
            attendances = self.get_attendance()
            
            new_records = 0
            skipped_records = 0
            errors = []
            
            for att in attendances:
                try:
                    employee = db.query(Employee).filter(
                        Employee.employee_id == str(att["user_id"])
                    ).first()
                    
                    if not employee:
                        errors.append(f"Employee not found: {att['user_id']}")
                        skipped_records += 1
                        continue
                    
                    existing = db.query(AttendanceRecord).filter(
                        AttendanceRecord.employee_id == employee.id,
                        AttendanceRecord.device_id == self.device.id,
                        AttendanceRecord.timestamp == att["timestamp"]
                    ).first()
                    
                    if existing:
                        skipped_records += 1
                        continue
                    
                    record = AttendanceRecord(
                        employee_id=employee.id,
                        device_id=self.device.id,
                        timestamp=att["timestamp"],
                        punch_type=att["punch"],
                        status=att["status"]
                    )
                    db.add(record)
                    new_records += 1
                    
                except Exception as e:
                    errors.append(f"Error processing record: {str(e)}")
                    skipped_records += 1
            
            db.commit()
            
            if clear_after_sync and new_records > 0:
                self.clear_attendance()
            
            sync_log.sync_end = datetime.utcnow()
            sync_log.status = "completed"
            sync_log.records_synced = new_records
            sync_log.records_failed = skipped_records
            if errors:
                sync_log.error_message = "; ".join(errors[:5])
            
            db.commit()
            
            return {
                "device": self.device.name,
                "new_records": new_records,
                "skipped_records": skipped_records,
                "errors": errors[:5],
                "status": "success"
            }
            
        except Exception as e:
            sync_log.sync_end = datetime.utcnow()
            sync_log.status = "failed"
            sync_log.error_message = str(e)
            db.commit()
            
            logger.error(f"Sync failed for device {self.device.name}: {str(e)}")
            return {
                "device": self.device.name,
                "error": str(e),
                "status": "failed"
            }
        finally:
            self.disconnect()


def sync_all_devices(db: Session) -> List[Dict[str, Any]]:
    """Sync attendance from all active devices"""
    devices = db.query(Device).filter(Device.is_active == True).all()
    results = []
    
    for device in devices:
        service = DeviceService(device)
        result = service.sync_attendance(db, clear_after_sync=settings.CLEAR_DEVICE_AFTER_SYNC)
        results.append(result)
    
    return results