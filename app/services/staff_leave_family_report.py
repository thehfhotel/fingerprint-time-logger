"""Add new employee leaves to HF Family's existing free slot reply.

This module deliberately DOES NOT push, multicast or broadcast.  It extends
staff_bot's scheduled group slot digest, which already rides a human event's
LINE reply token, with one readable leave section plus the corresponding leave
receipt images.  Delivery is marked only after LINE accepts that reply.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.core import database
from app.models.staff_leave import StaffLeaveRequest
from app.services import staff_leave

logger = logging.getLogger(__name__)

FAMILY_LEAVE_HEADER = "การลาใหม่"
MAX_LEAVE_IMAGES_PER_REPLY = 4
PORTION_LABELS = {"full": "เต็มวัน", "am": "ครึ่งวันเช้า", "pm": "ครึ่งวันบ่าย"}
_LEAVE_IMAGE_RE = re.compile(r"/leave-images/([0-9a-f]{32})\.png(?:\?|$)")
_INSTALL_MARKER = "hf-family-leave-slot-v1"


@dataclass(frozen=True)
class FamilyLeaveItem:
    request_id: str
    employee_name: str
    leave_label: str
    portion_label: str
    date_text: str
    image_url: str


def _thai_date(value: date) -> str:
    return staff_leave.thai_date(value)


def _date_text(row: StaffLeaveRequest) -> str:
    if row.date_from == row.date_to:
        return _thai_date(row.date_from)
    return f"{_thai_date(row.date_from)} – {_thai_date(row.date_to)}"


def _to_item(row: StaffLeaveRequest) -> FamilyLeaveItem:
    return FamilyLeaveItem(
        request_id=row.id,
        employee_name=row.employee_name,
        leave_label=staff_leave.TYPES.get(row.leave_type, row.leave_type),
        portion_label=PORTION_LABELS.get(row.leave_portion or "full", "เต็มวัน"),
        date_text=_date_text(row),
        image_url=staff_leave.image_url(row),
    )


def fetch_unreported(limit: int) -> tuple[List[FamilyLeaveItem], int]:
    """Oldest new leaves not yet carried by HF Family's slot report.

    Rejected/cancelled requests are deliberately excluded. Approved requests
    remain reportable if a manager reviewed them before the next slot.

    Leave reporting is an optional section on top of the existing HF Family
    slot report. If the leave schema/store is temporarily unavailable (for
    example in an older unit-test schema or during a failed migration), this
    section fails dark instead of breaking maintenance/feedback reporting.
    Unreported rows remain untouched and can be retried in a later slot.
    """
    if limit <= 0:
        return [], 0
    db = database.SessionLocal()
    try:
        query = db.query(StaffLeaveRequest).filter(
            StaffLeaveRequest.family_reported_at.is_(None),
            StaffLeaveRequest.status.in_(("pending", "approved")),
        )
        total = query.count()
        rows = query.order_by(
            StaffLeaveRequest.created_at.asc(), StaffLeaveRequest.id.asc()
        ).limit(limit).all()
        return [_to_item(row) for row in rows], total
    except SQLAlchemyError as exc:
        logger.warning(
            "HF Family leave read unavailable; keeping base slot report: %s",
            type(exc).__name__,
        )
        return [], 0
    finally:
        db.close()


def render_leave_section(items: Sequence[FamilyLeaveItem], total: Optional[int] = None) -> str:
    count = len(items)
    total_count = max(count, total or count)
    lines = [f"{FAMILY_LEAVE_HEADER} ({count} รายการ)"]
    for index, item in enumerate(items, start=1):
        lines.append(
            f"{index}. {item.employee_name} · {item.leave_label} · "
            f"{item.portion_label} · {item.date_text}"
        )
    remaining = total_count - count
    if remaining > 0:
        lines.append(f"และอีก {remaining} รายการ จะรายงานในรอบถัดไป")
    return "\n".join(lines)


def _image_message(item: FamilyLeaveItem) -> Dict:
    return {
        "type": "image",
        "originalContentUrl": item.image_url,
        "previewImageUrl": item.image_url,
    }


def _reported_ids_from_messages(messages: Sequence[Dict]) -> List[str]:
    has_leave_section = any(
        isinstance(message, dict)
        and message.get("type") == "text"
        and FAMILY_LEAVE_HEADER in str(message.get("text") or "")
        for message in messages
    )
    if not has_leave_section:
        return []
    ids: List[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("type") != "image":
            continue
        url = str(message.get("originalContentUrl") or "")
        match = _LEAVE_IMAGE_RE.search(url)
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    return ids


def mark_reported(request_ids: Sequence[str]) -> None:
    ids = [value for value in dict.fromkeys(request_ids) if isinstance(value, str)]
    if not ids:
        return
    db = database.SessionLocal()
    try:
        db.query(StaffLeaveRequest).filter(
            StaffLeaveRequest.id.in_(ids),
            StaffLeaveRequest.family_reported_at.is_(None),
        ).update(
            {"family_reported_at": datetime.utcnow()},
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def install(staff_bot_module, staff_oa_service_module) -> None:
    """Install the slot-report extension idempotently."""
    original_build = staff_bot_module.build_reply
    if getattr(original_build, "_hf_family_leave_marker", None) == _INSTALL_MARKER:
        return

    original_reply_messages = staff_oa_service_module.reply_messages

    def build_reply(
        commands,
        slot_id=None,
        confirmed_request_ids=None,
        actions=(),
        photo_acks=None,
    ):
        built = original_build(
            commands, slot_id, confirmed_request_ids, actions, photo_acks
        )
        if staff_bot_module.COMMAND_SLOT_DIGEST not in set(commands):
            return built

        messages = list(built.messages)
        max_messages = staff_bot_module.MAX_REPLY_MESSAGES
        if len(messages) >= max_messages:
            return built

        # If the normal slot digest already produced a text object, the leave
        # section can share it and every remaining object may be an image.
        text_index = None
        if built.slot_digest_included:
            text_index = next(
                (i for i, message in enumerate(messages)
                 if isinstance(message, dict) and message.get("type") == "text"),
                None,
            )
        reserved_text_objects = 0 if text_index is not None else 1
        image_capacity = min(
            MAX_LEAVE_IMAGES_PER_REPLY,
            max_messages - len(messages) - reserved_text_objects,
        )
        if image_capacity <= 0:
            return built

        items, total = fetch_unreported(image_capacity)
        if not items:
            return built
        section = render_leave_section(items, total)

        if text_index is not None:
            current = str(messages[text_index].get("text") or "")
            combined = current + ("\n\n" if current else "") + section
            # A very large maintenance/feedback digest should not force us to
            # send images without their leave explanation. In that rare case
            # use a separate text object and reduce the image batch by one.
            if len(combined) <= staff_bot_module.MAX_MESSAGE_CHARS:
                messages[text_index] = {**messages[text_index], "text": combined}
            else:
                separate_capacity = min(
                    MAX_LEAVE_IMAGES_PER_REPLY,
                    max_messages - len(messages) - 1,
                )
                if separate_capacity <= 0:
                    return built
                if separate_capacity < len(items):
                    items, total = fetch_unreported(separate_capacity)
                    section = render_leave_section(items, total)
                messages.append({"type": "text", "text": section})
        else:
            messages.append({"type": "text", "text": section})

        messages.extend(_image_message(item) for item in items)
        return staff_bot_module.BuiltReply(
            messages[:max_messages],
            True,  # leave content itself makes this a real slot report
            built.digest_available,
            built.pending_uploads,
        )

    def reply_messages(reply_token: str, messages: Sequence[Dict]) -> None:
        # First let LINE accept the free reply. Only then consume leave rows.
        original_reply_messages(reply_token, messages)
        request_ids = _reported_ids_from_messages(messages)
        if not request_ids:
            return
        try:
            mark_reported(request_ids)
        except Exception as exc:  # noqa: BLE001 — LINE already accepted the reply
            logger.warning(
                "HF Family leave delivery marker failed after LINE accepted reply: %s",
                type(exc).__name__,
            )

    build_reply._hf_family_leave_marker = _INSTALL_MARKER
    reply_messages._hf_family_leave_marker = _INSTALL_MARKER
    staff_bot_module.build_reply = build_reply
    staff_oa_service_module.reply_messages = reply_messages
