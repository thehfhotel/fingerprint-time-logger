"""Card-reader identity API — HF ID as the central card-login authority (2026-07).

HF ID is the one place a staff NFC tap becomes an identity. Two secrets guard
two distinct trust boundaries:

* ``READER_SECRET`` (reader↔central) — only the ESP32 reader knows it. Used by
  ``POST /scan`` to ingest a tap.
* ``READER_RESOLVE_SECRET`` (app↔central) — each consuming app's BACKEND knows
  it. Used by ``POST /resolve`` (direct UID→identity lookup),
  ``POST /resolve-badge`` (the same lookup keyed by badge, for an app that
  already holds an identity and needs the employee's branch), ``POST /claim``
  (pair a terminal to a reader), ``POST /wait`` (long-poll for the tap and
  receive a signed card assertion) and ``POST /hk-escalate`` (new-hotel asks
  HF ID to LINE-push an unacked ขอเช็คห้อง to the branch's on-duty maids —
  attendance is HF ID's, so only HF ID can answer who is on shift).

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

LINE-scan elevation flow (2026-07, Phase 3b of the employee-login plan): the
LINE Authenticator's answer to the card tap for shared kiosks. Same trust
boundaries, same assertion, no new OIDC client — the phone rides the EXISTING
LINE OAuth login (app/api/line_auth.py) exactly like HF ID's /oidc/authorize
does, via a redirect-hint continuation:

    app backend ── POST /elevate/start ─▶  HF ID mints an elevate ticket
                   (X-Reader-Secret)        (app + label, TTL 10 min)
    kiosk shows a QR of the PUBLIC page GET /api/public/reader/elevate/{ticket}
    employee's phone opens it (the erp /api/public* Cloudflare bypass), taps the
    LINE button → the stock LINE OAuth login with redirect hint
    ``elevate:<ticket>`` → the LINE callback hands control to
    :func:`continue_elevate_after_line`, which authorizes (employee.apps ∋ app)
    and parks the SAME one-time card assertion /wait would mint.
    app backend ── POST /elevate/wait ──▶  long-polls; delivers the assertion
                   (X-Reader-Secret)        once (or 403 not_authorized), so the
                                            kiosk elevates identically to a tap.

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
import re
import secrets
import threading
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee, EmployeeAppGrant
from app.services import hk_escalation_service, oidc_service, staff_oa_service
from app.services.line_auth_service import line_auth_service

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
# A kiosk elevate ticket (LINE-scan elevation) is the claim's LINE analogue:
# displayed as a QR and re-polled by the kiosk backend while the employee pulls
# out their phone, scans, and completes LINE OAuth — same generous lifetime.
ELEVATE_TICKET_TTL_SECONDS = 600  # 10 minutes
# The kiosk label an elevate ticket may carry (echoed on the phone-side page so
# the person sees WHICH terminal they are signing in to). Length-capped defence.
ELEVATE_LABEL_MAX_CHARS = 64
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


def _secret_guard(expected_secret: Callable[[], str]):
    """Build the route-level ``dependencies=[...]`` guard for one secret.

    **Why a dependency and not a call in the handler body (2026-09):** when the
    guard was the first statement of the handler, FastAPI had already parsed
    and validated the request body by the time it ran, so an UNAUTHENTICATED
    caller posting a wrong-shaped body got 422 with a full pydantic error list
    — field names, types, which keys are missing — instead of 401. That is a
    schema disclosure: the caller learns the endpoint's contract without ever
    proving it may call it. It affected every endpoint on this router,
    /hk-escalate included.

    FastAPI solves a route's ``dependencies`` BEFORE it validates the body and
    before it raises ``RequestValidationError``, so raising 401/404 in here
    preempts the 422 and the body is never described to a caller we have not
    authenticated. ``expected_secret`` is a callable, not a value, so the
    environment stays read per-request (the lazy-secret convention above, which
    monkeypatching tests depend on).

    Residual, and deliberate: a body that is not decodable JSON at all still
    answers 422, because FastAPI decodes the raw payload before it solves any
    dependency. That 422 carries no schema — only "this was not JSON" — so it
    discloses nothing about the endpoint, and preempting it would mean
    hand-rolling body reads on every route.
    """

    async def _guard(x_reader_secret: Optional[str] = Header(None)) -> None:
        _require_secret(x_reader_secret, expected_secret())

    return Depends(_guard)


#: The app↔central guard (``READER_RESOLVE_SECRET``) — /resolve, /resolve-badge,
#: /hk-escalate, /claim, /wait, /elevate/start, /elevate/wait.
RequireResolveSecret = _secret_guard(_resolve_secret)
#: The reader↔central guard (``READER_SECRET``) — /scan only. A separate secret
#: on purpose: a compromised app backend must not be able to forge taps.
RequireReaderSecret = _secret_guard(_reader_secret)


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
# elevate_token -> {"app","label","status","assertion","expires_at"} — the
# kiosk LINE-scan elevation store. status walks pending → authorized (assertion
# parked) or pending → denied (tapped-equivalent employee without the grant);
# the app backend's /elevate/wait then pops the resolved ticket (deliver-once).
# Its own namespace for the same reason as _self_login_tickets above.
_elevate_tickets: Dict[str, Dict[str, Any]] = {}


def _prune_locked(now: float) -> None:
    """Drop expired taps/claims/self-login/elevate tickets. Must hold ``_store_lock``."""
    for reader_id in [k for k, v in _pending_taps.items() if v["expires_at"] <= now]:
        _pending_taps.pop(reader_id, None)
    for token in [k for k, v in _claims.items() if v["expires_at"] <= now]:
        _claims.pop(token, None)
    for token in [k for k, v in _self_login_tickets.items() if v["expires_at"] <= now]:
        _self_login_tickets.pop(token, None)
    for token in [k for k, v in _elevate_tickets.items() if v["expires_at"] <= now]:
        _elevate_tickets.pop(token, None)


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


def create_elevate_ticket(*, app: str, label: str) -> str:
    """Mint a kiosk LINE-scan elevate ticket; return its opaque token.

    The LINE analogue of ``create_claim``: instead of binding a terminal to a
    physical reader, the ticket itself IS what the person "taps" — its token
    rides a QR to the employee's phone, and the LINE callback resolves it.
    ``app`` is the grant key the kiosk requires (e.g. "portal"); ``label`` is a
    short human name for the terminal, echoed on the phone-side page.
    """
    token = secrets.token_hex(32)  # 32 random bytes → 64 hex chars
    now = time.time()
    with _store_lock:
        _prune_locked(now)
        _elevate_tickets[token] = {
            "app": app,
            "label": label,
            "status": "pending",
            "assertion": None,
            "expires_at": now + ELEVATE_TICKET_TTL_SECONDS,
        }
    return token


def lookup_elevate_ticket(token: str) -> Optional[Dict[str, Any]]:
    """Resolve an elevate token to a copy of its record, or None.

    Read-only (not consume-once): the public QR page and the LINE continuation
    both peek at the ticket before anything is decided; only
    :func:`take_resolved_elevate_ticket` removes it.
    """
    now = time.time()
    with _store_lock:
        record = _elevate_tickets.get(token)
    if record is None or record["expires_at"] <= now:
        return None
    return dict(record)


def resolve_elevate_ticket(
    token: str, *, authorized: bool, assertion: Optional[str] = None
) -> bool:
    """One-time pending → authorized/denied transition for an elevate ticket.

    Returns False when the ticket is absent, expired, or already resolved — a
    second LINE completion against the same QR can never overwrite the first
    (mirrors the deliver-once posture of ``consume_pending_tap``).
    """
    now = time.time()
    with _store_lock:
        record = _elevate_tickets.get(token)
        if record is None or record["expires_at"] <= now:
            return False
        if record["status"] != "pending":
            return False
        record["status"] = "authorized" if authorized else "denied"
        record["assertion"] = assertion
    return True


def take_resolved_elevate_ticket(token: str) -> Optional[Dict[str, Any]]:
    """Pop-and-return an elevate ticket IFF it has been resolved (deliver-once).

    Pending tickets stay put (the /elevate/wait long-poll keeps watching them);
    absent/expired tickets return None. Popping under the lock guarantees the
    parked assertion is delivered to at most one caller.
    """
    now = time.time()
    with _store_lock:
        record = _elevate_tickets.get(token)
        if record is None or record["expires_at"] <= now:
            return None
        if record["status"] == "pending":
            return None
        _elevate_tickets.pop(token, None)
    return dict(record)


def reset_state() -> None:
    """Clear the in-memory stores (test isolation only)."""
    with _store_lock:
        _pending_taps.clear()
        _claims.clear()
        _self_login_tickets.clear()
        _elevate_tickets.clear()


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


def _find_employee_by_badge(db: Session, badge: str) -> Optional[Employee]:
    """Exact badge_number → employee lookup (the /resolve-badge rule).

    Deliberately NOT case-folded, unlike :func:`_find_employee_by_uid`. A card
    UID is hex whose case is an artefact of who wrote the row, so folding it is
    a correction; a badge is the identity key ITSELF — it is what a card
    assertion carries as ``sub``, it is stored verbatim, and it is unique
    case-sensitively — so folding case here could quietly map two distinct
    badges onto one employee. Surrounding whitespace IS stripped: it is never
    part of a badge and is the easiest thing for a caller to send by accident.

    A blank badge matches nothing rather than degenerating into a query that
    could pair with an empty-string badge row.
    """
    normalized = badge.strip()
    if not normalized:
        return None
    return db.query(Employee).filter(Employee.badge_number == normalized).first()


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


class ResolveBadgeRequest(BaseModel):
    badge: str


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


class HkEscalateRequest(BaseModel):
    branch: str
    roomNo: str  # noqa: N815 — camelCase on the wire (new-hotel's DTO style)
    url: str


class ElevateStartRequest(BaseModel):
    app: str
    label: Optional[str] = None


class ElevateWaitRequest(BaseModel):
    elevate_token: str


# ============================================================================
# POST /resolve — direct UID → employee identity (app↔central)
# ============================================================================

@router.post("/resolve", dependencies=[RequireResolveSecret])
async def resolve_card(
    body: ResolveRequest,
    db: Session = Depends(get_db),
):
    """Resolve a tapped NFC card UID into an employee identity.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET``. Dark (404) when unset; 401 on mismatch.

    A UID with no matching employee is a normal answer (found=false, HTTP 200),
    not an error.

    ``location`` ('HF' | 'HF_VILLE' | null) rides along for the same reason
    /resolve-badge exists — see that endpoint's note. It is passed through
    VERBATIM, null included; null means "HF ID has no branch on file", never a
    default branch.
    """
    employee = _find_employee_by_uid(db, body.uid)
    if employee is None:
        return {
            "found": False,
            "badge": None,
            "display_name": None,
            "apps": [],
            "active": False,
            "pending": False,
            "location": None,
        }

    return {
        "found": True,
        "badge": employee.badge_number,
        "display_name": employee.display_name,
        "apps": _grant_app_ids(db, employee.badge_number),
        "active": bool(employee.is_active),
        "pending": bool(employee.pending_approval),
        "location": employee.location,
    }


# ============================================================================
# POST /resolve-badge — badge → employee identity + branch (app↔central)
# ============================================================================
#
# The badge-keyed sibling of /resolve: same secret, same dark-when-unset
# posture, same not-found-is-200 contract, same payload. It exists because a
# consuming app that ALREADY has an identity — from a card assertion's ``sub``,
# an OIDC id_token, or its own session — holds a badge and not a card UID, so
# /resolve is unusable to it. Nothing here is visible to a caller that could
# not already learn it from /resolve for the same employee.
#
# Why (2026-08): new-hotel's maid surface (hotel.thehfhotel.org/hk) now files a
# cleaning report against a specific branch, but its branch picker was fed by a
# GLOBAL env allowlist (HK_BRANCHES) identical for every employee — so an HF
# Ville maid was offered "HF Hotel" too, and could file against the WRONG
# PROPERTY. HF ID already holds the authoritative answer in Employee.location.
# It is in no OIDC claim, and adding a Cloudflare Access claim is impractical
# (the IdP ``claims`` config is set at IdP-create time with no update path), so
# the app backend asks HF ID over the LAN instead: filter the picker to the
# maid's own branch, and refuse a mutation whose branch disagrees.
#
# ``location`` is passed through VERBATIM, NULL INCLUDED. Do not invent a
# default here. The consumer must be able to tell "this employee works at HF
# Hotel" from "HF ID does not know", because it REFUSES on unknown — coercing
# null to "HF" would silently reintroduce the exact wrong-property bug this
# endpoint fixes, one layer down and much harder to see.


@router.post("/resolve-badge", dependencies=[RequireResolveSecret])
async def resolve_badge(
    body: ResolveBadgeRequest,
    db: Session = Depends(get_db),
):
    """Resolve an employee badge number into an identity + branch location.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET``. Dark (404) when unset; 401 on mismatch —
    identical to /resolve, and the identical app↔central caller class.

    A badge with no matching employee is a normal answer (found=false, HTTP
    200), not an error: the caller is asking a question, not asserting the row
    exists.

    ``location`` is 'HF' | 'HF_VILLE' | null, verbatim from Employee.location.
    null means unassigned in HF ID — the caller must treat it as UNKNOWN and
    refuse, not as a branch.
    """
    employee = _find_employee_by_badge(db, body.badge)
    if employee is None:
        return {
            "found": False,
            "badge": None,
            "display_name": None,
            "apps": [],
            "active": False,
            "pending": False,
            "location": None,
        }

    return {
        "found": True,
        "badge": employee.badge_number,
        "display_name": employee.display_name,
        "apps": _grant_app_ids(db, employee.badge_number),
        "active": bool(employee.is_active),
        "pending": bool(employee.pending_approval),
        "location": employee.location,
    }


# ============================================================================
# POST /hk-escalate — housekeeping room-check escalation (app↔central)
# ============================================================================
#
# HF ID's half of new-hotel ADR 0008 ("Room signals over chat; LINE as door and
# escalation valve, never the pipe"). new-hotel owns room signals and their
# 2-minute unacked timer and monthly push cap; it calls here because HF ID owns
# ATTENDANCE and is the only system that can answer "who is physically working
# at this branch right now". Same router, same X-Reader-Secret guard, same
# dark-when-unset posture as /resolve — one secret for the whole app↔central
# surface (see the module docstring).
#
# The on-duty rule and the LINE multicast live in
# app/services/hk_escalation_service.py; this handler is validation + the
# status-code contract below.

#: Room numbers are short and boring by construction ("104"). Anything outside
#: this set is a caller bug, not a room — reject rather than sanitize, because
#: a *silently altered* room number would send maids to the wrong door.
_ROOM_NO_ALLOWED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./-]*$")


@router.post("/hk-escalate", dependencies=[RequireResolveSecret])
async def hk_escalate(
    body: HkEscalateRequest,
    db: Session = Depends(get_db),
):
    """Push an unacked ขอเช็คห้อง to the on-duty maids of one branch.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET`` — identical to /resolve, and the identical
    app↔central caller class. Dark (404) when unset; 401 on mismatch.

    Body ``{branch: 'HF'|'HF_VILLE', roomNo: str, url: str}``. Only those two
    string fields ever reach the message; the Thai sentence itself is ours.

    **The status split is the contract, because the caller marks the signal
    escalated on ANY 2xx and retries on anything else** (new-hotel's scheduler
    sets ``sig_escalated_at`` once, only on 2xx):

    * 200 ``{"sent": true, "recipients": n}`` — multicast accepted by LINE.
    * 200 ``{"sent": false, "recipients": 0, "reason": "nobody_on_duty"}`` — a
      VALID, terminal outcome. No push, no fallback audience (ADR 0008: the
      desk phones instead). 2xx on purpose: retrying next tick would not
      conjure a maid, and would burn the monthly cap on a room nobody can be
      told about.
    * 400 — unknown branch, or an unusable roomNo/url. A retry cannot fix a
      malformed body, but a 400 keeps the signal un-escalated and therefore
      visible rather than silently marked handled.
    * 502 — LINE rejected or could not be reached; the resolution query blew
      up. The push did NOT happen, so the caller must retry next tick.
    * 503 — the staff OA is not configured here (no channel access token), so
      no push is possible at all. Non-2xx for the same reason as 502: nothing
      was delivered, and the signal must stay un-escalated.
    """
    branch = body.branch.strip()
    if hk_escalation_service.branch_device_name(branch) is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown branch"
        )

    room_no = body.roomNo.strip()
    if not room_no or len(room_no) > hk_escalation_service.ROOM_NO_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid roomNo"
        )
    if not _ROOM_NO_ALLOWED.match(room_no):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid roomNo"
        )

    url = body.url.strip()
    if (
        not url
        or len(url) > hk_escalation_service.URL_MAX_CHARS
        or not url.startswith(("https://", "http://"))
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid url"
        )

    if not staff_oa_service.get_channel_access_token():
        # Gated on the PUSH credential alone, not staff_oa_service.is_enabled():
        # a multicast needs the channel access token; the channel SECRET only
        # verifies inbound webhook signatures and is irrelevant here.
        logger.warning(
            "hk-escalate: staff OA channel access token unset — cannot push "
            "room-check escalation for branch=%s", branch,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LINE staff OA not configured",
        )

    try:
        return hk_escalation_service.escalate(
            db, branch=branch, room_no=room_no, url=url
        )
    except HTTPException:
        raise
    except Exception:
        # Any failure past validation — LINE non-2xx, a network error, or a
        # blown-up resolution query — is a NON-2xx so new-hotel retries on its
        # next 30s tick and the signal stays un-escalated. Nothing was pushed.
        logger.exception(
            "hk-escalate: escalation failed for branch=%s room=%s", branch, room_no
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Escalation failed"
        )


# ============================================================================
# POST /scan — the ESP32 reader ingests a tap (reader↔central)
# ============================================================================

@router.post("/scan", dependencies=[RequireReaderSecret])
async def scan_card(
    body: ScanRequest,
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

@router.post("/claim", dependencies=[RequireResolveSecret])
async def claim_reader(
    body: ClaimRequest,
):
    """Pair a terminal to a reader for a specific app grant.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET``. Dark (404) when unset; 401 on mismatch.

    Returns an opaque ``claim_token`` the app backend then long-polls with via
    /wait. ``app`` is the grant key the app requires (e.g. "payroll", "rooms").
    """
    token = create_claim(reader_id=body.reader_id, app=body.app)
    return {"claim_token": token}


# ============================================================================
# POST /wait — an app backend long-polls for the tap (app↔central)
# ============================================================================

@router.post("/wait", dependencies=[RequireResolveSecret])
async def wait_for_tap(
    body: WaitRequest,
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
# POST /elevate/start + /elevate/wait — kiosk LINE-scan elevation (app↔central)
# ============================================================================


@router.post("/elevate/start", dependencies=[RequireResolveSecret])
async def elevate_start(
    body: ElevateStartRequest,
):
    """Mint a kiosk LINE-scan elevate ticket for a specific app grant.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET``. Dark (404) when unset; 401 on mismatch.

    The LINE analogue of /claim: returns an opaque ``elevate_token`` the app
    backend (a) embeds in a QR pointing the employee's phone at the PUBLIC
    ``GET /api/public/reader/elevate/{ticket}`` page, and (b) long-polls with
    via /elevate/wait. ``app`` is the grant key the kiosk requires (e.g.
    "portal"); ``label`` (optional, length-capped) names the terminal on the
    phone-side page.
    """
    app = body.app.strip()
    if not app:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="app is required"
        )
    label = (body.label or "").strip()[:ELEVATE_LABEL_MAX_CHARS]

    token = create_elevate_ticket(app=app, label=label)
    return {"elevate_token": token}


@router.post("/elevate/wait", dependencies=[RequireResolveSecret])
async def elevate_wait(
    body: ElevateWaitRequest,
):
    """Long-poll for the LINE completion of an elevate ticket.

    Auth: constant-time match of ``X-Reader-Secret`` against
    ``READER_RESOLVE_SECRET``. Dark (404) when unset; 401 on mismatch.

    Polls ~25s (env-overridable, the same knobs as /wait) until the LINE
    callback resolves the ticket via :func:`continue_elevate_after_line`:

    * authorized → the ticket is consumed (deliver-once) and its parked
      one-time **card assertion** is returned: 200 ``{"assertion": "<jwt>"}``
      — the identical artefact a card tap yields from /wait.
    * denied (scanned by an employee without the app grant) → the ticket is
      consumed and 403 ``{"error": "not_authorized"}`` — the card path's
      exact answer for a tap without the grant.

    On timeout with the ticket still pending → 204 (the app backend re-polls
    with the same token). An unknown/expired ticket → 404.
    """
    if lookup_elevate_ticket(body.elevate_token) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown or expired ticket"
        )

    timeout = _wait_timeout_seconds()
    tick = _wait_tick_seconds()
    deadline = time.monotonic() + timeout

    while True:
        record = take_resolved_elevate_ticket(body.elevate_token)
        if record is not None:
            if record["status"] != "authorized" or not record["assertion"]:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"error": "not_authorized"},
                )
            return {"assertion": record["assertion"]}

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


# ============================================================================
# Kiosk LINE-scan elevation — the phone side (PUBLIC — no reader secret)
# ============================================================================
#
# The browser here is the EMPLOYEE'S OWN PHONE, which scanned the QR a kiosk is
# showing. It reaches this app through the erp.thehfhotel.org ``/api/public*``
# Cloudflare bypass (the same path the QR clock-in phones use), so no Access
# account is needed. The page itself carries no secret and mints nothing: it
# only forwards the phone into the stock LINE OAuth login with an
# ``elevate:<ticket>`` redirect hint, exactly the way HF ID's /oidc/authorize
# forwards with ``oidc:<ticket>``. All authority stays server-side — the LINE
# callback resolves the LINE user, and :func:`continue_elevate_after_line`
# checks grants and parks the assertion for the secret-guarded /elevate/wait.
#
# Gate: the surface is dark (404) until READER_RESOLVE_SECRET is configured —
# without that secret no /elevate/start can mint a ticket, so there is nothing
# for this page to show anyway (mirrors self-login's dark-until-a-reader-exists
# posture, transposed to the secret that makes elevation possible).

# The existing LINE login entrypoint, reused verbatim (no LINE config is
# duplicated) — same constant oidc.py keeps for its own continuation.
_LINE_LOGIN_PATH = "/api/public/auth/line/login"
# Where a LINE user with no employee row is sent to self-onboard (mirrors oidc).
_ONBOARD_PATH = "/qr-checkin/onboard"


def _escape(value: str) -> str:
    """Escape text for safe interpolation into the phone-side page markup."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _elevate_page(
    heading: str,
    message: str,
    *,
    status_code: int = 200,
    button_href: Optional[str] = None,
    button_text: str = "",
) -> HTMLResponse:
    """Render a minimal, self-contained phone-side page (no external assets).

    Mirrors the chromeless status pages of the OIDC flow (app/api/oidc.py),
    plus an optional LINE-green action button for the confirm step.
    """
    safe_heading = _escape(heading)
    safe_message = _escape(message)
    button = ""
    if button_href is not None:
        # button_href is app-constructed (a fixed path + a token we minted);
        # escape anyway so no future caller can break out of the attribute.
        button = (
            f'<a class="line-btn" href="{_escape(button_href)}">'
            f"{_escape(button_text)}</a>"
        )
    content = f"""<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>HF Portal</title>
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
        .line-btn {{
            display: block; margin-top: 24px; padding: 14px 24px;
            background: #06C755; color: #fff; text-decoration: none;
            border-radius: 8px; font-size: 16px; font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{safe_heading}</h1>
        <p>{safe_message}</p>
        {button}
    </div>
</body>
</html>"""
    return HTMLResponse(content=content, status_code=status_code)


def _expired_elevate_page() -> HTMLResponse:
    """The shared answer for an unknown, expired, or already-used QR."""
    return _elevate_page(
        "คิวอาร์โค้ดหมดอายุ",
        "QR นี้หมดอายุหรือถูกใช้ไปแล้ว กรุณากดสแกนใหม่ที่หน้าจอเครื่อง "
        "(This QR has expired or was already used — restart it on the "
        "kiosk screen.)",
        status_code=status.HTTP_404_NOT_FOUND,
    )


@public_router.get("/elevate/{ticket}")
async def elevate_confirm_page(ticket: str):
    """The page the kiosk QR opens on the employee's phone.

    Public and reader-secret-free (see the section header). Ships DARK (404)
    until READER_RESOLVE_SECRET is configured. Shows WHICH terminal is asking
    (the ticket's label) and a single LINE button that enters the stock LINE
    OAuth login with the ``elevate:<ticket>`` continuation hint. Unknown,
    expired, or already-used tickets get a friendly restart page (HTTP 404).
    """
    if not is_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    record = lookup_elevate_ticket(ticket)
    if record is None or record["status"] != "pending":
        return _expired_elevate_page()

    label = record["label"]
    where = f"เครื่อง {label}" if label else "เครื่องนี้"
    hint = urllib.parse.quote(f"elevate:{ticket}", safe="")
    return _elevate_page(
        f"เข้าสู่ระบบที่{where}",
        "ยืนยันตัวตนด้วย LINE เพื่อแสดงเครื่องมือของคุณบนหน้าจอเครื่องนี้ "
        "(Sign in with LINE to reveal your tools on this terminal.)",
        button_href=f"{_LINE_LOGIN_PATH}?redirect={hint}",
        button_text="เข้าสู่ระบบด้วย LINE",
    )


def continue_elevate_after_line(
    *,
    ticket_id: str,
    line_user_id: str,
    db: Session,
    display_name: Optional[str] = None,
    picture_url: Optional[str] = None,
):
    """Resume a kiosk elevation after LINE resolves ``line_user_id``.

    Called from the LINE OAuth callback (app/api/line_auth.py) via an additive
    hook, exactly like :func:`app.api.oidc.continue_oidc_after_line`. This is
    where the LINE Authenticator meets the card path's admission rule:

    * grants contain the ticket's app → park the SAME one-time card assertion
      /wait would mint (RS256, aud = the app grant key) and tell the person to
      look up at the kiosk screen.
    * active employee WITHOUT the grant → resolve the ticket as denied, so the
      kiosk's /elevate/wait answers 403 not_authorized — the exact semantics of
      a card tap without the grant.
    * unknown LINE user → onboarding redirect; inactive/pending employee → an
      "account not ready" page. In both cases the ticket STAYS pending (a card
      path parallel: /scan rejects those taps and the kiosk keeps waiting), so
      the right person can still scan the same QR.

    ``display_name``/``picture_url`` are the LINE profile fields the callback
    already holds; optional so an older caller still works, and used only to
    ride along in the onboarding hand-off token below.
    """
    ticket = lookup_elevate_ticket(ticket_id)
    if ticket is None or ticket["status"] != "pending":
        return _expired_elevate_page()

    employee = (
        db.query(Employee).filter(Employee.line_user_id == line_user_id).first()
    )

    # A valid LINE user with no employee row is a prospective new hire.
    #
    # Carries the resolved identity, exactly like oidc.py's continuation and
    # for the same two reasons: without ``jwt`` the page makes the user log
    # into LINE a second time, and without it onboard.html's localStorage
    # fallback would adopt whatever ``line_jwt_token`` the last person left
    # behind. That fallback matters most HERE — the kiosk elevate QR is aimed
    # at whatever browser is to hand, so "the last person on this device" is
    # the normal case, not the edge case. See
    # line_auth_service.onboarding_continuation_query for the ``src=line``
    # half of the guard.
    if employee is None:
        query = line_auth_service.onboarding_continuation_query(
            line_user_id,
            display_name=display_name,
            picture_url=picture_url,
        )
        return RedirectResponse(
            url=f"{_ONBOARD_PATH}?{query}", status_code=status.HTTP_302_FOUND
        )

    # Registered but not yet cleared for access.
    if employee.pending_approval or not employee.is_active:
        return _elevate_page(
            "บัญชียังไม่พร้อมใช้งาน",
            "บัญชีของคุณกำลังรอการอนุมัติ หรือถูกปิดการใช้งาน "
            "กรุณาติดต่อผู้ดูแลระบบ",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    apps = _grant_app_ids(db, employee.badge_number)
    if ticket["app"] not in apps:
        # Same admission rule as the card path's /wait: no grant → denied.
        resolve_elevate_ticket(ticket_id, authorized=False)
        return _elevate_page(
            "ไม่มีสิทธิ์ใช้งานเครื่องนี้",
            "บัญชีของคุณยังไม่มีสิทธิ์ใช้งานพอร์ทัลบนเครื่องนี้ "
            "กรุณาติดต่อผู้ดูแลระบบ (Your account does not hold the "
            "required app grant.)",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # Mint the identical artefact a card tap yields from /wait — one assertion
    # format, verified one way by the kiosk, whatever the Authenticator.
    assertion = oidc_service.mint_id_token(
        badge=employee.badge_number,
        email=oidc_service.synthetic_email_for_badge(employee.badge_number),
        name=employee.display_name,
        apps=apps,
        nonce=None,
        audience=ticket["app"],
    )
    if not resolve_elevate_ticket(ticket_id, authorized=True, assertion=assertion):
        # Raced by another completion or just expired — never overwrite.
        return _expired_elevate_page()

    label = ticket["label"]
    where = f"เครื่อง {label}" if label else "เครื่อง"
    return _elevate_page(
        "เข้าสู่ระบบสำเร็จ",
        f"สวัสดี {employee.display_name} — {where}กำลังแสดงเครื่องมือของคุณ "
        "กลับไปดูที่หน้าจอได้เลย (Signed in — look up at the kiosk screen.)",
    )
