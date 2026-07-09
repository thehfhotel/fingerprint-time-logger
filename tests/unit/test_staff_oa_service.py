"""Unit tests for app.services.staff_oa_service.

Covers the fail-closed credential gate, LINE webhook signature
verification, the grant → menu-variant grouping the sync script uses, and
the one-user relink helper (LINE API mocked throughout — no HTTP).
"""
import base64
import hashlib
import hmac

import pytest

from app.models.models import Employee, EmployeeAppGrant
from app.services import staff_oa_service as service

TOKEN = "test-channel-access-token"
SECRET = "test-channel-secret"


@pytest.fixture
def staff_oa_enabled(monkeypatch):
    monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", SECRET)


@pytest.fixture
def staff_oa_dark(monkeypatch):
    monkeypatch.delenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("STAFF_OA_CHANNEL_SECRET", raising=False)


def _sign(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


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


def _grant(test_db, badge, *app_ids):
    for app_id in app_ids:
        test_db.add(EmployeeAppGrant(employee_badge_number=badge, app_id=app_id))
    test_db.commit()


class TestEnablement:
    def test_dark_when_both_env_vars_unset(self, staff_oa_dark):
        assert service.is_enabled() is False

    def test_dark_when_only_token_set(self, monkeypatch, staff_oa_dark):
        monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
        assert service.is_enabled() is False

    def test_dark_when_secret_is_blank(self, monkeypatch, staff_oa_enabled):
        monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", "   ")
        assert service.is_enabled() is False

    def test_enabled_when_both_set(self, staff_oa_enabled):
        assert service.is_enabled() is True


class TestWebhookSignature:
    def test_should_accept_valid_signature(self, staff_oa_enabled):
        body = b'{"events":[]}'
        assert service.verify_webhook_signature(body, _sign(body)) is True

    def test_should_reject_wrong_signature(self, staff_oa_enabled):
        body = b'{"events":[]}'
        assert service.verify_webhook_signature(body, _sign(b"other")) is False

    def test_should_reject_signature_from_wrong_secret(self, staff_oa_enabled):
        body = b'{"events":[]}'
        forged = _sign(body, secret="not-the-channel-secret")
        assert service.verify_webhook_signature(body, forged) is False

    def test_should_reject_missing_signature(self, staff_oa_enabled):
        assert service.verify_webhook_signature(b"{}", None) is False
        assert service.verify_webhook_signature(b"{}", "") is False

    def test_should_reject_everything_when_dark(self, staff_oa_dark):
        body = b'{"events":[]}'
        assert service.verify_webhook_signature(body, _sign(body)) is False


class TestEmployeeMenuAssignments:
    def test_groups_linked_employees_by_menu_variant(self, test_db):
        _make_employee(test_db, "1001", line_user_id="U-base")
        _make_employee(test_db, "1002", line_user_id="U-payroll")
        _grant(test_db, "1002", "payroll")
        _make_employee(test_db, "1003", line_user_id="U-payroll-2")
        _grant(test_db, "1003", "payroll", "rooms")  # rooms is menu-irrelevant

        assignments = service.employee_menu_assignments(test_db)

        assert assignments["base"] == ["U-base"]
        assert sorted(assignments["base+payroll"]) == ["U-payroll", "U-payroll-2"]

    def test_ignores_unlinked_and_inactive_employees(self, test_db):
        _make_employee(test_db, "2001")  # no LINE account linked
        _make_employee(test_db, "2002", line_user_id="U-gone", is_active=False)

        assert service.employee_menu_assignments(test_db) == {}


class TestDeployedMenuIdsByKey:
    def test_maps_variant_key_to_menu_id(self):
        menus = [
            {"richMenuId": "rm-1", "name": "staffhub:base:abc123"},
            {"richMenuId": "rm-2", "name": "staffhub:base+payroll:def456"},
            {"richMenuId": "rm-3", "name": "unrelated-menu"},
        ]
        mapping = service.deployed_menu_ids_by_key(menus)
        assert mapping == {"base": "rm-1", "base+payroll": "rm-2"}


class TestLinkRoleMenuForLineUser:
    @pytest.fixture
    def line_api(self, monkeypatch):
        """Mock the two LINE calls the helper makes; record link calls."""
        calls = {"linked": []}
        monkeypatch.setattr(
            service, "get_rich_menu_list",
            lambda: [
                {"richMenuId": "rm-base", "name": "staffhub:base:aaa"},
                {"richMenuId": "rm-payroll", "name": "staffhub:base+payroll:bbb"},
            ],
        )
        monkeypatch.setattr(
            service, "link_rich_menu_to_user",
            lambda user_id, menu_id: calls["linked"].append((user_id, menu_id)),
        )
        return calls

    def test_returns_none_when_dark(self, staff_oa_dark, test_db, line_api):
        assert service.link_role_menu_for_line_user(test_db, "U-1") is None
        assert line_api["linked"] == []

    def test_returns_none_for_unknown_line_user(self, staff_oa_enabled, test_db, line_api):
        assert service.link_role_menu_for_line_user(test_db, "U-stranger") is None
        assert line_api["linked"] == []

    def test_links_the_grant_driven_variant(self, staff_oa_enabled, test_db, line_api):
        _make_employee(test_db, "1001", line_user_id="U-1")
        _grant(test_db, "1001", "payroll")

        key = service.link_role_menu_for_line_user(test_db, "U-1")

        assert key == "base+payroll"
        assert line_api["linked"] == [("U-1", "rm-payroll")]

    def test_returns_none_when_variant_not_deployed(self, staff_oa_enabled, test_db, line_api):
        _make_employee(test_db, "1002", line_user_id="U-2")
        _grant(test_db, "1002", "ota")  # no staffhub:base+ota menu deployed

        assert service.link_role_menu_for_line_user(test_db, "U-2") is None
        assert line_api["linked"] == []
