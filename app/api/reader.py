"""Card-reader identity API — HF ID as the central card-login authority (2026-07).

HF ID is the one place a staff NFC tap becomes an identity. Two secrets guard
two distinct trust boundaries:

* ``READER_SECRET`` (reader↔central) — only the ESP32 reader knows it. Used by
  ``POST /scan`` to ingest a tap.
* ``READER_RESOLVE_SECRET`` (app↔central) — each consuming app's BACKEND knows
  it. Used by ``POST /resolve`` (direct UID→identity lookup), ``POST /claim``
  (pair a terminal to a reader) and ``POST /wait`` (long-poll for the tap and
  receive a signed card assertion).

Card-login flow (no browser ever talks to HF ID directly — all app↔central
calls are server-to-server):

    reader taps ── POST /scan ──▶  HF ID buffers a pending tap keyed by reader_id
    app backend ── POST /claim ─▶  HF ID returns a claim_token (reader_id + app)
    app backend ── POST /wait ──▶  HF ID long-polls; when the tap lands it
                                    authorizes (employee.apps ∋ app), consumes
                                    the tap once, and mints a one-time signed
                                    **card assertion** (an OIDC id_token, RS256,
                                    verifiable at GET /oidc/jwks). The app verifies
                                    it and turns it into its own session.

Each endpoint ships DARK: when its guarding secret is unset the whole surface
returns 404, mirroring the HF ID (OIDC) dark-until-configured posture.

Store: the pending-tap map (reader_id→tap) and claim map (claim_token→claim)
are module-level in-memory dicts guarded by a lock, with TTL + prune — exactly
like oidc_service's login-ticket/code stores. This is safe because the app runs
a SINGLE uvicorn worker (Dockerfile CMD: ``uvicorn app.main_unified:app`` with
no ``--workers``; docker-compose runs one container). If the app ever scales to
multiple workers, these stores must move to SQLite/Redis so taps and claims are
shared across processes.
"""
import asyncio
import hmac
import logging
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee, EmployeeAppGrant
from app.services import oidc_service

logger = logging.getLogger(__name__)

router = APIRouter()
# A second router for the PUBLIC, reader-secret-free employee self-service
# card-login surface (mounted at /api/public/reader). Kept separate from the
# secret-guarded app↔central `router` so the public/private split is obvious at
# the mount site: everything on `router` requires an X-Reader-Secret; the two
# self-login routes on `public_router` do not (the browser is the employee's
# own trusted terminal — see the self_login_* handlers below).
public_router = APIRouter()


# ============================================================================
# Constants — TTLs and long-poll budget
# ============================================================================

# A buffered tap is only meaningful for the few seconds between the physical
# tap and the app backend's /wait picking it up. Kept short so a stray tap
# never lingers to be claimed by an unrelated session.
PENDING_TAP_TTL_SECONDS = 30
# A terminal↔reader pairing (claim) is reused across many /wait re-polls while
# a human walks up to tap, so it must outlive several long-poll cycles.
CLAIM_TTL_SECONDS = 600  # 10 minutes
# A self-login ticket (employee self-service pairing) is likewise re-polled by
# many long-poll cycles while the employee walks up to tap their own card, so
# it shares the claim's generous lifetime.
SELF_LOGIN_TICKET_TTL_SECONDS = 600  # 10 minutes
# /wait long-poll budget. Env-overridable so tests don't wait 25s: set
# READER_WAIT_TIMEOUT_SECONDS / READER_WAIT_TICK_SECONDS to tiny values.
WAIT_TIMEOUT_SECONDS_DEFAULT = 25.0
WAIT_TICK_SECONDS_DEFAULT = 0.5


# ============================================================================
# Secrets (read lazily from the environment, never via pydantic Settings)
# ============================================================================

def _resolve_secret() -> str:
    """The app↔central secret (``READER_RESOLVE_SECRET``) — guards /resolve,
    /claim and /wait. Read directly via ``os.getenv`` (same convention as the
    HFID_* secrets in oidc_service)."""
    return os.getenv("READER_RESOLVE_SECRET", "").strip()


def _reader_secret() -> str:
    """The reader↔central secret (``READER_SECRET``) — guards /scan, the tap
    ingest only the ESP32 reader may call. Distinct from
    ``READER_RESOLVE_SECRET`` so a compromised app backend can't forge taps."""
    return os.getenv("READER_SECRET", "").strip()


def is_enabled() -> bool:
    """Whether the app↔central surface (/resolve, /claim, /wait) is configured.
    When False that surface is dark (404), like HF ID without a signing key."""
    return bool(_resolve_secret())


def self_login_enabled() -> bool:
    """Whether the PUBLIC employee self-service card-login surface
    (/self-login/start, /self-login/wait) is live.

    Gated on ``READER_SECRET`` — the reader↔central ingest secret — rather than
    the app↔central secret: card-login only makes sense once a physical reader
    is provisioned to inject taps via /scan. With no reader configured there is
    nothing to tap, so the whole surface ships DARK (404), mirroring the
    dark-until-configured posture of every other endpoint in this module. Note
    the browser call itself carries no secret; this gate only hides the feature
    until a reader exists."""
    return bool(_reader_secret())


def _require_secret(header_value: Optional[str], expected: str) -> None:
    """Guard an endpoint: dark (404) when ``expected`` is unset, else a
    constant-time match of the ``X-Reader-Secret`` header (401 on mismatch)."""
    if not expected:
        # Dark until configured — indistinguishable from a non-existent route.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not header_value or not hmac.compare_digest(header_value, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid reader secret"
        )


def _wait_timeout_seconds() -> float:
    """Total /wait long-poll budget (env-overridable for fast tests)."""
    try:
        return float(os.getenv("READER_WAIT_TIMEOUT_SECONDS", "") or WAIT_TIMEOUT_SECONDS_DEFAULT)
    except ValueError:
        return WAIT_TIMEOUT_SECONDS_DEFAULT


def _wait_tick_seconds() -> float:
    """/wait poll interval between tap checks (env-overridable for fast tests)."""
    try:
        return float(os.getenv("READER_WAIT_TICK_SECONDS", "") or WAIT_TICK_SECONDS_DEFAULT)
    except ValueError:
        return WAIT_TICK_SECONDS_DEFAULT


# ============================================================================
# In-memory stores (single-worker; guarded by a lock, TTL + prune)
# ============================================================================

_store_lock = threading.Lock()
# reader_id -> {"badge","display_name","apps","expires_at"}
_pending_taps: Dict[str, Dict[str, Any]] = {}
# claim_token -> {"reader_id","app","expires_at"}
_claims: Dict[str, Dict[str, Any]] = {}
# login_ticket -> {"reader_id","expires_at"} — the employee self-service
# pairing store. Kept separate from _claims so the public self-login namespace
# never collides with the secret-guarded app↔central claim namespace (a leaked
# claim_token can't be replayed against self-login, and vice versa). Both paths
# still share the ONE _pending_taps store, so a tap is delivered once to
# whichever consumer polls first — hence the one-terminal-per-reader assumption.
_self_login_tickets: Dict[str, Dict[str, Any]] = {}


def _prune_locked(now: float) -> None:
    """Drop expired taps/claims/self-login tickets. Must hold ``_store_lock``."""
    for reader_id in [k for k, v in _pending_taps.items() if v["expires_at"] <= now]:
        _pending_taps.pop(reader_id, None)
    for token in [k for k, v in _claims.items() if v["expires_at"] <= now]:
        _claims.pop(token, None)
    for token in [k for k, v in _self_login_tickets.items() if v["expires_at"] <= now]:
        _self_login_tickets.pop(token, None)


def stash_pending_tap(*, reader: str, badge: str, display_name: str, apps: List[str]) -> None:
    """Buffer a resolved tap for a reader (replacing any prior unclaimed tap)."""
    now = time.time()
    with _store_lock:
        _prune_locked(now)
        _pending_taps[reader] = {
            "badge": badge,
            "display_name": display_name,
            "apps": list(apps),
            "expires_at": now + PENDING_TAP_TTL_SECONDS,
        }


def consume_pending_tap(reader: str) -> Optional[Dict[str, Any]]:
    """Atomically fetch-and-remove a pending tap (deliver-once), or None if
    absent/expired. Popping under the lock guarantees a tap is delivered to at
    most one caller.

    This is the single, clean accessor into the pending-tap store shared by BOTH
    consumers of a tap: the app↔central ``/wait`` long-poll AND the public
    ``/self-login/wait`` long-poll. Neither reaches into the store internals; both
    call this. Because it is deliver-once, a given reader must be paired to only
    one of the two at a time (one terminal per reader)."""
    now = time.time()
    with _store_lock:
        record = _pending_taps.pop(reader, None)
    if record is None or record["expires_at"] <= now:
        return None
    return record


def create_claim(*, reader_id: str, app: str) -> str:
    """Pair a terminal to a reader for an app; return an opaque claim token."""
    token = secrets.token_hex(32)  # 32 random bytes → 64 hex chars
    now = time.time()
    with _store_lock:
        _prune_locked(now)
        _claims[token] = {
            "reader_id": reader_id,
            "app": app,
            "expires_at": now + CLAIM_TTL_SECONDS,
        }
    return token


def lookup_claim(token: str) -> Optional[Dict[str, Any]]:
    """Resolve a claim token to its ``{reader_id, app}`` binding, or None.

    Read-only (not consume-once): one claim is re-polled by many /wait calls
    over its 10-minute life until a tap finally lands."""
    now = time.time()
    with _store_lock:
        record = _claims.get(token)
    if record is None or record["expires_at"] <= now:
        return None
    return dict(record)


def create_self_login_ticket(*, reader_id: str) -> str:
    """Pair an employee self-service terminal to a reader; return an opaque
    login ticket the browser then long-polls with via /self-login/wait.

    The self-service analogue of ``create_claim`` — but with no ``app`` binding,
    because self-service authorizes on active-employee alone, not an app grant."""
    token = secrets.token_hex(32)  # 32 random bytes → 64 hex chars
    now = time.time()
    with _store_lock:
        _prune_locked(now)
        _self_login_tickets[token] = {
            "reader_id": reader_id,
            "expires_at": now + SELF_LOGIN_TICKET_TTL_SECONDS,
        }
    return token


def lookup_self_login_ticket(token: str) -> Optional[Dict[str, Any]]:
    """Resolve a self-login ticket to its ``{reader_id}`` binding, or None.

    Read-only (not consume-once): one ticket is re-polled by many
    /self-login/wait calls over its life until a tap finally lands."""
    now = time.time()
    with _store_lock:
        record = _self_login_tickets.get(token)
    if record is None or record["expires_at"] <= now:
        return None
    return dict(record)


def reset_state() -> None:
    """Clear the in-memory stores (test isolation only)."""
    with _store_lock:
        _pending_taps.clear()
        _claims.clear()
        _self_login_tickets.clear()


# ============================================================================
# Shared employee lookup (identical to the /resolve rule)
# ============================================================================

def _find_employee_by_uid(db: Session, uid: str) -> Optional[Employee]:
    """Case-insensitive NFC-UID → employee lookup.

    The reader sends uppercase hex; the admin assign endpoint stores the UID
    verbatim, so existing data may be mixed-case — compare case-insensitively
    on both sides so lookups line up regardless.
    """
    normalized = uid.strip().upper()
    return (
        db.query(Employee)
        .filter(func.upper(Employee.nfc_card_uid) == normalized)
        .first()
    )


def _grant_app_ids(db: Session, badge: str) -> List[str]:
    """The employee's granted app ids (the ``apps`` claim), ordered by id."""
    return [
        grant.app_id
        for grant in (
            db.query(EmployeeAppGrant)
            .filter(EmployeeAppGrant.employee_badge_number == badge)
            .order_by(EmployeeAppGrant.app_id)
            .all()
        )
    ]


# ============================================================================
# Request bodies
# ============================================================================

class ResolveRequest(BaseModel):
    uid: str


class ScanRequest(BaseModel):
    uid: str
    reader: str
    ts: Optional[int] = None


class ClaimRequest(BaseModel):
    reader_id: str
    app: str


class WaitRequest(BaseModel):
    claim_token: str


class SelfLoginStartRequest(BaseModel):
    reader_id: str


# ============================================================================
# POST /resolve — direct UID → employee identity (app↔central)
# ============================================================================

@router.post("/resolve")
async def resolve_card(
    body: ResolveRequest,
    x_reader_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Resolve a tapped NFC card UID into an employee identity.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET``. Dark (404) when unset; 401 on mismatch.

    A UID with no matching employee is a normal answer (found=false, HTTP 200),
    not an error.
    """
    _require_secret(x_reader_secret, _resolve_secret())

    employee = _find_employee_by_uid(db, body.uid)
    if employee is None:
        return {
            "found": False,
            "badge": None,
            "display_name": None,
            "apps": [],
            "active": False,
            "pending": False,
        }

    return {
        "found": True,
        "badge": employee.badge_number,
        "display_name": employee.display_name,
        "apps": _grant_app_ids(db, employee.badge_number),
        "active": bool(employee.is_active),
        "pending": bool(employee.pending_approval),
    }


# ============================================================================
# POST /scan — the ESP32 reader ingests a tap (reader↔central)
# ============================================================================

@router.post("/scan")
async def scan_card(
    body: ScanRequest,
    x_reader_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Ingest a physical NFC tap and buffer it for the reader.

    Auth: constant-time match of ``X-Reader-Secret`` against ``READER_SECRET``
    (reader↔central; NOT the app secret). Dark (404) when unset; 401 on
    mismatch.

    The UID is resolved to an employee. An unknown card, an inactive employee,
    or a still-pending onboarding all yield 403 (the reader double-beeps). A
    good tap is stashed as a pending tap for ``reader`` (TTL ~30s) and returns
    200 with the display name so the reader can show who tapped.
    """
    _require_secret(x_reader_secret, _reader_secret())

    employee = _find_employee_by_uid(db, body.uid)
    if employee is None or not employee.is_active or employee.pending_approval:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Card not authorized"
        )

    apps = _grant_app_ids(db, employee.badge_number)
    stash_pending_tap(
        reader=body.reader,
        badge=employee.badge_number,
        display_name=employee.display_name,
        apps=apps,
    )
    return {"ok": True, "display_name": employee.display_name}


# ============================================================================
# POST /claim — an app backend pairs a terminal to a reader (app↔central)
# ============================================================================

@router.post("/claim")
async def claim_reader(
    body: ClaimRequest,
    x_reader_secret: Optional[str] = Header(None),
):
    """Pair a terminal to a reader for a specific app grant.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET``. Dark (404) when unset; 401 on mismatch.

    Returns an opaque ``claim_token`` the app backend then long-polls with via
    /wait. ``app`` is the grant key the app requires (e.g. "payroll", "rooms").
    """
    _require_secret(x_reader_secret, _resolve_secret())

    token = create_claim(reader_id=body.reader_id, app=body.app)
    return {"claim_token": token}


# ============================================================================
# POST /wait — an app backend long-polls for the tap (app↔central)
# ============================================================================

@router.post("/wait")
async def wait_for_tap(
    body: WaitRequest,
    x_reader_secret: Optional[str] = Header(None),
):
    """Long-poll for a tap on the claim's reader; return a signed card assertion.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET``. Dark (404) when unset; 401 on mismatch.

    Looks up the claim → (reader_id, app), then polls ~25s (env-overridable) in
    ~0.5s ticks for a pending tap on that reader. When a tap lands it is
    consumed (deliver-once) and:

    * If the tapped employee's grants contain the claim's ``app`` → mint a
      one-time **card assertion** (an RS256 OIDC id_token, aud=<app>) and
      return 200 ``{"assertion": "<jwt>"}``.
    * Otherwise → 403 ``{"error": "not_authorized"}`` (the tap is still
      consumed so it doesn't loop).

    On timeout with no tap → 204 (the app backend re-polls with the same token).
    An unknown/expired claim → 404.
    """
    _require_secret(x_reader_secret, _resolve_secret())

    claim = lookup_claim(body.claim_token)
    if claim is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown or expired claim"
        )

    reader_id = claim["reader_id"]
    app = claim["app"]

    timeout = _wait_timeout_seconds()
    tick = _wait_tick_seconds()
    deadline = time.monotonic() + timeout

    while True:
        tap = consume_pending_tap(reader_id)
        if tap is not None:
            # Authorize: the tapped employee must hold the claim's app grant.
            if app not in tap["apps"]:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"error": "not_authorized"},
                )
            assertion = oidc_service.mint_id_token(
                badge=tap["badge"],
                email=oidc_service.synthetic_email_for_badge(tap["badge"]),
                name=tap["display_name"],
                apps=tap["apps"],
                nonce=None,
                audience=app,
            )
            return {"assertion": assertion}

        if time.monotonic() >= deadline:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        await asyncio.sleep(tick)


# ============================================================================
# Employee self-service card-login (PUBLIC — no reader secret)
# ============================================================================
#
# This is the browser-facing half of "tap your NFC staff card to log in" for an
# employee viewing THEIR OWN attendance. Unlike the app↔central endpoints above,
# these two are served on ``public_router`` (mounted at /api/public/reader) and
# carry NO X-Reader-Secret: the caller is the employee's own terminal (an office
# tablet / kiosk on the local network), not a server. The trust boundary is the
# opaque pairing ticket + the short pending-tap TTL + READER_SECRET on /scan
# (only the ESP32 reader can inject a tap). The whole surface ships DARK (404)
# until READER_SECRET is configured.
#
# Because this app ALSO owns the pending-tap store, a tap is resolved IN-PROCESS
# via ``consume_pending_tap`` — no HTTP/JWT round-trip to ourselves, and no card
# assertion is minted. Instead we mint the EXACT same LINE-JWT self-service
# session the LINE-login path issues (``line_auth_service.create_jwt_token``),
# so the browser stores it in localStorage just like the ``?jwt=`` LINE redirect.


def _mint_self_login_session(db: Session, badge: str):
    """Re-verify the tapped employee, then mint their self-service session.

    Defense-in-depth: even though /scan already rejected inactive/pending cards
    at stash time, we re-query here so an employee deactivated between tap and
    consume can't slip through. Self-service gates ONLY on active + not
    pending_approval — no app grant is required (an employee is always allowed
    to view their own data).

    Returns the same shape the browser expects to persist: the LINE JWT under
    ``token`` (stored as ``line_jwt_token`` in localStorage, identical to the
    LINE-login redirect), plus badge/name for immediate display.
    """
    employee = db.query(Employee).filter(Employee.badge_number == badge).first()
    if employee is None or not employee.is_active or employee.pending_approval:
        # Tap already consumed by the caller — a 403 here does not loop.
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"error": "not_authorized"},
        )

    # Lazy import keeps reader.py free of any import-time coupling to the LINE
    # service (which resolves JWT_SECRET at import); it is already loaded by the
    # app at runtime. Reusing create_jwt_token verbatim is the whole point — the
    # card path mints the identical session the LINE path does.
    from app.services.line_auth_service import line_auth_service

    display_name = employee.line_display_name or employee.display_name
    token = line_auth_service.create_jwt_token(
        line_user_id=employee.line_user_id,
        employee_badge=employee.badge_number,
        display_name=display_name,
        picture_url=employee.line_picture_url,
    )
    return {
        "token": token,
        "employee_badge": employee.badge_number,
        "display_name": display_name,
    }


@public_router.post("/self-login/start")
async def self_login_start(body: SelfLoginStartRequest):
    """Pair the employee's terminal to its reader; return a login ticket.

    Public and reader-secret-free (see the section header). Ships DARK (404)
    until READER_SECRET is configured. Mirrors /claim: takes a ``reader_id`` and
    returns an opaque ``login_ticket`` the browser long-polls with — but with no
    ``app`` because self-service needs no app grant.
    """
    if not self_login_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    reader_id = body.reader_id.strip()
    if not reader_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="reader_id is required"
        )

    token = create_self_login_ticket(reader_id=reader_id)
    return {"login_ticket": token}


@public_router.get("/self-login/wait")
async def self_login_wait(ticket: str, db: Session = Depends(get_db)):
    """Long-poll for a tap on the paired reader; return the minted session.

    Public and reader-secret-free (see the section header). Ships DARK (404)
    until READER_SECRET is configured.

    Resolves ``ticket`` → reader_id, then polls the shared pending-tap store
    (in-process, via ``consume_pending_tap``) for ~25s in ~0.5s ticks
    (env-overridable, same knobs as the app↔central /wait). On a tap:

    * active, non-pending employee -> 200 ``{"token", "employee_badge", ...}``
      (the same LINE-JWT session the LINE-login path mints).
    * inactive / pending / unknown badge -> 403 ``{"error": "not_authorized"}``
      (the tap is still consumed so it does not loop).

    On no tap before the budget elapses -> 204 (the browser re-polls with the
    same ticket). Unknown/expired ticket -> 404.
    """
    if not self_login_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    record = lookup_self_login_ticket(ticket)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown or expired ticket"
        )

    reader_id = record["reader_id"]

    timeout = _wait_timeout_seconds()
    tick = _wait_tick_seconds()
    deadline = time.monotonic() + timeout

    while True:
        tap = consume_pending_tap(reader_id)
        if tap is not None:
            return _mint_self_login_session(db, tap["badge"])

        if time.monotonic() >= deadline:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        await asyncio.sleep(tick)
