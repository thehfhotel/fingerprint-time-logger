"""
Admin Authentication API
Secure passcode authentication with session management
"""
from fastapi import APIRouter, HTTPException, Header, Depends, Response, Cookie, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, List
import logging
import os
import threading
import time

from app.services.admin_auth_service import admin_auth_service
from app.services.cf_access_service import get_cf_access_email

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Per-IP failed-login throttle ---------------------------------------------
# 5 failures within 15 minutes triggers a 15-minute lockout.
_FAILED_ATTEMPT_WINDOW_SECONDS = 15 * 60
_FAILED_ATTEMPT_THRESHOLD = 5
_failed_attempts: Dict[str, List[float]] = {}
_failed_attempts_lock = threading.Lock()


def _is_behind_proxy() -> bool:
    return os.getenv("BEHIND_PROXY", "false").lower() == "true"


def _get_client_ip(request: Request) -> str:
    """
    Resolve client IP when behind a trusted proxy.

    Trust order when ``BEHIND_PROXY=true``:
      1. ``CF-Connecting-IP`` — Cloudflare overwrites this per-request, so it
         cannot be spoofed by an attacker upstream of Cloudflare.
      2. First hop of ``X-Forwarded-For`` — only used when CF header is absent
         (assumes the proxy contract overwrites or trims XFF).
      3. ``request.client.host`` — direct-connection fallback.
    """
    if _is_behind_proxy():
        cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
        if cf_ip:
            return cf_ip
        forwarded = request.headers.get("X-Forwarded-For", "").strip()
        if forwarded:
            first_ip = forwarded.split(",")[0].strip()
            if first_ip:
                return first_ip
    return request.client.host if request.client else "unknown"


def _prune_expired_attempts(now: float) -> None:
    """Remove timestamps older than the window. Must be called under the lock."""
    cutoff = now - _FAILED_ATTEMPT_WINDOW_SECONDS
    for ip in list(_failed_attempts.keys()):
        recent = [ts for ts in _failed_attempts[ip] if ts >= cutoff]
        if recent:
            _failed_attempts[ip] = recent
        else:
            del _failed_attempts[ip]


def _check_lockout(ip: str) -> None:
    """Raise HTTP 429 if this IP has hit the lockout threshold."""
    now = time.time()
    with _failed_attempts_lock:
        _prune_expired_attempts(now)
        attempts = _failed_attempts.get(ip, [])
        if len(attempts) >= _FAILED_ATTEMPT_THRESHOLD:
            oldest = min(attempts)
            seconds_until_reset = int(_FAILED_ATTEMPT_WINDOW_SECONDS - (now - oldest))
            seconds_until_reset = max(seconds_until_reset, 1)
            minutes = max(1, (seconds_until_reset + 59) // 60)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in {minutes} minutes.",
                headers={"Retry-After": str(seconds_until_reset)}
            )


def _record_failed_attempt(ip: str) -> None:
    now = time.time()
    with _failed_attempts_lock:
        _prune_expired_attempts(now)
        _failed_attempts.setdefault(ip, []).append(now)


def _clear_failed_attempts(ip: str) -> None:
    with _failed_attempts_lock:
        _failed_attempts.pop(ip, None)

class LoginRequest(BaseModel):
    passcode: str = Field(..., min_length=1, description="Admin passcode")

class LoginResponse(BaseModel):
    success: bool
    token: str
    expires_at: str
    expires_in_seconds: int
    message: str

class ValidateResponse(BaseModel):
    valid: bool
    expires_in_seconds: Optional[int] = None
    expires_at: Optional[str] = None

class LogoutResponse(BaseModel):
    success: bool
    message: str

def get_token_from_header(authorization: Optional[str] = Header(None)) -> str:
    """
    Extract Bearer token from Authorization header

    Args:
        authorization: Authorization header value

    Returns:
        Token string

    Raises:
        HTTPException: If token is missing or invalid format
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    return parts[1]

def get_token_from_cookie_or_header(
    admin_session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
) -> str:
    """
    Extract token from HttpOnly cookie or Authorization header

    Priority:
    1. HttpOnly cookie (preferred for browser requests)
    2. Authorization header (for API clients)

    Args:
        admin_session_token: Token from HttpOnly cookie
        authorization: Authorization header value

    Returns:
        Token string

    Raises:
        HTTPException: If token is missing from both sources
    """
    # Try cookie first (preferred for browser requests)
    if admin_session_token:
        return admin_session_token

    # Fall back to Authorization header
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]

    raise HTTPException(
        status_code=401,
        detail="Unauthorized: Missing authentication token"
    )


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Pull the token out of an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def resolve_admin_identity(
    request: Request,
    admin_session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    """
    Resolve the authenticated admin identity for this request.

    Checked in order:
      1. Cloudflare Access — a fully verified CF Access JWT (see
         app.services.cf_access_service) counts as an authenticated admin.
         This never raises on failure, so it's safe to check first.
      2. The existing passcode session — HttpOnly cookie, then Bearer
         header — unchanged fallback behavior.

    Returns an opaque identity string on success (a ``cf-access:<email>``
    marker or the passcode session token), or None if neither path
    authenticates the request.
    """
    cf_email = get_cf_access_email(request)
    if cf_email:
        return f"cf-access:{cf_email}"

    token = admin_session_token or _extract_bearer_token(authorization)
    if token and admin_auth_service.validate_session(token):
        return token

    return None

@router.post("/login")
async def admin_login(login_payload: LoginRequest, request: Request):
    """
    Authenticate admin user with passcode

    Returns session token valid for 1 hour and sets HttpOnly cookie.
    Rate-limited per source IP (5 failures / 15 minutes triggers a 15-minute lockout).
    """
    client_ip = _get_client_ip(request)

    # Enforce lockout BEFORE attempting verification (avoids timing leakage of valid passcodes)
    _check_lockout(client_ip)

    try:
        # Verify passcode
        if not admin_auth_service.verify_passcode(login_payload.passcode):
            _record_failed_attempt(client_ip)
            logger.warning(f"Failed login attempt from {client_ip}")
            raise HTTPException(
                status_code=401,
                detail="รหัสผ่านไม่ถูกต้อง"
            )

        # Successful login: clear failure history for this IP
        _clear_failed_attempts(client_ip)

        # Create session
        token = admin_auth_service.create_session()
        session_info = admin_auth_service.get_session_info(token)

        logger.info("Admin login successful")

        # Create JSON response
        response = JSONResponse(content={
            "success": True,
            "token": token,
            "expires_at": session_info['expires_at'],
            "expires_in_seconds": session_info['expires_in_seconds'],
            "message": "เข้าสู่ระบบสำเร็จ"
        })

        # Set HttpOnly cookie for server-side authentication
        # Secure flag is enabled when running behind HTTPS proxy (Cloudflare/nginx).
        # SameSite=Strict aligns with PLAN.md §11.
        response.set_cookie(
            key="admin_session_token",
            value=token,
            httponly=True,  # Prevent JavaScript access
            max_age=3600,  # 1 hour in seconds
            samesite="strict",  # CSRF protection
            secure=_is_behind_proxy()
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=500,
            detail="เกิดข้อผิดพลาดในการเข้าสู่ระบบ"
        )

@router.get("/validate", response_model=ValidateResponse)
async def validate_session(
    request: Request,
    admin_session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
):
    """
    Validate admin session token

    Recognizes a verified Cloudflare Access identity first — so
    admin-login.html auto-skips the passcode prompt for admins already
    authenticated via CF Access — then falls back to validating the
    existing passcode session (unchanged behavior).
    """
    try:
        if get_cf_access_email(request):
            return ValidateResponse(valid=True)

        token = admin_session_token or _extract_bearer_token(authorization)
        if not token:
            return ValidateResponse(valid=False)

        # Clean up expired sessions periodically
        admin_auth_service.cleanup_expired_sessions()

        # Validate token
        if not admin_auth_service.validate_session(token):
            return ValidateResponse(valid=False)

        # Get session info
        session_info = admin_auth_service.get_session_info(token)

        return ValidateResponse(
            valid=True,
            expires_in_seconds=session_info['expires_in_seconds'],
            expires_at=session_info['expires_at']
        )

    except Exception as e:
        logger.error(f"Session validation error: {e}")
        return ValidateResponse(valid=False)

@router.post("/logout")
async def admin_logout(token: str = Depends(get_token_from_cookie_or_header)):
    """
    Logout admin user and revoke session
    """
    try:
        admin_auth_service.revoke_session(token)
        logger.info("Admin logout successful")

        # Create JSON response
        response = JSONResponse(content={
            "success": True,
            "message": "ออกจากระบบสำเร็จ"
        })

        # Clear the HttpOnly cookie. Attributes must match the original
        # set_cookie call (path/samesite/secure/httponly) so browsers will
        # actually delete the cookie under SameSite=Strict.
        response.delete_cookie(
            key="admin_session_token",
            path="/",
            samesite="strict",
            secure=_is_behind_proxy(),
            httponly=True,
        )

        return response

    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(
            status_code=500,
            detail="เกิดข้อผิดพลาดในการออกจากระบบ"
        )

@router.get("/session-info")
async def get_session_info(token: str = Depends(get_token_from_cookie_or_header)):
    """
    Get current session information
    """
    try:
        if not admin_auth_service.validate_session(token):
            raise HTTPException(status_code=401, detail="Session expired or invalid")

        session_info = admin_auth_service.get_session_info(token)

        return {
            "success": True,
            "session": session_info
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get session info error: {e}")
        raise HTTPException(
            status_code=500,
            detail="เกิดข้อผิดพลาดในการดึงข้อมูล session"
        )

# Dependency for protected routes
async def require_admin_auth(
    request: Request,
    admin_session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> str:
    """
    Dependency to require valid admin authentication.

    Checks Cloudflare Access first (see resolve_admin_identity) — this is
    intentionally NOT built on top of get_token_from_cookie_or_header,
    which raises immediately when no cookie/header is present. That hard
    fail would short-circuit before the CF Access check ever ran, which
    would break auto-login for CF-authenticated admins who don't have a
    passcode session cookie.

    Accepts token from HttpOnly cookie or Authorization header as the
    fallback, unchanged from prior behavior.

    Returns:
        Opaque identity string: a verified CF Access email marker, or the
        passcode session token.

    Raises:
        HTTPException: If authentication fails via both paths
    """
    identity = resolve_admin_identity(request, admin_session_token, authorization)
    if identity is None:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Session expired or invalid"
        )
    return identity
