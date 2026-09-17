"""
Route-level tests for the /v2/* pages served by ``fingerprint_app``
(app/main_unified.py), mounted in production under ``/fingerprintlogs``.

v2 had ZERO route coverage before this file. Two things are pinned here:

  1. The three NEW v2 admin pages (/v2/employees, /v2/system, /v2/terminals)
     sit behind the SAME server-side admin guard as their v1 counterparts —
     a verified Cloudflare Access admin identity OR a valid passcode session
     serves the page; anything else gets a 302 to the login page and no page
     content at all.
  2. The pre-existing UNGATED v2 pages (/v2/, /v2/live, /v2/by-date,
     /v2/monthly, /v2/shifts-admin) still serve 200 without any auth — they
     are protected upstream by Cloudflare Access, not at the FastAPI layer,
     and this migration must not accidentally gate them.

The four v1 admin pages are covered too: their inline guards were collapsed
into the shared ``serve_admin_page`` helper and must behave EXACTLY as
before (this is deploy 1 of a two-deploy cutover — no v1 route is retired
or redirected yet).

Harness mirrors tests/unit/test_admin_auth_cf_access.py: the real FastAPI
app via the repo's ``test_client`` fixture, a locally generated RSA keypair,
and a monkeypatched PyJWKClient — no network access to Cloudflare.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import cf_access_service
from app.services.admin_auth_service import admin_auth_service
from app.utils.static_asset_version import asset_version

ACCEPTED_AUD = "3c622b40cc931c7414dcfc583bed1f50afaac316eafb914cc7f153650843ea8b"
# One of the default CF_ADMIN_EMAILS (see cf_access_service.py).
TEST_EMAIL = "admin-1@example.invalid"
# A real HF shared mailbox the same Access apps admit but that is NOT an
# admin — must never get auto-login.
NON_ADMIN_EMAIL = "admin-7@example.invalid"

LOGIN_URL = "/fingerprintlogs/admin-login"

# The three new v2 admin pages added by this migration.
V2_ADMIN_ROUTES = [
    "/fingerprintlogs/v2/employees",
    "/fingerprintlogs/v2/system",
    "/fingerprintlogs/v2/terminals",
]

# Pre-existing v2 pages that are deliberately NOT gated at the app layer.
V2_UNGATED_ROUTES = [
    "/fingerprintlogs/v2/",
    "/fingerprintlogs/v2/live",
    "/fingerprintlogs/v2/by-date",
    "/fingerprintlogs/v2/monthly",
    "/fingerprintlogs/v2/shifts-admin",
    "/fingerprintlogs/v2/leaves",
]

# The v1 admin pages whose inline guards were collapsed into the shared
# helper. Deploy 1 keeps every one of them serving exactly as before.
V1_ADMIN_ROUTES = [
    "/fingerprintlogs/employee-management",
    "/fingerprintlogs/status",
    "/fingerprintlogs/admin/terminal-gps",
    "/fingerprintlogs/admin-console",
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
    """Create a real passcode session token via the actual service."""
    return admin_auth_service.create_session()


def _assert_redirected_to_login(response):
    assert response.status_code == 302
    assert response.headers["location"] == LOGIN_URL
    # No page content may reach an unauthenticated browser.
    assert "text/html" not in response.headers.get("content-type", "")
    assert b"<html" not in response.content.lower()


class TestV2AdminPagesServeForAuthenticatedAdmin:
    """The three new v2 admin pages serve for an authenticated admin."""

    @pytest.mark.parametrize("url", V2_ADMIN_ROUTES)
    def test_verified_cf_admin_identity_serves_page(self, test_client, rsa_keypair, url):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem)

        response = test_client.get(
            url,
            headers={"Cf-Access-Jwt-Assertion": token},
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert len(response.content) > 0

    @pytest.mark.parametrize("url", V2_ADMIN_ROUTES)
    def test_valid_passcode_session_serves_page(self, test_client, url):
        """The passcode path is not regressed by the CF Access path."""
        token = _valid_passcode_session_cookie()

        response = test_client.get(
            url,
            cookies={"admin_session_token": token},
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.parametrize("url", V2_ADMIN_ROUTES)
    def test_served_page_is_no_store(self, test_client, rsa_keypair, url):
        """Admin pages must never be cached by a shared/proxy cache."""
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem)

        response = test_client.get(
            url, headers={"Cf-Access-Jwt-Assertion": token}, follow_redirects=False
        )

        assert "no-store" in response.headers.get("cache-control", "")


class TestV2AdminPagesRejectUnauthenticated:
    """Every non-authenticated shape 302s to the passcode login page."""

    @pytest.mark.parametrize("url", V2_ADMIN_ROUTES)
    def test_no_identity_and_no_cookie_redirects_to_login(self, test_client, url):
        response = test_client.get(url, follow_redirects=False)

        _assert_redirected_to_login(response)

    @pytest.mark.parametrize("url", V2_ADMIN_ROUTES)
    def test_invalid_session_cookie_redirects_and_clears_cookie(self, test_client, url):
        response = test_client.get(
            url,
            cookies={"admin_session_token": "bogus-token"},
            follow_redirects=False,
        )

        _assert_redirected_to_login(response)
        set_cookie = response.headers.get("set-cookie", "")
        assert "admin_session_token=" in set_cookie
        assert "Max-Age=0" in set_cookie

    @pytest.mark.parametrize("url", V2_ADMIN_ROUTES)
    def test_forged_cf_header_redirects_to_login(self, test_client, url):
        response = test_client.get(
            url,
            headers={"Cf-Access-Jwt-Assertion": "not-a-real-jwt"},
            follow_redirects=False,
        )

        _assert_redirected_to_login(response)

    @pytest.mark.parametrize("url", V2_ADMIN_ROUTES)
    def test_non_admin_cf_identity_does_not_escalate(self, test_client, rsa_keypair, url):
        """
        Privilege-escalation guard: the Access application fronting these
        pages also admits employee-tier accounts. A fully-verified CF Access
        JWT for a non-admin email must fall through exactly as if absent.
        """
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, email=NON_ADMIN_EMAIL)

        response = test_client.get(
            url,
            headers={"Cf-Access-Jwt-Assertion": token},
            follow_redirects=False,
        )

        _assert_redirected_to_login(response)

    @pytest.mark.parametrize("url", V2_ADMIN_ROUTES)
    def test_wrong_audience_cf_token_redirects_to_login(self, test_client, rsa_keypair, url):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem, aud="unaccepted-aud")

        response = test_client.get(
            url,
            headers={"Cf-Access-Jwt-Assertion": token},
            follow_redirects=False,
        )

        _assert_redirected_to_login(response)


class TestV2UngatedPagesStillServe:
    """
    The existing v2 pages are protected upstream by Cloudflare Access, not at
    the FastAPI layer. Adding the guard to the three new pages must not have
    gated these.
    """

    @pytest.mark.parametrize("url", V2_UNGATED_ROUTES)
    def test_serves_200_without_any_auth(self, test_client, url):
        response = test_client.get(url, follow_redirects=False)

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


class TestV2LeavesIsItsOwnTopLevelPage:
    """วันลา · วันหยุด moved off the จัดกะ tab strip onto its own page
    (SPEC_ROSTER_NAV.md, Track N) — pin the split so it can't silently
    regress back onto shifts-admin or lose its board mount point.
    """

    def test_leaves_page_carries_the_nav_id_and_board_mount(self, test_client):
        response = test_client.get("/fingerprintlogs/v2/leaves", follow_redirects=False)

        assert response.status_code == 200
        body = response.text
        assert 'data-page="leaves"' in body
        assert 'id="lbBoard"' in body

    def test_shifts_admin_no_longer_hosts_the_leave_board_tab(self, test_client):
        response = test_client.get(
            "/fingerprintlogs/v2/shifts-admin", follow_redirects=False
        )

        assert response.status_code == 200
        assert 'data-tab="leaveboard"' not in response.text


class TestV2StaticAssetUrlsAreVersioned:
    """The edge in front of the app (nginx/Cloudflare) caches
    /fingerprintlogs/static/** BY URL for hours, ignoring our no-store
    header — so every asset URL a v2 page serves must carry this deploy's
    ``?v=`` stamp (app/utils/static_asset_version.py), or a deploy can keep
    running the previous release's JS for up to 4 hours.
    """

    @pytest.mark.parametrize(
        "url", ["/fingerprintlogs/v2/leaves", "/fingerprintlogs/v2/shifts-admin"]
    )
    def test_nav_and_theme_js_carry_the_deploy_version_stamp(self, test_client, url):
        response = test_client.get(url, follow_redirects=False)

        assert response.status_code == 200
        version = asset_version()
        assert f"nav.js?v={version}" in response.text
        assert f"theme.js?v={version}" in response.text


class TestV1AdminPagesUnchanged:
    """
    Deploy 1 is purely additive. The four v1 admin pages had their inline
    guards collapsed into the shared helper and must behave identically —
    NO redirect to /v2/* yet (that is WP5b, on the owner's signal).
    """

    @pytest.mark.parametrize("url", V1_ADMIN_ROUTES)
    def test_verified_cf_admin_identity_still_serves_page(self, test_client, rsa_keypair, url):
        private_pem, _ = rsa_keypair
        token = _make_cf_token(private_pem)

        response = test_client.get(
            url,
            headers={"Cf-Access-Jwt-Assertion": token},
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    @pytest.mark.parametrize("url", V1_ADMIN_ROUTES)
    def test_valid_passcode_session_still_serves_page(self, test_client, url):
        token = _valid_passcode_session_cookie()

        response = test_client.get(
            url,
            cookies={"admin_session_token": token},
            follow_redirects=False,
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("url", V1_ADMIN_ROUTES)
    def test_no_auth_still_redirects_to_the_login_page(self, test_client, url):
        """Not to /v2/* — the retirement flip is a separate deploy."""
        response = test_client.get(url, follow_redirects=False)

        _assert_redirected_to_login(response)

    @pytest.mark.parametrize("url", V1_ADMIN_ROUTES)
    def test_invalid_session_cookie_still_clears_cookie(self, test_client, url):
        response = test_client.get(
            url,
            cookies={"admin_session_token": "bogus-token"},
            follow_redirects=False,
        )

        _assert_redirected_to_login(response)
        assert "admin_session_token=" in response.headers.get("set-cookie", "")
