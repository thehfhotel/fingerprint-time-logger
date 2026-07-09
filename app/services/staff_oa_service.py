"""Staff LINE OA (Employee Hub) service — credentials, signature, LINE API.

The Employee Hub lives on a dedicated staff LINE Official Account
(Messaging API channel). This module owns:

  * the channel credentials (``STAFF_OA_CHANNEL_ACCESS_TOKEN`` /
    ``STAFF_OA_CHANNEL_SECRET``, read lazily via ``os.getenv`` like every
    other secret in this repo — see the registry in app/core/config.py).
    Both unset/blank ⇒ the whole feature is DARK: the webhook answers 503
    and the sync script refuses to run. Zero behavior change until the OA
    exists and its secrets are delivered.
  * webhook signature verification (HMAC-SHA256 of the raw body with the
    channel secret, base64, constant-time compare — LINE's scheme).
  * a thin LINE Messaging API client (rich-menu CRUD, per-user linking,
    bulk linking, reply messages) used by the webhook and the sync script.
  * :func:`link_role_menu_for_line_user` — the one-user relink helper the
    follow-event webhook uses today and grant-change hooks can call later.
"""

import base64
import hashlib
import hmac
import logging
import os
from typing import Dict, Iterable, List, Optional, Sequence, Set

import requests
from sqlalchemy.orm import Session

from app.models.models import Employee, EmployeeAppGrant
from app.services import staff_oa_menu

logger = logging.getLogger(__name__)

LINE_API_BASE = "https://api.line.me"
LINE_DATA_API_BASE = "https://api-data.line.me"
_REQUEST_TIMEOUT_SECONDS = 15
# LINE's bulk link endpoint caps userIds per request.
BULK_LINK_CHUNK_SIZE = 500


# ---------------------------------------------------------------------------
# Credentials (read lazily from the environment, never via pydantic Settings)
# ---------------------------------------------------------------------------

def get_channel_access_token() -> str:
    """Long-lived Messaging API token for the staff OA (blank = dark)."""
    return os.getenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", "").strip()


def get_channel_secret() -> str:
    """Messaging API channel secret for webhook signatures (blank = dark)."""
    return os.getenv("STAFF_OA_CHANNEL_SECRET", "").strip()


def is_enabled() -> bool:
    """Whether the Employee Hub surface is configured (fail closed)."""
    return bool(get_channel_access_token()) and bool(get_channel_secret())


# ---------------------------------------------------------------------------
# Webhook signature (https://developers.line.biz/en/reference/messaging-api/#signature-validation)
# ---------------------------------------------------------------------------

def verify_webhook_signature(body: bytes, signature: Optional[str]) -> bool:
    """Validate ``X-Line-Signature`` against the raw request body."""
    secret = get_channel_secret()
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature.strip())


# ---------------------------------------------------------------------------
# LINE Messaging API client (rich menus + replies)
# ---------------------------------------------------------------------------

class StaffOaApiError(RuntimeError):
    """A LINE Messaging API call failed (non-2xx)."""

    def __init__(self, operation: str, status_code: int, body: str):
        super().__init__(f"{operation} failed: HTTP {status_code} {body[:300]}")
        self.operation = operation
        self.status_code = status_code


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_channel_access_token()}"}


def _check(operation: str, response: requests.Response) -> requests.Response:
    if response.status_code // 100 != 2:
        raise StaffOaApiError(operation, response.status_code, response.text)
    return response


def get_rich_menu_list() -> List[Dict]:
    """All rich menus on the channel (GET /v2/bot/richmenu/list)."""
    response = _check("list rich menus", requests.get(
        f"{LINE_API_BASE}/v2/bot/richmenu/list",
        headers=_auth_headers(), timeout=_REQUEST_TIMEOUT_SECONDS,
    ))
    return response.json().get("richmenus", [])


def create_rich_menu(payload: Dict) -> str:
    """Create a rich menu; returns its richMenuId."""
    response = _check("create rich menu", requests.post(
        f"{LINE_API_BASE}/v2/bot/richmenu",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json=payload, timeout=_REQUEST_TIMEOUT_SECONDS,
    ))
    return response.json()["richMenuId"]


def upload_rich_menu_image(rich_menu_id: str, png_bytes: bytes) -> None:
    """Attach the menu image (POST to the data API host)."""
    _check("upload rich menu image", requests.post(
        f"{LINE_DATA_API_BASE}/v2/bot/richmenu/{rich_menu_id}/content",
        headers={**_auth_headers(), "Content-Type": "image/png"},
        data=png_bytes, timeout=_REQUEST_TIMEOUT_SECONDS,
    ))


def delete_rich_menu(rich_menu_id: str) -> None:
    _check("delete rich menu", requests.delete(
        f"{LINE_API_BASE}/v2/bot/richmenu/{rich_menu_id}",
        headers=_auth_headers(), timeout=_REQUEST_TIMEOUT_SECONDS,
    ))


def set_default_rich_menu(rich_menu_id: str) -> None:
    """Make this menu the channel default (what un-linked users see)."""
    _check("set default rich menu", requests.post(
        f"{LINE_API_BASE}/v2/bot/user/all/richmenu/{rich_menu_id}",
        headers=_auth_headers(), timeout=_REQUEST_TIMEOUT_SECONDS,
    ))


def get_default_rich_menu_id() -> Optional[str]:
    """The channel's current default rich menu id, or None when unset."""
    response = requests.get(
        f"{LINE_API_BASE}/v2/bot/user/all/richmenu",
        headers=_auth_headers(), timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return None
    _check("get default rich menu", response)
    return response.json().get("richMenuId")


def link_rich_menu_to_user(line_user_id: str, rich_menu_id: str) -> None:
    """Link one user to a rich menu (per-user Role Menu)."""
    _check("link rich menu to user", requests.post(
        f"{LINE_API_BASE}/v2/bot/user/{line_user_id}/richmenu/{rich_menu_id}",
        headers=_auth_headers(), timeout=_REQUEST_TIMEOUT_SECONDS,
    ))


def bulk_link_rich_menu(line_user_ids: Sequence[str], rich_menu_id: str) -> None:
    """Link many users to one menu, chunked to LINE's per-request cap."""
    for start in range(0, len(line_user_ids), BULK_LINK_CHUNK_SIZE):
        chunk = list(line_user_ids[start:start + BULK_LINK_CHUNK_SIZE])
        _check("bulk link rich menu", requests.post(
            f"{LINE_API_BASE}/v2/bot/richmenu/bulk/link",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json={"richMenuId": rich_menu_id, "userIds": chunk},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ))


def reply_text_message(reply_token: str, text: str) -> None:
    """Reply to a webhook event (replies don't consume the push quota)."""
    _check("reply message", requests.post(
        f"{LINE_API_BASE}/v2/bot/message/reply",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    ))


# ---------------------------------------------------------------------------
# Role-menu resolution + per-user (re)link
# ---------------------------------------------------------------------------

def grants_for_badge(db: Session, badge_number: str) -> Set[str]:
    """The employee's granted app_ids (all of them; the menu model filters)."""
    rows = (
        db.query(EmployeeAppGrant.app_id)
        .filter(EmployeeAppGrant.employee_badge_number == badge_number)
        .all()
    )
    return {app_id for (app_id,) in rows}


def employee_menu_assignments(db: Session) -> Dict[str, List[str]]:
    """menu-variant key -> [line_user_id, ...] for every active employee
    with a linked LINE account. The distinct keys returned here are exactly
    the Role Menu variants that must exist on the channel (plus ``base``,
    the channel default for not-yet-linked followers).
    """
    employees = (
        db.query(Employee.badge_number, Employee.line_user_id)
        .filter(Employee.line_user_id.isnot(None), Employee.is_active == True)  # noqa: E712
        .all()
    )
    grants_by_badge: Dict[str, Set[str]] = {}
    rows = (
        db.query(EmployeeAppGrant.employee_badge_number, EmployeeAppGrant.app_id)
        .all()
    )
    for badge, app_id in rows:
        grants_by_badge.setdefault(badge, set()).add(app_id)

    assignments: Dict[str, List[str]] = {}
    for badge, line_user_id in employees:
        key = staff_oa_menu.menu_key(grants_by_badge.get(badge, set()))
        assignments.setdefault(key, []).append(line_user_id)
    return assignments


def deployed_menu_ids_by_key(rich_menus: Optional[Iterable[Dict]] = None) -> Dict[str, str]:
    """Map menu-variant key -> richMenuId for the staff-hub menus currently
    deployed on the channel. Names carry the key (``staffhub:<key>:<sig>``);
    when duplicates exist (mid-sync), the last one listed wins.
    """
    if rich_menus is None:
        rich_menus = get_rich_menu_list()
    mapping: Dict[str, str] = {}
    for menu in rich_menus:
        name = menu.get("name", "")
        if not staff_oa_menu.is_staff_hub_menu_name(name):
            continue
        parts = name.split(":")
        if len(parts) >= 2:
            mapping[parts[1]] = menu.get("richMenuId", "")
    return mapping


def link_role_menu_for_line_user(db: Session, line_user_id: str) -> Optional[str]:
    """Link ``line_user_id`` to the Role Menu their grants call for.

    The relink primitive: the follow-event webhook calls it when an employee
    (re)adds the staff OA, and future grant-change hooks can call it so a
    changed grant set takes effect without a full sync. Returns the linked
    menu-variant key, or None when nothing could be linked (feature dark,
    unknown user, or that variant's menu not deployed yet — run the sync
    script). Never raises for "user not found": unknown followers simply
    keep the channel-default menu.
    """
    if not is_enabled():
        return None

    employee = (
        db.query(Employee)
        .filter(Employee.line_user_id == line_user_id, Employee.is_active == True)  # noqa: E712
        .first()
    )
    if not employee:
        return None

    grants = grants_for_badge(db, employee.badge_number)
    key = staff_oa_menu.menu_key(grants)
    deployed = deployed_menu_ids_by_key()
    rich_menu_id = deployed.get(key)
    if not rich_menu_id:
        logger.warning(
            "No deployed staff-hub rich menu for variant %r (badge=%s) — "
            "run scripts/staff_oa_sync.py --apply", key, employee.badge_number,
        )
        return None

    link_rich_menu_to_user(line_user_id, rich_menu_id)
    logger.info(
        "Linked staff-hub menu %r to badge=%s", key, employee.badge_number
    )
    return key
