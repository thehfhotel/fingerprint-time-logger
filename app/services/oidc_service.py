"""
HF ID — minimal OIDC identity provider (Authorization Code + PKCE).

Cloudflare Access registers this as a generic OIDC IdP so LINE-only
employees can sign into gated apps with one LINE tap. HF ID does not
authenticate anyone itself: /oidc/authorize brokers the browser into the
existing LINE OAuth login (app/api/line_auth.py) and, once LINE resolves a
line_user_id, asserts a synthetic identity for the matching employee.

Design notes
------------
* Ships DARK. When ``HFID_SIGNING_KEY`` is unset the whole /oidc surface is
  disabled (endpoints 404), mirroring the ``CF_AUTO_LOGIN`` kill-switch
  precedent. Nothing secret lives in the image — the RSA private key and the
  confidential client credentials are injected via environment only.
* Config is read lazily from the environment on each call (like
  cf_access_service / line_auth_service), so tests can flip it with
  monkeypatch and the parsed key is cached by its PEM content.
* State is in-memory. The service runs as a single instance (see
  docker-compose.yml / CLAUDE.md), so login tickets, one-time authorization
  codes and opaque access tokens live in process-local dicts guarded by a
  lock, exactly like line_auth_service's CSRF-state storage.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

logger = logging.getLogger(__name__)

# ============================================================================
# Constants — TTLs and defaults
# ============================================================================

# Authorization codes are single-use and must be redeemed almost immediately
# by Cloudflare Access's server-to-server token call. Kept short per spec.
AUTHORIZATION_CODE_TTL_SECONDS = 60
# The login ticket bridges /oidc/authorize -> LINE round trip -> callback.
# It must outlive a human completing the LINE consent screen.
LOGIN_TICKET_TTL_SECONDS = 600  # 10 minutes
# id_token and the opaque access token used for /oidc/userinfo.
ID_TOKEN_TTL_SECONDS = 300  # ~5 minutes
ACCESS_TOKEN_TTL_SECONDS = 300  # ~5 minutes

DEFAULT_ISSUER = "https://id.thehfhotel.org/oidc"
# Cloudflare Access team callback (laikaexpress). Exact-match allowlisted.
DEFAULT_REDIRECT_URI = (
    "https://laikaexpress.cloudflareaccess.com/cdn-cgi/access/callback"
)
# Synthetic identity domain for LINE-only employees (see employee registry).
SYNTHETIC_EMAIL_DOMAIN = "emp.thehfhotel.org"

SUPPORTED_SCOPES = ("openid", "email", "profile")

# ============================================================================
# In-memory stores (single-instance; guarded by a lock)
# ============================================================================

_store_lock = threading.Lock()
# ticket_id -> {"request": AuthorizationRequest, "expires_at": float}
_login_tickets: Dict[str, Dict[str, Any]] = {}
# code -> {claims + binding + "expires_at": float, "used": bool}
_authorization_codes: Dict[str, Dict[str, Any]] = {}
# access_token -> {claims + "expires_at": float}
_access_tokens: Dict[str, Dict[str, Any]] = {}
# Parsed signing-key material cached by normalized PEM string.
_key_material_cache: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# Request/validation types
# ============================================================================

@dataclass
class AuthorizationRequest:
    """A validated /oidc/authorize request, stashed in a login ticket."""

    client_id: str
    redirect_uri: str
    scope: str
    state: Optional[str]
    nonce: Optional[str]
    code_challenge: str
    code_challenge_method: str


class AuthorizeError(Exception):
    """Unrecoverable /authorize error — render an error page, never redirect.

    Raised only when the client_id or redirect_uri cannot be trusted, so the
    browser must NOT be redirected to an attacker-influenced location.
    """


class AuthorizeRedirectError(Exception):
    """Recoverable /authorize error — redirect back with an OAuth error.

    Used once redirect_uri has been validated against the allowlist, so it is
    safe to bounce the error (and the original ``state``) back to the client.
    """

    def __init__(self, error: str, description: str, redirect_uri: str,
                 state: Optional[str]) -> None:
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
        self.redirect_uri = redirect_uri
        self.state = state


# ============================================================================
# Configuration (read lazily from the environment)
# ============================================================================

def _raw_signing_key() -> str:
    """The raw ``HFID_SIGNING_KEY`` PEM from the environment (may be empty)."""
    return os.getenv("HFID_SIGNING_KEY", "").strip()


def is_enabled() -> bool:
    """Whether HF ID is configured. When False the whole /oidc surface is dark.

    A signing key that fails to parse also disables the provider — we never
    serve a JWKS or attempt to sign without a usable RSA private key.
    """
    return _load_key_material() is not None


def get_issuer() -> str:
    """OIDC issuer identifier (also the base for every endpoint URL)."""
    return os.getenv("HFID_ISSUER", DEFAULT_ISSUER).strip().rstrip("/")


def get_client_id() -> str:
    """The confidential client id (Cloudflare Access)."""
    return os.getenv("HFID_CLIENT_ID", "").strip()


def get_client_secret() -> str:
    """The confidential client secret (Cloudflare Access)."""
    return os.getenv("HFID_CLIENT_SECRET", "")


def get_allowed_redirect_uris() -> List[str]:
    """Exact-match redirect_uri allowlist (defaults to the CF Access callback)."""
    raw = os.getenv("HFID_REDIRECT_URIS", "").strip()
    if not raw:
        return [DEFAULT_REDIRECT_URI]
    return [uri.strip() for uri in raw.split(",") if uri.strip()]


def get_endpoints() -> Dict[str, str]:
    """Absolute URLs for every OIDC endpoint, derived from the issuer."""
    issuer = get_issuer()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "jwks_uri": f"{issuer}/jwks",
        "userinfo_endpoint": f"{issuer}/userinfo",
    }


# ============================================================================
# Signing key + JWK
# ============================================================================

def _base64url_uint(value: int) -> str:
    """Encode a non-negative integer as an unpadded base64url big-endian string."""
    byte_length = (value.bit_length() + 7) // 8 or 1
    raw = value.to_bytes(byte_length, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _compute_kid(modulus_b64: str, exponent_b64: str) -> str:
    """RFC 7638 JWK thumbprint over the RSA public key — a stable ``kid``.

    The thumbprint is computed over the required members in lexicographic
    order (``e``, ``kty``, ``n``) with no whitespace, so it is deterministic
    for a given public key and never changes across restarts or redeploys.
    """
    canonical = json.dumps(
        {"e": exponent_b64, "kty": "RSA", "n": modulus_b64},
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _load_key_material() -> Optional[Dict[str, Any]]:
    """Parse ``HFID_SIGNING_KEY`` into signing material, or None when dark.

    Returns a dict with ``kid``, the public ``jwk``, and the PKCS8 private
    ``pem`` used for signing. Result is cached by normalized PEM content so
    repeated calls are cheap while a changed key (tests) reloads.
    """
    raw = _raw_signing_key()
    if not raw:
        return None

    # Support both real newlines and ``\n``-escaped single-line env values.
    normalized = raw.replace("\\n", "\n")

    cached = _key_material_cache.get(normalized)
    if cached is not None:
        return cached

    try:
        private_key = serialization.load_pem_private_key(
            normalized.encode("utf-8"), password=None
        )
    except Exception as exc:  # noqa: BLE001 — any parse failure means "dark"
        logger.error("HFID_SIGNING_KEY could not be parsed: %s", exc)
        return None

    if not isinstance(private_key, rsa.RSAPrivateKey):
        logger.error("HFID_SIGNING_KEY is not an RSA private key — HF ID disabled")
        return None

    public_numbers = private_key.public_key().public_numbers()
    modulus_b64 = _base64url_uint(public_numbers.n)
    exponent_b64 = _base64url_uint(public_numbers.e)
    kid = _compute_kid(modulus_b64, exponent_b64)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    material = {
        "kid": kid,
        "jwk": {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": kid,
            "n": modulus_b64,
            "e": exponent_b64,
        },
        "pem": private_pem,
    }
    _key_material_cache[normalized] = material
    return material


def build_jwks() -> Dict[str, Any]:
    """Public JWKS document. Empty ``keys`` when the provider is dark."""
    material = _load_key_material()
    if material is None:
        return {"keys": []}
    return {"keys": [material["jwk"]]}


def build_discovery_document() -> Dict[str, Any]:
    """The OpenID Provider metadata served at the discovery endpoint."""
    endpoints = get_endpoints()
    return {
        **endpoints,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "scopes_supported": list(SUPPORTED_SCOPES),
        "id_token_signing_alg_values_supported": ["RS256"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "claims_supported": [
            "sub", "iss", "aud", "exp", "iat", "nonce",
            "email", "name", "apps", "badge",
        ],
    }


# ============================================================================
# Authorization request validation
# ============================================================================

def validate_authorization_request(
    *,
    client_id: Optional[str],
    redirect_uri: Optional[str],
    response_type: Optional[str],
    scope: Optional[str],
    state: Optional[str],
    nonce: Optional[str],
    code_challenge: Optional[str],
    code_challenge_method: Optional[str],
) -> AuthorizationRequest:
    """Validate an /oidc/authorize request, or raise.

    Order matters: client_id and redirect_uri are checked first and, on
    failure, raise :class:`AuthorizeError` (render a page — never redirect an
    untrusted URI). Everything after that raises :class:`AuthorizeRedirectError`
    so the OAuth error can be safely bounced back to the validated client.
    """
    expected_client_id = get_client_id()
    if not expected_client_id or client_id != expected_client_id:
        raise AuthorizeError("unknown client_id")

    if not redirect_uri or redirect_uri not in get_allowed_redirect_uris():
        raise AuthorizeError("redirect_uri is not registered")

    # redirect_uri is now trusted — recoverable errors may be redirected back.
    if response_type != "code":
        raise AuthorizeRedirectError(
            "unsupported_response_type",
            "only response_type=code is supported",
            redirect_uri, state,
        )

    scope_values = (scope or "").split()
    if "openid" not in scope_values:
        raise AuthorizeRedirectError(
            "invalid_scope", "the openid scope is required", redirect_uri, state,
        )

    if not code_challenge:
        raise AuthorizeRedirectError(
            "invalid_request", "PKCE code_challenge is required",
            redirect_uri, state,
        )

    if code_challenge_method != "S256":
        raise AuthorizeRedirectError(
            "invalid_request", "code_challenge_method must be S256",
            redirect_uri, state,
        )

    return AuthorizationRequest(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope or "openid",
        state=state,
        nonce=nonce,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )


# ============================================================================
# Login tickets (bridge the LINE round trip)
# ============================================================================

def _prune_expired_locked(now: float) -> None:
    """Drop expired tickets/codes/tokens. Must hold ``_store_lock``."""
    for ticket_id in [k for k, v in _login_tickets.items()
                      if v["expires_at"] <= now]:
        _login_tickets.pop(ticket_id, None)
    for code in [k for k, v in _authorization_codes.items()
                 if v["expires_at"] <= now]:
        _authorization_codes.pop(code, None)
    for token in [k for k, v in _access_tokens.items()
                  if v["expires_at"] <= now]:
        _access_tokens.pop(token, None)


def create_login_ticket(request: AuthorizationRequest) -> str:
    """Stash a validated authorization request; return an opaque ticket id."""
    ticket_id = secrets.token_urlsafe(32)
    now = time.time()
    with _store_lock:
        _prune_expired_locked(now)
        _login_tickets[ticket_id] = {
            "request": request,
            "expires_at": now + LOGIN_TICKET_TTL_SECONDS,
        }
    return ticket_id


def consume_login_ticket(ticket_id: str) -> Optional[AuthorizationRequest]:
    """Atomically fetch-and-remove a login ticket, or None if missing/expired."""
    now = time.time()
    with _store_lock:
        record = _login_tickets.pop(ticket_id, None)
    if record is None or record["expires_at"] <= now:
        return None
    return record["request"]


# ============================================================================
# Authorization codes (single-use, short-lived, bound)
# ============================================================================

def issue_authorization_code(
    *,
    request: AuthorizationRequest,
    badge: str,
    email: str,
    name: str,
    apps: List[str],
) -> str:
    """Mint a single-use authorization code bound to the request + identity."""
    code = secrets.token_urlsafe(32)
    now = time.time()
    with _store_lock:
        _prune_expired_locked(now)
        _authorization_codes[code] = {
            "client_id": request.client_id,
            "redirect_uri": request.redirect_uri,
            "code_challenge": request.code_challenge,
            "nonce": request.nonce,
            "badge": badge,
            "email": email,
            "name": name,
            "apps": list(apps),
            "expires_at": now + AUTHORIZATION_CODE_TTL_SECONDS,
            "used": False,
        }
    return code


def consume_authorization_code(code: str) -> Optional[Dict[str, Any]]:
    """Atomically redeem a code exactly once.

    Returns a copy of the stored binding + claims, or None when the code is
    unknown, expired, or already used (replay). The code is marked used under
    the lock so concurrent redemptions cannot both succeed.
    """
    now = time.time()
    with _store_lock:
        record = _authorization_codes.get(code)
        if record is None:
            return None
        if record["used"] or record["expires_at"] <= now:
            return None
        record["used"] = True
        return dict(record)


# ============================================================================
# PKCE + client authentication
# ============================================================================

def verify_pkce_s256(code_verifier: Optional[str], code_challenge: str) -> bool:
    """Verify ``BASE64URL(SHA256(code_verifier)) == code_challenge`` (S256)."""
    if not code_verifier:
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(computed, code_challenge)


def authenticate_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> bool:
    """Constant-time check of confidential client credentials."""
    expected_id = get_client_id()
    expected_secret = get_client_secret()
    if not expected_id or not expected_secret:
        return False
    if client_id is None or client_secret is None:
        return False
    return (
        hmac.compare_digest(client_id, expected_id)
        and hmac.compare_digest(client_secret, expected_secret)
    )


# ============================================================================
# Token minting
# ============================================================================

def mint_id_token(
    *,
    badge: str,
    email: str,
    name: str,
    apps: List[str],
    nonce: Optional[str],
    audience: str,
) -> str:
    """Sign an RS256 id_token. The algorithm is fixed — never taken from input."""
    material = _load_key_material()
    if material is None:
        raise RuntimeError("HF ID signing key is unavailable")

    now = int(time.time())
    payload: Dict[str, Any] = {
        "iss": get_issuer(),
        "sub": badge,
        "aud": audience,
        "iat": now,
        "exp": now + ID_TOKEN_TTL_SECONDS,
        "email": email,
        "name": name,
        # Custom claims Cloudflare Access maps to policies.
        "apps": list(apps),
        "badge": badge,
    }
    if nonce:
        payload["nonce"] = nonce

    return jwt.encode(
        payload,
        material["pem"],
        algorithm="RS256",
        headers={"kid": material["kid"]},
    )


def issue_access_token(
    *, badge: str, email: str, name: str, apps: List[str]
) -> str:
    """Issue an opaque bearer access token for /oidc/userinfo."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _store_lock:
        _prune_expired_locked(now)
        _access_tokens[token] = {
            "sub": badge,
            "badge": badge,
            "email": email,
            "name": name,
            "apps": list(apps),
            "expires_at": now + ACCESS_TOKEN_TTL_SECONDS,
        }
    return token


def lookup_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Resolve an opaque access token to its stored claims, or None."""
    now = time.time()
    with _store_lock:
        record = _access_tokens.get(token)
    if record is None or record["expires_at"] <= now:
        return None
    return dict(record)


# ============================================================================
# Identity derivation helpers
# ============================================================================

def synthetic_email_for_badge(badge: str) -> str:
    """The synthetic ``q####@emp.thehfhotel.org`` identity for a badge."""
    return f"{badge.lower()}@{SYNTHETIC_EMAIL_DOMAIN}"


# ============================================================================
# Test support
# ============================================================================

def reset_state() -> None:
    """Clear all in-memory stores + the key cache (test isolation only)."""
    with _store_lock:
        _login_tickets.clear()
        _authorization_codes.clear()
        _access_tokens.clear()
        _key_material_cache.clear()
