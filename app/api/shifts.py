"""
Shift admin API.

Endpoints (all mounted under /api/private/shifts/* by main_unified):

  GET    /                       — list active shifts
  GET    /assignments            — per-day overrides for a date range
  PUT    /assignments/{badge}/{date}
                                 — set or clear one per-day override
  DELETE /assignments/{badge}/{date}
                                 — same as PUT with {"shift_code": null}

Employee role + default shift live alongside the existing employee
endpoints — see consolidated_employees.py for those changes.

Auth: these routes go on the protected root app, gated by Cloudflare
Access just like the rest of /api/private/*.
"""

from __future__ import annotations

from datetime import date as date_type, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee, Shift, ShiftAssignment


router = APIRouter()


# --- Schemas -------------------------------------------------------------


class ShiftOut(BaseModel):
    """Compact shift dto, matching the shape /by-date embeds in each row."""
    id: int
    code: str
    name_th: str
    start_time: str  # HH:MM
    end_time: str    # HH:MM
    crosses_midnight: bool
    is_active: bool


class AssignmentOut(BaseModel):
    """One per-day override row."""
    employee_badge_number: str
    date: date_type
    shift_code: Optional[str] = None  # None = scheduled off


class AssignmentIn(BaseModel):
    """Body for PUT /assignments/{badge}/{date}. shift_code=None means off."""
    shift_code: Optional[str] = Field(
        default=None,
        description="Shift code (NORMAL, MORNING, MID, AFTERNOON, NIGHT) "
                    "or null for 'scheduled off'.",
    )


# --- Helpers -------------------------------------------------------------


def _shift_to_dto(s: Shift) -> ShiftOut:
    return ShiftOut(
        id=s.id,
        code=s.code,
        name_th=s.name_th,
        start_time=s.start_time.strftime("%H:%M"),
        end_time=s.end_time.strftime("%H:%M"),
        crosses_midnight=s.crosses_midnight,
        is_active=s.is_active,
    )


def _assignment_to_dto(a: ShiftAssignment) -> AssignmentOut:
    return AssignmentOut(
        employee_badge_number=a.employee_badge_number,
        date=a.date,
        shift_code=a.shift.code if a.shift else None,
    )


# --- Routes --------------------------------------------------------------


@router.get("/", response_model=list[ShiftOut])
def list_shifts(db: Session = Depends(get_db)) -> list[ShiftOut]:
    """List active shifts. Sorted by start_time for stable UI rendering."""
    rows = (
        db.query(Shift)
        .filter(Shift.is_active == True)  # noqa: E712
        .order_by(Shift.start_time)
        .all()
    )
    return [_shift_to_dto(s) for s in rows]


@router.get("/assignments", response_model=list[AssignmentOut])
def list_assignments(
    from_date: date_type = Query(..., alias="from"),
    to_date: date_type = Query(..., alias="to"),
    db: Session = Depends(get_db),
) -> list[AssignmentOut]:
    """Per-day overrides in [from, to] (inclusive on both ends).

    Capped at 31 days to keep the admin roster page responses small.
    Callers wanting a longer window can paginate.
    """
    if to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'to' must be on or after 'from'",
        )
    if (to_date - from_date).days > 31:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date range exceeds 31 days",
        )

    rows = (
        db.query(ShiftAssignment)
        .filter(
            ShiftAssignment.date >= from_date,
            ShiftAssignment.date <= to_date,
        )
        .order_by(ShiftAssignment.date, ShiftAssignment.employee_badge_number)
        .all()
    )
    return [_assignment_to_dto(a) for a in rows]


def _resolve_shift_code(db: Session, code: Optional[str]) -> Optional[Shift]:
    """Look up a shift by code, raising 400 for unknown codes."""
    if code is None:
        return None
    s = db.query(Shift).filter(Shift.code == code).first()
    if s is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown shift_code: {code}",
        )
    return s


@router.put("/assignments/{badge}/{on_date}", response_model=AssignmentOut)
def put_assignment(
    badge: str,
    on_date: date_type,
    body: AssignmentIn,
    db: Session = Depends(get_db),
) -> AssignmentOut:
    """Create or update one per-day override.

    Idempotent: replays with the same body produce the same row. To
    remove an override entirely (revert to default/role), call
    DELETE /assignments/{badge}/{on_date}.
    """
    emp = (
        db.query(Employee)
        .filter(Employee.badge_number == badge)
        .first()
    )
    if emp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee not found: {badge}",
        )

    shift = _resolve_shift_code(db, body.shift_code)

    existing = (
        db.query(ShiftAssignment)
        .filter(
            ShiftAssignment.employee_badge_number == badge,
            ShiftAssignment.date == on_date,
        )
        .first()
    )
    if existing is None:
        existing = ShiftAssignment(
            employee_badge_number=badge,
            date=on_date,
            shift_id=shift.id if shift else None,
        )
        db.add(existing)
    else:
        existing.shift_id = shift.id if shift else None
        existing.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(existing)
    return _assignment_to_dto(existing)


@router.delete(
    "/assignments/{badge}/{on_date}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_assignment(
    badge: str,
    on_date: date_type,
    db: Session = Depends(get_db),
) -> Response:
    """Remove a per-day override (employee falls back to default / role).

    Returns 204 whether or not a row existed — idempotent.
    """
    db.query(ShiftAssignment).filter(
        ShiftAssignment.employee_badge_number == badge,
        ShiftAssignment.date == on_date,
    ).delete()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
