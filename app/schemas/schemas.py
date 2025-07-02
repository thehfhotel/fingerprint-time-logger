from datetime import datetime, time, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from enum import Enum


# Device schemas
class DeviceBase(BaseModel):
    name: str
    ip_address: str
    port: int = 4370
    password: int = 0
    is_active: bool = True


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip_address: Optional[str] = None
    port: Optional[int] = None
    password: Optional[int] = None
    is_active: Optional[bool] = None


class Device(DeviceBase):
    id: int
    last_sync: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Employee schemas (unified model)
class EmployeeBase(BaseModel):
    badge_number: str
    english_name: Optional[str] = None
    thai_name: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    job_role_id: Optional[int] = None
    is_active: bool = True
    is_hidden: bool = False


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    english_name: Optional[str] = None
    thai_name: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    job_role_id: Optional[int] = None
    is_active: Optional[bool] = None
    is_hidden: Optional[bool] = None


class Employee(EmployeeBase):
    id: int
    display_name: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Attendance Record schemas
class AttendanceRecordBase(BaseModel):
    employee_badge_number: str
    device_id: int
    timestamp: datetime
    punch_type: int  # 0=check_in, 1=check_out, 2=break_out, 3=break_in, 4=ot_in, 5=ot_out
    status: int = 0  # 0=normal, 1=late, 2=early


class AttendanceRecordCreate(AttendanceRecordBase):
    pass


class AttendanceRecordUpdate(BaseModel):
    punch_type: Optional[int] = None
    status: Optional[int] = None


class AttendanceRecord(AttendanceRecordBase):
    id: int
    created_at: datetime
    employee: Optional[Employee] = None
    device: Optional[Device] = None

    class Config:
        from_attributes = True


# Sync Log schemas
class SyncLogBase(BaseModel):
    device_id: int
    sync_type: str  # 'employees', 'attendance', 'full'
    status: str  # 'success', 'failed', 'partial'
    records_synced: int = 0
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class SyncLog(SyncLogBase):
    id: int
    device: Optional[Device] = None

    class Config:
        from_attributes = True


# Additional request/response schemas
class SyncRequest(BaseModel):
    device_id: int
    sync_type: str = "full"  # 'employees', 'attendance', 'full'


class SyncResponse(BaseModel):
    message: str
    sync_log_id: Optional[int] = None
    records_synced: Optional[int] = None


class AttendanceFilter(BaseModel):
    employee_id: Optional[str] = None
    device_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    punch_type: Optional[int] = None


# Work Schedule Management Schemas

class JobRoleBase(BaseModel):
    role_name: str
    display_name: str
    description: Optional[str] = None
    has_shifts: bool = False
    is_active: bool = True


class JobRoleCreate(JobRoleBase):
    pass


class JobRoleUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    has_shifts: Optional[bool] = None
    is_active: Optional[bool] = None


class JobRole(JobRoleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkScheduleBase(BaseModel):
    start_time: time
    end_time: time
    working_days: List[str] = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    break_duration_minutes: int = 60
    is_active: bool = True


class WorkScheduleCreate(WorkScheduleBase):
    job_role_id: int


class WorkScheduleUpdate(BaseModel):
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    working_days: Optional[List[str]] = None
    break_duration_minutes: Optional[int] = None
    is_active: Optional[bool] = None


class WorkSchedule(WorkScheduleBase):
    id: int
    job_role_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkShiftBase(BaseModel):
    shift_name: str
    start_time: time
    end_time: time
    color: str = '#6c757d'  # Hex color for visual identification
    working_days: List[str] = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    break_duration_minutes: int = 30
    sort_order: int = 0
    is_active: bool = True


class WorkShiftCreate(WorkShiftBase):
    job_role_id: int


class WorkShiftUpdate(BaseModel):
    shift_name: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    color: Optional[str] = None  # Hex color for visual identification
    working_days: Optional[List[str]] = None
    break_duration_minutes: Optional[int] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class WorkShift(WorkShiftBase):
    id: int
    job_role_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Combined response schemas for job roles with their schedules/shifts
class JobRoleWithSchedule(JobRole):
    work_schedule: Optional[WorkSchedule] = None
    work_shifts: List[WorkShift] = []


# Employee Role Assignment Schemas
class EmployeeRoleAssignmentResponse(BaseModel):
    badge_number: str
    thai_name: str
    job_role_id: Optional[int] = None
    role_name: Optional[str] = None
    role_display_name: Optional[str] = None
    is_active: bool
    is_hidden: bool

    class Config:
        from_attributes = True


class EmployeeRoleAssignmentUpdate(BaseModel):
    job_role_id: Optional[int] = None


class RoleAssignment(BaseModel):
    badge_number: str
    job_role_id: Optional[int] = None


class BulkRoleAssignmentRequest(BaseModel):
    assignments: List[RoleAssignment]


class BulkRoleAssignmentResponse(BaseModel):
    total_requested: int
    successful_assignments: int
    failed_assignments: int
    successful: List[Dict[str, Any]]
    failed: List[Dict[str, Any]]


# Job Role Response Schema (includes employee count)
class JobRoleResponse(JobRole):
    employee_count: Optional[int] = None


# Time Checking Schemas
class TimeCheckConfigBase(BaseModel):
    warning_threshold_minutes: int = 15
    late_threshold_minutes: int = 15
    early_departure_threshold_minutes: int = 15
    auto_validate_on_punch: bool = True
    grace_period_enabled: bool = True
    overnight_shift_handling: bool = True


class TimeCheckConfigUpdate(BaseModel):
    warning_threshold_minutes: Optional[int] = None
    late_threshold_minutes: Optional[int] = None
    early_departure_threshold_minutes: Optional[int] = None
    auto_validate_on_punch: Optional[bool] = None
    grace_period_enabled: Optional[bool] = None
    overnight_shift_handling: Optional[bool] = None


class TimeCheckConfigResponse(TimeCheckConfigBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Attendance Validation Schemas
class AttendanceValidationResponse(BaseModel):
    record_id: int
    employee_id: str
    timestamp: datetime
    punch_type: int
    validation_status: str
    lateness_minutes: Optional[int] = None
    early_minutes: Optional[int] = None
    expected_time: Optional[time] = None
    message: str
    validated_at: Optional[datetime] = None


class BulkValidationRequest(BaseModel):
    start_date: date
    end_date: date
    badge_numbers: Optional[List[str]] = None


class BulkValidationResponse(BaseModel):
    total_records: int
    validated_records: int
    on_time: int
    warnings: int
    late: int
    early: int
    no_schedule: int
    errors: List[Dict[str, Any]]


# Late Employee Report Schemas
class LateEmployeeInfo(BaseModel):
    badge_number: str
    thai_name: str
    role_name: str
    expected_time: str
    actual_time: str
    lateness_minutes: int
    status: str
    message: str
    timestamp: datetime


class LateEmployeeReportResponse(BaseModel):
    report_date: date
    total_employees: int
    total_late: int
    total_warnings: int
    average_lateness_minutes: float
    employees: List[LateEmployeeInfo]


# Punctuality Report Schemas
class DailyPunctualityStats(BaseModel):
    date: date
    on_time: int
    warning: int
    late: int
    total: int


class PunctualitySummary(BaseModel):
    total_check_ins: int
    on_time: int
    warnings: int
    late: int
    on_time_percentage: float
    warning_percentage: float
    late_percentage: float
    average_lateness_minutes: float


class PunctualityReportResponse(BaseModel):
    start_date: date
    end_date: date
    badge_number: Optional[str] = None
    summary: PunctualitySummary
    daily_breakdown: List[DailyPunctualityStats]


# Employee Schedule Info Schema
class EmployeeScheduleInfo(BaseModel):
    badge_number: str
    date: date
    start_time: time
    end_time: time
    schedule_type: str  # 'STANDARD' or 'SHIFT'
    role_name: str
    is_working_day: bool


# ============================================================================
# CALENDAR & ATTENDANCE SCHEMAS (consolidated from attendance_calendar_schemas.py)
# ============================================================================

class AttendanceStatusEnum(str, Enum):
    """Attendance status for API responses"""
    PERFECT = "perfect"
    MINOR_ISSUE = "minor_issue"
    MAJOR_VIOLATION = "violation"
    ABSENT = "absent"
    NON_WORKING_DAY = "non_working"
    PARTIAL = "partial"


class HolidayTypeEnum(str, Enum):
    """Holiday types"""
    NATIONAL = "national"
    COMPANY = "company"
    RELIGIOUS = "religious"
    PERSONAL = "personal"


class CalendarFilters(BaseModel):
    """Filters for calendar data requests"""
    role: Optional[str] = None
    department: Optional[str] = None
    employee_ids: Optional[List[str]] = None
    include_inactive: Optional[bool] = False


class CalendarConfigResponse(BaseModel):
    """Calendar configuration and metadata"""
    violation_threshold_minutes: int = 15
    minor_issue_threshold_minutes: int = 1
    weekend_days: List[int] = [6, 0]  # Saturday, Sunday
    status_colors: Dict[str, str]
    status_symbols: Optional[Dict[str, str]] = None
    roles: List[str] = []
    months: List[Dict[str, Any]] = []


class HolidayResponse(BaseModel):
    """Holiday information"""
    id: int
    date: str
    name: str
    holiday_type: HolidayTypeEnum
    applies_to_all: bool = True
    applicable_roles: Optional[List[str]] = None


class CalendarStatisticsResponse(BaseModel):
    """Monthly calendar statistics"""
    total_employees: int
    total_working_days: int
    perfect_attendance_rate: float
    punctuality_rate: float
    average_late_minutes: float
    violation_count: int
    absent_count: int


class EmployeeDayDetailResponse(BaseModel):
    """Detailed attendance for specific employee and day"""
    employee_id: str
    employee_name: str
    date: str
    status: AttendanceStatusEnum
    
    # Time information
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    scheduled_start: Optional[time] = None
    scheduled_end: Optional[time] = None
    
    # Calculations
    late_minutes: int = 0
    early_departure_minutes: int = 0
    work_hours: Optional[float] = None
    
    # Context
    is_weekend: bool = False
    is_holiday: bool = False
    holiday_name: Optional[str] = None
    job_role: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
            time: lambda v: v.strftime("%H:%M:%S") if v else None
        }


class MonthlyCalendarResponse(BaseModel):
    """Complete monthly calendar response"""
    year: int
    month: int
    month_name: str
    days_in_month: int
    employees: List[Dict[str, Any]]  # Simplified to avoid circular imports
    holidays: List[int] = []
    weekends: List[int] = []
    working_days: List[int] = []
    statistics: CalendarStatisticsResponse


# ============================================================================
# GENERIC RESPONSE SCHEMAS
# ============================================================================

class SuccessResponse(BaseModel):
    """Standard success response"""
    success: bool = True
    message: str
    data: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """Standard error response"""
    success: bool = False
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None