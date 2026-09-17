"""The roster (``EmployeeLeave``) is the single source of truth for every
LINE leave surface. A ``StaffLeaveRequest`` records how a leave was filed;
what LINE actually SHOWS about it is always recomputed from the roster rows
that currently exist for that request's reference, never trusted from
``StaffLeaveRequest.status`` alone. An admin editing/removing roster rows on
`/v2/shifts-admin` is therefore immediately reflected on every LINE surface,
and this module is the only place that reconciles the two.

A LINE-filed roster row's ``EmployeeLeave.note`` is either exactly
``reference(row)`` ("HF-LV-<ID>") or that reference plus a half-day marker
("HF-LV-<ID>|half=am"). An admin-added roster row carries no such reference.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import or_

from app.models.models import EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest
from app.services import staff_leave
from app.services.staff_leave_options import portion_from_leave_note

# Audit marker recorded on ``reviewed_by`` when the ROSTER — not a LINE
# confirmation or a manager decision — is what ended a request (every
# roster row it created was deleted/reassigned on shifts-admin). Never
# shown to an employee and never a LINE id or a name.
ROSTER_ADMIN_REVIEWER = "admin:shifts-admin"

EFFECTIVE_LABELS = {
    "pending": "รออนุมัติ",
    "recorded": "บันทึกการลาแล้ว",
    "partial": "บันทึกการลาแล้ว (ปรับจากตารางงาน)",
    "cancelled": "ยกเลิกแล้ว",
    "cancelled_roster": "ยกเลิกแล้ว (ปรับจากตารางงาน)",
    "rejected": "ไม่อนุมัติ",
}

_REF_RE = re.compile(r"^HF-LV-([^|]+)")


@dataclass(frozen=True)
class EffectiveLeave:
    """What a LINE surface should actually show for one leave, recomputed
    from the roster rather than trusted from ``StaffLeaveRequest.status``."""

    status: str
    dates: tuple[date, ...]
    date_from: date | None
    date_to: date | None
    leave_type: str
    portion: str
    source: str  # "line" (backed by a StaffLeaveRequest) | "roster" (admin-added run)
    request: StaffLeaveRequest | None

    @property
    def label(self) -> str:
        return EFFECTIVE_LABELS[self.status]


def _span(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def request_id_from_note(note: str | None) -> str | None:
    """Parse "HF-LV-<ID>" or "HF-LV-<ID>|half=am" -> the lowercase id form
    used by ``StaffLeaveRequest.id``. ``None`` for an admin note (no
    reference at all). A malformed/unknown reference still parses to
    *some* id string here — the caller must look it up and handle a miss;
    this function only reads the note's shape."""
    if not note:
        return None
    match = _REF_RE.match(note)
    if not match:
        return None
    return match.group(1).lower()


def roster_rows_for_request(db, row: StaffLeaveRequest) -> list[EmployeeLeave]:
    """Roster rows currently linked to ``row``: note == reference(row), or
    that reference plus a half-day marker. Ordered by date."""
    ref = staff_leave.reference(row)
    return (
        db.query(EmployeeLeave)
        .filter(
            EmployeeLeave.employee_badge_number == row.employee_badge_number,
            or_(EmployeeLeave.note == ref, EmployeeLeave.note.like(f"{ref}|%")),
        )
        .order_by(EmployeeLeave.date)
        .all()
    )


def effective_state(db, row: StaffLeaveRequest) -> EffectiveLeave:
    """What a LINE surface should show right now for ``row``, recomputed
    against the roster instead of trusting ``row.status`` alone."""
    if row.status in ("pending", "rejected"):
        dates = tuple(_span(row.date_from, row.date_to))
        return EffectiveLeave(
            status=row.status, dates=dates, date_from=row.date_from, date_to=row.date_to,
            leave_type=row.leave_type, portion=row.leave_portion,
            source="line", request=row,
        )
    if row.status == "cancelled":
        status = "cancelled_roster" if row.reviewed_by == ROSTER_ADMIN_REVIEWER else "cancelled"
        return EffectiveLeave(
            status=status, dates=(), date_from=None, date_to=None,
            leave_type=row.leave_type, portion=row.leave_portion,
            source="line", request=row,
        )
    # status == "approved": the roster is the only source of truth for what
    # actually happened; a manager rejecting via a route that never touches
    # ``status`` cannot occur, so this is the only remaining branch.
    rows = roster_rows_for_request(db, row)
    if not rows:
        return EffectiveLeave(
            status="cancelled_roster", dates=(), date_from=None, date_to=None,
            leave_type=row.leave_type, portion=row.leave_portion,
            source="line", request=row,
        )
    row_dates = tuple(sorted(r.date for r in rows))
    full_range = tuple(_span(row.date_from, row.date_to))
    status = "recorded" if row_dates == full_range else "partial"
    return EffectiveLeave(
        status=status, dates=row_dates, date_from=row_dates[0], date_to=row_dates[-1],
        leave_type=rows[0].leave_type, portion=portion_from_leave_note(rows[0].note),
        source="line", request=row,
    )


def _newest_admin_run(rows: list[EmployeeLeave]) -> list[EmployeeLeave] | None:
    """``rows`` is every admin-added (no LINE reference) EmployeeLeave row
    for one badge, already sorted by date. Group contiguous same-type runs
    and return the run whose max date is latest, or ``None``."""
    if not rows:
        return None
    runs: list[list[EmployeeLeave]] = []
    current = [rows[0]]
    for prev, cur in zip(rows, rows[1:]):
        if cur.leave_type == prev.leave_type and (cur.date - prev.date).days == 1:
            current.append(cur)
        else:
            runs.append(current)
            current = [cur]
    runs.append(current)
    return max(runs, key=lambda run: run[-1].date)


def latest_effective_leave(db, badge: str) -> EffectiveLeave | None:
    """The most recent leave the ROSTER knows about for ``badge``: the
    newest ``StaffLeaveRequest`` (by ``created_at``) versus the newest
    admin-added ``EmployeeLeave`` run (rows with no LINE reference, grouped
    into contiguous same-type runs; "newest" = the run's max date)."""
    request = (
        db.query(StaffLeaveRequest)
        .filter(StaffLeaveRequest.employee_badge_number == badge)
        .order_by(StaffLeaveRequest.created_at.desc(), StaffLeaveRequest.id.desc())
        .first()
    )
    admin_rows = [
        r for r in (
            db.query(EmployeeLeave)
            .filter(EmployeeLeave.employee_badge_number == badge)
            .order_by(EmployeeLeave.date)
            .all()
        )
        if request_id_from_note(r.note) is None
    ]
    admin_run = _newest_admin_run(admin_rows)

    if admin_run is not None and (
        request is None or admin_run[-1].date > request.created_at.date()
    ):
        dates = tuple(r.date for r in admin_run)
        return EffectiveLeave(
            status="recorded", dates=dates, date_from=dates[0], date_to=dates[-1],
            leave_type=admin_run[0].leave_type,
            portion=portion_from_leave_note(admin_run[0].note),
            source="roster", request=None,
        )
    if request is not None:
        return effective_state(db, request)
    return None


def release_request_days(db, row: StaffLeaveRequest) -> int:
    """Delete every ``StaffLeaveDay`` row reserved for ``row``. Returns the
    number of rows deleted. Does not commit."""
    return (
        db.query(StaffLeaveDay)
        .filter(StaffLeaveDay.request_id == row.id)
        .delete(synchronize_session=False)
    )


def on_roster_leave_removed(db, badge: str, on_date: date, note: str | None) -> StaffLeaveRequest | None:
    """Called by the leaves API, in the same transaction and before commit,
    right after a roster row for (``badge``, ``on_date``) was deleted or had
    its note overwritten away from ``note`` (the row's OLD note).

    If ``note`` references an existing ``StaffLeaveRequest`` for ``badge``,
    releases that date's ``StaffLeaveDay`` reservation so the employee can
    re-file it. If that was the request's last remaining roster row and it
    was still "approved", the roster itself is what ended the leave: marks
    it "cancelled" with ``ROSTER_ADMIN_REVIEWER``, clears the medical
    certificate, and releases any remaining ``StaffLeaveDay`` rows.

    Never raises for an admin note or a reference that resolves to no
    request; idempotent when called again after the request is already
    cancelled.
    """
    request_id = request_id_from_note(note)
    if request_id is None:
        return None
    db.flush()  # make any pending roster row change visible to our own reads below
    row = db.get(StaffLeaveRequest, request_id)
    if row is None or row.employee_badge_number != badge:
        return None
    db.query(StaffLeaveDay).filter(
        StaffLeaveDay.request_id == row.id, StaffLeaveDay.date == on_date,
    ).delete(synchronize_session=False)
    if row.status == "approved" and not roster_rows_for_request(db, row):
        now = datetime.utcnow()
        row.status = "cancelled"
        row.reviewed_by = ROSTER_ADMIN_REVIEWER
        row.reviewed_at = now
        row.version += 1
        row.medical_certificate = None
        row.medical_certificate_content_type = None
        row.updated_at = now
        release_request_days(db, row)
    return row
