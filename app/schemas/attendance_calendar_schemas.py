"""
Pydantic schemas for Attendance Calendar API endpoints
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date, time
from datetime import date as DateType
from enum import Enum


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


# Request schemas

class CalendarFilters(BaseModel):
    """Filters for calendar data requests"""
    role: Optional[str] = Field(None, description="Filter by job role")
    department: Optional[str] = Field(None, description="Filter by department")
    employee_ids: Optional[List[str]] = Field(None, description="Specific employee IDs to include")
    include_inactive: Optional[bool] = Field(False, description="Include inactive employees")
    
    @validator('employee_ids', pre=True)
    def parse_employee_ids(cls, v):
        if isinstance(v, str):
            return [id.strip() for id in v.split(',') if id.strip()]
        return v


class ExportRequest(BaseModel):
    """Export calendar data request"""
    format: str = Field("csv", description="Export format: csv, xlsx, pdf")
    include_details: bool = Field(True, description="Include check-in/out times")
    include_statistics: bool = Field(True, description="Include summary statistics")
    date_range: Optional[str] = Field(None, description="Custom date range if different from month")


# Response schemas

class DailyAttendanceResponse(BaseModel):
    """Single day attendance data"""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    status: AttendanceStatusEnum = Field(..., description="Attendance status")
    check_in: Optional[datetime] = Field(None, description="Check-in timestamp")
    check_out: Optional[datetime] = Field(None, description="Check-out timestamp")
    scheduled_start: Optional[time] = Field(None, description="Scheduled start time")
    scheduled_end: Optional[time] = Field(None, description="Scheduled end time")
    late_minutes: int = Field(0, description="Minutes late for check-in")
    early_departure_minutes: int = Field(0, description="Minutes early for check-out")
    work_hours: Optional[float] = Field(None, description="Total work hours")
    is_weekend: bool = Field(False, description="Whether date is a weekend")
    is_holiday: bool = Field(False, description="Whether date is a holiday")
    holiday_name: Optional[str] = Field(None, description="Holiday name if applicable")
    notes: Optional[str] = Field(None, description="Additional notes")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
            time: lambda v: v.strftime("%H:%M:%S") if v else None
        }


class EmployeeCalendarResponse(BaseModel):
    """Employee calendar data for a month"""
    id: str = Field(..., description="Employee badge number")
    name: str = Field(..., description="Employee Thai name")
    role: Optional[str] = Field(None, description="Job role name")
    daily_attendance: Dict[str, DailyAttendanceResponse] = Field(
        ..., 
        description="Daily attendance data keyed by day number"
    )


class RoleStatistics(BaseModel):
    """Statistics for a specific role"""
    role_name: str = Field(..., description="Role name")
    employee_count: int = Field(..., description="Number of employees in role")
    perfect_count: int = Field(0, description="Perfect attendance count")
    minor_issue_count: int = Field(0, description="Minor issue count")
    violation_count: int = Field(0, description="Major violation count")
    absent_count: int = Field(0, description="Absent count")
    punctuality_rate: float = Field(0.0, description="Punctuality rate percentage")


class CalendarStatisticsResponse(BaseModel):
    """Monthly calendar statistics"""
    total_employees: int = Field(..., description="Total number of employees")
    total_working_days: int = Field(..., description="Total working days in month")
    perfect_attendance_rate: float = Field(..., description="Perfect attendance rate percentage")
    punctuality_rate: float = Field(..., description="Overall punctuality rate percentage")
    average_late_minutes: float = Field(..., description="Average lateness in minutes")
    violation_count: int = Field(..., description="Total major violations")
    absent_count: int = Field(..., description="Total absences")
    role_breakdown: List[RoleStatistics] = Field([], description="Statistics by role")


class HolidayResponse(BaseModel):
    """Holiday information"""
    id: int = Field(..., description="Holiday ID")
    date: str = Field(..., description="Holiday date")
    name: str = Field(..., description="Holiday name")
    holiday_type: HolidayTypeEnum = Field(..., description="Type of holiday")
    applies_to_all: bool = Field(True, description="Whether applies to all employees")
    applicable_roles: Optional[List[str]] = Field(None, description="Applicable roles if not all")


class MonthlyCalendarResponse(BaseModel):
    """Complete monthly calendar response"""
    year: int = Field(..., description="Calendar year")
    month: int = Field(..., description="Calendar month (1-12)")
    month_name: str = Field(..., description="Month name in English")
    days_in_month: int = Field(..., description="Number of days in the month")
    employees: List[EmployeeCalendarResponse] = Field(..., description="Employee attendance data")
    holidays: List[int] = Field([], description="Holiday day numbers")
    weekends: List[int] = Field([], description="Weekend day numbers")
    working_days: List[int] = Field([], description="Working day numbers")
    statistics: CalendarStatisticsResponse = Field(..., description="Monthly statistics")
    
    @validator('month')
    def validate_month(cls, v):
        if not 1 <= v <= 12:
            raise ValueError('Month must be between 1 and 12')
        return v


class EmployeeDayDetailResponse(BaseModel):
    """Detailed attendance for specific employee and day"""
    employee_id: str = Field(..., description="Employee badge number")
    employee_name: str = Field(..., description="Employee Thai name")
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    status: AttendanceStatusEnum = Field(..., description="Attendance status")
    
    # Detailed time information
    check_in: Optional[datetime] = Field(None, description="Check-in timestamp")
    check_out: Optional[datetime] = Field(None, description="Check-out timestamp")
    scheduled_start: Optional[time] = Field(None, description="Scheduled start time")
    scheduled_end: Optional[time] = Field(None, description="Scheduled end time")
    
    # Calculations
    late_minutes: int = Field(0, description="Minutes late")
    early_departure_minutes: int = Field(0, description="Minutes early departure")
    work_hours: Optional[float] = Field(None, description="Total work hours")
    break_duration: int = Field(0, description="Break duration in minutes")
    overtime_hours: Optional[float] = Field(None, description="Overtime hours")
    
    # Context information
    is_weekend: bool = Field(False, description="Whether date is weekend")
    is_holiday: bool = Field(False, description="Whether date is holiday")
    holiday_name: Optional[str] = Field(None, description="Holiday name")
    job_role: Optional[str] = Field(None, description="Job role")
    shift_name: Optional[str] = Field(None, description="Shift name for reception")
    
    # Additional info
    notes: Optional[str] = Field(None, description="Additional notes")
    punch_records: List[Dict[str, Any]] = Field([], description="Raw punch records")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
            time: lambda v: v.strftime("%H:%M:%S") if v else None
        }


class CalendarConfigResponse(BaseModel):
    """Calendar configuration and metadata"""
    violation_threshold_minutes: int = Field(15, description="Minutes threshold for major violations")
    minor_issue_threshold_minutes: int = Field(1, description="Minutes threshold for minor issues")
    weekend_days: List[int] = Field([6, 0], description="Weekend days (0=Sunday, 6=Saturday)")
    status_colors: Dict[str, str] = Field(..., description="Color mapping for statuses")
    status_symbols: Dict[str, str] = Field(..., description="Symbol mapping for statuses")
    roles: List[str] = Field([], description="Available job roles")
    months: List[Dict[str, Any]] = Field([], description="Available months with data")


class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    code: Optional[str] = Field(None, description="Error code")


class SuccessResponse(BaseModel):
    """Standard success response"""
    success: bool = Field(True, description="Operation success status")
    message: str = Field(..., description="Success message")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional response data")


# Utility schemas for complex operations

class BulkStatusUpdate(BaseModel):
    """Bulk update attendance status"""
    employee_ids: List[str] = Field(..., description="Employee IDs to update")
    date_range: Dict[str, str] = Field(..., description="Start and end dates")
    recalculate: bool = Field(True, description="Whether to recalculate from raw data")


class CalendarExportResponse(BaseModel):
    """Export operation response"""
    file_url: Optional[str] = Field(None, description="Download URL for file")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    record_count: int = Field(..., description="Number of records exported")
    format: str = Field(..., description="Export format used")
    generated_at: datetime = Field(..., description="Export generation timestamp")
    expires_at: Optional[datetime] = Field(None, description="Download link expiration")


# Configuration for OpenAPI documentation removed due to recursion issues