from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.models import Employee, EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest
from app.services import staff_leave as service
from app.services import staff_leave_manage as manage
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
        badge_number="EDIT-1", display_name="พนักงานแก้ไข", thai_name="พนักงานแก้ไข",
        department="ต้อนรับ", location="HF", line_user_id="Uedit1",
        is_active=True, pending_approval=False,
    )
    db.add(employee)
    db.commit()
    return engine, db, employee


def test_pending_wording_is_hidden_from_employee_copy():
    text = "หลังส่งจะบันทึกในระบบพนักงานเป็นสถานะ รออนุมัติ"
    cleaned = manage._sanitize_text(text)
    assert "รออนุมัติ" not in cleaned
    assert "บันทึกใบลาในระบบพนักงานทันที" in cleaned


def test_edit_request_keeps_reference_and_replaces_reservations(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        row = service.submit(
            db, employee, uuid4().hex, "personal",
            date(2026, 9, 18), date(2026, 9, 19),
        )
        request_id = row.id
        old_version = row.version

        updated = manage._edit_request(
            service, db, employee, request_id, old_version,
            "day_off", date(2026, 9, 20), date(2026, 9, 20), "pm",
        )
        assert updated.id == request_id
        assert updated.version == old_version + 1
        assert updated.leave_type == "day_off"
        assert updated.leave_portion == "pm"
        assert updated.date_from == updated.date_to == date(2026, 9, 20)
        days = db.query(StaffLeaveDay).filter_by(request_id=request_id).all()
        assert [item.date for item in days] == [date(2026, 9, 20)]

        # LINE retry of the same signed confirmation is idempotent.
        replay = manage._edit_request(
            service, db, employee, request_id, old_version,
            "day_off", date(2026, 9, 20), date(2026, 9, 20), "pm",
        )
        assert replay.version == old_version + 1
    finally:
        db.close(); engine.dispose()


def test_edit_conflict_rolls_back_original_request_and_days(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        first = service.submit(
            db, employee, uuid4().hex, "personal",
            date(2026, 9, 18), date(2026, 9, 18),
        )
        second = service.submit(
            db, employee, uuid4().hex, "vacation",
            date(2026, 9, 20), date(2026, 9, 20),
        )
        with pytest.raises(service.LeaveError):
            manage._edit_request(
                service, db, employee, first.id, first.version,
                "personal", date(2026, 9, 20), date(2026, 9, 20), "full",
            )
        db.expire_all()
        restored = db.get(StaffLeaveRequest, first.id)
        assert restored.date_from == restored.date_to == date(2026, 9, 18)
        assert restored.version == 1
        assert db.query(StaffLeaveDay).filter_by(request_id=first.id).one().date == date(2026, 9, 18)
        assert db.query(StaffLeaveDay).filter_by(request_id=second.id).one().date == date(2026, 9, 20)
    finally:
        db.close(); engine.dispose()


def test_reviewed_request_cannot_be_edited(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        row = service.submit(
            db, employee, uuid4().hex, "personal",
            date(2026, 9, 18), date(2026, 9, 18),
        )
        service.decide(db, row.id, "rejected", row.version, "manager@example.invalid")
        with pytest.raises(service.LeaveError, match="ถูกตรวจหรือเปลี่ยนแปลง"):
            manage._edit_request(
                service, db, employee, row.id, 1,
                "vacation", date(2026, 9, 19), date(2026, 9, 19), "full",
            )
    finally:
        db.close(); engine.dispose()


def test_cancel_picker_offers_and_cancels_auto_recorded_request_via_handle_event(
    monkeypatch,
):
    engine, db, employee = make_db(monkeypatch)
    try:
        manage.install(service)
        replies = []
        monkeypatch.setattr(
            service, "_reply", lambda token, messages: replies.append(messages)
        )
        badge = employee.badge_number

        # Unrelated pre-existing leave on another date must survive.
        other = service.submit(
            db, employee, uuid4().hex, "vacation",
            date(2026, 9, 25), date(2026, 9, 25),
        )
        other = service._maybe_auto_approve(db, other)
        assert other.status == "approved"

        row = service.submit(
            db, employee, uuid4().hex, "personal",
            date(2026, 9, 18), date(2026, 9, 19),
        )
        row = service._maybe_auto_approve(db, row)
        assert row.status == "approved" and row.reviewed_by == service.AUTO_REVIEWER

        picker = service._messages(
            {"type": "message", "message": {"type": "text", "text": "ยกเลิกใบลา"}},
            db, employee,
        )[0]
        labels = [item["action"]["label"] for item in picker["quickReply"]["items"]]
        assert "ยกเลิกใบที่ 1" in labels
        pick_data = picker["quickReply"]["items"][0]["action"]["data"]

        pick_event = {
            "replyToken": "rt-pick", "type": "postback",
            "source": {"type": "user", "userId": "Uedit1"},
            "postback": {"data": pick_data},
        }
        service.handle_event(pick_event, db)
        confirm = replies[-1][0]
        confirm_data = confirm["quickReply"]["items"][0]["action"]["data"]

        confirm_event = {
            "replyToken": "rt-confirm", "type": "postback",
            "source": {"type": "user", "userId": "Uedit1"},
            "postback": {"data": confirm_data},
        }
        service.handle_event(confirm_event, db)

        db.expire_all()
        refreshed = db.get(StaffLeaveRequest, row.id)
        assert refreshed.status == "cancelled"
        assert "ยกเลิกแล้ว" in replies[-1][0]["text"]

        remaining_dates = {
            item.date for item in
            db.query(EmployeeLeave).filter_by(employee_badge_number=badge).all()
        }
        assert remaining_dates == {date(2026, 9, 25)}
    finally:
        db.close(); engine.dispose()


def test_edit_picker_excludes_auto_recorded_request(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        manage.install(service)
        row = service.submit(
            db, employee, uuid4().hex, "personal",
            date(2026, 9, 18), date(2026, 9, 19),
        )
        row = service._maybe_auto_approve(db, row)
        assert row.status == "approved"

        result = service._messages(
            {"type": "message", "message": {"type": "text", "text": "แก้ไขใบลา"}},
            db, employee,
        )
        assert result == [service._text("ไม่มีใบลาที่แก้ไขได้")]
    finally:
        db.close(); engine.dispose()


def test_manager_approved_request_excluded_from_cancel_picker_and_cancel_v(
    monkeypatch,
):
    engine, db, employee = make_db(monkeypatch)
    try:
        manage.install(service)
        row = service.submit(
            db, employee, uuid4().hex, "personal",
            date(2026, 9, 18), date(2026, 9, 19),
        )
        row = service.decide(db, row.id, "approved", row.version, "manager@example.invalid")
        assert row.status == "approved" and row.reviewed_by == "manager@example.invalid"

        picker = service._messages(
            {"type": "message", "message": {"type": "text", "text": "ยกเลิกใบลา"}},
            db, employee,
        )
        assert picker == [service._text("ไม่มีใบลาที่ยกเลิกได้")]

        data = service.action_data(f"cancel_v{row.version}", employee.badge_number, row.id)
        with pytest.raises(service.LeaveError, match="เปลี่ยนแปลงแล้ว"):
            service._messages(
                {"type": "postback", "postback": {"data": data}}, db, employee,
            )
    finally:
        db.close(); engine.dispose()
