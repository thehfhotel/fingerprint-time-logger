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
# SyncLogBase schema removed - not used by application

# SyncLog schema removed - not used by application

# Additional request/response schemas
# SyncRequest schema removed - not used by application

# SyncResponse schema removed - not used by application

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
# JobRoleWithSchedule schema removed - not used by application

# Employee Role Assignment Schemas
# EmployeeRoleAssignmentResponse schema removed - not used by application

class EmployeeRoleAssignmentUpdate(BaseModel):
    job_role_id: Optional[int] = None


class RoleAssignment(BaseModel):
    badge_number: str
    job_role_id: Optional[int] = None


# BulkRoleAssignmentRequest schema removed - not used by application

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
# TimeCheckConfigBase schema removed - not used by application

# TimeCheckConfigUpdate schema removed - not used by application

# TimeCheckConfigResponse schema removed - not used by application

# Attendance Validation Schemas
# AttendanceValidationResponse schema removed - not used by application


# BulkValidationRequest schema removed - not used by application


# BulkValidationResponse schema removed - not used by application

# Late Employee Report Schemas
# LateEmployeeInfo schema removed - not used by application

# LateEmployeeReportResponse schema removed - not used by application

# Punctuality Report Schemas
# DailyPunctualityStats schema removed - not used by application

# PunctualitySummary schema removed - not used by application

# PunctualityReportResponse schema removed - not used by application

# Employee Schedule Info Schema
# EmployeeScheduleInfo schema removed - not used by application

# ============================================================================
# CALENDAR & ATTENDANCE SCHEMAS (consolidated from attendance_calendar_schemas.py)
# ============================================================================

# AttendanceStatusEnum enum removed - not used by application

# HolidayTypeEnum enum removed - not used by application

# CalendarFilters schema removed - not used by application

# CalendarConfigResponse schema removed - not used by application

# HolidayResponse schema removed - not used by application

# CalendarStatisticsResponse schema removed - not used by application

# EmployeeDayDetailResponse schema removed - not used by application

# MonthlyCalendarResponse schema removed - not used by application

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