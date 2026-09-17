from datetime import date
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.models import Employee
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
        badge_number="UX-1", display_name="พนักงานทดสอบ", thai_name="พนักงานทดสอบ",
        department="ต้อนรับ", location="HF", line_user_id="Uux1",
        is_active=True, pending_approval=False,
    )
    db.add(employee)
    db.commit()
    return engine, db, employee


def add_leave(db, employee, kind, start, end, portion="full"):
    row = service.submit(db, employee, uuid4().hex, kind, start, end)
    row.leave_portion = portion
    db.commit()
    db.refresh(row)
    return row


def test_edit_selection_lists_multiple_leaves_without_visible_internal_ids(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        first = add_leave(
            db, employee, "vacation", date(2026, 9, 20), date(2026, 9, 22)
        )
        second = add_leave(
            db, employee, "personal", date(2026, 9, 25), date(2026, 9, 25), "am"
        )
        rows = manage._editable_rows(db, employee.badge_number)
        message = manage._selection_message(service, rows, "edit")

        assert "เลือกใบลาที่ต้องการแก้ไข" in message["text"]
        assert "ลาพักร้อน" in message["text"]
        assert "ลากิจ" in message["text"]
        assert "ครึ่งวันเช้า" in message["text"]
        assert first.id not in message["text"]
        assert second.id not in message["text"]
        assert "HF-LV-" not in message["text"]
        labels = [item["action"]["label"] for item in message["quickReply"]["items"]]
        assert labels == ["แก้ใบที่ 1", "แก้ใบที่ 2"]
        assert all(item["action"]["type"] == "postback" for item in message["quickReply"]["items"])
    finally:
        db.close()
        engine.dispose()


def test_cancel_selection_and_confirm_never_show_internal_id(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        row = add_leave(
            db, employee, "day_off", date(2026, 9, 21), date(2026, 9, 21), "pm"
        )
        selection = manage._selection_message(service, [row], "cancel")
        confirm = manage._cancel_confirm_message(service, row)

        assert "ใช้วันหยุด" in selection["text"]
        assert "ครึ่งวันบ่าย" in selection["text"]
        assert row.id not in selection["text"]
        assert row.id not in confirm["text"]
        assert "HF-LV-" not in selection["text"] + confirm["text"]
        assert selection["quickReply"]["items"][0]["action"]["label"] == "ยกเลิกใบที่ 1"
        assert confirm["quickReply"]["items"][0]["action"]["label"] == "ยืนยันยกเลิก"
    finally:
        db.close()
        engine.dispose()


def test_edit_form_and_review_use_human_details_not_reference(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        row = add_leave(
            db, employee, "personal", date(2026, 9, 18), date(2026, 9, 18)
        )
        start = manage._edit_start_message(service, row)
        review = manage._edit_review(
            service, row, "vacation", date(2026, 9, 19), date(2026, 9, 20),
            "full", row.version,
        )
        combined = start["text"] + review["text"]
        assert "HF-LV-" not in combined
        assert row.id not in combined
        assert "ลากิจ" in start["text"]
        assert "ลาพักร้อน" in review["text"]
    finally:
        db.close()
        engine.dispose()


def test_shareable_image_source_does_not_render_internal_reference():
    path = Path(__file__).resolve().parents[2] / "app/services/staff_leave_image.py"
    source = path.read_text(encoding="utf-8")
    assert "reference(row)" not in source
    assert "สร้างจาก HF ภายใน" in source
