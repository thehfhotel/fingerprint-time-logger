"""
Tests for the admin auth CF-Access-first / passcode-session-fallback
resolver (app/api/admin_auth.py: resolve_admin_identity, require_admin_auth,
GET /validate) and the page guards / WebSocket guard that use it
(app/main_unified.py).

Uses the real FastAPI app via the repo's ``test_client`` fixture, a
locally generated RSA keypair, and a monkeypatched PyJWKClient — no
network access to Cloudflare. Confirms:
  - A verified CF Access identity for an admin-allowlisted email
    authenticates without any passcode session.
  - A forged/invalid CF header does NOT authenticate on its own.
  - A verified CF Access identity for a NON-admin email (e.g. a shared
    hotel mailbox — the same Access apps admit employee-tier accounts)
    does NOT authenticate either; it falls through to the passcode path
    like a missing token would (privilege-escalation guard).
  - The passcode session cookie/Bearer path still works unchanged when
    there's no CF identity (STRICTLY ADDITIVE fallback).
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.websockets import WebSocketDisconnect

from app.services import cf_access_service
from app.services.admin_auth_service import admin_auth_service

ACCEPTED_AUD = "3c622b40cc931c7414dcfc583bed1f50afaac316eafb914cc7f153650843ea8b"
# Clearly-fake address put in the MANAGER_ADMIN_EMAILS floor by the
# patch_jwks_client fixture below (see app/services/manager_directory.py).
TEST_EMAIL = "admin-1@example.invalid"
# Deliberately NOT added to MANAGER_ADMIN_EMAILS — an Access-admitted
# identity that is NOT an admin (e.g. a shared hotel mailbox) — must never
# get auto-login.
NON_ADMIN_EMAIL = "employee-1@example.invalid"

VALIDATE_URL = "/api/private/admin/auth/validate"
PROTECTED_TEST_URL = "/api/private/test"
STATUS_PAGE_URL = "/fingerprintlogs/status"
WS_URL = "/fingerprintlogs/ws"


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


class _FakeSigningKey:
    def __init__(self, public_pem: bytes):
        self.key = public_pem


@pytest.fixture(autouse=True)
def patch_jwks_client(monkeypatch, rsa_keypair):
    """No network calls to Cloudflare's JWKS during tests."""
    _, public_pem = rsa_keypair
    monkeypatch.setattr(
        cf_access_service._jwks_client,
        "get_signing_key_from_jwt",
        lambda token: _FakeSigningKey(public_pem),
    )
    monkeypatch.delenv("CF_AUTO_LOGIN", raising=False)
    monkeypatch.delenv("CF_ACCESS_AUDS", raising=False)
    monkeypatch.delenv("CF_ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("MANAGER_ADMIN_EMAILS", TEST_EMAIL)


def _make_cf_token(
    private_pem, *, email=TEST_EMAIL, aud=ACCEPTED_AUD, exp_delta=timedelta(minutes=5)
):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "email": email,
            "iss": cf_access_service.CF_ACCESS_TEAM_DOMAIN,
            "aud": aud,
            "iat": now,
            "exp": now + exp_delta,
        },
        private_pem,
        algorithm="RS256",
    )


def _valid_passcode_session_cookie() -> str:
    """Create a real passcode session token via the actual service (no bcrypt needed)."""
    return admin_auth_service.create_session()


class TestRequireAdminAuthCfAccess:
    """GET /api/private/test is gated by require_admin_auth."""

    def test_valid_cf_header_authenticates_without_passcode_session(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem)

        response = test_client.get(
            PROTECTED_TEST_URL, headers={"Cf-Access-Jwt-Assertion": token}
        )

        assert response.status_code == 200

    def test_no_auth_at_all_is_rejected(self, test_client):
        response = test_client.get(PROTECTED_TEST_URL)

        assert response.status_code == 401

    def test_forged_cf_header_without_passcode_session_is_rejected(self, test_client):
        response = test_client.get(
            PROTECTED_TEST_URL,
            headers={"Cf-Access-Jwt-Assertion": "not-a-real-jwt"},
        )

        assert response.status_code == 401

    def test_wrong_audience_cf_token_is_rejected(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, aud="unaccepted-aud")

        response = test_client.get(
            PROTECTED_TEST_URL, headers={"Cf-Access-Jwt-Assertion": token}
        )

        assert response.status_code == 401

    def test_falls_back_to_valid_passcode_session_when_no_cf_token(self, test_client):
        """STRICTLY ADDITIVE: existing passcode sessions keep working."""
        token = _valid_passcode_session_cookie()

        response = test_client.get(
            PROTECTED_TEST_URL, cookies={"admin_session_token": token}
        )

        assert response.status_code == 200

    def test_invalid_passcode_session_and_no_cf_token_is_rejected(self, test_client):
        response = test_client.get(
            PROTECTED_TEST_URL, cookies={"admin_session_token": "bogus-token"}
        )

        assert response.status_code == 401

    def test_cf_auto_login_kill_switch_forces_passcode_fallback(
        self, test_client, monkeypatch, rsa_keypair
    ):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem)
        monkeypatch.setenv("CF_AUTO_LOGIN", "false")

        cf_only_response = test_client.get(
            PROTECTED_TEST_URL, headers={"Cf-Access-Jwt-Assertion": token}
        )
        assert cf_only_response.status_code == 401

        passcode_token = _valid_passcode_session_cookie()
        passcode_response = test_client.get(
            PROTECTED_TEST_URL, cookies={"admin_session_token": passcode_token}
        )
        assert passcode_response.status_code == 200


class TestValidateEndpointCfAccess:
    """GET /validate lets admin-login.html auto-skip the passcode prompt."""

    def test_valid_cf_token_reports_valid_true(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem)

        response = test_client.get(
            VALIDATE_URL, headers={"Cf-Access-Jwt-Assertion": token}
        )

        assert response.status_code == 200
        assert response.json()["valid"] is True

    def test_no_auth_reports_valid_false(self, test_client):
        response = test_client.get(VALIDATE_URL)

        assert response.status_code == 200
        assert response.json()["valid"] is False

    def test_valid_passcode_session_still_reports_valid_true(self, test_client):
        token = _valid_passcode_session_cookie()

        response = test_client.get(
            VALIDATE_URL, cookies={"admin_session_token": token}
        )

        assert response.status_code == 200
        assert response.json()["valid"] is True


class TestPageGuardCfAccess:
    """Inline page guards (e.g. /fingerprintlogs/status) accept CF Access too."""

    def test_valid_cf_token_serves_page_without_redirect(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem)

        response = test_client.get(
            STATUS_PAGE_URL,
            headers={"Cf-Access-Jwt-Assertion": token},
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_no_auth_redirects_to_login(self, test_client):
        response = test_client.get(STATUS_PAGE_URL, follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/fingerprintlogs/admin-login"

    def test_valid_passcode_cookie_still_serves_page(self, test_client):
        """STRICTLY ADDITIVE: unchanged passcode-cookie page guard behavior."""
        token = _valid_passcode_session_cookie()

        response = test_client.get(
            STATUS_PAGE_URL,
            cookies={"admin_session_token": token},
            follow_redirects=False,
        )

        assert response.status_code == 200


class TestWebSocketGuardCfAccess:
    """The dashboard WebSocket accepts a verified CF Access identity too."""

    def test_valid_cf_token_allows_connection(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem)

        with test_client.websocket_connect(
            WS_URL, headers={"Cf-Access-Jwt-Assertion": token}
        ) as websocket:
            websocket.send_json({"type": "ping"})
            reply = websocket.receive_json()

        assert reply == {"type": "pong"}

    def test_no_auth_rejects_connection(self, test_client):
        with pytest.raises(WebSocketDisconnect):
            with test_client.websocket_connect(WS_URL):
                pass

    def test_valid_passcode_cookie_still_allows_connection(self, test_client):
        """STRICTLY ADDITIVE: unchanged passcode-cookie WebSocket guard behavior."""
        token = _valid_passcode_session_cookie()

        with test_client.websocket_connect(
            WS_URL, cookies={"admin_session_token": token}
        ) as websocket:
            websocket.send_json({"type": "ping"})
            reply = websocket.receive_json()

        assert reply == {"type": "pong"}


class TestNonAdminCfEmailDoesNotEscalate:
    """
    Privilege-escalation guard: the Access applications fronting these
    pages also admit employee-tier accounts (shared hotel mailboxes). A
    fully-verified CF Access JWT for one of those emails must NOT grant
    admin access anywhere it's checked — it must fall through exactly as
    if the header were absent.
    """

    def test_protected_api_rejects_non_admin_cf_email(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=NON_ADMIN_EMAIL)

        response = test_client.get(
            PROTECTED_TEST_URL, headers={"Cf-Access-Jwt-Assertion": token}
        )

        assert response.status_code == 401

    def test_validate_endpoint_reports_invalid_for_non_admin_cf_email(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=NON_ADMIN_EMAIL)

        response = test_client.get(
            VALIDATE_URL, headers={"Cf-Access-Jwt-Assertion": token}
        )

        assert response.status_code == 200
        assert response.json()["valid"] is False

    def test_page_guard_redirects_non_admin_cf_email_to_login(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=NON_ADMIN_EMAIL)

        response = test_client.get(
            STATUS_PAGE_URL,
            headers={"Cf-Access-Jwt-Assertion": token},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/fingerprintlogs/admin-login"

    def test_websocket_guard_rejects_non_admin_cf_email(self, test_client, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=NON_ADMIN_EMAIL)

        with pytest.raises(WebSocketDisconnect):
            with test_client.websocket_connect(
                WS_URL, headers={"Cf-Access-Jwt-Assertion": token}
            ):
                pass

    def test_non_admin_cf_email_can_still_use_passcode_session(self, test_client, rsa_keypair):
        """
        A non-admin CF identity doesn't block the passcode fallback — an
        admin who happens to also carry a non-admin CF token (unlikely,
        but must not deadlock) can still authenticate with the passcode.
        """
        private_pem, _ = rsa_keypair
        cf_token = _make_cf_token(private_pem, email=NON_ADMIN_EMAIL)
        passcode_token = _valid_passcode_session_cookie()

        response = test_client.get(
            PROTECTED_TEST_URL,
            headers={"Cf-Access-Jwt-Assertion": cf_token},
            cookies={"admin_session_token": passcode_token},
        )

        assert response.status_code == 200
