from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Float, JSON, Time, Date, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from enum import Enum


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    ip_address = Column(String(15), nullable=False)
    port = Column(Integer, default=4370)
    password = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    last_sync = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    attendance_records = relationship("AttendanceRecord", back_populates="device")
    sync_logs = relationship("SyncLog", back_populates="device")
    status_logs = relationship("DeviceStatusLog", back_populates="device")
    error_events = relationship("ErrorEvent", back_populates="device")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    badge_number = Column(String(50), unique=True, nullable=False, index=True)  # Unified identifier
    
    # Names (consolidated from both models)
    english_name = Column(String(100), nullable=True)      # From original Employee.name
    thai_name = Column(String(100), nullable=True)         # From EmployeeThaiName.thai_name
    display_name = Column(String(100), nullable=False)     # Computed: thai_name or f"พนักงาน {badge_number}"
    
    # Organization data
    department = Column(String(100), nullable=True)        # From original Employee
    position = Column(String(100), nullable=True)          # From original Employee
    job_role_id = Column(Integer, ForeignKey("job_roles.id"), nullable=True)  # From EmployeeThaiName
    
    # Status and visibility
    is_active = Column(Boolean, nullable=False, default=True)              # Merged from both models
    is_hidden = Column(Boolean, nullable=False, default=False)             # From EmployeeThaiName (UI control)
    
    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    attendance_records = relationship("AttendanceRecord", back_populates="employee")
    job_role = relationship("JobRole", back_populates="employees")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, index=True)
    employee_badge_number = Column(String(50), ForeignKey("employees.badge_number"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    punch_type = Column(Integer, nullable=False)  # 0=check_in, 1=check_out, 2=break_out, 3=break_in, 4=ot_in, 5=ot_out
    status = Column(Integer, default=0)  # 0=normal, 1=late, 2=early
    created_at = Column(DateTime, default=func.now())
    
    # Offline-first enhancements
    sync_status = Column(String(20), nullable=False, default='synced')  # 'synced', 'pending', 'failed'
    local_id = Column(String(36), nullable=True)  # UUID for local tracking
    created_locally = Column(Boolean, default=False)  # True if created offline
    
    # Time checking fields
    validation_status = Column(String(20), default='unvalidated')  # 'on_time', 'warning', 'late', 'early', etc.
    lateness_minutes = Column(Integer, nullable=True)  # Minutes late for check-in
    early_minutes = Column(Integer, nullable=True)  # Minutes early for check-out
    expected_time = Column(Time, nullable=True)  # Expected time from schedule
    schedule_type = Column(String(20), nullable=True)  # 'STANDARD' or 'SHIFT'
    validation_message = Column(Text, nullable=True)  # Human-readable validation message
    validated_at = Column(DateTime, nullable=True)  # When validation was performed

    employee = relationship("Employee", back_populates="attendance_records")
    device = relationship("Device", back_populates="attendance_records")




class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    sync_type = Column(String(50), nullable=False)  # 'employees', 'attendance', 'full'
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'partial'
    records_synced = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="sync_logs")


class SyncQueue(Base):
    """Queue for background sync operations - offline-first enhancement"""
    __tablename__ = "sync_queue"

    id = Column(Integer, primary_key=True, index=True)
    operation_type = Column(String(20), nullable=False)  # 'sync_attendance', 'sync_users', etc.
    target_table = Column(String(50), nullable=False)
    record_id = Column(String(100), nullable=True)
    payload = Column(Text, nullable=True)  # JSON data stored as text
    status = Column(String(20), nullable=False, default='pending')  # 'pending', 'processing', 'completed', 'failed'
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    scheduled_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)


class DeviceStatusLog(Base):
    """Log of device connectivity status - offline-first enhancement"""
    __tablename__ = "device_status_log"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    status = Column(String(20), nullable=False)  # 'online', 'offline', 'error'
    last_successful_sync = Column(DateTime, nullable=True)
    last_attempt = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    device_metadata = Column(Text, nullable=True)  # JSON metadata stored as text
    created_at = Column(DateTime, default=func.now())

    device = relationship("Device", back_populates="status_logs")


class DataCache(Base):
    """Cache for offline data storage - offline-first enhancement"""
    __tablename__ = "data_cache"

    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String(100), unique=True, nullable=False, index=True)
    cache_data = Column(Text, nullable=False)  # JSON data stored as text
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class ErrorEvent(Base):
    """Track detailed error events for pattern analysis"""
    __tablename__ = "error_events"
    
    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    operation_type = Column(String(50), nullable=False)  # sync_attendance, health_check, etc.
    
    # Error classification
    severity = Column(Integer, nullable=False)  # ErrorSeverity value (1-5)
    category = Column(String(50), nullable=False)  # ErrorCategory value
    error_message = Column(Text, nullable=False)
    context_data = Column(JSON, nullable=True)  # Additional context as JSON
    
    # Timing and recovery
    timestamp = Column(DateTime, default=func.now())
    resolved_at = Column(DateTime, nullable=True)
    recovery_duration = Column(Float, nullable=True)  # seconds to recover
    
    # Impact tracking
    should_count_as_failure = Column(Boolean, default=True)
    user_visible = Column(Boolean, default=True)
    suggested_recovery_time = Column(Integer, default=60)  # seconds
    
    # Pattern analysis
    consecutive_count = Column(Integer, default=1)  # How many in a row
    pattern_hash = Column(String(32), nullable=True)  # For grouping similar errors
    
    # Relationships
    device = relationship("Device", back_populates="error_events")
    
    def to_dict(self):
        return {
            "id": self.id,
            "device_id": self.device_id,
            "operation_type": self.operation_type,
            "severity": self.severity,
            "category": self.category,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "recovery_duration": self.recovery_duration,
            "consecutive_count": self.consecutive_count
        }


# Work Schedule Management Models - Added for schedule management feature

class JobRole(Base):
    """Job roles for employees with work schedule configuration"""
    __tablename__ = "job_roles"

    id = Column(Integer, primary_key=True, index=True)
    role_name = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    has_shifts = Column(Boolean, default=False)  # True for reception (shift-based), False for others
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    work_schedules = relationship("WorkSchedule", back_populates="job_role")
    work_shifts = relationship("WorkShift", back_populates="job_role")
    employees = relationship("Employee", back_populates="job_role")  # Role assignments


class WorkSchedule(Base):
    """Work schedule for job roles that don't use shifts (maid, office, maintenance, management)"""
    __tablename__ = "work_schedules"

    id = Column(Integer, primary_key=True, index=True)
    job_role_id = Column(Integer, ForeignKey("job_roles.id"), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    working_days = Column(JSON, default=["monday", "tuesday", "wednesday", "thursday", "friday"])
    break_duration_minutes = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    job_role = relationship("JobRole", back_populates="work_schedules")


class WorkShift(Base):
    """Work shifts for reception role (4 different shifts)"""
    __tablename__ = "work_shifts"

    id = Column(Integer, primary_key=True, index=True)
    job_role_id = Column(Integer, ForeignKey("job_roles.id"), nullable=False)
    shift_name = Column(String(100), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    color = Column(String(7), default='#6c757d', nullable=False)  # Hex color for visual identification
    working_days = Column(JSON, default=["monday", "tuesday", "wednesday", "thursday", "friday"])
    break_duration_minutes = Column(Integer, default=30)
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    is_overnight = Column(Boolean, default=False)  # For shifts that cross midnight
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    job_role = relationship("JobRole", back_populates="work_shifts")


class EmployeeMonthlySchedule(Base):
    """Monthly work schedule for employees in standard roles (non-reception)"""
    __tablename__ = "employee_monthly_schedules"

    id = Column(Integer, primary_key=True, index=True)
    employee_badge_number = Column(String(50), nullable=False, index=True)
    job_role_id = Column(Integer, ForeignKey("job_roles.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    work_days = Column(JSON, default=[])  # Array of day numbers [1,2,3,5,8...]
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    job_role = relationship("JobRole")

    __table_args__ = (
        UniqueConstraint('employee_badge_number', 'job_role_id', 'year', 'month'),
    )




class ReceptionShiftAssignment(Base):
    """Daily shift assignments for reception employees"""
    __tablename__ = "reception_shift_assignments"

    id = Column(Integer, primary_key=True, index=True)
    employee_badge_number = Column(String(50), nullable=False, index=True)
    work_date = Column(Date, nullable=False)
    shift_id = Column(Integer, ForeignKey("work_shifts.id"), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    shift = relationship("WorkShift")

    __table_args__ = (
        UniqueConstraint('employee_badge_number', 'work_date'),
    )


class TimeCheckConfig(Base):
    """Configuration for time checking functionality"""
    __tablename__ = "time_check_config"

    id = Column(Integer, primary_key=True, index=True)
    warning_threshold_minutes = Column(Integer, default=15, nullable=False)
    late_threshold_minutes = Column(Integer, default=15, nullable=False)
    early_departure_threshold_minutes = Column(Integer, default=15, nullable=False)
    auto_validate_on_punch = Column(Boolean, default=True, nullable=False)
    grace_period_enabled = Column(Boolean, default=True, nullable=False)
    overnight_shift_handling = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class DailyAttendanceSummary(Base):
    """Pre-calculated daily attendance summaries for reporting"""
    __tablename__ = "daily_attendance_summary"

    id = Column(Integer, primary_key=True, index=True)
    employee_badge_number = Column(String(50), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    role_name = Column(String(50), nullable=True)
    scheduled_start_time = Column(Time, nullable=True)
    scheduled_end_time = Column(Time, nullable=True)
    actual_check_in_time = Column(Time, nullable=True)
    actual_check_out_time = Column(Time, nullable=True)
    check_in_status = Column(String(20), nullable=True)  # on_time, warning, late, etc.
    check_out_status = Column(String(20), nullable=True)
    total_lateness_minutes = Column(Integer, default=0)
    total_early_minutes = Column(Integer, default=0)
    is_absent = Column(Boolean, default=False)
    has_incomplete_punches = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('employee_badge_number', 'date'),
    )


# Attendance Calendar Models

class AttendanceStatus(str, Enum):
    """Attendance status for calendar display"""
    PERFECT = "perfect"           # Green - On time check-in and check-out
    MINOR_ISSUE = "minor_issue"   # Yellow - Late check-in OR early check-out (≤15 min)
    MAJOR_VIOLATION = "violation" # Red - >15 min late OR >15 min early departure
    ABSENT = "absent"             # Gray - No attendance record
    NON_WORKING_DAY = "non_working" # Blue - Weekend/Holiday
    PARTIAL = "partial"           # Orange - Only check-in OR only check-out


class HolidayType(str, Enum):
    """Types of holidays"""
    NATIONAL = "national"
    COMPANY = "company"
    RELIGIOUS = "religious"
    PERSONAL = "personal"


class Holiday(Base):
    """Holiday calendar for attendance calculation"""
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    holiday_type = Column(SQLEnum(HolidayType), default=HolidayType.COMPANY)
    is_active = Column(Boolean, default=True)
    applies_to_all = Column(Boolean, default=True)  # If false, specific to certain roles
    applicable_roles = Column(JSON, nullable=True)  # List of role IDs if not applies_to_all
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('date', 'name'),
    )


class MonthlyAttendanceStats(Base):
    """Pre-calculated monthly statistics for performance"""
    __tablename__ = "monthly_attendance_stats"

    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    
    # Overall statistics
    total_employees = Column(Integer, default=0)
    total_working_days = Column(Integer, default=0)
    
    # Status counts
    perfect_count = Column(Integer, default=0)
    minor_issue_count = Column(Integer, default=0)
    violation_count = Column(Integer, default=0)
    absent_count = Column(Integer, default=0)
    
    # Percentages
    perfect_attendance_rate = Column(Float, default=0.0)
    punctuality_rate = Column(Float, default=0.0)
    
    # Time statistics
    average_late_minutes = Column(Float, default=0.0)
    average_early_departure_minutes = Column(Float, default=0.0)
    average_work_hours = Column(Float, default=0.0)
    
    # Role-based statistics
    role_statistics = Column(JSON, nullable=True)  # Statistics broken down by role
    
    # Metadata
    last_calculated = Column(DateTime, default=func.now())
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('year', 'month'),
    )