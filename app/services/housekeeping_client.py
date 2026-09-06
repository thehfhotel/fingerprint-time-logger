"""Housekeeping internal client — the staff bot's read AND write side.

The staff bot (app/services/staff_bot.py) answers งานค้าง with a digest of the
open แจ้งซ่อม rows, and (phase 3) lets a linked employee raise, edit, cancel
and photograph a work order over LINE. Those rows live in the housekeeping
app, not here, so this module is the one place that talks to it:

    GET  {HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/digest
    POST {HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/work-orders
    POST {HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/work-orders/{id}/photos
    PATCH{HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/work-orders/{id}
    POST {HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/work-orders/{id}/cancel
    GET  {HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/work-orders/{id}
    GET  {HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/work-orders?reporter_badge=...
    Authorization: Bearer {HOUSEKEEPING_STAFF_BOT_TOKEN}

Server-to-server over the shared-nginx Docker network (default
``http://housekeeping:4070``) — no Cloudflare Access in the path, so a bearer
token stands in for it, exactly like PORTAL_DIRECTORY_URL/TOKEN in
app/services/manager_directory.py and GUEST_FEEDBACK_LINE_URL/SECRET in
staff_oa_service.py. Housekeeping answers 503 while ITS ``STAFF_BOT_INGRESS_TOKEN``
is unset, 401 on a wrong token.

FAIL CLOSED, and NEVER RAISE. An unset token means the feature is dark here
too: every function below returns None without dialing anything. The digest
read collapses EVERY failure mode — dark, timeout, connection error, non-2xx,
malformed JSON — to the same None, which the renderer turns into one fixed
Thai line ("ระบบงานซ่อมยังไม่เชื่อมต่อ ..."). The write/read-one calls below draw
one more distinction the digest does not need: a 4xx is housekeeping actively
REFUSING the request with a Thai reason worth relaying to the person who
tapped a button (validation, "not your ticket", "too late to cancel", ...),
so those come back as ``{"error": "<Thai message>"}`` instead of None; a 5xx,
a timeout or a malformed body is a MISS exactly like the digest's, and still
collapses to None. The bot must never leak an exception or an HTTP status
code into a LINE reply, and must never tell staff anything but plain Thai.

Env is read lazily via ``os.getenv`` on every call, the same convention as the
STAFF_OA_* secrets (registry comment in app/core/config.py) — an operator can
deliver the token and the next command picks it up without a restart.
"""

import logging
import os
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

# Container-to-container inside the shared-nginx network. Not a secret, and
# overridable so a local run can point somewhere else.
DEFAULT_HOUSEKEEPING_URL = "http://housekeeping:4070"

DIGEST_PATH = "/internal/staff-bot/digest"
WORK_ORDERS_PATH = "/internal/staff-bot/work-orders"

# Short: these calls sit between a LINE webhook event and a reply token that
# expires. A housekeeping app that is merely slow must cost us the reply, not
# make LINE retry the whole webhook delivery.
REQUEST_TIMEOUT_SECONDS = 5
# The photo upload carries the image bytes themselves; give it more room than
# the JSON calls above (same allowance the ticket asks for).
PHOTO_UPLOAD_TIMEOUT_SECONDS = 15

# The one line shown when housekeeping is dark/unreachable for a write or a
# read-one call — never a status code, never a raw exception.
_GENERIC_REFUSAL_TEXT = "ระบบแจ้งซ่อมยังไม่เชื่อมต่อ ลองใหม่อีกครั้งภายหลัง"


def get_internal_url() -> str:
    """Housekeeping's internal base URL (default: the docker-network name)."""
    return os.getenv("HOUSEKEEPING_INTERNAL_URL", "").strip() or DEFAULT_HOUSEKEEPING_URL


def get_staff_bot_token() -> str:
    """Bearer token for the digest endpoint (blank = dark)."""
    return os.getenv("HOUSEKEEPING_STAFF_BOT_TOKEN", "").strip()


def is_enabled() -> bool:
    """Whether the digest read is wired up at all (its token is set)."""
    return bool(get_staff_bot_token())


def fetch_digest() -> Optional[Dict]:
    """The open-แจ้งซ่อม digest, or None when it cannot be had.

    None covers every unhappy path on purpose — dark token, timeout, refused
    connection, 401/503 from housekeeping, a body that is not a JSON object —
    because the caller does exactly one thing with all of them (renders the
    fixed "not connected yet" Thai line). Never raises.
    """
    token = get_staff_bot_token()
    if not token:
        return None

    url = f"{get_internal_url().rstrip('/')}{DIGEST_PATH}"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — the bot degrades, never raises
        logger.warning("housekeeping digest unreachable: %s", exc)
        return None

    if response.status_code // 100 != 2:
        logger.warning(
            "housekeeping digest refused: HTTP %s", response.status_code
        )
        return None

    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 — malformed body is just another miss
        logger.warning("housekeeping digest returned a non-JSON body")
        return None

    if not isinstance(payload, dict):
        logger.warning("housekeeping digest returned %s, expected an object",
                       type(payload).__name__)
        return None
    return payload


# ---------------------------------------------------------------------------
# Ticket intake (phase 3) — same door, same token, one shared call helper
# ---------------------------------------------------------------------------

def _auth_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {get_staff_bot_token()}"}
    if extra:
        headers.update(extra)
    return headers


def _call(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict] = None,
    data: Optional[bytes] = None,
    extra_headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict] = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> Optional[Dict]:
    """One call against the internal door. Never raises.

    2xx with a JSON object body -> that body, verbatim (the caller reads
    whatever shape the route documents, e.g. ``{"order": {...}}``).
    4xx -> ``{"error": "<Thai message>"}`` — housekeeping's own reason when the
    body carries one, else the one fixed line above; this is the ONE case
    that is not a plain miss, because the person who tapped a button is owed
    an explanation.
    Anything else (token unset, 5xx, timeout, connection error, a body that
    is not a JSON object) -> None, exactly like :func:`fetch_digest`.
    """
    token = get_staff_bot_token()
    if not token:
        return None

    url = f"{get_internal_url().rstrip('/')}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=_auth_headers(extra_headers),
            json=json_body,
            data=data,
            params=params,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — the bot degrades, never raises
        logger.warning("housekeeping %s %s unreachable: %s", method, path, exc)
        return None

    if response.status_code // 100 == 2:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001 — malformed body is just another miss
            logger.warning("housekeeping %s %s returned a non-JSON body", method, path)
            return None
        if not isinstance(payload, dict):
            logger.warning(
                "housekeeping %s %s returned %s, expected an object",
                method, path, type(payload).__name__,
            )
            return None
        return payload

    if response.status_code // 100 == 4:
        message = _GENERIC_REFUSAL_TEXT
        try:
            body = response.json()
        except Exception:  # noqa: BLE001 — no Thai reason to relay, use the fallback
            body = None
        if isinstance(body, dict) and isinstance(body.get("error"), str) and body["error"].strip():
            message = body["error"]
        return {"error": message}

    logger.warning("housekeeping %s %s refused: HTTP %s", method, path, response.status_code)
    return None


def create_work_order(payload: Dict) -> Optional[Dict]:
    """POST /internal/staff-bot/work-orders — raise a ticket from the bot.

    ``payload`` is the body the ticket documents: ``{property, location_kind,
    room_no?, common_area?, category, urgent?, detail_text?,
    reporter:{badge,name}, source:"line-bot"}``. 201 body on success (an
    ``{"order": {...}}`` OrderView); ``{"error": ...}`` on a 400; None when
    housekeeping cannot be reached at all.
    """
    return _call("POST", WORK_ORDERS_PATH, json_body=payload)


def upload_photo(order_id, data: bytes, mime: str, actor_badge: str) -> Optional[Dict]:
    """POST .../work-orders/{id}/photos — raw image bytes, actor badge header.

    15 s timeout: this call carries the image bytes themselves, not just a
    JSON body. 201 ``{"photoId": ..., "photoCount": ...}`` on success;
    ``{"error": ...}`` on a 400/404/409 (unknown order, done/cancelled,
    wrong content type); None when housekeeping cannot be reached at all.
    """
    return _call(
        "POST", f"{WORK_ORDERS_PATH}/{order_id}/photos",
        data=data,
        extra_headers={"Content-Type": mime or "application/octet-stream",
                       "X-Actor-Badge": actor_badge},
        timeout=PHOTO_UPLOAD_TIMEOUT_SECONDS,
    )


def patch_work_order(order_id, fields: Dict, actor: Dict) -> Optional[Dict]:
    """PATCH .../work-orders/{id} — edit category/urgency/property/location.

    Only while the order is still ``new`` — housekeeping enforces that and
    answers 409 with its own Thai reason otherwise, which lands here as
    ``{"error": ...}``. 200 ``{"order": {...}}`` on success; None when
    housekeeping cannot be reached at all.
    """
    body = dict(fields)
    body["actor"] = actor
    return _call("PATCH", f"{WORK_ORDERS_PATH}/{order_id}", json_body=body)


def cancel_work_order(order_id, actor: Dict) -> Optional[Dict]:
    """POST .../work-orders/{id}/cancel — the reporter backs out within 10 min.

    200 ``{"order": {...}}`` on success; ``{"error": ...}`` for every 409 this
    route can answer (not the reporter, already started, too late); None when
    housekeeping cannot be reached at all.
    """
    return _call(
        "POST", f"{WORK_ORDERS_PATH}/{order_id}/cancel", json_body={"actor": actor},
    )


def get_work_order(order_id) -> Optional[Dict]:
    """GET .../work-orders/{id} — one ticket, to check authorship before an edit.

    200 ``{"order": {...}}`` on success; ``{"error": ...}`` on a 404 (unknown
    ticket); None when housekeeping cannot be reached at all.
    """
    return _call("GET", f"{WORK_ORDERS_PATH}/{order_id}")


def list_work_orders(reporter_badge: str, active: bool = True, limit: int = 10) -> Optional[Dict]:
    """GET .../work-orders?reporter_badge=...&active=...&limit=... — one
    reporter's tickets, newest first (phase 4's งานของฉัน).

    200 ``{"orders": [...]}`` on success; ``{"error": ...}`` on a 400 (a bad
    query); None when housekeeping cannot be reached at all.
    """
    return _call(
        "GET", WORK_ORDERS_PATH,
        params={
            "reporter_badge": reporter_badge,
            "active": "1" if active else "0",
            "limit": limit,
        },
    )
