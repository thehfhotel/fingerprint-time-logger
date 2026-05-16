"""
Consolidated Attendance API - All attendance operations in one place
Replaces: attendance.py, attendance_calendar.py, calendar_api.py, simple_calendar.py
"""

import asyncio
from datetime import datetime, date, time as dtime, timezone, timedelta
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
import calendar as _calendar
import csv
import io


# Bangkok timezone helpers live in app.utils.timezone (single source of truth).
from app.utils.timezone import BANGKOK_TZ, to_bangkok as _to_bangkok

from app.core.database import get_db
from app.models.models import (
    AttendanceRecord, Employee, EmployeeLeave, PublicHoliday, Shift,
)
from app.services.attendance_service import attendance_service
from app.services.device_service import device_service
from app.services.export_service import export_service
from app.services.shift_service import effective_shift, shift_window_for

router = APIRouter()


# ============================================================================
# BY-DATE SUMMARY HELPERS (v2 by-date page)
# ============================================================================

# Sort priority for the by-date status enum. Late first (most actionable),
# then absent, then on-time, then off. The page hides "off" by default;
# putting them last keeps the order stable when an admin toggles the
# filter to show them.
_BY_DATE_STATUS_SORT_ORDER = {
    "late": 0,
    "absent": 1,
    "on_time": 2,
    "off": 3,
}


# (_bangkok_day_to_utc_range removed 2026-05: shift-aware /by-date uses
# shift_window_for() per employee instead of a single Bangkok-day range.)


def _resolve_display_name(employee: Employee) -> str:
    """
    Resolve the user-facing display name for an employee.

    Preference order (per plan + how the rest of the codebase treats
    display_name, e.g. consolidated_employees.py:87-89):
      1. employee.display_name — already the resolved nickname/thai_name
      2. employee.english_name — fallback if display_name somehow blank
      3. f"พนักงาน {badge_number}" — final fallback matching factory default
    """
    if employee.display_name:
        return employee.display_name
    if employee.english_name:
        return employee.english_name
    return f"พนักงาน {employee.badge_number}"


def _compute_hours_worked(
    first_in_utc: Optional[datetime],
    last_out_utc: Optional[datetime],
) -> Optional[float]:
    """
    Decimal hours between first_in and last_out. Returns None if either is
    missing or if they're the same instant (single-punch day — no meaningful
    duration).
    """
    if first_in_utc is None or last_out_utc is None:
        return None
    if last_out_utc <= first_in_utc:
        return None
    delta_seconds = (last_out_utc - first_in_utc).total_seconds()
    return round(delta_seconds / 3600, 2)


def _compute_status_shift_aware(
    first_in_bangkok: Optional[datetime],
    shift_start_bkk: datetime,
    is_off: bool,
) -> str:
    """
    Compute by-date status using the employee's effective shift.

    - "off": employee is scheduled off (no shift today)
    - "absent": effective shift exists, no punches in its window
    - "late": first punch in window is AFTER shift_start_bkk
    - "on_time": first punch in window is at-or-before shift_start_bkk

    ``first_in_bangkok`` is the first attendance punch inside the shift's
    window (see ``shift_window_for``), already converted to Bangkok time.
    For overnight shifts (e.g. NIGHT 22:00-07:00), shift_start_bkk is the
    same calendar day as the assigned date even though the punch may be
    on the following day.
    """
    if is_off:
        return "off"
    if first_in_bangkok is None:
        return "absent"
    if first_in_bangkok > shift_start_bkk:
        return "late"
    return "on_time"


# ============================================================================
# ATTENDANCE RECORDS - Basic CRUD Operations
# ============================================================================

@router.get("/", response_model=Dict[str, Any])
async def get_attendance_records(
    start_date: Optional[date] = Query(None, description="Start date filter"),
    end_date: Optional[date] = Query(None, description="End date filter"),
    employee_badge: Optional[str] = Query(None, description="Employee badge filter"),
    limit: int = Query(100, description="Maximum records to return")
):
    """Get attendance records with optional filtering"""
    try:
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            employee_badge=employee_badge,
            limit=limit
        )
        
        # Convert to list format for API response
        record_list = []
        for record in records:
            record_list.append({
                "id": record.id,
                "employee_badge_number": record.employee_badge_number,
                "timestamp": record.timestamp.replace(tzinfo=timezone.utc).isoformat() if record.timestamp else None,
                "punch_type": record.punch_type,
                "status": record.status,
                "device_id": record.device_id,
                "sync_status": record.sync_status
            })
        
        return {
            "records": record_list,
            "total": len(record_list),
            "filters": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "employee_badge": employee_badge
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_attendance_summary():
    """
    Get attendance summary for dashboard

    CACHE-FIRST ARCHITECTURE:
    - Serves data from cache (refreshed every 5 minutes by background scheduler)
    - No database query overhead, instant response from memory cache
    """
    try:
        from app.services.device_cache_service import device_cache_service

        # Get cached summary (includes metadata)
        cached_data = device_cache_service.get('attendance_summary', include_metadata=True)

        if cached_data is None:
            # Cache miss - fallback to direct query (graceful degradation)
            summary = attendance_service.get_attendance_summary()
            return {
                "data": summary,
                "cache_metadata": {
                    "cached_at": None,
                    "age_seconds": 0,
                    "stale": True,
                    "source": "direct_query"
                }
            }

        return cached_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Manual record creation endpoint removed - not used by frontend


@router.get("/employee/{employee_id}")
async def get_employee_attendance_by_id(
    employee_id: int,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db)
):
    """Get attendance records for a specific employee by ID (for individual attendance page)"""
    try:
        # Get employee by ID
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        # Get attendance records
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            employee_badge=employee.badge_number,
            limit=1000  # Higher limit for individual view
        )

        # Format records for the individual attendance page
        formatted_records = []
        for record in records:
            formatted_records.append({
                "id": record.id,
                "check_in_time": record.timestamp.isoformat() if record.punch_type == 0 else None,
                "check_out_time": record.timestamp.isoformat() if record.punch_type == 1 else None,
                "punch_type": record.punch_type,
                "timestamp": record.timestamp.isoformat()
            })

        return {
            "employee_id": employee_id,
            "employee_name": employee.display_name,
            "records": formatted_records,
            "total": len(formatted_records)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employee/badge/{employee_badge}")
async def get_employee_attendance(
    employee_badge: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(100),
    db: Session = Depends(get_db)
):
    """Get attendance records for a specific employee by badge"""
    try:
        # Check if employee exists first
        employee = db.query(Employee).filter(Employee.badge_number == employee_badge).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            employee_badge=employee_badge,
            limit=limit
        )

        return {
            "employee_badge": employee_badge,
            "records": [
                {
                    "id": record.id,
                    "timestamp": record.timestamp.replace(tzinfo=timezone.utc).isoformat() if record.timestamp else None,
                    "punch_type": record.punch_type,
                    "status": record.status,
                    "device_id": record.device_id,
                    "validation_message": record.validation_message  # Include for QR check-in detection
                }
                for record in records
            ],
            "total": len(records)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CALENDAR VIEWS - Simplified calendar functionality
# ============================================================================

@router.get("/calendar/config")
async def get_calendar_config():
    """Get calendar display configuration"""
    return {
        "violation_threshold_minutes": 15,
        "status_colors": {
            "perfect": "#22c55e",
            "minor_issue": "#eab308", 
            "violation": "#ef4444",
            "absent": "#9ca3af",
            "non_working": "#3b82f6"
        },
        "working_days": [1, 2, 3, 4, 5]  # Monday to Friday
    }


@router.get("/calendar/{year}/{month}")
async def get_calendar_data(year: int, month: int):
    """Get attendance data for calendar view"""
    try:
        # Get start and end dates for the month
        # NOTE: attendance_service interprets end_date as INCLUSIVE Bangkok end-of-day,
        # so end_date must be the LAST day of the month, not the first day of the next.
        start_date = date(year, month, 1)
        last_day = _calendar.monthrange(year, month)[1]
        end_date = date(year, month, last_day)

        # Get all attendance records for the month
        records = attendance_service.get_attendance_records(
            start_date=start_date,
            end_date=end_date,
            limit=10000
        )

        # Group by employee and date — convert UTC-stored timestamps to Bangkok
        # for user-facing date grouping and time display.
        calendar_data = {}
        for record in records:
            employee_badge = record.employee_badge_number
            bangkok_timestamp = _to_bangkok(record.timestamp)
            record_date = bangkok_timestamp.date().isoformat()

            if employee_badge not in calendar_data:
                calendar_data[employee_badge] = {}

            if record_date not in calendar_data[employee_badge]:
                calendar_data[employee_badge][record_date] = []

            calendar_data[employee_badge][record_date].append({
                "time": bangkok_timestamp.strftime("%H:%M"),
                "type": "check-in" if record.punch_type == 0 else "check-out",
                "status": record.status
            })
        
        return {
            "year": year,
            "month": month,
            "calendar_data": calendar_data,
            "total_records": len(records)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-date")
async def get_attendance_by_date(
    date_param: Optional[str] = Query(
        None,
        alias="date",
        description="Bangkok-local day in YYYY-MM-DD. Defaults to today (Bangkok).",
    ),
    location: Optional[str] = Query(
        None,
        description=(
            "Filter to one branch. Values: 'HF' or 'HF_VILLE'. Omit to "
            "include all employees regardless of location. Employees "
            "with location=NULL are included only when this filter is "
            "also NULL (omitted)."
        ),
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Per-date attendance summary for the v2 by-date page.

    One row per ACTIVE employee whose effective shift on the target
    Bangkok date is either a real shift (NORMAL/MORNING/MID/AFTERNOON/
    NIGHT) or a scheduled off-day. Employees with no role and no
    default shift are treated as "untracked" and omitted entirely —
    nothing to compare their punches against.

    For each tracked employee:
      - Look up the effective shift (see shift_service.effective_shift)
      - Compute the punch window for that shift on that date
        (shift_service.shift_window_for; overnight shifts cross
        midnight into the next calendar day)
      - Take first/last punch inside the window
      - Status: "on_time" (in by shift_start), "late" (in after
        shift_start), "absent" (no punches in window), "off"
        (scheduled rest)

    first_in / last_out are HH:mm Bangkok. hours_worked is the decimal
    hour delta, or null if there's only one punch.

    Sort: late > absent > on_time > off, then by display_name.

    Returns ``shift`` per row when one applies (code + name_th +
    start/end + crosses_midnight) so the page can show what the
    employee was scheduled for.
    """
    target_day = _parse_date_param(date_param)

    # Validate location filter early so a typo returns 400 instead of
    # silently returning an empty row list.
    _ALLOWED_LOCATIONS = ("HF", "HF_VILLE")
    if location is not None and location not in _ALLOWED_LOCATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"location must be one of {_ALLOWED_LOCATIONS} or omitted",
        )

    # Lookup leaves + holidays once for the target day. Both take
    # precedence over the shift assignment when computing status: a
    # vacationing employee should be flagged "ลาพักร้อน", not "absent",
    # even if they have a shift assigned that day.
    holiday = (
        db.query(PublicHoliday)
        .filter(PublicHoliday.date == target_day)
        .first()
    )
    leaves_by_badge = {
        l.employee_badge_number: l
        for l in db.query(EmployeeLeave)
        .filter(EmployeeLeave.date == target_day)
        .all()
    }

    rows: List[Dict[str, Any]] = []
    for employee in _fetch_active_employees(db):
        if location is not None and employee.location != location:
            continue
        eff = effective_shift(db, employee, target_day)
        if eff.shift is None and not eff.is_off:
            # Untracked — no role, no default. Skip entirely.
            continue
        rows.append(_build_shift_row(
            db, employee, target_day, eff,
            holiday=holiday,
            leave=leaves_by_badge.get(employee.badge_number),
        ))

    rows.sort(key=lambda row: (
        _BY_DATE_STATUS_SORT_ORDER.get(row["status"], 99),
        (row["display_name"] or "").casefold(),
    ))

    return {
        "date": target_day.isoformat(),
        "rows": rows,
    }


def _parse_date_param(raw: Optional[str]) -> date:
    """Parse YYYY-MM-DD; default to Bangkok-today; 400 on bad format."""
    if raw is None:
        return datetime.now(BANGKOK_TZ).date()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid date format. Expected YYYY-MM-DD.",
        )


def _fetch_active_employees(db: Session) -> List[Employee]:
    """All employees with is_active=True. is_hidden is ignored — the v2 page
    is for active payroll and shows hidden employees too if they're active."""
    return db.query(Employee).filter(Employee.is_active == True).all()  # noqa: E712


def _shift_summary(shift: Optional[Shift]) -> Optional[Dict[str, Any]]:
    """Compact shift snapshot for the row payload, or None if off."""
    if shift is None:
        return None
    return {
        "code": shift.code,
        "name_th": shift.name_th,
        "start_time": shift.start_time.strftime("%H:%M"),
        "end_time": shift.end_time.strftime("%H:%M"),
        "crosses_midnight": shift.crosses_midnight,
    }


def _build_shift_row(
    db: Session,
    employee: Employee,
    target_day: date,
    eff,
    *,
    holiday: Optional[PublicHoliday] = None,
    leave: Optional[EmployeeLeave] = None,
) -> Dict[str, Any]:
    """Build one /by-date row using the employee's effective shift.

    Off days produce a row with no times and status="off". Other rows
    query the AttendanceRecord table within the shift's punch window
    (which may straddle midnight for NIGHT shifts) and classify by
    whether the first_in is before or after shift_start.

    Public holiday + personal leave both short-circuit to status="off"
    with leave_type set on the row, so the UI can render a more
    specific label than plain "หยุด".
    """
    # Public holiday wins over an employee's personal leave for label
    # purposes — the holiday is more informative (everyone is off for
    # the same reason). They never co-occur in normal operation.
    if holiday is not None:
        return {
            "badge_number": employee.badge_number,
            "display_name": _resolve_display_name(employee),
            "role": employee.role,
            "location": employee.location,
            "shift": None,
            "first_in": None,
            "last_out": None,
            "hours_worked": None,
            "status": "off",
            "leave_type": "public_holiday",
            "leave_note": holiday.name,
        }

    if leave is not None:
        return {
            "badge_number": employee.badge_number,
            "display_name": _resolve_display_name(employee),
            "role": employee.role,
            "location": employee.location,
            "shift": None,
            "first_in": None,
            "last_out": None,
            "hours_worked": None,
            "status": "off",
            "leave_type": leave.leave_type,
            "leave_note": leave.note,
        }

    if eff.is_off:
        return {
            "badge_number": employee.badge_number,
            "display_name": _resolve_display_name(employee),
            "role": employee.role,
            "location": employee.location,
            "shift": None,
            "first_in": None,
            "last_out": None,
            "hours_worked": None,
            "status": "off",
            "leave_type": None,
            "leave_note": None,
        }

    shift = eff.shift  # guaranteed non-None by caller (untracked were filtered out)
    window = shift_window_for(shift, target_day)

    first_in_utc, last_out_utc = (
        db.query(
            func.min(AttendanceRecord.timestamp),
            func.max(AttendanceRecord.timestamp),
        )
        .filter(
            AttendanceRecord.employee_badge_number == employee.badge_number,
            AttendanceRecord.timestamp >= window.start_utc,
            AttendanceRecord.timestamp < window.end_utc,
        )
        .one()
    )

    first_in_bangkok = _to_bangkok(first_in_utc) if first_in_utc else None
    last_out_bangkok = _to_bangkok(last_out_utc) if last_out_utc else None

    return {
        "badge_number": employee.badge_number,
        "display_name": _resolve_display_name(employee),
        "role": employee.role,
        "location": employee.location,
        "shift": _shift_summary(shift),
        "first_in": first_in_bangkok.strftime("%H:%M") if first_in_bangkok else None,
        "last_out": last_out_bangkok.strftime("%H:%M") if last_out_bangkok else None,
        "hours_worked": _compute_hours_worked(first_in_utc, last_out_utc),
        "status": _compute_status_shift_aware(
            first_in_bangkok, window.shift_start_bkk, eff.is_off,
        ),
        "leave_type": None,
        "leave_note": None,
    }


@router.get("/today")
async def get_today_attendance():
    """Get today's attendance records"""
    try:
        today = date.today()
        records = attendance_service.get_attendance_records(
            start_date=today,
            end_date=today,
            limit=1000
        )
        
        return {
            "date": today.isoformat(),
            "records": [
                {
                    "employee_badge": record.employee_badge_number,
                    "timestamp": record.timestamp.replace(tzinfo=timezone.utc).isoformat() if record.timestamp else None,
                    "punch_type": record.punch_type,
                    "status": record.status
                }
                for record in records
            ],
            "total": len(records)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# SYNC & DEVICE INTEGRATION
# ============================================================================

@router.post("/sync")
async def sync_attendance_from_device():
    """Trigger an attendance import through the lock-aware scheduler."""
    try:
        from app.services.background_scheduler import background_scheduler
        return await background_scheduler.run_attendance_import_now()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync/status")
async def get_sync_status():
    """Get sync status from the device-status cache (no live device call)."""
    try:
        from app.services.device_cache_service import device_cache_service
        device_status = device_cache_service.get_raw("device_status") or {}
        device = device_service.get_default_device()
        connected = bool(device_status.get("connected", False))

        return {
            "status": "healthy" if connected else "unhealthy",
            "device_status": device_status,
            "last_sync": device.last_sync.isoformat() if device and device.last_sync else None,
            "sync_available": connected,
            "last": device.last_sync.isoformat() if device and device.last_sync else None,
            "sync": connected,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# EXPORT FUNCTIONALITY
# ============================================================================

@router.get("/export/csv")
async def export_attendance_csv(
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    streaming: bool = Query(False, description="Enable streaming for large datasets"),
    batch_size: int = Query(1000, description="Batch size for streaming"),
    db: Session = Depends(get_db)
):
    """Export attendance records as CSV file"""
    try:
        # Create export service instance
        service = export_service.__class__(db)
        
        # Convert dates to datetime for compatibility
        start_datetime = datetime.combine(start_date, datetime.min.time()) if start_date else None
        end_datetime = datetime.combine(end_date, datetime.max.time()) if end_date else None
        
        # Count records
        total_records = service.count_records(
            start_date=start_datetime,
            end_date=end_datetime
        )
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"attendance_export_{timestamp}.csv"
        
        # Return CSV response
        return service.export_to_csv(
            start_date=start_datetime,
            end_date=end_datetime,
            format_type="detailed",
            include_employee_names=True,
            include_device_names=True
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


# ============================================================================
# VALIDATION & STATISTICS
# ============================================================================

# Daily statistics endpoint removed - not used by frontend


# Record validation endpoint removed - not used by frontend


# ============================================================================
# HEALTH & STATUS
# ============================================================================

@router.get("/health")
async def attendance_health_check():
    """Health check for attendance system (cache-only — no live device call)."""
    try:
        from app.services.device_cache_service import device_cache_service
        device_status = device_cache_service.get_raw("device_status") or {}
        recent_records = attendance_service.get_attendance_records(limit=1)

        return {
            "status": "healthy",
            "device_connected": bool(device_status.get("connected", False)),
            "has_recent_data": len(recent_records) > 0,
            "last_record": recent_records[0].timestamp.isoformat() if recent_records else None
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }



