"""
Additional models for Attendance Calendar functionality
Extends existing models in models.py for calendar-specific features
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Float, JSON, Time, Date, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from enum import Enum
from datetime import date, datetime, time
from typing import Optional, List, Dict
from dataclasses import dataclass


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


class DailyAttendanceSummary(Base):
    """Pre-calculated daily attendance summary for fast calendar loading"""
    __tablename__ = "daily_attendance_summary"

    id = Column(Integer, primary_key=True, index=True)
    employee_badge_number = Column(String(50), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Attendance status
    status = Column(SQLEnum(AttendanceStatus), nullable=False)
    
    # Time information
    check_in_time = Column(DateTime, nullable=True)
    check_out_time = Column(DateTime, nullable=True)
    scheduled_start = Column(Time, nullable=True)
    scheduled_end = Column(Time, nullable=True)
    
    # Calculations
    late_minutes = Column(Integer, default=0)
    early_departure_minutes = Column(Integer, default=0)
    total_work_hours = Column(Float, nullable=True)
    
    # Additional info
    is_weekend = Column(Boolean, default=False)
    is_holiday = Column(Boolean, default=False)
    holiday_name = Column(String(200), nullable=True)
    job_role = Column(String(50), nullable=True)
    shift_name = Column(String(100), nullable=True)  # For reception role
    
    # Metadata
    notes = Column(Text, nullable=True)
    last_calculated = Column(DateTime, default=func.now())
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('employee_badge_number', 'date'),
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


# Dataclasses for API responses (not database models)

@dataclass
class DailyAttendanceData:
    """Single day attendance data for API response"""
    date: str
    status: AttendanceStatus
    check_in: Optional[datetime]
    check_out: Optional[datetime]
    scheduled_start: Optional[time]
    scheduled_end: Optional[time]
    late_minutes: int
    early_departure_minutes: int
    work_hours: Optional[float]
    is_weekend: bool
    is_holiday: bool
    holiday_name: Optional[str]
    notes: Optional[str]


@dataclass
class EmployeeCalendarData:
    """Employee data for monthly calendar"""
    id: str
    name: str
    role: Optional[str]
    daily_attendance: Dict[int, DailyAttendanceData]


@dataclass
class CalendarStatistics:
    """Monthly calendar statistics"""
    total_employees: int
    total_working_days: int
    perfect_attendance_rate: float
    punctuality_rate: float
    average_late_minutes: float
    violation_count: int
    absent_count: int
    role_breakdown: Dict[str, Dict[str, int]]


@dataclass
class MonthlyCalendarResponse:
    """Complete monthly calendar API response"""
    year: int
    month: int
    month_name: str
    days_in_month: int
    employees: List[EmployeeCalendarData]
    holidays: List[int]
    weekends: List[int]
    statistics: CalendarStatistics


# Helper functions for status calculation

def calculate_attendance_status(
    check_in: Optional[datetime],
    check_out: Optional[datetime],
    scheduled_start: Optional[time],
    scheduled_end: Optional[time],
    date_obj: date,
    is_weekend: bool = False,
    is_holiday: bool = False,
    violation_threshold_minutes: int = 15
) -> AttendanceStatus:
    """
    Calculate attendance status based on check-in/out times and schedule
    
    Args:
        check_in: Check-in datetime
        check_out: Check-out datetime  
        scheduled_start: Scheduled start time
        scheduled_end: Scheduled end time
        date_obj: Date of attendance
        is_weekend: Whether the date is a weekend
        is_holiday: Whether the date is a holiday
        violation_threshold_minutes: Minutes threshold for major violation
        
    Returns:
        AttendanceStatus enum value
    """
    
    # Non-working days
    if is_weekend or is_holiday:
        return AttendanceStatus.NON_WORKING_DAY
    
    # No attendance record
    if check_in is None and check_out is None:
        return AttendanceStatus.ABSENT
    
    # Partial attendance (only check-in or only check-out)
    if check_in is None or check_out is None:
        return AttendanceStatus.PARTIAL
    
    # If no schedule defined, assume on time
    if scheduled_start is None or scheduled_end is None:
        return AttendanceStatus.PERFECT
    
    # Calculate lateness and early departure
    late_minutes = 0
    early_departure_minutes = 0
    
    # Check lateness
    scheduled_start_dt = datetime.combine(date_obj, scheduled_start)
    if check_in > scheduled_start_dt:
        late_minutes = (check_in - scheduled_start_dt).total_seconds() / 60
    
    # Check early departure
    scheduled_end_dt = datetime.combine(date_obj, scheduled_end)
    if check_out < scheduled_end_dt:
        early_departure_minutes = (scheduled_end_dt - check_out).total_seconds() / 60
    
    # Determine status
    if late_minutes > violation_threshold_minutes or early_departure_minutes > violation_threshold_minutes:
        return AttendanceStatus.MAJOR_VIOLATION
    elif late_minutes > 0 or early_departure_minutes > 0:
        return AttendanceStatus.MINOR_ISSUE
    else:
        return AttendanceStatus.PERFECT


def get_status_color(status: AttendanceStatus) -> str:
    """Get hex color code for attendance status"""
    color_map = {
        AttendanceStatus.PERFECT: "#4CAF50",        # Green
        AttendanceStatus.MINOR_ISSUE: "#FF9800",    # Orange
        AttendanceStatus.MAJOR_VIOLATION: "#F44336", # Red
        AttendanceStatus.ABSENT: "#E0E0E0",         # Light Gray
        AttendanceStatus.NON_WORKING_DAY: "#2196F3", # Blue
        AttendanceStatus.PARTIAL: "#FF5722"         # Deep Orange
    }
    return color_map.get(status, "#666666")


def get_status_symbol(status: AttendanceStatus) -> str:
    """Get symbol for attendance status"""
    symbol_map = {
        AttendanceStatus.PERFECT: "✓",
        AttendanceStatus.MINOR_ISSUE: "⚠",
        AttendanceStatus.MAJOR_VIOLATION: "✗",
        AttendanceStatus.ABSENT: "-",
        AttendanceStatus.NON_WORKING_DAY: "H",
        AttendanceStatus.PARTIAL: "◐"
    }
    return symbol_map.get(status, "?")