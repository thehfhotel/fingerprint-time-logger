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
    # Removed relationships to deleted models: sync_logs, status_logs, error_events


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
    
    # Status and visibility
    is_active = Column(Boolean, nullable=False, default=True)              # Merged from both models
    is_hidden = Column(Boolean, nullable=False, default=False)             # From EmployeeThaiName (UI control)
    
    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    attendance_records = relationship("AttendanceRecord", back_populates="employee")


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
    adjustments = relationship("AttendanceAdjustment", back_populates="attendance_record", cascade="all, delete-orphan")




class AttendanceAdjustment(Base):
    """Manual adjustments to attendance records (late marking, corrections, etc.)"""
    __tablename__ = "attendance_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    attendance_record_id = Column(Integer, ForeignKey("attendance_records.id"), nullable=False)
    
    # Adjustment details
    adjustment_type = Column(String(20), nullable=False)  # 'late_marking', 'correction', 'manual_entry'
    is_marked_late = Column(Boolean, nullable=False, default=False)  # Manual late marking
    late_reason = Column(String(200), nullable=True)  # Reason for late marking
    
    # Audit fields
    adjusted_by = Column(String(50), nullable=True)  # Who made the adjustment (for future user management)
    adjustment_timestamp = Column(DateTime, default=func.now(), nullable=False)
    notes = Column(Text, nullable=True)  # Additional notes
    
    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    attendance_record = relationship("AttendanceRecord", back_populates="adjustments")


# SyncLog model removed - not used by application


# SyncQueue model removed - not used by application


# DeviceStatusLog model removed - not used by application


# DataCache model removed - not used by application


# ErrorEvent model removed - not used by application

# Work Schedule Management Models - Added for schedule management feature

# JobRole model removed - simplifying employee management


# WorkSchedule model removed - not used by application

# WorkShift model removed - not used by application

# EmployeeMonthlySchedule model removed - not used by application

# ReceptionShiftAssignment model removed - not used by application

# TimeCheckConfig model removed - not used by application

# DailyAttendanceSummary model removed - not used by application

# Attendance Calendar Models

# AttendanceStatus enum removed - not used by application

# Holiday model removed - not used by application

# Holiday model removed - not used by application

# MonthlyAttendanceStats model removed - not used by application