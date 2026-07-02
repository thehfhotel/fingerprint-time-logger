"""
HF ID — OIDC provider endpoints (Authorization Code + PKCE), served at /oidc.

Cloudflare Access is the single confidential client. The employee never sees
a password: /oidc/authorize brokers the browser into the existing LINE OAuth
login, and the LINE callback (app/api/line_auth.py) hands control back here
via :func:`continue_oidc_after_line` once a line_user_id is resolved.

The whole surface is DARK until ``HFID_SIGNING_KEY`` is configured — every
endpoint 404s while the provider is disabled.
"""

import base64
import binascii
import logging
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee, EmployeeAppGrant
from app.services import oidc_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Where a not-yet-registered LINE user is sent to self-onboard.
_ONBOARD_PATH = "/qr-checkin/onboard"
# The existing LINE login entrypoint. Reused verbatim (no LINE config is
# duplicated) — the ``redirect`` hint carries the OIDC login ticket so the
# LINE callback can hand control back to this module.
_LINE_LOGIN_PATH = "/api/public/auth/line/login"


# ============================================================================
# Small HTML helpers (chromeless, mirror the LINE-flow error/landing pages)
# ============================================================================

def _html_page(title: str, heading: str, message: str,
               status_code: int = 200) -> HTMLResponse:
    """Render a minimal, self-contained status page (no external assets)."""
    safe = {
        "title": _escape(title),
        "heading": _escape(heading),
        "message": _escape(message),
    }
    content = f"""<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{safe['title']}</title>
    <style>
        body {{
            font-family: 'Sarabun', 'Prompt', sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0; background: #f5f5f5; color: #333;
        }}
        .card {{
            background: #fff; padding: 32px; border-radius: 12px;
            box-shadow: 0 2px 16px rgba(0,0,0,0.08);
            text-align: center; max-width: 420px; margin: 16px;
        }}
        h1 {{ font-size: 20px; margin: 0 0 12px; color: #6b1f2a; }}
        p {{ color: #666; line-height: 1.6; margin: 0; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{safe['heading']}</h1>
        <p>{safe['message']}</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=content, status_code=status_code)


def _escape(value: str) -> str:
    """Escape text for safe interpolation into the status page markup."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _require_enabled() -> None:
    """404 the endpoint when HF ID is not configured (dark)."""
    if not oidc_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
        )


def _redirect_with_error(
    error: "oidc_service.AuthorizeRedirectError",
) -> RedirectResponse:
    """Bounce a recoverable /authorize error back to the trusted redirect_uri."""
    params = {"error": error.error, "error_description": error.description}
    if error.state is not None:
        params["state"] = error.state
    separator = "&" if "?" in error.redirect_uri else "?"
    url = f"{error.redirect_uri}{separator}{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


# ============================================================================
# Discovery + JWKS
# ============================================================================

@router.get("/.well-known/openid-configuration")
async def openid_configuration():
    """OpenID Provider metadata (issuer, endpoints, supported params)."""
    _require_enabled()
    return JSONResponse(oidc_service.build_discovery_document())


@router.get("/jwks")
async def jwks():
    """Public RSA JWK set used to verify id_tokens."""
    _require_enabled()
    return JSONResponse(oidc_service.build_jwks())


# ============================================================================
# Authorization endpoint
# ============================================================================

@router.get("/authorize")
async def authorize(
    request: Request,
    client_id: Optional[str] = Query(None),
    redirect_uri: Optional[str] = Query(None),
    response_type: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    nonce: Optional[str] = Query(None),
    code_challenge: Optional[str] = Query(None),
    code_challenge_method: Optional[str] = Query(None),
):
    """Validate the OIDC request, then broker the browser into LINE login.

    On success the validated request is stashed in a short-TTL server-side
    login ticket and the browser is redirected into the existing LINE OAuth
    login carrying an ``oidc:<ticket>`` hint. No authorization code is minted
    until the LINE callback resolves an eligible employee.
    """
    _require_enabled()

    try:
        oidc_request = oidc_service.validate_authorization_request(
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            scope=scope,
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )
    except oidc_service.AuthorizeError as exc:
        return _html_page(
            "HF ID",
            "คำขอเข้าสู่ระบบไม่ถูกต้อง",
            f"ไม่สามารถดำเนินการต่อได้ ({exc})",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except oidc_service.AuthorizeRedirectError as exc:
        return _redirect_with_error(exc)

    ticket_id = oidc_service.create_login_ticket(oidc_request)
    redirect_hint = urllib.parse.quote(f"oidc:{ticket_id}", safe="")
    login_url = f"{_LINE_LOGIN_PATH}?redirect={redirect_hint}"
    return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)


def continue_oidc_after_line(
    *, ticket_id: str, line_user_id: str, db: Session
):
    """Resume an OIDC login after LINE resolves ``line_user_id``.

    Called from the LINE OAuth callback (app/api/line_auth.py) via an additive
    hook. Only an employee that is active, not pending approval, and matched by
    line_user_id may proceed; everyone else is routed to onboarding or an
    "awaiting approval / access disabled" page — never issued a code.
    """
    oidc_request = oidc_service.consume_login_ticket(ticket_id)
    if oidc_request is None:
        return _html_page(
            "HF ID",
            "คำขอหมดอายุ",
            "เซสชันการเข้าสู่ระบบหมดอายุแล้ว กรุณาเริ่มใหม่อีกครั้ง",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    employee = (
        db.query(Employee)
        .filter(Employee.line_user_id == line_user_id)
        .first()
    )

    # A valid LINE user with no employee row is a prospective new hire.
    if employee is None:
        return RedirectResponse(
            url=_ONBOARD_PATH, status_code=status.HTTP_302_FOUND
        )

    # Registered but not yet cleared for access.
    if employee.pending_approval or not employee.is_active:
        return _html_page(
            "HF ID",
            "บัญชียังไม่พร้อมใช้งาน",
            "บัญชีของคุณกำลังรอการอนุมัติ หรือถูกปิดการใช้งาน "
            "กรุณาติดต่อผู้ดูแลระบบ",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    email = employee.email or oidc_service.synthetic_email_for_badge(
        employee.badge_number
    )
    name = employee.display_name or ""
    apps = [
        grant.app_id
        for grant in (
            db.query(EmployeeAppGrant)
            .filter(
                EmployeeAppGrant.employee_badge_number == employee.badge_number
            )
            .order_by(EmployeeAppGrant.app_id)
            .all()
        )
    ]

    code = oidc_service.issue_authorization_code(
        request=oidc_request,
        badge=employee.badge_number,
        email=email,
        name=name,
        apps=apps,
    )

    params = {"code": code}
    if oidc_request.state is not None:
        params["state"] = oidc_request.state
    separator = "&" if "?" in oidc_request.redirect_uri else "?"
    url = f"{oidc_request.redirect_uri}{separator}{urllib.parse.urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


# ============================================================================
# Token endpoint
# ============================================================================

def _parse_basic_client_auth(authorization: Optional[str]):
    """Extract (client_id, client_secret) from a Basic Authorization header.

    Returns (None, None) when the header is absent or not Basic, so callers
    can fall back to client_secret_post form fields.
    """
    if not authorization:
        return None, None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None, None
    try:
        decoded = base64.b64decode(parts[1].strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None, None
    if ":" not in decoded:
        return None, None
    # Per RFC 6749 the userid/password are form-urlencoded before base64.
    client_id, client_secret = decoded.split(":", 1)
    return urllib.parse.unquote(client_id), urllib.parse.unquote(client_secret)


def _token_error(error: str, http_status: int, description: Optional[str] = None,
                 headers: Optional[dict] = None) -> JSONResponse:
    """Build an RFC 6749 token error response with no-store caching."""
    body = {"error": error}
    if description:
        body["error_description"] = description
    response_headers = {"Cache-Control": "no-store", "Pragma": "no-cache"}
    if headers:
        response_headers.update(headers)
    return JSONResponse(body, status_code=http_status, headers=response_headers)


@router.post("/token")
async def token(
    grant_type: Optional[str] = Form(None),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
):
    """Exchange an authorization code for an id_token + access token.

    Accepts both client_secret_basic and client_secret_post. Validates client
    auth, single-use code redemption, redirect_uri binding, and PKCE (S256)
    before minting an RS256 id_token.
    """
    _require_enabled()

    # Client authentication — Basic header takes precedence, then form fields.
    basic_id, basic_secret = _parse_basic_client_auth(authorization)
    auth_client_id = basic_id if basic_id is not None else client_id
    auth_client_secret = basic_secret if basic_secret is not None else client_secret

    if not oidc_service.authenticate_client(auth_client_id, auth_client_secret):
        return _token_error(
            "invalid_client",
            status.HTTP_401_UNAUTHORIZED,
            "client authentication failed",
            headers={"WWW-Authenticate": "Basic"},
        )

    if grant_type != "authorization_code":
        return _token_error(
            "unsupported_grant_type", status.HTTP_400_BAD_REQUEST,
            "only authorization_code is supported",
        )

    if not code:
        return _token_error(
            "invalid_request", status.HTTP_400_BAD_REQUEST, "code is required"
        )

    if not code_verifier:
        return _token_error(
            "invalid_request", status.HTTP_400_BAD_REQUEST,
            "code_verifier is required",
        )

    record = oidc_service.consume_authorization_code(code)
    if record is None:
        return _token_error(
            "invalid_grant", status.HTTP_400_BAD_REQUEST,
            "authorization code is invalid, expired, or already used",
        )

    # The code is bound to the client it was issued for.
    if auth_client_id is None or not _constant_time_equals(
        record["client_id"], auth_client_id
    ):
        return _token_error(
            "invalid_grant", status.HTTP_400_BAD_REQUEST,
            "authorization code was issued to a different client",
        )

    if redirect_uri != record["redirect_uri"]:
        return _token_error(
            "invalid_grant", status.HTTP_400_BAD_REQUEST,
            "redirect_uri does not match the authorization request",
        )

    if not oidc_service.verify_pkce_s256(code_verifier, record["code_challenge"]):
        return _token_error(
            "invalid_grant", status.HTTP_400_BAD_REQUEST,
            "PKCE verification failed",
        )

    id_token = oidc_service.mint_id_token(
        badge=record["badge"],
        email=record["email"],
        name=record["name"],
        apps=record["apps"],
        nonce=record["nonce"],
        audience=record["client_id"],
    )
    access_token = oidc_service.issue_access_token(
        badge=record["badge"],
        email=record["email"],
        name=record["name"],
        apps=record["apps"],
    )

    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": oidc_service.ACCESS_TOKEN_TTL_SECONDS,
            "id_token": id_token,
            "scope": "openid email profile",
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _constant_time_equals(left: str, right: str) -> bool:
    """Constant-time string comparison."""
    import hmac

    return hmac.compare_digest(left, right)


# ============================================================================
# UserInfo endpoint
# ============================================================================

@router.get("/userinfo")
async def userinfo(authorization: Optional[str] = Header(None)):
    """Return the identity claims for a valid Bearer access token."""
    _require_enabled()

    token_value = _extract_bearer_token(authorization)
    record = oidc_service.lookup_access_token(token_value)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    return {
        "sub": record["sub"],
        "email": record["email"],
        "name": record["name"],
        "apps": record["apps"],
        "badge": record["badge"],
    }


def _extract_bearer_token(authorization: Optional[str]) -> str:
    """Extract a Bearer token from an Authorization header, or 401."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authorization header must be 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1].strip()
