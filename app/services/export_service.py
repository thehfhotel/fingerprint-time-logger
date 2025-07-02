"""
Simplified Export Service - Basic CSV Export
Replaces complex streaming, batch processing, and enterprise patterns
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date
import csv
import io
import logging

from app.models.models import AttendanceRecord, Employee
from app.services.attendance_service import attendance_service

logger = logging.getLogger(__name__)


class SimpleExportService:
    """Simplified export service for CSV generation"""
    
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
                
                writer.writerow([
                    record.employee_badge_number,
                    employee_name,
                    record.timestamp.strftime('%Y-%m-%d'),
                    record.timestamp.strftime('%H:%M:%S'),
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
    
    def export_employees_csv(self) -> str:
        """Export employee list to CSV string"""
        try:
            employees = attendance_service.get_employee_list()
            
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
                'Job Role ID',
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
                    employee.job_role_id or '',
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
    
    def generate_filename(self, export_type: str, start_date: Optional[date] = None, 
                         end_date: Optional[date] = None) -> str:
        """Generate appropriate filename for export"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if export_type == 'attendance':
            if start_date and end_date:
                date_range = f"{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}"
                return f"attendance_{date_range}_{timestamp}.csv"
            else:
                return f"attendance_export_{timestamp}.csv"
        elif export_type == 'employees':
            return f"employees_export_{timestamp}.csv"
        else:
            return f"export_{timestamp}.csv"
    
    def get_export_stats(self, start_date: Optional[date] = None, 
                        end_date: Optional[date] = None) -> Dict[str, Any]:
        """Get simple export statistics"""
        try:
            records = attendance_service.get_attendance_records(
                start_date=start_date,
                end_date=end_date,
                limit=50000  # Just for counting
            )
            
            employees = attendance_service.get_employee_list()
            
            # Basic stats
            stats = {
                "total_records": len(records),
                "total_employees": len(employees),
                "date_range": {
                    "start": start_date.isoformat() if start_date else None,
                    "end": end_date.isoformat() if end_date else None
                }
            }
            
            if records:
                stats["first_record"] = records[-1].timestamp.isoformat()
                stats["last_record"] = records[0].timestamp.isoformat()
            
            return stats
            
        except Exception as e:
            logger.error(f"Export stats failed: {e}")
            return {"error": str(e)}


# Global service instance
export_service = SimpleExportService()

# Backward compatibility alias
AttendanceExportService = SimpleExportService