"""
Effective-shift resolution and shift-window arithmetic.

The /by-date endpoint and the absent-detection logic in
``consolidated_attendance.get_attendance_by_date`` both depend on
answering "what shift was Employee E supposed to work on Bangkok date
D?". The contract is in three layers:

  1. ShiftAssignment row for (badge, date) — including ``shift_id = NULL``
     which means "scheduled off today, do not flag as absent".
  2. Employee.default_shift_id — applied to every day without an override.
  3. None — the employee is "untracked" for that day (no role yet, or
     role set but no default and no override).

The functions in this module are intentionally pure: they take a session
or pre-fetched objects and return values. No HTTP, no logging, no global
state. That makes them trivial to test and easy to swap out if the
resolution rules change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type, datetime, time as time_type, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import Employee, EmployeeSchedule, Shift, ShiftAssignment
from app.utils.timezone import BANGKOK_TZ


# How far before the shift-start (and after the shift-end) we still count
# an attendance punch as belonging to this shift. 2h handles common cases:
# an employee arriving 30 min early, a manager forgetting to punch out
# until well after their shift ended, etc. Keep this <= 4h so a worker's
# pre-shift window doesn't bleed into the previous shift's post-window
# (closest overlap is MID 11:00 ending 20:00 → AFTERNOON 13:00 → 8h gap,
# so 2h either side is comfortably safe).
SHIFT_WINDOW_BUFFER = timedelta(hours=2)


@dataclass(frozen=True)
class ShiftWindow:
    """Resolved punch window for a shift on a specific Bangkok date.

    ``start_utc`` / ``end_utc`` are naive UTC datetimes (matching the
    AttendanceRecord.timestamp column shape). ``shift_start_bkk`` is a
    timezone-aware Bangkok datetime — used by the lateness check to
    compare apples-to-apples with the bangkok-localised first_in punch.
    """

    start_utc: datetime
    end_utc: datetime
    shift_start_bkk: datetime
    crosses_midnight: bool


# --- Resolution -----------------------------------------------------------


# Default shift codes per role. Roles not in this map (or None) fall
# through to "look at default_shift_id only" — i.e. they're untracked
# unless the admin explicitly set a default shift on the employee.
#
# Reception isn't here on purpose: reception staff rotate, so a missing
# per-day assignment for them means "off today", not "use a fallback".
DEFAULT_SHIFT_CODE_BY_ROLE: dict[str, str] = {
    "housekeeping": "MORNING",      # 07:00–16:00
    "technician":   "NORMAL",       # 08:00–17:00
    "admin":        "NORMAL",       # 08:00–17:00
}

# Roles that require an explicit per-day assignment. Without one,
# they're considered "off today" (not absent).
ROLES_REQUIRING_DAILY_ASSIGNMENT = frozenset({"reception"})


def role_default_shift(db: Session, role: Optional[str]) -> Optional[Shift]:
    """Return the seeded Shift row for the role's default, or None.

    Looks up by ``code`` so the function survives shift-id renumbering
    (migrations may re-seed). Returns None for roles that don't have a
    role-level default (e.g. ``reception``) or for None.
    """
    if not role:
        return None
    code = DEFAULT_SHIFT_CODE_BY_ROLE.get(role)
    if not code:
        return None
    return db.query(Shift).filter(Shift.code == code).first()


@dataclass(frozen=True)
class EffectiveShift:
    """The result of resolving an employee's shift for one date.

    ``shift`` is None when the employee is scheduled off (explicit
    override with shift_id=NULL) OR when they're untracked for that day.
    ``is_off`` distinguishes the two:
      - is_off=True  → scheduled off (don't flag absent)
      - is_off=False, shift=None → untracked (don't surface on /by-date)
    ``source`` records why we landed where we did, for logs/UI.
    """

    shift: Optional[Shift]
    is_off: bool
    source: str  # 'override' | 'override_off' | 'schedule' |
                 # 'schedule_off_day' | 'schedule_reception_off' |
                 # 'employee_default' | 'role_default' | 'untracked'


def _schedule_as_of(
    db: Session,
    badge: str,
    on_date: date_type,
) -> Optional[EmployeeSchedule]:
    """Return the schedule version in force for ``badge`` on ``on_date``.

    The applicable version is the one with the greatest ``effective_from``
    that is still <= ``on_date``. None means the employee has no schedule
    history yet (fall back to the legacy resolution path).
    """
    return (
        db.query(EmployeeSchedule)
        .filter(
            EmployeeSchedule.employee_badge_number == badge,
            EmployeeSchedule.effective_from <= on_date,
        )
        .order_by(EmployeeSchedule.effective_from.desc())
        .first()
    )


def _parse_work_days(raw: Optional[str]) -> set[int]:
    """Parse a comma-separated weekday string into a set of ints.

    ``"0,1,2,3,4"`` → {0, 1, 2, 3, 4} (Python weekdays, Mon=0..Sun=6).
    Blanks are ignored; None or empty yields an empty set.
    """
    if not raw:
        return set()
    return {int(part) for part in raw.split(",") if part.strip()}


def _shift_for_hours(
    db: Session,
    start_time: time_type,
    end_time: time_type,
) -> Shift:
    """Return a Shift matching the given hours.

    Prefer a seeded, active Shift whose start/end match exactly (so the
    familiar code/name like NORMAL/"ปกติ" is preserved). When no seeded
    shift matches, return a TRANSIENT Shift (not added to the session) —
    downstream only reads scalar attributes and the crosses_midnight
    property, so a detached instance is sufficient.
    """
    seeded = (
        db.query(Shift)
        .filter(
            Shift.start_time == start_time,
            Shift.end_time == end_time,
            Shift.is_active.is_(True),
            Shift.code != "OFF",
        )
        .first()
    )
    if seeded is not None:
        return seeded
    return Shift(
        code="CUSTOM",
        letter=None,
        name_th="กำหนดเอง",
        start_time=start_time,
        end_time=end_time,
        is_active=True,
    )


def _resolve_from_schedule(
    db: Session,
    version: EmployeeSchedule,
    on_date: date_type,
) -> EffectiveShift:
    """Resolve the effective shift from a schedule version (tier 2).

    Reception is roster-driven (off without a per-day override). An
    explicit work_days + work_start/work_end version drives a per-weekday
    schedule. A role-only version falls back to that role's default; any
    other version is untracked.
    """
    if version.role == "reception":
        return EffectiveShift(
            shift=None, is_off=True, source="schedule_reception_off",
        )

    work_days = _parse_work_days(version.work_days)
    if version.work_start is not None and version.work_end is not None and work_days:
        if on_date.weekday() not in work_days:
            return EffectiveShift(shift=None, is_off=True, source="schedule_off_day")
        shift = _shift_for_hours(db, version.work_start, version.work_end)
        return EffectiveShift(shift=shift, is_off=False, source="schedule")

    if version.role in DEFAULT_SHIFT_CODE_BY_ROLE:
        role_shift = role_default_shift(db, version.role)
        if role_shift is not None:
            return EffectiveShift(shift=role_shift, is_off=False, source="role_default")
        return EffectiveShift(shift=None, is_off=False, source="untracked")

    return EffectiveShift(shift=None, is_off=False, source="untracked")


def effective_shift(
    db: Session,
    employee: Employee,
    on_date: date_type,
) -> EffectiveShift:
    """Resolve which shift applies to ``employee`` on ``on_date``.

    Three-tier precedence:
      1. ShiftAssignment for (badge, on_date), including shift_id NULL.
      2. The schedule version in force as-of ``on_date`` (the
         EmployeeSchedule row with the greatest effective_from <= on_date):
         reception → off; explicit work_days/hours → schedule or off-day;
         role with a default → role_default; otherwise untracked.
      3. No schedule version → the legacy fallback (employee default,
         reception-without-assignment off, role default, else untracked).
         Required so employees with no EmployeeSchedule history still
         resolve exactly as they did before schedule versions existed.
    """
    override = (
        db.query(ShiftAssignment)
        .filter(
            ShiftAssignment.employee_badge_number == employee.badge_number,
            ShiftAssignment.date == on_date,
        )
        .first()
    )
    if override is not None:
        if override.shift_id is None:
            return EffectiveShift(shift=None, is_off=True, source="override_off")
        return EffectiveShift(shift=override.shift, is_off=False, source="override")

    version = _schedule_as_of(db, employee.badge_number, on_date)
    if version is not None:
        return _resolve_from_schedule(db, version, on_date)

    if employee.default_shift_id is not None:
        return EffectiveShift(
            shift=employee.default_shift,
            is_off=False,
            source="employee_default",
        )

    if employee.role in ROLES_REQUIRING_DAILY_ASSIGNMENT:
        # Reception with no assignment today = off, not untracked.
        return EffectiveShift(shift=None, is_off=True, source="override_off")

    role_shift = role_default_shift(db, employee.role)
    if role_shift is not None:
        return EffectiveShift(shift=role_shift, is_off=False, source="role_default")

    return EffectiveShift(shift=None, is_off=False, source="untracked")


# --- Window arithmetic ---------------------------------------------------


def _crosses_midnight(start_time: time_type, end_time: time_type) -> bool:
    """The convention used by Shift.crosses_midnight, broken out for
    reuse without needing a fully-hydrated Shift instance."""
    return end_time <= start_time


def shift_window_for(shift: Shift, on_date: date_type) -> ShiftWindow:
    """Return the punch window for ``shift`` on Bangkok date ``on_date``.

    Non-overnight (08:00–17:00 on D):
      shift_start = D 08:00 Bangkok
      shift_end   = D 17:00 Bangkok
      window      = [D 06:00, D 19:00] Bangkok  (±2h buffer)

    Overnight (22:00–07:00 on D):
      shift_start = D 22:00 Bangkok
      shift_end   = D+1 07:00 Bangkok
      window      = [D 20:00, D+1 09:00] Bangkok  (±2h buffer)

    The 2h buffer lets early-arriving / late-departing punches still
    count toward this shift instead of falling through the cracks.
    """
    bkk_start_of_day = datetime.combine(on_date, time_type.min, tzinfo=BANGKOK_TZ)
    shift_start_bkk = bkk_start_of_day + timedelta(
        hours=shift.start_time.hour,
        minutes=shift.start_time.minute,
    )

    if _crosses_midnight(shift.start_time, shift.end_time):
        # Ends on D+1.
        shift_end_bkk = bkk_start_of_day + timedelta(
            days=1,
            hours=shift.end_time.hour,
            minutes=shift.end_time.minute,
        )
        crosses = True
    else:
        shift_end_bkk = bkk_start_of_day + timedelta(
            hours=shift.end_time.hour,
            minutes=shift.end_time.minute,
        )
        crosses = False

    window_start_bkk = shift_start_bkk - SHIFT_WINDOW_BUFFER
    window_end_bkk = shift_end_bkk + SHIFT_WINDOW_BUFFER

    return ShiftWindow(
        start_utc=window_start_bkk.astimezone(timezone.utc).replace(tzinfo=None),
        end_utc=window_end_bkk.astimezone(timezone.utc).replace(tzinfo=None),
        shift_start_bkk=shift_start_bkk,
        crosses_midnight=crosses,
    )
