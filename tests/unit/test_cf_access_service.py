"""
Unit tests for Cloudflare Access JWT verification
(app/services/cf_access_service.py).

Uses a locally generated RSA keypair and a monkeypatched PyJWKClient so
these tests exercise the real signature/issuer/audience/expiry checks
without ever touching the network. The container's :5000 port is
LAN-reachable and bypasses Cloudflare's edge, so the mere presence of a
``Cf-Access-Jwt-Assertion`` header must never be trusted — these tests
specifically cover forged/tampered tokens to guard against that.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import cf_access_service

ACCEPTED_AUD_1 = "3c622b40cc931c7414dcfc583bed1f50afaac316eafb914cc7f153650843ea8b"
ACCEPTED_AUD_2 = "57f843579497b508143412a5980c1c4fc94ca01abadab465b57a88b5a733e487"
# Used for pure JWT-verification tests (verify_cf_access), which are not
# gated by the admin allowlist — any well-formed, correctly-signed email
# claim is a valid outcome there.
TEST_EMAIL = "manager@thehfhotel.org"
# One of the default CF_ADMIN_EMAILS — used for get_cf_access_email tests,
# which DO enforce the admin allowlist.
ADMIN_EMAIL = "admin-1@example.invalid"
# A real HF shared mailbox admitted by the same Access apps but NOT an
# admin — must fall through to the passcode path, never auto-login.
EMPLOYEE_EMAIL = "admin-7@example.invalid"


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate a throwaway RSA keypair to sign/verify test tokens with."""
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
    """Stand-in for jwt.PyJWKClient's PyJWK — verify_cf_access only uses .key."""

    def __init__(self, public_pem: bytes):
        self.key = public_pem


class _FakeRequestLike:
    """Minimal stand-in for Starlette's Request/WebSocket: .headers + .cookies."""

    def __init__(self, headers=None, cookies=None):
        self.headers = headers or {}
        self.cookies = cookies or {}


@pytest.fixture(autouse=True)
def patch_jwks_client(monkeypatch, rsa_keypair):
    """Point the module-level PyJWKClient at our test key — no network call."""
    _, public_pem = rsa_keypair
    monkeypatch.setattr(
        cf_access_service._jwks_client,
        "get_signing_key_from_jwt",
        lambda token: _FakeSigningKey(public_pem),
    )
    # Tests explicitly control these env vars per-case; make sure each test
    # starts from the real defaults (kill switch enabled, default auds,
    # default admin allowlist).
    monkeypatch.delenv("CF_AUTO_LOGIN", raising=False)
    monkeypatch.delenv("CF_ACCESS_AUDS", raising=False)
    monkeypatch.delenv("CF_ADMIN_EMAILS", raising=False)


def _make_token(
    private_pem,
    *,
    email=TEST_EMAIL,
    iss=cf_access_service.CF_ACCESS_TEAM_DOMAIN,
    aud=ACCEPTED_AUD_1,
    exp_delta=timedelta(minutes=5),
):
    now = datetime.now(timezone.utc)
    payload = {"iss": iss, "aud": aud, "iat": now, "exp": now + exp_delta}
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, private_pem, algorithm="RS256")


class TestVerifyCfAccess:
    def test_should_return_email_when_token_is_fully_valid(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem)

        assert cf_access_service.verify_cf_access(token) == TEST_EMAIL

    def test_should_accept_either_configured_audience(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, aud=ACCEPTED_AUD_2)

        assert cf_access_service.verify_cf_access(token) == TEST_EMAIL

    def test_should_reject_expired_token(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, exp_delta=timedelta(minutes=-5))

        assert cf_access_service.verify_cf_access(token) is None

    def test_should_reject_wrong_audience(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, aud="some-other-access-app-aud")

        assert cf_access_service.verify_cf_access(token) is None

    def test_should_reject_wrong_issuer(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, iss="https://attacker.cloudflareaccess.com")

        assert cf_access_service.verify_cf_access(token) is None

    def test_should_reject_token_missing_email_claim(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, email=None)

        assert cf_access_service.verify_cf_access(token) is None

    def test_should_reject_empty_or_missing_token(self):
        assert cf_access_service.verify_cf_access("") is None
        assert cf_access_service.verify_cf_access(None) is None

    def test_should_reject_forged_non_jwt_header_value(self):
        """
        A LAN attacker on :5000 can set Cf-Access-Jwt-Assertion to any
        string. A value that isn't even a JWT must be rejected, not
        crash the request.
        """
        assert cf_access_service.verify_cf_access("attacker@example.com") is None

    def test_should_reject_token_signed_with_alg_none(self):
        """
        A forged 'none'-algorithm token (no signature at all) must be
        rejected even though it's structurally a valid JWT — RS256 is the
        only algorithm this service accepts.
        """
        now = datetime.now(timezone.utc)
        payload = {
            "email": TEST_EMAIL,
            "iss": cf_access_service.CF_ACCESS_TEAM_DOMAIN,
            "aud": ACCEPTED_AUD_1,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        token = jwt.encode(payload, key=None, algorithm="none")

        assert cf_access_service.verify_cf_access(token) is None

    def test_should_honor_cf_access_auds_env_override(self, monkeypatch, rsa_keypair):
        private_pem, _ = rsa_keypair
        custom_aud = "custom-access-app-aud-123"
        token = _make_token(private_pem, aud=custom_aud)
        monkeypatch.setenv("CF_ACCESS_AUDS", custom_aud)

        assert cf_access_service.verify_cf_access(token) == TEST_EMAIL

    def test_should_reject_default_auds_once_env_override_is_set(self, monkeypatch, rsa_keypair):
        """Once CF_ACCESS_AUDS is set, it fully replaces the defaults."""
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, aud=ACCEPTED_AUD_1)
        monkeypatch.setenv("CF_ACCESS_AUDS", "some-unrelated-aud")

        assert cf_access_service.verify_cf_access(token) is None


class TestGetCfAccessEmail:
    """
    get_cf_access_email additionally gates on the admin allowlist, so
    these tests use ADMIN_EMAIL (one of the CF_ADMIN_EMAILS defaults) for
    the positive cases. Allowlist-specific behavior is covered separately
    in TestAdminAllowlist below.
    """

    def test_should_return_none_when_no_token_present(self):
        assert cf_access_service.get_cf_access_email(_FakeRequestLike()) is None

    def test_should_prefer_header_over_cookie(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        good_token = _make_token(private_pem, email=ADMIN_EMAIL)
        bad_token = _make_token(private_pem, email=ADMIN_EMAIL, aud="wrong-aud")
        request = _FakeRequestLike(
            headers={"Cf-Access-Jwt-Assertion": good_token},
            cookies={"CF_Authorization": bad_token},
        )

        assert cf_access_service.get_cf_access_email(request) == ADMIN_EMAIL

    def test_should_fall_back_to_cookie_when_header_absent(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, email=ADMIN_EMAIL)
        request = _FakeRequestLike(cookies={"CF_Authorization": token})

        assert cf_access_service.get_cf_access_email(request) == ADMIN_EMAIL

    def test_should_return_none_when_kill_switch_disabled(self, monkeypatch, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, email=ADMIN_EMAIL)
        request = _FakeRequestLike(headers={"Cf-Access-Jwt-Assertion": token})
        monkeypatch.setenv("CF_AUTO_LOGIN", "false")

        assert cf_access_service.get_cf_access_email(request) is None

    def test_should_default_to_enabled_when_kill_switch_unset(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, email=ADMIN_EMAIL)
        request = _FakeRequestLike(headers={"Cf-Access-Jwt-Assertion": token})

        assert cf_access_service.get_cf_access_email(request) == ADMIN_EMAIL

    def test_should_work_uniformly_for_websocket_like_object(self, rsa_keypair):
        """
        get_cf_access_email must work for both Request and WebSocket —
        both Starlette types expose the same .headers/.cookies interface.
        """
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, email=ADMIN_EMAIL)
        fake_websocket = _FakeRequestLike(headers={"Cf-Access-Jwt-Assertion": token})

        assert cf_access_service.get_cf_access_email(fake_websocket) == ADMIN_EMAIL


class TestAdminAllowlist:
    """
    CF Access verification alone is NOT sufficient for admin access — the
    same Access applications also admit employee-tier accounts (shared
    hotel mailboxes). Only CF_ADMIN_EMAILS members get auto-login.
    """

    def test_allowlisted_manager_email_authenticates(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, email=ADMIN_EMAIL)
        request = _FakeRequestLike(headers={"Cf-Access-Jwt-Assertion": token})

        assert cf_access_service.get_cf_access_email(request) == ADMIN_EMAIL

    def test_verified_but_non_admin_email_falls_back(self, rsa_keypair):
        """
        A verified, fully-legitimate CF Access JWT for a non-admin email
        (e.g. a shared hotel mailbox) must NOT authenticate as admin —
        treated exactly like an absent/invalid header.
        """
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, email=EMPLOYEE_EMAIL)
        request = _FakeRequestLike(headers={"Cf-Access-Jwt-Assertion": token})

        assert cf_access_service.get_cf_access_email(request) is None

    def test_allowlist_check_is_case_insensitive(self, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_token(private_pem, email=ADMIN_EMAIL.upper())
        request = _FakeRequestLike(headers={"Cf-Access-Jwt-Assertion": token})

        assert cf_access_service.get_cf_access_email(request) == ADMIN_EMAIL.upper()

    def test_cf_admin_emails_env_override_replaces_defaults(self, monkeypatch, rsa_keypair):
        private_pem, _ = rsa_keypair
        # ADMIN_EMAIL is a default admin, but once CF_ADMIN_EMAILS is set
        # it should no longer be trusted unless explicitly included.
        monkeypatch.setenv("CF_ADMIN_EMAILS", EMPLOYEE_EMAIL)
        admin_token = _make_token(private_pem, email=ADMIN_EMAIL)
        newly_admin_token = _make_token(private_pem, email=EMPLOYEE_EMAIL)

        admin_request = _FakeRequestLike(headers={"Cf-Access-Jwt-Assertion": admin_token})
        newly_admin_request = _FakeRequestLike(
            headers={"Cf-Access-Jwt-Assertion": newly_admin_token}
        )

        assert cf_access_service.get_cf_access_email(admin_request) is None
        assert cf_access_service.get_cf_access_email(newly_admin_request) == EMPLOYEE_EMAIL
