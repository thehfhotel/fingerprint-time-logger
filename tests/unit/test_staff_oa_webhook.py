"""Unit tests for the staff OA webhook (app.api.staff_oa).

POST /api/public/staff-oa/webhook: dark until configured (503), rejects
bad signatures (401), and on `follow` events links the follower's Role
Menu — or the base menu plus a Thai onboarding reply for strangers. All
LINE Messaging API calls are mocked.
"""
import base64
import hashlib
import hmac
import json

import pytest

from app.api import staff_oa as staff_oa_module
from app.models.models import Employee, EmployeeAppGrant
from app.services import staff_oa_service as service

TOKEN = "test-channel-access-token"
SECRET = "test-channel-secret"
WEBHOOK_PATH = "/api/public/staff-oa/webhook"


@pytest.fixture
def staff_oa_enabled(monkeypatch):
    monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", SECRET)


@pytest.fixture
def line_api(monkeypatch):
    """Mock every LINE call the webhook path can make; record them."""
    calls = {"linked": [], "replies": []}
    monkeypatch.setattr(
        service, "get_rich_menu_list",
        lambda: [
            {"richMenuId": "rm-base", "name": "staffhub:base:aaa"},
            {"richMenuId": "rm-ota", "name": "staffhub:base+ota:bbb"},
        ],
    )
    monkeypatch.setattr(
        service, "link_rich_menu_to_user",
        lambda user_id, menu_id: calls["linked"].append((user_id, menu_id)),
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
        _make_employee(test_db, "1001", line_user_id="U-reception")
        test_db.add(EmployeeAppGrant(employee_badge_number="1001", app_id="ota"))
        test_db.commit()

        response = _signed_post(
            test_client, {"events": [_follow_event("U-reception")]}
        )

        assert response.status_code == 200
        assert response.json()["follow_events_handled"] == 1
        assert line_api["linked"] == [("U-reception", "rm-ota")]
        assert line_api["replies"] == []  # known employees get no lecture

    def test_unknown_follower_gets_base_menu_and_onboarding_reply(
        self, test_client, test_db, staff_oa_enabled, line_api
    ):
        response = _signed_post(
            test_client, {"events": [_follow_event("U-stranger", "reply-42")]}
        )

        assert response.status_code == 200
        assert line_api["linked"] == [("U-stranger", "rm-base")]
        assert len(line_api["replies"]) == 1
        reply_token, text = line_api["replies"][0]
        assert reply_token == "reply-42"
        assert text == staff_oa_module.ONBOARDING_REPLY_TEXT
        assert "qr-checkin/onboard" in text  # points at Q-badge onboarding

    def test_inactive_employee_is_treated_as_unknown(
        self, test_client, test_db, staff_oa_enabled, line_api
    ):
        _make_employee(test_db, "1002", line_user_id="U-left", is_active=False)

        _signed_post(test_client, {"events": [_follow_event("U-left")]})

        assert line_api["linked"] == [("U-left", "rm-base")]
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
        def _explode(*args, **kwargs):
            raise service.StaffOaApiError("link rich menu to user", 500, "boom")

        monkeypatch.setattr(service, "link_rich_menu_to_user", _explode)

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
