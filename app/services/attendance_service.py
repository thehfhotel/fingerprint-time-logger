"""
Simplified Attendance Service - Basic CRUD Operations
Replaces complex validation, conflict resolution, and enterprise patterns
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, desc
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
            
            # Filter out future dates (year 2065 and beyond)
            current_year = datetime.now().year
            max_year = current_year + 5  # Allow up to 5 years in the future for clock skew
            query = query.filter(AttendanceRecord.timestamp < datetime(max_year, 1, 1))
            
            # Order by timestamp (most recent first) and limit
            records = query.order_by(desc(AttendanceRecord.timestamp)).limit(limit).all()
            return records
        finally:
            db.close()
    
    def get_attendance_summary(self) -> Dict[str, Any]:
        """Get simple attendance summary for dashboard"""
        db = next(get_db())
        try:
            
            # Get recent records (last 100), filtering out future dates
            current_year = datetime.now().year
            max_year = current_year + 5  # Allow up to 5 years in the future for clock skew
            records = db.query(AttendanceRecord)\
                       .filter(AttendanceRecord.timestamp < datetime(max_year, 1, 1))\
                       .order_by(desc(AttendanceRecord.timestamp))\
                       .limit(100)\
                       .all()
            
            # Get device last sync time for last import indicator
            from app.models.models import Device
            # Refresh the session to ensure we get the latest data
            db.expire_all()
            device = db.query(Device).first()
            last_import_time = None
            if device and device.last_sync:
                # Return ISO format timestamp with timezone info for proper client-side conversion
                last_import_time = device.last_sync.isoformat()
            
            # Group by employee
            employee_data = {}
            for record in records:
                employee_id = record.employee_badge_number
                
                if employee_id not in employee_data:
                    employee_data[employee_id] = []
                
                employee_data[employee_id].append({
                    'id': record.id,
                    'employee_id': employee_id,
                    'time': record.timestamp.strftime('%H:%M:%S'),
                    'date': record.timestamp.strftime('%Y-%m-%d'),
                    'date_display': record.timestamp.strftime('%m/%d/%Y'),
                    'status': 'Check-in' if record.punch_type == 0 else 'Check-out',
                    'timestamp': record.timestamp.isoformat()
                })
            
            return {
                'data': employee_data,
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'last_import': last_import_time,
                'total_employees': len(employee_data),
                'total_records': len(records)
            }
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
    


# Global service instance
attendance_service = SimpleAttendanceService()