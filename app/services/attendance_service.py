"""
Simplified Attendance Service - Basic CRUD Operations
Replaces complex validation, conflict resolution, and enterprise patterns
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
import csv
import logging

from app.models.models import AttendanceRecord, Employee, Device
from app.core.database import get_db

logger = logging.getLogger(__name__)


class SimpleAttendanceService:
    """Simplified attendance service with basic operations"""
    
    def get_attendance_records(self, 
                             start_date: Optional[date] = None,
                             end_date: Optional[date] = None,
                             employee_badge: Optional[str] = None,
                             limit: int = 1000) -> List[AttendanceRecord]:
        """Get attendance records with basic filtering"""
        db = next(get_db())
        try:
            query = db.query(AttendanceRecord)
            
            # Apply filters
            if start_date:
                query = query.filter(AttendanceRecord.timestamp >= start_date)
            if end_date:
                query = query.filter(AttendanceRecord.timestamp <= end_date)
            if employee_badge:
                query = query.filter(AttendanceRecord.employee_badge_number == employee_badge)
            
            # Order by timestamp (most recent first) and limit
            records = query.order_by(desc(AttendanceRecord.timestamp)).limit(limit).all()
            return records
        finally:
            db.close()
    
    def get_attendance_summary(self) -> Dict[str, Any]:
        """Get simple attendance summary for dashboard"""
        db = next(get_db())
        try:
            # Get recent records (last 100)
            records = db.query(AttendanceRecord)\
                       .order_by(desc(AttendanceRecord.timestamp))\
                       .limit(100)\
                       .all()
            
            # Group by employee
            employee_data = {}
            for record in records:
                employee_id = record.employee_badge_number
                
                if employee_id not in employee_data:
                    employee_data[employee_id] = []
                
                employee_data[employee_id].append({
                    'employee_id': employee_id,
                    'time': record.timestamp.strftime('%H:%M:%S'),
                    'date': record.timestamp.strftime('%Y-%m-%d'),
                    'date_display': record.timestamp.strftime('%m/%d'),
                    'status': 'Check-in' if record.punch_type == 0 else 'Check-out',
                    'timestamp': record.timestamp.isoformat()
                })
            
            return {
                'data': employee_data,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_employees': len(employee_data),
                'total_records': len(records)
            }
        finally:
            db.close()
    
    def create_attendance_record(self, 
                               employee_badge: str,
                               timestamp: datetime,
                               punch_type: int,
                               device_id: int,
                               status: int = 0) -> AttendanceRecord:
        """Create new attendance record"""
        db = next(get_db())
        try:
            record = AttendanceRecord(
                employee_badge_number=employee_badge,
                device_id=device_id,
                timestamp=timestamp,
                punch_type=punch_type,
                status=status,
                sync_status='synced'
            )
            
            db.add(record)
            db.commit()
            db.refresh(record)
            
            logger.info(f"Created attendance record for {employee_badge}")
            return record
        finally:
            db.close()
    
    def import_from_csv(self, csv_file_path: str) -> Dict[str, Any]:
        """Import employee data from CSV (userid.csv format)"""
        db = next(get_db())
        try:
            imported_count = 0
            updated_count = 0
            
            with open(csv_file_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                
                for row in reader:
                    badge_number = row.get('Badgenumber', '').strip()
                    thai_name = row.get('ชื่อ', '').strip()
                    
                    if not badge_number:
                        continue
                    
                    # Check if employee exists
                    employee = db.query(Employee).filter(
                        Employee.badge_number == badge_number
                    ).first()
                    
                    if employee:
                        # Update existing employee
                        if thai_name and not employee.thai_name:
                            employee.thai_name = thai_name
                            employee.display_name = thai_name
                            updated_count += 1
                    else:
                        # Create new employee
                        display_name = thai_name if thai_name else f"พนักงาน {badge_number}"
                        
                        employee = Employee(
                            badge_number=badge_number,
                            thai_name=thai_name if thai_name else None,
                            display_name=display_name,
                            is_active=True,
                            is_hidden=False
                        )
                        db.add(employee)
                        imported_count += 1
                
                db.commit()
                
                return {
                    "success": True,
                    "imported": imported_count,
                    "updated": updated_count,
                    "total_processed": imported_count + updated_count
                }
        except Exception as e:
            logger.error(f"CSV import failed: {e}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()
    
    def sync_employees_from_device(self, device_users: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Sync employees discovered from device"""
        db = next(get_db())
        try:
            synced_count = 0
            
            for user in device_users:
                user_id = str(user.get('user_id', ''))
                name = user.get('name', '')
                
                if not user_id:
                    continue
                
                # Check if employee exists
                employee = db.query(Employee).filter(
                    Employee.badge_number == user_id
                ).first()
                
                if not employee:
                    # Create new employee
                    display_name = name if name and name != f"User {user_id}" else f"พนักงาน {user_id}"
                    
                    employee = Employee(
                        badge_number=user_id,
                        english_name=name if name and name != f"User {user_id}" else None,
                        display_name=display_name,
                        is_active=True,
                        is_hidden=False
                    )
                    db.add(employee)
                    synced_count += 1
            
            db.commit()
            
            return {
                "success": True,
                "total_synced": synced_count,
                "message": f"Synced {synced_count} new employees"
            }
        except Exception as e:
            logger.error(f"Employee sync failed: {e}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()
    
    def get_employee_list(self) -> List[Employee]:
        """Get list of all active employees"""
        db = next(get_db())
        try:
            employees = db.query(Employee)\
                         .filter(Employee.is_active == True)\
                         .order_by(Employee.badge_number)\
                         .all()
            return employees
        finally:
            db.close()
    
    def validate_attendance_record(self, record: AttendanceRecord) -> Dict[str, Any]:
        """Basic attendance validation (simplified)"""
        # Just basic checks - no complex validation logic
        validation = {
            "status": "valid",
            "message": "Record is valid",
            "issues": []
        }
        
        # Check if employee exists
        db = next(get_db())
        try:
            employee = db.query(Employee).filter(
                Employee.badge_number == record.employee_badge_number
            ).first()
            
            if not employee:
                validation["status"] = "warning"
                validation["issues"].append("Employee not found in system")
        finally:
            db.close()
        
        return validation


# Global service instance
attendance_service = SimpleAttendanceService()