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

from datetime import date as date_type, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee, EmployeeLeave, PublicHoliday


router = APIRouter()


# Allowed personal-leave types. 'public_holiday' lives in its own
# table (no badge) so it isn't in this set.
_ALLOWED_LEAVE_TYPES = ("vacation", "personal", "sick")


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
