"""
Attendance Export Service - CSV export functionality
"""

from io import StringIO
import csv
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Generator
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func
from fastapi.responses import StreamingResponse
import logging

from app.models.models import AttendanceRecord, Employee, Device
from app.core.config import settings

logger = logging.getLogger(__name__)


class AttendanceExportService:
    """Service for exporting attendance records to various formats"""
    
    def __init__(self, db: Session):
        self.db = db
        # Configurable batch sizes for different formats
        self.BATCH_SIZES = {
            'raw': min(5000, settings.csv_export_max_batch_size),      # Simple format, larger batches
            'detailed': min(1000, settings.csv_export_default_batch_size),  # Complex format with joins, smaller batches
            'summary': min(2000, settings.csv_export_default_batch_size)    # Medium complexity
        }
        self.STREAMING_THRESHOLD = settings.csv_export_streaming_threshold  # Auto-enable streaming above this
    
    def export_to_csv(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        employee_ids: Optional[List[str]] = None,
        device_ids: Optional[List[int]] = None,
        punch_types: Optional[List[int]] = None,
        format_type: str = "detailed",
        include_employee_names: bool = True,
        include_device_names: bool = True
    ) -> StreamingResponse:
        """
        Export attendance records as CSV file
        
        Args:
            start_date: Start date for filtering records
            end_date: End date for filtering records
            employee_ids: List of employee IDs to include
            device_ids: List of device IDs to include
            punch_types: List of punch types to include
            format_type: Export format (detailed, summary, raw)
            include_employee_names: Include Thai employee names
            include_device_names: Include device names
            
        Returns:
            StreamingResponse with CSV content
        """
        # Build query with filters
        query = self._build_query(
            start_date, end_date, employee_ids, device_ids, punch_types
        )
        
        # Generate CSV content
        csv_content = self._generate_csv(
            query, format_type, include_employee_names, include_device_names
        )
        
        # Generate filename
        filename = self._generate_filename(start_date, end_date, format_type)
        
        # Return streaming response
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )
    
    def _build_query(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        employee_ids: Optional[List[str]],
        device_ids: Optional[List[int]],
        punch_types: Optional[List[int]]
    ):
        """Build SQLAlchemy query with filters"""
        query = self.db.query(AttendanceRecord)\
            .join(Employee, AttendanceRecord.employee_badge_number == Employee.badge_number, isouter=True)\
            .join(Device, AttendanceRecord.device_id == Device.id, isouter=True)
        
        # Apply date filters
        if start_date:
            query = query.filter(AttendanceRecord.timestamp >= start_date)
        if end_date:
            # Include the entire end date
            end_date_inclusive = end_date + timedelta(days=1)
            query = query.filter(AttendanceRecord.timestamp < end_date_inclusive)
        
        # Apply employee filter
        if employee_ids:
            query = query.filter(AttendanceRecord.employee_badge_number.in_(employee_ids))
        
        # Apply device filter
        if device_ids:
            query = query.filter(AttendanceRecord.device_id.in_(device_ids))
        
        # Apply punch type filter
        if punch_types:
            query = query.filter(AttendanceRecord.punch_type.in_(punch_types))
        
        return query.order_by(AttendanceRecord.timestamp.desc())
    
    def _generate_csv(
        self,
        query,
        format_type: str,
        include_employee_names: bool,
        include_device_names: bool
    ) -> str:
        """Generate CSV content based on format type"""
        output = StringIO()
        writer = csv.writer(output)
        
        if format_type == "detailed":
            return self._generate_detailed_csv(query, writer, include_employee_names, include_device_names)
        elif format_type == "summary":
            return self._generate_summary_csv(query, writer, include_employee_names)
        elif format_type == "raw":
            return self._generate_raw_csv(query, writer)
        else:
            raise ValueError(f"Unsupported format type: {format_type}")
    
    def _generate_detailed_csv(self, query, writer, include_employee_names: bool, include_device_names: bool) -> str:
        """Generate detailed CSV format"""
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        headers = ['Badge Number', 'Timestamp', 'Punch Type', 'Status', 'Sync Status']
        
        if include_employee_names:
            headers.insert(1, 'Employee Name (Thai)')
        if include_device_names:
            headers.insert(-3, 'Device Name')
        
        writer.writerow(headers)
        
        # Write data rows
        for record in query:
            row = [record.employee_id]
            
            if include_employee_names:
                # Get Thai name from unified Employee model
                thai_name = record.employee.thai_name if record.employee and record.employee.thai_name else record.employee.display_name if record.employee else ''
                row.append(thai_name)
            
            row.append(record.timestamp.strftime('%Y-%m-%d %H:%M:%S'))
            
            if include_device_names:
                device_name = record.device.name if record.device else f"Device {record.device_id}"
                row.append(device_name)
            
            row.extend([
                self._format_punch_type(record.punch_type),
                self._format_status(record.status),
                record.sync_status
            ])
            
            writer.writerow(row)
        
        return output.getvalue()
    
    def _generate_summary_csv(self, query, writer, include_employee_names: bool) -> str:
        """Generate daily summary CSV format"""
        output = StringIO()
        writer = csv.writer(output)
        
        # Group records by employee and date
        daily_data = {}
        
        for record in query:
            date_key = record.timestamp.date()
            emp_key = record.employee_id
            key = (emp_key, date_key)
            
            if key not in daily_data:
                # Get Thai name from unified Employee model
                thai_name = ''
                if include_employee_names:
                    thai_name = record.employee.thai_name if record.employee and record.employee.thai_name else record.employee.display_name if record.employee else ''
                
                daily_data[key] = {
                    'badge_number': emp_key,
                    'employee_name': thai_name,
                    'date': date_key,
                    'check_in': None,
                    'check_out': None,
                    'records': []
                }
            
            daily_data[key]['records'].append(record)
            
            # Track first check-in and last check-out
            if record.punch_type == 0:  # Check in
                if daily_data[key]['check_in'] is None or record.timestamp < daily_data[key]['check_in']:
                    daily_data[key]['check_in'] = record.timestamp
            elif record.punch_type == 1:  # Check out
                if daily_data[key]['check_out'] is None or record.timestamp > daily_data[key]['check_out']:
                    daily_data[key]['check_out'] = record.timestamp
        
        # Write header
        headers = ['Badge Number', 'Date', 'Check In', 'Check Out', 'Work Hours', 'Status']
        if include_employee_names:
            headers.insert(1, 'Employee Name')
        writer.writerow(headers)
        
        # Write summary rows
        for (emp_id, date), data in sorted(daily_data.items()):
            row = [data['badge_number']]
            
            if include_employee_names:
                row.append(data['employee_name'])
            
            row.append(data['date'].strftime('%Y-%m-%d'))
            
            check_in_str = data['check_in'].strftime('%H:%M') if data['check_in'] else ''
            check_out_str = data['check_out'].strftime('%H:%M') if data['check_out'] else ''
            
            # Calculate work hours
            work_hours = ''
            if data['check_in'] and data['check_out']:
                duration = data['check_out'] - data['check_in']
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                work_hours = f"{hours}h {minutes}m"
            
            # Determine status
            status = 'Incomplete'
            if data['check_in'] and data['check_out']:
                status = 'Complete'
            elif data['check_in']:
                status = 'No Check Out'
            elif data['check_out']:
                status = 'No Check In'
            
            row.extend([check_in_str, check_out_str, work_hours, status])
            writer.writerow(row)
        
        return output.getvalue()
    
    def _generate_raw_csv(self, query, writer) -> str:
        """Generate raw database format CSV"""
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'ID', 'Employee ID', 'Device ID', 'Timestamp', 'Punch Type', 
            'Status', 'Created At', 'Sync Status', 'Local ID', 'Created Locally'
        ])
        
        # Write data rows
        for record in query:
            writer.writerow([
                record.id,
                record.employee_id,
                record.device_id,
                record.timestamp.strftime('%Y-%m-%d %H:%M:%S') if record.timestamp else '',
                record.punch_type,
                record.status,
                record.created_at.strftime('%Y-%m-%d %H:%M:%S') if record.created_at else '',
                record.sync_status,
                record.local_id or '',
                record.created_locally
            ])
        
        return output.getvalue()
    
    def _format_punch_type(self, punch_type: int) -> str:
        """Format punch type for display"""
        types = {
            0: 'Check In',
            1: 'Check Out',
            2: 'Break Out',
            3: 'Break In',
            4: 'OT In',
            5: 'OT Out'
        }
        return types.get(punch_type, f'Unknown ({punch_type})')
    
    def _format_status(self, status: int) -> str:
        """Format status for display"""
        statuses = {
            0: 'Normal',
            1: 'Late',
            2: 'Early'
        }
        return statuses.get(status, f'Unknown ({status})')
    
    def _generate_filename(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        format_type: str
    ) -> str:
        """Generate appropriate filename for export"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if start_date and end_date:
            date_range = f"{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}"
            return f"attendance_{format_type}_{date_range}_{timestamp}.csv"
        elif start_date:
            return f"attendance_{format_type}_from_{start_date.strftime('%Y%m%d')}_{timestamp}.csv"
        elif end_date:
            return f"attendance_{format_type}_until_{end_date.strftime('%Y%m%d')}_{timestamp}.csv"
        else:
            return f"attendance_{format_type}_all_{timestamp}.csv"
    
    def count_records(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        employee_ids: Optional[List[str]] = None,
        device_ids: Optional[List[int]] = None,
        punch_types: Optional[List[int]] = None
    ) -> int:
        """Count total records matching filters"""
        query = self.db.query(func.count(AttendanceRecord.id))
        
        # Apply filters
        if start_date:
            query = query.filter(AttendanceRecord.timestamp >= start_date)
        if end_date:
            end_date_inclusive = end_date + timedelta(days=1)
            query = query.filter(AttendanceRecord.timestamp < end_date_inclusive)
        if employee_ids:
            query = query.filter(AttendanceRecord.employee_id.in_(employee_ids))
        if device_ids:
            query = query.filter(AttendanceRecord.device_id.in_(device_ids))
        if punch_types:
            query = query.filter(AttendanceRecord.punch_type.in_(punch_types))
        
        return query.scalar()
    
    def export_to_csv_streaming(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        employee_ids: Optional[List[str]] = None,
        device_ids: Optional[List[int]] = None,
        punch_types: Optional[List[int]] = None,
        format_type: str = "detailed",
        include_employee_names: bool = True,
        include_device_names: bool = True,
        batch_size: Optional[int] = None,
        max_records: Optional[int] = None
    ) -> Generator[str, None, None]:
        """
        Export attendance records as CSV with streaming support
        Yields CSV data in chunks for memory-efficient large exports
        """
        # Use configured batch size if not provided
        if batch_size is None:
            batch_size = self.BATCH_SIZES.get(format_type, 1000)
        
        # Build base query
        query = self._build_query(
            start_date, end_date, employee_ids, device_ids, punch_types
        )
        
        # Apply max_records limit if specified
        if max_records:
            query = query.limit(max_records)
        
        # Generate CSV based on format
        if format_type == "detailed":
            yield from self._stream_detailed_csv(query, batch_size, include_employee_names, include_device_names)
        elif format_type == "summary":
            yield from self._stream_summary_csv(query, batch_size, include_employee_names)
        elif format_type == "raw":
            yield from self._stream_raw_csv(query, batch_size)
        else:
            raise ValueError(f"Unsupported format type: {format_type}")
    
    def _stream_detailed_csv(
        self, 
        query, 
        batch_size: int,
        include_employee_names: bool,
        include_device_names: bool
    ) -> Generator[str, None, None]:
        """Stream detailed CSV format in batches"""
        # First yield the header
        headers = ['Badge Number', 'Timestamp', 'Punch Type', 'Status', 'Sync Status']
        if include_employee_names:
            headers.insert(1, 'Employee Name (Thai)')
        if include_device_names:
            headers.insert(-3, 'Device Name')
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        yield output.getvalue()
        
        # Stream data in batches
        offset = 0
        while True:
            batch = query.limit(batch_size).offset(offset).all()
            if not batch:
                break
            
            output = StringIO()
            writer = csv.writer(output)
            
            for record in batch:
                row = [record.employee_id]
                
                if include_employee_names:
                    # Get Thai name from unified Employee model
                    thai_name = record.employee.thai_name if record.employee and record.employee.thai_name else record.employee.display_name if record.employee else ''
                    row.append(thai_name)
                
                row.append(record.timestamp.strftime('%Y-%m-%d %H:%M:%S'))
                
                if include_device_names:
                    device_name = record.device.name if record.device else f"Device {record.device_id}"
                    row.append(device_name)
                
                row.extend([
                    self._format_punch_type(record.punch_type),
                    self._format_status(record.status),
                    record.sync_status
                ])
                
                writer.writerow(row)
            
            yield output.getvalue()
            offset += batch_size
            
            # Log progress
            if offset % 10000 == 0:
                logger.info(f"Exported {offset} records")
    
    def _stream_raw_csv(self, query, batch_size: int) -> Generator[str, None, None]:
        """Stream raw CSV format in batches"""
        # Yield header
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'ID', 'Employee ID', 'Device ID', 'Timestamp', 'Punch Type', 
            'Status', 'Created At', 'Sync Status', 'Local ID', 'Created Locally'
        ])
        yield output.getvalue()
        
        # Stream data in batches
        offset = 0
        while True:
            batch = query.limit(batch_size).offset(offset).all()
            if not batch:
                break
            
            output = StringIO()
            writer = csv.writer(output)
            
            for record in batch:
                writer.writerow([
                    record.id,
                    record.employee_id,
                    record.device_id,
                    record.timestamp.strftime('%Y-%m-%d %H:%M:%S') if record.timestamp else '',
                    record.punch_type,
                    record.status,
                    record.created_at.strftime('%Y-%m-%d %H:%M:%S') if record.created_at else '',
                    record.sync_status,
                    record.local_id or '',
                    record.created_locally
                ])
            
            yield output.getvalue()
            offset += batch_size
    
    def _stream_summary_csv(
        self, 
        query, 
        batch_size: int,
        include_employee_names: bool
    ) -> Generator[str, None, None]:
        """Stream summary CSV format by processing in employee batches"""
        # Yield header
        headers = ['Badge Number', 'Date', 'Check In', 'Check Out', 'Work Hours', 'Status']
        if include_employee_names:
            headers.insert(1, 'Employee Name')
        
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        yield output.getvalue()
        
        # Get distinct employees
        employees = self.db.query(AttendanceRecord.employee_id).distinct().all()
        
        # Process employees in batches
        for i in range(0, len(employees), batch_size):
            employee_batch = employees[i:i + batch_size]
            employee_ids = [emp[0] for emp in employee_batch]
            
            # Query records for this batch of employees
            batch_query = query.filter(AttendanceRecord.employee_id.in_(employee_ids))
            
            # Group records by employee and date
            daily_data = {}
            
            for record in batch_query:
                date_key = record.timestamp.date()
                emp_key = record.employee_id
                key = (emp_key, date_key)
                
                if key not in daily_data:
                    # Get Thai name from unified Employee model
                    thai_name = ''
                    if include_employee_names:
                        thai_name = record.employee.thai_name if record.employee and record.employee.thai_name else record.employee.display_name if record.employee else ''
                    
                    daily_data[key] = {
                        'badge_number': emp_key,
                        'employee_name': thai_name,
                        'date': date_key,
                        'check_in': None,
                        'check_out': None,
                        'records': []
                    }
                
                daily_data[key]['records'].append(record)
                
                # Track first check-in and last check-out
                if record.punch_type == 0:  # Check in
                    if daily_data[key]['check_in'] is None or record.timestamp < daily_data[key]['check_in']:
                        daily_data[key]['check_in'] = record.timestamp
                elif record.punch_type == 1:  # Check out
                    if daily_data[key]['check_out'] is None or record.timestamp > daily_data[key]['check_out']:
                        daily_data[key]['check_out'] = record.timestamp
            
            # Write summary rows for this batch
            output = StringIO()
            writer = csv.writer(output)
            
            for (emp_id, date), data in sorted(daily_data.items()):
                row = [data['badge_number']]
                
                if include_employee_names:
                    row.append(data['employee_name'])
                
                row.append(data['date'].strftime('%Y-%m-%d'))
                
                check_in_str = data['check_in'].strftime('%H:%M') if data['check_in'] else ''
                check_out_str = data['check_out'].strftime('%H:%M') if data['check_out'] else ''
                
                # Calculate work hours
                work_hours = ''
                if data['check_in'] and data['check_out']:
                    duration = data['check_out'] - data['check_in']
                    hours = int(duration.total_seconds() // 3600)
                    minutes = int((duration.total_seconds() % 3600) // 60)
                    work_hours = f"{hours}h {minutes}m"
                
                # Determine status
                status = 'Incomplete'
                if data['check_in'] and data['check_out']:
                    status = 'Complete'
                elif data['check_in']:
                    status = 'No Check Out'
                elif data['check_out']:
                    status = 'No Check In'
                
                row.extend([check_in_str, check_out_str, work_hours, status])
                writer.writerow(row)
            
            yield output.getvalue()