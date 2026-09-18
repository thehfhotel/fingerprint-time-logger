"""
Tests for the defense-in-depth auth dependency on the consolidated
/api/private/* routers (app/api/deps.py: require_cf_access, applied in
app/main_unified.py to attendance / devices / employees / system /
shifts / leaves, plus the three bare auto-import/refresh endpoints
mounted alongside them).

Background: these routers used to carry NO in-app auth dependency at
all — their only protection was edge-side Cloudflare Access on
erp.thehfhotel.org. Publishing id.thehfhotel.org (the SAME backend
process) with access:"none" briefly served them completely
unauthenticated (closed at the Cloudflare edge 2026-08-14; see
hf-erp/infra/cloudflare/gate-hfid-host.ts). This test file proves the
in-app half of that fix: a request with a fully-verified Cloudflare
Access assertion still reaches the handler (the live dashboard keeps
working — including for NON-admin staff/kiosk identities, since these
routers are tier "staff", not admin-only), while a request with no
assertion at all — the actual exposure — is rejected.

Uses the real FastAPI app via the repo's ``test_client`` fixture, a
locally generated RSA keypair, and a monkeypatched PyJWKClient — no
network access to Cloudflare. Mirrors the fixture shape of
tests/unit/test_admin_auth_cf_access.py and
tests/unit/test_cf_access_service.py.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.deps import require_cf_access
from app.main_unified import app as fastapi_app
from app.services import cf_access_service

ACCEPTED_AUD = "3c622b40cc931c7414dcfc583bed1f50afaac316eafb914cc7f153650843ea8b"
# Clearly-fake address put in the MANAGER_ADMIN_EMAILS floor by the
# patch_jwks_client fixture below — used to prove admins are NOT
# accidentally locked out either.
ADMIN_EMAIL = "admin-1@example.invalid"
# Deliberately NOT added to MANAGER_ADMIN_EMAILS — a staff/kiosk-tier
# identity (e.g. a shared hotel mailbox) that the SAME Access app admits
# but that is NOT an admin — see app/api/deps.py's module docstring for
# why require_cf_access must accept this identity where require_admin_auth
# would not.
NON_ADMIN_EMAIL = "employee-1@example.invalid"

# One representative, cheap (no device I/O, empty-DB-safe) GET endpoint
# per protected router — enough to prove the dependency lets a verified
# request all the way through to the handler, without exercising each
# router's business logic (that's each router's own test file's job).
PROTECTED_GET_ENDPOINTS = [
    pytest.param("/api/private/attendance/", id="attendance"),
    pytest.param("/api/private/devices/health", id="devices"),
    pytest.param("/api/private/employees/health", id="employees"),
    pytest.param("/api/private/system/health", id="system"),
    pytest.param("/api/private/shifts/", id="shifts"),
    pytest.param("/api/private/leaves/types", id="leaves"),
    pytest.param("/api/private/auto-import/status", id="auto-import-status"),
]

# POST endpoints that trigger real background-scheduler work (attendance
# import via the ZKTeco device client) — deliberately NOT given a
# valid-token/200 test here, since driving them would attempt real device
# I/O in a unit test. The 401-without-auth path (which never reaches the
# handler body) is what matters for this fix and is covered below.
PROTECTED_POST_ENDPOINTS_REJECT_ONLY = [
    pytest.param("/api/private/refresh", id="refresh"),
    pytest.param("/api/private/auto-import/trigger/", id="auto-import-trigger"),
]


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
def use_real_require_cf_access(test_client):
    """tests/conftest.py's ``test_client`` overrides require_cf_access to a
    fixed authenticated identity by default (so the hundreds of pre-existing
    router tests that don't care about auth keep passing). THIS file exists
    specifically to test require_cf_access itself, so it pops that
    convenience override back out — every request below exercises the real
    dependency. Depending on ``test_client`` (not just ``app``) makes fixture
    ordering explicit: the override must be installed before we remove it.
    """
    fastapi_app.dependency_overrides.pop(require_cf_access, None)
    yield


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
    monkeypatch.setenv("MANAGER_ADMIN_EMAILS", ADMIN_EMAIL)


def _make_cf_token(
    private_pem, *, email, aud=ACCEPTED_AUD, exp_delta=timedelta(minutes=5)
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


@pytest.mark.parametrize("path", PROTECTED_GET_ENDPOINTS)
class TestPrivateRouterRequiresCfAccess:
    def test_no_auth_at_all_is_rejected(self, test_client, path):
        """The actual exposure this fix closes: a bare hit with no
        Cloudflare Access assertion (e.g. via a future ungated hostname
        pointing at this same process) must never reach the handler."""
        response = test_client.get(path)
        assert response.status_code == 401

    def test_forged_header_is_rejected(self, test_client, path):
        response = test_client.get(
            path, headers={"Cf-Access-Jwt-Assertion": "not-a-real-jwt"}
        )
        assert response.status_code == 401

    def test_wrong_audience_token_is_rejected(self, test_client, path, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=ADMIN_EMAIL, aud="unaccepted-aud")
        response = test_client.get(
            path, headers={"Cf-Access-Jwt-Assertion": token}
        )
        assert response.status_code == 401

    def test_expired_token_is_rejected(self, test_client, path, rsa_keypair):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(
            private_pem, email=ADMIN_EMAIL, exp_delta=timedelta(minutes=-5)
        )
        response = test_client.get(
            path, headers={"Cf-Access-Jwt-Assertion": token}
        )
        assert response.status_code == 401

    def test_valid_admin_token_reaches_handler(self, test_client, path, rsa_keypair):
        """Admins keep working (not just non-admins) — this dependency is
        strictly additive over the previous no-auth-at-all state."""
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=ADMIN_EMAIL)
        response = test_client.get(
            path, headers={"Cf-Access-Jwt-Assertion": token}
        )
        assert response.status_code != 401

    def test_valid_non_admin_staff_token_reaches_handler(
        self, test_client, path, rsa_keypair
    ):
        """The load-bearing case: a verified but NON-admin identity (the
        reception kiosk mailbox) must still pass. require_admin_auth
        would reject this; require_cf_access must not — these routers
        are tier "staff", not admin-only (see app/api/deps.py)."""
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=NON_ADMIN_EMAIL)
        response = test_client.get(
            path, headers={"Cf-Access-Jwt-Assertion": token}
        )
        assert response.status_code != 401

    def test_cf_auto_login_kill_switch_does_not_affect_this_dependency(
        self, test_client, monkeypatch, path, rsa_keypair
    ):
        """Unlike require_admin_auth, require_cf_access is NOT wired to
        the CF_AUTO_LOGIN kill switch (see app/api/deps.py's docstring):
        that flag is for the unrelated admin passcode-skip convenience,
        and must not silently reopen (or needlessly close) this
        defense-in-depth layer."""
        monkeypatch.setenv("CF_AUTO_LOGIN", "false")
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=NON_ADMIN_EMAIL)
        response = test_client.get(
            path, headers={"Cf-Access-Jwt-Assertion": token}
        )
        assert response.status_code != 401


@pytest.mark.parametrize("path", PROTECTED_POST_ENDPOINTS_REJECT_ONLY)
class TestPrivatePostEndpointRejectsUnauthenticated:
    def test_no_auth_at_all_is_rejected(self, test_client, path):
        response = test_client.post(path)
        assert response.status_code == 401

    def test_forged_header_is_rejected(self, test_client, path):
        response = test_client.post(
            path, headers={"Cf-Access-Jwt-Assertion": "not-a-real-jwt"}
        )
        assert response.status_code == 401
