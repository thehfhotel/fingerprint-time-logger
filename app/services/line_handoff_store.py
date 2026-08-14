"""Same-browser LINE completion hand-off — the ticket store.

WHAT THIS IS FOR
----------------
A password-less staff LINE account reaching a Cloudflare-Access-gated app from
a NON-LINE mobile browser (Safari/Chrome — a scanned QR, a link opened outside
LINE, a bookmark) has no LINE login screen it can complete. The long block
comment in :func:`app.api.line_auth.line_login` records why both obvious
parameter fixes are wrong; the fix this module supports is the third one:

    keep auto login ON, let LINE finish in its own in-app browser, and have the
    ORIGINAL browser tab poll a server-side ticket until the LINE side resolves
    — then complete the Cloudflare Access redirect IN THE TAB THAT HOLDS THE
    ACCESS SESSION.

That removes the cookie-jar problem instead of routing around it: the Access
session was started in Safari, so the Access callback must be navigated in
Safari, and nothing about which browser LINE happens to finish in matters any
more.

This is the same shape the kiosk already runs (app/api/reader.py's
``/elevate/start`` + ``/elevate/wait`` long-poll, resolved by
``continue_elevate_after_line``) and the same store conventions as
oidc_service's login tickets: a module-level dict guarded by a lock, TTL +
prune, deliver-once pops. Safe because the app runs a SINGLE uvicorn worker
(Dockerfile CMD has no ``--workers``; docker-compose runs one container). If
the app ever scales to multiple workers this store must move to SQLite/Redis,
exactly like the reader and OIDC stores.

THE SECURITY MODEL — READ BEFORE CHANGING ANYTHING HERE
-------------------------------------------------------
The invariant this module exists to hold:

    Completing a LINE login must only ever yield a session to the browser that
    STARTED that specific flow.

Two independent secrets, deliberately travelling on different legs:

* ``ticket_id`` — rides the LINE round trip. It is stored ONLY inside
  line_auth_service's server-side ``_state_storage`` (as the ``handoff:<id>``
  redirect hint keyed by LINE's random ``state``), so it never appears in a URL,
  a page body, a Referer header or a log line. The LINE side needs it to say
  "this flow resolved to this person".
* ``holder_secret`` — NEVER leaves the originating browser. It is set at start
  in an HttpOnly, SameSite=Strict, Secure cookie and is the ONLY thing that can
  release the completed session.

The cookie is the right binder precisely because of the bug we are working
around: LINE's in-app browser is a SEPARATE COOKIE JAR. The leg of this flow
that runs through LINE structurally cannot carry the cookie — not "does not",
*cannot* — and JS cannot read it either (HttpOnly), so it cannot be relayed
through the LINE page. Possession of the cookie therefore proves "I am the tab
that started this", which is the exact property the Access redirect needs.

Threats, and where each dies:

1. OBSERVES a ticket (shoulder-surf, shared device, logs, Referer). The ticket
   id is not rendered anywhere and not logged (see the logging note below), but
   even a full leak buys nothing: :func:`take_resolved` refuses to release the
   parked identity without the holder secret, which lives only in the
   originating browser's HttpOnly cookie jar. An observer polling with a
   correct id and no/other secret is indistinguishable from an unknown ticket.
2. GUESSES / brute-forces. ``ticket_id`` is 192 bits and ``holder_secret`` 256
   bits of ``secrets`` entropy, and both must match. The secret is compared
   with :func:`hmac.compare_digest`, and a wrong secret is answered exactly
   like a wrong id (None), so nothing distinguishes "close" from "wrong".
   :data:`MAX_CONCURRENT_WAITERS` bounds how many long-polls an attacker can
   park while trying.
3. FIXATION — plants a ticket and induces a victim to complete into it. This is
   the one the cookie does NOT solve on its own: the attacker holds the cookie
   for their OWN ticket, so if a victim's LINE login can be steered onto that
   ticket, the attacker's tab is the "originating browser" and wins. The
   mitigation here is :func:`resolve_ticket`'s client-IP binding — the LINE
   completion must arrive from the same client IP that started the ticket. The
   legitimate flow is same-phone (Safari and LINE's in-app browser share one
   egress IP seconds apart), so this holds for real users and breaks a remote
   attacker. It does NOT stop an attacker sharing the victim's egress IP; see
   the honest limits note at the bottom of this docstring.
4. RACE between two pollers on the same ticket. :func:`take_resolved` pops
   under the lock, so a resolved ticket is delivered to at most one caller —
   the deliver-once posture of reader.py's ``take_resolved_elevate_ticket``.
   :func:`resolve_ticket` is likewise a one-way pending -> resolved transition,
   so a second LINE completion can never overwrite the first.

Deliberately NOT logged: ticket ids, cookie values, holder secrets. Threat 1 is
"an attacker who OBSERVES a ticket", and application logs are one of the places
things get observed (shipped to an aggregator, read by an operator, pasted into
a bug report). Counters and outcomes are logged; identifiers are not.

HONEST LIMITS (also reported to the caller, not buried here)
------------------------------------------------------------
* The IP binding in threat 3 is a corroborating signal, not proof. Attacker and
  victim behind ONE NAT — a hotel staff wifi is exactly that — share an egress
  IP, and the binding passes. What actually closes cross-context fixation is a
  user-visible code shown in the originating tab and entered on the LINE side
  (RFC 8628 §5.4 shape); that was rejected here because the audience is 80+
  year old housekeeping staff on a single phone, for whom retyping a code
  between two browsers is a worse dead end than the one being fixed.
* The residual is NOT introduced by this module. Any party can already call the
  public ``/oidc/authorize`` with the registered client_id + redirect_uri, get a
  LINE authorize URL, and phish it; ``disable_auto_login`` is no defence against
  that because an attacker assembling their own authorize URL simply omits the
  parameter. The hand-off adds an IP check to that path where there was none.
"""

import hmac
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Constants — TTLs, budgets and caps
# ============================================================================

# How long the whole hand-off may take, start to completion. Bounds the wait
# for a maid who wanders off: after this the ticket is gone and the polling
# page shows its Thai retry path (see static/line-handoff.html).
#
# Sized to sit INSIDE oidc_service.LOGIN_TICKET_TTL_SECONDS (600s) so a retry
# within the budget can still reuse the same, still-valid OIDC login ticket
# rather than dead-ending on an expired inner request.
HANDOFF_TICKET_TTL_SECONDS = 300  # 5 minutes

# One long-poll slice. The browser re-polls until its own overall deadline, so
# this only controls how often a connection is recycled — not how long the user
# may take. Same 25s/0.5s pair (and the same env-override-for-fast-tests trick)
# as reader.py's /wait and /elevate/wait.
WAIT_TIMEOUT_SECONDS_DEFAULT = 25.0
WAIT_TICK_SECONDS_DEFAULT = 0.5

# Bound the store against an attacker minting tickets in a loop. At ~300 bytes
# a ticket this is trivial memory, but an unbounded dict on a public endpoint
# is a memory-exhaustion primitive, so it gets a ceiling. Over the cap,
# create_ticket returns None and the caller falls back to the guidance
# interstitial — i.e. degrades to today's proven behaviour, never to an error.
MAX_TICKETS = 500

# Bound how many long-poll connections may be parked at once. Only a cookie
# holder can park one (a bad cookie is answered immediately), but cookies are
# free to mint, so the ceiling is what keeps a single-process uvicorn from
# having its connection budget consumed by parked waiters. Over the cap the
# endpoint answers immediately with a retry-after; the page treats that as
# "poll again shortly", not as a failure.
MAX_CONCURRENT_WAITERS = 32

# The HttpOnly cookie that binds a ticket to the browser that started it.
# Value format: "<ticket_id>.<holder_secret>". Both halves live in the cookie
# and NOWHERE else on the browser side, so no ticket identifier is ever put in
# a URL, a page body or a log line (see threat 1 in the module docstring).
# ``secrets.token_urlsafe`` emits only [A-Za-z0-9_-], so "." is an unambiguous
# separator.
COOKIE_NAME = "hf_line_handoff"
# Scoped to the LINE auth surface: the only endpoint that must ever receive
# this cookie is the wait long-poll. Nothing else in the app should see it.
COOKIE_PATH = "/api/public/auth/line"

_TICKET_ID_BYTES = 24   # 192 bits
_HOLDER_SECRET_BYTES = 32  # 256 bits


# ============================================================================
# Feature gate
# ============================================================================

def is_enabled() -> bool:
    """Whether the same-browser hand-off is live.

    Ships DARK — off unless ``LINE_SAME_BROWSER_HANDOFF`` is explicitly truthy.
    That is this repo's posture for every new authority surface (reader.py and
    oidc_service both 404 until their secret is configured), and it is worth
    more than usual here: this replaces a login path that 80+ year old
    housekeeping staff depend on, so the interim guidance interstitial stays
    reachable by flipping one environment variable, with no redeploy and no
    code change. With the flag unset every existing path — including the
    guidance interstitial — behaves byte-identically to before this module
    existed.
    """
    return os.getenv("LINE_SAME_BROWSER_HANDOFF", "false").strip().lower() in (
        "1", "true", "yes",
    )


def wait_timeout_seconds() -> float:
    """One long-poll slice budget (env-overridable so tests don't wait 25s)."""
    try:
        return float(
            os.getenv("LINE_HANDOFF_WAIT_TIMEOUT_SECONDS", "")
            or WAIT_TIMEOUT_SECONDS_DEFAULT
        )
    except ValueError:
        return WAIT_TIMEOUT_SECONDS_DEFAULT


def wait_tick_seconds() -> float:
    """Poll interval inside one long-poll slice (env-overridable for tests)."""
    try:
        return float(
            os.getenv("LINE_HANDOFF_WAIT_TICK_SECONDS", "")
            or WAIT_TICK_SECONDS_DEFAULT
        )
    except ValueError:
        return WAIT_TICK_SECONDS_DEFAULT


def ticket_ttl_seconds() -> float:
    """Total hand-off budget (env-overridable so expiry tests are instant)."""
    try:
        return float(
            os.getenv("LINE_HANDOFF_TICKET_TTL_SECONDS", "")
            or HANDOFF_TICKET_TTL_SECONDS
        )
    except ValueError:
        return float(HANDOFF_TICKET_TTL_SECONDS)


# ============================================================================
# Store (single-worker; guarded by a lock, TTL + prune)
# ============================================================================

_store_lock = threading.Lock()
# ticket_id -> {
#     "holder_secret", "inner_hint", "client_ip", "status",
#     "line_user_id", "display_name", "picture_url", "expires_at",
# }
_tickets: Dict[str, Dict[str, Any]] = {}
# Count of long-polls currently parked in the wait endpoint (see
# MAX_CONCURRENT_WAITERS). Guarded by the same lock as the ticket store.
_waiters = 0


# Resolve outcomes, returned to the LINE-side continuation so it can render the
# right Thai page. Strings rather than an enum to match the plain-dict idiom the
# reader/oidc stores already use.
RESOLVE_OK = "resolved"
RESOLVE_UNKNOWN = "unknown"          # absent, expired, or never existed
RESOLVE_ALREADY = "already_resolved"  # never overwrite a first completion
RESOLVE_IP_MISMATCH = "ip_mismatch"   # threat 3 — see module docstring


@dataclass(frozen=True)
class NewTicket:
    """What :func:`create_ticket` hands back.

    ``ticket_id`` goes into the LINE redirect hint (server-side only);
    ``cookie_value`` goes into the HttpOnly cookie and nowhere else.
    """

    ticket_id: str
    cookie_value: str


def _prune_locked(now: float) -> None:
    """Drop expired tickets. Must hold ``_store_lock``."""
    for ticket_id in [k for k, v in _tickets.items() if v["expires_at"] <= now]:
        _tickets.pop(ticket_id, None)


def create_ticket(*, inner_hint: str, client_ip: str) -> Optional[NewTicket]:
    """Start a hand-off; return the ticket id + the cookie value, or None.

    ``inner_hint`` is the redirect hint this hand-off WRAPS — always the
    ``oidc:<login-ticket>`` hint that /oidc/authorize handed to the LINE login.
    It is kept server-side so the completion can resume the real OIDC
    continuation later, in the originating browser.

    ``client_ip`` is recorded for the fixation check in :func:`resolve_ticket`.

    None means "the store is at its ceiling" (:data:`MAX_TICKETS`) — a
    capacity answer, not an error. The caller falls back to the guidance
    interstitial, which is today's behaviour, so a flood degrades this path to
    the status quo instead of breaking it.
    """
    now = time.time()
    ticket_id = secrets.token_urlsafe(_TICKET_ID_BYTES)
    holder_secret = secrets.token_urlsafe(_HOLDER_SECRET_BYTES)

    with _store_lock:
        _prune_locked(now)
        if len(_tickets) >= MAX_TICKETS:
            logger.warning(
                "LINE hand-off ticket store at capacity (%d) — falling back to "
                "the guidance interstitial",
                MAX_TICKETS,
            )
            return None
        _tickets[ticket_id] = {
            "holder_secret": holder_secret,
            "inner_hint": inner_hint,
            "client_ip": client_ip or "",
            "status": "pending",
            "line_user_id": None,
            "display_name": None,
            "picture_url": None,
            "expires_at": now + ticket_ttl_seconds(),
        }

    return NewTicket(ticket_id=ticket_id, cookie_value=f"{ticket_id}.{holder_secret}")


def resolve_ticket(
    ticket_id: str,
    *,
    line_user_id: str,
    display_name: Optional[str],
    picture_url: Optional[str],
    client_ip: str,
) -> str:
    """Park a resolved LINE identity against a pending ticket (one-way).

    Called from the LINE side — i.e. from LINE's in-app browser, the leg that
    by construction holds no cookie of ours. It therefore parks an IDENTITY
    only; it never mints, releases or returns anything a session could be built
    from. Everything that turns this into a session happens later, in
    :func:`take_resolved`, behind the holder-secret check.

    Two guards, both deliberate:

    * ``status != "pending"`` -> :data:`RESOLVE_ALREADY`. A second LINE
      completion against the same ticket can never overwrite the first (the
      deliver-once posture of reader.py's ``resolve_elevate_ticket``).
    * ``client_ip`` must match the IP that started the ticket, else
      :data:`RESOLVE_IP_MISMATCH` and the ticket STAYS PENDING — the identity
      is simply discarded. This is the fixation defence (threat 3): the
      legitimate hand-off is same-phone, so Safari and LINE's in-app browser
      present the same egress IP seconds apart, while an attacker who planted a
      ticket from their own device cannot make a victim's LINE completion
      arrive from that device's IP. Leaving the ticket pending rather than
      failing it means an attacker who somehow learns a ticket id still cannot
      even DoS the real user's flow, and the real user can complete afterwards.
    """
    now = time.time()
    with _store_lock:
        record = _tickets.get(ticket_id)
        if record is None or record["expires_at"] <= now:
            return RESOLVE_UNKNOWN
        if record["status"] != "pending":
            return RESOLVE_ALREADY
        if not hmac.compare_digest(record["client_ip"], client_ip or ""):
            # No ticket identifier in the log line — see the logging note in
            # the module docstring.
            logger.warning(
                "LINE hand-off completion refused: client IP does not match "
                "the browser that started the flow"
            )
            return RESOLVE_IP_MISMATCH

        record["status"] = "resolved"
        record["line_user_id"] = line_user_id
        record["display_name"] = display_name
        record["picture_url"] = picture_url

    return RESOLVE_OK


def _split_cookie(cookie_value: Optional[str]) -> Optional[tuple]:
    """Split a ``<ticket_id>.<holder_secret>`` cookie, or None if malformed."""
    if not cookie_value or "." not in cookie_value:
        return None
    ticket_id, _, holder_secret = cookie_value.partition(".")
    if not ticket_id or not holder_secret:
        return None
    return ticket_id, holder_secret


def _authenticated_record_locked(cookie_value: Optional[str], now: float):
    """Ticket for this cookie, or None. Must hold ``_store_lock``.

    "Unknown ticket", "expired ticket", "malformed cookie" and "wrong holder
    secret" all collapse to the SAME None. A caller must not be able to tell a
    real ticket id with a bad secret from a made-up one — that distinction is
    the oracle a brute-forcer (threat 2) would need.
    """
    parts = _split_cookie(cookie_value)
    if parts is None:
        return None
    ticket_id, holder_secret = parts
    record = _tickets.get(ticket_id)
    if record is None or record["expires_at"] <= now:
        return None
    if not hmac.compare_digest(record["holder_secret"], holder_secret):
        return None
    return ticket_id, record


def peek(cookie_value: Optional[str]) -> Optional[str]:
    """Status of the ticket this cookie owns: "pending"/"resolved", else None.

    Read-only, cookie-authenticated. Used once before the long-poll loop so an
    unknown/expired/foreign ticket is answered immediately instead of parking a
    connection for 25 seconds (that also keeps threat 2's brute-forcer from
    using the wait endpoint as a slow-drip connection sink).
    """
    now = time.time()
    with _store_lock:
        found = _authenticated_record_locked(cookie_value, now)
        if found is None:
            return None
        return found[1]["status"]


def take_resolved(cookie_value: Optional[str]) -> Optional[Dict[str, Any]]:
    """Pop-and-return a RESOLVED ticket, iff the cookie proves ownership.

    This is the single gate the whole design rests on. It returns the parked
    LINE identity — the raw material for a session — and it returns it ONLY to
    a caller presenting the holder secret from the cookie set on the browser
    that started the flow. Pending tickets stay put (the long-poll keeps
    watching); unknown/expired/foreign cookies get None.

    Popping under the lock makes delivery once-only, which settles threat 4: if
    two tabs of the same browser (they share the cookie) race, exactly one gets
    the identity and the other sees an unknown ticket and renders the retry
    path. Two sessions can never be minted from one LINE completion.
    """
    now = time.time()
    with _store_lock:
        found = _authenticated_record_locked(cookie_value, now)
        if found is None:
            return None
        ticket_id, record = found
        if record["status"] != "resolved":
            return None
        _tickets.pop(ticket_id, None)
    return dict(record)


def try_acquire_waiter() -> bool:
    """Reserve one of the :data:`MAX_CONCURRENT_WAITERS` long-poll slots."""
    global _waiters
    with _store_lock:
        if _waiters >= MAX_CONCURRENT_WAITERS:
            return False
        _waiters += 1
        return True


def release_waiter() -> None:
    """Give back a long-poll slot. Always call from a ``finally``."""
    global _waiters
    with _store_lock:
        if _waiters > 0:
            _waiters -= 1


def active_waiters() -> int:
    """Currently parked long-polls (observability + tests)."""
    with _store_lock:
        return _waiters


def reset_state() -> None:
    """Clear the store and the waiter counter (test isolation only)."""
    global _waiters
    with _store_lock:
        _tickets.clear()
        _waiters = 0
