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
  * a thin LINE Messaging API client (rich-menu CRUD, the channel default,
    per-user linking, bulk link/unlink, reply messages, and the one metered
    call — ``multicast_text_message``) used by the webhook, the sync script
    and the housekeeping escalation (app/services/hk_escalation_service.py).
  * :func:`link_role_menu_for_line_user` — the one-user relink helper the
    follow-event webhook uses today and grant-change hooks can call later.
  * the guest-feedback forwarder (``GUEST_FEEDBACK_LINE_*``, dark when the
    URL is empty): the staff LINE GROUP can only host one Official Account,
    so group events this webhook receives are relayed to the guest-feedback
    app, which replies into the group with this same OA's token. Since
    2026-09-05 1:1 ``message`` events are relayed too, reduced to their ids
    (no text), so an allowlisted manager can preview the pending requests in
    private — guest-feedback holds that allowlist, not this app.
"""

import base64
import hashlib
import hmac
import logging
import os
import threading
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
# LINE's multicast endpoint caps recipients per request the same way.
MULTICAST_CHUNK_SIZE = 500


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


def clear_default_rich_menu() -> None:
    """Unset the channel default (DELETE /v2/bot/user/all/richmenu).

    The mirror image of :func:`get_default_rich_menu_id` — same path, same
    resource, opposite verb — and it treats 404 the same way that GET does,
    for the same reason: "there is no channel default" is the state this
    call exists to reach, so finding it already reached is success, not an
    error. Clearing an absent default must therefore never raise
    StaffOaApiError; a sync that aborted on it would leave the channel
    half-synced over a no-op.

    Called by scripts/staff_oa_sync.py when the ``base`` variant has no
    buttons (see the MENU_BUTTONS comment in staff_oa_menu): there is no
    base menu to be the default, and leaving the default pointed at the old
    one is worse than useless once the stale-menu sweep deletes it.
    """
    response = requests.delete(
        f"{LINE_API_BASE}/v2/bot/user/all/richmenu",
        headers=_auth_headers(), timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return
    _check("clear default rich menu", response)


def link_rich_menu_to_user(line_user_id: str, rich_menu_id: str) -> None:
    """Link one user to a rich menu (per-user Role Menu)."""
    _check("link rich menu to user", requests.post(
        f"{LINE_API_BASE}/v2/bot/user/{line_user_id}/richmenu/{rich_menu_id}",
        headers=_auth_headers(), timeout=_REQUEST_TIMEOUT_SECONDS,
    ))


def unlink_rich_menu_from_user(line_user_id: str) -> None:
    """Drop one user's per-user Role Menu link, so they fall back to the
    channel default (or to no menu at all, which is the state since the
    Hub became maid-only — see the MENU_BUTTONS comment in staff_oa_menu).

    A 404 means there was no link to remove, which is the outcome we
    wanted; treat it as success rather than an error, the same way
    get_default_rich_menu_id() treats an absent default as None.
    """
    response = requests.delete(
        f"{LINE_API_BASE}/v2/bot/user/{line_user_id}/richmenu",
        headers=_auth_headers(), timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return
    _check("unlink rich menu from user", response)


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


def bulk_unlink_rich_menu(line_user_ids: Sequence[str]) -> None:
    """Unlink many users from whatever menu they hold, chunked like the link.

    POST /v2/bot/richmenu/bulk/unlink takes ONLY ``userIds`` — there is no
    richMenuId in the body, unlike :func:`bulk_link_rich_menu`, because the
    operation is "this user should have no per-user menu" rather than
    "detach this specific menu". The chunking is identical (LINE caps
    userIds per request the same way on both endpoints), so the two stay
    side by side and change together.

    Empty input is a no-op by construction: ``range(0, 0, chunk)`` is empty,
    so no request fires. That matters — LINE rejects an empty userIds array,
    and the caller (scripts/staff_oa_sync.py) reaches this with whatever the
    ``base`` variant happened to hold, which is routinely nobody.
    """
    for start in range(0, len(line_user_ids), BULK_LINK_CHUNK_SIZE):
        chunk = list(line_user_ids[start:start + BULK_LINK_CHUNK_SIZE])
        _check("bulk unlink rich menu", requests.post(
            f"{LINE_API_BASE}/v2/bot/richmenu/bulk/unlink",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json={"userIds": chunk},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ))


def multicast_text_message(line_user_ids: Sequence[str], text: str) -> None:
    """Push ONE text message to many users (POST /v2/bot/message/multicast).

    The only METERED call in this module — LINE counts a push per recipient,
    which is precisely why the housekeeping escalation that uses it is bounded
    on both sides (new-hotel ADR 0008: one push per signal, monthly cap; HF ID:
    on-duty maids only, never a fallback audience). Rich-menu CRUD, linking and
    webhook replies above all cost zero.

    Chunked at LINE's per-request recipient cap, exactly like
    :func:`bulk_link_rich_menu`. Empty input is a no-op by construction
    (``range(0, 0, chunk)`` is empty) — LINE rejects an empty ``to`` array, and
    "nobody to tell" must never become an API error.
    """
    for start in range(0, len(line_user_ids), MULTICAST_CHUNK_SIZE):
        chunk = list(line_user_ids[start:start + MULTICAST_CHUNK_SIZE])
        _check("multicast message", requests.post(
            f"{LINE_API_BASE}/v2/bot/message/multicast",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json={"to": chunk, "messages": [{"type": "text", "text": text}]},
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


def reply_messages(reply_token: str, messages: Sequence[Dict]) -> None:
    """Reply with up to 5 message objects — text, Flex, whatever LINE takes.

    The generic form of :func:`reply_text_message`, added for the staff bot
    (app/services/staff_bot.py), which answers one debounced burst with a
    palette bubble and/or a digest text in a SINGLE reply. Still a reply, so
    still free at any chat size — the whole feature rides this call rather
    than any push (hf-erp ADR: LINE meters pushes per recipient).

    Sliced to LINE's five-object cap rather than trusting the caller: a reply
    LINE rejects wholesale is worse than a reply missing its last bubble, and
    the caller is a debouncer that COALESCES commands, so growing past five is
    exactly the failure mode to expect. An empty list is a no-op — LINE
    rejects an empty ``messages`` array, and "nothing to say" must not become
    an API error (same rule as the empty-audience guards above).
    """
    payload = list(messages)[:5]
    if not payload:
        return
    _check("reply messages", requests.post(
        f"{LINE_API_BASE}/v2/bot/message/reply",
        headers={**_auth_headers(), "Content-Type": "application/json"},
        json={"replyToken": reply_token, "messages": payload},
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
    unknown user, that employee's variant has no buttons at all, or that
    variant's menu is not deployed yet — run the sync script). Never raises
    for "user not found": unknown followers simply keep whatever the channel
    default is.
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

    # A variant with NO buttons has no rich menu to link, and must not be
    # quietly handed some OTHER variant's menu — that would show an employee
    # tools their grants do not cover. Since the 2026-08-14 maid-only
    # re-scope, `base` is exactly that variant: every remaining button needs
    # the `housekeeping` grant, so a non-maid follower legitimately gets no
    # Employee Hub menu at all (see the MENU_BUTTONS comment in
    # staff_oa_menu). Degrade to None, quietly and without raising — this
    # runs inside the follow webhook, where an exception is caught and
    # logged as a failure per event, and this is not a failure. Deliberately
    # NOT the warning below: nothing is missing, nothing needs an operator,
    # and a "run the sync script" line here would fire for every non-maid
    # who ever adds the OA.
    if not staff_oa_menu.buttons_for(grants):
        # ACTIVELY unlink rather than merely declining to link. Returning
        # early would leave a PREVIOUS link in place, and the case that
        # matters is a demoted maid: her `housekeeping` grant is revoked,
        # she re-adds the OA before anyone runs the sync, and she would keep
        # a menu of maid tiles her grants no longer cover. The targets stay
        # Access-gated so this is not privilege escalation — it is worse in
        # the way this Hub keeps getting bitten, a button that opens a
        # Cloudflare block page. Unlinking here makes a refollow self-heal
        # instead of waiting for the next --apply.
        unlink_rich_menu_from_user(line_user_id)
        logger.info(
            "No staff-hub menu for variant %r (badge=%s) — that variant has "
            "no buttons; unlinked this user's rich menu",
            key, employee.badge_number,
        )
        return None

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


# ---------------------------------------------------------------------------
# Guest-feedback forwarder — LINE events out to the guest-feedback app
# ---------------------------------------------------------------------------
#
# LINE allows exactly ONE Official Account per group chat. The staff group
# already hosts THIS OA (the Employee Hub), so the guest-feedback app
# (feedback.thehfhotel.org) cannot also be invited and cannot get its own
# webhook for that group. Instead this webhook forwards the group events it
# does not itself handle, and guest-feedback replies into the group with the
# Staff OA's token. See guest-feedback docs/CONTRACTS.md §15.4.
#
# Since 2026-09-05 the same relay also carries 1:1 `message` events, reduced
# to their ids (guest-feedback §15.5): an allowlisted manager can ask the OA
# privately for the pending guest requests instead of pulling the whole staff
# group into a test. The ALLOWLIST LIVES ON THE FAR SIDE — this app forwards
# every 1:1 message id-only and knows nothing about who may preview.
#
# Deliberately narrow, and narrower still for a 1:1: `group` sources forward
# the four event types below, `user` sources forward ONLY `message`, and a
# multi-person `room` forwards nothing at all. No message text ever crosses,
# no userId ever crosses for a group event, and `follow`/`unfollow` stay
# entirely inside the Employee Hub (app/api/staff_oa.py) — a userId reaching
# guest-feedback means "this person messaged the OA directly", nothing more.

# Event types guest-feedback acts on: `join`/`memberJoined` learn the group,
# `leave` forgets it, `message` is the free reply window for pending rows.
FORWARDED_GROUP_EVENT_TYPES = frozenset({"message", "join", "memberJoined", "leave"})

# 1:1 chats forward ONE type. `follow`/`unfollow` are the Employee Hub's own
# (they link Role Menus and are answered here), `postback` is a Hub menu tap,
# and neither is any of guest-feedback's business — a private preview needs a
# message and a reply window, nothing else.
FORWARDED_USER_EVENT_TYPES = frozenset({"message"})

# Short on purpose: this runs off the webhook path and the only thing a slow
# peer may cost us is a background thread, never LINE's 200.
_FORWARD_TIMEOUT_SECONDS = 2


def get_guest_feedback_line_url() -> str:
    """Guest-feedback's internal LINE-event endpoint (blank = dark).

    Production: ``http://feedback:4080/api/internal/line/event`` — container
    to container over the shared-nginx Docker network, no Cloudflare Access
    in the path. Blank/unset ⇒ nothing is ever forwarded.
    """
    return os.getenv("GUEST_FEEDBACK_LINE_URL", "").strip()


def get_guest_feedback_line_secret() -> str:
    """Shared secret for that endpoint (sent as ``X-Reader-Secret``)."""
    return os.getenv("GUEST_FEEDBACK_LINE_SECRET", "").strip()


def group_event_forward_payload(
    event: Dict, *, withhold_reply_token: bool = False,
) -> Optional[Dict]:
    """Reduce ONE webhook event to what guest-feedback gets, or None.

    Named for the group relay it started as (2026-09-05); it now reduces the
    two shapes guest-feedback accepts, which are NOT the same payload:

      group  → ``{type, replyToken, timestamp, groupId, channel}``
      1:1    → ``{type, replyToken, timestamp, userId, groupId: None, channel}``

    A group event never carries the speaker's userId (staff chatter stays
    here); a 1:1 event carries the userId precisely because it IS the
    identity guest-feedback checks against its preview allowlist, and carries
    ``groupId: None`` to say "answer this person, do not touch the group".
    Neither carries ``message.text``, ever.

    None means "not forwardable": a `room` source, a source with no id, or an
    event type guest-feedback does not act on for that source — above all
    `follow`/`unfollow`, which belong to the Employee Hub alone.

    ``withhold_reply_token`` — a LINE reply token is single-use. When the
    staff bot (app/services/staff_bot.py) has claimed this event's token for
    its own debounced reply, the payload still crosses (guest-feedback keeps
    learning the group, or the id) but with ``replyToken: None``: "no reply
    window on this one, wait for the next message". Exactly one consumer per
    token. NOTE this bites hardest in a 1:1, where the bot answers every text
    message it is sent and therefore claims nearly every 1:1 token — see
    docs/EMPLOYEE_HUB_SETUP.md.
    """
    if not isinstance(event, dict):
        return None
    source = event.get("source")
    if not isinstance(source, dict):
        return None
    source_type = source.get("type")
    event_type = event.get("type")
    reply_token = None if withhold_reply_token else event.get("replyToken")

    if source_type == "group":
        if event_type not in FORWARDED_GROUP_EVENT_TYPES:
            return None
        group_id = source.get("groupId")
        if not group_id:
            return None
        return {
            "type": event_type,
            "replyToken": reply_token,
            "timestamp": event.get("timestamp"),
            "groupId": group_id,
            "channel": "staff-oa",
        }

    if source_type == "user":
        if event_type not in FORWARDED_USER_EVENT_TYPES:
            return None
        user_id = source.get("userId")
        if not user_id:
            return None
        return {
            "type": event_type,
            "replyToken": reply_token,
            "timestamp": event.get("timestamp"),
            "userId": user_id,
            "groupId": None,
            "channel": "staff-oa",
        }

    # `room` (multi-person chat, no group id) and anything LINE invents next.
    return None


def forward_group_events(payloads: Sequence[Dict]) -> None:
    """POST each reduced payload to guest-feedback. NEVER raises.

    Group and 1:1 payloads travel the same way — one POST each, same URL,
    same header, same timeout; only :func:`group_event_forward_payload`
    knows the difference between them.

    Dark (and silent) while ``GUEST_FEEDBACK_LINE_URL`` is empty. Every
    failure — connect error, timeout, non-2xx — is logged and swallowed:
    this is a best-effort side channel, and the webhook it hangs off must
    answer LINE 200 regardless (see :func:`forward_group_events_in_background`,
    which is how the webhook actually calls this).
    """
    url = get_guest_feedback_line_url()
    if not url:
        return
    headers = {"X-Reader-Secret": get_guest_feedback_line_secret()}
    for payload in payloads:
        try:
            response = requests.post(
                url, json=payload, headers=headers,
                timeout=_FORWARD_TIMEOUT_SECONDS,
            )
            if response.status_code // 100 != 2:
                logger.warning(
                    "guest-feedback rejected forwarded %s event: HTTP %s %s",
                    payload.get("type"), response.status_code,
                    getattr(response, "text", "")[:200],
                )
        except Exception as exc:  # noqa: BLE001 — best-effort side channel
            logger.warning(
                "Forwarding %s event to guest-feedback failed: %s",
                payload.get("type"), exc,
            )


def forward_group_events_in_background(payloads: Sequence[Dict]) -> None:
    """Fire-and-forget :func:`forward_group_events` on a daemon thread.

    A plain thread rather than FastAPI ``BackgroundTasks``: Starlette runs
    background tasks inside the same ASGI call, so a peer that is merely SLOW
    (up to the 2 s timeout, per event) would still push out the moment LINE
    sees its 200. LINE retries a delivery it considers failed, so the webhook
    response must not depend on a second app being up at all. Volume is a
    handful of events per delivery, so a thread per delivery is cheap.

    Returns immediately, and never raises — even spawning the thread is
    guarded, so an exhausted thread pool cannot fail the webhook either.
    """
    if not payloads or not get_guest_feedback_line_url():
        return
    try:
        threading.Thread(
            target=forward_group_events,
            args=(list(payloads),),
            name="staff-oa-guest-feedback-forward",
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 — never fail the webhook
        logger.warning("Could not start guest-feedback forward thread: %s", exc)
