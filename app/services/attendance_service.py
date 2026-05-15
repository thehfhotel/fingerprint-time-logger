"""
Simplified Attendance Service - Basic CRUD Operations
Replaces complex validation, conflict resolution, and enterprise patterns
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, timezone, timedelta
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
                             device_id: Optional[int] = None,
                             device_ids: Optional[List[int]] = None,
                             limit: int = 1000) -> List[AttendanceRecord]:
        """Get attendance records with basic filtering

        NOTE: start_date and end_date are interpreted as Bangkok timezone dates.
        They are converted to UTC datetime ranges for database queries.
        Database stores UTC timestamps, but users filter by Bangkok dates.
        """
        db = next(get_db())
        try:
            query = db.query(AttendanceRecord)

            # Convert Bangkok dates to UTC datetime ranges for filtering
            # Database stores UTC, but users select Bangkok dates
            bangkok_tz = timezone(timedelta(hours=7))

            if start_date:
                # Bangkok date 2025-10-04 00:00:00 → UTC 2025-10-03 17:00:00
                bangkok_start = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=bangkok_tz)
                utc_start = bangkok_start.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(AttendanceRecord.timestamp >= utc_start)
                logger.debug(f"Filter: Bangkok {start_date} 00:00 → UTC >= {utc_start}")

            if end_date:
                # Bangkok date 2025-10-04 23:59:59.999999 → UTC 2025-10-04 16:59:59.999999
                bangkok_end = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=bangkok_tz)
                utc_end = bangkok_end.astimezone(timezone.utc).replace(tzinfo=None)
                query = query.filter(AttendanceRecord.timestamp <= utc_end)
                logger.debug(f"Filter: Bangkok {end_date} 23:59 → UTC <= {utc_end}")

            if employee_badge:
                query = query.filter(AttendanceRecord.employee_badge_number == employee_badge)

            # device_ids takes precedence over device_id when both are passed.
            # Used by the kiosk /recent endpoint to pull QR check-ins + linked
            # fingerprint scans in a single query.
            if device_ids:
                query = query.filter(AttendanceRecord.device_id.in_(device_ids))
            elif device_id is not None:
                query = query.filter(AttendanceRecord.device_id == device_id)

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
                # Ensure timezone-aware datetime (SQLite stores as text, loses tzinfo on read)
                dt = device.last_sync
                if dt.tzinfo is None:
                    # Assume UTC if no timezone info (backward compatibility)
                    dt = dt.replace(tzinfo=timezone.utc)
                last_import_time = dt.isoformat()
            
            # Group by employee
            employee_data = {}
            for record in records:
                employee_id = record.employee_badge_number
                
                if employee_id not in employee_data:
                    employee_data[employee_id] = []
                
                # Convert UTC to Bangkok timezone for WebSocket display (dashboard uses time field directly)
                utc_timestamp = record.timestamp.replace(tzinfo=timezone.utc)
                bangkok_timestamp = utc_timestamp.astimezone()  # Convert to Bangkok (UTC+7)

                employee_data[employee_id].append({
                    'id': record.id,
                    'employee_id': employee_id,
                    'time': bangkok_timestamp.strftime('%H:%M:%S'),  # Bangkok time for display
                    'date': bangkok_timestamp.strftime('%Y-%m-%d'),  # Bangkok date
                    'date_display': bangkok_timestamp.strftime('%d/%m/%Y'),  # Bangkok date in DD/MM/YYYY format
                    'status': 'Check-in' if record.punch_type == 0 else 'Check-out',
                    'timestamp': utc_timestamp.isoformat()  # Keep UTC with +00:00 for API consumers
                })
            
            return {
                'data': employee_data,
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