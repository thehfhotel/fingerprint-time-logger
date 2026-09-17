from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import database
from app.core.database import Base
from app.models.models import Employee
from app.models.staff_leave import StaffLeaveRequest
from app.services import staff_leave, staff_leave_family_report as family


@dataclass(frozen=True)
class FakeBuiltReply:
    messages: list
    slot_digest_included: bool = False
    digest_available: bool = False
    pending_uploads: list = None

    def __post_init__(self):
        if self.pending_uploads is None:
            object.__setattr__(self, "pending_uploads", [])


def item(request_id="a" * 32, name="พนักงาน ก", label="ลาพักร้อน",
         portion="เต็มวัน", dates="17/09/2569"):
    return family.FamilyLeaveItem(
        request_id=request_id,
        employee_name=name,
        leave_label=label,
        portion_label=portion,
        date_text=dates,
        image_url=(
            "https://erp.thehfhotel.org/api/public/staff-oa/leave-images/"
            f"{request_id}.png?version=1&expires=1&signature=test"
        ),
    )


def fake_modules(base_reply):
    bot = SimpleNamespace(
        build_reply=lambda *_args, **_kwargs: base_reply,
        COMMAND_SLOT_DIGEST="slot_digest",
        MAX_REPLY_MESSAGES=5,
        MAX_MESSAGE_CHARS=5000,
        BuiltReply=FakeBuiltReply,
    )
    calls = []
    service = SimpleNamespace(
        reply_messages=lambda token, messages: calls.append((token, messages))
    )
    return bot, service, calls


def test_render_leave_section_is_human_readable_and_has_no_internal_id():
    request_id = "b" * 32
    text = family.render_leave_section([
        item(request_id=request_id, name="สมชาย", label="ลากิจ",
             portion="ครึ่งวันเช้า", dates="18/09/2569")
    ])
    assert text == "การลาใหม่ (1 รายการ)\n1. สมชาย · ลากิจ · ครึ่งวันเช้า · 18/09/2569"
    assert request_id not in text
    assert "HF-LV" not in text


def test_slot_report_merges_leave_section_and_images(monkeypatch):
    base = FakeBuiltReply(
        [{"type": "text", "text": "สรุปงานซ่อมค้างประจำรอบเช้า\n\nไม่มีงานซ่อมค้าง"}],
        slot_digest_included=True,
        digest_available=True,
    )
    bot, service, calls = fake_modules(base)
    rows = [item("1" * 32), item("2" * 32, name="พนักงาน ข", label="ลาป่วย")]
    monkeypatch.setattr(family, "fetch_unreported", lambda limit: (rows[:limit], len(rows)))
    marked = []
    monkeypatch.setattr(family, "mark_reported", lambda ids: marked.extend(ids))

    family.install(bot, service)
    built = bot.build_reply(["slot_digest"], "morning", [], (), {})

    assert built.slot_digest_included is True
    assert len(built.messages) == 3
    assert "สรุปงานซ่อมค้าง" in built.messages[0]["text"]
    assert "การลาใหม่ (2 รายการ)" in built.messages[0]["text"]
    assert [m["type"] for m in built.messages[1:]] == ["image", "image"]

    service.reply_messages("reply-token", built.messages)
    assert calls and calls[0][0] == "reply-token"
    assert marked == ["1" * 32, "2" * 32]


def test_leave_only_can_make_a_real_slot_report(monkeypatch):
    base = FakeBuiltReply([], slot_digest_included=False, digest_available=False)
    bot, service, _ = fake_modules(base)
    monkeypatch.setattr(family, "fetch_unreported", lambda limit: ([item()], 1))

    family.install(bot, service)
    built = bot.build_reply(["slot_digest"], "night", [], (), {})

    assert built.slot_digest_included is True
    assert [m["type"] for m in built.messages] == ["text", "image"]
    assert built.messages[0]["text"].startswith("การลาใหม่")


def test_non_slot_reply_never_fetches_or_adds_leave(monkeypatch):
    base = FakeBuiltReply([{"type": "text", "text": "งานค้าง"}], True, True)
    bot, service, _ = fake_modules(base)

    def should_not_run(_limit):
        raise AssertionError("leave fetch must be slot-only")

    monkeypatch.setattr(family, "fetch_unreported", should_not_run)
    family.install(bot, service)
    built = bot.build_reply(["digest"], None, [], (), {})
    assert built.messages == base.messages


def test_reply_never_exceeds_line_five_message_limit(monkeypatch):
    base = FakeBuiltReply(
        [{"type": "text", "text": "สรุปรอบบ่าย"}],
        slot_digest_included=True,
        digest_available=True,
    )
    bot, service, _ = fake_modules(base)
    rows = [item(f"{n:x}".rjust(32, "0")) for n in range(1, 8)]
    monkeypatch.setattr(family, "fetch_unreported", lambda limit: (rows[:limit], len(rows)))

    family.install(bot, service)
    built = bot.build_reply(["slot_digest"], "afternoon", [], (), {})

    assert len(built.messages) == 5
    assert sum(m["type"] == "image" for m in built.messages) == 4
    assert "และอีก 3 รายการ จะรายงานในรอบถัดไป" in built.messages[0]["text"]


def test_line_reply_failure_does_not_mark_leave_reported(monkeypatch):
    base = FakeBuiltReply([], False, False)
    bot = SimpleNamespace(
        build_reply=lambda *_a, **_k: base,
        COMMAND_SLOT_DIGEST="slot_digest",
        MAX_REPLY_MESSAGES=5,
        MAX_MESSAGE_CHARS=5000,
        BuiltReply=FakeBuiltReply,
    )

    def fail_reply(_token, _messages):
        raise RuntimeError("LINE down")

    service = SimpleNamespace(reply_messages=fail_reply)
    monkeypatch.setattr(family, "fetch_unreported", lambda limit: ([item()], 1))
    marked = []
    monkeypatch.setattr(family, "mark_reported", lambda ids: marked.extend(ids))
    family.install(bot, service)
    built = bot.build_reply(["slot_digest"], "morning", [], (), {})

    with pytest.raises(RuntimeError, match="LINE down"):
        service.reply_messages("reply-token", built.messages)
    assert marked == []


def test_fetch_and_mark_reported_use_durable_database(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    monkeypatch.setattr(staff_leave, "image_url", lambda row: f"https://example/{row.id}.png")

    db = Session()
    try:
        db.add(Employee(
            badge_number="FAM-1", display_name="พนักงานทดสอบ", thai_name="พนักงานทดสอบ",
            is_active=True, pending_approval=False,
        ))
        rows = []
        for status in ("pending", "approved", "rejected", "cancelled"):
            row = StaffLeaveRequest(
                id=uuid4().hex,
                employee_badge_number="FAM-1",
                employee_name=f"พนักงาน {status}",
                leave_type="vacation",
                leave_portion="full",
                date_from=date(2026, 9, 20),
                date_to=date(2026, 9, 20),
                status=status,
                version=1,
            )
            rows.append(row)
            db.add(row)
        db.commit()

        fetched, total = family.fetch_unreported(4)
        assert total == 2
        assert {x.employee_name for x in fetched} == {"พนักงาน pending", "พนักงาน approved"}

        target = fetched[0].request_id
        family.mark_reported([target])
        db.expire_all()
        assert db.get(StaffLeaveRequest, target).family_reported_at is not None

        again, total_again = family.fetch_unreported(4)
        assert total_again == 1
        assert all(x.request_id != target for x in again)
    finally:
        db.close()
        engine.dispose()
