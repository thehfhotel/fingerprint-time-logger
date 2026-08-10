"""
Integration tests for the HF ID OIDC provider (app/api/oidc.py).

Drives the full Cloudflare-Access-style flow through the FastAPI surface with
LINE mocked end to end (no network):

    /oidc/authorize -> LINE (mocked) -> LINE callback continuation
      -> authorization code -> /oidc/token -> id_token + access_token
      -> /oidc/userinfo

plus every security check from the spec: PKCE mismatch, replay of a used code,
bad/absent client secret, wrong redirect_uri, unregistered redirect_uri,
inactive employee, pending employee, unknown LINE user, and an alg-confusion
attempt against the emitted id_token. Also verifies the provider is fully dark
(404) until configured.

PKCE is conditional: the flow must complete for a confidential client that
never sends a code_challenge (Cloudflare Access), while a client that does
send one is still held to it at the token endpoint.
"""

import base64
import hashlib
import time
import urllib.parse

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.models.models import Employee, EmployeeAppGrant
from app.services import oidc_service
from app.services.line_auth_service import line_auth_service


# One RSA key for the whole module.
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = _PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

_CLIENT_ID = "cf-access-client"
_CLIENT_SECRET = "confidential-client-secret"
_REDIRECT_URI = oidc_service.DEFAULT_REDIRECT_URI
_ISSUER = "https://id.thehfhotel.org/oidc"
_ELIGIBLE_LINE_USER = "Ueligible0001"


@pytest.fixture
def hfid_enabled(monkeypatch):
    """Enable HF ID with the module signing key + confidential client."""
    monkeypatch.setenv("HFID_SIGNING_KEY", _PRIVATE_PEM)
    monkeypatch.setenv("HFID_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("HFID_CLIENT_SECRET", _CLIENT_SECRET)
    monkeypatch.delenv("HFID_ISSUER", raising=False)
    monkeypatch.delenv("HFID_REDIRECT_URIS", raising=False)
    oidc_service.reset_state()
    yield
    oidc_service.reset_state()


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _seed_employee(session, *, badge="Q001", line_user_id=_ELIGIBLE_LINE_USER,
                   is_active=True, pending_approval=False,
                   email="q001@emp.thehfhotel.org", apps=("rooms", "portal")):
    """Insert an employee (+ app grants) into the shared test engine."""
    employee = Employee(
        badge_number=badge,
        display_name="พนักงาน สมชาย",
        is_active=is_active,
        pending_approval=pending_approval,
        email=email,
        line_user_id=line_user_id,
        join_source="self_onboard",
    )
    session.add(employee)
    for app_id in apps:
        session.add(
            EmployeeAppGrant(employee_badge_number=badge, app_id=app_id)
        )
    session.commit()
    return employee


def _authorize(test_client, *, state="client-state-xyz", scope="openid email profile",
               overrides=None, use_pkce=True):
    """Call /oidc/authorize and return the raw response (no redirect follow).

    ``use_pkce=False`` reproduces Cloudflare Access's generic OIDC connector,
    which sends neither code_challenge nor code_challenge_method; the returned
    verifier is then None.
    """
    verifier, challenge = _pkce_pair()
    params = {
        "client_id": _CLIENT_ID,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": scope,
        "state": state,
        "nonce": "nonce-abc",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if not use_pkce:
        params.pop("code_challenge")
        params.pop("code_challenge_method")
        verifier = None
    if overrides:
        params.update({k: v for k, v in overrides.items() if v is not None})
        for k, v in overrides.items():
            if v is None:
                params.pop(k, None)
    response = test_client.get(
        "/oidc/authorize?" + urllib.parse.urlencode(params),
        follow_redirects=False,
    )
    return response, verifier


def _ticket_from_authorize(response):
    """Extract the OIDC login ticket from the /authorize redirect Location."""
    location = response.headers["location"]
    query = urllib.parse.urlparse(location).query
    redirect_value = urllib.parse.parse_qs(query)["redirect"][0]
    assert redirect_value.startswith("oidc:")
    return redirect_value[len("oidc:"):]


def _drive_line_callback(test_client, monkeypatch, ticket, line_user_id):
    """Simulate LINE returning ``line_user_id`` for an OIDC login ticket.

    Seeds the LINE CSRF state directly (LINE creds are unset in tests) and
    mocks the token/profile network calls, then hits the real LINE callback so
    the additive OIDC continuation hook fires.
    """
    state = "line-state-" + str(int(time.time() * 1000))
    line_auth_service._state_storage[state] = (time.time(), f"oidc:{ticket}")
    monkeypatch.setattr(
        line_auth_service, "exchange_code_for_token",
        lambda code: {"access_token": "line-access-token"},
    )
    monkeypatch.setattr(
        line_auth_service, "get_user_profile",
        lambda access_token: {
            "userId": line_user_id,
            "displayName": "LINE Name",
            "pictureUrl": "",
        },
    )
    return test_client.get(
        f"/api/public/auth/line/callback?code=line-code&state={state}",
        follow_redirects=False,
    )


def _run_flow_to_code(test_client, monkeypatch, *, line_user_id=_ELIGIBLE_LINE_USER,
                      state="client-state-xyz", use_pkce=True):
    """Run authorize -> LINE -> callback and return (callback_response, verifier)."""
    authorize_response, verifier = _authorize(
        test_client, state=state, use_pkce=use_pkce
    )
    assert authorize_response.status_code == 302
    ticket = _ticket_from_authorize(authorize_response)
    callback = _drive_line_callback(test_client, monkeypatch, ticket, line_user_id)
    return callback, verifier


def _extract_code_and_state(callback_response):
    location = callback_response.headers["location"]
    assert location.startswith(_REDIRECT_URI)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    return query["code"][0], query.get("state", [None])[0]


def _exchange(test_client, code, verifier, *, redirect_uri=_REDIRECT_URI,
              client_id=_CLIENT_ID, client_secret=_CLIENT_SECRET, use_basic=False):
    """POST /oidc/token. ``verifier=None`` omits code_verifier entirely, the
    way Cloudflare Access's token call does."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if verifier is not None:
        data["code_verifier"] = verifier
    headers = {}
    if use_basic:
        raw = f"{client_id}:{client_secret}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    else:
        if client_id is not None:
            data["client_id"] = client_id
        if client_secret is not None:
            data["client_secret"] = client_secret
    return test_client.post("/oidc/token", data=data, headers=headers)


# ============================================================================
# Dark provider
# ============================================================================

class TestDarkProvider:
    def test_all_endpoints_404_when_unconfigured(self, test_client, monkeypatch):
        monkeypatch.delenv("HFID_SIGNING_KEY", raising=False)
        oidc_service.reset_state()
        for path in [
            "/oidc/.well-known/openid-configuration",
            "/oidc/jwks",
            "/oidc/authorize",
            "/oidc/userinfo",
        ]:
            assert test_client.get(path).status_code == 404
        assert test_client.post("/oidc/token", data={}).status_code == 404


# ============================================================================
# Discovery + JWKS
# ============================================================================

class TestDiscoveryEndpoints:
    def test_discovery_served_when_enabled(self, test_client, hfid_enabled):
        response = test_client.get("/oidc/.well-known/openid-configuration")
        assert response.status_code == 200
        doc = response.json()
        assert doc["issuer"] == _ISSUER
        assert doc["code_challenge_methods_supported"] == ["S256"]
        assert doc["id_token_signing_alg_values_supported"] == ["RS256"]

    def test_jwks_served_when_enabled(self, test_client, hfid_enabled):
        response = test_client.get("/oidc/jwks")
        assert response.status_code == 200
        keys = response.json()["keys"]
        assert len(keys) == 1
        assert keys[0]["kty"] == "RSA"


# ============================================================================
# Happy path
# ============================================================================

class TestHappyPath:
    def test_full_authorization_code_flow(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)

        callback, verifier = _run_flow_to_code(test_client, monkeypatch)
        assert callback.status_code == 302
        code, returned_state = _extract_code_and_state(callback)
        assert returned_state == "client-state-xyz"  # OIDC state passthrough

        token_response = _exchange(test_client, code, verifier)
        assert token_response.status_code == 200
        body = token_response.json()
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == oidc_service.ACCESS_TOKEN_TTL_SECONDS

        claims = jwt.decode(
            body["id_token"], _PUBLIC_PEM, algorithms=["RS256"],
            audience=_CLIENT_ID, issuer=_ISSUER,
        )
        assert claims["sub"] == "Q001"
        assert claims["badge"] == "Q001"
        assert claims["email"] == "q001@emp.thehfhotel.org"
        assert set(claims["apps"]) == {"rooms", "portal"}
        assert claims["nonce"] == "nonce-abc"

        userinfo = test_client.get(
            "/oidc/userinfo",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert userinfo.status_code == 200
        info = userinfo.json()
        assert info["sub"] == "Q001"
        assert info["badge"] == "Q001"
        assert info["email"] == "q001@emp.thehfhotel.org"
        assert set(info["apps"]) == {"rooms", "portal"}

    def test_client_secret_basic_is_accepted(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, verifier = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        response = _exchange(test_client, code, verifier, use_basic=True)
        assert response.status_code == 200
        assert "id_token" in response.json()

    def test_full_flow_without_pkce_succeeds(self, test_client, test_db, hfid_enabled, monkeypatch):
        """THE Cloudflare Access case — no code_challenge, no code_verifier.

        Cloudflare Access's generic OIDC connector does not implement PKCE. It
        is a confidential client and still proves itself with client_secret on
        the token call, so the exchange must succeed. This flow used to die at
        /oidc/token with 400 "code_verifier is required", which Cloudflare
        reported to users as "Failed to fetch user/group information from the
        identity provider".
        """
        _seed_employee(test_db)

        callback, verifier = _run_flow_to_code(
            test_client, monkeypatch, use_pkce=False
        )
        assert verifier is None
        assert callback.status_code == 302
        code, returned_state = _extract_code_and_state(callback)
        assert returned_state == "client-state-xyz"

        token_response = _exchange(test_client, code, None)
        assert token_response.status_code == 200
        body = token_response.json()

        claims = jwt.decode(
            body["id_token"], _PUBLIC_PEM, algorithms=["RS256"],
            audience=_CLIENT_ID, issuer=_ISSUER,
        )
        assert claims["sub"] == "Q001"
        assert claims["email"] == "q001@emp.thehfhotel.org"

        userinfo = test_client.get(
            "/oidc/userinfo",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert userinfo.status_code == 200
        assert userinfo.json()["badge"] == "Q001"


# ============================================================================
# Security — authorize endpoint
# ============================================================================

class TestAuthorizeSecurity:
    def test_unregistered_redirect_uri_is_not_redirected(self, test_client, hfid_enabled):
        response, _ = _authorize(
            test_client, overrides={"redirect_uri": "https://evil.example/cb"}
        )
        assert response.status_code == 400  # rendered page, NOT a redirect
        assert "location" not in {k.lower() for k in response.headers}

    def test_unknown_client_is_not_redirected(self, test_client, hfid_enabled):
        response, _ = _authorize(test_client, overrides={"client_id": "attacker"})
        assert response.status_code == 400

    def test_missing_pkce_is_brokered_into_line(self, test_client, hfid_enabled):
        """No code_challenge is legal for this confidential client: the browser
        must go on to LINE login, not bounce back with error=invalid_request."""
        response, verifier = _authorize(test_client, use_pkce=False)
        assert response.status_code == 302
        assert verifier is None
        location = response.headers["location"]
        assert location.startswith("/api/public/auth/line/login")
        assert "error" not in urllib.parse.parse_qs(
            urllib.parse.urlparse(location).query
        )
        assert _ticket_from_authorize(response)  # a real login ticket was made

    def test_pkce_method_without_challenge_redirects_with_error(self, test_client, hfid_enabled):
        """Half a PKCE request stays an error — only *neither* value is OK."""
        response, _ = _authorize(test_client, overrides={"code_challenge": None})
        assert response.status_code == 302
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(response.headers["location"]).query
        )
        assert query["error"][0] == "invalid_request"
        assert query["state"][0] == "client-state-xyz"

    def test_plain_pkce_method_redirects_with_error(self, test_client, hfid_enabled):
        response, _ = _authorize(
            test_client, overrides={"code_challenge_method": "plain"}
        )
        assert response.status_code == 302
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(response.headers["location"]).query
        )
        assert query["error"][0] == "invalid_request"


# ============================================================================
# Security — LINE continuation (employee eligibility)
# ============================================================================

class TestEmployeeEligibility:
    def test_inactive_employee_gets_no_code(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db, is_active=False)
        callback, _ = _run_flow_to_code(test_client, monkeypatch)
        assert callback.status_code == 403
        assert "location" not in {k.lower() for k in callback.headers}

    def test_pending_employee_gets_no_code(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db, is_active=True, pending_approval=True)
        callback, _ = _run_flow_to_code(test_client, monkeypatch)
        assert callback.status_code == 403

    def test_unknown_line_user_is_routed_to_onboarding(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)  # different line_user_id than the caller
        callback, _ = _run_flow_to_code(
            test_client, monkeypatch, line_user_id="Ustranger999"
        )
        assert callback.status_code == 302
        assert callback.headers["location"] == "/qr-checkin/onboard"

    def test_expired_login_ticket_is_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        authorize_response, _ = _authorize(test_client)
        ticket = _ticket_from_authorize(authorize_response)
        # Force the ticket to expire before LINE returns.
        oidc_service._login_tickets[ticket]["expires_at"] = time.time() - 1
        callback = _drive_line_callback(
            test_client, monkeypatch, ticket, _ELIGIBLE_LINE_USER
        )
        assert callback.status_code == 400


# ============================================================================
# Security — token endpoint
# ============================================================================

class TestTokenSecurity:
    def test_wrong_client_secret_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, verifier = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        response = _exchange(test_client, code, verifier, client_secret="wrong")
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_client"

    def test_absent_client_secret_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, verifier = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        response = _exchange(test_client, code, verifier, client_secret=None)
        assert response.status_code == 401

    def test_pkce_mismatch_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, _ = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        response = _exchange(test_client, code, "attacker-verifier-not-matching")
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_missing_verifier_rejected_when_challenge_was_sent(self, test_client, test_db, hfid_enabled, monkeypatch):
        """A client that STARTED PKCE must finish it — relaxing PKCE for the
        connector that never uses it must not let anyone drop a verifier."""
        _seed_employee(test_db)
        callback, _ = _run_flow_to_code(test_client, monkeypatch)  # sends a challenge
        code, _ = _extract_code_and_state(callback)
        response = _exchange(test_client, code, None)
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"
        assert response.json()["error_description"] == "code_verifier is required"

    def test_malformed_non_ascii_verifier_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        """A non-ASCII verifier is malformed per RFC 7636 — it must be a clean
        400, never a 500 from an unhandled UnicodeEncodeError."""
        _seed_employee(test_db)
        callback, _ = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        response = _exchange(test_client, code, "ทดสอบ-verifier")
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_verifier_without_challenge_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        """No challenge on the code, but a verifier on the token call.

        The implementation rejects with invalid_grant rather than ignoring the
        stray verifier: a verifier that exists implies the client believed it
        sent a challenge, so the missing challenge means something stripped it
        on the front channel (a PKCE downgrade attack). Failing loudly makes
        that visible; silently succeeding would hide it. Cloudflare Access
        sends neither value, so this cannot affect real SSO traffic.
        """
        _seed_employee(test_db)
        callback, verifier = _run_flow_to_code(
            test_client, monkeypatch, use_pkce=False
        )
        assert verifier is None
        code, _ = _extract_code_and_state(callback)
        response = _exchange(test_client, code, "a-verifier-nobody-asked-for")
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_no_pkce_code_is_still_single_use(self, test_client, test_db, hfid_enabled, monkeypatch):
        """Dropping PKCE must not soften replay protection."""
        _seed_employee(test_db)
        callback, _ = _run_flow_to_code(test_client, monkeypatch, use_pkce=False)
        code, _ = _extract_code_and_state(callback)
        assert _exchange(test_client, code, None).status_code == 200
        replay = _exchange(test_client, code, None)
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"

    def test_no_pkce_code_still_requires_client_secret(self, test_client, test_db, hfid_enabled, monkeypatch):
        """The secret is what replaces PKCE here — it must still be checked."""
        _seed_employee(test_db)
        callback, _ = _run_flow_to_code(test_client, monkeypatch, use_pkce=False)
        code, _ = _extract_code_and_state(callback)
        response = _exchange(test_client, code, None, client_secret="wrong")
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_client"

    def test_no_pkce_code_still_binds_redirect_uri(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, _ = _run_flow_to_code(test_client, monkeypatch, use_pkce=False)
        code, _ = _extract_code_and_state(callback)
        response = _exchange(
            test_client, code, None,
            redirect_uri="https://laikaexpress.cloudflareaccess.com/other",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_used_code_replay_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, verifier = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        first = _exchange(test_client, code, verifier)
        assert first.status_code == 200
        replay = _exchange(test_client, code, verifier)
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"

    def test_wrong_redirect_uri_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, verifier = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        response = _exchange(
            test_client, code, verifier,
            redirect_uri="https://laikaexpress.cloudflareaccess.com/other",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_unsupported_grant_type_rejected(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, verifier = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        response = test_client.post("/oidc/token", data={
            "grant_type": "client_credentials",
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": _CLIENT_ID,
            "client_secret": _CLIENT_SECRET,
        })
        assert response.status_code == 400
        assert response.json()["error"] == "unsupported_grant_type"

    def test_emitted_id_token_resists_alg_confusion(self, test_client, test_db, hfid_enabled, monkeypatch):
        _seed_employee(test_db)
        callback, verifier = _run_flow_to_code(test_client, monkeypatch)
        code, _ = _extract_code_and_state(callback)
        id_token = _exchange(test_client, code, verifier).json()["id_token"]
        assert jwt.get_unverified_header(id_token)["alg"] == "RS256"
        with pytest.raises(jwt.InvalidAlgorithmError):
            jwt.decode(id_token, _PUBLIC_PEM, algorithms=["HS256"])


# ============================================================================
# Security — userinfo endpoint
# ============================================================================

class TestUserInfoSecurity:
    def test_missing_bearer_rejected(self, test_client, hfid_enabled):
        assert test_client.get("/oidc/userinfo").status_code == 401

    def test_invalid_token_rejected(self, test_client, hfid_enabled):
        response = test_client.get(
            "/oidc/userinfo",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert response.status_code == 401
