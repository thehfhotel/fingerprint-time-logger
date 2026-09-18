from datetime import date
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.models import Employee, EmployeeLeave
from app.models.staff_leave import StaffLeaveRequest
from app.services import staff_leave as service
from app.services import staff_leave_options


def make_db(monkeypatch):
    staff_leave_options.install(service)
    monkeypatch.setattr(service, "today", lambda: date(2026, 9, 17))
    monkeypatch.setattr(service.staff_oa_service, "get_channel_secret", lambda: "test-secret")
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine)
    employee = Employee(
        badge_number="HALF-1", display_name="พนักงานครึ่งวัน", thai_name="พนักงานครึ่งวัน",
        department="ต้อนรับ", location="HF", line_user_id="Uhalf1",
        is_active=True, pending_approval=False,
    )
    db.add(employee)
    db.commit()
    return engine, db, employee


def test_day_off_is_a_distinct_type_and_direct_text_parses(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        assert service.TYPES["public_holiday"] == "ใช้วันหยุดนักขัตฤกษ์"
        assert service.parse_direct_request("แจ้งลา ใช้วันหยุด 18/9/2569") == (
            "public_holiday", date(2026, 9, 18), date(2026, 9, 18)
        )
        assert service.parse_direct_request("แจ้งลา นักขัตฤกษ์ 18/9/2569") == (
            "public_holiday", date(2026, 9, 18), date(2026, 9, 18)
        )
        row = service.submit(
            db, employee, uuid4().hex, "public_holiday", date(2026, 9, 18), date(2026, 9, 18)
        )
        approved = service.decide(db, row.id, "approved", row.version, "manager@example.invalid")
        assert approved.leave_type == "public_holiday"
        roster = db.query(EmployeeLeave).filter_by(employee_badge_number=employee.badge_number).one()
        assert roster.leave_type == "public_holiday"
    finally:
        db.close(); engine.dispose()


def test_line_typed_use_day_off_and_nakhattarue_both_file_public_holiday(monkeypatch):
    """Both the pre-existing day_off wording and the formal public-holiday
    wording map to the same merged public_holiday type, and the confirmation
    reply carries LINE's label (ใช้วันหยุดนักขัตฤกษ์), not the shorter admin
    board label."""
    engine, db, employee = make_db(monkeypatch)
    try:
        for text in ("แจ้งลา ใช้วันหยุด 18/9/2569", "แจ้งลา นักขัตฤกษ์ 18/9/2569"):
            event = {"type": "message", "message": {"type": "text", "text": text}}
            review = service._messages(event, db, employee)[0]
            assert "ใช้วันหยุดนักขัตฤกษ์" in review["text"]
            submit_action = review["quickReply"]["items"][0]["action"]
            submit_event = {"type": "postback", "postback": {"data": submit_action["data"]}}
            messages = service._messages(submit_event, db, employee)
            assert messages
            row = db.query(StaffLeaveRequest).filter_by(
                employee_badge_number=employee.badge_number
            ).order_by(StaffLeaveRequest.created_at.desc()).first()
            assert row.leave_type == "public_holiday"
            roster = db.query(EmployeeLeave).filter_by(
                employee_badge_number=employee.badge_number, date=date(2026, 9, 18),
            ).one()
            assert roster.leave_type == "public_holiday"
            db.query(EmployeeLeave).filter_by(
                employee_badge_number=employee.badge_number
            ).delete()
            db.query(StaffLeaveRequest).filter_by(
                employee_badge_number=employee.badge_number
            ).delete()
            db.commit()
    finally:
        db.close(); engine.dispose()


def test_half_day_direct_text_and_manual_approval_are_half_not_full(monkeypatch):
    """With the auto-record switch off, half-day requests still go through
    the original pending -> manager-decide path, with the half-day override
    (0.5 day, single EmployeeLeave row with the |half marker) intact."""
    monkeypatch.setenv("STAFF_LEAVE_AUTO_APPROVE", "false")
    engine, db, employee = make_db(monkeypatch)
    try:
        event = {
            "type": "message",
            "message": {"type": "text", "text": "แจ้งลา ลากิจ ครึ่งวันเช้า 18/9/2569"},
        }
        review = service._messages(event, db, employee)[0]
        assert "ลากิจ • ครึ่งวันเช้า" in review["text"]
        assert "0.5 วัน" in review["text"]
        submit_action = review["quickReply"]["items"][0]["action"]
        submit_event = {"type": "postback", "postback": {"data": submit_action["data"]}}
        messages = service._messages(submit_event, db, employee)
        assert messages
        row = db.query(StaffLeaveRequest).filter_by(
            employee_badge_number=employee.badge_number
        ).one()
        assert row.status == "pending" and row.reviewed_by is None
        assert row.leave_portion == "am"
        assert service.calendar_days(row) == 0.5

        approved = service.decide(db, row.id, "approved", row.version, "manager@example.invalid")
        assert approved.status == "approved"
        leave = db.query(EmployeeLeave).filter_by(employee_badge_number=employee.badge_number).one()
        assert leave.leave_type == "personal"
        assert leave.note.endswith("|half=am")
        assert staff_leave_options.portion_from_leave_note(leave.note) == "am"
    finally:
        db.close(); engine.dispose()


def test_half_day_auto_approve_records_immediately_with_half_marker(monkeypatch):
    """Auto-record (default, switch unset) applies to the half-day path too,
    through the SAME installed `decide` override — a single EmployeeLeave row
    with the |half marker, reviewer AUTO_REVIEWER, no manager step."""
    engine, db, employee = make_db(monkeypatch)
    try:
        event = {
            "type": "message",
            "message": {"type": "text", "text": "แจ้งลา ลากิจ ครึ่งวันบ่าย 18/9/2569"},
        }
        review = service._messages(event, db, employee)[0]
        submit_action = review["quickReply"]["items"][0]["action"]
        submit_event = {"type": "postback", "postback": {"data": submit_action["data"]}}
        messages = service._messages(submit_event, db, employee)
        assert messages
        row = db.query(StaffLeaveRequest).filter_by(
            employee_badge_number=employee.badge_number
        ).one()
        assert row.status == "approved" and row.reviewed_by == service.AUTO_REVIEWER
        assert row.leave_portion == "pm"
        leave = db.query(EmployeeLeave).filter_by(employee_badge_number=employee.badge_number).one()
        assert leave.leave_type == "personal"
        assert leave.note.endswith("|half=pm")
        assert staff_leave_options.portion_from_leave_note(leave.note) == "pm"
    finally:
        db.close(); engine.dispose()


def test_picker_offers_both_half_day_periods(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        first = service._messages(
            {"type": "message", "message": {"type": "text", "text": "แจ้งลา"}},
            db, employee,
        )[0]
        kinds = [item["action"]["label"] for item in first["quickReply"]["items"]]
        assert "ใช้วันหยุดนักขัตฤกษ์" in kinds
        personal = next(
            item["action"] for item in first["quickReply"]["items"]
            if item["action"]["label"] == "ลากิจ"
        )
        second = service._messages({
            "type": "postback",
            "postback": {"data": personal["data"], "params": {"date": "2026-09-18"}},
        }, db, employee)[0]
        labels = [item["action"]["label"] for item in second["quickReply"]["items"]]
        assert "ลาถึงวันที่" in labels
        assert "ลา 1 วัน" in labels
        assert "ครึ่งวันเช้า" in labels
        assert "ครึ่งวันบ่าย" in labels
    finally:
        db.close(); engine.dispose()


def test_half_day_constraint_requires_single_date(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        row = StaffLeaveRequest(
            id=uuid4().hex,
            employee_badge_number=employee.badge_number,
            employee_name=employee.display_name,
            leave_type="personal",
            leave_portion="pm",
            date_from=date(2026, 9, 18),
            date_to=date(2026, 9, 19),
            status="pending",
            version=1,
        )
        db.add(row)
        try:
            db.commit()
            assert False, "database should reject a multi-date half-day request"
        except Exception:
            db.rollback()
    finally:
        db.close(); engine.dispose()
