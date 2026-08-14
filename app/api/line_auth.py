"""
LINE Authentication API

Endpoints for LINE OAuth integration with QR check-in:
- Initiate LINE OAuth login flow
- Handle LINE OAuth callback
- Link LINE account with employee using 6-digit code
- Verify JWT tokens
- Unlink LINE accounts (admin only)

Mobile Safari compatible with HTML meta refresh redirects.
"""

import logging
import os
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, status, Query, Request, Depends, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models.models import Employee
from app.services.line_auth_service import is_line_in_app_browser, line_auth_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Link-account brute-force protection
# ============================================================================
#
# In-memory tracking of failed link-account attempts. Two layers:
#   1) Per-(IP, line_user_id) sliding window: 5 attempts/minute, 5-minute lockout
#      after 20 failed attempts.
#   2) Per-linking-code: after 5 wrong attempts on the same code, the code is
#      invalidated (set to NULL on the employee record). Admin must regenerate.
#
# Pure in-process protection — sufficient for the single-instance deployment
# documented in CLAUDE.md / PLAN.md.

_LINK_ATTEMPT_WINDOW_SECONDS = 60
_LINK_ATTEMPT_MAX_PER_WINDOW = 5
_LINK_ATTEMPT_LOCKOUT_THRESHOLD = 20
_LINK_ATTEMPT_LOCKOUT_SECONDS = 300  # 5 minutes
_LINK_ATTEMPT_RETENTION_SECONDS = 300  # prune older entries
_LINK_CODE_INVALIDATE_THRESHOLD = 5
_LINK_CODE_FAILURE_TTL_SECONDS = 3600  # drop inactive code-failure counters after 1h

# (ip, line_user_id) -> list[timestamps of failed attempts]
_link_attempts: Dict[Tuple[str, str], List[float]] = {}
# (ip, line_user_id) -> lockout_until timestamp
_link_lockouts: Dict[Tuple[str, str], float] = {}
# linking_code -> {"count": int, "last_updated": float}
_link_code_failures: Dict[str, Dict[str, float]] = {}
_link_attempts_lock = threading.Lock()


def _prune_link_rate_limit_state(now: float) -> None:
    """
    Drop dead entries from all three rate-limit dicts.

    Must be called under ``_link_attempts_lock``. This is a safety pruner to
    bound memory growth: it only removes entries that are no longer relevant
    (lockouts past, no recent attempts, code failure counters that haven't been
    touched in an hour). It does not over-prune active counters.
    """
    # Drop expired lockouts.
    expired_lockouts = [
        key for key, lockout_until in _link_lockouts.items()
        if lockout_until <= now
    ]
    for key in expired_lockouts:
        _link_lockouts.pop(key, None)

    # Drop attempt history with no in-window timestamps. We use the retention
    # window so we don't kill counters during an active sliding-window attack.
    cutoff = now - _LINK_ATTEMPT_RETENTION_SECONDS
    empty_attempt_keys = []
    for key, timestamps in _link_attempts.items():
        if not timestamps or all(ts <= cutoff for ts in timestamps):
            empty_attempt_keys.append(key)
    for key in empty_attempt_keys:
        _link_attempts.pop(key, None)

    # Drop code-failure entries that have not been touched in an hour.
    code_cutoff = now - _LINK_CODE_FAILURE_TTL_SECONDS
    stale_codes = [
        code for code, info in _link_code_failures.items()
        if info.get("last_updated", 0) <= code_cutoff
    ]
    for code in stale_codes:
        _link_code_failures.pop(code, None)


def _client_ip(request: Request) -> str:
    """
    Resolve the client IP when behind a trusted proxy.

    Trust order when ``BEHIND_PROXY=true``:
      1. ``CF-Connecting-IP`` — Cloudflare overwrites this per-request, so it
         cannot be spoofed by an attacker upstream of Cloudflare.
      2. First hop of ``X-Forwarded-For`` — only used when CF header is absent
         (assumes the proxy contract overwrites or trims XFF). Documented in
         CLAUDE.md / PLAN.md §1.
      3. ``request.client.host`` — direct-connection fallback.
    """
    if os.getenv("BEHIND_PROXY", "false").lower() == "true":
        cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
        if cf_ip:
            return cf_ip
        forwarded = request.headers.get("X-Forwarded-For", "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_link_rate_limit(ip: str, line_user_id: str) -> None:
    """
    Enforce per-(IP, line_user_id) brute-force protection.
    Raises HTTPException(429) when the limit is exceeded.
    """
    key = (ip, line_user_id)
    now = time.time()

    with _link_attempts_lock:
        # Drop dead entries across all three dicts to bound memory growth
        # from inactive attackers rotating IP/LINE-user/code keys.
        _prune_link_rate_limit_state(now)

        # Lockout check
        lockout_until = _link_lockouts.get(key)
        if lockout_until and now < lockout_until:
            retry_after = int(lockout_until - now) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="พยายามเชื่อมต่อบัญชีเกินกำหนด กรุณาลองใหม่ภายหลัง",
                headers={"Retry-After": str(retry_after)},
            )
        if lockout_until and now >= lockout_until:
            _link_lockouts.pop(key, None)

        # Read existing attempt history without creating an empty entry on
        # first access (otherwise dict grows unboundedly for one-shot probes).
        timestamps = _link_attempts.get(key)
        if timestamps is None:
            return

        # Prune attempt history older than the retention window.
        cutoff = now - _LINK_ATTEMPT_RETENTION_SECONDS
        timestamps = [t for t in timestamps if t > cutoff]
        if timestamps:
            _link_attempts[key] = timestamps
        else:
            _link_attempts.pop(key, None)
            return

        # Attempts within the sliding window
        window_cutoff = now - _LINK_ATTEMPT_WINDOW_SECONDS
        in_window = [t for t in timestamps if t > window_cutoff]
        if len(in_window) >= _LINK_ATTEMPT_MAX_PER_WINDOW:
            retry_after = int(_LINK_ATTEMPT_WINDOW_SECONDS - (now - in_window[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="พยายามเชื่อมต่อบัญชีเกินกำหนด กรุณาลองใหม่ภายหลัง",
                headers={"Retry-After": str(max(1, retry_after))},
            )


def _record_link_failure(ip: str, line_user_id: str) -> None:
    """Track a failed link attempt and apply lockout when threshold is reached."""
    key = (ip, line_user_id)
    now = time.time()
    with _link_attempts_lock:
        timestamps = _link_attempts.get(key, [])
        timestamps.append(now)
        # Prune older entries
        cutoff = now - _LINK_ATTEMPT_RETENTION_SECONDS
        timestamps = [t for t in timestamps if t > cutoff]
        _link_attempts[key] = timestamps

        if len(timestamps) >= _LINK_ATTEMPT_LOCKOUT_THRESHOLD:
            _link_lockouts[key] = now + _LINK_ATTEMPT_LOCKOUT_SECONDS


def _clear_link_failures(ip: str, line_user_id: str) -> None:
    """Clear failure tracking for a successful (ip, line_user_id) link."""
    key = (ip, line_user_id)
    with _link_attempts_lock:
        _link_attempts.pop(key, None)
        _link_lockouts.pop(key, None)


def _record_code_failure(linking_code: str) -> int:
    """Increment failure count for a specific linking code; return new total."""
    now = time.time()
    with _link_attempts_lock:
        info = _link_code_failures.get(linking_code) or {"count": 0}
        new_count = int(info.get("count", 0)) + 1
        _link_code_failures[linking_code] = {
            "count": new_count,
            "last_updated": now,
        }
        return new_count


def _clear_code_failures(linking_code: str) -> None:
    with _link_attempts_lock:
        _link_code_failures.pop(linking_code, None)


# ============================================================================
# Request/Response Models
# ============================================================================

class LinkAccountRequest(BaseModel):
    """Request to link LINE account with employee"""
    # 6-digit numeric code (per PLAN.md §2.2). Strict length bounds also keep
    # the per-code failure dict from being grown by oversized payloads.
    linking_code: str = Field(..., min_length=6, max_length=6)
    jwt_token: str


class UnlinkAccountRequest(BaseModel):
    """
    Request body for self-unlink of LINE account.

    The authenticated LINE user (identified via the Authorization Bearer JWT)
    can only unlink their OWN linked employee account. Administrative unlink
    of other users is performed via /api/private/admin/line-codes/unlink.
    """
    reason: Optional[str] = None


class VerifyTokenRequest(BaseModel):
    """Request to verify JWT token"""
    token: str


# ============================================================================
# OAuth Flow Endpoints
# ============================================================================

def _escape_attribute(value: str) -> str:
    """Escape an app-built URL for interpolation into an HTML attribute."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _line_app_guidance_page(auth_url: str) -> HTMLResponse:
    """The interstitial for the password-less mobile dead end.

    Rendered INSTEAD of the usual auto-redirect on one narrow combination
    (Cloudflare Access flow + mobile + non-LINE browser); see the long comment
    at the call site in :func:`line_login` for why that combination has no
    working LINE login screen and why no OAuth parameter can fix it.

    Deliberately NOT an error page: it explains the way through (open the tool
    from the LINE app, where auto login works) and still offers the LINE login
    for the office staff and managers who do hold a LINE email/password. The
    ``auth_url`` handed to the button is the identical URL the auto-redirect
    would have used — this page changes what the user is told, never what is
    requested from LINE.
    """
    safe_auth_url = _escape_attribute(auth_url)
    html_content = f"""<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>เข้าสู่ระบบด้วย LINE</title>
    <style>
        body {{
            font-family: 'Sarabun', 'Prompt', sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0; background: #f5f5f5; color: #333;
        }}
        .card {{
            background: #fff; padding: 32px; border-radius: 12px;
            box-shadow: 0 2px 16px rgba(0,0,0,0.08);
            max-width: 420px; margin: 16px;
        }}
        h1 {{ font-size: 20px; margin: 0 0 12px; color: #6b1f2a; text-align: center; }}
        p {{ color: #555; line-height: 1.7; margin: 0 0 16px; }}
        .steps {{ color: #555; line-height: 1.7; margin: 0 0 20px; padding-left: 20px; }}
        .secondary {{
            display: block; text-align: center; padding: 14px 24px;
            background: #06C755; color: #fff; text-decoration: none;
            border-radius: 8px; font-size: 15px; font-weight: 600;
        }}
        .note {{ font-size: 13px; color: #7A7268; margin: 16px 0 0; text-align: center; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>กรุณาเปิดจากแอป LINE</h1>
        <p>
            บัญชี LINE ของพนักงานส่วนใหญ่ไม่ได้ตั้งอีเมลและรหัสผ่านไว้
            หากเปิดลิงก์นี้จากเบราว์เซอร์บนมือถือ หน้าเข้าสู่ระบบของ LINE
            จะขอ<strong>อีเมลและรหัสผ่าน</strong> ซึ่งจะไปต่อไม่ได้
        </p>
        <ol class="steps">
            <li>เปิดแอป LINE</li>
            <li>เข้าห้องแชทของโรงแรม แล้วกดเมนูด้านล่าง (ริชเมนู)</li>
            <li>เข้าสู่ระบบจากตรงนั้นได้เลย ไม่ต้องใช้รหัสผ่าน</li>
        </ol>
        <a class="secondary" href="{safe_auth_url}">
            ฉันมีอีเมลและรหัสผ่าน LINE — เข้าสู่ระบบต่อ
        </a>
        <p class="note">
            Open this tool from the LINE app menu. The button above only works
            if your LINE account has an email and password set.
        </p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@router.get("/login")
async def line_login(
    request: Request,
    redirect: Optional[str] = Query(None),
    qr_context: Optional[str] = Query(None)
):
    """
    Initiate LINE OAuth login flow

    Query Parameters:
        redirect: Optional redirect destination after OAuth (e.g., 'qr-scan-callback', 'mobile-checkin')
        qr_context: Optional QR scan context (JSON-encoded token and terminal info) for cross-browser preservation

    Returns:
        HTML response with meta refresh redirect for Mobile Safari compatibility.

        One exception: on the Cloudflare Access flow from a mobile NON-LINE
        browser the response is a guidance interstitial instead of an
        auto-redirect, because LINE has no login screen a password-less staff
        account can complete there. See the block comment below.
    """
    try:
        # Build redirect hint that includes both redirect page and qr_context
        # Format: "qr-scan-callback|{qr_context}" or just "mobile-checkin"
        redirect_hint = redirect
        if qr_context and redirect:
            redirect_hint = f"{redirect}|{qr_context}"

        # QR login is a desktop affordance: the code is scanned with the phone.
        # On a phone it would be a code the user cannot scan from their own
        # screen, so mobile keeps LINE's normal in-browser form.
        user_agent = request.headers.get("user-agent") or ""
        is_mobile = any(
            token in user_agent.lower()
            for token in ("iphone", "ipad", "ipod", "android", "mobile")
        )

        # Store redirect parameter in state for callback
        auth_data = line_auth_service.generate_authorization_url(
            redirect_hint=redirect_hint,
            prefer_qr=not is_mobile,
            # Pass the header verbatim, NOT the lowercased copy used for the
            # mobile sniff above: the service looks for the `Line/<version>`
            # product token to tell LINE's own in-app browser (where the
            # login form is a dead end for password-less staff accounts)
            # from an external one (where auto login strands the Access
            # session). Case and delimiters both matter to that match.
            user_agent=user_agent,
        )
        auth_url = auth_data["auth_url"]

        # ------------------------------------------------------------------
        # The password-less mobile dead end (Cloudflare Access / "oidc:" flow
        # only, external browser only).
        #
        # Three facts collide on exactly one combination:
        #   1. Staff LINE accounts are created on a phone from the LINE app.
        #      They typically have NO email and NO password set.
        #   2. On the Access flow in an external browser we must send
        #      disable_auto_login (line_auth_service.generate_authorization_url
        #      explains why: without it iOS app-switches to LINE, the callback
        #      completes in LINE's in-app browser — a different cookie jar —
        #      and the Access session started in Safari is stranded on
        #      "Invalid session"). Disabling auto login makes LINE render its
        #      email/password web FORM.
        #   3. initial_amr_display=lineqr, the desktop escape from that form,
        #      is useless on a phone: it shows a QR the user is being asked to
        #      scan with the very device displaying it.
        # So a password-less employee who reaches a gated app from Safari or
        # Chrome on their phone — a scanned QR, a link opened outside LINE,
        # a bookmark — lands on a form they cannot complete and has no way
        # forward. Nothing on the LINE side of that page can help them.
        #
        # What this page does about it: it does NOT change a single OAuth
        # parameter. Both of the obvious parameter fixes make things worse —
        # dropping disable_auto_login hands back the Safari cookie-jar bug for
        # everyone on this path, and forcing lineqr on mobile replaces an
        # unusable form with an unusable QR. Instead the user is TOLD, before
        # LINE ever renders, that the way through is to open the tool from the
        # LINE app's rich menu, which is their primary path anyway and where
        # auto login works (fact 2 does not apply inside LINE's own browser).
        #
        # It stays an interstitial rather than a hard block because the same
        # combination is also hit by office staff and managers who DO have a
        # LINE email/password; for them the form works fine and one tap on
        # "continue" is the whole cost. Blocking them to help the maids would
        # trade one dead end for another.
        #
        # Scope is deliberately narrow — Access flow, mobile UA, non-LINE
        # browser. The desktop path (QR, works), the rich-menu-inside-LINE path
        # (auto login, works), and every public-path flow (QR clock-in, mobile
        # check-in, onboarding, kiosk elevate — all keep auto login and work)
        # are untouched and still auto-redirect exactly as before.
        #
        # THE REAL FIX, for whoever picks this up: a same-browser completion
        # hand-off, i.e. keep auto login ON for mobile, let LINE finish in its
        # in-app browser, and have the ORIGINAL browser tab poll a server-side
        # ticket until the LINE side resolves, then finish the Access redirect
        # in the tab that holds the Access session. That removes the cookie-jar
        # problem instead of routing around it, and this repo already runs that
        # exact pattern for the kiosk (reader.py /elevate/start + /elevate/wait
        # long-poll, resolved by continue_elevate_after_line). The cost is a
        # new stateful flow on the login path — a ticket store, a polling page,
        # a timeout/abandonment story, and a careful look at what an attacker
        # can do by polling someone else's ticket — which is why it is a piece
        # of work rather than a line of code, and why the guidance page is the
        # interim.
        # ------------------------------------------------------------------
        #
        # The check runs AFTER generate_authorization_url so the button below
        # carries a live, state-backed URL. A user who takes the LINE-app route
        # instead simply leaves that CSRF state unused, and it is pruned by the
        # existing 10-minute TTL sweep.
        if (
            (redirect_hint or "").startswith("oidc:")
            and is_mobile
            and not is_line_in_app_browser(user_agent)
        ):
            return _line_app_guidance_page(auth_url)

        # Mobile Safari compatible redirect using HTML meta refresh
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta http-equiv="refresh" content="0; url={auth_url}">
            <title>เข้าสู่ระบบด้วย LINE</title>
            <style>
                body {{
                    font-family: 'Prompt', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #06C755 0%, #00B900 100%);
                }}
                .loading {{
                    text-align: center;
                    color: white;
                }}
                .spinner {{
                    border: 4px solid rgba(255, 255, 255, 0.3);
                    border-radius: 50%;
                    border-top: 4px solid white;
                    width: 40px;
                    height: 40px;
                    animation: spin 1s linear infinite;
                    margin: 0 auto 20px;
                }}
                @keyframes spin {{
                    0% {{ transform: rotate(0deg); }}
                    100% {{ transform: rotate(360deg); }}
                }}
            </style>
        </head>
        <body>
            <div class="loading">
                <div class="spinner"></div>
                <h2>กำลังเชื่อมต่อ LINE...</h2>
                <p>หากไม่ถูกเปลี่ยนเส้นทางอัตโนมัติ <a href="{auth_url}" style="color: white;">คลิกที่นี่</a></p>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate LINE login: {str(e)}"
        )


@router.get("/callback")
async def line_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    redirect: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Handle LINE OAuth callback

    Query Parameters:
        code: Authorization code from LINE
        state: CSRF state token
        error: Error code if authentication failed
        error_description: Error description if authentication failed
        redirect: Optional redirect destination (e.g., 'qr-scan-callback')

    Returns:
        HTML response redirecting to link account page or specified redirect with LINE profile data
    """
    # Handle OAuth errors
    if error:
        error_msg = error_description or error
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>การเข้าสู่ระบบล้มเหลว</title>
            <style>
                body {{
                    font-family: 'Prompt', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: #f5f5f5;
                }}
                .error-box {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    text-align: center;
                    max-width: 400px;
                }}
                .error-icon {{
                    font-size: 48px;
                    color: #dc3545;
                    margin-bottom: 20px;
                }}
                h2 {{
                    color: #333;
                    margin-bottom: 10px;
                }}
                p {{
                    color: #666;
                    margin-bottom: 20px;
                }}
                a {{
                    display: inline-block;
                    padding: 10px 20px;
                    background: #06C755;
                    color: white;
                    text-decoration: none;
                    border-radius: 4px;
                }}
            </style>
        </head>
        <body>
            <div class="error-box">
                <div class="error-icon">❌</div>
                <h2>การเข้าสู่ระบบล้มเหลว</h2>
                <p>{error_msg}</p>
                <a href="/qr-checkin/mobile">ลองอีกครั้ง</a>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content, status_code=400)

    # Validate required parameters
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter"
        )

    try:
        # Validate CSRF state token and retrieve redirect hint
        is_valid, stored_redirect_hint = line_auth_service.validate_state(state)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state token"
            )

        # Parse redirect_hint to extract redirect page and qr_context
        # Format: "qr-scan-callback|{qr_context}" or just "mobile-checkin"
        qr_context = None
        if stored_redirect_hint and '|' in stored_redirect_hint:
            parts = stored_redirect_hint.split('|', 1)
            redirect = parts[0]
            qr_context = parts[1]
        else:
            redirect = stored_redirect_hint or redirect

        # Both LINE round-trips below are BLOCKING `requests` calls with a
        # 10-second timeout each (line_auth_service.exchange_code_for_token /
        # get_user_profile). This handler is `async def`, so calling them
        # directly parks the single uvicorn event loop for up to ~20s per
        # callback — and while it is parked NOTHING else in the process runs:
        # not /oidc/token, not /oidc/jwks (Cloudflare Access fetches both
        # synchronously, with its own timeout), not the kiosk /wait and
        # /elevate/wait long-polls, not the QR check-in APIs. One slow LINE
        # response therefore reads as an estate-wide stall.
        #
        # run_in_threadpool moves them onto Starlette's worker threads, which
        # is where a sync def handler's body would have run anyway. Nothing
        # about the calls themselves changes — same functions, same arguments,
        # same timeouts, and HTTPException raised inside the thread still
        # propagates to the `except HTTPException` below unchanged. The
        # awaits keep this handler async so the two continuations further down
        # (OIDC / kiosk elevate) stay ordinary in-loop calls.
        #
        # Kept as an async handler rather than converted to `def` on purpose:
        # `def` would move the ENTIRE body — including the SQLAlchemy session
        # from Depends(get_db) and both continuations — onto a worker thread,
        # a far larger behavioural change than this bug warrants.
        token_data = await run_in_threadpool(
            line_auth_service.exchange_code_for_token, code
        )
        access_token = token_data["access_token"]

        # Get LINE user profile
        profile = await run_in_threadpool(
            line_auth_service.get_user_profile, access_token
        )

        # Extract profile data
        line_user_id = profile.get("userId", "")
        display_name = profile.get("displayName", "ผู้ใช้ LINE")
        picture_url = profile.get("pictureUrl", "")

        # HF ID (OIDC) continuation — additive hook. When this LINE login was
        # initiated by /oidc/authorize, the redirect hint carries an OIDC login
        # ticket ("oidc:<ticket>"). Hand control to the HF ID provider to
        # resolve the employee identity and mint an authorization code. This
        # does not alter any existing QR/guest redirect behaviour — no existing
        # redirect hint uses the "oidc:" prefix.
        if redirect and redirect.startswith("oidc:"):
            from app.api.oidc import continue_oidc_after_line

            return continue_oidc_after_line(
                ticket_id=redirect[len("oidc:"):],
                line_user_id=line_user_id,
                db=db,
                # Forwarded so an unregistered LINE user's onboarding hand-off
                # carries the same prefilled profile the normal path gives it.
                display_name=display_name,
                picture_url=picture_url,
            )

        # Kiosk LINE-scan elevation continuation — additive hook, the exact
        # shape of the "oidc:" continuation above. When this LINE login was
        # initiated from a kiosk elevate QR (GET /api/public/reader/elevate/
        # {ticket}), the redirect hint carries the elevate ticket
        # ("elevate:<ticket>"). Hand control to the reader module to check the
        # employee's grants and park a one-time card assertion for the kiosk
        # backend's /elevate/wait long-poll. This does not alter any existing
        # QR/guest redirect behaviour — no existing redirect hint uses the
        # "elevate:" prefix.
        if redirect and redirect.startswith("elevate:"):
            from app.api.reader import continue_elevate_after_line

            return continue_elevate_after_line(
                ticket_id=redirect[len("elevate:"):],
                line_user_id=line_user_id,
                db=db,
                # Same reason as the OIDC continuation above.
                display_name=display_name,
                picture_url=picture_url,
            )

        # Check if this LINE user is already linked to an employee
        existing_employee = db.query(Employee).filter(
            Employee.line_user_id == line_user_id
        ).first()

        # Create JWT token with employee_badge if already linked
        if existing_employee:
            jwt_token = line_auth_service.create_jwt_token(
                line_user_id=line_user_id,
                employee_badge=existing_employee.badge_number,
                display_name=display_name,
                picture_url=picture_url
            )
            # Already linked - redirect to specified callback or default mobile check-in
            if redirect == 'qr-scan-callback':
                # Include qr_context if present for cross-browser QR scan flow
                # qr_context is already URL-encoded from login endpoint, keep it encoded
                qr_context_param = f"&qr_context={qr_context}" if qr_context else ""
                redirect_url = f"/qr-checkin/scan-callback?jwt={jwt_token}{qr_context_param}"
            else:
                redirect_url = f"/qr-checkin/mobile?jwt={jwt_token}"
        elif redirect == 'onboard':
            # Not yet linked, arriving from the self-service onboarding page
            # (/qr-checkin/onboard) — send them straight back there instead
            # of the admin-code link-account page; a brand-new self-onboarder
            # has no 6-digit admin code to enter.
            #
            # Built by the shared helper so this path carries the ``src=line``
            # marker too. It has always attached a jwt, so the marker changes
            # nothing here today — but onboard.html's stale-token refusal keys
            # off "did this arrival come from a LINE continuation", and that
            # question has to be answerable on EVERY continuation, not only the
            # ones we currently expect to need it.
            redirect_url = (
                "/qr-checkin/onboard?"
                + line_auth_service.onboarding_continuation_query(
                    line_user_id,
                    display_name=display_name,
                    picture_url=picture_url,
                )
            )
        else:
            # Not yet linked - redirect to link account page with redirect hint and qr_context
            jwt_token = line_auth_service.create_jwt_token(
                line_user_id=line_user_id,
                employee_badge=None,
                display_name=display_name,
                picture_url=picture_url
            )
            redirect_param = (
                f"&redirect={urllib.parse.quote(redirect or '', safe='')}"
                if redirect else ""
            )
            # qr_context is already URL-encoded from login endpoint, keep it encoded
            qr_context_param = f"&qr_context={qr_context}" if qr_context else ""
            # URL-encode LINE-supplied profile values to prevent unsafe characters
            # (spaces, &, =, #, Unicode) from breaking the redirect URL.
            encoded_line_user_id = urllib.parse.quote(line_user_id or "", safe="")
            encoded_display_name = urllib.parse.quote(display_name or "", safe="")
            encoded_picture_url = urllib.parse.quote(picture_url or "", safe="")
            redirect_url = (
                f"/qr-checkin/link-account"
                f"?jwt={jwt_token}"
                f"&line_user_id={encoded_line_user_id}"
                f"&display_name={encoded_display_name}"
                f"&picture_url={encoded_picture_url}"
                f"{redirect_param}"
                f"{qr_context_param}"
            )

        link_url = redirect_url

        # Use JavaScript redirect instead of meta refresh to properly handle URL encoding
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>เข้าสู่ระบบสำเร็จ</title>
            <style>
                body {{
                    font-family: 'Prompt', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #06C755 0%, #00B900 100%);
                }}
                .loading {{
                    text-align: center;
                    color: white;
                }}
                .spinner {{
                    border: 4px solid rgba(255, 255, 255, 0.3);
                    border-radius: 50%;
                    border-top: 4px solid white;
                    width: 40px;
                    height: 40px;
                    animation: spin 1s linear infinite;
                    margin: 0 auto 20px;
                }}
                @keyframes spin {{
                    0% {{ transform: rotate(0deg); }}
                    100% {{ transform: rotate(360deg); }}
                }}
            </style>
            <script>
                // Use JavaScript redirect to properly handle URL encoding
                window.location.href = {repr(link_url)};
            </script>
        </head>
        <body>
            <div class="loading">
                <div class="spinner"></div>
                <h2>เข้าสู่ระบบสำเร็จ!</h2>
                <p>กำลังเชื่อมต่อบัญชี...</p>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth callback failed: {str(e)}"
        )


# ============================================================================
# Account Linking Endpoints
# ============================================================================

@router.post("/link-account")
async def link_account(
    request: LinkAccountRequest,
    http_request: Request,
    db: Session = Depends(get_db)
):
    """
    Link LINE account with employee using 6-digit code

    Request Body:
        linking_code: 6-digit code from admin
        jwt_token: JWT token containing LINE user ID

    Returns:
        Success message with new JWT token for authenticated session

    Raises:
        400: Invalid linking code or already linked
        401: Invalid JWT token
        404: Employee not found
        429: Too many failed attempts (per-IP+LINE-user rate limit)
    """
    try:
        # Verify JWT token to get LINE user data
        token_payload = line_auth_service.verify_jwt_token(request.jwt_token)
        line_user_id = token_payload.get("line_user_id")
        line_display_name = token_payload.get("display_name")
        line_picture_url = token_payload.get("picture_url")

        if not line_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing LINE user ID"
            )

        # Brute-force protection: enforce per-(IP, LINE user) rate limit BEFORE
        # touching the database. This raises 429 when over budget.
        client_ip = _client_ip(http_request)
        _enforce_link_rate_limit(client_ip, line_user_id)

        # Find employee by linking code
        employee = db.query(Employee).filter(
            Employee.line_linking_code == request.linking_code,
            Employee.is_active == True
        ).first()

        if not employee:
            # Wrong code: increment per-IP/user failure counter and per-code counter.
            _record_link_failure(client_ip, line_user_id)
            code_failures = _record_code_failure(request.linking_code)

            # Distributed-attack protection: if a SPECIFIC code accumulates too
            # many failed attempts (across any IPs), invalidate the code so the
            # admin must regenerate. We only invalidate codes that actually
            # exist on an employee record (the request body could be garbage).
            if code_failures >= _LINK_CODE_INVALIDATE_THRESHOLD:
                target_employee = db.query(Employee).filter(
                    Employee.line_linking_code == request.linking_code
                ).first()
                if target_employee:
                    target_employee.line_linking_code = None
                    target_employee.line_linking_code_generated_at = None
                    target_employee.updated_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.warning(
                        "Invalidated linking code after %d failed attempts for badge=%s",
                        code_failures,
                        target_employee.badge_number,
                    )
                _clear_code_failures(request.linking_code)

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสเชื่อมต่อไม่ถูกต้องหรือหมดอายุ"
            )

        # Check if linking code has expired (24 hours)
        if employee.line_linking_code_generated_at:
            # Ensure timezone-aware datetime for comparison
            generated_at = employee.line_linking_code_generated_at
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            expiry = generated_at + timedelta(hours=24)
            if now > expiry:
                _record_link_failure(client_ip, line_user_id)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="รหัสเชื่อมต่อหมดอายุแล้ว กรุณาติดต่อเจ้าหน้าที่"
                )

        # Check if employee already has LINE linked
        if employee.line_user_id:
            _record_link_failure(client_ip, line_user_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="บัญชีนี้เชื่อมต่อ LINE แล้ว"
            )

        # Link LINE account to employee
        employee.line_user_id = line_user_id
        employee.line_display_name = line_display_name
        employee.line_picture_url = line_picture_url
        employee.line_linking_code = None  # Clear code after successful link
        employee.line_linking_code_generated_at = None
        employee.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(employee)

        # Successful link: clear failure counters for this client and the code.
        _clear_link_failures(client_ip, line_user_id)
        _clear_code_failures(request.linking_code)

        # Create new JWT token with employee badge for authenticated session
        new_token = line_auth_service.create_jwt_token(
            line_user_id=line_user_id,
            employee_badge=employee.badge_number,
            display_name=line_display_name,
            picture_url=line_picture_url
        )

        return {
            "success": True,
            "message": "เชื่อมต่อบัญชีสำเร็จ",
            "employee": {
                "badge_number": employee.badge_number,
                "display_name": employee.display_name,
                "line_user_id": employee.line_user_id
            },
            "token": new_token
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การเชื่อมต่อบัญชีล้มเหลว: {str(e)}"
        )


def _extract_bearer_token(authorization: Optional[str]) -> str:
    """Extract a bearer token from an Authorization header."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
        )
    return parts[1].strip()


@router.post("/unlink-account")
async def unlink_account(
    request: UnlinkAccountRequest,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Unlink the caller's own LINE account.

    Authentication:
        Authorization: Bearer <LINE-JWT>

    The LINE JWT identifies the caller's LINE user ID. The caller can only
    unlink the employee that their LINE account is currently linked to.
    Administrative unlink of arbitrary users is performed via
    /api/private/admin/line-codes/unlink (Cloudflare Access protected).

    Request Body:
        reason: Optional reason for unlinking

    Returns:
        Success message

    Raises:
        401: Missing/invalid LINE JWT
        404: No linked employee for this LINE user
    """
    token = _extract_bearer_token(authorization)
    payload = line_auth_service.verify_jwt_token(token)
    line_user_id = payload.get("line_user_id")
    if not line_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing LINE user ID",
        )

    try:
        # Find the employee currently linked to this LINE user.
        employee = db.query(Employee).filter(
            Employee.line_user_id == line_user_id,
            Employee.is_active == True
        ).first()

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบบัญชีที่เชื่อมต่อกับ LINE นี้"
            )

        # Unlink LINE account
        old_line_user_id = employee.line_user_id
        employee.line_user_id = None
        employee.line_display_name = None
        employee.line_picture_url = None
        employee.line_linking_code = None
        employee.line_linking_code_generated_at = None
        employee.updated_at = datetime.now(timezone.utc)

        db.commit()

        return {
            "success": True,
            "message": "ยกเลิกการเชื่อมต่อสำเร็จ",
            "badge_number": employee.badge_number,
            "old_line_user_id": old_line_user_id,
            "reason": request.reason
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การยกเลิกการเชื่อมต่อล้มเหลว: {str(e)}"
        )


@router.post("/verify-token")
async def verify_token(request: VerifyTokenRequest):
    """
    Verify JWT token

    Request Body:
        token: JWT token to verify

    Returns:
        Token validation with employee badge and LINE profile data

    Raises:
        401: Invalid or expired token
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[verify-token] Received request: {request}")
        logger.info(f"[verify-token] Token value: {request.token[:20] if request.token else 'None'}...")

        payload = line_auth_service.verify_jwt_token(request.token)

        # Return structure expected by mobile-checkin.js
        result = {
            "valid": True,
            "employee_badge": payload.get("employee_badge"),  # None if not linked
            "line_profile": {
                "user_id": payload.get("line_user_id"),
                "display_name": payload.get("display_name"),
                "picture_url": payload.get("picture_url")
            },
            "payload": payload  # Keep original payload for backward compatibility
        }
        logger.info(f"[verify-token] Returning: valid=True, employee_badge={result['employee_badge']}")
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"[verify-token] Unexpected error: {str(e)}")
        raise
