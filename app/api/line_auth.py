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

import asyncio
import json
import logging
import os
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import (
    APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status,
)
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.models.models import Employee
from app.services import line_handoff_store
from app.services.line_auth_service import is_line_in_app_browser, line_auth_service
from app.services.staff_oa_provision import provision_for_badge

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


# ============================================================================
# Same-browser completion hand-off
# ============================================================================
#
# THE PROBLEM, in one line: on the Cloudflare Access flow from a phone's
# non-LINE browser, the Access session lives in Safari and the LINE login can
# only complete in LINE's in-app browser, which is a different cookie jar. See
# the long block comment inside :func:`line_login` for why neither of the two
# obvious OAuth-parameter fixes can close that gap.
#
# THE FIX: stop trying to keep the LINE login in one browser. Let auto login
# do what it does — app-switch to LINE, finish there — and keep the ORIGINAL
# tab alive, polling a server-side ticket. When the LINE side resolves, the
# ORIGINAL tab (which holds the Access session) is the one that navigates to
# the Cloudflare Access callback. The cookie jar split stops mattering because
# nothing that matters crosses it any more.
#
# Shape copied from the kiosk elevation this repo already runs
# (app/api/reader.py: /elevate/start mints a ticket, /elevate/wait long-polls
# it, continue_elevate_after_line resolves it from the LINE callback). Same
# store conventions, same 25s/0.5s long-poll budget, same 204-and-re-poll
# contract, same deliver-once pop. Two stores, one pattern — do not invent a
# third.
#
# SECURITY. The whole design rests on one invariant:
#
#     completing a LINE login must only ever yield a session to the browser
#     that STARTED that specific flow.
#
# It is enforced by splitting the flow's two secrets across the two legs:
#
#   * the ticket id travels the LINE leg, but ONLY inside line_auth_service's
#     server-side state store (as the ``handoff:<id>`` redirect hint keyed by
#     LINE's random ``state``). It is never in a URL, a page, a Referer or a
#     log line.
#   * the holder secret never leaves the originating browser. It rides in an
#     HttpOnly, SameSite=Strict cookie set on the response below, and it is the
#     only thing that can release the finished login.
#
# The HttpOnly cookie is the right binder for exactly the reason the bug exists:
# LINE's in-app browser is a separate cookie jar, so the LINE leg structurally
# CANNOT present it, and script on the LINE-side page cannot read it out of
# ours to relay it. Possession of the cookie is therefore proof of "I am the
# tab that started this" — which is precisely the tab the Access redirect has
# to happen in.
#
# The full threat analysis (observe / guess / fixation / race), including the
# one property that is mitigated rather than closed, lives in the module
# docstring of app/services/line_handoff_store.py. Read it before changing the
# cookie attributes, the IP check, or the pop-under-lock in take_resolved.

# Where the polling page long-polls. Absolute because the page may be served
# under either the /api/public mount or the legacy /fingerprintlogs alias, and
# the wait endpoint only exists on the former. Same convention as reader.py's
# _LINE_LOGIN_PATH.
_HANDOFF_WAIT_PATH = "/api/public/auth/line/handoff/wait"

# The polling page itself. Kept as a real file under static/ rather than an
# f-string like the pages above it: it carries a state machine and a poll loop,
# and Thai copy aimed at 80+ year old housekeeping staff is edited far more
# often than the code around it.
_HANDOFF_PAGE_FILE = (
    Path(__file__).resolve().parents[2] / "static" / "line-handoff.html"
)
_HANDOFF_CONFIG_PLACEHOLDER = "__HANDOFF_CONFIG__"

# Read once and memoised: the page is a deploy-time asset, and re-reading it
# from disk on every login would put a blocking filesystem call on the single
# uvicorn event loop for no benefit. None means "not readable" — see
# :func:`_handoff_page`.
_handoff_template_cache: Optional[str] = None
_handoff_template_lock = threading.Lock()


def _is_behind_proxy() -> bool:
    """Whether the app runs behind a TLS-terminating proxy.

    Local copy of the same helper in app/api/admin_auth.py and
    app/main_unified.py (importing either from here would be a circular
    import). Drives the cookie ``Secure`` flag, exactly as it does for the
    admin session cookie.
    """
    return os.getenv("BEHIND_PROXY", "false").lower() == "true"


def _load_handoff_template() -> Optional[str]:
    """The polling page markup, or None when the asset is missing.

    A missing file is treated as "the hand-off is unavailable" rather than an
    error: the caller falls back to the guidance interstitial, so a deployment
    that somehow shipped without static/ degrades to today's behaviour instead
    of taking the login path down.
    """
    global _handoff_template_cache
    if _handoff_template_cache is not None:
        return _handoff_template_cache
    with _handoff_template_lock:
        if _handoff_template_cache is not None:
            return _handoff_template_cache
        try:
            _handoff_template_cache = _HANDOFF_PAGE_FILE.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error(
                "LINE hand-off page missing at %s (%s) — falling back to the "
                "guidance interstitial",
                _HANDOFF_PAGE_FILE,
                exc,
            )
            return None
        return _handoff_template_cache


def _handoff_page(
    *, auth_url: str, retry_url: str, cookie_value: str
) -> Optional[HTMLResponse]:
    """Render the polling page and attach the browser-binding cookie.

    ``auth_url`` is the ordinary LINE authorization URL — auto login ON, no
    ``initial_amr_display`` — that the page's single green button opens in a
    SECOND tab. It must be a second tab: navigating this one into LINE would
    destroy the tab that has to finish the Access redirect.

    ``retry_url`` is this same /login request, so the retry button restarts the
    whole hand-off cleanly (a fresh ticket, a fresh cookie) while reusing the
    still-valid inner OIDC login ticket underneath.

    Returns None when the page asset is unavailable, so the caller can fall
    back to the guidance interstitial.
    """
    template = _load_handoff_template()
    if template is None:
        return None

    config = {
        "authUrl": auth_url,
        "waitUrl": _HANDOFF_WAIT_PATH,
        "retryUrl": retry_url,
        # The page's own overall deadline. Kept slightly under the server-side
        # ticket TTL so the user sees the Thai retry panel rather than racing
        # the server into a 404 at the same instant.
        "budgetMs": int(max(1.0, line_handoff_store.ticket_ttl_seconds() - 5) * 1000),
    }
    # ``</script>`` inside a JSON string would end the block early. Every value
    # here is app-built, but escaping the three characters that can break out
    # costs nothing and removes the question entirely.
    serialized = (
        json.dumps(config, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    response = HTMLResponse(content=template.replace(
        _HANDOFF_CONFIG_PLACEHOLDER, serialized
    ))

    # The browser binding. Every attribute is load-bearing:
    #   httponly  — script cannot read it, so a hostile page (or the LINE-side
    #               page) cannot relay it to another browser.
    #   samesite  — Strict, matching the admin session cookie. The only request
    #               that must carry it is a same-origin fetch from this page.
    #   secure    — on behind the proxy, same rule as every other cookie here.
    #   path      — narrowed to the LINE auth surface; nothing else in the app
    #               has any business seeing it.
    #   max_age   — dies with the ticket, so an abandoned phone stops carrying
    #               a usable binder around.
    response.set_cookie(
        key=line_handoff_store.COOKIE_NAME,
        value=cookie_value,
        httponly=True,
        samesite="strict",
        secure=_is_behind_proxy(),
        path=line_handoff_store.COOKIE_PATH,
        max_age=int(line_handoff_store.ticket_ttl_seconds()),
    )
    # The ticket cookie must never be cached by a shared cache, and neither
    # must a page that is one tap away from a session.
    response.headers["Cache-Control"] = "no-store"
    return response


def _handoff_applies(
    *, redirect_hint: Optional[str], is_mobile: bool, user_agent: str
) -> bool:
    """Whether this /login call is the password-less mobile dead end.

    Deliberately the SAME three-part condition the guidance interstitial
    already uses — Access flow, mobile UA, non-LINE browser — so the hand-off
    replaces that page on exactly its scope and nothing else. The four working
    paths are untouched by construction:

      * rich menu inside LINE  -> is_line_in_app_browser is True
      * desktop                -> is_mobile is False
      * every public-path flow -> the hint does not start with "oidc:"
      * kiosk elevate          -> its hint is "elevate:", not "oidc:"

    Plus the feature gate, so the whole thing is one environment variable away
    from today's behaviour.

    The page asset is checked HERE, before a ticket exists and before the
    authorization URL is built, so an unrenderable hand-off never gets as far
    as changing which OAuth parameters are sent.
    """
    if not line_handoff_store.is_enabled():
        return False
    if not (redirect_hint or "").startswith("oidc:"):
        return False
    if not is_mobile or is_line_in_app_browser(user_agent):
        return False
    return _load_handoff_template() is not None


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
        browser the response is NOT an auto-redirect, because LINE has no login
        screen a password-less staff account can complete there. See the block
        comment below. That combination gets one of two pages:

        * the same-browser hand-off polling page, when
          ``LINE_SAME_BROWSER_HANDOFF`` is on — this tab keeps the Cloudflare
          Access session and waits for LINE to finish in its own browser;
        * the guidance interstitial otherwise, which is the interim and also
          the standing fallback (feature off, ticket store full, page asset
          missing).
    """
    try:
        # Build redirect hint that includes both redirect page and qr_context
        # Format: "qr-scan-callback|{qr_context}" or just "mobile-checkin"
        redirect_hint = redirect
        if qr_context and redirect:
            redirect_hint = f"{redirect}|{qr_context}"

        # A "handoff:" hint is ALWAYS synthesized below, never supplied by a
        # caller, so one arriving in the query string is forged by definition.
        #
        # Refused rather than ignored. Honouring it would let anyone aim a LINE
        # login at a hand-off ticket id of their choosing, and the LINE callback
        # would then park THEIR identity against SOMEONE ELSE'S waiting tab —
        # fixation run backwards, ending with a victim signed in as the
        # attacker. The IP binding and the 192-bit unguessable ticket id both
        # already stand in the way, but a request that has no legitimate form
        # should not be reaching those defences at all.
        #
        # Deliberately scoped to this one prefix: "oidc:" and "elevate:" hints
        # do legitimately arrive through the browser (our own /oidc/authorize
        # and kiosk QR redirects put them there), and they are guarded by their
        # own unguessable, single-use ticket ids.
        if (redirect_hint or "").startswith("handoff:"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid redirect hint",
            )

        # QR login is a desktop affordance: the code is scanned with the phone.
        # On a phone it would be a code the user cannot scan from their own
        # screen, so mobile keeps LINE's normal in-browser form.
        user_agent = request.headers.get("user-agent") or ""
        is_mobile = any(
            token in user_agent.lower()
            for token in ("iphone", "ipad", "ipod", "android", "mobile")
        )

        # ------------------------------------------------------------------
        # Same-browser completion hand-off (see the section above this handler).
        #
        # On the one combination that has no completable LINE screen, wrap the
        # real redirect hint in a hand-off ticket and hand LINE ``handoff:<id>``
        # instead of ``oidc:<id>``. Changing the prefix is what turns auto login
        # back ON, because line_auth_service.generate_authorization_url keys
        # disable_auto_login off the ``oidc:`` prefix — and that is the point:
        # the hand-off WANTS the app-switch to LINE, because the original tab
        # is now waiting to finish the Access redirect itself.
        #
        # Ordered before generate_authorization_url so the state that LINE
        # echoes back is bound to the hand-off hint, and so the ticket id never
        # has to appear anywhere the browser can see.
        #
        # Every branch that is not this exact combination leaves redirect_hint
        # untouched and reaches the identical code below that ran before the
        # hand-off existed.
        # ------------------------------------------------------------------
        handoff = None
        if _handoff_applies(
            redirect_hint=redirect_hint, is_mobile=is_mobile, user_agent=user_agent
        ):
            handoff = line_handoff_store.create_ticket(
                inner_hint=redirect_hint,
                client_ip=_client_ip(request),
            )

        effective_hint = f"handoff:{handoff.ticket_id}" if handoff else redirect_hint

        # Store redirect parameter in state for callback
        auth_data = line_auth_service.generate_authorization_url(
            redirect_hint=effective_hint,
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

        # The hand-off page replaces the guidance interstitial on that same
        # narrow combination.
        if handoff is not None:
            retry_url = request.url.path
            if request.url.query:
                retry_url = f"{retry_url}?{request.url.query}"
            handoff_response = _handoff_page(
                auth_url=auth_url,
                retry_url=retry_url,
                cookie_value=handoff.cookie_value,
            )
            if handoff_response is not None:
                return handoff_response

            # Belt and braces: _handoff_applies already refused to mint a
            # ticket without a readable page asset, so this is unreachable in
            # practice. If it ever is reached, the auth_url in hand was built
            # for the hand-off — auto login ON — and handing THAT to the
            # guidance page's button would drop the Safari cookie-jar guard for
            # anyone who taps it. Rebuild the URL against the original hint so
            # the fallback really is today's behaviour and not a half-migrated
            # one.
            auth_url = line_auth_service.generate_authorization_url(
                redirect_hint=redirect_hint,
                prefer_qr=not is_mobile,
                user_agent=user_agent,
            )["auth_url"]

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


# ============================================================================
# Same-browser hand-off — the LINE side, and the original tab's long-poll
# ============================================================================

def _handoff_line_side_page(
    heading: str, message: str, *, status_code: int = 200
) -> HTMLResponse:
    """A page for LINE's in-app browser at the end of the LINE leg.

    Chromeless card, same shape as the OIDC and kiosk-elevate status pages.
    Its whole job is to tell the person the browser they came from is
    finishing the job — the equivalent of the kiosk flow's "look up at the
    screen". Nothing here is an action; the action is switching back.
    """
    safe_heading = _escape_attribute(heading)
    safe_message = _escape_attribute(message)
    content = f"""<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>เข้าสู่ระบบด้วย LINE</title>
    <style>
        body {{
            font-family: 'Sarabun', 'Prompt', sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0; background: #f5f5f5; color: #2b2b2b;
            font-size: 20px; line-height: 1.7;
        }}
        .card {{
            background: #fff; padding: 32px 24px; border-radius: 16px;
            box-shadow: 0 2px 16px rgba(0,0,0,0.08);
            text-align: center; max-width: 460px; margin: 16px;
        }}
        h1 {{ font-size: 26px; margin: 0 0 16px; color: #6b1f2a; line-height: 1.5; }}
        p {{ color: #5c5c5c; margin: 0; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{safe_heading}</h1>
        <p>{safe_message}</p>
    </div>
</body>
</html>"""
    return HTMLResponse(content=content, status_code=status_code)


def continue_handoff_after_line(
    *,
    ticket_id: str,
    line_user_id: str,
    client_ip: str,
    display_name: Optional[str] = None,
    picture_url: Optional[str] = None,
):
    """Resume a same-browser hand-off after LINE resolves ``line_user_id``.

    Called from the LINE OAuth callback via an additive hook, the exact shape
    of :func:`app.api.oidc.continue_oidc_after_line` and
    :func:`app.api.reader.continue_elevate_after_line`.

    This runs in LINE'S IN-APP BROWSER — the wrong cookie jar, by design — so
    it deliberately does the LEAST it possibly can. It parks a resolved LINE
    identity against the ticket and renders a "go back to your browser" page.
    It mints no token, issues no code, sets no cookie, and returns nothing a
    session could be assembled from. Everything with authority happens later in
    :func:`line_handoff_wait`, behind the holder-secret cookie that only the
    originating browser has.

    That split is the point. Even a caller who somehow knows a ticket id — the
    shoulder-surf / leaked-log threat — gains nothing by driving this function:
    the only observable result is a Thai page telling them to go back to a
    browser they do not control.

    The authorization code is NOT minted here for a second, practical reason:
    oidc_service burns codes 60 seconds after issue. Minting on the LINE leg
    would start that clock while the user is still switching apps, so a slow
    return would hand Cloudflare Access an expired code and an error page
    nobody can act on. Minting at claim time means the code is always seconds
    old when it is used.
    """
    outcome = line_handoff_store.resolve_ticket(
        ticket_id,
        line_user_id=line_user_id,
        display_name=display_name,
        picture_url=picture_url,
        client_ip=client_ip,
    )

    if outcome == line_handoff_store.RESOLVE_OK:
        return _handoff_line_side_page(
            "ยืนยันตัวตนสำเร็จ",
            "กลับไปที่หน้าเว็บเดิมในเบราว์เซอร์ของคุณได้เลย "
            "ระบบกำลังพาเข้าใช้งานต่อให้ที่นั่น "
            "(Signed in — switch back to the browser tab you started from.)",
        )

    if outcome == line_handoff_store.RESOLVE_IP_MISMATCH:
        # Login fixation, or a genuine network change mid-flow. Both get the
        # same answer, and the ticket stays pending either way:
        #
        #  * If this was an attack — a ticket planted on the attacker's device
        #    and a LINE login phished onto it — the victim's identity is simply
        #    discarded here. Nothing is parked, so the attacker's polling tab
        #    waits out its budget and gets the retry page. No session, anywhere.
        #  * If this was the real user whose phone flipped wifi to cellular
        #    between starting and finishing, they are told to start again in
        #    their own browser, which works on the retry.
        #
        # Refusing to say WHICH of the two happened is deliberate: an attacker
        # must not be able to use this page to confirm that a ticket exists.
        return _handoff_line_side_page(
            "กรุณาเริ่มใหม่จากเบราว์เซอร์ของคุณ",
            "ไม่สามารถยืนยันได้ว่าคำขอนี้มาจากเครื่องเดียวกัน "
            "กรุณากลับไปเปิดหน้าเข้าสู่ระบบใหม่อีกครั้ง "
            "(Could not confirm this request came from the same device — "
            "please start the login again.)",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Unknown, expired, or already completed. One answer for all three, for the
    # same no-oracle reason as above.
    return _handoff_line_side_page(
        "คำขอหมดอายุ",
        "การเข้าสู่ระบบครั้งนี้หมดอายุหรือถูกใช้ไปแล้ว "
        "กรุณาเริ่มใหม่จากเบราว์เซอร์ของคุณ "
        "(This login has expired or was already used — start again.)",
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _complete_handoff(record: Dict[str, Any], db: Session) -> JSONResponse:
    """Turn a claimed hand-off ticket into the URL the original tab navigates to.

    Reached only from :func:`line_handoff_wait`, i.e. only after the holder
    secret has been proved and the ticket popped once. Resumes the wrapped
    ``oidc:<login-ticket>`` continuation exactly as the ordinary LINE callback
    would have, so HF ID's admission rules (registered, active, not pending
    approval) are the SAME rules on this path — no second copy of them lives
    here.

    The continuation's own return value is the answer:

    * a redirect -> the completion URL, either the Cloudflare Access callback
      carrying a fresh authorization code, or the onboarding hand-off for a
      LINE user with no employee row. Both belong in the original tab: the
      first because that tab holds the Access session, the second because the
      onboarding URL carries a bearer JWT that must not be handed to any other
      browser.
    * anything else -> a Thai failure the polling page renders, keyed off the
      continuation's own status code so "waiting for approval" stays
      distinguishable from "expired".
    """
    inner_hint = record.get("inner_hint") or ""
    if not inner_hint.startswith("oidc:"):
        # Unreachable today (only oidc: hints are wrapped), and fails closed if
        # a future caller ever wraps something else without thinking it through.
        logger.error("LINE hand-off ticket carried an unsupported inner hint")
        return JSONResponse(
            {"status": "failed", "reason": "expired"},
            headers={"Cache-Control": "no-store"},
        )

    from app.api.oidc import continue_oidc_after_line

    result = continue_oidc_after_line(
        ticket_id=inner_hint[len("oidc:"):],
        line_user_id=record["line_user_id"],
        db=db,
        display_name=record.get("display_name"),
        picture_url=record.get("picture_url"),
    )

    location = result.headers.get("location")
    if 300 <= result.status_code < 400 and location:
        return JSONResponse(
            {"status": "ready", "completion_url": location},
            headers={"Cache-Control": "no-store"},
        )

    reason = "not_ready" if result.status_code == status.HTTP_403_FORBIDDEN else "expired"
    return JSONResponse(
        {"status": "failed", "reason": reason},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/handoff/wait")
async def line_handoff_wait(
    request: Request,
    db: Session = Depends(get_db),
):
    """Long-poll from the ORIGINAL browser tab for its LINE completion.

    Authentication is the HttpOnly cookie set when the polling page was served,
    and nothing else. There is no ticket parameter to pass, guess or leak: the
    ticket id lives in that cookie and in the server's state store, never in a
    URL, a page or a log line. A caller without the cookie — an unrelated
    poller, a shared-device snooper, someone replaying a ticket id out of a log
    — is answered exactly as if the ticket did not exist.

    Answers, matching the /elevate/wait contract this repo already runs:

    * resolved -> 200 ``{"status": "ready", "completion_url": "..."}``, the
      ticket consumed (deliver-once), or ``{"status": "failed", "reason": ...}``
      when the employee is not admissible.
    * still pending when the slice elapses -> 204, and the page re-polls.
    * unknown / expired / not ours -> 404.
    * at the concurrent-waiter ceiling -> 503 + Retry-After, which the page
      treats as "poll again shortly", not as a failure.

    EVENT LOOP. This is a single-process uvicorn deployment that was bitten
    today by a blocking call parking /oidc/token, so the loop discipline here
    is copied from reader.py's /wait rather than improvised: no blocking call
    anywhere in the body, ``await asyncio.sleep(tick)`` between checks so the
    loop runs everything else while this request waits, a bounded slice (~25s)
    after which the connection is handed back instead of held open, and a hard
    ceiling on how many of these may be parked at once. The DB session from
    Depends is created but untouched until a ticket actually resolves, and
    SQLAlchemy does not acquire a connection for an unused session, so a parked
    waiter holds no database connection either.
    """
    if not line_handoff_store.is_enabled():
        # Dark until configured — indistinguishable from a route that is not
        # deployed, the same posture as the reader and OIDC surfaces.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    cookie_value = request.cookies.get(line_handoff_store.COOKIE_NAME)

    # Answer a bad/absent/foreign cookie immediately rather than parking a
    # connection for 25 seconds on its behalf. That is both the honest answer
    # and the thing that stops the long-poll being used as a connection sink.
    if line_handoff_store.peek(cookie_value) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown or expired login",
        )

    if not line_handoff_store.try_acquire_waiter():
        return JSONResponse(
            {"status": "busy"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Retry-After": "2", "Cache-Control": "no-store"},
        )

    try:
        timeout = line_handoff_store.wait_timeout_seconds()
        tick = line_handoff_store.wait_tick_seconds()
        deadline = time.monotonic() + timeout

        while True:
            record = line_handoff_store.take_resolved(cookie_value)
            if record is not None:
                return _complete_handoff(record, db)

            if time.monotonic() >= deadline:
                return Response(
                    status_code=status.HTTP_204_NO_CONTENT,
                    headers={"Cache-Control": "no-store"},
                )
            await asyncio.sleep(tick)
    finally:
        line_handoff_store.release_waiter()


@router.get("/callback")
async def line_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    redirect: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Handle LINE OAuth callback

    ``request`` is injected only so the same-browser hand-off continuation can
    see the client IP of the LINE leg (see continue_handoff_after_line). No
    other branch reads it, and no existing behaviour depends on it.

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

        # Same-browser hand-off continuation — additive hook, the exact shape
        # of the two continuations below it. When this LINE login was started
        # from the password-less mobile dead end, the redirect hint carries a
        # hand-off ticket ("handoff:<id>") that WRAPS the real "oidc:<ticket>"
        # hint. Park the resolved identity for the original browser tab to
        # collect and stop here — this request is running in LINE's in-app
        # browser, the cookie jar that must not be given a session. No existing
        # redirect hint uses the "handoff:" prefix, so nothing else changes.
        #
        # Ordered before the "oidc:" branch because a hand-off is an oidc flow
        # in a wrapper; the wrapper has to come off in the browser that started
        # it, not here.
        if redirect and redirect.startswith("handoff:"):
            return continue_handoff_after_line(
                ticket_id=redirect[len("handoff:"):],
                line_user_id=line_user_id,
                client_ip=_client_ip(request),
                display_name=display_name,
                picture_url=picture_url,
            )

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
    background_tasks: BackgroundTasks,
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

        # The employee now HAS a LINE identity, so their Employee Hub Role
        # Menu can finally be provisioned. Grant-then-link is a real
        # onboarding order — an admin ticks "Housekeeping" days before the
        # maid ever scans her Q-badge, and that grant-change trigger returned
        # early because line_user_id was still None. Without this second
        # trigger she would hold the grant and see no menu until someone ran
        # the sync script. Background + never-raises for the same reasons as
        # the grants endpoint: the link itself is committed above and must
        # not be undone by a LINE hiccup.
        background_tasks.add_task(provision_for_badge, employee.badge_number)

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
