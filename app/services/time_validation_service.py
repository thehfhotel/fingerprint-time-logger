"""
Time Validation Service

Handles schedule-based time validation for attendance records with 15-minute rule implementation.
Integrates with role-based schedules (standard schedules vs shift-based schedules).
"""

from datetime import datetime, time, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.models import (
    AttendanceRecord, Employee, JobRole, WorkSchedule, WorkShift,
    ReceptionShiftAssignment, EmployeeMonthlySchedule, TimeCheckConfig
)


class ScheduleInfo:
    """Container for resolved schedule information"""
    def __init__(self, start_time: time, end_time: time, schedule_type: str, 
                 role_name: str, is_working_day: bool = True):
        self.start_time = start_time
        self.end_time = end_time
        self.schedule_type = schedule_type  # 'STANDARD' or 'SHIFT'
        self.role_name = role_name
        self.is_working_day = is_working_day


class ValidationResult:
    """Container for time validation results"""
    def __init__(self, status: str, lateness_minutes: int = 0, early_minutes: int = 0,
                 expected_time: Optional[time] = None, message: str = ""):
        self.status = status  # 'on_time', 'warning', 'late', 'early', 'no_schedule', 'not_working_day'
        self.lateness_minutes = lateness_minutes
        self.early_minutes = early_minutes
        self.expected_time = expected_time
        self.message = message


class TimeValidationService:
    """Service for validating attendance times against employee schedules"""
    
    def __init__(self, db: Session):
        self.db = db
        self._config = None
    
    def get_config(self) -> TimeCheckConfig:
        """Get or create time checking configuration"""
        if self._config is None:
            self._config = self.db.query(TimeCheckConfig).first()
            if not self._config:
                # Create default config if none exists
                self._config = TimeCheckConfig(
                    warning_threshold_minutes=15,
                    late_threshold_minutes=15,
                    early_departure_threshold_minutes=15,
                    auto_validate_on_punch=True,
                    grace_period_enabled=True,
                    overnight_shift_handling=True
                )
                self.db.add(self._config)
                self.db.commit()
        return self._config
    
    def resolve_employee_schedule(self, badge_number: str, target_date: date) -> Optional[ScheduleInfo]:
        """
        Resolve the work schedule for an employee on a specific date.
        
        Business Logic:
        1. Get employee's role assignment
        2. If role has shifts (reception): check daily shift assignment
        3. If role has standard schedule: get role's work schedule
        4. Validate if it's a working day for the employee
        
        Args:
            badge_number: Employee badge number
            target_date: Date to check schedule for
            
        Returns:
            ScheduleInfo object or None if no schedule found
        """
        # Get employee and their role
        employee = self.db.query(Employee).filter(
            Employee.badge_number == badge_number,
            Employee.is_active == True
        ).first()
        
        if not employee or not employee.job_role_id:
            return None
        
        role = self.db.query(JobRole).filter(
            JobRole.id == employee.job_role_id,
            JobRole.is_active == True
        ).first()
        
        if not role:
            return None
        
        # Check if role uses shifts (reception)
        if role.has_shifts:
            return self._resolve_shift_schedule(badge_number, target_date, role)
        else:
            return self._resolve_standard_schedule(badge_number, target_date, role)
    
    def _resolve_shift_schedule(self, badge_number: str, target_date: date, role: JobRole) -> Optional[ScheduleInfo]:
        """Resolve schedule for shift-based roles (reception)"""
        # Check if employee has a shift assignment for this date
        shift_assignment = self.db.query(ReceptionShiftAssignment).filter(
            ReceptionShiftAssignment.employee_badge_number == badge_number,
            ReceptionShiftAssignment.work_date == target_date
        ).first()
        
        if not shift_assignment:
            return ScheduleInfo(
                start_time=time(9, 0), end_time=time(17, 0),
                schedule_type='SHIFT', role_name=role.role_name,
                is_working_day=False
            )
        
        shift = shift_assignment.shift
        if not shift or not shift.is_active:
            return None
        
        # Check if target date's weekday is in shift's working days
        weekday_name = target_date.strftime('%A').lower()
        if weekday_name not in shift.working_days:
            return ScheduleInfo(
                start_time=shift.start_time, end_time=shift.end_time,
                schedule_type='SHIFT', role_name=role.role_name,
                is_working_day=False
            )
        
        return ScheduleInfo(
            start_time=shift.start_time,
            end_time=shift.end_time,
            schedule_type='SHIFT',
            role_name=role.role_name,
            is_working_day=True
        )
    
    def _resolve_standard_schedule(self, badge_number: str, target_date: date, role: JobRole) -> Optional[ScheduleInfo]:
        """Resolve schedule for standard roles (maid, office, maintenance, management)"""
        # Get role's work schedule
        work_schedule = self.db.query(WorkSchedule).filter(
            WorkSchedule.job_role_id == role.id,
            WorkSchedule.is_active == True
        ).first()
        
        if not work_schedule:
            return None
        
        # Check if employee is scheduled to work this month
        monthly_schedule = self.db.query(EmployeeMonthlySchedule).filter(
            EmployeeMonthlySchedule.employee_badge_number == badge_number,
            EmployeeMonthlySchedule.job_role_id == role.id,
            EmployeeMonthlySchedule.year == target_date.year,
            EmployeeMonthlySchedule.month == target_date.month
        ).first()
        
        if not monthly_schedule:
            # No monthly schedule = working all days according to role's working_days
            weekday_name = target_date.strftime('%A').lower()
            is_working_day = weekday_name in work_schedule.working_days
        else:
            # Check if this specific day is in the employee's work days
            is_working_day = target_date.day in monthly_schedule.work_days
        
        return ScheduleInfo(
            start_time=work_schedule.start_time,
            end_time=work_schedule.end_time,
            schedule_type='STANDARD',
            role_name=role.role_name,
            is_working_day=is_working_day
        )
    
    def validate_attendance_time(self, badge_number: str, punch_time: datetime, 
                               punch_type: int) -> ValidationResult:
        """
        Validate attendance time against employee's schedule with 15-minute rule.
        
        Business Logic:
        - Check-in (punch_type=0): Compare against scheduled start time
        - Check-out (punch_type=1): Compare against scheduled end time
        - 15 minutes late = warning status
        - >15 minutes late = late status
        - Early departure handling for check-out
        
        Args:
            badge_number: Employee badge number
            punch_time: Time of the punch
            punch_type: 0=check_in, 1=check_out, etc.
            
        Returns:
            ValidationResult with status and timing details
        """
        config = self.get_config()
        punch_date = punch_time.date()
        punch_time_only = punch_time.time()
        
        # Resolve employee's schedule for this date
        schedule = self.resolve_employee_schedule(badge_number, punch_date)
        
        if not schedule:
            return ValidationResult(
                status='no_schedule',
                message=f"No schedule found for employee {badge_number}"
            )
        
        if not schedule.is_working_day:
            return ValidationResult(
                status='not_working_day',
                message=f"Employee {badge_number} not scheduled to work on {punch_date}"
            )
        
        # Validate based on punch type
        if punch_type == 0:  # Check-in
            return self._validate_check_in(punch_time_only, schedule, config)
        elif punch_type == 1:  # Check-out
            return self._validate_check_out(punch_time_only, schedule, config)
        else:
            # For other punch types (break, overtime), return neutral status
            return ValidationResult(
                status='on_time',
                expected_time=schedule.start_time,
                message=f"Punch type {punch_type} recorded"
            )
    
    def _validate_check_in(self, punch_time: time, schedule: ScheduleInfo, 
                          config: TimeCheckConfig) -> ValidationResult:
        """Validate check-in time against scheduled start time"""
        expected_time = schedule.start_time
        
        # Convert times to minutes for easier calculation
        punch_minutes = punch_time.hour * 60 + punch_time.minute
        expected_minutes = expected_time.hour * 60 + expected_time.minute
        
        # Handle overnight shifts (cross midnight)
        if schedule.schedule_type == 'SHIFT' and expected_time > time(20, 0):
            # For overnight shifts starting after 8 PM, allow punch times in early morning
            if punch_time < time(12, 0):  # Punch time is in early morning
                punch_minutes += 24 * 60  # Add 24 hours
        
        lateness_minutes = punch_minutes - expected_minutes
        
        if lateness_minutes <= 0:
            # On time or early
            return ValidationResult(
                status='on_time',
                lateness_minutes=0,
                expected_time=expected_time,
                message=f"On time check-in (expected: {expected_time.strftime('%H:%M')})"
            )
        elif lateness_minutes <= config.warning_threshold_minutes:
            # Within warning threshold (≤15 minutes)
            return ValidationResult(
                status='warning',
                lateness_minutes=lateness_minutes,
                expected_time=expected_time,
                message=f"{lateness_minutes} min late - within grace period"
            )
        else:
            # Late (>15 minutes)
            return ValidationResult(
                status='late',
                lateness_minutes=lateness_minutes,
                expected_time=expected_time,
                message=f"{lateness_minutes} min late"
            )
    
    def _validate_check_out(self, punch_time: time, schedule: ScheduleInfo, 
                           config: TimeCheckConfig) -> ValidationResult:
        """Validate check-out time against scheduled end time"""
        expected_time = schedule.end_time
        
        # Convert times to minutes for easier calculation
        punch_minutes = punch_time.hour * 60 + punch_time.minute
        expected_minutes = expected_time.hour * 60 + expected_time.minute
        
        # Handle overnight shifts (cross midnight)
        if schedule.schedule_type == 'SHIFT' and expected_time < time(12, 0):
            # For overnight shifts ending before noon, adjust punch time if it's in evening
            if punch_time > time(12, 0):  # Punch time is in evening/night
                punch_minutes -= 24 * 60  # Subtract 24 hours
        
        early_minutes = expected_minutes - punch_minutes
        
        if early_minutes <= 0:
            # On time or late checkout (normal)
            return ValidationResult(
                status='on_time',
                early_minutes=0,
                expected_time=expected_time,
                message=f"Normal check-out (expected: {expected_time.strftime('%H:%M')})"
            )
        elif early_minutes <= config.early_departure_threshold_minutes:
            # Slightly early but within threshold
            return ValidationResult(
                status='on_time',
                early_minutes=early_minutes,
                expected_time=expected_time,
                message=f"{early_minutes} min early - acceptable"
            )
        else:
            # Too early departure
            return ValidationResult(
                status='early',
                early_minutes=early_minutes,
                expected_time=expected_time,
                message=f"{early_minutes} min early departure"
            )
    
    def validate_and_update_attendance_record(self, attendance_record: AttendanceRecord) -> ValidationResult:
        """
        Validate an attendance record and update it with validation results.
        
        Args:
            attendance_record: AttendanceRecord to validate and update
            
        Returns:
            ValidationResult with validation details
        """
        if not attendance_record.employee_id:
            return ValidationResult(status='no_employee', message="No employee ID found")
        
        # Perform validation
        result = self.validate_attendance_time(
            badge_number=attendance_record.employee_id,
            punch_time=attendance_record.timestamp,
            punch_type=attendance_record.punch_type
        )
        
        # Update attendance record with validation results
        attendance_record.validation_status = result.status
        attendance_record.lateness_minutes = result.lateness_minutes
        attendance_record.early_minutes = result.early_minutes
        attendance_record.expected_time = result.expected_time
        attendance_record.validation_message = result.message
        attendance_record.validated_at = datetime.now()
        
        # Determine schedule type from resolved schedule
        if result.expected_time:
            schedule = self.resolve_employee_schedule(
                attendance_record.employee_id, 
                attendance_record.timestamp.date()
            )
            if schedule:
                attendance_record.schedule_type = schedule.schedule_type
        
        return result
    
    def bulk_validate_attendance_records(self, start_date: date, end_date: date, 
                                       badge_numbers: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Bulk validate attendance records for a date range.
        
        Args:
            start_date: Start date for validation
            end_date: End date for validation
            badge_numbers: Optional list of specific badge numbers to validate
            
        Returns:
            Dictionary with validation summary and results
        """
        # Build query for attendance records
        query = self.db.query(AttendanceRecord).filter(
            AttendanceRecord.timestamp >= datetime.combine(start_date, time.min),
            AttendanceRecord.timestamp <= datetime.combine(end_date, time.max)
        )
        
        if badge_numbers:
            query = query.filter(AttendanceRecord.employee_id.in_(badge_numbers))
        
        records = query.all()
        
        validation_results = {
            'total_records': len(records),
            'validated_records': 0,
            'on_time': 0,
            'warnings': 0,
            'late': 0,
            'early': 0,
            'no_schedule': 0,
            'errors': []
        }
        
        for record in records:
            try:
                result = self.validate_and_update_attendance_record(record)
                validation_results['validated_records'] += 1
                
                # Count by status
                if result.status in validation_results:
                    validation_results[result.status] += 1
                
            except Exception as e:
                validation_results['errors'].append({
                    'record_id': record.id,
                    'employee_id': record.employee_id,
                    'error': str(e)
                })
        
        # Commit all updates
        self.db.commit()
        
        return validation_results
    
    def get_late_employees_report(self, target_date: date) -> List[Dict[str, Any]]:
        """
        Generate a report of late employees for a specific date.
        
        Args:
            target_date: Date to generate report for
            
        Returns:
            List of dictionaries with late employee details
        """
        # Get attendance records for the target date with late or warning status
        start_datetime = datetime.combine(target_date, time.min)
        end_datetime = datetime.combine(target_date, time.max)
        
        late_records = self.db.query(AttendanceRecord).filter(
            AttendanceRecord.timestamp >= start_datetime,
            AttendanceRecord.timestamp <= end_datetime,
            AttendanceRecord.punch_type == 0,  # Check-in only
            AttendanceRecord.validation_status.in_(['warning', 'late'])
        ).all()
        
        report_data = []
        
        for record in late_records:
            # Get employee details
            employee = self.db.query(Employee).filter(
                Employee.badge_number == record.employee_id,
                Employee.is_active == True
            ).first()
            
            if not employee:
                continue
            
            # Get role information
            role_name = "Unknown"
            if employee.job_role:
                role_name = employee.job_role.display_name
            
            report_data.append({
                'badge_number': record.employee_id,
                'thai_name': employee.thai_name,
                'role_name': role_name,
                'expected_time': record.expected_time.strftime('%H:%M') if record.expected_time else 'N/A',
                'actual_time': record.timestamp.strftime('%H:%M'),
                'lateness_minutes': record.lateness_minutes or 0,
                'status': record.validation_status,
                'message': record.validation_message,
                'timestamp': record.timestamp
            })
        
        # Sort by lateness (most late first)
        report_data.sort(key=lambda x: x['lateness_minutes'], reverse=True)
        
        return report_data