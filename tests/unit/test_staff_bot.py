"""Unit tests for the staff bot (HF ภายใน) — app.services.staff_bot.

Phase 1 of the staff bot: summoned in the all-staff LINE group or messaged
1:1, it answers งานค้าง with housekeeping's open แจ้งซ่อม digest. Design
authority: hf-erp ADR "The staff bot answers only with reply tokens; LINE
meters pushes per recipient".

What these tests exist to protect, in order of how expensive the mistake is:

  * ZERO METERED SENDS. Everything rides a reply token. The autouse
    ``_block_line_http`` fixture below replaces ``requests`` in BOTH outbound
    modules with an object that raises on any attribute access, so no test in
    this file can reach api.line.me or the housekeeping container by any code
    path — the same belt-and-braces as tests/unit/test_hk_escalation.py,
    which exists because an unstubbed path in this repo really did fire live
    requests at LINE.
  * NEVER RACE A HUMAN BURST. The debounce rules (quiet timer, token refresh,
    45 s cap, coalescing, per-chat isolation) are tested against a fake clock,
    so the suite waits zero real seconds for a 45-second rule.
  * DISCARD BEFORE LOGGING. Group chat that is not a summon must produce no
    command at all — the privacy commitment to staff.
  * The follow path is untouched (its own tests still pass, and one here pins
    that a follow produces no bot command).
"""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.api import staff_oa as staff_oa_module
from app.models.models import Employee
from app.services import guest_feedback_client, housekeeping_client, staff_bot
from app.services import staff_oa_service as service

TOKEN = "test-channel-access-token"
SECRET = "test-channel-secret"
WEBHOOK_PATH = "/api/public/staff-oa/webhook"

BANGKOK = timezone(timedelta(hours=7))


# ---------------------------------------------------------------------------
# Boundaries: nothing in this module may dial out
# ---------------------------------------------------------------------------


class _ExplodingRequests:
    """Stand-in for the ``requests`` module that refuses every call."""

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
    """No test here may reach api.line.me, housekeeping or guest-feedback,
    by any route."""
    monkeypatch.setattr(service, "requests", _ExplodingRequests("LINE"))
    monkeypatch.setattr(
        housekeeping_client, "requests", _ExplodingRequests("housekeeping")
    )
    monkeypatch.setattr(
        guest_feedback_client, "requests", _ExplodingRequests("guest-feedback")
    )


@pytest.fixture(autouse=True)
def _dark_housekeeping(monkeypatch):
    """Default: the digest read is dark, so nothing tries to fetch it."""
    monkeypatch.delenv("HOUSEKEEPING_STAFF_BOT_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _dark_guest_feedback(monkeypatch):
    """Default: the guest-requests read is dark, so nothing tries to fetch it."""
    monkeypatch.delenv("GUEST_FEEDBACK_BASE_URL", raising=False)
    monkeypatch.delenv("GUEST_FEEDBACK_READER_SECRET", raising=False)


@pytest.fixture(autouse=True)
def _idle_requests_gate(monkeypatch):
    """Default: no chat ever has pending guest requests, so plain group
    chatter never auto-upgrades to a command — tests that want the auto-offer
    install their own gate."""
    monkeypatch.setattr(
        staff_bot, "get_requests_gate",
        lambda: staff_bot.PendingRequestsGate(fetch=lambda: None),
    )


class _CollectingDispatcher:
    """Records what the router files, without any timers or a loop."""

    def __init__(self):
        self.commands = []
        self.messages = []

    def submit_command(self, command):
        self.commands.append(command)

    def submit_message(self, chat_key, reply_token):
        self.messages.append((chat_key, reply_token))


@pytest.fixture
def dispatcher(monkeypatch):
    """Swap the process-wide dispatcher for a recording one."""
    collected = _CollectingDispatcher()
    monkeypatch.setattr(staff_bot, "get_dispatcher", lambda: collected)
    return collected


class _Clock:
    """A hand-cranked monotonic clock."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------------------
# Event builders
# ---------------------------------------------------------------------------


def _group_text(text, reply_token="reply-g", message=None, group_id="Cgroup"):
    payload = {"type": "text", "id": "m1", "text": text}
    if message:
        payload.update(message)
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "group", "groupId": group_id, "userId": "Uspeaker"},
        "message": payload,
    }


def _direct_text(text, user_id="U-emp", reply_token="reply-d"):
    return {
        "type": "message",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": user_id},
        "message": {"type": "text", "id": "m1", "text": text},
    }


def _postback(data, reply_token="reply-p", source=None):
    return {
        "type": "postback",
        "replyToken": reply_token,
        "source": source or {"type": "group", "groupId": "Cgroup"},
        "postback": {"data": data},
    }


def _route(event, known=()):
    return staff_bot.route_event(event, lambda user_id: user_id in known)


# ===========================================================================
# Summon grammar
# ===========================================================================


class TestSummonGrammar:
    @pytest.mark.parametrize("particle", ["คะ", "ค่ะ", "ครับ", "คับ"])
    def test_every_particle_summons_the_palette(self, particle):
        routed = _route(_group_text(f"น้อง{particle}"))
        assert isinstance(routed, staff_bot.RoutedCommand)
        assert routed.command == staff_bot.COMMAND_PALETTE

    @pytest.mark.parametrize(
        "text",
        ["น้อง คะ", "น้อง   ครับ", "  น้องค่ะ  ", "น้องคับ "],
    )
    def test_spaces_around_the_summon_are_tolerated(self, text):
        routed = _route(_group_text(text))
        assert isinstance(routed, staff_bot.RoutedCommand)
        assert routed.command == staff_bot.COMMAND_PALETTE

    @pytest.mark.parametrize("word", ["งานค้าง", "งานซ่อมค้าง", "แจ้งซ่อมค้าง"])
    def test_a_command_word_after_the_summon_runs_the_digest(self, word):
        routed = _route(_group_text(f"น้องคะ {word}"))
        assert routed.command == staff_bot.COMMAND_DIGEST

    @pytest.mark.parametrize("word", ["คำขอ", "คำขอลูกค้า", "guest requests"])
    def test_a_command_word_after_the_summon_runs_the_guest_requests(self, word):
        routed = _route(_group_text(f"น้องคะ {word}"))
        assert routed.command == staff_bot.COMMAND_REQUESTS

    def test_unrecognised_words_after_the_summon_open_the_palette(self):
        routed = _route(_group_text("น้องคะ ช่วยดูให้หน่อย"))
        assert routed.command == staff_bot.COMMAND_PALETTE

    def test_a_self_mention_summons_and_its_span_is_stripped(self):
        # "@HF ภายใน งานค้าง" — the mention occupies the first 12 characters.
        text = "@HF ภายใน งานค้าง"
        routed = _route(_group_text(text, message={"mention": {"mentionees": [
            {"index": 0, "length": 9, "isSelf": True, "userId": "Ubot"},
        ]}}))
        assert routed.command == staff_bot.COMMAND_DIGEST

    def test_a_mention_of_somebody_else_is_not_a_summon(self):
        routed = _route(_group_text("@สมชาย งานค้าง", message={"mention": {
            "mentionees": [{"index": 0, "length": 7, "userId": "Usomchai"}],
        }}))
        assert isinstance(routed, staff_bot.RoutedMessage)

    def test_a_bare_mention_opens_the_palette(self):
        routed = _route(_group_text("@HF ภายใน", message={"mention": {
            "mentionees": [{"index": 0, "length": 9, "isSelf": True}],
        }}))
        assert routed.command == staff_bot.COMMAND_PALETTE

    def test_nong_without_a_particle_is_ordinary_chat(self):
        # THE false-trigger case: staff talking about a น้อง, not to the bot.
        routed = _route(_group_text("น้องเอาข้าวไหม"))
        assert isinstance(routed, staff_bot.RoutedMessage)

    def test_a_command_word_alone_in_a_group_is_not_a_summon(self):
        # Reads are open, but the group still has to ASK. Otherwise every
        # mention of งานค้าง in staff chat would make the bot interrupt.
        routed = _route(_group_text("งานค้าง"))
        assert isinstance(routed, staff_bot.RoutedMessage)

    def test_a_summon_mid_sentence_does_not_count(self):
        routed = _route(_group_text("ฝากบอกน้องคะ"))
        assert isinstance(routed, staff_bot.RoutedMessage)

    def test_group_noise_never_becomes_a_command(self, dispatcher, test_db):
        # The privacy rule, at the handler edge: a non-summon message files
        # no command (and therefore logs nothing about it).
        assert staff_bot.handle_event(_group_text("พรุ่งนี้เข้ากี่โมง"), test_db) is False
        assert dispatcher.commands == []
        assert dispatcher.messages == [("Cgroup", "reply-g")]

    def test_a_photo_in_the_group_only_refreshes_the_token(self):
        event = _group_text("", message={"type": "image"})
        routed = _route(event)
        assert isinstance(routed, staff_bot.RoutedMessage)
        assert routed.reply_token == "reply-g"


# ===========================================================================
# 1:1 rules
# ===========================================================================


class TestDirectChat:
    def test_a_known_employee_gets_the_palette_for_any_text(self):
        routed = _route(_direct_text("สวัสดีค่ะ"), known={"U-emp"})
        assert routed.command == staff_bot.COMMAND_PALETTE
        assert routed.chat_key == "U-emp"

    @pytest.mark.parametrize("word", ["งานค้าง", "งานซ่อมค้าง", "แจ้งซ่อมค้าง"])
    def test_a_bare_command_word_runs_that_command(self, word):
        routed = _route(_direct_text(word), known={"U-emp"})
        assert routed.command == staff_bot.COMMAND_DIGEST

    @pytest.mark.parametrize("word", ["คำขอ", "คำขอลูกค้า", "guest requests"])
    def test_a_bare_guest_requests_word_runs_that_command(self, word):
        routed = _route(_direct_text(word), known={"U-emp"})
        assert routed.command == staff_bot.COMMAND_REQUESTS
        assert routed.source_type == "user"

    def test_no_summon_is_needed_in_a_one_to_one_chat(self):
        routed = _route(_direct_text("น้องคะ"), known={"U-emp"})
        assert routed.command == staff_bot.COMMAND_PALETTE

    def test_an_unknown_sender_gets_the_onboarding_reply(self):
        routed = _route(_direct_text("งานค้าง", user_id="U-stranger"))
        assert routed.command == staff_bot.COMMAND_ONBOARDING

    def test_the_onboarding_text_is_the_one_the_follow_path_uses(self):
        messages = staff_bot.build_messages([staff_bot.COMMAND_ONBOARDING])
        assert messages == [
            {"type": "text", "text": staff_oa_module.ONBOARDING_REPLY_TEXT}
        ]

    def test_an_inactive_employee_is_a_stranger(self, test_db):
        test_db.add(Employee(
            badge_number="9001", display_name="left", is_active=False,
            is_hidden=False, line_user_id="U-left",
        ))
        test_db.commit()
        assert staff_bot.is_linked_employee(test_db, "U-left") is False

    def test_an_active_employee_resolves(self, test_db):
        test_db.add(Employee(
            badge_number="9002", display_name="maid", is_active=True,
            is_hidden=False, line_user_id="U-maid",
        ))
        test_db.commit()
        assert staff_bot.is_linked_employee(test_db, "U-maid") is True

    def test_one_to_one_waits_two_seconds_not_fifteen(self):
        routed = _route(_direct_text("งานค้าง"), known={"U-emp"})
        assert routed.quiet_seconds == staff_bot.COMMAND_QUIET_SECONDS == 0.0
        group = _route(_group_text("น้องคะ"))
        assert group.quiet_seconds == staff_bot.COMMAND_QUIET_SECONDS == 0.0


# ===========================================================================
# Postback
# ===========================================================================


class TestPostback:
    def test_cmd_digest_runs_the_digest(self):
        routed = _route(_postback("cmd=digest"))
        assert routed.command == staff_bot.COMMAND_DIGEST
        assert routed.event_type == "postback"

    def test_cmd_palette_opens_the_palette(self):
        routed = _route(_postback("cmd=palette"))
        assert routed.command == staff_bot.COMMAND_PALETTE

    def test_cmd_requests_runs_the_guest_requests_command(self):
        routed = _route(_postback("cmd=requests"))
        assert routed.command == staff_bot.COMMAND_REQUESTS

    def test_extra_parameters_do_not_confuse_the_parse(self):
        routed = _route(_postback("cmd=digest&id=17"))
        assert routed.command == staff_bot.COMMAND_DIGEST

    @pytest.mark.parametrize("data", ["cmd=ticket", "cmd=", "", "digest", "x=1"])
    def test_an_unknown_postback_is_ignored(self, data):
        assert _route(_postback(data)) is None

    def test_a_postback_works_in_a_one_to_one_chat_too(self):
        routed = _route(_postback(
            "cmd=digest", source={"type": "user", "userId": "U-emp"}
        ))
        assert routed.command == staff_bot.COMMAND_DIGEST
        assert routed.chat_key == "U-emp"

    def test_the_palette_button_carries_the_postback_the_router_understands(self):
        button = staff_bot.palette_message()["contents"]["footer"]["contents"][0]
        routed = _route(_postback(button["action"]["data"]))
        assert routed.command == staff_bot.COMMAND_DIGEST

    def test_the_requests_button_carries_the_postback_the_router_understands(self):
        button = staff_bot.palette_message()["contents"]["footer"]["contents"][1]
        routed = _route(_postback(button["action"]["data"]))
        assert routed.command == staff_bot.COMMAND_REQUESTS


# ===========================================================================
# Group auto-offer of guest requests — route_event stays pure, the I/O and
# the 10 s per-chat cache live in handle_event_detail via PendingRequestsGate
# ===========================================================================


class TestGroupAutoOffer:
    def test_route_event_never_upgrades_plain_chat_on_its_own(self):
        # route_event does no I/O — a non-summon group message is always a
        # RoutedMessage from route_event's point of view, pending or not.
        routed = _route(_group_text("ผ้าเช็ดตัวหมดค่ะ"))
        assert isinstance(routed, staff_bot.RoutedMessage)

    def test_plain_group_chat_becomes_a_command_when_requests_are_pending(
        self, dispatcher, test_db, monkeypatch,
    ):
        monkeypatch.setattr(
            staff_bot, "get_requests_gate",
            lambda: staff_bot.PendingRequestsGate(fetch=lambda: _requests_payload()),
        )
        handled = staff_bot.handle_event_detail(
            _group_text("ผ้าเช็ดตัวหมดค่ะ", reply_token="reply-g"), test_db,
        )
        assert handled.command is True
        assert [c.command for c in dispatcher.commands] == [staff_bot.COMMAND_REQUESTS]
        assert dispatcher.commands[0].source_type == "group"
        assert dispatcher.commands[0].reply_token == "reply-g"

    def test_plain_group_chat_stays_a_message_when_nothing_is_pending(
        self, dispatcher, test_db, monkeypatch,
    ):
        monkeypatch.setattr(
            staff_bot, "get_requests_gate",
            lambda: staff_bot.PendingRequestsGate(fetch=lambda: None),
        )
        handled = staff_bot.handle_event_detail(_group_text("ผ้าเช็ดตัวหมดค่ะ"), test_db)
        assert handled.command is False
        assert dispatcher.commands == []

    def test_a_summon_is_unaffected_by_pending_requests(self, dispatcher, test_db, monkeypatch):
        # A summon is already a RoutedCommand before the gate ever runs —
        # the digest/palette rules are untouched by this feature.
        monkeypatch.setattr(
            staff_bot, "get_requests_gate",
            lambda: staff_bot.PendingRequestsGate(fetch=lambda: _requests_payload()),
        )
        staff_bot.handle_event_detail(_group_text("น้องคะ"), test_db)
        assert [c.command for c in dispatcher.commands] == [staff_bot.COMMAND_PALETTE]

    def test_the_pending_check_is_cached_per_chat_for_ten_seconds(self):
        clock = _Clock()
        fetch_calls = []

        def _fetch():
            fetch_calls.append(True)
            return _requests_payload()

        gate = staff_bot.PendingRequestsGate(clock=clock, fetch=_fetch)

        assert gate.has_pending("Cgroup") is True
        assert gate.has_pending("Cgroup") is True
        assert len(fetch_calls) == 1  # second call served from cache

        clock.advance(staff_bot.REQUESTS_AUTO_TRIGGER_CACHE_SECONDS - 0.01)
        assert gate.has_pending("Cgroup") is True
        assert len(fetch_calls) == 1

        clock.advance(0.02)
        assert gate.has_pending("Cgroup") is True
        assert len(fetch_calls) == 2  # cache expired, checked again

    def test_the_cache_is_per_chat(self):
        clock = _Clock()
        fetch_calls = []

        def _fetch():
            fetch_calls.append(True)
            return _requests_payload()

        gate = staff_bot.PendingRequestsGate(clock=clock, fetch=_fetch)
        gate.has_pending("C1")
        gate.has_pending("C2")
        assert len(fetch_calls) == 2

    def test_a_room_message_is_also_a_candidate(self, dispatcher, test_db, monkeypatch):
        monkeypatch.setattr(
            staff_bot, "get_requests_gate",
            lambda: staff_bot.PendingRequestsGate(fetch=lambda: _requests_payload()),
        )
        event = {
            "type": "message",
            "replyToken": "reply-r",
            "source": {"type": "room", "roomId": "R1", "userId": "Uspeaker"},
            "message": {"type": "text", "id": "m1", "text": "hello"},
        }
        staff_bot.handle_event_detail(event, test_db)
        assert [c.command for c in dispatcher.commands] == [staff_bot.COMMAND_REQUESTS]
        assert dispatcher.commands[0].source_type == "room"

    def test_a_one_to_one_chat_is_never_upgraded_by_the_gate(
        self, dispatcher, test_db, monkeypatch,
    ):
        # 1:1 never produces a RoutedMessage in the first place (route_event
        # always turns it into a command), so the gate never even runs.
        gate_calls = []
        monkeypatch.setattr(
            staff_bot, "get_requests_gate",
            lambda: staff_bot.PendingRequestsGate(
                fetch=lambda: gate_calls.append(True) or _requests_payload()
            ),
        )
        test_db.add(Employee(
            badge_number="9010", display_name="maid", is_active=True,
            is_hidden=False, line_user_id="U-emp",
        ))
        test_db.commit()
        staff_bot.handle_event_detail(_direct_text("สวัสดีค่ะ"), test_db)
        assert [c.command for c in dispatcher.commands] == [staff_bot.COMMAND_PALETTE]
        assert gate_calls == []


# ===========================================================================
# Debounce state machine (fake clock — no real waiting)
# ===========================================================================


class TestDebounce:
    def _debouncer(self, clock):
        self.scheduled = []
        return staff_bot.ReplyDebouncer(
            clock=clock, scheduler=self.scheduled.append
        )

    def test_it_fires_after_the_quiet_window(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_command("C1", staff_bot.COMMAND_DIGEST, "tok-1", 15.0)

        assert self.scheduled == [15.0]
        clock.advance(14.9)
        assert debouncer.pop_due() == []
        clock.advance(0.1)
        due = debouncer.pop_due()
        assert [(p.chat_key, p.reply_token) for p in due] == [("C1", "tok-1")]
        # And it is gone: one burst, one reply.
        assert debouncer.next_delay() is None

    def test_a_later_message_refreshes_the_token_and_restarts_the_timer(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_command("C1", staff_bot.COMMAND_DIGEST, "tok-1", 15.0)

        clock.advance(10)
        debouncer.note_message("C1", "tok-2")
        clock.advance(5)  # 15 s after the command, but only 5 s of quiet
        assert debouncer.pop_due() == []

        clock.advance(10)
        due = debouncer.pop_due()
        assert [p.reply_token for p in due] == ["tok-2"]

    def test_ordinary_chat_never_creates_a_pending_reply(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_message("C9", "tok-x")
        assert debouncer.pending_for("C9") is None
        assert debouncer.next_delay() is None

    def test_the_forty_five_second_cap_wins_over_a_chatty_group(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_command("C1", staff_bot.COMMAND_DIGEST, "tok-1", 15.0)

        for step in range(1, 5):  # a message every 10 s: 10, 20, 30, 40
            clock.advance(10)
            debouncer.note_message("C1", f"tok-{step + 1}")

        clock.advance(4)  # t = 44
        assert debouncer.pop_due() == []
        clock.advance(1)  # t = 45, exactly the cap
        due = debouncer.pop_due()
        assert [p.reply_token for p in due] == ["tok-5"]

    def test_two_commands_in_one_burst_coalesce_into_one_reply(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_command("C1", staff_bot.COMMAND_PALETTE, "tok-1", 15.0)
        clock.advance(3)
        debouncer.note_command("C1", staff_bot.COMMAND_DIGEST, "tok-2", 15.0)

        clock.advance(15)
        due = debouncer.pop_due()
        assert len(due) == 1
        assert due[0].commands == {
            staff_bot.COMMAND_PALETTE, staff_bot.COMMAND_DIGEST
        }
        assert due[0].reply_token == "tok-2"  # the newest token

    def test_the_same_command_twice_is_still_one_message(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_command("C1", staff_bot.COMMAND_DIGEST, "tok-1", 15.0)
        debouncer.note_command("C1", staff_bot.COMMAND_DIGEST, "tok-2", 15.0)
        clock.advance(15)
        due = debouncer.pop_due()
        assert len(due) == 1
        assert due[0].commands == {staff_bot.COMMAND_DIGEST}

    def test_chats_are_isolated_from_each_other(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_command("C-group", staff_bot.COMMAND_DIGEST, "tok-g", 15.0)
        debouncer.note_command("U-direct", staff_bot.COMMAND_PALETTE, "tok-u", 2.0)

        clock.advance(2)
        due = debouncer.pop_due()
        assert [p.chat_key for p in due] == ["U-direct"]
        # The group's own timer is untouched by the 1:1 firing.
        clock.advance(13)
        assert [p.chat_key for p in debouncer.pop_due()] == ["C-group"]

    def test_a_message_in_another_chat_does_not_delay_this_one(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_command("C1", staff_bot.COMMAND_DIGEST, "tok-1", 15.0)
        clock.advance(10)
        debouncer.note_message("C2", "tok-other")
        clock.advance(5)
        assert [p.chat_key for p in debouncer.pop_due()] == ["C1"]

    def test_the_scheduler_is_told_when_to_wake_up(self):
        clock = _Clock()
        debouncer = self._debouncer(clock)
        debouncer.note_command("C1", staff_bot.COMMAND_DIGEST, "tok-1", 15.0)
        clock.advance(5)
        debouncer.note_message("C1", "tok-2")
        assert self.scheduled == [15.0, 15.0]


# ===========================================================================
# Rendering
# ===========================================================================


def _payload(**overrides):
    payload = {
        "generatedAt": "2026-09-05T15:10:00+07:00",
        "properties": [
            {
                "property": "hf", "label": "HF", "openCount": 2, "truncated": 0,
                "orders": [
                    {
                        "id": 128, "urgent": True, "location": "ห้อง 204",
                        "category": "แอร์", "detail": "แอร์ไม่เย็น",
                        "status": "in_progress", "statusLabel": "กำลังซ่อม",
                        "ageDays": 2, "createdAt": "2026-09-03T09:12:00.000Z",
                    },
                    {
                        "id": 130, "urgent": False, "location": "ห้อง 311",
                        "category": "ประปา", "detail": None,
                        "status": "new", "statusLabel": "รอช่าง",
                        "ageDays": 0, "createdAt": "2026-09-05T09:00:00.000Z",
                    },
                ],
            },
            {
                "property": "hfville", "label": "HF Ville", "openCount": 0,
                "truncated": 0, "orders": [],
            },
        ],
    }
    payload.update(overrides)
    return payload


class TestDigestRendering:
    def test_a_normal_digest(self):
        text = staff_bot.render_digest(_payload())
        lines = text.split("\n")
        assert lines[0] == "งานซ่อมค้าง 2 งาน (5 ก.ย. 15:10)"
        assert lines[1] == ""
        assert lines[2] == "HF (2)"
        assert lines[3] == "ด่วน ห้อง 204 แอร์ · แอร์ไม่เย็น · 2 วัน · กำลังซ่อม"
        # No detail: the category stands in for it.
        assert lines[4] == "ห้อง 311 ประปา · ประปา · วันนี้ · รอช่าง"

    def test_a_property_with_nothing_open_is_left_out(self):
        assert "HF Ville" not in staff_bot.render_digest(_payload())

    def test_both_properties_appear_when_both_have_work(self):
        payload = _payload()
        payload["properties"][1].update({
            "openCount": 1,
            "orders": [{
                "id": 9, "urgent": False, "location": "ล็อบบี้",
                "category": "ไฟฟ้า", "detail": "ไฟกระพริบ",
                "status": "new", "statusLabel": "รอช่าง", "ageDays": 5,
            }],
        })
        text = staff_bot.render_digest(payload)
        assert text.startswith("งานซ่อมค้าง 3 งาน (")
        assert "\n\nHF Ville (1)\nล็อบบี้ ไฟฟ้า · ไฟกระพริบ · 5 วัน · รอช่าง" in text

    def test_truncation_is_announced(self):
        payload = _payload()
        payload["properties"][0]["openCount"] = 25
        payload["properties"][0]["truncated"] = 23
        text = staff_bot.render_digest(payload)
        assert "HF (25)" in text
        assert text.endswith("และอีก 23 งาน")

    def test_an_empty_board_says_so(self):
        payload = _payload()
        payload["properties"][0].update({"openCount": 0, "orders": []})
        assert staff_bot.render_digest(payload) == "ไม่มีงานซ่อมค้าง (5 ก.ย. 15:10)"

    def test_a_dark_or_broken_housekeeping_gets_one_fixed_thai_line(self):
        assert staff_bot.render_digest(None) == staff_bot.DIGEST_UNAVAILABLE_TEXT
        assert staff_bot.render_digest("nope") == staff_bot.DIGEST_UNAVAILABLE_TEXT

    def test_emoji_in_a_human_typed_detail_are_stripped(self):
        payload = _payload()
        payload["properties"][0]["orders"][0]["detail"] = "แอร์ไม่เย็น 😭🔥"
        text = staff_bot.render_digest(payload)
        assert "😭" not in text and "🔥" not in text
        assert "ด่วน ห้อง 204 แอร์ · แอร์ไม่เย็น · 2 วัน · กำลังซ่อม" in text

    def test_a_detail_that_is_only_emoji_falls_back_to_the_category(self):
        payload = _payload()
        payload["properties"][0]["orders"][0]["detail"] = "🔥🔥"
        assert "ด่วน ห้อง 204 แอร์ · แอร์ · 2 วัน · กำลังซ่อม" in (
            staff_bot.render_digest(payload)
        )

    def test_a_missing_generated_at_falls_back_to_now(self):
        payload = _payload(generatedAt=None)
        now = datetime(2026, 2, 9, 8, 5, tzinfo=BANGKOK)
        assert "(9 ก.พ. 08:05)" in staff_bot.render_digest(payload, now=now)

    def test_a_utc_generated_at_is_shown_in_bangkok_time(self):
        payload = _payload(generatedAt="2026-09-05T08:10:00Z")
        assert "(5 ก.ย. 15:10)" in staff_bot.render_digest(payload)

    def test_the_digest_stays_under_line_s_message_cap(self):
        payload = _payload()
        payload["properties"][0]["openCount"] = 400
        payload["properties"][0]["orders"] = [
            {
                "id": index, "urgent": True, "location": "ห้อง 1234",
                "category": "เครื่องปรับอากาศ",
                "detail": "รายละเอียดยาวมาก " * 5,
                "statusLabel": "กำลังซ่อม", "ageDays": 9,
            }
            for index in range(400)
        ]
        text = staff_bot.render_digest(payload)
        assert len(text) <= staff_bot.MAX_MESSAGE_CHARS

    def test_no_bot_string_carries_an_emoji(self):
        payload = _payload()
        for text in (
            staff_bot.render_digest(payload),
            staff_bot.render_digest(None),
            staff_bot.DIGEST_UNAVAILABLE_TEXT,
            json.dumps(staff_bot.palette_message(), ensure_ascii=False),
        ):
            assert staff_bot.strip_pictographs(text) == staff_bot.strip_pictographs(
                text
            )
            assert not staff_bot._PICTOGRAPH_PATTERN.search(text)


class TestPalette:
    def test_the_bubble_says_what_the_spec_says(self):
        message = staff_bot.palette_message()
        assert message["type"] == "flex"
        assert message["altText"] == "เมนู HF ภายใน"
        bubble = message["contents"]
        assert bubble["header"]["contents"][0]["text"] == "HF ภายใน"
        assert bubble["body"]["contents"][0]["text"] == "มีอะไรให้ช่วยคะ"
        action = bubble["footer"]["contents"][0]["action"]
        assert action == {
            "type": "postback",
            "label": "งานค้าง แจ้งซ่อม",
            "data": "cmd=digest",
            "displayText": "งานค้าง",
        }
        requests_action = bubble["footer"]["contents"][1]["action"]
        assert requests_action == {
            "type": "postback",
            "label": "คำขอลูกค้า",
            "data": "cmd=requests",
            "displayText": "คำขอลูกค้า",
        }

    def test_a_coalesced_reply_is_palette_then_digest(self, monkeypatch):
        monkeypatch.setattr(housekeeping_client, "fetch_digest", lambda: None)
        messages = staff_bot.build_messages(
            {staff_bot.COMMAND_DIGEST, staff_bot.COMMAND_PALETTE}
        )
        assert [m["type"] for m in messages] == ["flex", "text"]
        assert messages[1]["text"] == staff_bot.DIGEST_UNAVAILABLE_TEXT

    def test_a_reply_never_exceeds_line_s_five_object_cap(self, monkeypatch):
        monkeypatch.setattr(housekeeping_client, "fetch_digest", lambda: None)
        messages = staff_bot.build_messages(
            [staff_bot.COMMAND_PALETTE] * 9 + [staff_bot.COMMAND_DIGEST]
        )
        assert len(messages) <= staff_bot.MAX_REPLY_MESSAGES


# ===========================================================================
# Guest requests (คำขอลูกค้า) — rendering, build_messages, the ids threaded
# through for the delivery confirm
# ===========================================================================


def _requests_payload(count=2, text="รายการคำขอ 2 รายการ", items=None):
    return {
        "ok": True,
        "count": count,
        "text": text,
        "items": items if items is not None else [
            {"id": "fb-1", "ref": "A1"}, {"id": "fb-2", "ref": "A2"},
        ],
    }


class TestRequestsRendering:
    def test_prints_guest_feedback_s_own_text_as_is_when_pending(self):
        payload = _requests_payload()
        assert staff_bot.render_requests(payload) == payload["text"]

    def test_a_reachable_read_with_nothing_pending_says_so(self):
        payload = _requests_payload(count=0, text="")
        assert staff_bot.render_requests(payload) == staff_bot.REQUESTS_NONE_TEXT

    def test_a_dark_or_broken_read_gets_one_fixed_thai_line(self):
        assert staff_bot.render_requests(None) == staff_bot.REQUESTS_UNAVAILABLE_TEXT

    def test_build_messages_includes_the_requests_text(self, monkeypatch):
        monkeypatch.setattr(
            guest_feedback_client, "fetch_pending", lambda: _requests_payload()
        )
        messages = staff_bot.build_messages([staff_bot.COMMAND_REQUESTS])
        assert messages == [{"type": "text", "text": _requests_payload()["text"]}]

    def test_build_messages_carries_the_dark_line_when_the_read_fails(self, monkeypatch):
        monkeypatch.setattr(guest_feedback_client, "fetch_pending", lambda: None)
        messages = staff_bot.build_messages([staff_bot.COMMAND_REQUESTS])
        assert messages == [
            {"type": "text", "text": staff_bot.REQUESTS_UNAVAILABLE_TEXT}
        ]

    def test_build_messages_collects_the_ids_used_to_render(self, monkeypatch):
        monkeypatch.setattr(
            guest_feedback_client, "fetch_pending", lambda: _requests_payload()
        )
        collected = []
        staff_bot.build_messages([staff_bot.COMMAND_REQUESTS], collected)
        assert collected == ["fb-1", "fb-2"]

    def test_no_ids_are_collected_when_nothing_is_pending(self, monkeypatch):
        monkeypatch.setattr(
            guest_feedback_client, "fetch_pending",
            lambda: _requests_payload(count=0, text="", items=[]),
        )
        collected = []
        staff_bot.build_messages([staff_bot.COMMAND_REQUESTS], collected)
        assert collected == []


# ===========================================================================
# guest_feedback_client — fail closed, never raise
# ===========================================================================


class TestGuestFeedbackClient:
    def test_either_env_unset_dials_nothing(self, monkeypatch):
        monkeypatch.delenv("GUEST_FEEDBACK_BASE_URL", raising=False)
        monkeypatch.delenv("GUEST_FEEDBACK_READER_SECRET", raising=False)
        assert guest_feedback_client.is_enabled() is False
        assert guest_feedback_client.fetch_pending() is None
        assert guest_feedback_client.confirm_delivered(["fb-1"]) is False

    def test_only_the_url_set_is_still_dark(self, monkeypatch):
        monkeypatch.setenv("GUEST_FEEDBACK_BASE_URL", "http://feedback:4080")
        monkeypatch.delenv("GUEST_FEEDBACK_READER_SECRET", raising=False)
        assert guest_feedback_client.fetch_pending() is None

    def _wire_get(self, monkeypatch, response=None, boom=None):
        calls = {}

        def _get(url, headers=None, timeout=None, **kwargs):
            calls.update(url=url, headers=headers, timeout=timeout)
            if boom:
                raise boom
            return response

        monkeypatch.setenv("GUEST_FEEDBACK_BASE_URL", "http://feedback:4080")
        monkeypatch.setenv("GUEST_FEEDBACK_READER_SECRET", "shared-secret")
        monkeypatch.setattr(
            guest_feedback_client, "requests",
            type("R", (), {"get": staticmethod(_get)}),
        )
        return calls

    def test_fetch_pending_calls_the_documented_endpoint(self, monkeypatch):
        payload = _requests_payload()
        calls = self._wire_get(monkeypatch, _Response(200, payload))

        assert guest_feedback_client.fetch_pending() == payload
        assert calls["url"] == "http://feedback:4080/api/internal/line/pending"
        assert calls["headers"] == {"X-Reader-Secret": "shared-secret"}
        assert calls["timeout"] == 2

    @pytest.mark.parametrize("status", [401, 403, 500, 503])
    def test_a_refusal_is_a_miss_not_an_exception(self, monkeypatch, status):
        self._wire_get(monkeypatch, _Response(status, {}))
        assert guest_feedback_client.fetch_pending() is None

    def test_a_timeout_is_a_miss(self, monkeypatch):
        self._wire_get(monkeypatch, boom=OSError("timed out"))
        assert guest_feedback_client.fetch_pending() is None

    def test_a_non_json_body_is_a_miss(self, monkeypatch):
        self._wire_get(monkeypatch, _Response(200, raises=True))
        assert guest_feedback_client.fetch_pending() is None

    def test_a_json_array_is_a_miss(self, monkeypatch):
        self._wire_get(monkeypatch, _Response(200, ["nope"]))
        assert guest_feedback_client.fetch_pending() is None

    def _wire_post(self, monkeypatch, response=None, boom=None):
        calls = {}

        def _post(url, headers=None, json=None, timeout=None, **kwargs):
            calls.update(url=url, headers=headers, json=json, timeout=timeout)
            if boom:
                raise boom
            return response

        monkeypatch.setenv("GUEST_FEEDBACK_BASE_URL", "http://feedback:4080")
        monkeypatch.setenv("GUEST_FEEDBACK_READER_SECRET", "shared-secret")
        monkeypatch.setattr(
            guest_feedback_client, "requests",
            type("R", (), {"post": staticmethod(_post)}),
        )
        return calls

    def test_confirm_delivered_posts_the_documented_body(self, monkeypatch):
        calls = self._wire_post(monkeypatch, _Response(200, {"ok": True, "marked": 2}))

        assert guest_feedback_client.confirm_delivered(["fb-1", "fb-2"]) is True
        assert calls["url"] == "http://feedback:4080/api/internal/line/delivered"
        assert calls["headers"] == {"X-Reader-Secret": "shared-secret"}
        assert calls["json"] == {"ids": ["fb-1", "fb-2"], "method": "reply"}
        assert calls["timeout"] == 2

    def test_confirm_delivered_with_no_ids_dials_nothing(self, monkeypatch):
        # `requests` here is the un-stubbed real module — a real dial would
        # fail loudly rather than silently pass.
        monkeypatch.setenv("GUEST_FEEDBACK_BASE_URL", "http://feedback:4080")
        monkeypatch.setenv("GUEST_FEEDBACK_READER_SECRET", "shared-secret")
        assert guest_feedback_client.confirm_delivered([]) is False

    @pytest.mark.parametrize("status", [401, 403, 500, 503])
    def test_confirm_delivered_refusal_is_a_miss(self, monkeypatch, status):
        self._wire_post(monkeypatch, _Response(status, {}))
        assert guest_feedback_client.confirm_delivered(["fb-1"]) is False

    def test_confirm_delivered_timeout_is_a_miss(self, monkeypatch):
        self._wire_post(monkeypatch, boom=OSError("timed out"))
        assert guest_feedback_client.confirm_delivered(["fb-1"]) is False


# ===========================================================================
# housekeeping_client — fail closed, never raise
# ===========================================================================


class _Response:
    def __init__(self, status_code=200, payload=None, raises=False):
        self.status_code = status_code
        self._payload = payload
        self._raises = raises
        self.text = "{}"

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._payload


class TestHousekeepingClient:
    def test_an_unset_token_dials_nothing(self, monkeypatch):
        # `requests` is the exploding stub, so a dial-out would fail loudly.
        monkeypatch.delenv("HOUSEKEEPING_STAFF_BOT_TOKEN", raising=False)
        assert housekeeping_client.is_enabled() is False
        assert housekeeping_client.fetch_digest() is None

    def test_a_blank_token_is_also_dark(self, monkeypatch):
        monkeypatch.setenv("HOUSEKEEPING_STAFF_BOT_TOKEN", "   ")
        assert housekeeping_client.fetch_digest() is None

    def _wire(self, monkeypatch, response=None, boom=None):
        calls = {}

        def _get(url, headers=None, timeout=None, **kwargs):
            calls.update(url=url, headers=headers, timeout=timeout)
            if boom:
                raise boom
            return response

        monkeypatch.setenv("HOUSEKEEPING_STAFF_BOT_TOKEN", "shared-token")
        monkeypatch.setattr(
            housekeeping_client, "requests", type("R", (), {"get": staticmethod(_get)})
        )
        return calls

    def test_it_calls_the_locked_url_with_a_bearer_token(self, monkeypatch):
        monkeypatch.delenv("HOUSEKEEPING_INTERNAL_URL", raising=False)
        calls = self._wire(monkeypatch, _Response(200, _payload()))

        assert housekeeping_client.fetch_digest() == _payload()
        assert calls["url"] == "http://housekeeping:4070/internal/staff-bot/digest"
        assert calls["headers"] == {"Authorization": "Bearer shared-token"}
        assert calls["timeout"] == 5

    def test_the_base_url_is_overridable(self, monkeypatch):
        calls = self._wire(monkeypatch, _Response(200, {}))
        monkeypatch.setenv("HOUSEKEEPING_INTERNAL_URL", "http://hk.test:9/")
        housekeeping_client.fetch_digest()
        assert calls["url"] == "http://hk.test:9/internal/staff-bot/digest"

    @pytest.mark.parametrize("status", [401, 403, 500, 503])
    def test_a_refusal_is_a_miss_not_an_exception(self, monkeypatch, status):
        self._wire(monkeypatch, _Response(status, {}))
        assert housekeeping_client.fetch_digest() is None

    def test_a_timeout_is_a_miss(self, monkeypatch):
        self._wire(monkeypatch, boom=OSError("timed out"))
        assert housekeeping_client.fetch_digest() is None

    def test_a_non_json_body_is_a_miss(self, monkeypatch):
        self._wire(monkeypatch, _Response(200, raises=True))
        assert housekeeping_client.fetch_digest() is None

    def test_a_json_array_is_a_miss(self, monkeypatch):
        self._wire(monkeypatch, _Response(200, ["nope"]))
        assert housekeeping_client.fetch_digest() is None


# ===========================================================================
# The asyncio adapter (the only part with a loop)
# ===========================================================================


class TestAsyncioDispatcher:
    def test_one_burst_becomes_exactly_one_reply(self, monkeypatch, staff_oa_enabled):
        sent = []
        monkeypatch.setattr(
            service, "reply_messages",
            lambda token, messages: sent.append((token, messages)),
        )
        monkeypatch.setattr(housekeeping_client, "fetch_digest", lambda: _payload())

        async def _scenario():
            dispatcher = staff_bot.AsyncioBotDispatcher()
            dispatcher.submit_command(staff_bot.RoutedCommand(
                chat_key="C1", command=staff_bot.COMMAND_PALETTE,
                reply_token="tok-1", quiet_seconds=0.01,
                event_type="message", source_type="group",
            ))
            dispatcher.submit_command(staff_bot.RoutedCommand(
                chat_key="C1", command=staff_bot.COMMAND_DIGEST,
                reply_token="tok-2", quiet_seconds=0.01,
                event_type="message", source_type="group",
            ))
            deadline = time.monotonic() + 3
            while not sent and time.monotonic() < deadline:
                await asyncio.sleep(0.01)

        asyncio.run(_scenario())

        assert len(sent) == 1
        token, messages = sent[0]
        assert token == "tok-2"  # the newest token in the burst
        assert [m["type"] for m in messages] == ["flex", "text"]
        assert messages[1]["text"].startswith("งานซ่อมค้าง 2 งาน")

    def test_a_line_failure_does_not_escape_the_task(self, monkeypatch, staff_oa_enabled):
        def _explode(token, messages):
            raise service.StaffOaApiError("reply messages", 500, "boom")

        monkeypatch.setattr(service, "reply_messages", _explode)
        monkeypatch.setattr(housekeeping_client, "fetch_digest", lambda: None)

        pending = staff_bot.PendingReply(
            chat_key="C1", commands={staff_bot.COMMAND_DIGEST},
            reply_token="tok", quiet_seconds=0.01,
        )
        asyncio.run(staff_bot.AsyncioBotDispatcher()._reply(pending))

    def test_a_pending_reply_without_a_token_sends_nothing(self, monkeypatch, staff_oa_enabled):
        sent = []
        monkeypatch.setattr(
            service, "reply_messages",
            lambda token, messages: sent.append(token),
        )
        monkeypatch.setattr(housekeeping_client, "fetch_digest", lambda: None)
        pending = staff_bot.PendingReply(
            chat_key="C1", commands={staff_bot.COMMAND_DIGEST}, reply_token="",
        )
        asyncio.run(staff_bot.AsyncioBotDispatcher()._reply(pending))
        assert sent == []

    def test_a_dark_staff_oa_sends_nothing(self, monkeypatch):
        """Fail closed: no credentials, no send — not even a stale pending."""
        monkeypatch.delenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("STAFF_OA_CHANNEL_SECRET", raising=False)
        sent = []
        monkeypatch.setattr(
            service, "reply_messages", lambda token, messages: sent.append(token)
        )
        monkeypatch.setattr(housekeeping_client, "fetch_digest", lambda: None)
        pending = staff_bot.PendingReply(
            chat_key="C1", commands={staff_bot.COMMAND_DIGEST}, reply_token="tok",
        )
        asyncio.run(staff_bot.AsyncioBotDispatcher()._reply(pending))
        assert sent == []

    def test_a_group_requests_reply_confirms_delivery_exactly_once(
        self, monkeypatch, staff_oa_enabled,
    ):
        monkeypatch.setattr(service, "reply_messages", lambda token, messages: None)
        monkeypatch.setattr(
            guest_feedback_client, "fetch_pending", lambda: _requests_payload()
        )
        confirmed = []
        monkeypatch.setattr(
            guest_feedback_client, "confirm_delivered",
            lambda ids: confirmed.append(list(ids)) or True,
        )
        pending = staff_bot.PendingReply(
            chat_key="Cgroup", commands={staff_bot.COMMAND_REQUESTS},
            reply_token="tok", source_type="group",
        )
        asyncio.run(staff_bot.AsyncioBotDispatcher()._reply(pending))
        assert confirmed == [["fb-1", "fb-2"]]

    def test_a_room_requests_reply_also_confirms(self, monkeypatch, staff_oa_enabled):
        monkeypatch.setattr(service, "reply_messages", lambda token, messages: None)
        monkeypatch.setattr(
            guest_feedback_client, "fetch_pending", lambda: _requests_payload()
        )
        confirmed = []
        monkeypatch.setattr(
            guest_feedback_client, "confirm_delivered",
            lambda ids: confirmed.append(list(ids)) or True,
        )
        pending = staff_bot.PendingReply(
            chat_key="Croom", commands={staff_bot.COMMAND_REQUESTS},
            reply_token="tok", source_type="room",
        )
        asyncio.run(staff_bot.AsyncioBotDispatcher()._reply(pending))
        assert len(confirmed) == 1

    def test_a_one_to_one_requests_reply_never_confirms(self, monkeypatch, staff_oa_enabled):
        monkeypatch.setattr(service, "reply_messages", lambda token, messages: None)
        monkeypatch.setattr(
            guest_feedback_client, "fetch_pending", lambda: _requests_payload()
        )
        confirmed = []
        monkeypatch.setattr(
            guest_feedback_client, "confirm_delivered",
            lambda ids: confirmed.append(list(ids)) or True,
        )
        pending = staff_bot.PendingReply(
            chat_key="U-emp", commands={staff_bot.COMMAND_REQUESTS},
            reply_token="tok", source_type="user",
        )
        asyncio.run(staff_bot.AsyncioBotDispatcher()._reply(pending))
        assert confirmed == []

    def test_a_failed_line_reply_never_confirms_delivery(self, monkeypatch, staff_oa_enabled):
        def _explode(token, messages):
            raise service.StaffOaApiError("reply messages", 500, "boom")

        monkeypatch.setattr(service, "reply_messages", _explode)
        monkeypatch.setattr(
            guest_feedback_client, "fetch_pending", lambda: _requests_payload()
        )
        confirmed = []
        monkeypatch.setattr(
            guest_feedback_client, "confirm_delivered",
            lambda ids: confirmed.append(list(ids)) or True,
        )
        pending = staff_bot.PendingReply(
            chat_key="Cgroup", commands={staff_bot.COMMAND_REQUESTS},
            reply_token="tok", source_type="group",
        )
        asyncio.run(staff_bot.AsyncioBotDispatcher()._reply(pending))
        assert confirmed == []

    def test_no_pending_requests_means_no_confirm_call(self, monkeypatch, staff_oa_enabled):
        monkeypatch.setattr(service, "reply_messages", lambda token, messages: None)
        monkeypatch.setattr(guest_feedback_client, "fetch_pending", lambda: None)
        confirmed = []
        monkeypatch.setattr(
            guest_feedback_client, "confirm_delivered",
            lambda ids: confirmed.append(list(ids)) or True,
        )
        pending = staff_bot.PendingReply(
            chat_key="Cgroup", commands={staff_bot.COMMAND_REQUESTS},
            reply_token="tok", source_type="group",
        )
        asyncio.run(staff_bot.AsyncioBotDispatcher()._reply(pending))
        assert confirmed == []


class TestReplyMessages:
    """The one new LINE call — still a REPLY, never a push."""

    def test_it_posts_the_reply_endpoint_with_every_message(self, monkeypatch):
        calls = []

        class _Recorder:
            @staticmethod
            def post(url, headers=None, json=None, timeout=None, **kwargs):
                calls.append({"url": url, "json": json})
                return _Response(200)

        monkeypatch.setattr(service, "requests", _Recorder)
        monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)

        service.reply_messages("tok", [{"type": "text", "text": "a"}])

        assert calls[0]["url"] == "https://api.line.me/v2/bot/message/reply"
        assert calls[0]["json"] == {
            "replyToken": "tok", "messages": [{"type": "text", "text": "a"}]
        }

    def test_an_empty_message_list_is_a_no_op(self, monkeypatch):
        # `requests` is still the exploding stub: any call would blow up.
        service.reply_messages("tok", [])

    def test_more_than_five_messages_are_sliced(self, monkeypatch):
        calls = []

        class _Recorder:
            @staticmethod
            def post(url, headers=None, json=None, timeout=None, **kwargs):
                calls.append(json)
                return _Response(200)

        monkeypatch.setattr(service, "requests", _Recorder)
        service.reply_messages(
            "tok", [{"type": "text", "text": str(i)} for i in range(9)]
        )
        assert len(calls[0]["messages"]) == 5


# ===========================================================================
# Webhook integration (FastAPI test client; LINE + housekeeping stubbed)
# ===========================================================================


@pytest.fixture
def staff_oa_enabled(monkeypatch):
    monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", SECRET)


def _signed_post(client, payload):
    body = json.dumps(payload).encode("utf-8")
    digest = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    return client.post(
        WEBHOOK_PATH,
        content=body,
        headers={
            "X-Line-Signature": base64.b64encode(digest).decode("ascii"),
            "Content-Type": "application/json",
        },
    )


class TestWebhookIntegration:
    def test_a_summon_files_one_command_and_still_answers_line_fast(
        self, test_client, test_db, staff_oa_enabled, dispatcher
    ):
        response = _signed_post(test_client, {"events": [_group_text("น้องคะ งานค้าง")]})

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 1
        assert [(c.chat_key, c.command, c.reply_token) for c in dispatcher.commands] == [
            ("Cgroup", staff_bot.COMMAND_DIGEST, "reply-g")
        ]

    def test_group_chatter_files_nothing_but_a_token_refresh(
        self, test_client, test_db, staff_oa_enabled, dispatcher
    ):
        response = _signed_post(
            test_client, {"events": [_group_text("ผ้าเช็ดตัวหมดค่ะ")]}
        )

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 0
        assert dispatcher.commands == []

    def test_a_known_employee_in_a_one_to_one_chat_gets_a_command(
        self, test_client, test_db, staff_oa_enabled, dispatcher
    ):
        test_db.add(Employee(
            badge_number="7001", display_name="maid", is_active=True,
            is_hidden=False, line_user_id="U-emp",
        ))
        test_db.commit()

        _signed_post(test_client, {"events": [_direct_text("งานค้าง")]})

        assert [c.command for c in dispatcher.commands] == [staff_bot.COMMAND_DIGEST]

    def test_a_known_employee_asking_for_requests_in_a_one_to_one_gets_that_command(
        self, test_client, test_db, staff_oa_enabled, dispatcher
    ):
        test_db.add(Employee(
            badge_number="7002", display_name="maid", is_active=True,
            is_hidden=False, line_user_id="U-emp",
        ))
        test_db.commit()

        _signed_post(test_client, {"events": [_direct_text("คำขอลูกค้า")]})

        assert [c.command for c in dispatcher.commands] == [staff_bot.COMMAND_REQUESTS]
        assert dispatcher.commands[0].source_type == "user"

    def test_plain_group_chat_files_a_requests_command_when_pending(
        self, test_client, test_db, staff_oa_enabled, dispatcher, monkeypatch,
    ):
        monkeypatch.setattr(
            staff_bot, "get_requests_gate",
            lambda: staff_bot.PendingRequestsGate(fetch=lambda: _requests_payload()),
        )
        response = _signed_post(
            test_client, {"events": [_group_text("ผ้าเช็ดตัวหมดค่ะ")]}
        )

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 1
        assert [c.command for c in dispatcher.commands] == [staff_bot.COMMAND_REQUESTS]

    def test_an_unknown_one_to_one_sender_gets_the_onboarding_command(
        self, test_client, test_db, staff_oa_enabled, dispatcher
    ):
        _signed_post(
            test_client, {"events": [_direct_text("สวัสดี", user_id="U-nobody")]}
        )
        assert [c.command for c in dispatcher.commands] == [
            staff_bot.COMMAND_ONBOARDING
        ]

    def test_a_redelivery_is_ignored(
        self, test_client, test_db, staff_oa_enabled, dispatcher
    ):
        event = _group_text("น้องคะ งานค้าง")
        event["deliveryContext"] = {"isRedelivery": True}

        response = _signed_post(test_client, {"events": [event]})

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 0
        assert dispatcher.commands == []

    def test_a_first_delivery_is_not_ignored(
        self, test_client, test_db, staff_oa_enabled, dispatcher
    ):
        event = _group_text("น้องคะ")
        event["deliveryContext"] = {"isRedelivery": False}
        _signed_post(test_client, {"events": [event]})
        assert len(dispatcher.commands) == 1

    def test_a_join_event_logs_the_group_id_and_nothing_else(
        self, test_client, test_db, staff_oa_enabled, dispatcher, caplog
    ):
        with caplog.at_level("INFO"):
            response = _signed_post(test_client, {"events": [{
                "type": "join",
                "replyToken": "reply-j",
                "source": {"type": "group", "groupId": "Cnewgroup"},
            }]})

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 0
        assert dispatcher.commands == []
        assert "staff-bot joined group Cnewgroup" in caplog.text

    def test_a_command_logs_only_type_source_and_chat_id(
        self, test_client, test_db, staff_oa_enabled, dispatcher, caplog
    ):
        with caplog.at_level("INFO"):
            _signed_post(
                test_client,
                {"events": [_group_text("น้องคะ ขอดูงานค้างหน่อยเรื่องแอร์ห้อง 204")]},
            )

        assert "staff-bot command: event=message source=group chat=Cgroup" in caplog.text
        # The message text is NEVER written down.
        assert "แอร์ห้อง 204" not in caplog.text
        assert "Uspeaker" not in caplog.text

    def test_the_follow_path_is_untouched(
        self, test_client, test_db, staff_oa_enabled, dispatcher, monkeypatch
    ):
        replies = []
        monkeypatch.setattr(service, "get_rich_menu_list", lambda: [])
        monkeypatch.setattr(
            service, "reply_text_message",
            lambda token, text: replies.append((token, text)),
        )

        response = _signed_post(test_client, {"events": [{
            "type": "follow",
            "replyToken": "reply-f",
            "source": {"type": "user", "userId": "U-stranger"},
        }]})

        assert response.json()["follow_events_handled"] == 1
        assert response.json()["bot_commands"] == 0
        assert replies == [("reply-f", staff_oa_module.ONBOARDING_REPLY_TEXT)]
        assert dispatcher.commands == []

    def test_an_unhandled_event_type_is_silent(
        self, test_client, test_db, staff_oa_enabled, dispatcher
    ):
        response = _signed_post(test_client, {"events": [
            {"type": "unfollow", "source": {"type": "user", "userId": "U-x"}},
            {"type": "memberJoined", "source": {"type": "group", "groupId": "Cg"}},
        ]})

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 0
        assert dispatcher.commands == []
        assert dispatcher.messages == []

    def test_a_router_failure_never_breaks_the_webhook(
        self, test_client, test_db, staff_oa_enabled, monkeypatch
    ):
        def _explode():
            raise RuntimeError("dispatcher is broken")

        monkeypatch.setattr(staff_bot, "get_dispatcher", _explode)

        response = _signed_post(test_client, {"events": [_group_text("น้องคะ")]})

        # LINE must still see 200 or it retries the whole delivery forever.
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestReplyTokenClaims:
    """handle_event_detail tells the webhook which reply tokens the bot will
    spend, so the guest-feedback relay can be handed the rest."""

    @pytest.fixture
    def bot(self, monkeypatch):
        dispatcher = staff_bot.AsyncioBotDispatcher()
        dispatcher.debouncer = staff_bot.ReplyDebouncer(scheduler=lambda delay: None)
        monkeypatch.setattr(staff_bot, "get_dispatcher", lambda: dispatcher)
        return dispatcher

    def test_a_command_claims_its_token(self, bot, test_db):
        handled = staff_bot.handle_event_detail(_group_text("น้องคะ", reply_token="t1"), test_db)
        assert handled == staff_bot.HandledEvent(command=True, claims_reply_token=True)

    def test_plain_chat_in_an_idle_chat_claims_nothing(self, bot, test_db):
        handled = staff_bot.handle_event_detail(
            _group_text("พรุ่งนี้เข้ากี่โมง", reply_token="t1"), test_db
        )
        assert handled == staff_bot.HandledEvent(command=False, claims_reply_token=False)

    def test_plain_chat_while_a_reply_is_pending_claims_the_newer_token(self, bot, test_db):
        staff_bot.handle_event_detail(_group_text("น้องคะ", reply_token="t1"), test_db)
        handled = staff_bot.handle_event_detail(_group_text("ขอบคุณค่ะ", reply_token="t2"), test_db)
        assert handled == staff_bot.HandledEvent(command=False, claims_reply_token=True)
        key = staff_bot._chat_key({"type": "group", "groupId": "Cgroup"})
        assert bot.debouncer.pending_for(key).reply_token == "t2"

    def test_a_pending_reply_in_one_chat_claims_nothing_in_another(self, bot, test_db):
        staff_bot.handle_event_detail(_group_text("น้องคะ", reply_token="t1"), test_db)
        handled = staff_bot.handle_event_detail(
            _group_text("ขอบคุณค่ะ", reply_token="t9", group_id="Cother"), test_db
        )
        assert handled.claims_reply_token is False

    def test_redelivery_and_join_claim_nothing(self, bot, test_db):
        redelivered = _group_text("น้องคะ", reply_token="t1")
        redelivered["deliveryContext"] = {"isRedelivery": True}
        assert staff_bot.handle_event_detail(redelivered, test_db) == staff_bot._NOT_HANDLED
        join = {"type": "join", "source": {"type": "group", "groupId": "Cgroup"}}
        assert staff_bot.handle_event_detail(join, test_db) == staff_bot._NOT_HANDLED

    def test_handle_event_still_reports_commands_only(self, bot, test_db):
        assert staff_bot.handle_event(_group_text("น้องคะ", reply_token="t1"), test_db) is True
        assert staff_bot.handle_event(_group_text("ขอบคุณค่ะ", reply_token="t2"), test_db) is False


class TestCommandsAnswerAtOnce:
    """Owner rule 2026-09-05: the quiet wait is for scheduled reports, never
    for a command reply. A command is due the moment it is filed."""

    def test_a_group_command_is_due_immediately(self):
        clock = [100.0]
        debouncer = staff_bot.ReplyDebouncer(clock=lambda: clock[0])
        routed = staff_bot.route_event(_group_text("น้องคะ งานค้าง", reply_token="t1"), lambda _u: True)
        debouncer.note_command(routed.chat_key, routed.command, routed.reply_token,
                               quiet_seconds=routed.quiet_seconds)
        assert debouncer.next_delay() == 0.0
        due = debouncer.pop_due()
        assert [p.reply_token for p in due] == ["t1"]

    def test_slot_quiet_is_still_fifteen_seconds_for_phase_two(self):
        assert staff_bot.SLOT_QUIET_SECONDS == 15.0
