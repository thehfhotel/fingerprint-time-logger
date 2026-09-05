"""Staff LINE OA webhook — Employee Hub follow-event handler (2026-07).

LINE calls POST /api/public/staff-oa/webhook whenever something happens on
the dedicated staff Official Account. We only act on ``follow`` events
(employee adds/re-adds the OA as a friend):

  * LINE userId matches an active employee's ``line_user_id`` → link that
    employee's Role Menu (grant-driven rich menu, per-user link API). An
    employee whose variant has no buttons at all — since 2026-08-14 that is
    anyone without the ``housekeeping`` grant, see the MENU_BUTTONS comment
    in app/services/staff_oa_menu.py — is linked to nothing, deliberately.
  * unknown userId → link the channel's base/default menu if one exists
    (with an empty base there is none) and reply once with a short Thai
    pointer to the Q-badge onboarding flow that links LINE accounts to the
    employee registry.

Everything else used to be dropped on the floor. Since 2026-09-05 GROUP
events (``message``/``join``/``memberJoined``/``leave`` with a ``group``
source) are ALSO forwarded, fire-and-forget, to the guest-feedback app —
LINE allows one Official Account per group chat, so the staff group hosts
this OA and guest-feedback has to be fed second-hand. Follow handling is
untouched by that, the forward is dark unless GUEST_FEEDBACK_LINE_URL is
set, and it can neither delay nor fail the response (see
staff_oa_service.forward_group_events_in_background). No message text and
no user/room event ever leaves this app.

FAIL CLOSED: the endpoint answers 503 until both STAFF_OA_* secrets are
configured (see app/core/config.py), and every request must carry a valid
``X-Line-Signature`` (HMAC of the raw body with the channel secret).
Event processing is best-effort per event — a LINE API hiccup on one event
never turns the webhook response into an error (LINE would retry and the
channel could wedge on a poison event).
"""

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee
from app.services import staff_oa_menu, staff_oa_service

logger = logging.getLogger(__name__)

router = APIRouter()

# One short reply for not-yet-onboarded followers. Replies are free (no
# push quota) and only sent for this one event, so the OA stays quiet.
ONBOARDING_REPLY_TEXT = (
    "ยินดีต้อนรับสู่ HF Employee Hub\n"
    "บัญชี LINE นี้ยังไม่ได้เชื่อมกับทะเบียนพนักงาน "
    "กรุณาสแกน QR บนป้ายพนักงาน (Q-badge) ของคุณ หรือเปิด "
    "https://erp.thehfhotel.org/qr-checkin/onboard "
    "เพื่อเชื่อมบัญชี แล้วเมนูเครื่องมือของคุณจะปรากฏที่นี่"
)


def _require_enabled() -> None:
    """503 while the staff OA is not configured (feature dark)."""
    if not staff_oa_service.is_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Staff OA is not configured",
        )


def _handle_follow_event(db: Session, event: dict) -> None:
    """Link the right menu for one follower; reply to strangers."""
    line_user_id = (event.get("source") or {}).get("userId", "")
    if not line_user_id:
        return

    employee = (
        db.query(Employee)
        .filter(
            Employee.line_user_id == line_user_id,
            Employee.is_active == True,  # noqa: E712
        )
        .first()
    )

    if employee:
        staff_oa_service.link_role_menu_for_line_user(db, line_user_id)
        return

    # Unknown follower: pin the base menu explicitly (when there is one) and
    # point them at the Q-badge onboarding flow so their LINE account gets
    # linked.
    #
    # Since the 2026-08-14 maid-only re-scope there IS no base menu: every
    # remaining button is gated on the `housekeeping` grant, so the `base`
    # variant has zero buttons and the sync deliberately deploys nothing for
    # it (see base_has_buttons in scripts/staff_oa_sync.py). A stranger
    # therefore gets no rich menu — correct, they are not staff — and the
    # reply below is the whole of what they get, which is why it must still
    # be sent on this path. Distinguish the two reasons the menu is missing:
    # "the variant has no buttons" is the designed state and only worth an
    # info line, while "base has buttons but nothing is deployed" really does
    # mean the sync has not run and an operator should act.
    deployed = staff_oa_service.deployed_menu_ids_by_key()
    base_menu_id = deployed.get("base")
    if base_menu_id:
        staff_oa_service.link_rich_menu_to_user(line_user_id, base_menu_id)
    elif not staff_oa_menu.buttons_for(frozenset()):
        logger.info(
            "Unknown follower gets no rich menu: the base variant is empty "
            "by design (maid-only Hub). Sending the onboarding reply only."
        )
    else:
        logger.warning(
            "No deployed base staff-hub menu to link for unknown follower — "
            "run scripts/staff_oa_sync.py --apply"
        )

    reply_token = event.get("replyToken")
    if reply_token:
        staff_oa_service.reply_text_message(reply_token, ONBOARDING_REPLY_TEXT)


@router.post("/webhook")
async def staff_oa_webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """LINE Messaging API webhook: follow events + group-event forwarding."""
    _require_enabled()

    body = await request.body()
    if not staff_oa_service.verify_webhook_signature(body, x_line_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    try:
        events = json.loads(body.decode("utf-8")).get("events", [])
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook body",
        )
    if not isinstance(events, list):
        events = []

    # Relay group events to guest-feedback BEFORE the follow loop: they carry
    # the same short-lived reply token LINE hands us, and the loop below makes
    # blocking LINE API calls. Fire-and-forget on a daemon thread — it cannot
    # raise, cannot block, and never touches the follow path.
    #
    # The URL check is here as well as inside the forwarder so that a dark
    # deployment does nothing at all (no reduction, no thread) and so the
    # count reported below means "actually dispatched", not "would have been".
    forwarded: list = []
    if staff_oa_service.get_guest_feedback_line_url():
        forwarded = [
            payload
            for payload in (
                staff_oa_service.group_event_forward_payload(event)
                for event in events
            )
            if payload is not None
        ]
        if forwarded:
            staff_oa_service.forward_group_events_in_background(forwarded)

    handled = 0
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "follow":
            continue
        try:
            _handle_follow_event(db, event)
            handled += 1
        except Exception:  # noqa: BLE001 — keep the webhook green per event
            logger.exception("staff-oa follow event handling failed")

    return {
        "status": "ok",
        "follow_events_handled": handled,
        "group_events_forwarded": len(forwarded),
    }
