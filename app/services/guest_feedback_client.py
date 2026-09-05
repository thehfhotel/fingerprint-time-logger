"""Guest-feedback internal client — the staff bot's guest-requests read side.

The staff bot (app/services/staff_bot.py) answers คำขอลูกค้า with the guest
requests waiting on a free LINE reply, and also auto-offers them into
ordinary staff-group chat. Those rows live in the guest-feedback app, not
here, so this module is the one place that talks to it:

    GET  {GUEST_FEEDBACK_BASE_URL}/api/internal/line/pending
         X-Reader-Secret: {GUEST_FEEDBACK_READER_SECRET}
    POST {GUEST_FEEDBACK_BASE_URL}/api/internal/line/delivered
         X-Reader-Secret: {GUEST_FEEDBACK_READER_SECRET}
         {"ids": [...], "method": "reply"}

Server-to-server over the shared-nginx Docker network (production:
``http://feedback:4080``) — no Cloudflare Access in the path, so a shared
secret stands in for it, the same shape as HOUSEKEEPING_INTERNAL_URL/TOKEN in
app/services/housekeeping_client.py. Design authority: guest-feedback
docs/CONTRACTS.md §15 rev 3 ("Guest requests → staff LINE — the Employee Hub
bot is the ONLY responder").

FAIL CLOSED, and NEVER RAISE. Either env unset means the feature is dark:
:func:`fetch_pending` returns None and :func:`confirm_delivered` returns
False without dialing anything. Every failure mode — dark, timeout,
connection error, non-2xx, malformed JSON — collapses to that same miss,
which the bot renders as one fixed Thai line
("ยังอ่านคำขอลูกค้าไม่ได้ค่ะ ลองใหม่อีกครั้ง"). Neither function ever logs the
guest's text — only counts, ids and outcomes.

Env is read lazily via ``os.getenv`` on every call, same convention as every
other secret in this repo (registry comment in app/core/config.py) — an
operator can deliver the values and the next command picks them up without a
restart. Unlike HOUSEKEEPING_INTERNAL_URL there is no built-in default: both
GUEST_FEEDBACK_BASE_URL and GUEST_FEEDBACK_READER_SECRET must be set, or the
feature stays dark.
"""

import logging
import os
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

PENDING_PATH = "/api/internal/line/pending"
DELIVERED_PATH = "/api/internal/line/delivered"

# Short: this call sits between a LINE webhook event/chat message and a reply
# token that expires. A guest-feedback app that is merely slow must cost us
# the requests read, not the reply.
REQUEST_TIMEOUT_SECONDS = 2


def get_base_url() -> str:
    """Guest-feedback's internal base URL (blank = dark, no default)."""
    return os.getenv("GUEST_FEEDBACK_BASE_URL", "").strip()


def get_reader_secret() -> str:
    """Shared secret for both endpoints (sent as ``X-Reader-Secret``)."""
    return os.getenv("GUEST_FEEDBACK_READER_SECRET", "").strip()


def is_enabled() -> bool:
    """Whether the guest-requests read is wired up at all (both env set)."""
    return bool(get_base_url()) and bool(get_reader_secret())


def fetch_pending() -> Optional[Dict]:
    """The pending guest-requests payload, or None when it cannot be had.

    None covers every unhappy path on purpose — either env blank, timeout,
    refused connection, non-2xx, a body that is not a JSON object — because
    the caller does exactly one thing with all of them (renders the fixed
    "can't read requests" Thai line). Never raises, never logs the guest's
    text: only the outcome.
    """
    base_url = get_base_url()
    secret = get_reader_secret()
    if not base_url or not secret:
        return None

    url = f"{base_url.rstrip('/')}{PENDING_PATH}"
    try:
        response = requests.get(
            url,
            headers={"X-Reader-Secret": secret},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — the bot degrades, never raises
        logger.warning("guest-feedback pending unreachable: %s", exc)
        return None

    if response.status_code // 100 != 2:
        logger.warning(
            "guest-feedback pending refused: HTTP %s", response.status_code
        )
        return None

    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 — malformed body is just another miss
        logger.warning("guest-feedback pending returned a non-JSON body")
        return None

    if not isinstance(payload, dict):
        logger.warning(
            "guest-feedback pending returned %s, expected an object",
            type(payload).__name__,
        )
        return None
    return payload


def confirm_delivered(ids: List[str]) -> bool:
    """Mark the given feedback ids delivered by LINE reply. Never raises.

    Only called after LINE has ACCEPTED a reply carrying those ids' text
    (staff_bot._reply), and only for a group/room reply — a 1:1 reply is a
    preview and must never confirm delivery. An empty ``ids`` dials nothing
    (there is nothing to confirm) and returns False, matching every other
    miss here.
    """
    base_url = get_base_url()
    secret = get_reader_secret()
    if not base_url or not secret or not ids:
        return False

    url = f"{base_url.rstrip('/')}{DELIVERED_PATH}"
    try:
        response = requests.post(
            url,
            headers={"X-Reader-Secret": secret},
            json={"ids": list(ids), "method": "reply"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — the bot degrades, never raises
        logger.warning("guest-feedback delivered-confirm unreachable: %s", exc)
        return False

    if response.status_code // 100 != 2:
        logger.warning(
            "guest-feedback delivered-confirm refused: HTTP %s",
            response.status_code,
        )
        return False
    return True
