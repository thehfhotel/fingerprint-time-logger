from datetime import date
from io import BytesIO
from uuid import uuid4

from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.models import Employee, EmployeeLeave
from app.models.staff_leave import StaffLeaveRequest
from app.services import staff_leave as service
from app.services import staff_leave_palette


def make_db(monkeypatch):
    monkeypatch.setattr(service, "today", lambda: date(2026, 9, 16))
    monkeypatch.setattr(service.staff_oa_service, "get_channel_secret", lambda: "test-secret")
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    db = Session(engine)
    employee = Employee(
        badge_number="MED-1", display_name="พนักงานทดสอบ", thai_name="พนักงานทดสอบ",
        department="ต้อนรับ", location="HF", line_user_id="Umed1",
        is_active=True, pending_approval=False,
    )
    db.add(employee)
    db.commit()
    return engine, db, employee


def test_direct_thai_leave_examples(monkeypatch):
    monkeypatch.setattr(service, "today", lambda: date(2026, 9, 16))
    assert service.parse_direct_request("แจ้งลา พักร้อน 17-20/9/2569") == (
        "vacation", date(2026, 9, 17), date(2026, 9, 20))
    assert service.parse_direct_request("แจ้งลา พักร้อน 17/9/2569") == (
        "vacation", date(2026, 9, 17), date(2026, 9, 17))
    assert service.parse_direct_request("แจ้งลา ลาป่วย 18/9/2569") == (
        "sick", date(2026, 9, 18), date(2026, 9, 18))


def test_sick_more_than_three_days_requires_certificate(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        row = service.submit(db, employee, uuid4().hex, "sick",
                             date(2026, 9, 17), date(2026, 9, 20))
        assert service.medical_certificate_required(row)
        try:
            service.decide(db, row.id, "approved", row.version, "manager@example.invalid")
            assert False, "approval should require medical certificate"
        except service.LeaveError as exc:
            assert "ใบรับรองแพทย์" in str(exc)
        content = b"normalized-medical-image"
        row = service.attach_medical_certificate(
            db, row, content, "image/jpeg", service.hashlib.sha256(content).hexdigest())
        assert row.medical_certificate == content
        approved = service.decide(db, row.id, "approved", row.version,
                                  "manager@example.invalid")
        assert approved.status == "approved"
    finally:
        db.close(); engine.dispose()


def test_sick_three_days_certificate_optional(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        row = service.submit(db, employee, uuid4().hex, "sick",
                             date(2026, 9, 17), date(2026, 9, 19))
        assert not service.medical_certificate_required(row)
        assert service.decide(db, row.id, "approved", row.version,
                              "manager@example.invalid").status == "approved"
    finally:
        db.close(); engine.dispose()


def test_medical_image_is_normalized(monkeypatch):
    image = Image.new("RGB", (900, 1200), "white")
    raw = BytesIO(); image.save(raw, format="PNG")
    class Response:
        status_code = 200
        content = raw.getvalue()
    monkeypatch.setattr(service.requests, "get", lambda *a, **k: Response())
    monkeypatch.setattr(service.staff_oa_service, "get_channel_access_token", lambda: "token")
    content, content_type, digest = service._download_medical_certificate("123")
    assert content.startswith(b"\xff\xd8")
    assert content_type == "image/jpeg"
    assert digest == service.hashlib.sha256(content).hexdigest()


def test_certificate_arrival_records_sick_leave_over_threshold(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        replies = []
        monkeypatch.setattr(
            service, "_reply", lambda token, messages: replies.append(messages)
        )
        badge = employee.badge_number
        request_id = uuid4().hex
        start, end = date(2026, 9, 17), date(2026, 9, 21)  # 5 calendar days
        data = service.action_data(
            "submit", badge, request_id, "sick", start.isoformat(), end.isoformat(),
        )
        submit_event = {
            "replyToken": "rt-submit", "type": "postback",
            "source": {"type": "user", "userId": "Umed1"},
            "postback": {"data": data},
        }
        service.handle_event(submit_event, db)
        row = db.get(StaffLeaveRequest, request_id)
        assert row.status == "pending"
        assert "ต้องแนบรูปใบรับรองแพทย์ก่อนอนุมัติ" in replies[-1][0]["text"]

        image = Image.new("RGB", (900, 1200), "white")
        raw = BytesIO(); image.save(raw, format="PNG")

        class Response:
            status_code = 200
            content = raw.getvalue()

        monkeypatch.setattr(service.requests, "get", lambda *a, **k: Response())
        monkeypatch.setattr(service.staff_oa_service, "get_channel_access_token", lambda: "token")
        image_event = {
            "replyToken": "rt-cert", "type": "message",
            "source": {"type": "user", "userId": "Umed1"},
            "message": {"type": "image", "id": "img-1"},
        }
        service.handle_event(image_event, db)

        db.expire_all()
        refreshed = db.get(StaffLeaveRequest, request_id)
        assert refreshed.status == "approved"
        assert refreshed.reviewed_by == service.AUTO_REVIEWER
        leave_days = db.query(EmployeeLeave).filter_by(employee_badge_number=badge).all()
        assert len(leave_days) == 5
        # messages[0] is the "certificate attached" line; messages[1] is the
        # receipt text, whose heading reflects the now-approved status.
        assert "บันทึกการลาแล้ว" in replies[-1][1]["text"]
    finally:
        db.close(); engine.dispose()


def test_certificate_arrival_stays_pending_when_auto_approve_disabled(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        monkeypatch.setenv("STAFF_LEAVE_AUTO_APPROVE", "false")
        replies = []
        monkeypatch.setattr(
            service, "_reply", lambda token, messages: replies.append(messages)
        )
        row = service.submit(
            db, employee, uuid4().hex, "sick", date(2026, 9, 17), date(2026, 9, 21),
        )
        assert row.status == "pending"

        image = Image.new("RGB", (900, 1200), "white")
        raw = BytesIO(); image.save(raw, format="PNG")

        class Response:
            status_code = 200
            content = raw.getvalue()

        monkeypatch.setattr(service.requests, "get", lambda *a, **k: Response())
        monkeypatch.setattr(service.staff_oa_service, "get_channel_access_token", lambda: "token")
        image_event = {
            "replyToken": "rt-cert", "type": "message",
            "source": {"type": "user", "userId": "Umed1"},
            "message": {"type": "image", "id": "img-2"},
        }
        service.handle_event(image_event, db)

        db.expire_all()
        refreshed = db.get(StaffLeaveRequest, row.id)
        assert refreshed.status == "pending"
        assert refreshed.medical_certificate is not None
        assert db.query(EmployeeLeave).filter_by(
            employee_badge_number=employee.badge_number
        ).count() == 0
    finally:
        db.close(); engine.dispose()


def test_picker_uses_leave_until_label(monkeypatch):
    engine, db, employee = make_db(monkeypatch)
    try:
        first = service._messages({"type":"message","message":{"type":"text","text":"แจ้งลา"}}, db, employee)[0]
        action = first["quickReply"]["items"][0]["action"]
        second = service._messages({"type":"postback","postback":{"data":action["data"],"params":{"date":"2026-09-17"}}}, db, employee)[0]
        labels = [item["action"]["label"] for item in second["quickReply"]["items"]]
        assert "ลาถึงวันที่" in labels
        assert "เลือกวันสุดท้าย" not in labels
    finally:
        db.close(); engine.dispose()


def test_default_palette_gets_leave_button_and_full_command_guide():
    class Dummy:
        REQUEST_WORDS = frozenset({"ความคิดเห็น", "ฟีดแบค", "คำขอ"})

        @staticmethod
        def palette_message():
            return {
                "contents": {
                    "body": {
                        "contents": [
                            {"type": "text", "text": "มีอะไรให้ช่วยคะ", "wrap": True}
                        ]
                    },
                    "footer": {"contents": []},
                }
            }

    staff_leave_palette.install(Dummy)
    message = Dummy.palette_message()
    assert message["contents"]["footer"]["contents"][0]["action"] == {
        "type": "postback", "label": "แจ้งลา",
        "data": staff_leave_palette.LEAVE_POSTBACK_DATA,
        "displayText": "แจ้งลา",
    }
    body_contents = message["contents"]["body"]["contents"]
    assert body_contents[0]["text"] == "มีอะไรให้ช่วยคะ"
    help_text = body_contents[1]["text"]
    for phrase in (
        "งานค้าง", "แจ้งซ่อม 204 แอร์ไม่เย็น", "งานของฉัน", "สถานะ 128",
        "เพิ่มรูป 128", "ความคิดเห็นลูกค้า", "แจ้งลา",
        "แจ้งลา ลากิจ ครึ่งวันเช้า 18/9/2569", "ใบลาล่าสุด",
        "แก้ไขใบลา", "ยกเลิกใบลา",
    ):
        assert phrase in help_text
    assert "ความคิดเห็นลูกค้า" in Dummy.REQUEST_WORDS
    assert "HF-LV-" not in help_text
