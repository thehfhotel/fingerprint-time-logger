"""
Unit tests for the HF ID OIDC provider service (app/services/oidc_service.py).

Covers the security-critical primitives in isolation: signing-key loading +
stable kid, JWKS shape, PKCE (S256) verification, constant-time client auth,
single-use / short-lived authorization codes and login tickets, RS256 id_token
minting (and the absence of alg confusion), opaque access tokens, and the
dark-when-unconfigured kill switch.
"""

import base64
import hashlib
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import oidc_service


# Generated once for the whole module — RSA keygen is comparatively expensive.
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


@pytest.fixture
def enabled_provider(monkeypatch):
    """Configure HF ID with a real signing key + client, isolated per test."""
    monkeypatch.setenv("HFID_SIGNING_KEY", _PRIVATE_PEM)
    monkeypatch.setenv("HFID_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("HFID_CLIENT_SECRET", _CLIENT_SECRET)
    monkeypatch.delenv("HFID_ISSUER", raising=False)
    monkeypatch.delenv("HFID_REDIRECT_URIS", raising=False)
    oidc_service.reset_state()
    yield
    oidc_service.reset_state()


def _make_pkce_pair():
    """Return a (code_verifier, code_challenge) S256 pair."""
    verifier = base64.urlsafe_b64encode(b"verifier-seed-1234567890").rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _sample_request(challenge, *, state="client-state", nonce="client-nonce"):
    """A validated request; ``challenge=None`` models a client without PKCE."""
    return oidc_service.AuthorizationRequest(
        client_id=_CLIENT_ID,
        redirect_uri=oidc_service.DEFAULT_REDIRECT_URI,
        scope="openid email profile",
        state=state,
        nonce=nonce,
        code_challenge=challenge,
        code_challenge_method="S256" if challenge else None,
    )


# ============================================================================
# Kill switch / configuration
# ============================================================================

class TestKillSwitch:
    def test_disabled_when_signing_key_unset(self, monkeypatch):
        monkeypatch.delenv("HFID_SIGNING_KEY", raising=False)
        oidc_service.reset_state()
        assert oidc_service.is_enabled() is False
        assert oidc_service.build_jwks() == {"keys": []}

    def test_disabled_when_signing_key_unparseable(self, monkeypatch):
        monkeypatch.setenv("HFID_SIGNING_KEY", "-----BEGIN nonsense-----")
        oidc_service.reset_state()
        assert oidc_service.is_enabled() is False

    def test_enabled_with_valid_key(self, enabled_provider):
        assert oidc_service.is_enabled() is True


# ============================================================================
# Signing key + JWK + kid
# ============================================================================

class TestSigningKey:
    def test_jwks_contains_single_rsa_public_key(self, enabled_provider):
        jwks = oidc_service.build_jwks()
        assert len(jwks["keys"]) == 1
        key = jwks["keys"][0]
        assert key["kty"] == "RSA"
        assert key["use"] == "sig"
        assert key["alg"] == "RS256"
        assert key["n"] and key["e"]

    def test_kid_is_stable_across_calls(self, enabled_provider):
        first = oidc_service.build_jwks()["keys"][0]["kid"]
        oidc_service.reset_state()  # drop the cache; must recompute identically
        second = oidc_service.build_jwks()["keys"][0]["kid"]
        assert first == second

    def test_kid_matches_rfc7638_thumbprint(self, enabled_provider):
        key = oidc_service.build_jwks()["keys"][0]
        canonical = json.dumps(
            {"e": key["e"], "kty": "RSA", "n": key["n"]},
            separators=(",", ":"),
            sort_keys=True,
        )
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert key["kid"] == expected

    def test_escaped_newline_pem_is_accepted(self, monkeypatch):
        monkeypatch.setenv("HFID_SIGNING_KEY", _PRIVATE_PEM.replace("\n", "\\n"))
        monkeypatch.setenv("HFID_CLIENT_ID", _CLIENT_ID)
        monkeypatch.setenv("HFID_CLIENT_SECRET", _CLIENT_SECRET)
        oidc_service.reset_state()
        assert oidc_service.is_enabled() is True


# ============================================================================
# Discovery
# ============================================================================

class TestDiscovery:
    def test_discovery_document_fields(self, enabled_provider):
        doc = oidc_service.build_discovery_document()
        assert doc["issuer"] == "https://id.thehfhotel.org/oidc"
        assert doc["authorization_endpoint"] == "https://id.thehfhotel.org/oidc/authorize"
        assert doc["token_endpoint"] == "https://id.thehfhotel.org/oidc/token"
        assert doc["jwks_uri"] == "https://id.thehfhotel.org/oidc/jwks"
        assert doc["userinfo_endpoint"] == "https://id.thehfhotel.org/oidc/userinfo"
        assert doc["response_types_supported"] == ["code"]
        assert doc["id_token_signing_alg_values_supported"] == ["RS256"]
        assert doc["code_challenge_methods_supported"] == ["S256"]
        assert set(doc["scopes_supported"]) == {"openid", "email", "profile"}


class TestIssuerResolution:
    """The issuer must survive being SET TO EMPTY, not just being unset.

    Production only ever presents the empty case: docker-compose.yml passes
    ``HFID_ISSUER=${HFID_ISSUER:-}`` and no HFID_ISSUER secret is defined, so
    the container gets the variable set to "". Every test above uses the
    ``enabled_provider`` fixture, which does ``monkeypatch.delenv`` — it
    models UNSET, the one state production never has, which is how this
    reached production unnoticed.

    The consequence when it regresses: every minted id_token carries
    ``"iss": ""`` and the discovery document advertises relative endpoints,
    so any consumer that pins the issuer rejects every assertion. That took
    out both the card tap and the LINE QR scan on the reimbursement kiosk,
    which share one admission step, behind a UI message about the card.
    """

    def test_empty_issuer_falls_back_to_the_default(self, enabled_provider, monkeypatch):
        monkeypatch.setenv("HFID_ISSUER", "")
        assert oidc_service.get_issuer() == "https://id.thehfhotel.org/oidc"

    def test_whitespace_only_issuer_falls_back_to_the_default(
        self, enabled_provider, monkeypatch
    ):
        monkeypatch.setenv("HFID_ISSUER", "   ")
        assert oidc_service.get_issuer() == "https://id.thehfhotel.org/oidc"

    def test_unset_issuer_uses_the_default(self, enabled_provider):
        assert oidc_service.get_issuer() == "https://id.thehfhotel.org/oidc"

    def test_an_explicit_issuer_still_wins(self, enabled_provider, monkeypatch):
        monkeypatch.setenv("HFID_ISSUER", "https://id.example.test/oidc/")
        assert oidc_service.get_issuer() == "https://id.example.test/oidc"

    def test_discovery_endpoints_stay_absolute_when_the_env_is_empty(
        self, enabled_provider, monkeypatch
    ):
        # The live symptom: {"issuer": "", "jwks_uri": "/jwks", ...}. Relative
        # endpoints are unusable to every OIDC client, so pin absoluteness.
        monkeypatch.setenv("HFID_ISSUER", "")
        doc = oidc_service.build_discovery_document()
        assert doc["issuer"] == "https://id.thehfhotel.org/oidc"
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri",
                      "userinfo_endpoint"):
            assert doc[field].startswith("https://"), field

    def test_minted_id_token_carries_the_absolute_issuer_when_env_is_empty(
        self, enabled_provider, monkeypatch
    ):
        # The actual failure: consumers pin `iss`, so an empty one is a 401
        # at their end, not an error at ours.
        monkeypatch.setenv("HFID_ISSUER", "")
        token = oidc_service.mint_id_token(
            badge="1001",
            email="somsri@emp.thehfhotel.org",
            name="สมศรี",
            audience="reimbursement",
            apps=["reimbursement"],
            nonce=None,
        )
        claims = jwt.decode(token, options={"verify_signature": False})
        assert claims["iss"] == "https://id.thehfhotel.org/oidc"


# ============================================================================
# PKCE
# ============================================================================

class TestPkce:
    def test_valid_verifier_passes(self):
        verifier, challenge = _make_pkce_pair()
        assert oidc_service.verify_pkce_s256(verifier, challenge) is True

    def test_wrong_verifier_fails(self):
        _, challenge = _make_pkce_pair()
        assert oidc_service.verify_pkce_s256("attacker-verifier", challenge) is False

    def test_empty_verifier_fails(self):
        _, challenge = _make_pkce_pair()
        assert oidc_service.verify_pkce_s256("", challenge) is False
        assert oidc_service.verify_pkce_s256(None, challenge) is False

    def test_absent_challenge_fails(self):
        """Never "verify" against nothing — a caller that reaches here without
        a stored challenge must get False, not an accidental pass."""
        verifier, _ = _make_pkce_pair()
        assert oidc_service.verify_pkce_s256(verifier, None) is False
        assert oidc_service.verify_pkce_s256(verifier, "") is False

    def test_non_ascii_verifier_fails_closed(self):
        """RFC 7636 verifiers are ASCII; a non-ASCII one used to raise
        UnicodeEncodeError and surface as a 500 from /oidc/token."""
        _, challenge = _make_pkce_pair()
        assert oidc_service.verify_pkce_s256("ทดสอบ-verifier", challenge) is False


# ============================================================================
# Client authentication
# ============================================================================

class TestClientAuth:
    def test_correct_credentials(self, enabled_provider):
        assert oidc_service.authenticate_client(_CLIENT_ID, _CLIENT_SECRET) is True

    def test_wrong_secret_rejected(self, enabled_provider):
        assert oidc_service.authenticate_client(_CLIENT_ID, "nope") is False

    def test_missing_secret_rejected(self, enabled_provider):
        assert oidc_service.authenticate_client(_CLIENT_ID, None) is False

    def test_wrong_client_id_rejected(self, enabled_provider):
        assert oidc_service.authenticate_client("other", _CLIENT_SECRET) is False

    def test_rejected_when_no_client_configured(self, monkeypatch):
        monkeypatch.setenv("HFID_SIGNING_KEY", _PRIVATE_PEM)
        monkeypatch.delenv("HFID_CLIENT_ID", raising=False)
        monkeypatch.delenv("HFID_CLIENT_SECRET", raising=False)
        oidc_service.reset_state()
        assert oidc_service.authenticate_client("", "") is False


# ============================================================================
# Authorization request validation
# ============================================================================

class TestAuthorizationValidation:
    def _valid_kwargs(self):
        _, challenge = _make_pkce_pair()
        return dict(
            client_id=_CLIENT_ID,
            redirect_uri=oidc_service.DEFAULT_REDIRECT_URI,
            response_type="code",
            scope="openid email",
            state="s",
            nonce="n",
            code_challenge=challenge,
            code_challenge_method="S256",
        )

    def test_valid_request_returns_model(self, enabled_provider):
        req = oidc_service.validate_authorization_request(**self._valid_kwargs())
        assert req.client_id == _CLIENT_ID
        assert req.redirect_uri == oidc_service.DEFAULT_REDIRECT_URI

    def test_unknown_client_raises_hard_error(self, enabled_provider):
        kwargs = self._valid_kwargs()
        kwargs["client_id"] = "attacker"
        with pytest.raises(oidc_service.AuthorizeError):
            oidc_service.validate_authorization_request(**kwargs)

    def test_unregistered_redirect_uri_raises_hard_error(self, enabled_provider):
        kwargs = self._valid_kwargs()
        kwargs["redirect_uri"] = "https://evil.example/callback"
        with pytest.raises(oidc_service.AuthorizeError):
            oidc_service.validate_authorization_request(**kwargs)

    def test_missing_pkce_is_accepted_for_the_confidential_client(self, enabled_provider):
        """Cloudflare Access's generic OIDC connector sends no code_challenge.

        It is a confidential client (client_secret enforced at /oidc/token),
        so the authorize request must still be honoured — rejecting it here is
        what broke HF ID SSO for every Cloudflare-Access-gated app.
        """
        kwargs = self._valid_kwargs()
        kwargs["code_challenge"] = None
        kwargs["code_challenge_method"] = None
        req = oidc_service.validate_authorization_request(**kwargs)
        assert req.code_challenge is None
        assert req.code_challenge_method is None

    def test_empty_pkce_values_normalize_to_none(self, enabled_provider):
        """An empty string and None must land in the store identically, so the
        token endpoint's "did this client use PKCE?" check is a single
        truthiness test with no third state."""
        kwargs = self._valid_kwargs()
        kwargs["code_challenge"] = ""
        kwargs["code_challenge_method"] = ""
        req = oidc_service.validate_authorization_request(**kwargs)
        assert req.code_challenge is None
        assert req.code_challenge_method is None

    def test_method_without_challenge_raises_redirect_error(self, enabled_provider):
        """Half a PKCE request is incoherent — fail rather than guess."""
        kwargs = self._valid_kwargs()
        kwargs["code_challenge"] = None
        with pytest.raises(oidc_service.AuthorizeRedirectError):
            oidc_service.validate_authorization_request(**kwargs)

    def test_plain_pkce_method_raises_redirect_error(self, enabled_provider):
        kwargs = self._valid_kwargs()
        kwargs["code_challenge_method"] = "plain"
        with pytest.raises(oidc_service.AuthorizeRedirectError):
            oidc_service.validate_authorization_request(**kwargs)

    def test_non_code_response_type_raises_redirect_error(self, enabled_provider):
        kwargs = self._valid_kwargs()
        kwargs["response_type"] = "token"
        with pytest.raises(oidc_service.AuthorizeRedirectError):
            oidc_service.validate_authorization_request(**kwargs)

    def test_missing_openid_scope_raises_redirect_error(self, enabled_provider):
        kwargs = self._valid_kwargs()
        kwargs["scope"] = "email profile"
        with pytest.raises(oidc_service.AuthorizeRedirectError):
            oidc_service.validate_authorization_request(**kwargs)


# ============================================================================
# Login tickets
# ============================================================================

class TestLoginTickets:
    def test_ticket_round_trip(self, enabled_provider):
        _, challenge = _make_pkce_pair()
        ticket = oidc_service.create_login_ticket(_sample_request(challenge))
        recovered = oidc_service.consume_login_ticket(ticket)
        assert recovered is not None
        assert recovered.code_challenge == challenge

    def test_ticket_is_single_use(self, enabled_provider):
        _, challenge = _make_pkce_pair()
        ticket = oidc_service.create_login_ticket(_sample_request(challenge))
        assert oidc_service.consume_login_ticket(ticket) is not None
        assert oidc_service.consume_login_ticket(ticket) is None

    def test_expired_ticket_rejected(self, enabled_provider):
        _, challenge = _make_pkce_pair()
        ticket = oidc_service.create_login_ticket(_sample_request(challenge))
        oidc_service._login_tickets[ticket]["expires_at"] = time.time() - 1
        assert oidc_service.consume_login_ticket(ticket) is None


# ============================================================================
# Authorization codes
# ============================================================================

class TestAuthorizationCodes:
    def _issue(self):
        _, challenge = _make_pkce_pair()
        return oidc_service.issue_authorization_code(
            request=_sample_request(challenge),
            badge="Q001",
            email="q001@emp.thehfhotel.org",
            name="พนักงาน",
            apps=["rooms", "portal"],
        )

    def test_code_is_single_use(self, enabled_provider):
        code = self._issue()
        first = oidc_service.consume_authorization_code(code)
        assert first is not None
        assert first["badge"] == "Q001"
        # Replay must fail.
        assert oidc_service.consume_authorization_code(code) is None

    def test_expired_code_rejected(self, enabled_provider):
        code = self._issue()
        oidc_service._authorization_codes[code]["expires_at"] = time.time() - 1
        assert oidc_service.consume_authorization_code(code) is None

    def test_unknown_code_rejected(self, enabled_provider):
        assert oidc_service.consume_authorization_code("does-not-exist") is None

    def test_code_binds_client_redirect_and_pkce(self, enabled_provider):
        verifier, challenge = _make_pkce_pair()
        code = oidc_service.issue_authorization_code(
            request=_sample_request(challenge),
            badge="Q001",
            email="q001@emp.thehfhotel.org",
            name="พนักงาน",
            apps=[],
        )
        record = oidc_service.consume_authorization_code(code)
        assert record["client_id"] == _CLIENT_ID
        assert record["redirect_uri"] == oidc_service.DEFAULT_REDIRECT_URI
        assert oidc_service.verify_pkce_s256(verifier, record["code_challenge"])

    def test_code_without_pkce_stores_no_challenge(self, enabled_provider):
        """A PKCE-less request must store code_challenge=None — that stored
        None is exactly what the token endpoint keys its PKCE decision on."""
        code = oidc_service.issue_authorization_code(
            request=_sample_request(None),
            badge="Q001",
            email="q001@emp.thehfhotel.org",
            name="พนักงาน",
            apps=[],
        )
        record = oidc_service.consume_authorization_code(code)
        assert record["code_challenge"] is None
        # Binding and single-use are untouched by the PKCE decision.
        assert record["client_id"] == _CLIENT_ID
        assert oidc_service.consume_authorization_code(code) is None


# ============================================================================
# id_token + access token
# ============================================================================

class TestTokenMinting:
    def test_id_token_is_rs256_with_expected_claims(self, enabled_provider):
        token = oidc_service.mint_id_token(
            badge="Q001",
            email="q001@emp.thehfhotel.org",
            name="พนักงาน สมชาย",
            apps=["rooms", "portal"],
            nonce="nonce-1",
            audience=_CLIENT_ID,
        )
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256"
        assert header["kid"] == oidc_service.build_jwks()["keys"][0]["kid"]

        claims = jwt.decode(
            token,
            _PUBLIC_PEM,
            algorithms=["RS256"],
            audience=_CLIENT_ID,
            issuer="https://id.thehfhotel.org/oidc",
        )
        assert claims["sub"] == "Q001"
        assert claims["badge"] == "Q001"
        assert claims["email"] == "q001@emp.thehfhotel.org"
        assert claims["name"] == "พนักงาน สมชาย"
        assert claims["apps"] == ["rooms", "portal"]
        assert claims["nonce"] == "nonce-1"

    def test_id_token_rejects_alg_confusion(self, enabled_provider):
        token = oidc_service.mint_id_token(
            badge="Q001", email="q001@emp.thehfhotel.org", name="X",
            apps=[], nonce=None, audience=_CLIENT_ID,
        )
        # Attempting to verify an RS256 token as HS256 using the public key
        # must not succeed — PyJWT refuses to treat an asymmetric key as HMAC.
        with pytest.raises(jwt.InvalidAlgorithmError):
            jwt.decode(token, _PUBLIC_PEM, algorithms=["HS256"])

    def test_access_token_lookup(self, enabled_provider):
        token = oidc_service.issue_access_token(
            badge="Q001", email="q001@emp.thehfhotel.org",
            name="พนักงาน", apps=["rooms"],
        )
        record = oidc_service.lookup_access_token(token)
        assert record["sub"] == "Q001"
        assert record["apps"] == ["rooms"]

    def test_expired_access_token_rejected(self, enabled_provider):
        token = oidc_service.issue_access_token(
            badge="Q001", email="q001@emp.thehfhotel.org", name="X", apps=[],
        )
        oidc_service._access_tokens[token]["expires_at"] = time.time() - 1
        assert oidc_service.lookup_access_token(token) is None


# ============================================================================
# Synthetic identity derivation
# ============================================================================

class TestSyntheticEmail:
    def test_email_is_lowercased_badge_at_emp_domain(self):
        assert (
            oidc_service.synthetic_email_for_badge("Q0123")
            == "q0123@emp.thehfhotel.org"
        )
