"""Unit tests for the staff OA webhook (app.api.staff_oa).

POST /api/public/staff-oa/webhook: dark until configured (503), rejects
bad signatures (401), and on `follow` events links the follower's Role
Menu — or, for a stranger, a Thai onboarding reply. All LINE Messaging API
calls are mocked.

NOBODY GETS A BASE MENU ANY MORE
--------------------------------
Until 2026-08-14 a stranger (and any employee with no menu-relevant grant)
was linked to the `base` menu. The owner then removed the last ungated
button — the clock-in tile — so `base` has zero buttons, no base rich menu
is deployed at all, and there is nothing to link those followers to. The
onboarding REPLY is unchanged and now carries the whole stranger path: it
is the only thing a new follower gets, which is why several tests below
moved their assertion from "linked to rm-base" to "replied, linked
nothing".
"""
import base64
import hashlib
import hmac
import json
import threading
import time

import pytest

from app.api import staff_oa as staff_oa_module
from app.models.models import Employee, EmployeeAppGrant
from app.services import staff_bot
from app.services import staff_oa_service as service

TOKEN = "test-channel-access-token"
SECRET = "test-channel-secret"
WEBHOOK_PATH = "/api/public/staff-oa/webhook"

# Since the Employee Hub was re-scoped to a maid tool (2026-08-14),
# `housekeeping` is the only grant that changes a follower's menu, so it is
# what "their role menu" means here. `payroll` is still a real grant people
# hold, but its tile is gone — a follower holding only it lands on `base`,
# which is a different thing from a stranger landing on `base`.
MENU_GRANT = "housekeeping"
MENU_IRRELEVANT_GRANT = "payroll"


class _NullBotDispatcher:
    """Swallows what the staff bot files; this module tests the OTHER paths.

    Since 2026-09-05 the same webhook also feeds the staff bot
    (app/services/staff_bot.py), whose dispatcher is process-wide and holds
    pending replies BEYOND the request that filed them. Letting these tests
    write into the real one would leak a pending reply — and a stale reply
    token — into whatever test drains it next. The bot's own behaviour is
    covered in tests/unit/test_staff_bot.py.
    """

    def submit_command(self, command):
        pass

    def submit_message(self, chat_key, reply_token):
        pass

    def submit_slot_digest(self, ref, reply_token, trigger):
        pass


@pytest.fixture(autouse=True)
def _isolate_staff_bot(monkeypatch):
    monkeypatch.setattr(staff_bot, "get_dispatcher", _NullBotDispatcher)


@pytest.fixture
def staff_oa_enabled(monkeypatch):
    monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", SECRET)


@pytest.fixture
def line_api(monkeypatch):
    """Mock every LINE call the webhook path can make; record them.

    The deployed-menu list is what the sync script actually leaves on the
    channel now: ONLY the housekeeping variant. There is no
    `staffhub:base:*` menu, because base has no buttons to render — listing
    a fake one here would let these tests pass against a channel state that
    cannot occur.
    """
    calls = {"linked": [], "unlinked": [], "replies": []}
    monkeypatch.setattr(
        service, "get_rich_menu_list",
        lambda: [
            {"richMenuId": "rm-housekeeping", "name": "staffhub:base+housekeeping:bbb"},
        ],
    )
    monkeypatch.setattr(
        service, "link_rich_menu_to_user",
        lambda user_id, menu_id: calls["linked"].append((user_id, menu_id)),
    )
    # Every LINE call reachable from a follow event must be stubbed here, not
    # just the ones today's assertions look at. This one was missing and the
    # gap was invisible until link_role_menu_for_line_user started unlinking:
    # the suite then issued a REAL DELETE to api.line.me and the test failed
    # on a live HTTP 401 rather than on anything it meant to assert.
    monkeypatch.setattr(
        service, "unlink_rich_menu_from_user",
        lambda user_id: calls["unlinked"].append(user_id),
    )
    monkeypatch.setattr(
        service, "reply_text_message",
        lambda reply_token, text: calls["replies"].append((reply_token, text)),
    )
    return calls


def _signed_post(client, payload, secret=SECRET, signature=None):
    body = json.dumps(payload).encode("utf-8")
    if signature is None:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("ascii")
    return client.post(
        WEBHOOK_PATH,
        content=body,
        headers={"X-Line-Signature": signature, "Content-Type": "application/json"},
    )


def _follow_event(user_id, reply_token="reply-1"):
    return {
        "type": "follow",
        "replyToken": reply_token,
        "source": {"type": "user", "userId": user_id},
    }


def _make_employee(test_db, badge, **overrides):
    defaults = dict(
        badge_number=badge, display_name=f"emp-{badge}",
        is_active=True, is_hidden=False,
    )
    defaults.update(overrides)
    employee = Employee(**defaults)
    test_db.add(employee)
    test_db.commit()
    return employee


class TestWebhookFailClosed:
    def test_dark_returns_503_when_credentials_unset(self, test_client, monkeypatch):
        monkeypatch.delenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("STAFF_OA_CHANNEL_SECRET", raising=False)
        response = _signed_post(test_client, {"events": []})
        assert response.status_code == 503

    def test_missing_signature_returns_401(self, test_client, staff_oa_enabled):
        response = test_client.post(WEBHOOK_PATH, json={"events": []})
        assert response.status_code == 401

    def test_wrong_signature_returns_401(self, test_client, staff_oa_enabled):
        response = _signed_post(
            test_client, {"events": []}, signature="bm90LXRoZS1zaWduYXR1cmU="
        )
        assert response.status_code == 401

    def test_signature_from_wrong_secret_returns_401(self, test_client, staff_oa_enabled):
        response = _signed_post(test_client, {"events": []}, secret="other-secret")
        assert response.status_code == 401

    def test_malformed_body_with_valid_signature_returns_400(
        self, test_client, staff_oa_enabled
    ):
        body = b"not-json"
        digest = hmac.new(SECRET.encode(), body, hashlib.sha256).digest()
        response = test_client.post(
            WEBHOOK_PATH,
            content=body,
            headers={"X-Line-Signature": base64.b64encode(digest).decode()},
        )
        assert response.status_code == 400


class TestFollowEvents:
    def test_known_employee_gets_their_role_menu(
        self, test_client, test_db, staff_oa_enabled, line_api
    ):
        # Re-pointed from the `ota` grant, whose tile was removed on
        # 2026-08-14 — an ota holder now resolves to `base`, which would make
        # this test indistinguishable from the stranger case below.
        _make_employee(test_db, "1001", line_user_id="U-maid")
        test_db.add(EmployeeAppGrant(employee_badge_number="1001", app_id=MENU_GRANT))
        test_db.commit()

        response = _signed_post(test_client, {"events": [_follow_event("U-maid")]})

        assert response.status_code == 200
        assert response.json()["follow_events_handled"] == 1
        assert line_api["linked"] == [("U-maid", "rm-housekeeping")]
        assert line_api["replies"] == []  # known employees get no lecture

    def test_employee_with_only_menu_irrelevant_grants_gets_no_menu_and_no_lecture(
        self, test_client, test_db, staff_oa_enabled, line_api
    ):
        # Was ..._gets_base_without_a_lecture, asserting ("U-accounts",
        # "rm-base"). Since the clock-in tile left on 2026-08-14 there is no
        # base menu, so a KNOWN non-maid employee is linked to nothing at
        # all. The half that still matters is unchanged and is the reason
        # this test exists: no onboarding reply. That reply says the
        # follower's LINE account is not linked to the employee registry,
        # which would be flatly wrong here — this person is on file.
        _make_employee(test_db, "1003", line_user_id="U-accounts")
        test_db.add(
            EmployeeAppGrant(
                employee_badge_number="1003", app_id=MENU_IRRELEVANT_GRANT
            )
        )
        test_db.commit()

        response = _signed_post(test_client, {"events": [_follow_event("U-accounts")]})

        assert response.status_code == 200
        assert response.json()["follow_events_handled"] == 1  # handled, not failed
        assert line_api["linked"] == []
        assert line_api["replies"] == []

    def test_unknown_follower_gets_the_onboarding_reply_and_no_menu(
        self, test_client, test_db, staff_oa_enabled, line_api
    ):
        # Was ..._gets_base_menu_and_onboarding_reply. With base empty there
        # is no menu to pin on a stranger, so the reply is the entire
        # stranger path — and therefore must still fire.
        response = _signed_post(
            test_client, {"events": [_follow_event("U-stranger", "reply-42")]}
        )

        assert response.status_code == 200
        assert line_api["linked"] == []
        assert len(line_api["replies"]) == 1
        reply_token, text = line_api["replies"][0]
        assert reply_token == "reply-42"
        assert text == staff_oa_module.ONBOARDING_REPLY_TEXT
        assert "qr-checkin/onboard" in text  # points at Q-badge onboarding

    def test_a_still_deployed_base_menu_is_the_only_thing_a_stranger_gets(
        self, test_client, test_db, staff_oa_enabled, line_api, monkeypatch
    ):
        # The stranger branch links `base` when a base menu EXISTS, and that
        # branch is still live code — a base button coming back restores it
        # in one commit. Model the channel that has one (also the real
        # window between removing the button and running the sync) and pin
        # that the behaviour is unchanged there, so the empty-base tests
        # above are proving the empty case rather than a dead branch.
        monkeypatch.setattr(
            service, "get_rich_menu_list",
            lambda: [
                {"richMenuId": "rm-base", "name": "staffhub:base:aaa"},
                {
                    "richMenuId": "rm-housekeeping",
                    "name": "staffhub:base+housekeeping:bbb",
                },
            ],
        )

        response = _signed_post(test_client, {"events": [_follow_event("U-stranger")]})

        assert response.status_code == 200
        assert line_api["linked"] == [("U-stranger", "rm-base")]
        assert len(line_api["replies"]) == 1

    def test_inactive_employee_is_treated_as_unknown(
        self, test_client, test_db, staff_oa_enabled, line_api
    ):
        # Still the stranger path (reply sent); the link half of the old
        # assertion went with the base menu.
        _make_employee(test_db, "1002", line_user_id="U-left", is_active=False)

        _signed_post(test_client, {"events": [_follow_event("U-left")]})

        assert line_api["linked"] == []
        assert len(line_api["replies"]) == 1

    def test_non_follow_events_are_ignored(
        self, test_client, test_db, staff_oa_enabled, line_api
    ):
        events = [
            {"type": "message", "source": {"userId": "U-x"}, "replyToken": "r"},
            {"type": "unfollow", "source": {"userId": "U-y"}},
        ]
        response = _signed_post(test_client, {"events": events})

        assert response.status_code == 200
        assert response.json()["follow_events_handled"] == 0
        assert line_api["linked"] == []
        assert line_api["replies"] == []

    def test_line_api_failure_on_one_event_keeps_webhook_green(
        self, test_client, test_db, staff_oa_enabled, line_api, monkeypatch
    ):
        # Was pointed at link_rich_menu_to_user, which the stranger path no
        # longer calls (no base menu to link). Re-pointed at the reply, which
        # is the LINE call that path still makes — the test is about a LINE
        # hiccup not wedging the webhook, not about which endpoint hiccuped.
        def _explode(*args, **kwargs):
            raise service.StaffOaApiError("reply message", 500, "boom")

        monkeypatch.setattr(service, "reply_text_message", _explode)

        response = _signed_post(
            test_client, {"events": [_follow_event("U-stranger")]}
        )

        # LINE must still see 200 or it retries the whole delivery forever.
        assert response.status_code == 200
        assert response.json()["follow_events_handled"] == 0

    def test_follow_event_without_user_id_is_skipped(
        self, test_client, test_db, staff_oa_enabled, line_api
    ):
        response = _signed_post(
            test_client, {"events": [{"type": "follow", "source": {}}]}
        )

        assert response.status_code == 200
        assert line_api["linked"] == []


class TestGroupEventForwarding:
    """Events relayed to guest-feedback (2026-09-05).

    LINE allows one Official Account per group chat and the staff group
    hosts THIS OA, so the guest-feedback app is fed second-hand from here
    (see guest-feedback docs/CONTRACTS.md §15.4, and §15.5 for the 1:1
    preview). What these tests pin is the boundary, not guest-feedback's
    behaviour: the exact payload of each of the two shapes, that nothing
    else crosses it, and that the relay can neither delay nor fail the 200
    LINE is waiting for — a delivery LINE counts as failed is retried, and a
    wedged staff channel is a far worse outcome than a missed guest request.
    """

    FORWARD_URL = "http://feedback:4080/api/internal/line/event"

    @pytest.fixture
    def forwarding_on(self, monkeypatch):
        monkeypatch.setenv("GUEST_FEEDBACK_LINE_URL", self.FORWARD_URL)
        monkeypatch.setenv("GUEST_FEEDBACK_LINE_SECRET", "shared-secret")

    @pytest.fixture
    def forwards(self, monkeypatch):
        """Record what the webhook hands the background forwarder.

        Patched at the hand-off, which the request thread calls directly —
        so the assertions stay synchronous. The thread itself is exercised
        in tests/unit/test_staff_oa_service.py and by the two
        does-not-block/does-not-fail tests at the bottom of this class.
        """
        calls = []
        monkeypatch.setattr(
            service, "forward_group_events_in_background",
            lambda payloads: calls.append(list(payloads)),
        )
        return calls

    @staticmethod
    def _group_message_event():
        return {
            "type": "message",
            "replyToken": "reply-group-1",
            "timestamp": 1757000000000,
            "source": {"type": "group", "groupId": "Cgroup123", "userId": "Uspeaker"},
            "message": {"type": "text", "id": "m1", "text": "ผ้าเช็ดตัวหมดค่ะ"},
        }

    def test_group_message_is_forwarded_with_the_exact_payload(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on, forwards
    ):
        response = _signed_post(
            test_client, {"events": [self._group_message_event()]}
        )

        assert response.status_code == 200
        assert response.json()["group_events_forwarded"] == 1
        assert forwards == [[{
            "type": "message",
            "replyToken": "reply-group-1",
            "timestamp": 1757000000000,
            "groupId": "Cgroup123",
            "channel": "staff-oa",
        }]]
        # The message text and the speaker stay here.
        assert "ผ้าเช็ดตัวหมดค่ะ" not in json.dumps(forwards, ensure_ascii=False)

    def test_follow_events_are_never_forwarded_and_still_get_their_reply(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on, forwards
    ):
        # The one thing this feature must not disturb. A follow is excluded
        # by its TYPE, not by its source — since 2026-09-05 `user`-source
        # `message` events DO cross (below), so this is no longer implied by
        # "only group events are forwarded" and has to be pinned on its own:
        # the follower is linked/greeted here and guest-feedback never hears
        # about it.
        response = _signed_post(
            test_client, {"events": [_follow_event("U-stranger", "reply-42")]}
        )

        assert response.status_code == 200
        assert response.json()["follow_events_handled"] == 1
        assert response.json()["group_events_forwarded"] == 0
        assert forwards == []
        assert len(line_api["replies"]) == 1  # unchanged onboarding path

    @pytest.fixture
    def bot_idle(self, monkeypatch):
        """Take the staff bot out of the reply-token arbitration.

        The bot answers EVERY 1:1 text message it is sent, so with it in the
        loop every direct message would cross with ``replyToken: None`` and
        these tests could not see the payload the contract specifies. That
        arbitration is real behaviour, not an accident, and is pinned by
        ``test_a_direct_message_the_bot_answers_loses_its_reply_token``
        below and by TestReplyTokenArbitration; this fixture isolates the
        OTHER half — what the relay does with an event nobody claimed.
        """
        monkeypatch.setattr(
            staff_bot, "handle_event_detail",
            lambda event, db: staff_bot._NOT_HANDLED,
        )

    @staticmethod
    def _direct_message_event(text="ขอดูรายการที่ค้าง"):
        return {
            "type": "message",
            "replyToken": "reply-direct-1",
            "timestamp": 1757000000001,
            "source": {"type": "user", "userId": "Umanager"},
            "message": {"type": "text", "id": "m2", "text": text},
        }

    def test_a_direct_message_is_forwarded_ids_only(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on,
        forwards, bot_idle,
    ):
        # guest-feedback §15.5: an allowlisted manager messages the OA in
        # private and gets the pending guest requests back, without pulling
        # the staff group into a test. The allowlist is guest-feedback's —
        # this app forwards every 1:1 message and judges nobody.
        response = _signed_post(
            test_client, {"events": [self._direct_message_event()]}
        )

        assert response.status_code == 200
        assert forwards == [[{
            "type": "message",
            "replyToken": "reply-direct-1",
            "timestamp": 1757000000001,
            "userId": "Umanager",
            "groupId": None,
            "channel": "staff-oa",
        }]]
        # The words stay here, exactly as in a group.
        assert "ขอดูรายการที่ค้าง" not in json.dumps(forwards, ensure_ascii=False)

    def test_a_direct_message_the_bot_answers_loses_its_reply_token(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on,
        forwards,
    ):
        # No `bot_idle` here: the REAL bot sees this message, and it answers
        # every 1:1 text (a stranger gets the onboarding pointer), so it
        # claims the single-use token and the relay must not also get it.
        # This is the routine 1:1 case, and the documented limitation of the
        # preview — see docs/EMPLOYEE_HUB_SETUP.md.
        response = _signed_post(
            test_client, {"events": [self._direct_message_event()]}
        )

        assert response.status_code == 200
        assert forwards[0][0]["replyToken"] is None
        assert forwards[0][0]["userId"] == "Umanager"  # the id still crosses

    def test_a_user_unfollow_is_never_forwarded(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on,
        forwards, bot_idle,
    ):
        # Only `message` crosses from a 1:1. An unfollow says someone blocked
        # the OA — an Employee Hub fact, and not guest-feedback's business.
        response = _signed_post(test_client, {"events": [{
            "type": "unfollow",
            "timestamp": 1757000000002,
            "source": {"type": "user", "userId": "U-someone"},
        }]})

        assert response.status_code == 200
        assert forwards == []

    def test_a_room_source_message_is_never_forwarded(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on,
        forwards, bot_idle,
    ):
        # A multi-person room is neither the staff group nor a 1:1: nothing
        # about it is forwardable, and there is nobody to answer.
        response = _signed_post(test_client, {"events": [{
            "type": "message",
            "replyToken": "r",
            "timestamp": 1757000000003,
            "source": {"type": "room", "roomId": "R-room", "userId": "U-someone"},
            "message": {"type": "text", "id": "m3", "text": "hello"},
        }]})

        assert response.status_code == 200
        assert response.json()["group_events_forwarded"] == 0
        assert forwards == []

    def test_nothing_is_forwarded_while_the_url_is_empty(
        self, test_client, test_db, staff_oa_enabled, line_api, monkeypatch
    ):
        monkeypatch.delenv("GUEST_FEEDBACK_LINE_URL", raising=False)
        ran = []
        monkeypatch.setattr(service, "forward_group_events", ran.append)

        response = _signed_post(
            test_client, {"events": [self._group_message_event()]}
        )

        assert response.status_code == 200
        assert response.json()["group_events_forwarded"] == 0
        assert ran == []

    def test_a_slow_guest_feedback_does_not_delay_the_webhook_response(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on, monkeypatch
    ):
        # Real thread this time — the point of using one rather than
        # FastAPI BackgroundTasks, which Starlette runs before the response
        # leaves the ASGI call.
        started = threading.Event()

        def _slow(payloads):
            started.set()
            time.sleep(5)

        monkeypatch.setattr(service, "forward_group_events", _slow)

        began = time.monotonic()
        response = _signed_post(
            test_client, {"events": [self._group_message_event()]}
        )
        elapsed = time.monotonic() - began

        assert response.status_code == 200
        assert elapsed < 1.0, f"webhook waited {elapsed:.2f}s on the forward"
        assert started.wait(timeout=5)  # it really was dispatched

    def test_a_failing_guest_feedback_does_not_change_the_200(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on, monkeypatch
    ):
        # The real forward_group_events runs here; only the HTTP call is
        # faked, so this exercises the actual swallow path.
        posted = threading.Event()

        class _RefusingRequests:
            def post(self, url, **kwargs):
                posted.set()
                raise OSError("connection refused")

        monkeypatch.setattr(service, "requests", _RefusingRequests())

        response = _signed_post(
            test_client, {"events": [self._group_message_event()]}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert posted.wait(timeout=5)  # the failure really happened


class TestReplyTokenArbitration:
    """A LINE reply token is single-use, and two consumers hang off this
    webhook: the staff bot (debounced replies) and the guest-feedback relay.
    The bot files intent FIRST; any event whose token it has claimed still
    crosses to guest-feedback (the group is still learned) but with
    ``replyToken: None`` — one consumer per token, decided here, never by a
    race between two senders.
    """

    FORWARD_URL = "http://feedback:4080/api/internal/line/event"

    @pytest.fixture
    def forwarding_on(self, monkeypatch):
        monkeypatch.setenv("GUEST_FEEDBACK_LINE_URL", self.FORWARD_URL)
        monkeypatch.setenv("GUEST_FEEDBACK_LINE_SECRET", "shared-secret")

    @pytest.fixture
    def forwards(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            service, "forward_group_events_in_background",
            lambda payloads: calls.append(list(payloads)),
        )
        return calls

    @pytest.fixture
    def real_bot(self, monkeypatch):
        """A private dispatcher whose scheduler never arms a timer, so the
        state machine holds pending replies and nothing is ever sent."""
        dispatcher = staff_bot.AsyncioBotDispatcher()
        dispatcher.debouncer = staff_bot.ReplyDebouncer(scheduler=lambda delay: None)
        monkeypatch.setattr(staff_bot, "get_dispatcher", lambda: dispatcher)
        return dispatcher

    @staticmethod
    def _group_text(text, reply_token, group_id="Cgroup123"):
        return {
            "type": "message",
            "replyToken": reply_token,
            "timestamp": 1757000000000,
            "source": {"type": "group", "groupId": group_id, "userId": "Uspeaker"},
            "message": {"type": "text", "id": "m", "text": text},
        }

    def test_a_summon_is_relayed_without_its_reply_token(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on, forwards, real_bot
    ):
        response = _signed_post(
            test_client, {"events": [self._group_text("น้องคะ", "reply-claimed")]}
        )

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 1
        assert response.json()["group_events_forwarded"] == 1
        assert forwards == [[{
            "type": "message",
            "replyToken": None,
            "timestamp": 1757000000000,
            "groupId": "Cgroup123",
            "channel": "staff-oa",
        }]]
        key = staff_bot._chat_key({"type": "group", "groupId": "Cgroup123"})
        assert real_bot.debouncer.pending_for(key).reply_token == "reply-claimed"

    def test_plain_chat_keeps_its_token_while_the_bot_is_idle(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on, forwards, real_bot
    ):
        response = _signed_post(
            test_client, {"events": [self._group_text("ผ้าเช็ดตัวหมดค่ะ", "reply-free")]}
        )

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 0
        assert forwards[0][0]["replyToken"] == "reply-free"

    def test_plain_chat_loses_its_token_while_the_bot_holds_the_chat(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on, forwards, real_bot
    ):
        _signed_post(test_client, {"events": [self._group_text("น้องคะ", "reply-1")]})
        response = _signed_post(
            test_client, {"events": [self._group_text("ขอบคุณค่ะ", "reply-2")]}
        )

        assert response.status_code == 200
        assert response.json()["bot_commands"] == 0
        assert [call[0]["replyToken"] for call in forwards] == [None, None]
        key = staff_bot._chat_key({"type": "group", "groupId": "Cgroup123"})
        # The bot moved on to the newer token, which is why the relay must
        # not get it.
        assert real_bot.debouncer.pending_for(key).reply_token == "reply-2"

    def test_another_chat_is_not_affected_by_a_pending_reply_elsewhere(
        self, test_client, test_db, staff_oa_enabled, line_api, forwarding_on, forwards, real_bot
    ):
        _signed_post(test_client, {"events": [self._group_text("น้องคะ", "reply-1")]})
        _signed_post(
            test_client,
            {"events": [self._group_text("สวัสดีค่ะ", "reply-other", group_id="Cother")]},
        )

        assert [call[0]["replyToken"] for call in forwards] == [None, "reply-other"]
