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

    # QR Terminal support (Phase 1 - QR Check-in Feature)
    device_type = Column(String(20), nullable=False, default="fingerprint")  # "fingerprint" or "qr_terminal"
    device_metadata = Column(Text, nullable=True)  # JSON-encoded device metadata (GPS, display settings, etc.)

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

    # LINE integration fields (Phase 1 - QR Check-in Feature)
    line_user_id = Column(String(100), nullable=True, unique=True)        # LINE user identifier
    line_display_name = Column(String(100), nullable=True)                # LINE display name
    line_picture_url = Column(String(500), nullable=True)                 # LINE profile picture URL
    line_linking_code = Column(String(6), nullable=True, unique=True)     # 6-digit temporary linking code
    line_linking_code_generated_at = Column(DateTime, nullable=True)      # When linking code was generated

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


class ApplicationLog(Base):
    """Application activity and error logging for system monitoring"""
    __tablename__ = "application_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    level = Column(String(10), nullable=False, index=True)  # INFO, WARNING, ERROR, DEBUG
    category = Column(String(20), nullable=False, index=True)  # sync, connection, api, error, system
    action = Column(String(100), nullable=False)  # sync_completed, device_connected, etc.
    message = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)  # Additional structured data
    user_agent = Column(String(500), nullable=True)  # For API requests
    ip_address = Column(String(45), nullable=True)  # For API requests
    employee_badge = Column(String(50), nullable=True)  # Related employee if applicable
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)  # Related device if applicable
    duration_ms = Column(Integer, nullable=True)  # Operation duration if applicable
    success = Column(Boolean, nullable=True)  # Success/failure for operations

    # Relationships
    device = relationship("Device", foreign_keys=[device_id])