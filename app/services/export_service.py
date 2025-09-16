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

    def export_summary_csv(self, summary: Dict[str, Any]) -> str:
        """Export attendance summary to CSV"""
        try:
            output = io.StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow(['Metric', 'Value'])

            # Write summary data
            for key, value in summary.items():
                if isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        writer.writerow([f"{key}_{sub_key}", str(sub_value)])
                else:
                    writer.writerow([key, str(value)])

            return output.getvalue()
        except Exception as e:
            logger.error(f"Summary CSV export failed: {e}")
            raise Exception(f"Summary export failed: {str(e)}")

    def export_thai_names_csv(self) -> str:
        """Export Thai names to CSV"""
        try:
            employees = attendance_service.get_employee_list()

            output = io.StringIO()
            writer = csv.writer(output)

            writer.writerow(['Badge Number', 'English Name', 'Thai Name', 'Display Name'])

            for employee in employees:
                writer.writerow([
                    employee.badge_number,
                    employee.english_name or '',
                    employee.thai_name or '',
                    employee.display_name or ''
                ])

            return output.getvalue()
        except Exception as e:
            logger.error(f"Thai names CSV export failed: {e}")
            raise Exception(f"Thai names export failed: {str(e)}")

    def generate_monthly_report(self, year: int, month: int, records: List[Any]) -> Dict[str, Any]:
        """Generate monthly report data"""
        try:
            return {
                "report_type": "monthly",
                "year": year,
                "month": month,
                "total_records": len(records),
                "period": f"{year}-{month:02d}",
                "summary": {
                    "records_count": len(records),
                    "unique_employees": len(set(r.employee_badge_number for r in records))
                }
            }
        except Exception as e:
            logger.error(f"Monthly report generation failed: {e}")
            raise Exception(f"Monthly report failed: {str(e)}")

    def export_monthly_report_csv(self, report: Dict[str, Any]) -> str:
        """Export monthly report to CSV"""
        try:
            output = io.StringIO()
            writer = csv.writer(output)

            writer.writerow(['Report Type', 'Monthly'])
            writer.writerow(['Year', report.get('year', 'N/A')])
            writer.writerow(['Month', report.get('month', 'N/A')])
            writer.writerow(['Total Records', report.get('total_records', 0)])

            return output.getvalue()
        except Exception as e:
            logger.error(f"Monthly report CSV export failed: {e}")
            raise Exception(f"Monthly report CSV failed: {str(e)}")

    def generate_employee_summary_report(self, employee_badge: str, records: List[Any]) -> Dict[str, Any]:
        """Generate employee summary report"""
        try:
            employees = attendance_service.get_employee_list()
            employee = next((emp for emp in employees if emp.badge_number == employee_badge), None)

            if not employee:
                raise Exception(f"Employee {employee_badge} not found")

            return {
                "report_type": "employee_summary",
                "employee": {
                    "badge_number": employee.badge_number,
                    "display_name": employee.display_name
                },
                "records_count": len(records),
                "summary": {
                    "total_records": len(records),
                    "checkins": len([r for r in records if r.punch_type == 0]),
                    "checkouts": len([r for r in records if r.punch_type == 1])
                }
            }
        except Exception as e:
            logger.error(f"Employee summary generation failed: {e}")
            raise Exception(f"Employee summary failed: {str(e)}")

    def export_employee_summary_csv(self, report: Dict[str, Any]) -> str:
        """Export employee summary to CSV"""
        try:
            output = io.StringIO()
            writer = csv.writer(output)

            writer.writerow(['Employee Badge', report['employee']['badge_number']])
            writer.writerow(['Employee Name', report['employee']['display_name']])
            writer.writerow(['Total Records', report['records_count']])

            return output.getvalue()
        except Exception as e:
            logger.error(f"Employee summary CSV export failed: {e}")
            raise Exception(f"Employee summary CSV failed: {str(e)}")

    def test_export_capability(self) -> bool:
        """Test if export service is working"""
        try:
            # Simple test - try to get employee count
            employees = attendance_service.get_employee_list()
            return True
        except Exception as e:
            logger.error(f"Export capability test failed: {e}")
            return False
    
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
                        record.timestamp.strftime('%Y-%m-%d'),
                        record.timestamp.strftime('%H:%M:%S'),
                        action,
                        status_text,
                        record.device_id if include_device_names else ''
                    ]
                else:
                    row = [
                        record.employee_badge_number,
                        record.timestamp.strftime('%Y-%m-%d'),
                        record.timestamp.strftime('%H:%M:%S'),
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
    
    def export_to_csv_streaming(self, start_date=None, end_date=None, employee_ids=None,
                               device_ids=None, punch_types=None, format_type="detailed",
                               include_employee_names=True, include_device_names=True,
                               batch_size=1000, max_records=None):
        """Export to CSV with streaming for large datasets"""
        try:
            # Get all records
            records = attendance_service.get_attendance_records(
                start_date=start_date,
                end_date=end_date,
                limit=max_records or 100000
            )
            
            # Apply filters
            if employee_ids:
                records = [r for r in records if r.employee_badge_number in employee_ids]
            if device_ids:
                records = [r for r in records if r.device_id in device_ids]
            if punch_types is not None:
                records = [r for r in records if r.punch_type in punch_types]
            
            # Get employee names once
            employees = {emp.badge_number: emp.display_name 
                        for emp in attendance_service.get_employee_list()}
            
            # Write header
            if format_type == "detailed":
                headers = ['Employee Badge', 'Employee Name', 'Date', 'Time', 
                          'Action', 'Status', 'Device ID']
            else:
                headers = ['Employee Badge', 'Date', 'Time', 'Action']
            
            yield ','.join(headers) + '\n'
            
            # Stream records in batches
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                output = io.StringIO()
                writer = csv.writer(output)
                
                for record in batch:
                    employee_name = employees.get(record.employee_badge_number, 
                                               f"Employee {record.employee_badge_number}")
                    action = 'Check-in' if record.punch_type == 0 else 'Check-out'
                    
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
                            record.timestamp.strftime('%Y-%m-%d'),
                            record.timestamp.strftime('%H:%M:%S'),
                            action,
                            status_text,
                            record.device_id if include_device_names else ''
                        ]
                    else:
                        row = [
                            record.employee_badge_number,
                            record.timestamp.strftime('%Y-%m-%d'),
                            record.timestamp.strftime('%H:%M:%S'),
                            action
                        ]
                    
                    writer.writerow(row)
                
                # Yield this batch
                output.seek(0)
                content = output.getvalue()
                if content:
                    yield content
                    
        except Exception as e:
            logger.error(f"Streaming CSV export failed: {e}")
            yield f"ERROR: {str(e)}\n"


# Global service instance
export_service = SimpleExportService()

# Backward compatibility alias
AttendanceExportService = SimpleExportService