"""The roster (EmployeeLeave) is the single source of truth every LINE leave
surface reads from — see app/services/staff_leave_roster.py and
docs/LEAVE_SYNC_SURFACES.md. No LINE HTTP calls anywhere in this file.
"""
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.models import Employee, EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest
from app.services import staff_leave, staff_leave_roster as roster


BADGE = "ROST-1"


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Employee(
            badge_number=BADGE, display_name="พนักงานตารางงาน", thai_name="พนักงานตารางงาน",
            department="ต้อนรับ", location="HF", is_active=True, pending_approval=False,
        ))
        session.commit()
        yield session


def make_request(db, *, status="pending", leave_type="vacation", portion="full",
                 date_from=date(2026, 9, 10), date_to=date(2026, 9, 12),
                 reviewed_by=None, created_at=None) -> StaffLeaveRequest:
    row = StaffLeaveRequest(
        id=uuid4().hex, employee_badge_number=BADGE, employee_name="พนักงานตารางงาน",
        leave_type=leave_type, leave_portion=portion,
        date_from=date_from, date_to=date_to, status=status, version=1,
        reviewed_by=reviewed_by,
    )
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_roster_row(db, on_date, leave_type, note):
    row = EmployeeLeave(employee_badge_number=BADGE, date=on_date, leave_type=leave_type, note=note)
    db.add(row)
    db.commit()
    return row


def add_day(db, request_id, on_date):
    db.add(StaffLeaveDay(employee_badge_number=BADGE, date=on_date, request_id=request_id))
    db.commit()


# --------------------------------------------------------------------------
# request_id_from_note
# --------------------------------------------------------------------------


def test_request_id_from_note_plain_reference():
    request_id = uuid4().hex
    note = f"HF-LV-{request_id.upper()}"
    assert roster.request_id_from_note(note) == request_id


def test_request_id_from_note_half_marker():
    request_id = uuid4().hex
    note = f"HF-LV-{request_id.upper()}|half=am"
    assert roster.request_id_from_note(note) == request_id


@pytest.mark.parametrize("note", [None, "", "หมายเหตุทั่วไปของแอดมิน", "|half=am"])
def test_request_id_from_note_admin_note_is_none(note):
    assert roster.request_id_from_note(note) is None


def test_request_id_from_note_junk_reference_resolves_to_no_request(db):
    note = "HF-LV-not-a-real-request-id"
    request_id = roster.request_id_from_note(note)
    assert request_id is not None
    # It parses structurally, but resolves to nothing real.
    assert db.get(StaffLeaveRequest, request_id) is None


# --------------------------------------------------------------------------
# effective_state
# --------------------------------------------------------------------------


def test_effective_state_pending(db):
    row = make_request(db, status="pending")
    effective = roster.effective_state(db, row)
    assert effective.status == "pending"
    assert effective.label == "รออนุมัติ"
    assert effective.dates == (date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12))
    assert effective.source == "line" and effective.request is row


def test_effective_state_rejected(db):
    row = make_request(db, status="rejected", leave_type="sick")
    effective = roster.effective_state(db, row)
    assert effective.status == "rejected"
    assert effective.label == "ไม่อนุมัติ"
    assert effective.dates == (date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12))


def test_effective_state_recorded_full_range(db):
    row = make_request(db, status="approved", reviewed_by=staff_leave.AUTO_REVIEWER)
    ref = staff_leave.reference(row)
    for d in (date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12)):
        add_roster_row(db, d, "vacation", ref)
    effective = roster.effective_state(db, row)
    assert effective.status == "recorded"
    assert effective.label == "บันทึกการลาแล้ว"
    assert effective.dates == (date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12))
    assert effective.date_from == date(2026, 9, 10) and effective.date_to == date(2026, 9, 12)


def test_effective_state_recorded_half_day(db):
    row = make_request(
        db, status="approved", leave_type="personal", portion="am",
        date_from=date(2026, 9, 15), date_to=date(2026, 9, 15),
        reviewed_by=staff_leave.AUTO_REVIEWER,
    )
    ref = staff_leave.reference(row)
    add_roster_row(db, date(2026, 9, 15), "personal", f"{ref}|half=am")
    effective = roster.effective_state(db, row)
    assert effective.status == "recorded"
    assert effective.dates == (date(2026, 9, 15),)
    assert effective.portion == "am"


def test_effective_state_partial(db):
    row = make_request(db, status="approved", reviewed_by=staff_leave.AUTO_REVIEWER)
    ref = staff_leave.reference(row)
    # The middle day (9/11) was removed by an admin — only 9/10 and 9/12 remain.
    add_roster_row(db, date(2026, 9, 10), "vacation", ref)
    add_roster_row(db, date(2026, 9, 12), "vacation", ref)
    effective = roster.effective_state(db, row)
    assert effective.status == "partial"
    assert effective.label == "บันทึกการลาแล้ว (ปรับจากตารางงาน)"
    assert effective.dates == (date(2026, 9, 10), date(2026, 9, 12))


def test_effective_state_cancelled_roster_via_approved_with_no_rows(db):
    row = make_request(db, status="approved", reviewed_by=staff_leave.AUTO_REVIEWER)
    effective = roster.effective_state(db, row)
    assert effective.status == "cancelled_roster"
    assert effective.label == "ยกเลิกแล้ว (ปรับจากตารางงาน)"
    assert effective.dates == () and effective.date_from is None and effective.date_to is None


def test_effective_state_cancelled_by_employee(db):
    row = make_request(db, status="cancelled", reviewed_by=staff_leave.AUTO_REVIEWER)
    effective = roster.effective_state(db, row)
    assert effective.status == "cancelled"
    assert effective.label == "ยกเลิกแล้ว"


def test_effective_state_cancelled_roster_via_cancelled_status(db):
    row = make_request(db, status="cancelled", reviewed_by=roster.ROSTER_ADMIN_REVIEWER)
    effective = roster.effective_state(db, row)
    assert effective.status == "cancelled_roster"
    assert effective.label == "ยกเลิกแล้ว (ปรับจากตารางงาน)"


# --------------------------------------------------------------------------
# latest_effective_leave
# --------------------------------------------------------------------------


def test_latest_effective_leave_none_when_nothing_exists(db):
    assert roster.latest_effective_leave(db, BADGE) is None


def test_latest_effective_leave_picks_the_request_when_it_is_newer(db):
    row = make_request(
        db, status="approved", reviewed_by=staff_leave.AUTO_REVIEWER,
        created_at=datetime(2026, 9, 15, 10, 0, 0),
    )
    add_roster_row(db, date(2026, 9, 10), "vacation", staff_leave.reference(row))
    # An older admin run — the request is still the newer thing.
    add_roster_row(db, date(2026, 9, 1), "sick", None)

    effective = roster.latest_effective_leave(db, BADGE)
    assert effective.source == "line"
    assert effective.request.id == row.id


def test_latest_effective_leave_picks_the_admin_run_when_it_is_newer(db):
    row = make_request(
        db, status="approved", reviewed_by=staff_leave.AUTO_REVIEWER,
        created_at=datetime(2026, 9, 1, 10, 0, 0),
    )
    add_roster_row(db, date(2026, 9, 1), "vacation", staff_leave.reference(row))
    # A later admin-added run of 2 contiguous days, newer than the request.
    add_roster_row(db, date(2026, 9, 20), "sick", None)
    add_roster_row(db, date(2026, 9, 21), "sick", None)

    effective = roster.latest_effective_leave(db, BADGE)
    assert effective.source == "roster"
    assert effective.request is None
    assert effective.status == "recorded"
    assert effective.dates == (date(2026, 9, 20), date(2026, 9, 21))
    assert effective.leave_type == "sick"


def test_latest_effective_leave_admin_run_groups_by_contiguous_same_type(db):
    # Two separate runs of admin rows: an older 1-day "sick" run and a newer
    # 1-day "vacation" run one week later (not contiguous with the first).
    add_roster_row(db, date(2026, 9, 1), "sick", None)
    add_roster_row(db, date(2026, 9, 8), "vacation", None)

    effective = roster.latest_effective_leave(db, BADGE)
    assert effective.source == "roster"
    assert effective.dates == (date(2026, 9, 8),)
    assert effective.leave_type == "vacation"


# --------------------------------------------------------------------------
# release_request_days / on_roster_leave_removed
# --------------------------------------------------------------------------


def test_release_request_days_deletes_without_commit(db):
    row = make_request(db, status="pending")
    for d in (date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12)):
        add_day(db, row.id, d)
    assert roster.release_request_days(db, row) == 3
    assert db.query(StaffLeaveDay).filter_by(request_id=row.id).count() == 0


def test_on_roster_leave_removed_ignores_admin_notes(db):
    assert roster.on_roster_leave_removed(db, BADGE, date(2026, 9, 10), None) is None
    assert roster.on_roster_leave_removed(db, BADGE, date(2026, 9, 10), "หมายเหตุทั่วไป") is None


def test_on_roster_leave_removed_ignores_unknown_reference(db):
    assert roster.on_roster_leave_removed(db, BADGE, date(2026, 9, 10), "HF-LV-doesnotexist") is None


def test_on_roster_leave_removed_releases_the_day_only(db):
    row = make_request(db, status="approved", reviewed_by=staff_leave.AUTO_REVIEWER)
    ref = staff_leave.reference(row)
    for d in (date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12)):
        add_day(db, row.id, d)
    add_roster_row(db, date(2026, 9, 10), "vacation", ref)
    add_roster_row(db, date(2026, 9, 12), "vacation", ref)
    # 9/11's EmployeeLeave row was already removed by the caller; tell the
    # roster sync module about it.
    result = roster.on_roster_leave_removed(db, BADGE, date(2026, 9, 11), ref)

    assert result.id == row.id
    db.refresh(row)
    assert row.status == "approved"
    assert db.query(StaffLeaveDay).filter_by(
        request_id=row.id, date=date(2026, 9, 11)
    ).count() == 0
    assert db.query(StaffLeaveDay).filter_by(request_id=row.id).count() == 2


def test_on_roster_leave_removed_cancels_only_when_last_row_gone(db):
    row = make_request(
        db, status="approved", date_from=date(2026, 9, 10), date_to=date(2026, 9, 10),
        reviewed_by=staff_leave.AUTO_REVIEWER,
    )
    ref = staff_leave.reference(row)
    add_day(db, row.id, date(2026, 9, 10))
    # No EmployeeLeave row is added — it was already deleted by the caller.

    result = roster.on_roster_leave_removed(db, BADGE, date(2026, 9, 10), ref)

    assert result.status == "cancelled"
    assert result.reviewed_by == roster.ROSTER_ADMIN_REVIEWER
    assert result.version == 2
    assert result.medical_certificate is None
    assert db.query(StaffLeaveDay).filter_by(request_id=row.id).count() == 0


def test_on_roster_leave_removed_is_idempotent(db):
    row = make_request(
        db, status="approved", date_from=date(2026, 9, 10), date_to=date(2026, 9, 10),
        reviewed_by=staff_leave.AUTO_REVIEWER,
    )
    ref = staff_leave.reference(row)
    add_day(db, row.id, date(2026, 9, 10))

    first = roster.on_roster_leave_removed(db, BADGE, date(2026, 9, 10), ref)
    assert first.status == "cancelled" and first.version == 2

    second = roster.on_roster_leave_removed(db, BADGE, date(2026, 9, 10), ref)
    assert second.id == row.id
    assert second.status == "cancelled" and second.version == 2
    assert db.query(StaffLeaveDay).filter_by(request_id=row.id).count() == 0
