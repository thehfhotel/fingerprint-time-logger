"""
Leaves admin API — public holidays + per-employee leaves.

Mounted under /api/private/leaves/* by main_unified.

Public holidays: company-wide non-working days. CRUD on date as PK.

Employee leaves: per-employee, per-date rows. One row per (badge, date)
so a multi-day vacation is N rows. The admin UI bulk-creates a range.

Both are consumed by:
  - The reception roster grid (renderRoster on /v2/shifts-admin tab 2),
    which renders a colored badge instead of the A/B/C/D dropdown on
    days that have a leave or holiday.
  - The /by-date page (consolidated_attendance.get_attendance_by_date),
    which surfaces leaves/holidays as status='off' with a leave_type
    field so the UI can label "พักร้อน" / "ลากิจ" / "ลาป่วย" /
    "วันหยุดนักขัตฤกษ์".
"""

from __future__ import annotations

import re
from datetime import date as date_type, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee, EmployeeLeave, LeaveType, PublicHoliday
from app.services.thai_holidays import thai_holidays_for_year
from app.api.staff_leave import admin_router as staff_leave_admin_router


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


router = APIRouter()
# These routes add a verified-manager check on top of the existing staff-tier gate.
router.include_router(staff_leave_admin_router, prefix="/requests", tags=["staff-leave-review"])


# Allowed leave types for the per-employee table. 'public_holiday' is
# included here in addition to existing in its own (company-wide)
# PublicHoliday table, because the admin sometimes wants to mark a
# specific employee as off-for-holiday without applying it to everyone
# (e.g. ad-hoc holiday for one branch's staff). When both a per-employee
# public_holiday row and a company-wide PublicHoliday row exist for the
# same date, the company-wide entry wins in /by-date's status logic —
# but they render identically, so the difference is invisible to users.
_ALLOWED_LEAVE_TYPES = ("vacation", "personal", "sick", "public_holiday")


# --- Schemas -------------------------------------------------------------


class PublicHolidayOut(BaseModel):
    date: date_type
    name: str


class PublicHolidayIn(BaseModel):
    date: date_type
    name: str = Field(..., min_length=1, max_length=100)


class EmployeeLeaveOut(BaseModel):
    id: int
    employee_badge_number: str
    date: date_type
    leave_type: str
    note: Optional[str] = None


class EmployeeLeaveIn(BaseModel):
    """Body for POST /api/private/leaves/employee.

    Pass either a single date OR a date range. Range is inclusive on
    both ends, expanded into N rows in the DB.
    """
    employee_badge_number: str
    leave_type: str
    date: Optional[date_type] = None
    date_from: Optional[date_type] = None
    date_to: Optional[date_type] = None
    note: Optional[str] = None


# --- Helpers -------------------------------------------------------------


def _holiday_to_dto(h: PublicHoliday) -> PublicHolidayOut:
    return PublicHolidayOut(date=h.date, name=h.name)


def _leave_to_dto(l: EmployeeLeave) -> EmployeeLeaveOut:
    return EmployeeLeaveOut(
        id=l.id,
        employee_badge_number=l.employee_badge_number,
        date=l.date,
        leave_type=l.leave_type,
        note=l.note,
    )


def _validate_range(from_date: date_type, to_date: date_type, max_days: int = 366) -> None:
    """Sanity-check a [from, to] range. Defaults to 1-year cap."""
    if to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'to' must be on or after 'from'",
        )
    if (to_date - from_date).days > max_days:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date range exceeds {max_days} days",
        )


# --- Public holidays -----------------------------------------------------


@router.get("/holidays", response_model=list[PublicHolidayOut])
def list_holidays(
    from_date: date_type = Query(..., alias="from"),
    to_date: date_type = Query(..., alias="to"),
    db: Session = Depends(get_db),
) -> list[PublicHolidayOut]:
    """All public holidays in [from, to] inclusive. Max range: 1 year."""
    _validate_range(from_date, to_date)
    rows = (
        db.query(PublicHoliday)
        .filter(
            PublicHoliday.date >= from_date,
            PublicHoliday.date <= to_date,
        )
        .order_by(PublicHoliday.date)
        .all()
    )
    return [_holiday_to_dto(h) for h in rows]


@router.post("/holidays", response_model=PublicHolidayOut)
def create_holiday(body: PublicHolidayIn, db: Session = Depends(get_db)) -> PublicHolidayOut:
    """Upsert one public holiday. Replays with the same date update the name."""
    existing = db.query(PublicHoliday).filter(PublicHoliday.date == body.date).first()
    if existing is None:
        existing = PublicHoliday(date=body.date, name=body.name)
        db.add(existing)
    else:
        existing.name = body.name
    db.commit()
    db.refresh(existing)
    return _holiday_to_dto(existing)


@router.delete(
    "/holidays/{on_date}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_holiday(on_date: date_type, db: Session = Depends(get_db)) -> Response:
    """Remove a public holiday. Idempotent — 204 whether or not the row existed."""
    db.query(PublicHoliday).filter(PublicHoliday.date == on_date).delete()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/holidays/thailand/{year}", response_model=list[PublicHolidayOut])
def list_thai_holiday_presets(year: int) -> list[PublicHolidayOut]:
    """Preset list of Thai national public holidays for ``year``, for the
    holiday-config picker. Does NOT touch the DB — the admin selects which to
    add. 2026 is the official curated calendar; other years return the
    fixed-date holidays only (lunar Buddhist days vary and aren't computed)."""
    if year < 2000 or year > 2100:
        raise HTTPException(status_code=400, detail="year out of range (2000-2100)")
    return [
        PublicHolidayOut(date=date_type.fromisoformat(h["date"]), name=h["name"])
        for h in thai_holidays_for_year(year)
    ]


# --- Employee leaves -----------------------------------------------------


@router.get("/employee", response_model=list[EmployeeLeaveOut])
def list_employee_leaves(
    from_date: date_type = Query(..., alias="from"),
    to_date: date_type = Query(..., alias="to"),
    employee_badge: Optional[str] = Query(None, alias="badge"),
    db: Session = Depends(get_db),
) -> list[EmployeeLeaveOut]:
    """All employee leaves in [from, to] inclusive, optionally filtered
    to one employee. Max range: 1 year."""
    _validate_range(from_date, to_date)
    q = db.query(EmployeeLeave).filter(
        EmployeeLeave.date >= from_date,
        EmployeeLeave.date <= to_date,
    )
    if employee_badge:
        q = q.filter(EmployeeLeave.employee_badge_number == employee_badge)
    rows = q.order_by(
        EmployeeLeave.date,
        EmployeeLeave.employee_badge_number,
    ).all()
    return [_leave_to_dto(l) for l in rows]


@router.post("/employee", response_model=list[EmployeeLeaveOut])
def create_employee_leaves(
    body: EmployeeLeaveIn,
    db: Session = Depends(get_db),
) -> list[EmployeeLeaveOut]:
    """Create or replace leave rows for one employee on each date in
    the requested range (or the single date).

    Idempotent per (badge, date): existing rows are updated in-place
    rather than duplicating.
    """
    if body.leave_type not in _ALLOWED_LEAVE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"leave_type must be one of {_ALLOWED_LEAVE_TYPES}",
        )

    if body.date is not None and (body.date_from is not None or body.date_to is not None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either 'date' OR 'date_from'+'date_to', not both",
        )

    if body.date is not None:
        from_d = to_d = body.date
    else:
        if body.date_from is None or body.date_to is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide 'date' or both 'date_from' and 'date_to'",
            )
        from_d, to_d = body.date_from, body.date_to
    _validate_range(from_d, to_d, max_days=92)  # quarter-year cap on a single bulk insert

    employee = (
        db.query(Employee)
        .filter(Employee.badge_number == body.employee_badge_number)
        .first()
    )
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee not found: {body.employee_badge_number}",
        )

    # Upsert each day in the range. Single round-trip to fetch existing
    # rows in one go, then per-day in Python.
    span = [from_d + timedelta(days=i) for i in range((to_d - from_d).days + 1)]
    existing_rows = (
        db.query(EmployeeLeave)
        .filter(
            EmployeeLeave.employee_badge_number == body.employee_badge_number,
            EmployeeLeave.date.in_(span),
        )
        .all()
    )
    existing_by_date = {r.date: r for r in existing_rows}

    written: list[EmployeeLeave] = []
    for d in span:
        row = existing_by_date.get(d)
        if row is None:
            row = EmployeeLeave(
                employee_badge_number=body.employee_badge_number,
                date=d,
                leave_type=body.leave_type,
                note=body.note,
            )
            db.add(row)
        else:
            row.leave_type = body.leave_type
            row.note = body.note
        written.append(row)

    db.commit()
    for row in written:
        db.refresh(row)
    return [_leave_to_dto(r) for r in written]


@router.delete(
    "/employee/{badge}/{on_date}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_employee_leave(
    badge: str,
    on_date: date_type,
    db: Session = Depends(get_db),
) -> Response:
    """Remove one leave row. Idempotent."""
    db.query(EmployeeLeave).filter(
        EmployeeLeave.employee_badge_number == badge,
        EmployeeLeave.date == on_date,
    ).delete()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Leave-type colors (admin-editable via the roster legend) -----------


class LeaveTypeOut(BaseModel):
    code: str
    name_th: str
    color: Optional[str] = None


class LeaveTypeColorUpdate(BaseModel):
    color: Optional[str] = None  # hex (#RRGGBB) or null/empty to reset


def _leave_type_to_dto(lt: LeaveType) -> LeaveTypeOut:
    return LeaveTypeOut(code=lt.code, name_th=lt.name_th, color=lt.color)


@router.get("/types", response_model=list[LeaveTypeOut])
def list_leave_types(db: Session = Depends(get_db)) -> list[LeaveTypeOut]:
    """List the 4 leave types with their current display colors.

    The shifts-admin "ตั้งค่าสีกะ" legend renders one color picker per
    type next to the shift-color pickers.
    """
    rows = db.query(LeaveType).order_by(LeaveType.code).all()
    return [_leave_type_to_dto(lt) for lt in rows]


@router.patch("/types/{code}/color", response_model=LeaveTypeOut)
def update_leave_type_color(
    code: str,
    body: LeaveTypeColorUpdate,
    db: Session = Depends(get_db),
) -> LeaveTypeOut:
    """Set the display color for one leave type. Mirrors the
    PATCH /api/private/shifts/{code}/color shape so the frontend can
    reuse the same debounced color-picker UI."""
    lt = db.query(LeaveType).filter(LeaveType.code == code).first()
    if lt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown leave type code: {code}",
        )

    new_color = body.color
    if new_color == "":
        new_color = None
    if new_color is not None and not _HEX_COLOR_RE.match(new_color):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="color must be a #RRGGBB hex string or null",
        )

    lt.color = new_color
    db.commit()
    db.refresh(lt)
    return _leave_type_to_dto(lt)
