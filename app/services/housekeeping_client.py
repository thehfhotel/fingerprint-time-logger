"""Housekeeping internal client — the staff bot's read side.

The staff bot (app/services/staff_bot.py) answers งานค้าง with a digest of the
open แจ้งซ่อม rows. Those rows live in the housekeeping app, not here, so this
module is the one place that talks to it:

    GET {HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/digest
    Authorization: Bearer {HOUSEKEEPING_STAFF_BOT_TOKEN}

Server-to-server over the shared-nginx Docker network (default
``http://housekeeping:4070``) — no Cloudflare Access in the path, so a bearer
token stands in for it, exactly like PORTAL_DIRECTORY_URL/TOKEN in
app/services/manager_directory.py and GUEST_FEEDBACK_LINE_URL/SECRET in
staff_oa_service.py. Housekeeping answers 503 while ITS ``STAFF_BOT_INGRESS_TOKEN``
is unset, 401 on a wrong token.

FAIL CLOSED, and NEVER RAISE. An unset token means the feature is dark here
too: :func:`fetch_digest` returns None without dialing anything. Every failure
mode — dark, timeout, connection error, non-2xx, malformed JSON — collapses to
the same None, which the renderer turns into one fixed Thai line
("ระบบงานซ่อมยังไม่เชื่อมต่อ ..."). The bot must never leak an exception into a
LINE reply, and must never tell staff anything but plain Thai.

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

# Short: this call sits between a LINE webhook event and a reply token that
# expires. A housekeeping app that is merely slow must cost us the digest, not
# the reply.
REQUEST_TIMEOUT_SECONDS = 5


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
