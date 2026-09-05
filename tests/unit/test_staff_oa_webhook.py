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
