"""
Simplified Export Service - Basic CSV Export
Replaces complex streaming, batch processing, and enterprise patterns
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date, timezone, timedelta
import csv
import io
import logging

from app.models.models import AttendanceRecord, Employee
from app.services.attendance_service import attendance_service

logger = logging.getLogger(__name__)


# Bangkok timezone helpers live in app.utils.timezone (single source of truth).
# CSV exports must show Bangkok-local date/time.
from app.utils.timezone import BANGKOK_TZ, to_bangkok as _to_bangkok


class SimpleExportService:
    """Simplified export service for CSV generation"""
    
    STREAMING_THRESHOLD = 10000  # Threshold for enabling streaming
    
    def __init__(self, db=None):
        """Initialize with optional database session"""
        self.db = db
    
    def export_attendance_csv(self, 
                            start_date: Optional[date] = None,
                            end_date: Optional[date] = None,
                            employee_badge: Optional[str] = None) -> str:
        """Export attendance records to CSV string"""
        try:
            # Get attendance records
            records = attendance_service.get_attendance_records(
                start_date=start_date,
                end_date=end_date,
                employee_badge=employee_badge,
                limit=10000  # Reasonable limit for single-user system
            )
            
            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Employee Badge',
                'Employee Name',
                'Date',
                'Time',
                'Action',
                'Status',
                'Device ID'
            ])
            
            # Get employee names for display
            employees = {emp.badge_number: emp.display_name 
                        for emp in attendance_service.get_employee_list()}
            
            # Write records
            for record in records:
                employee_name = employees.get(record.employee_badge_number, 
                                           f"Employee {record.employee_badge_number}")
                
                action = 'Check-in' if record.punch_type == 0 else 'Check-out'
                status_text = 'Normal'
                if record.status == 1:
                    status_text = 'Late'
                elif record.status == 2:
                    status_text = 'Early'
                
                bangkok_timestamp = _to_bangkok(record.timestamp)
                writer.writerow([
                    record.employee_badge_number,
                    employee_name,
                    bangkok_timestamp.strftime('%Y-%m-%d'),
                    bangkok_timestamp.strftime('%H:%M:%S'),
                    action,
                    status_text,
                    record.device_id
                ])
            
            csv_content = output.getvalue()
            output.close()
            
            logger.info(f"Exported {len(records)} attendance records to CSV")
            return csv_content
            
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            raise Exception(f"Export failed: {str(e)}")
    
    def export_employees_csv(self, active_only: bool = False, include_hidden: bool = True) -> str:
        """Export employee list to CSV string"""
        try:
            employees = attendance_service.get_employee_list()

            # Filter based on parameters
            if active_only:
                employees = [emp for emp in employees if emp.is_active]
            if not include_hidden:
                employees = [emp for emp in employees if not emp.is_hidden]

            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Badge Number',
                'Display Name',
                'Thai Name',
                'English Name',
                'Department',
                'Position',
                'Active',
                'Hidden',
                'Created Date'
            ])
            
            # Write employee records
            for employee in employees:
                writer.writerow([
                    employee.badge_number,
                    employee.display_name,
                    employee.thai_name or '',
                    employee.english_name or '',
                    employee.department or '',
                    employee.position or '',
                    'Yes' if employee.is_active else 'No',
                    'Yes' if employee.is_hidden else 'No',
                    employee.created_at.strftime('%Y-%m-%d %H:%M:%S') if employee.created_at else ''
                ])
            
            csv_content = output.getvalue()
            output.close()
            
            logger.info(f"Exported {len(employees)} employees to CSV")
            return csv_content
            
        except Exception as e:
            logger.error(f"Employee CSV export failed: {e}")
            raise Exception(f"Employee export failed: {str(e)}")
    
    
    
    def count_records(self, start_date=None, end_date=None, employee_ids=None, 
                     device_ids=None, punch_types=None):
        """Count records matching the filters"""
        try:
            # For simplicity, get all records and count
            records = attendance_service.get_attendance_records(
                start_date=start_date,
                end_date=end_date,
                limit=50000
            )
            
            # Apply additional filters if needed
            filtered_records = records
            if employee_ids:
                filtered_records = [r for r in filtered_records 
                                  if r.employee_badge_number in employee_ids]
            if device_ids:
                filtered_records = [r for r in filtered_records 
                                  if r.device_id in device_ids]
            if punch_types is not None:
                filtered_records = [r for r in filtered_records 
                                  if r.punch_type in punch_types]
            
            return len(filtered_records)
        except Exception as e:
            logger.error(f"Count records failed: {e}")
            return 0







    
    def export_to_csv(self, start_date=None, end_date=None, employee_ids=None,
                     device_ids=None, punch_types=None, format_type="detailed",
                     include_employee_names=True, include_device_names=True):
        """Export to CSV and return as streaming response"""
        from fastapi.responses import StreamingResponse
        
        try:
            # Get attendance records
            records = attendance_service.get_attendance_records(
                start_date=start_date,
                end_date=end_date,
                limit=50000
            )
            
            # Apply additional filters
            if employee_ids:
                records = [r for r in records if r.employee_badge_number in employee_ids]
            if device_ids:
                records = [r for r in records if r.device_id in device_ids]
            if punch_types is not None:
                records = [r for r in records if r.punch_type in punch_types]
            
            # Create CSV in memory
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header based on format
            if format_type == "detailed":
                headers = ['Employee Badge', 'Employee Name', 'Date', 'Time', 
                          'Action', 'Status', 'Device ID']
            else:
                headers = ['Employee Badge', 'Date', 'Time', 'Action']
            writer.writerow(headers)
            
            # Get employee names
            employees = {emp.badge_number: emp.display_name 
                        for emp in attendance_service.get_employee_list()}
            
            # Write records
            for record in records:
                employee_name = employees.get(record.employee_badge_number, 
                                           f"Employee {record.employee_badge_number}")
                action = 'Check-in' if record.punch_type == 0 else 'Check-out'
                
                bangkok_timestamp = _to_bangkok(record.timestamp)
                if format_type == "detailed":
                    status_text = 'Normal'
                    if hasattr(record, 'status'):
                        if record.status == 1:
                            status_text = 'Late'
                        elif record.status == 2:
                            status_text = 'Early'

                    row = [
                        record.employee_badge_number,
                        employee_name if include_employee_names else record.employee_badge_number,
                        bangkok_timestamp.strftime('%Y-%m-%d'),
                        bangkok_timestamp.strftime('%H:%M:%S'),
                        action,
                        status_text,
                        record.device_id if include_device_names else ''
                    ]
                else:
                    row = [
                        record.employee_badge_number,
                        bangkok_timestamp.strftime('%Y-%m-%d'),
                        bangkok_timestamp.strftime('%H:%M:%S'),
                        action
                    ]
                
                writer.writerow(row)
            
            # Get CSV content
            output.seek(0)
            
            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"attendance_{format_type}_{timestamp}.csv"
            
            return StreamingResponse(
                io.StringIO(output.getvalue()),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename={filename}",
                    "Content-Type": "text/csv; charset=utf-8"
                }
            )
            
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            raise
    


# Global service instance
export_service = SimpleExportService()

# Backward compatibility alias
AttendanceExportService = SimpleExportService