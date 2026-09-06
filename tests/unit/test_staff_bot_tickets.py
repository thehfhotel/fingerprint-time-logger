"""Unit tests for the staff bot's phase-3 ticket intake — แจ้งซ่อม, the photo
buffer/attach window, the confirmation bubble, and the fixcat/setcat/
toggleurgent/addphoto/cancel/switchprop postbacks.

Companion to tests/unit/test_staff_bot.py (phases 1/2), split out because
phase 3 is a self-contained slice: a linked employee types แจ้งซ่อม, the bot
creates a work order in housekeeping over the internal door
(app/services/housekeeping_client.py) and replies a confirmation bubble at
once, uploading any claimed photos in the background. See hf-erp
docs/staff-bot-plan.md ("Locked interface (phases 3 and 4)").

Same boundaries as test_staff_bot.py, restated here because pytest fixtures
do not cross files without a shared conftest:

  * ZERO METERED SENDS, and no test may reach api.line.me, api-data.line.me
    or housekeeping by any path — the exploding-``requests`` stub below.
  * A photo is NEVER downloaded unless it is tied to a ticket — the photo
    buffer only ever holds message ids.
  * DISCARD BEFORE LOGGING — no message text, no photo bytes, no message id
    is ever written to a log line.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import time

import pytest

from app.models.models import Employee, EmployeeAppGrant
from app.services import guest_feedback_client, housekeeping_client, staff_bot
from app.services import staff_oa_service as service

TOKEN = "test-channel-access-token"
SECRET = "test-channel-secret"
WEBHOOK_PATH = "/api/public/staff-oa/webhook"


# ---------------------------------------------------------------------------
# Boundaries (mirrors test_staff_bot.py)
# ---------------------------------------------------------------------------

class _ExplodingRequests:
    def __init__(self, label):
        self._label = label

    def __getattr__(self, name):
        def _boom(*args, **kwargs):
            raise AssertionError(
                f"{self._label} boundary escaped the stub: requests.{name}{args!r}"
            )
        return _boom


@pytest.fixture(autouse=True)
def _block_line_http(monkeypatch):
    monkeypatch.setattr(service, "requests", _ExplodingRequests("LINE"))
    monkeypatch.setattr(housekeeping_client, "requests", _ExplodingRequests("housekeeping"))
    monkeypatch.setattr(guest_feedback_client, "requests", _ExplodingRequests("guest-feedback"))


@pytest.fixture(autouse=True)
def _dark_housekeeping(monkeypatch):
    monkeypatch.delenv("HOUSEKEEPING_STAFF_BOT_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _dark_guest_feedback(monkeypatch):
    monkeypatch.delenv("GUEST_FEEDBACK_BASE_URL", raising=False)
    monkeypatch.delenv("GUEST_FEEDBACK_READER_SECRET", raising=False)


@pytest.fixture(autouse=True)
def _idle_requests_gate(monkeypatch):
    monkeypatch.setattr(
        staff_bot, "get_requests_gate",
        lambda: staff_bot.PendingRequestsGate(fetch=lambda: None),
    )


@pytest.fixture(autouse=True)
def _fresh_ticket_state(monkeypatch):
    """Fresh photo buffer + attach-window store per test — see the identical
    fixture (and its rationale) in test_staff_bot.py."""
    fresh_buffer = staff_bot.PhotoBuffer()
    fresh_windows = staff_bot.AttachWindowStore()
    monkeypatch.setattr(staff_bot, "get_photo_buffer", lambda: fresh_buffer)
    monkeypatch.setattr(staff_bot, "get_attach_windows", lambda: fresh_windows)


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


async def _wait_until(predicate, timeout=3.0):
    """Poll a no-arg predicate for real background asyncio work (a spawned
    upload task, the debounce drain loop) — the same shape as the existing
    asyncio-dispatcher tests' inline deadline loops, factored out because the
    photo-ack tests below need it more than once."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


class _CollectingDispatcher:
    """Records what the router files — mirrors test_staff_bot.py's, plus the
    one phase-3 method."""

    def __init__(self):
        self.commands = []
        self.messages = []
        self.slots = []
        self.photo_uploads = []
        self.photo_upload_tokens = []

    def submit_command(self, command):
        self.commands.append(command)

    def submit_message(self, chat_key, reply_token):
        self.messages.append((chat_key, reply_token))

    def submit_slot_digest(self, ref, reply_token, trigger):
        self.slots.append((ref, reply_token, trigger))

    def spawn_photo_upload(self, order_id, message_id, actor_badge, chat_key="", reply_token=""):
        # chat_key/reply_token (rule A, 2026-09-06) are recorded separately so
        # the existing 3-tuple assertions in TestAttachWindow/TestPhotoBuffer
        # stay exactly as they were.
        self.photo_uploads.append((order_id, message_id, actor_badge))
        self.photo_upload_tokens.append((order_id, chat_key, reply_token))


@pytest.fixture
def dispatcher(monkeypatch):
    collected = _CollectingDispatcher()
    monkeypatch.setattr(staff_bot, "get_dispatcher", lambda: collected)
    return collected


def _employee(db, badge="7001", line_user_id="U-emp", location=None, name="สมชาย"):
    emp = Employee(
        badge_number=badge, display_name=name, is_active=True, is_hidden=False,
        line_user_id=line_user_id, location=location,
    )
    db.add(emp)
    db.commit()
    return emp


def _action(command, **overrides):
    base = dict(
        chat_key="Cgroup", command=command, reply_token="tok",
        quiet_seconds=0.0, event_type="message", source_type="group",
        user_id="U-emp", identity_known=True, badge="7001",
        display_name="สมชาย", property="hf", is_reception=False,
    )
    base.update(overrides)
    return staff_bot.RoutedCommand(**base)


def _flatten_texts(node, out=None):
    """Every string value under a "text" key, anywhere in a Flex/quick-reply
    structure — used to assert on bubble content without hard-coding layout."""
    if out is None:
        out = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "text" and isinstance(value, str):
                out.append(value)
            else:
                _flatten_texts(value, out)
    elif isinstance(node, list):
        for item in node:
            _flatten_texts(item, out)
    return out


def _group_text(text, reply_token="reply-g", group_id="Cgroup", user_id="Uspeaker"):
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "group", "groupId": group_id, "userId": user_id},
        "message": {"type": "text", "id": "m1", "text": text},
    }


def _direct_text(text, user_id="U-emp", reply_token="reply-d"):
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": user_id},
        "message": {"type": "text", "id": "m1", "text": text},
    }


def _image(message_id="line-img-1", group_id="Cgroup", user_id="U-emp", reply_token="reply-i"):
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "group", "groupId": group_id, "userId": user_id},
        "message": {"type": "image", "id": message_id},
    }


def _postback(data, group_id="Cgroup", user_id="U-emp", reply_token="reply-p"):
    return {
        "type": "postback",
        "replyToken": reply_token,
        "source": {"type": "group", "groupId": group_id, "userId": user_id},
        "postback": {"data": data},
    }


def _signed_post(client, payload):
    body = json.dumps(payload).encode("utf-8")
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    return client.post(
        WEBHOOK_PATH, content=body,
        headers={
            "X-Line-Signature": base64.b64encode(digest).decode("ascii"),
            "Content-Type": "application/json",
        },
    )


@pytest.fixture
def staff_oa_enabled(monkeypatch):
    monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", SECRET)


# ===========================================================================
# Parser
# ===========================================================================

class TestParseReport:
    @pytest.mark.parametrize("text,expected_room", [
        ("204 แอร์ไม่เย็น", "204"),
        ("ห้อง 204 แอร์ไม่เย็น", "204"),
        ("1204 แอร์ไม่เย็น", "1204"),
        ("แอร์ไม่เย็น ห้อง 311", "311"),
        ("แอร์ไม่เย็นห้อง 311 ด่วน", "311"),
        ("ห้อง204แอร์เสีย", "204"),
        ("แอร์เสีย204", "204"),
    ])
    def test_room_detection(self, text, expected_room):
        draft = staff_bot.parse_report(text)
        assert isinstance(draft, staff_bot.ReportDraft)
        assert draft.room_no == expected_room
        assert draft.location_kind == staff_bot.LOCATION_KIND_ROOM
        assert draft.common_area is None

    @pytest.mark.parametrize("text,expected_area", [
        ("ล็อบบี้ไฟดับ", "lobby"),
        ("ล็อบบีไฟดับ", "lobby"),
        ("lobby ไฟดับ", "lobby"),
        ("ทางเดินมืด", "corridor"),
        ("โถงมืด", "corridor"),
        ("สระน้ำสกปรก", "pool"),
        ("ครัวไฟดับ", "kitchen"),
        ("ซักรีดเครื่องเสีย", "laundry"),
        ("ซักผ้าเครื่องเสีย", "laundry"),
        ("ด้านนอกไฟดับ", "outside"),
        ("ข้างนอกไฟดับ", "outside"),
        ("ลานจอดไฟดับ", "outside"),
        ("ที่จอดรถไฟดับ", "outside"),
        ("สวนไฟดับ", "outside"),
    ])
    def test_area_detection(self, text, expected_area):
        draft = staff_bot.parse_report(text)
        assert isinstance(draft, staff_bot.ReportDraft)
        assert draft.common_area == expected_area
        assert draft.location_kind == staff_bot.LOCATION_KIND_COMMON_AREA
        assert draft.room_no is None

    def test_a_room_number_wins_over_an_area_word(self):
        draft = staff_bot.parse_report("204 ล็อบบี้ไฟดับ")
        assert draft.location_kind == staff_bot.LOCATION_KIND_ROOM
        assert draft.room_no == "204"

    def test_neither_room_nor_area_is_a_parse_error(self):
        result = staff_bot.parse_report("แอร์ไม่เย็น")
        assert isinstance(result, staff_bot.ParseError)
        assert result.message == staff_bot.PARSE_ERROR_NO_ROOM_TEXT

    def test_a_bare_report_word_is_a_parse_error(self):
        assert isinstance(staff_bot.parse_report(""), staff_bot.ParseError)

    @pytest.mark.parametrize("text,expected_category", [
        ("204 แอร์เสีย", "aircon"),
        ("204 aircon เสีย", "aircon"),
        ("204 คอมเพรสเซอร์เสีย", "aircon"),
        ("204 ทีวีเสีย", "tv"),
        ("204 tv เสีย", "tv"),
        ("204 รีโมทหาย", "tv"),
        ("204 น้ำไม่ไหล", "plumbing"),
        ("204 ท่อตัน", "plumbing"),
        ("204 ฝักบัวเสีย", "plumbing"),
        ("204 ชักโครกเสีย", "plumbing"),
        ("204 ส้วมตัน", "plumbing"),
        ("204 อ่างแตก", "plumbing"),
        ("204 ก๊อกเสีย", "plumbing"),
        ("204 ท่อรั่ว", "plumbing"),
        ("204 ประปาเสีย", "plumbing"),
        ("204 ไฟดับ", "electric"),
        ("204 หลอดไฟขาด", "electric"),
        ("204 ปลั๊กไฟเสีย", "electric"),
        ("204 สวิตช์เสีย", "electric"),
        ("204 สวิทช์เสีย", "electric"),
        ("204 ไฟฟ้าลัดวงจร", "electric"),
        ("204 เบรกเกอร์ตัด", "electric"),
        ("204 เตียงหัก", "furniture"),
        ("204 ตู้เสีย", "furniture"),
        ("204 เก้าอี้หัก", "furniture"),
        ("204 โต๊ะหัก", "furniture"),
        ("204 ผ้าม่านขาด", "furniture"),
        ("204 ประตูเสีย", "furniture"),
        ("204 ลิ้นชักเสีย", "furniture"),
        ("204 กระจกแตก", "furniture"),
        ("204 เฟอร์นิเจอร์เสีย", "furniture"),
        ("204 อะไรก็ไม่รู้", "other"),
    ])
    def test_category_keywords(self, text, expected_category):
        draft = staff_bot.parse_report(text)
        assert draft.category == expected_category

    def test_category_priority_aircon_wins_over_plumbing(self):
        # "แอร์รั่ว" carries both an aircon keyword and the plumbing keyword
        # "รั่ว" — aircon is checked first and wins.
        assert staff_bot.parse_report("204 แอร์รั่ว").category == "aircon"

    def test_urgent_flag(self):
        assert staff_bot.parse_report("204 แอร์เสีย ด่วน").urgent is True
        assert staff_bot.parse_report("204 แอร์เสีย").urgent is False

    def test_detail_strips_the_bare_room_token(self):
        assert staff_bot.parse_report("204 แอร์ไม่เย็น").detail_text == "แอร์ไม่เย็น"

    def test_detail_strips_the_hong_prefixed_room_token(self):
        assert staff_bot.parse_report("ห้อง 204 แอร์ไม่เย็น").detail_text == "แอร์ไม่เย็น"

    def test_detail_is_none_when_nothing_is_left(self):
        assert staff_bot.parse_report("204").detail_text is None

    def test_detail_strips_pictographs(self):
        draft = staff_bot.parse_report("204 แอร์ไม่เย็น\U0001F525")
        assert draft.detail_text == "แอร์ไม่เย็น"

    def test_detail_is_capped_at_200_chars(self):
        draft = staff_bot.parse_report("204 " + ("อ" * 250))
        assert len(draft.detail_text) == 200


# ===========================================================================
# Identity + property mapping
# ===========================================================================

class TestIdentityAndProperty:
    def test_hf_maps_to_hf(self, test_db):
        _employee(test_db, badge="1", line_user_id="U-1", location="HF")
        identity = staff_bot.resolve_employee_identity(test_db, "U-1")
        assert identity.property == "hf"
        assert identity.badge == "1"

    def test_hf_ville_maps_to_hfville(self, test_db):
        _employee(test_db, badge="2", line_user_id="U-2", location="HF_VILLE")
        assert staff_bot.resolve_employee_identity(test_db, "U-2").property == "hfville"

    def test_unset_location_defaults_to_hf(self, test_db):
        _employee(test_db, badge="3", line_user_id="U-3", location=None)
        assert staff_bot.resolve_employee_identity(test_db, "U-3").property == "hf"

    def test_unknown_sender_is_none(self, test_db):
        assert staff_bot.resolve_employee_identity(test_db, "U-nobody") is None

    def test_inactive_employee_is_none(self, test_db):
        test_db.add(Employee(
            badge_number="4", display_name="D", is_active=False, is_hidden=False,
            line_user_id="U-4",
        ))
        test_db.commit()
        assert staff_bot.resolve_employee_identity(test_db, "U-4") is None

    def test_enrich_marks_a_stranger_not_linked(self, test_db):
        routed = _action(staff_bot.COMMAND_REPORT, user_id="U-nobody", report_text="204 แอร์เสีย")
        enriched = staff_bot._enrich_ticket_command(routed, test_db)
        assert enriched.identity_known is False

    def test_enrich_fills_in_the_senders_identity(self, test_db):
        _employee(test_db, badge="7001", line_user_id="U-emp", location="HF_VILLE", name="สมชาย")
        routed = staff_bot.RoutedCommand(
            chat_key="Cgroup", command=staff_bot.COMMAND_REPORT, reply_token="tok",
            quiet_seconds=0.0, event_type="message", source_type="group",
            user_id="U-emp", report_text="204 แอร์เสีย",
        )
        enriched = staff_bot._enrich_ticket_command(routed, test_db)
        assert enriched.identity_known is True
        assert enriched.badge == "7001"
        assert enriched.display_name == "สมชาย"
        assert enriched.property == "hfville"
        assert enriched.is_reception is False

    def test_enrich_notices_a_reception_grant(self, test_db):
        _employee(test_db, badge="8001", line_user_id="U-reception")
        test_db.add(EmployeeAppGrant(employee_badge_number="8001", app_id="reception"))
        test_db.commit()
        routed = _action(staff_bot.COMMAND_CANCEL, user_id="U-reception", order_id=1)
        enriched = staff_bot._enrich_ticket_command(routed, test_db)
        assert enriched.is_reception is True


# ===========================================================================
# Routing: แจ้งซ่อม / report_help / mine word + prefix rules
# ===========================================================================

class TestReportRouting:
    def test_a_summoned_report_is_routed_with_its_text(self):
        routed = staff_bot.route_event(_group_text("น้องคะ แจ้งซ่อม 204 แอร์ไม่เย็น"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_REPORT
        assert routed.report_text == "204 แอร์ไม่เย็น"

    def test_a_bare_report_in_1_1_needs_no_summon(self):
        routed = staff_bot.route_event(_direct_text("แจ้งซ่อม 204 แอร์ไม่เย็น"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_REPORT
        assert routed.report_text == "204 แอร์ไม่เย็น"

    def test_digest_word_is_never_mistaken_for_a_report(self):
        routed = staff_bot.route_event(_group_text("น้องคะ แจ้งซ่อมค้าง"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_DIGEST

    def test_mine_word_routes_to_mine(self):
        routed = staff_bot.route_event(_direct_text("งานของฉัน"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_MINE

    def test_report_commands_answer_immediately(self):
        routed = staff_bot.route_event(_direct_text("แจ้งซ่อม 204 แอร์เสีย"), lambda u: True)
        assert routed.quiet_seconds == staff_bot.COMMAND_QUIET_SECONDS == 0.0


# ===========================================================================
# Bare แจ้งซ่อม in a group/room (owner decision 2026-09-06)
# ===========================================================================

class TestBareGroupReport:
    def test_bare_group_report_routes_exactly_like_the_summoned_form(self):
        summoned = staff_bot.route_event(
            _group_text("น้องคะ แจ้งซ่อม 204 แอร์ไม่เย็น ด่วน"), lambda u: True,
        )
        bare = staff_bot.route_event(
            _group_text("แจ้งซ่อม 204 แอร์ไม่เย็น ด่วน"), lambda u: True,
        )
        assert bare.command == summoned.command == staff_bot.COMMAND_REPORT
        assert bare.report_text == summoned.report_text == "204 แอร์ไม่เย็น ด่วน"
        assert bare.quiet_seconds == staff_bot.COMMAND_QUIET_SECONDS == 0.0

    @pytest.mark.parametrize("text", ["แจ้งซ่อมแล้วนะ", "แจ้งซ่อม ไฟดับ"])
    def test_bare_report_with_no_room_is_silent_chatter(self, text):
        routed = staff_bot.route_event(_group_text(text), lambda u: True)
        assert isinstance(routed, staff_bot.RoutedMessage)

    @pytest.mark.parametrize("phrase", sorted(staff_bot.BARE_REPORT_SKIP_PHRASES))
    def test_each_skip_phrase_with_a_room_is_silent_chatter(self, phrase):
        routed = staff_bot.route_event(_group_text(f"แจ้งซ่อม 204 {phrase}"), lambda u: True)
        assert isinstance(routed, staff_bot.RoutedMessage)

    def test_digest_word_bare_in_group_is_still_chatter(self):
        routed = staff_bot.route_event(_group_text("แจ้งซ่อมค้าง"), lambda u: True)
        assert isinstance(routed, staff_bot.RoutedMessage)

    @pytest.mark.parametrize("word", sorted(staff_bot.DIGEST_WORDS))
    def test_a_digest_word_prefix_with_trailing_text_is_still_chatter(self, word):
        # Reviewer finding: a digest word followed by MORE text (not just the
        # bare word on its own) must stay chatter too — a PREFIX match, not
        # only an exact one. Regression for "แจ้งซ่อมค้าง 204 ยังไม่มาเลย" once
        # silently becoming a ticket.
        routed = staff_bot.route_event(_group_text(f"{word} 204 ยังไม่มาเลย"), lambda u: True)
        assert isinstance(routed, staff_bot.RoutedMessage)

    def test_summoned_form_with_no_room_is_still_a_command(self):
        # The summon form is unchanged: unlike the bare form, a parse error
        # is still a command (and its reply still nags for a room), not
        # silence.
        routed = staff_bot.route_event(_group_text("น้องคะ แจ้งซ่อม แอร์เสีย"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_REPORT
        messages = staff_bot.build_messages([], actions=[routed])
        assert messages == [{"type": "text", "text": staff_bot.PARSE_ERROR_NO_ROOM_TEXT}]

    def test_the_skip_phrase_filter_does_not_apply_to_1_1(self):
        # Rule 2: the safeguard is bare-GROUP-only. A 1:1 "...เสร็จแล้ว" is
        # still a plain แจ้งซ่อม with that text in the detail.
        routed = staff_bot.route_event(_direct_text("แจ้งซ่อม 204 เสร็จแล้ว"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_REPORT
        assert routed.report_text == "204 เสร็จแล้ว"

    @pytest.mark.parametrize("text", ["แจ้งซ่อมแล้วนะ", "แจ้งซ่อม ไฟดับ", "แจ้งซ่อม 204 เสร็จแล้ว"])
    def test_webhook_bare_chatter_gets_no_command_and_no_reply(
        self, text, test_client, test_db, staff_oa_enabled, dispatcher,
    ):
        _employee(test_db, badge="7001", line_user_id="U-emp")
        response = _signed_post(test_client, {"events": [_group_text(text, user_id="U-emp")]})
        assert response.status_code == 200
        assert dispatcher.commands == []


class TestPostbackRouting:
    def test_fixcat_carries_the_order_id(self):
        routed = staff_bot.route_event(_postback("cmd=fixcat&id=128"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_FIXCAT
        assert routed.order_id == 128

    def test_setcat_carries_id_and_category(self):
        routed = staff_bot.route_event(_postback("cmd=setcat&id=128&cat=plumbing"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_SETCAT
        assert routed.order_id == 128
        assert routed.category == "plumbing"

    def test_setcat_without_a_category_is_ignored(self):
        assert staff_bot.route_event(_postback("cmd=setcat&id=128"), lambda u: True) is None

    def test_setcat_with_an_unknown_category_is_ignored(self):
        assert staff_bot.route_event(_postback("cmd=setcat&id=128&cat=nope"), lambda u: True) is None

    @pytest.mark.parametrize("cmd", ["fixcat", "toggleurgent", "addphoto", "cancel", "switchprop"])
    def test_order_postbacks_without_an_id_are_ignored(self, cmd):
        assert staff_bot.route_event(_postback(f"cmd={cmd}"), lambda u: True) is None

    def test_report_help_needs_no_id(self):
        routed = staff_bot.route_event(_postback("cmd=report_help"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_REPORT_HELP

    def test_mine_needs_no_id(self):
        routed = staff_bot.route_event(_postback("cmd=mine"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_MINE

    def test_a_malformed_id_is_ignored(self):
        assert staff_bot.route_event(_postback("cmd=fixcat&id=nope"), lambda u: True) is None


class TestPalette:
    def test_the_palette_keeps_its_original_two_buttons(self):
        buttons = staff_bot.palette_message()["contents"]["footer"]["contents"]
        assert buttons[0]["action"]["data"] == "cmd=digest"
        assert buttons[1]["action"]["data"] == "cmd=requests"

    def test_the_palette_gains_report_help_and_mine(self):
        buttons = staff_bot.palette_message()["contents"]["footer"]["contents"]
        data = [b["action"]["data"] for b in buttons]
        assert "cmd=report_help" in data
        assert "cmd=mine" in data

    def test_every_palette_button_postback_routes_correctly(self):
        for button in staff_bot.palette_message()["contents"]["footer"]["contents"]:
            routed = staff_bot.route_event(
                _postback(button["action"]["data"]), lambda u: True,
            )
            assert routed is not None


# ===========================================================================
# Not-linked gate
# ===========================================================================

class TestNotLinkedGate:
    @pytest.mark.parametrize("command", [
        staff_bot.COMMAND_REPORT, staff_bot.COMMAND_FIXCAT, staff_bot.COMMAND_SETCAT,
        staff_bot.COMMAND_TOGGLEURGENT, staff_bot.COMMAND_ADDPHOTO,
        staff_bot.COMMAND_CANCEL, staff_bot.COMMAND_SWITCHPROP,
        staff_bot.COMMAND_MINE, staff_bot.COMMAND_STATUS,
    ])
    def test_every_authenticated_ticket_command_is_gated(self, command):
        routed = _action(command, identity_known=False, order_id=1, category="tv")
        messages = staff_bot.build_messages([], actions=[routed])
        assert messages == [{"type": "text", "text": staff_bot.NOT_LINKED_TEXT}]

    def test_report_help_needs_no_identity(self):
        routed = _action(staff_bot.COMMAND_REPORT_HELP, identity_known=False)
        messages = staff_bot.build_messages([], actions=[routed])
        assert messages[0]["text"] != staff_bot.NOT_LINKED_TEXT

    def test_webhook_report_from_a_stranger_gets_the_not_linked_reply(
        self, test_client, test_db, staff_oa_enabled, dispatcher,
    ):
        _signed_post(test_client, {"events": [_direct_text(
            "แจ้งซ่อม 204 แอร์เสีย", user_id="U-stranger",
        )]})
        # A 1:1 stranger is caught by the EXISTING onboarding gate first
        # (route_event never even reaches _word_command for an unknown 1:1
        # sender) — this pins that the two "not linked" paths do not
        # conflict, not that phase 3 replaces phase 1's onboarding text.
        assert [c.command for c in dispatcher.commands] == [staff_bot.COMMAND_ONBOARDING]

    def test_webhook_group_report_from_a_non_employee_is_not_linked(
        self, test_client, test_db, staff_oa_enabled, dispatcher,
    ):
        _signed_post(test_client, {"events": [_group_text(
            "น้องคะ แจ้งซ่อม 204 แอร์เสีย", user_id="U-stranger",
        )]})
        assert len(dispatcher.commands) == 1
        routed = dispatcher.commands[0]
        assert routed.command == staff_bot.COMMAND_REPORT
        assert routed.identity_known is False

    def test_webhook_bare_group_report_from_a_non_employee_is_not_linked(
        self, test_client, test_db, staff_oa_enabled, dispatcher,
    ):
        _signed_post(test_client, {"events": [_group_text(
            "แจ้งซ่อม 204 แอร์เสีย", user_id="U-stranger",
        )]})
        assert len(dispatcher.commands) == 1
        routed = dispatcher.commands[0]
        assert routed.command == staff_bot.COMMAND_REPORT
        assert routed.identity_known is False
        messages = staff_bot.build_messages([], actions=[routed])
        assert messages == [{"type": "text", "text": staff_bot.NOT_LINKED_TEXT}]


# ===========================================================================
# Ticket creation
# ===========================================================================

class TestCreateTicket:
    def _order_view(self, **overrides):
        order = {
            "id": 128, "property": "hf", "propertyLabel": "HF",
            "locationKind": "room", "roomNo": "204", "commonArea": None,
            "location": "ห้อง 204", "category": "aircon", "categoryLabel": "แอร์",
            "urgent": True, "detailText": "แอร์ไม่เย็น", "status": "new",
            "statusLabel": "รอช่าง", "reporterBadge": "7001", "reporterName": "สมชาย",
            "createdAt": "2026-09-06T09:00:00.000Z", "updatedAt": "2026-09-06T09:00:00.000Z",
            "ageDays": 0, "photoCount": 0,
        }
        order.update(overrides)
        return order

    def test_success_calls_create_work_order_with_the_documented_body(self, monkeypatch):
        captured = {}

        def _create(payload):
            captured.update(payload)
            return {"order": self._order_view()}

        monkeypatch.setattr(housekeeping_client, "create_work_order", _create)
        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็น ด่วน")
        staff_bot.build_messages([], actions=[action])

        assert captured["property"] == "hf"
        assert captured["location_kind"] == staff_bot.LOCATION_KIND_ROOM
        assert captured["room_no"] == "204"
        assert captured["category"] == "aircon"
        assert captured["urgent"] is True
        # Only the room token is stripped out of the detail — "ด่วน" is left
        # in place, exactly as parse_report documents.
        assert captured["detail_text"] == "แอร์ไม่เย็น ด่วน"
        assert captured["reporter"] == {"badge": "7001", "name": "สมชาย"}
        assert captured["source"] == "line-bot"
        assert "common_area" not in captured

    def test_area_report_sends_common_area_not_room_no(self, monkeypatch):
        captured = {}

        def _create(payload):
            captured.update(payload)
            return {"order": self._order_view(locationKind="common", roomNo=None, commonArea="lobby")}

        monkeypatch.setattr(housekeeping_client, "create_work_order", _create)
        action = _action(staff_bot.COMMAND_REPORT, report_text="ล็อบบี้ไฟดับ")
        staff_bot.build_messages([], actions=[action])

        assert captured["location_kind"] == staff_bot.LOCATION_KIND_COMMON_AREA
        assert captured["common_area"] == "lobby"
        assert "room_no" not in captured

    def test_a_parse_error_never_calls_housekeeping(self, monkeypatch):
        def _boom(payload):
            raise AssertionError("create_work_order must not be called on a parse error")

        monkeypatch.setattr(housekeeping_client, "create_work_order", _boom)
        action = _action(staff_bot.COMMAND_REPORT, report_text="แอร์เสีย")
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.PARSE_ERROR_NO_ROOM_TEXT}]

    def test_success_replies_the_confirmation_bubble(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "create_work_order",
            lambda payload: {"order": self._order_view()},
        )
        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็น ด่วน")
        messages = staff_bot.build_messages([], actions=[action])
        assert len(messages) == 1
        bubble = messages[0]
        assert bubble["type"] == "flex"
        assert bubble["altText"] == "รับเรื่องแล้ว #128"
        texts = _flatten_texts(bubble)
        assert "รับเรื่องแล้ว #128" in texts
        assert "HF" in texts
        assert "ห้อง 204" in texts
        assert "แอร์" in texts
        assert "ด่วน" in texts
        assert "แอร์ไม่เย็น" in texts
        assert "สมชาย" in texts
        assert "ยังไม่มีรูป" in texts  # no photos claimed in this test

    def test_the_bubble_carries_every_button_with_correct_postback_data(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "create_work_order",
            lambda payload: {"order": self._order_view()},
        )
        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็น")
        bubble = staff_bot.build_messages([], actions=[action])[0]
        buttons = bubble["contents"]["footer"]["contents"]
        data_by_label = {b["action"]["label"]: b["action"]["data"] for b in buttons}
        assert data_by_label["แก้หมวด"] == "cmd=fixcat&id=128"
        assert data_by_label["เพิ่มรูป"] == "cmd=addphoto&id=128"
        assert data_by_label["ยกเลิก"] == "cmd=cancel&id=128"
        assert data_by_label["สลับสาขา"] == "cmd=switchprop&id=128"
        # Urgent order -> the toggle offers "ไม่ด่วน".
        assert "cmd=toggleurgent&id=128" in [b["action"]["data"] for b in buttons]
        assert "ไม่ด่วน" in data_by_label
        for button in buttons:
            assert button["action"]["displayText"] == button["action"]["label"]

    def test_the_bubble_never_carries_emoji(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "create_work_order",
            lambda payload: {"order": self._order_view(detailText="แอร์ไม่เย็น\U0001F525")},
        )
        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็น")
        bubble = staff_bot.build_messages([], actions=[action])[0]
        blob = json.dumps(bubble, ensure_ascii=False)
        assert "\U0001F525" not in blob

    def test_housekeeping_none_gives_the_fixed_unavailable_line(self, monkeypatch):
        monkeypatch.setattr(housekeeping_client, "create_work_order", lambda payload: None)
        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็น")
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.TICKET_UNAVAILABLE_TEXT}]

    def test_a_validation_error_is_relayed_verbatim(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "create_work_order",
            lambda payload: {"error": "หมวดไม่ถูกต้อง"},
        )
        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็น")
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": "หมวดไม่ถูกต้อง"}]

    def test_success_claims_buffered_photos_and_schedules_their_upload(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "create_work_order",
            lambda payload: {"order": self._order_view()},
        )
        staff_bot.get_photo_buffer().add("Cgroup", "U-emp", "img-1")
        staff_bot.get_photo_buffer().add("Cgroup", "U-emp", "img-2")

        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็น")
        built = staff_bot.build_reply([], actions=[action])

        assert len(built.pending_uploads) == 1
        upload = built.pending_uploads[0]
        assert upload.order_id == 128
        assert upload.message_ids == ["img-1", "img-2"]
        assert upload.actor_badge == "7001"
        texts = _flatten_texts(built.messages[0])
        assert "กำลังแนบ 2 รูป" in texts
        # And the buffer is now empty — claimed, not merely peeked at.
        assert staff_bot.get_photo_buffer().claim("Cgroup", "U-emp") == []

    def test_success_opens_an_attach_window_for_more_photos(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "create_work_order",
            lambda payload: {"order": self._order_view()},
        )
        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็น")
        staff_bot.build_messages([], actions=[action])
        assert staff_bot.get_attach_windows().active_order("Cgroup", "U-emp") == 128

    def test_ticket_created_log_line_carries_only_ids(self, monkeypatch, caplog):
        monkeypatch.setattr(
            housekeeping_client, "create_work_order",
            lambda payload: {"order": self._order_view()},
        )
        staff_bot.get_photo_buffer().add("Cgroup", "U-emp", "img-1")
        action = _action(staff_bot.COMMAND_REPORT, report_text="204 แอร์ไม่เย็นสุดๆ ห้ามบอกใคร")
        with caplog.at_level("INFO"):
            staff_bot.build_messages([], actions=[action])
        assert "staff-bot ticket created: chat=Cgroup order=128 photos=1" in caplog.text
        assert "แอร์ไม่เย็นสุดๆ" not in caplog.text
        assert "img-1" not in caplog.text


# ===========================================================================
# Photos-first: the confirmation bubble waits (bounded) for the claimed
# batch's uploads (owner request 2026-09-06, rule B)
# ===========================================================================

class TestPhotosFirstBoundedWait:
    """Unlike TestCreateTicket above (which calls build_reply/build_messages
    directly, synchronously, and always sees the "claimed but not yet
    uploaded" กำลังแนบ N รูป line — that stays exactly as it was), these drive
    the real AsyncioBotDispatcher so the bounded wait in
    ``_await_claimed_uploads`` actually runs and patches the bubble in
    place before the reply is sent — the existing async-dispatcher tests'
    pattern (submit, poll for a sent reply)."""

    def _order(self):
        return {
            "id": 9, "propertyLabel": "HF", "location": "ห้อง 204",
            "categoryLabel": "แอร์", "urgent": False, "detailText": "แอร์ไม่เย็น",
            "reporterName": "สมชาย",
        }

    def _submit_report_and_wait(self, sent):
        async def _scenario():
            dispatcher = staff_bot.AsyncioBotDispatcher()
            dispatcher.submit_command(_action(
                staff_bot.COMMAND_REPORT, reply_token="tok-1", quiet_seconds=0.0,
                report_text="204 แอร์ไม่เย็น",
            ))
            await _wait_until(lambda: bool(sent))
            # Let any still-running background upload finish inside this same
            # loop, so nothing is torn down mid-flight at asyncio.run's exit.
            await asyncio.sleep(0.4)
        asyncio.run(_scenario())

    def test_bubble_shows_the_completed_count_when_uploads_finish_within_the_wait(
        self, monkeypatch, staff_oa_enabled,
    ):
        monkeypatch.setattr(housekeeping_client, "create_work_order", lambda payload: {"order": self._order()})
        monkeypatch.setattr(service, "fetch_message_content", lambda mid: (b"x", "image/jpeg"))
        monkeypatch.setattr(housekeeping_client, "upload_photo", lambda *a, **k: {"photoId": 1, "photoCount": 2})
        staff_bot.get_photo_buffer().add("Cgroup", "U-emp", "img-1")
        staff_bot.get_photo_buffer().add("Cgroup", "U-emp", "img-2")

        sent = []
        monkeypatch.setattr(service, "reply_messages", lambda token, messages: sent.append((token, messages)))
        self._submit_report_and_wait(sent)

        assert len(sent) == 1
        _, messages = sent[0]
        assert "รูป 2 รูป" in _flatten_texts(messages[0])

    def test_bubble_shows_the_still_running_count_when_an_upload_times_out(
        self, monkeypatch, staff_oa_enabled,
    ):
        monkeypatch.setattr(staff_bot, "CLAIMED_UPLOAD_WAIT_SECONDS", 0.05)
        monkeypatch.setattr(housekeeping_client, "create_work_order", lambda payload: {"order": self._order()})

        def _slow_fetch(message_id):
            time.sleep(0.3)  # slower than the (shrunk) bounded wait above
            return (b"x", "image/jpeg")

        monkeypatch.setattr(service, "fetch_message_content", _slow_fetch)
        monkeypatch.setattr(housekeeping_client, "upload_photo", lambda *a, **k: {"photoId": 1, "photoCount": 1})
        staff_bot.get_photo_buffer().add("Cgroup", "U-emp", "img-1")

        sent = []
        monkeypatch.setattr(service, "reply_messages", lambda token, messages: sent.append((token, messages)))
        self._submit_report_and_wait(sent)

        assert len(sent) == 1
        _, messages = sent[0]
        assert "กำลังแนบอีก 1 รูป" in _flatten_texts(messages[0])

    def test_bubble_shows_the_failed_count_on_an_upload_failure(
        self, monkeypatch, staff_oa_enabled,
    ):
        monkeypatch.setattr(housekeeping_client, "create_work_order", lambda payload: {"order": self._order()})
        monkeypatch.setattr(service, "fetch_message_content", lambda mid: None)  # download fails
        staff_bot.get_photo_buffer().add("Cgroup", "U-emp", "img-1")

        sent = []
        monkeypatch.setattr(service, "reply_messages", lambda token, messages: sent.append((token, messages)))
        self._submit_report_and_wait(sent)

        assert len(sent) == 1
        _, messages = sent[0]
        assert "แนบไม่สำเร็จ 1 รูป" in _flatten_texts(messages[0])


# ===========================================================================
# Photo buffer + attach window
# ===========================================================================

class TestPhotoBuffer:
    def test_claim_returns_fresh_ids_oldest_first(self):
        clock = _Clock()
        buf = staff_bot.PhotoBuffer(clock=clock)
        buf.add("C1", "U1", "a")
        clock.advance(1)
        buf.add("C1", "U1", "b")
        assert buf.claim("C1", "U1") == ["a", "b"]

    def test_claim_drops_entries_older_than_the_ttl(self):
        clock = _Clock()
        buf = staff_bot.PhotoBuffer(clock=clock, ttl_seconds=90.0)
        buf.add("C1", "U1", "old")
        clock.advance(91)
        buf.add("C1", "U1", "new")
        assert buf.claim("C1", "U1") == ["new"]

    def test_claim_caps_at_max_count(self):
        clock = _Clock()
        buf = staff_bot.PhotoBuffer(clock=clock)
        for i in range(10):
            buf.add("C1", "U1", f"p{i}")
        claimed = buf.claim("C1", "U1", max_count=6)
        assert claimed == [f"p{i}" for i in range(6)]

    def test_claim_empties_the_buffer(self):
        clock = _Clock()
        buf = staff_bot.PhotoBuffer(clock=clock)
        buf.add("C1", "U1", "a")
        buf.claim("C1", "U1")
        assert buf.claim("C1", "U1") == []

    def test_buffers_are_isolated_per_chat_and_user(self):
        clock = _Clock()
        buf = staff_bot.PhotoBuffer(clock=clock)
        buf.add("C1", "U1", "a")
        buf.add("C1", "U2", "b")
        buf.add("C2", "U1", "c")
        assert buf.claim("C1", "U1") == ["a"]
        assert buf.claim("C1", "U2") == ["b"]
        assert buf.claim("C2", "U1") == ["c"]

    def test_a_photo_is_never_downloaded_just_by_being_buffered(self, test_db, dispatcher):
        _employee(test_db, badge="7001", line_user_id="U-emp")
        staff_bot.handle_event_detail(_image(message_id="img-1"), test_db)
        assert dispatcher.photo_uploads == []
        assert staff_bot.get_photo_buffer().claim("Cgroup", "U-emp") == ["img-1"]

    def test_a_non_linked_senders_photo_is_ignored_entirely(self, test_db, dispatcher):
        staff_bot.handle_event_detail(
            _image(message_id="img-1", user_id="U-stranger"), test_db,
        )
        assert dispatcher.photo_uploads == []
        assert staff_bot.get_photo_buffer().claim("Cgroup", "U-stranger") == []

    def test_a_photo_with_no_sender_id_is_ignored(self, test_db, dispatcher):
        event = _image(message_id="img-1")
        event["source"] = {"type": "group", "groupId": "Cgroup"}
        staff_bot.handle_event_detail(event, test_db)
        assert dispatcher.photo_uploads == []


class TestAttachWindow:
    def test_active_order_none_before_opening(self):
        store = staff_bot.AttachWindowStore(clock=_Clock())
        assert store.active_order("C1", "U1") is None

    def test_open_then_active_order(self):
        store = staff_bot.AttachWindowStore(clock=_Clock())
        store.open("C1", "U1", 42)
        assert store.active_order("C1", "U1") == 42

    def test_the_window_expires(self):
        clock = _Clock()
        store = staff_bot.AttachWindowStore(clock=clock, window_seconds=120.0, hard_cap_seconds=300.0)
        store.open("C1", "U1", 42)
        clock.advance(121)
        assert store.active_order("C1", "U1") is None

    def test_refresh_extends_the_window(self):
        clock = _Clock()
        store = staff_bot.AttachWindowStore(clock=clock, window_seconds=120.0, hard_cap_seconds=300.0)
        store.open("C1", "U1", 42)
        clock.advance(100)
        assert store.refresh("C1", "U1") == 42  # still open, and now extended
        clock.advance(100)  # 200s since open, but only 100s since refresh
        assert store.active_order("C1", "U1") == 42

    def test_the_hard_cap_wins_over_repeated_refreshes(self):
        clock = _Clock()
        store = staff_bot.AttachWindowStore(clock=clock, window_seconds=120.0, hard_cap_seconds=300.0)
        store.open("C1", "U1", 42)
        for _ in range(10):
            clock.advance(50)
            store.refresh("C1", "U1")
        # 500s have passed since the window first opened — past the 300s cap.
        assert store.active_order("C1", "U1") is None

    def test_opening_for_a_different_order_resets_the_hard_cap(self):
        clock = _Clock()
        store = staff_bot.AttachWindowStore(clock=clock, window_seconds=120.0, hard_cap_seconds=300.0)
        store.open("C1", "U1", 1)
        clock.advance(250)
        store.open("C1", "U1", 2)  # a NEW order: both clocks start over
        # Refresh well past what would have been order 1's hard cap (300s
        # from ITS open, i.e. absolute t=300) to prove the cap moved with it.
        for _ in range(3):
            clock.advance(80)
            assert store.refresh("C1", "U1") == 2
        assert store.active_order("C1", "U1") == 2

    def test_refresh_on_a_closed_window_returns_none(self):
        clock = _Clock()
        store = staff_bot.AttachWindowStore(clock=clock, window_seconds=120.0)
        assert store.refresh("C1", "U1") is None

    def test_a_photo_while_a_window_is_open_attaches_silently(self, test_db, dispatcher):
        _employee(test_db, badge="7001", line_user_id="U-emp")
        staff_bot.get_attach_windows().open("Cgroup", "U-emp", 55)

        handled = staff_bot.handle_event_detail(_image(message_id="img-1"), test_db)

        assert dispatcher.photo_uploads == [(55, "img-1", "7001")]
        # An attached photo is STILL just "a message in this chat" for the
        # debounce machinery (it may refresh a pending reply's token, same as
        # any photo/sticker) — it just never becomes a command of its own.
        assert dispatcher.commands == []
        assert handled.command is False

    def test_a_photo_never_opens_a_window_by_itself(self, test_db, dispatcher):
        _employee(test_db, badge="7001", line_user_id="U-emp")
        staff_bot.handle_event_detail(_image(), test_db)
        assert staff_bot.get_attach_windows().active_order("Cgroup", "U-emp") is None

    def test_an_attached_photo_is_spawned_with_its_own_event_reply_token(
        self, test_db, dispatcher,
    ):
        # Wiring for rule A (2026-09-06): the photo EVENT's own reply token
        # (not whatever token some other pending reply currently holds) is
        # what note_photo_ack will later file the ack with.
        _employee(test_db, badge="7001", line_user_id="U-emp")
        staff_bot.get_attach_windows().open("Cgroup", "U-emp", 55)
        staff_bot.handle_event_detail(_image(message_id="img-1", reply_token="reply-i"), test_db)
        assert dispatcher.photo_upload_tokens == [(55, "Cgroup", "reply-i")]


# ===========================================================================
# Photo acknowledgements (owner request 2026-09-06, rule A): a photo that
# attaches silently while an order's attach window is open gets a free-token
# ack once its upload resolves, coalesced with PHOTO_ACK_QUIET_SECONDS of
# quiet. These drive the REAL AsyncioBotDispatcher (spawn_photo_upload is
# where the ack is actually filed), the same async-helper shape as
# TestPhotosFirstBoundedWait and test_staff_bot.py's TestAsyncioDispatcher.
# ===========================================================================

class TestPhotoAck:
    def test_two_in_window_photos_produce_one_ack_line_with_the_last_total_and_newest_token(
        self, monkeypatch, staff_oa_enabled,
    ):
        upload_results = iter([
            {"photoId": 1, "photoCount": 3},
            {"photoId": 2, "photoCount": 4},
        ])
        monkeypatch.setattr(service, "fetch_message_content", lambda mid: (b"x", "image/jpeg"))
        monkeypatch.setattr(housekeeping_client, "upload_photo", lambda *a, **k: next(upload_results))

        async def _scenario():
            dispatcher = staff_bot.AsyncioBotDispatcher()

            def _acked(n):
                return lambda: (
                    (pending := dispatcher.debouncer.pending_for("Cgroup")) is not None
                    and pending.photo_acks.get(55, {}).get("attached") == n
                )

            dispatcher.spawn_photo_upload(55, "img-1", "7001", chat_key="Cgroup", reply_token="tok-1")
            await _wait_until(_acked(1))
            # Sent strictly after the first finishes, so it is unambiguously
            # the NEWEST photo — this is what "ack uses the newest photo
            # token" is asserting below.
            dispatcher.spawn_photo_upload(55, "img-2", "7001", chat_key="Cgroup", reply_token="tok-2")
            await _wait_until(_acked(2))
            return dispatcher.debouncer.pending_for("Cgroup")

        pending = asyncio.run(_scenario())
        assert pending is not None
        assert pending.photo_acks[55] == {"attached": 2, "failed": 0, "total": 4}
        assert pending.reply_token == "tok-2"
        messages = staff_bot.build_messages([], actions=[], photo_acks=pending.photo_acks)
        assert messages == [{"type": "text", "text": "แนบรูปเข้า #55 แล้ว 2 รูป (รวม 4 รูป)"}]

    def test_one_success_and_one_failure_produce_two_lines(
        self, monkeypatch, staff_oa_enabled,
    ):
        monkeypatch.setattr(
            service, "fetch_message_content",
            lambda mid: (b"x", "image/jpeg") if mid == "img-ok" else None,
        )
        monkeypatch.setattr(housekeeping_client, "upload_photo", lambda *a, **k: {"photoId": 1, "photoCount": 1})

        async def _scenario():
            dispatcher = staff_bot.AsyncioBotDispatcher()
            dispatcher.spawn_photo_upload(55, "img-ok", "7001", chat_key="Cgroup", reply_token="tok-1")
            dispatcher.spawn_photo_upload(55, "img-bad", "7001", chat_key="Cgroup", reply_token="tok-2")
            await _wait_until(lambda: (
                (pending := dispatcher.debouncer.pending_for("Cgroup")) is not None
                and pending.photo_acks.get(55, {}).get("attached") == 1
                and pending.photo_acks.get(55, {}).get("failed") == 1
            ))
            return dispatcher.debouncer.pending_for("Cgroup")

        pending = asyncio.run(_scenario())
        text = staff_bot.build_messages([], actions=[], photo_acks=pending.photo_acks)[0]["text"]
        assert text == (
            "แนบรูปเข้า #55 แล้ว 1 รูป (รวม 1 รูป)\n"
            "แนบรูปไม่สำเร็จ 1 รูป ลองส่งใหม่อีกครั้งค่ะ (#55)"
        )

    def test_a_command_typed_during_the_ack_quiet_rides_in_the_same_reply(
        self, monkeypatch, staff_oa_enabled,
    ):
        sent = []
        monkeypatch.setattr(
            service, "reply_messages",
            lambda token, messages: sent.append((token, messages)),
        )
        monkeypatch.setattr(service, "fetch_message_content", lambda mid: (b"x", "image/jpeg"))
        monkeypatch.setattr(housekeeping_client, "upload_photo", lambda *a, **k: {"photoId": 1, "photoCount": 1})

        async def _scenario():
            dispatcher = staff_bot.AsyncioBotDispatcher()
            dispatcher.spawn_photo_upload(55, "img-1", "7001", chat_key="Cgroup", reply_token="tok-ack")
            await _wait_until(lambda: (
                (pending := dispatcher.debouncer.pending_for("Cgroup")) is not None
                and staff_bot.COMMAND_PHOTO_ACK in pending.commands
            ))
            # A command lands in the SAME chat while the 3 s ack quiet is
            # still ticking: the impatient one (0 s) wins and both ride the
            # same reply, on the command's own (newest) token.
            dispatcher.submit_command(staff_bot.RoutedCommand(
                chat_key="Cgroup", command=staff_bot.COMMAND_PALETTE,
                reply_token="tok-cmd", quiet_seconds=0.0,
                event_type="message", source_type="group",
            ))
            await _wait_until(lambda: bool(sent))

        asyncio.run(_scenario())
        assert len(sent) == 1
        token, messages = sent[0]
        assert token == "tok-cmd"
        assert any(m.get("type") == "flex" for m in messages)  # the palette
        assert any(
            t == "แนบรูปเข้า #55 แล้ว 1 รูป (รวม 1 รูป)" for t in _flatten_texts(messages)
        )

    def test_a_buffered_photo_with_no_attach_window_never_fetches_or_acks(
        self, test_db, monkeypatch,
    ):
        # Rule A only ever applies to a photo already tied to a ticket (an
        # open attach window) — a plain buffered photo is never fetched, and
        # a chat with no command already pending gets no PendingReply at all.
        fetch_calls = []
        monkeypatch.setattr(
            service, "fetch_message_content",
            lambda mid: fetch_calls.append(mid) or (b"x", "image/jpeg"),
        )
        _employee(test_db, badge="7001", line_user_id="U-emp")
        dispatcher = staff_bot.AsyncioBotDispatcher()
        monkeypatch.setattr(staff_bot, "get_dispatcher", lambda: dispatcher)

        staff_bot.handle_event_detail(_image(message_id="img-1"), test_db)

        assert fetch_calls == []
        assert dispatcher.debouncer.pending_for("Cgroup") is None


# ===========================================================================
# addphoto
# ===========================================================================

class TestAddPhoto:
    def test_reopens_the_window_and_replies_the_prompt(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": {"id": 5, "reporterBadge": "7001"}},
        )
        action = _action(staff_bot.COMMAND_ADDPHOTO, order_id=5)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": "ส่งรูปมาได้เลยค่ะ (ภายใน 2 นาที) #5"}]
        assert staff_bot.get_attach_windows().active_order("Cgroup", "U-emp") == 5

    def test_a_non_reporter_non_reception_tapper_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": {"id": 5, "reporterBadge": "9999"}},
        )
        action = _action(staff_bot.COMMAND_ADDPHOTO, order_id=5, badge="7001", is_reception=False)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.EDIT_FORBIDDEN_TEXT}]
        assert staff_bot.get_attach_windows().active_order("Cgroup", "U-emp") is None

    def test_a_reception_grant_holder_may_addphoto_someone_elses_ticket(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": {"id": 5, "reporterBadge": "9999"}},
        )
        action = _action(staff_bot.COMMAND_ADDPHOTO, order_id=5, badge="7001", is_reception=True)
        messages = staff_bot.build_messages([], actions=[action])
        assert "#5" in messages[0]["text"]

    def test_unknown_order_relays_the_404(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"error": "ไม่พบรายการแจ้งซ่อมนี้"},
        )
        action = _action(staff_bot.COMMAND_ADDPHOTO, order_id=999)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": "ไม่พบรายการแจ้งซ่อมนี้"}]

    def test_housekeeping_dark_is_the_fixed_line(self, monkeypatch):
        monkeypatch.setattr(housekeeping_client, "get_work_order", lambda order_id: None)
        action = _action(staff_bot.COMMAND_ADDPHOTO, order_id=5)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.TICKET_UNAVAILABLE_TEXT}]


# ===========================================================================
# fixcat / setcat / toggleurgent / switchprop
# ===========================================================================

class TestFixcat:
    def test_replies_a_quick_reply_with_all_six_categories(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": {"id": 5, "reporterBadge": "7001"}},
        )
        action = _action(staff_bot.COMMAND_FIXCAT, order_id=5)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages[0]["text"] == "เลือกหมวดใหม่ของ #5"
        items = messages[0]["quickReply"]["items"]
        data = {item["action"]["label"]: item["action"]["data"] for item in items}
        assert len(items) == 6
        assert data["แอร์"] == "cmd=setcat&id=5&cat=aircon"
        assert data["อื่นๆ"] == "cmd=setcat&id=5&cat=other"

    def test_forbidden_for_a_non_reporter(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": {"id": 5, "reporterBadge": "9999"}},
        )
        action = _action(staff_bot.COMMAND_FIXCAT, order_id=5)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.EDIT_FORBIDDEN_TEXT}]


class TestSetcatToggleurgentSwitchprop:
    def _order_view(self, **overrides):
        order = {
            "id": 5, "property": "hf", "propertyLabel": "HF", "location": "ห้อง 204",
            "categoryLabel": "แอร์", "urgent": False, "detailText": "แอร์ไม่เย็น",
            "reporterBadge": "7001", "reporterName": "สมชาย", "photoCount": 0,
        }
        order.update(overrides)
        return order

    def test_setcat_patches_the_category(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view()},
        )

        def _patch(order_id, fields, actor):
            captured.update(order_id=order_id, fields=fields, actor=actor)
            return {"order": self._order_view(categoryLabel="ประปา")}

        monkeypatch.setattr(housekeeping_client, "patch_work_order", _patch)
        action = _action(staff_bot.COMMAND_SETCAT, order_id=5, category="plumbing")
        messages = staff_bot.build_messages([], actions=[action])

        assert captured["order_id"] == 5
        assert captured["fields"] == {"category": "plumbing"}
        assert captured["actor"] == {"badge": "7001", "name": "สมชาย"}
        assert "ประปา" in _flatten_texts(messages[0])

    def test_toggleurgent_flips_the_current_value(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view(urgent=False)},
        )

        def _patch(order_id, fields, actor):
            captured.update(fields)
            return {"order": self._order_view(urgent=True)}

        monkeypatch.setattr(housekeeping_client, "patch_work_order", _patch)
        action = _action(staff_bot.COMMAND_TOGGLEURGENT, order_id=5)
        staff_bot.build_messages([], actions=[action])
        assert captured == {"urgent": True}

    def test_switchprop_flips_hf_to_hfville(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view(property="hf")},
        )

        def _patch(order_id, fields, actor):
            captured.update(fields)
            return {"order": self._order_view(property="hfville", propertyLabel="HF Ville")}

        monkeypatch.setattr(housekeeping_client, "patch_work_order", _patch)
        action = _action(staff_bot.COMMAND_SWITCHPROP, order_id=5)
        staff_bot.build_messages([], actions=[action])
        assert captured == {"property": "hfville"}

    def test_a_409_from_patch_is_relayed(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view()},
        )
        monkeypatch.setattr(
            housekeeping_client, "patch_work_order",
            lambda *a, **k: {"error": "แก้ไขได้เฉพาะงานที่ยังไม่เริ่มซ่อม"},
        )
        action = _action(staff_bot.COMMAND_TOGGLEURGENT, order_id=5)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": "แก้ไขได้เฉพาะงานที่ยังไม่เริ่มซ่อม"}]

    def test_forbidden_for_a_non_reporter_non_reception(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view(reporterBadge="9999")},
        )

        def _boom(*a, **k):
            raise AssertionError("patch_work_order must not be called when forbidden")

        monkeypatch.setattr(housekeeping_client, "patch_work_order", _boom)
        action = _action(staff_bot.COMMAND_TOGGLEURGENT, order_id=5, badge="7001")
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.EDIT_FORBIDDEN_TEXT}]

    def test_edited_log_line_names_the_field(self, monkeypatch, caplog):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view()},
        )
        monkeypatch.setattr(
            housekeeping_client, "patch_work_order",
            lambda *a, **k: {"order": self._order_view(urgent=True)},
        )
        action = _action(staff_bot.COMMAND_TOGGLEURGENT, order_id=5)
        with caplog.at_level("INFO"):
            staff_bot.build_messages([], actions=[action])
        assert "staff-bot ticket edited: order=5 field=urgent" in caplog.text


# ===========================================================================
# cancel
# ===========================================================================

class TestCancel:
    def test_success_replies_the_confirmation(self, monkeypatch, caplog):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": {"id": 5, "reporterBadge": "7001"}},
        )
        monkeypatch.setattr(
            housekeeping_client, "cancel_work_order",
            lambda order_id, actor: {"order": {"id": order_id, "status": "cancelled"}},
        )
        action = _action(staff_bot.COMMAND_CANCEL, order_id=5)
        with caplog.at_level("INFO"):
            messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": "ยกเลิก #5 แล้วค่ะ"}]
        assert "staff-bot ticket cancelled: order=5" in caplog.text

    @pytest.mark.parametrize("reason", [
        "ยกเลิกได้เฉพาะผู้แจ้ง",
        "งานนี้เริ่มดำเนินการแล้ว ยกเลิกไม่ได้",
        "เลย 10 นาทีแล้ว ยกเลิกไม่ได้ กรุณาแจ้งแผนกต้อนรับ",
    ])
    def test_every_documented_409_reason_is_relayed(self, monkeypatch, reason):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": {"id": 5, "reporterBadge": "7001"}},
        )
        monkeypatch.setattr(
            housekeeping_client, "cancel_work_order",
            lambda order_id, actor: {"error": reason},
        )
        action = _action(staff_bot.COMMAND_CANCEL, order_id=5)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": reason}]

    def test_forbidden_before_ever_calling_cancel(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": {"id": 5, "reporterBadge": "9999"}},
        )

        def _boom(*a, **k):
            raise AssertionError("cancel_work_order must not be called when forbidden")

        monkeypatch.setattr(housekeeping_client, "cancel_work_order", _boom)
        action = _action(staff_bot.COMMAND_CANCEL, order_id=5, badge="7001", is_reception=False)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.EDIT_FORBIDDEN_TEXT}]

    def test_housekeeping_dark_on_get_is_the_fixed_line(self, monkeypatch):
        monkeypatch.setattr(housekeeping_client, "get_work_order", lambda order_id: None)
        action = _action(staff_bot.COMMAND_CANCEL, order_id=5)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.TICKET_UNAVAILABLE_TEXT}]


# ===========================================================================
# report_help / mine
# ===========================================================================

class TestReportHelpAndMine:
    def test_group_help_repeats_the_summon(self):
        action = _action(staff_bot.COMMAND_REPORT_HELP, source_type="group")
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.REPORT_HELP_GROUP_TEXT}]
        assert "น้องคะ" in messages[0]["text"]

    def test_direct_help_omits_the_summon(self):
        action = _action(staff_bot.COMMAND_REPORT_HELP, source_type="user")
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.REPORT_HELP_DIRECT_TEXT}]
        assert "น้องคะ" not in messages[0]["text"]

    def test_no_bot_string_carries_emoji(self):
        for text in (
            staff_bot.NOT_LINKED_TEXT, staff_bot.TICKET_UNAVAILABLE_TEXT,
            staff_bot.EDIT_FORBIDDEN_TEXT, staff_bot.REPORT_HELP_GROUP_TEXT,
            staff_bot.REPORT_HELP_DIRECT_TEXT, staff_bot.MINE_EMPTY_TEXT,
            staff_bot.STATUS_FORBIDDEN_TEXT, staff_bot.STATUS_NOT_FOUND_FMT.format(id=1),
            staff_bot.PARSE_ERROR_NO_ROOM_TEXT,
        ):
            assert staff_bot.strip_pictographs(text) == text


# ===========================================================================
# งานของฉัน carousel (phase 4)
# ===========================================================================

class TestMine:
    def _order_view(self, **overrides):
        order = {
            "id": 128, "location": "ห้อง 204", "categoryLabel": "แอร์",
            "statusLabel": "รอช่าง", "ageDays": 0, "photoCount": 0,
            "reporterBadge": "7001",
        }
        order.update(overrides)
        return order

    def test_mine_word_routes_to_mine(self):
        routed = staff_bot.route_event(_direct_text("งานของฉัน"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_MINE

    def test_calls_list_work_orders_with_the_tapper_badge(self, monkeypatch):
        captured = {}

        def _list(reporter_badge, active=True, limit=10):
            captured.update(reporter_badge=reporter_badge, active=active, limit=limit)
            return {"orders": []}

        monkeypatch.setattr(housekeeping_client, "list_work_orders", _list)
        action = _action(staff_bot.COMMAND_MINE, badge="7001")
        staff_bot.build_messages([], actions=[action])
        assert captured == {"reporter_badge": "7001", "active": True, "limit": 10}

    def test_carousel_has_a_bubble_per_order_capped_at_ten(self, monkeypatch):
        orders = [self._order_view(id=i) for i in range(1, 13)]  # 12 > the cap
        monkeypatch.setattr(
            housekeeping_client, "list_work_orders",
            lambda reporter_badge, active=True, limit=10: {"orders": orders[:limit]},
        )
        action = _action(staff_bot.COMMAND_MINE)
        messages = staff_bot.build_messages([], actions=[action])
        assert len(messages) == 1
        bubble_msg = messages[0]
        assert bubble_msg["type"] == "flex"
        assert bubble_msg["contents"]["type"] == "carousel"
        assert len(bubble_msg["contents"]["contents"]) == 10

    def test_bubble_content_and_buttons(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "list_work_orders",
            lambda reporter_badge, active=True, limit=10: {"orders": [self._order_view()]},
        )
        action = _action(staff_bot.COMMAND_MINE)
        messages = staff_bot.build_messages([], actions=[action])
        bubble = messages[0]["contents"]["contents"][0]
        texts = _flatten_texts(bubble)
        assert "#128 · ห้อง 204" in texts
        assert "แอร์" in texts
        assert "รอช่าง" in texts
        assert "วันนี้" in texts
        buttons = bubble["footer"]["contents"]
        data_by_label = {b["action"]["label"]: b["action"]["data"] for b in buttons}
        assert data_by_label["เพิ่มรูป"] == "cmd=addphoto&id=128"
        assert data_by_label["ยกเลิก"] == "cmd=cancel&id=128"

    def test_empty_list_is_one_plain_line(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "list_work_orders",
            lambda reporter_badge, active=True, limit=10: {"orders": []},
        )
        action = _action(staff_bot.COMMAND_MINE)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.MINE_EMPTY_TEXT}]

    def test_housekeeping_dark_gives_the_fixed_unavailable_line(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "list_work_orders",
            lambda reporter_badge, active=True, limit=10: None,
        )
        action = _action(staff_bot.COMMAND_MINE)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.TICKET_UNAVAILABLE_TEXT}]

    def test_bubble_never_carries_emoji(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "list_work_orders",
            lambda reporter_badge, active=True, limit=10: {
                "orders": [self._order_view(location="ห้อง 204\U0001F525")],
            },
        )
        action = _action(staff_bot.COMMAND_MINE)
        messages = staff_bot.build_messages([], actions=[action])
        blob = json.dumps(messages, ensure_ascii=False)
        assert "\U0001F525" not in blob


# ===========================================================================
# สถานะ / งาน <id> lookup (phase 4)
# ===========================================================================

class TestStatus:
    def _order_view(self, **overrides):
        order = {
            "id": 128, "location": "ห้อง 204", "categoryLabel": "แอร์",
            "statusLabel": "รอช่าง", "ageDays": 0, "photoCount": 0,
            "reporterBadge": "7001",
        }
        order.update(overrides)
        return order

    @pytest.mark.parametrize("text", ["สถานะ 128", "งาน 128"])
    def test_status_word_routes_with_the_order_id(self, text):
        routed = staff_bot.route_event(_direct_text(text), lambda u: True)
        assert routed.command == staff_bot.COMMAND_STATUS
        assert routed.order_id == 128

    def test_status_word_without_digits_is_not_a_command(self):
        routed = staff_bot.route_event(_direct_text("งานเยอะมากวันนี้"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_PALETTE

    def test_mine_word_still_wins_over_the_status_prefix(self):
        routed = staff_bot.route_event(_direct_text("งานของฉัน"), lambda u: True)
        assert routed.command == staff_bot.COMMAND_MINE

    def test_reporter_gets_the_bubble(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view()},
        )
        action = _action(staff_bot.COMMAND_STATUS, order_id=128, badge="7001")
        messages = staff_bot.build_messages([], actions=[action])
        assert len(messages) == 1
        assert messages[0]["type"] == "flex"
        texts = _flatten_texts(messages[0])
        assert "#128 · ห้อง 204" in texts

    def test_reception_grant_holder_gets_the_bubble(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view(reporterBadge="9999")},
        )
        action = _action(
            staff_bot.COMMAND_STATUS, order_id=128, badge="7001", is_reception=True,
        )
        messages = staff_bot.build_messages([], actions=[action])
        assert messages[0]["type"] == "flex"

    def test_somebody_elses_ticket_is_forbidden(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"order": self._order_view(reporterBadge="9999")},
        )
        action = _action(
            staff_bot.COMMAND_STATUS, order_id=128, badge="7001", is_reception=False,
        )
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.STATUS_FORBIDDEN_TEXT}]

    def test_unknown_id_is_404(self, monkeypatch):
        monkeypatch.setattr(
            housekeeping_client, "get_work_order",
            lambda order_id: {"error": "ไม่พบรายการแจ้งซ่อมนี้"},
        )
        action = _action(staff_bot.COMMAND_STATUS, order_id=999)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": "ไม่พบงาน #999 ค่ะ"}]

    def test_housekeeping_dark_gives_the_fixed_unavailable_line(self, monkeypatch):
        monkeypatch.setattr(housekeeping_client, "get_work_order", lambda order_id: None)
        action = _action(staff_bot.COMMAND_STATUS, order_id=128)
        messages = staff_bot.build_messages([], actions=[action])
        assert messages == [{"type": "text", "text": staff_bot.TICKET_UNAVAILABLE_TEXT}]


# ===========================================================================
# Webhook-level: end-to-end report creation, immediacy, slot-digest isolation
# ===========================================================================

class TestTicketWebhookIntegration:
    def test_report_creates_a_ticket_and_the_command_is_immediate(
        self, test_client, test_db, staff_oa_enabled, dispatcher,
    ):
        _employee(test_db, badge="7001", line_user_id="U-emp")
        response = _signed_post(test_client, {"events": [
            _group_text("น้องคะ แจ้งซ่อม 204 แอร์ไม่เย็น", user_id="U-emp"),
        ]})
        assert response.status_code == 200
        assert len(dispatcher.commands) == 1
        routed = dispatcher.commands[0]
        assert routed.command == staff_bot.COMMAND_REPORT
        assert routed.identity_known is True
        assert routed.badge == "7001"
        assert routed.quiet_seconds == 0.0

    def test_a_report_inside_a_slot_window_never_marks_the_slot(
        self, test_client, test_db, staff_oa_enabled, dispatcher,
    ):
        # Same shape as test_staff_bot.py's slot-digest tests: a report is
        # phase 1/2's "a command lands inside an open window" case, and only
        # COMMAND_DIGEST (not COMMAND_REPORT) is allowed to cover a slot.
        from app.models.models import StaffBotSlotMark

        _employee(test_db, badge="7001", line_user_id="U-emp")
        response = _signed_post(test_client, {"events": [
            _group_text("น้องคะ แจ้งซ่อม 204 แอร์ไม่เย็น", user_id="U-emp"),
        ]})
        assert response.status_code == 200
        assert test_db.query(StaffBotSlotMark).count() == 0

    def test_bare_report_creates_a_ticket_and_the_command_is_immediate(
        self, test_client, test_db, staff_oa_enabled, dispatcher, monkeypatch,
    ):
        # Rule 1c: a bare group report is a RoutedCommand indistinguishable
        # (bar its user_id) from the summoned form, so everything downstream
        # — identity, ticket creation, photo claiming — is unchanged.
        _employee(test_db, badge="7001", line_user_id="U-emp")
        captured = {}

        def _create(payload):
            captured.update(payload)
            return {"order": {
                "id": 128, "property": "hf", "propertyLabel": "HF",
                "locationKind": "room", "roomNo": "204", "commonArea": None,
                "location": "ห้อง 204", "category": "aircon", "categoryLabel": "แอร์",
                "urgent": True, "detailText": "แอร์ไม่เย็น ด่วน", "status": "new",
                "statusLabel": "รอช่าง", "reporterBadge": "7001", "reporterName": "สมชาย",
                "createdAt": "2026-09-06T09:00:00.000Z",
                "updatedAt": "2026-09-06T09:00:00.000Z",
                "ageDays": 0, "photoCount": 0,
            }}

        monkeypatch.setattr(housekeeping_client, "create_work_order", _create)
        staff_bot.get_photo_buffer().add("Cgroup", "U-emp", "img-1")

        response = _signed_post(test_client, {"events": [
            _group_text("แจ้งซ่อม 204 แอร์ไม่เย็น ด่วน", user_id="U-emp"),
        ]})
        assert response.status_code == 200
        assert len(dispatcher.commands) == 1
        routed = dispatcher.commands[0]
        assert routed.command == staff_bot.COMMAND_REPORT
        assert routed.report_text == "204 แอร์ไม่เย็น ด่วน"
        assert routed.identity_known is True
        assert routed.badge == "7001"
        assert routed.quiet_seconds == 0.0

        # Ticket creation and photo attaching, exactly as the summoned form
        # (TestCreateTicket) already exercises via build_reply.
        built = staff_bot.build_reply([], actions=[routed])
        assert captured["room_no"] == "204"
        assert captured["urgent"] is True
        assert len(built.pending_uploads) == 1
        assert built.pending_uploads[0].order_id == 128
        assert built.pending_uploads[0].message_ids == ["img-1"]

    def test_a_bare_report_inside_a_slot_window_never_marks_the_slot(
        self, test_client, test_db, staff_oa_enabled, dispatcher,
    ):
        from app.models.models import StaffBotSlotMark

        _employee(test_db, badge="7001", line_user_id="U-emp")
        response = _signed_post(test_client, {"events": [
            _group_text("แจ้งซ่อม 204 แอร์ไม่เย็น", user_id="U-emp"),
        ]})
        assert response.status_code == 200
        assert test_db.query(StaffBotSlotMark).count() == 0

    def test_a_command_logs_no_report_text(
        self, test_client, test_db, staff_oa_enabled, dispatcher, caplog,
    ):
        _employee(test_db, badge="7001", line_user_id="U-emp")
        with caplog.at_level("INFO"):
            _signed_post(test_client, {"events": [
                _group_text("น้องคะ แจ้งซ่อม 204 แอร์ไม่เย็นลับสุดยอด", user_id="U-emp"),
            ]})
        assert "staff-bot command: event=message source=group chat=Cgroup" in caplog.text
        assert "แอร์ไม่เย็นลับสุดยอด" not in caplog.text

    def test_the_asyncio_dispatcher_replies_the_bubble_and_never_touches_the_network(
        self, monkeypatch, staff_oa_enabled,
    ):
        import asyncio

        sent = []
        monkeypatch.setattr(
            service, "reply_messages",
            lambda token, messages: sent.append((token, messages)),
        )
        monkeypatch.setattr(
            housekeeping_client, "create_work_order",
            lambda payload: {"order": {
                "id": 9, "propertyLabel": "HF", "location": "ห้อง 204",
                "categoryLabel": "แอร์", "urgent": False, "detailText": "แอร์ไม่เย็น",
                "reporterName": "สมชาย",
            }},
        )

        async def _scenario():
            dispatcher = staff_bot.AsyncioBotDispatcher()
            dispatcher.submit_command(_action(
                staff_bot.COMMAND_REPORT, reply_token="tok-1", quiet_seconds=0.01,
                report_text="204 แอร์ไม่เย็น",
            ))
            deadline = asyncio.get_event_loop().time() + 3
            while not sent and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.01)

        asyncio.run(_scenario())

        assert len(sent) == 1
        token, messages = sent[0]
        assert token == "tok-1"
        assert messages[0]["altText"] == "รับเรื่องแล้ว #9"
