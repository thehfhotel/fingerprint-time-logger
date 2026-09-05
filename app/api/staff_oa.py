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

Since 2026-09-05 this webhook is ALSO the staff bot's front door
(``HF ภายใน``): ``message``/``postback``/``join`` events are routed into
app/services/staff_bot.py, which debounces them and answers with a free reply
token. Follow handling is byte-for-byte what it was; the bot never pushes, and
non-command chat is discarded before anything is logged.

The bot is also the ONLY responder for guest requests raised on the public
guest-feedback site (guest-feedback docs/CONTRACTS.md §15 rev 3): it reads
and confirms them from guest-feedback itself
(app/services/guest_feedback_client.py) rather than guest-feedback holding
any LINE credentials or relaying events here. The event-forwarding relay this
webhook used to run (PR #28/#30) is retired along with it.

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
from app.services import staff_bot, staff_oa_menu, staff_oa_service

logger = logging.getLogger(__name__)

router = APIRouter()

# One short reply for not-yet-onboarded followers. Replies are free (no
# push quota) and only sent for this one event, so the OA stays quiet.
#
# The string itself moved to app/services/staff_bot.py on 2026-09-05, because
# the bot sends the SAME text to a stranger who opens a 1:1 chat and the two
# must never drift apart. Re-exported here under its original name: this is
# still where the follow path reads it, and the text is unchanged.
ONBOARDING_REPLY_TEXT = staff_bot.ONBOARDING_REPLY_TEXT


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
    """LINE Messaging API webhook: follow events + the staff bot."""
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

    # Staff bot (HF ภายใน): message/postback/join events become debounced,
    # free replies. Nothing is sent from inside this request — the bot waits
    # for the chat to go quiet — so this loop only files intent, and a
    # failure in it must not change the 200 LINE is waiting for.
    commands = 0
    for event in events:
        try:
            handled_event = staff_bot.handle_event_detail(event, db)
        except Exception:  # noqa: BLE001 — keep the webhook green per event
            logger.exception("staff-bot event handling failed")
            continue
        if handled_event.command:
            commands += 1

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
        "bot_commands": commands,
    }
