"""
Estate manager directory — the source of truth for "is this email an admin".

WHY THIS EXISTS
---------------
The admin allowlist for Cloudflare Access auto-login used to be six manager
emails hardcoded in ``cf_access_service._DEFAULT_ADMIN_EMAILS``. ``CF_ADMIN_EMAILS``
could override it, but that variable is not carried in the deploy payload (and
is not even plumbed through docker-compose), so production always ran the
in-code list. When a manager is added to — or removed from — the "HF Managers"
Cloudflare Access tier via the HF Portal Access menu, that change never reached
this app: a new manager signed in with no admin rights, a removed one kept them
until somebody edited source and redeployed.

The portal now publishes that membership at
``GET /portal-api/directory/managers`` (bearer auth, 60s cached, fail-closed
with 503 rather than serving an empty or stale list). This module consumes it.

LAYERS (in resolution order)
----------------------------
1. HARD FLOOR — ``PROTECTED_ADMIN`` is an admin in code, mirroring the portal's
   own ``PROTECTED_MANAGER`` break-glass convention (src/server/access.ts).
   A directory that omits the owner — a bad membership edit, a portal
   regression, a half-applied tier change — must never lock him out of the
   console that repairs it. This holds whenever the live directory is in play,
   and the static floor below also contains him, so every dark/broken state
   admits him too.
2. LIVE SNAPSHOT — a background-refreshed copy of the portal's manager list.
   Replaced only by a 200 carrying a NON-EMPTY list; every other outcome
   (401, 503, timeout, malformed body, empty list) keeps the last known-good
   set. Dormant when ``PORTAL_DIRECTORY_TOKEN`` is unset — estate convention is
   "empty env = feature off".
3. FLOOR — when no live snapshot has ever been obtained, exactly today's
   behaviour: ``CF_ADMIN_EMAILS`` if set, else the in-code manager list.
   Deliberately kept, not deleted: it is what keeps this app working when the
   portal is down, unreachable, or not yet configured.

An explicit ``CF_ADMIN_EMAILS`` is the operator's manual control and still
replaces the floor wholesale, including the protected owner, exactly as it does
today. That knob is a deliberate local act by someone already on the host; it is
not a state the directory or a remote edit can put this app into.

HOT PATH
--------
``is_admin_email`` does ZERO network I/O: it reads one module-level frozenset.
The refresher is a plain daemon thread — it must never touch the database, the
asyncio event loop, or the ZKTeco device lock (all device access in this app
serializes behind a single threading.Lock, and an APScheduler already runs
here; adding contention to either would be a real outage risk). The swap is a
single assignment of an immutable frozenset, so a reader sees either the whole
old set or the whole new one, never a partial one, and no lock is needed on
read.

Access FAILS CLOSED at every layer: any unresolvable state falls back to a
narrower, known-good allowlist, never to "allow everyone".
"""
import logging
import os
import threading
from typing import FrozenSet, Optional

import requests

logger = logging.getLogger(__name__)


def _parse_admin_emails_env(raw: str) -> tuple:
    """Comma-separated env value -> normalized (lowercased, stripped) tuple.

    Empty/unset input yields an empty tuple — there is no in-code default
    any more; the floor is entirely operator-configured.
    """
    return tuple(
        item.strip().lower() for item in raw.split(",") if item.strip()
    )


def _manager_admin_emails() -> tuple:
    """
    The operator-configured manager/admin floor: MANAGER_ADMIN_EMAILS
    (comma-separated, lower-cased, stripped), empty tuple when unset. Read
    fresh from the environment on every call — same "operator change takes
    effect without a restart" convention as ``_floor_emails``'s
    ``CF_ADMIN_EMAILS`` and ``_directory_token``/``_directory_url`` below. No
    emails are hardcoded in source any more; configure this in the deploy
    environment.
    """
    return _parse_admin_emails_env(os.getenv("MANAGER_ADMIN_EMAILS", ""))


def _protected_admin() -> str:
    """
    Owner account that must never lose admin access — the break-glass path
    back in if a membership edit, a policy rename, or a portal outage would
    otherwise leave nobody able to repair it. Mirrors PROTECTED_MANAGER in
    the portal's src/server/access.ts. The first configured manager email is
    the break-glass owner; '' (matches nothing — see ``_normalize``) when
    MANAGER_ADMIN_EMAILS is unset entirely.
    """
    emails = _manager_admin_emails()
    return emails[0] if emails else ""


def __getattr__(name):
    """
    PEP 562 module ``__getattr__``: keep ``PROTECTED_ADMIN`` and
    ``STATIC_ADMIN_EMAILS`` available as public, live, env-driven attributes
    (e.g. ``manager_directory.PROTECTED_ADMIN``) without caching them at
    import time — a test's ``monkeypatch.setenv("MANAGER_ADMIN_EMAILS", ...)``
    takes effect on the very next read, no module reload required. Code
    inside this module calls ``_protected_admin()``/``_manager_admin_emails()``
    directly instead of the bare names, since module-level bytecode does not
    route through ``__getattr__``.
    """
    if name == "PROTECTED_ADMIN":
        return _protected_admin()
    if name == "STATIC_ADMIN_EMAILS":
        return _manager_admin_emails()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Server-to-server over the shared-nginx Docker network — no Cloudflare Access
# in the path, so no bypass token is needed. Not a secret; overridable so a
# local/dev run can point somewhere else.
DEFAULT_DIRECTORY_URL = "http://hf-erp-portal:3000/portal-api/directory/managers"

# Short timeout: this runs off the hot path, but a hung portal must not pin a
# thread for minutes. Refresh cadence matches the portal endpoint's own 60s
# cache — asking faster only burns Cloudflare reads.
DIRECTORY_TIMEOUT_SECONDS = 2.0
REFRESH_INTERVAL_SECONDS = 60.0

# ── mutable module state ──────────────────────────────────────────────────────
# _snapshot: None means "no live directory data has EVER been obtained" (which
# selects the floor). Once set it is only ever replaced by a whole new
# frozenset — never mutated in place — so readers need no lock.
_snapshot: Optional[FrozenSet[str]] = None

# Last logged health state, so a persistent failure logs once instead of every
# 60s cycle, and a recovery is announced. Written only by the refresher thread.
_last_state: Optional[str] = None

_refresher: Optional[threading.Thread] = None
# Stop signal for the CURRENT refresher generation. Each start gets a fresh
# Event, so stopping one generation can never accidentally un-stop another.
_refresher_stop = threading.Event()
_refresher_lock = threading.Lock()


# ── config ────────────────────────────────────────────────────────────────────
def _directory_token() -> str:
    """Bearer token for the portal directory. Empty means dormant."""
    return os.getenv("PORTAL_DIRECTORY_TOKEN", "").strip()


def _directory_url() -> str:
    return os.getenv("PORTAL_DIRECTORY_URL", "").strip() or DEFAULT_DIRECTORY_URL


def directory_enabled() -> bool:
    """Whether the live directory is wired up at all (its token is set)."""
    return bool(_directory_token())


def _normalize(email) -> str:
    """Lowercase + trim. Non-strings normalize to '' (which never matches)."""
    if not isinstance(email, str):
        return ""
    return email.strip().lower()


def _floor_emails() -> FrozenSet[str]:
    """
    Exactly the pre-directory allowlist: CF_ADMIN_EMAILS if set, else the
    in-code list. Read from the environment on every call, as before, so an
    operator change takes effect without a restart.
    """
    raw = os.getenv("CF_ADMIN_EMAILS", "").strip()
    source = raw.split(",") if raw else _manager_admin_emails()
    return frozenset(_normalize(item) for item in source if _normalize(item))


def live_snapshot() -> Optional[FrozenSet[str]]:
    """The current live manager set, or None if one has never been obtained."""
    return _snapshot


# ── health logging (once per state change, not once per cycle) ────────────────
def _note_state(state: str, message: str) -> None:
    """
    Log a refresher outcome only when it differs from the last one.

    The estate alerting rule is: only page on confirmed failures, suppress
    self-recovering blips, and pair every failure with a recovery notice. A
    portal restart that costs one refresh cycle should not produce a log line
    every minute forever, and a recovery should be visible.
    """
    global _last_state
    previous = _last_state
    if state == previous:
        return
    _last_state = state
    if state == "ok":
        if previous is None:
            logger.info(message)
        else:
            logger.info(f"manager directory recovered: {message}")
    else:
        logger.warning(message)


# ── the single network call ───────────────────────────────────────────────────
def _http_get(url: str, headers: dict, timeout: float):
    """
    Sole network call in this module, isolated so tests replace it wholesale
    and never dial out.
    """
    return requests.get(url, headers=headers, timeout=timeout)


def _refresh_once() -> bool:
    """
    Fetch the directory once and, only on a good answer, swap the snapshot in.

    Returns True when the snapshot was replaced. Never raises: every failure
    mode keeps the last known-good set (or the floor, if there never was one).
    """
    token = _directory_token()
    if not token:
        return False

    url = _directory_url()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    try:
        response = _http_get(url, headers, DIRECTORY_TIMEOUT_SECONDS)
    except Exception as exc:
        _note_state("unreachable", f"manager directory unreachable at {url}: {exc}")
        return False

    status = getattr(response, "status_code", None)
    if status != 200:
        # 401 = our token is wrong/revoked, 503 = the portal could not read
        # Cloudflare. Both mean "no trustworthy answer", never "no managers".
        _note_state(f"http-{status}", f"manager directory returned HTTP {status}; keeping the current admin set")
        return False

    try:
        payload = response.json()
    except Exception as exc:
        _note_state("malformed", f"manager directory returned an unparseable body: {exc}")
        return False

    managers = payload.get("managers") if isinstance(payload, dict) else None
    if not isinstance(managers, list):
        _note_state("malformed", "manager directory response had no managers list; keeping the current admin set")
        return False

    emails = frozenset(_normalize(item) for item in managers if _normalize(item))
    if not emails:
        # Defence in depth. The portal already refuses to serve an empty list
        # (it 503s instead), so a 200 with zero managers can only be a
        # regression there — accepting it would lock every manager out at once.
        _note_state("empty", "manager directory returned an empty manager list; ignoring it and keeping the current admin set")
        return False

    global _snapshot
    _snapshot = emails  # atomic single assignment of an immutable set
    _note_state("ok", f"manager directory refreshed: {len(emails)} managers from {url}")
    return True


def _refresh_loop(stop: threading.Event) -> None:
    """Refresh now, then every REFRESH_INTERVAL_SECONDS, until told to stop."""
    while not stop.is_set():
        try:
            _refresh_once()
        except Exception as exc:  # pragma: no cover — _refresh_once swallows its own
            _note_state("crashed", f"manager directory refresh crashed: {exc}")
        if not _directory_token():
            return  # went dormant; _ensure_refresher_started will restart it if it comes back
        stop.wait(REFRESH_INTERVAL_SECONDS)


def _ensure_refresher_started() -> None:
    """
    Start the background refresher on first use. Cheap and non-blocking: the
    caller never waits for HTTP, it just gets the floor until the first
    snapshot lands (typically well under a second later).
    """
    if not _directory_token():
        return  # dormant — empty env = feature off
    global _refresher, _refresher_stop
    if _refresher is not None and _refresher.is_alive():
        return
    with _refresher_lock:
        if _refresher is not None and _refresher.is_alive():
            return
        stop = threading.Event()
        _refresher_stop = stop
        thread = threading.Thread(
            target=_refresh_loop, args=(stop,), name="manager-directory-refresh", daemon=True
        )
        _refresher = thread
        thread.start()


# ── the hot path ──────────────────────────────────────────────────────────────
def is_admin_email(email) -> bool:
    """
    Whether a Cloudflare-verified email belongs to an admin of this app.

    Case-insensitive and whitespace-tolerant. Performs NO network I/O: it reads
    one in-memory frozenset. Called on every guarded request, so keep it that
    way.
    """
    normalized = _normalize(email)
    if not normalized:
        return False

    _ensure_refresher_started()

    snapshot = _snapshot  # single read — see the module docstring on atomicity
    if snapshot is not None:
        return normalized == _protected_admin() or normalized in snapshot
    return normalized in _floor_emails()


# ── test-only helpers ─────────────────────────────────────────────────────────
def reset_for_tests() -> None:
    """Stop the refresher and clear all cached state. Test-only."""
    global _snapshot, _last_state, _refresher
    _refresher_stop.set()  # signals this generation only; the next start makes a new Event
    thread = _refresher
    if thread is not None and thread.is_alive():
        thread.join(timeout=5.0)
    _refresher = None
    _snapshot = None
    _last_state = None


def set_snapshot_for_tests(emails) -> None:
    """Install a live snapshot without any HTTP. Test-only."""
    global _snapshot
    _snapshot = None if emails is None else frozenset(_normalize(e) for e in emails if _normalize(e))
