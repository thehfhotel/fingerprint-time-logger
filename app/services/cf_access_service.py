"""
Cloudflare Access verification for the admin auto-login path.

A manager who has already passed Cloudflare Access (the CF edge, in front
of the app) should not have to re-enter the shared admin passcode. This
module verifies the identity Cloudflare asserts about the request.

SECURITY: the container's port :5000 is LAN-reachable and bypasses
Cloudflare's edge entirely. An attacker on the LAN can set
``Cf-Access-Jwt-Assertion`` to any value they like. Presence of the header
proves NOTHING by itself — every token is fully verified here: RS256
signature against Cloudflare's published JWKS, issuer, audience, and
expiry. Verification failures are logged and treated as "not CF
authenticated", never raised, so callers can fall back to the existing
passcode session.
"""
import logging
import os
from typing import List, Optional

import jwt

from app.services import manager_directory

logger = logging.getLogger(__name__)

# Cloudflare Access team domain that signs these tokens, and the JWKS
# endpoint used to verify them. Not secrets — this is Cloudflare's public
# key discovery endpoint for our team.
CF_ACCESS_TEAM_DOMAIN = "https://laikaexpress.cloudflareaccess.com"
CF_ACCESS_JWKS_URL = f"{CF_ACCESS_TEAM_DOMAIN}/cdn-cgi/access/certs"

# Access "application audience" (AUD) tags this deployment accepts. These
# identify which Cloudflare Access applications a token was minted for —
# public identifiers, not secrets. Override with CF_ACCESS_AUDS
# (comma-separated) if additional Access apps should be trusted.
_DEFAULT_ACCESS_AUDS = (
    # /fingerprintlogs* Access application
    "3c622b40cc931c7414dcfc583bed1f50afaac316eafb914cc7f153650843ea8b",
    # erp root Access application
    "57f843579497b508143412a5980c1c4fc94ca01abadab465b57a88b5a733e487",
)

# Admin allowlist for CF Access auto-login. The Access applications that
# front these pages (aud tags above) also admit employee-tier accounts
# (e.g. shared hotel mailboxes) — a verified CF Access identity is NOT by
# itself proof of admin privilege. Only admins get auto-login; everyone
# else falls through to the passcode path.
#
# WHO counts as an admin now lives in app/services/manager_directory.py: it
# tracks the HF Portal's "HF Managers" tier (GET /portal-api/directory/managers)
# so portal membership changes actually reach this app, and falls back to the
# list below — the pre-directory behaviour, kept verbatim as the floor — when
# no live directory answer has ever been obtained. Not secrets. Still
# overridable with CF_ADMIN_EMAILS (comma-separated), which replaces the floor.
_DEFAULT_ADMIN_EMAILS = manager_directory.STATIC_ADMIN_EMAILS

# PyJWKClient caches fetched keys internally and only refetches on a
# kid it hasn't seen, so a single module-level instance is intentional.
_jwks_client = jwt.PyJWKClient(CF_ACCESS_JWKS_URL)


def _resolve_accepted_auds() -> List[str]:
    """Accepted Access application audiences, with env override."""
    raw = os.getenv("CF_ACCESS_AUDS", "").strip()
    if not raw:
        return list(_DEFAULT_ACCESS_AUDS)
    return [aud.strip() for aud in raw.split(",") if aud.strip()]


def _resolve_admin_emails() -> List[str]:
    """The admin allowlist FLOOR — CF_ADMIN_EMAILS if set, else the in-code list.

    This is what applies when the portal manager directory has never answered
    (dormant, down, or unreachable). Comparisons are case-insensitive, so all
    entries are lowercased here.
    """
    return sorted(manager_directory._floor_emails())


def _is_allowlisted_admin_email(email: str) -> bool:
    """Whether a CF-verified email belongs to an admin (case-insensitive).

    Delegates to the manager directory, which resolves the live portal
    "HF Managers" tier first and falls back to the floor above. No network I/O
    happens here — the directory serves an in-memory snapshot refreshed on a
    background thread.
    """
    return manager_directory.is_admin_email(email)


def is_cf_auto_login_enabled() -> bool:
    """Kill switch for CF Access auto-login. Defaults to enabled."""
    return os.getenv("CF_AUTO_LOGIN", "true").strip().lower() not in ("false", "0", "no")


def verify_cf_access(token: str) -> Optional[str]:
    """
    Fully verify a Cloudflare Access JWT and return the authenticated email.

    Checks (all mandatory, none skippable):
      - RS256 signature against Cloudflare's JWKS
      - issuer == our Cloudflare Access team domain
      - audience is one of the accepted Access application tags
      - expiry (PyJWT checks this by default during decode)

    Returns None — never raises — when the token is missing, malformed,
    expired, or fails any check. Callers must treat None as "not CF
    authenticated" and fall back to the passcode session path.
    """
    if not token:
        return None

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=CF_ACCESS_TEAM_DOMAIN,
            audience=_resolve_accepted_auds(),
        )
    except jwt.PyJWTError as exc:
        logger.warning(f"Cloudflare Access JWT rejected: {exc}")
        return None
    except Exception as exc:
        # JWKS fetch/network errors and anything else unexpected — treat
        # as "not verified" rather than letting the request crash.
        logger.warning(f"Cloudflare Access JWT verification failed: {exc}")
        return None

    email = claims.get("email")
    if not email:
        logger.warning("Cloudflare Access JWT verified but had no email claim")
        return None
    return email


def _extract_cf_access_token(request_like) -> Optional[str]:
    """
    Pull the Cloudflare Access JWT off a Request or WebSocket.

    Both Starlette ``Request`` and ``WebSocket`` expose ``.headers`` and
    ``.cookies``, so this works uniformly for HTTP routes and the
    WebSocket guard.

    Checks the header Cloudflare's edge injects for proxied requests
    first, then the cookie the Access UI sets client-side.
    """
    header_token = request_like.headers.get("Cf-Access-Jwt-Assertion")
    if header_token:
        return header_token
    return request_like.cookies.get("CF_Authorization")


def get_cf_access_email(request_like) -> Optional[str]:
    """
    Resolve the authenticated ADMIN email for this request via Cloudflare
    Access, or None if unavailable, disabled, invalid, or not on the admin
    allowlist.

    This is the single entry point callers (page guards, the WebSocket
    guard, and the admin auth dependency) should use.

    IMPORTANT: a fully-verified CF Access JWT proves the request passed
    Cloudflare Access, but the Access applications fronting these pages
    also admit employee-tier accounts — so verification alone is NOT
    sufficient to grant admin access. The email must ALSO be an admin per
    the manager directory (app/services/manager_directory.py: the portal's
    live "HF Managers" tier, or the CF_ADMIN_EMAILS / in-code floor when the
    portal has never answered). A verified-but-non-admin email is treated
    exactly like a missing/invalid token: it falls through to the
    passcode session path, never granted admin access.
    """
    if not is_cf_auto_login_enabled():
        return None

    token = _extract_cf_access_token(request_like)
    if not token:
        return None

    email = verify_cf_access(token)
    if not email:
        return None

    if not _is_allowlisted_admin_email(email):
        logger.info(f"CF Access identity verified but not admin-allowlisted: {email}")
        return None

    return email
