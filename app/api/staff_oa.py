"""Staff LINE OA webhook — Employee Hub follow-event handler (2026-07).

LINE calls POST /api/public/staff-oa/webhook whenever something happens on
the dedicated staff Official Account. Follow events link the right rich menu,
and verified leave events are claimed before the general staff bot.
"""

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee
from app.services import (staff_bot, staff_leave, staff_leave_palette,
                          staff_oa_menu, staff_oa_service)
from app.api.staff_leave import image_router
from app.api.deployment_ready import router as deployment_ready_router

logger = logging.getLogger(__name__)

# Extend the default "HF ภายใน • มีอะไรให้ช่วยคะ" palette with แจ้งลา.
staff_leave_palette.install(staff_bot)

router = APIRouter()
router.include_router(image_router)
router.include_router(deployment_ready_router)

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


def _leave_palette_event(event: object) -> dict | None:
    """Translate our palette postback into the same private flow as ``แจ้งลา``.

    The button deliberately uses ``cmd=palette`` as its fail-safe command so
    the general staff-bot router still understands every palette postback. The
    extra ``leave=1`` marker is intercepted here first. No unsigned leave form
    state is accepted; this only opens the existing signed picker flow.
    """
    if not isinstance(event, dict) or event.get("type") != "postback":
        return None
    postback = event.get("postback")
    if (not isinstance(postback, dict)
            or postback.get("data") != staff_leave_palette.LEAVE_POSTBACK_DATA):
        return None
    converted = dict(event)
    converted["type"] = "message"
    converted["message"] = {"type": "text", "text": "แจ้งลา"}
    converted.pop("postback", None)
    return converted


@router.post("/webhook")
async def staff_oa_webhook(
    request: Request,
    x_line_signature: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """LINE Messaging API webhook: follow events, leave requests and staff bot."""
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

    commands = 0
    for event in events:
        # A direct image is claimed by leave only when this employee has a
        # pending sick-leave request without a certificate. Other media keeps
        # the existing maintenance-ticket behavior. The palette's dedicated
        # postback is translated to the same signed flow as typing แจ้งลา.
        palette_event = _leave_palette_event(event)
        if palette_event is not None or staff_leave.is_leave_event(event, db):
            try:
                await run_in_threadpool(
                    staff_leave.handle_event, palette_event if palette_event is not None else event, db
                )
                commands += 1
            except Exception as exc:  # noqa: BLE001 — isolate each event
                db.rollback()
                logger.error("staff-leave event handling failed: %s", type(exc).__name__)
            continue
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
