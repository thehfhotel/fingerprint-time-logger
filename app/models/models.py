from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Float, JSON, Time, Date, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from enum import Enum


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    ip_address = Column(String(15), nullable=True)  # Nullable for QR terminals (not used)
    port = Column(Integer, nullable=True, default=4370)  # Nullable for QR terminals (not used)
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

    # Role + shift scheduling (Phase: Employee Shifts, 2026-05).
    # role: 'reception' | 'housekeeping' | 'technician' | 'admin' | NULL
    #   NULL means "untracked" — the by-date page won't compute late/absent
    #   for this employee until a role is set.
    # default_shift_id: shift used on days without an override.
    #   reception employees typically leave this NULL and assign per-day
    #   shifts via shift_assignments; the other three roles get a default.
    # location: 'HF' | 'HF_VILLE' | NULL — which branch this employee
    #   works at. Drives per-location reception rosters and the
    #   /by-date page's location filter. NULL = unassigned, treated as
    #   "either" for filtering purposes.
    role = Column(String(20), nullable=True, index=True)
    default_shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=True)
    location = Column(String(20), nullable=True, index=True)

    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    attendance_records = relationship("AttendanceRecord", back_populates="employee")
    default_shift = relationship("Shift", foreign_keys=[default_shift_id])
    shift_assignments = relationship("ShiftAssignment", back_populates="employee", cascade="all, delete-orphan")
    schedules = relationship("EmployeeSchedule", back_populates="employee", cascade="all, delete-orphan")


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


# ============================================================================
# Employee Shifts (2026-05)
# ============================================================================

class Shift(Base):
    """One work-shift definition. Seeded with 5 rows: NORMAL, MORNING, MID,
    AFTERNOON, NIGHT. start_time / end_time are HH:MM in Bangkok local
    time. If end_time <= start_time the shift crosses midnight (the only
    seeded example is NIGHT 22:00-07:00).

    Adding more shifts later is a data operation (INSERT into shifts);
    no code changes required.
    """
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True, index=True)
    # Stable identifier used by API + admin UI. Examples:
    # NORMAL, MORNING, MID, AFTERNOON, NIGHT.
    code = Column(String(20), unique=True, nullable=False, index=True)
    # Single-letter shorthand used on the reception monthly roster
    # spreadsheet: A=MORNING, B=AFTERNOON, C=MID, D=NIGHT. NORMAL is
    # NULL here because it's not a reception shift.
    letter = Column(String(1), nullable=True)
    # Thai display label (e.g. "ปกติ", "เช้า", "สาย", "บ่าย", "ดึก").
    name_th = Column(String(50), nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    # Hex color used by the roster grid to visually distinguish shifts.
    # Backfilled per code in migration 20260516_010000; admin can change
    # via PATCH /api/private/shifts/{code}/color. NULL falls back to a
    # neutral gray on the client.
    color = Column(String(7), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    @property
    def crosses_midnight(self) -> bool:
        """True iff end_time <= start_time (overnight shift)."""
        return self.end_time <= self.start_time


class ShiftAssignment(Base):
    """Per-day override of an employee's effective shift.

    Used primarily for reception employees on a rotating roster, but
    works for any employee on any date. A row with ``shift_id = NULL``
    means "scheduled off today" — the by-date page will not flag the
    employee as absent on that date.

    Resolution order for an employee's effective shift on a given
    Bangkok date D (see app/services/shift_service.py:effective_shift):
      1. ShiftAssignment row for (badge, D) — including NULL = off
      2. Employee.default_shift_id
      3. None — employee is not tracked for that day
    """
    __tablename__ = "shift_assignments"

    id = Column(Integer, primary_key=True, index=True)
    employee_badge_number = Column(
        String(50),
        ForeignKey("employees.badge_number"),
        nullable=False,
        index=True,
    )
    # Bangkok-local date. We don't store timezone because the column
    # represents a calendar day, not a moment.
    date = Column(Date, nullable=False, index=True)
    # NULL = scheduled off
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("employee_badge_number", "date", name="uq_assignment_badge_date"),
    )

    employee = relationship("Employee", back_populates="shift_assignments")
    shift = relationship("Shift")


class EmployeeSchedule(Base):
    """Effective-dated work schedule for one employee (2026-06).

    Each row is the schedule that takes effect on ``effective_from`` and
    stays in force until a later row supersedes it. For any Bangkok date
    D, the applicable row is the one with the greatest effective_from <= D
    (see app/services/shift_service.py:effective_shift). This is what gives
    role/workday/hours changes proper history — a May report keeps May's
    schedule even after the employee's role changes in June.

    Fields:
      - role: 'reception' | 'housekeeping' | 'technician' | 'admin' | NULL
        Reception is roster-driven (per-day shift_assignments); the other
        roles use work_days + work_start/work_end below.
      - work_days: comma-separated Python weekday ints, Mon=0 .. Sun=6
        (e.g. "0,1,2,3,4,5" = Mon–Sat). Days not listed are scheduled off,
        NOT absent. NULL/empty for reception (roster) or untracked.
      - work_start / work_end: Bangkok-local HH:MM defining the day's shift
        for non-reception roles. end <= start means an overnight shift.
        NULL for reception/untracked.

    Employee.role is kept as a denormalised cache of the *current* (as-of
    today) version so existing code that reads employee.role stays valid.
    """
    __tablename__ = "employee_schedules"

    id = Column(Integer, primary_key=True, index=True)
    employee_badge_number = Column(
        String(50),
        ForeignKey("employees.badge_number"),
        nullable=False,
        index=True,
    )
    # Bangkok-local calendar day this schedule takes effect.
    effective_from = Column(Date, nullable=False, index=True)
    role = Column(String(20), nullable=True)
    work_days = Column(String(20), nullable=True)
    work_start = Column(Time, nullable=True)
    work_end = Column(Time, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint(
            "employee_badge_number", "effective_from",
            name="uq_employee_schedule_date",
        ),
    )

    employee = relationship("Employee", back_populates="schedules")


# ============================================================================
# Leaves + Public Holidays (2026-05)
# ============================================================================

class LeaveType(Base):
    """Lookup row for the 4 leave types used by EmployeeLeave + the
    admin UI: vacation / personal / sick / public_holiday.

    The `color` column is editable from the shifts-admin "ตั้งค่าสีกะ"
    legend, so admins can recolor leave badges the same way they
    recolor shift cells. Seeded with sensible defaults in migration
    20260516_020000.
    """
    __tablename__ = "leave_types"

    code = Column(String(20), primary_key=True)
    name_th = Column(String(50), nullable=False)
    color = Column(String(7), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class PublicHoliday(Base):
    """Company-wide non-working day. Applies to every employee at every
    location for that Bangkok-local calendar date.

    Used by:
      - /by-date: an employee whose effective shift is a real shift on
        a public-holiday date is flagged off (leave_type='public_holiday')
        rather than absent / late.
      - The reception roster grid: cells on holiday dates render as a
        read-only badge instead of the A/B/C/D/OFF dropdown.
    """
    __tablename__ = "public_holidays"

    date = Column(Date, primary_key=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=func.now())


class EmployeeLeave(Base):
    """One employee on leave for one specific Bangkok-local date.

    leave_type must be one of:
      - 'vacation' (พักร้อน)
      - 'personal' (ลากิจ)
      - 'sick'     (ลาป่วย)

    Multi-day leaves are stored as one row per date so the
    UNIQUE (badge, date) index can short-circuit per-day lookups. The
    leaves admin UI bulk-inserts a date range as N rows.

    Public holidays are stored in PublicHoliday (no badge needed).
    """
    __tablename__ = "employee_leaves"

    id = Column(Integer, primary_key=True, index=True)
    employee_badge_number = Column(
        String(50),
        ForeignKey("employees.badge_number"),
        nullable=False,
        index=True,
    )
    date = Column(Date, nullable=False, index=True)
    leave_type = Column(String(20), nullable=False)
    note = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("employee_badge_number", "date", name="uq_leave_badge_date"),
    )

    employee = relationship("Employee")


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