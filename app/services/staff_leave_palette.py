"""Integration hook for leave intake and command discovery in HF ภายใน."""
from __future__ import annotations

LEAVE_BUTTON_MARKER = "hf-leave-palette-v4"
LEAVE_POSTBACK_DATA = "cmd=palette&leave=1"

# Keep this short enough to scan on a phone, but explicit enough that an
# employee never has to guess what the bot can do. These are the human-facing
# commands/capabilities; internal postbacks (fixcat/toggleurgent/etc.) remain
# buttons and are deliberately not exposed as technical command names.
HELP_TEXT = (
    "คำสั่งที่ใช้ได้\n\n"
    "งานซ่อม\n"
    "งานค้าง / งานซ่อมค้าง / แจ้งซ่อมค้าง\n"
    "แจ้งซ่อม 204 แอร์ไม่เย็น\n"
    "งานของฉัน\n"
    "สถานะ 128\n"
    "เพิ่มรูป 128\n\n"
    "ความคิดเห็นลูกค้า\n"
    "ความคิดเห็นลูกค้า / ความคิดเห็น / ฟีดแบค / คำขอ\n\n"
    "การลา\n"
    "แจ้งลา / ขอลา\n"
    "ประเภท: ลาป่วย / ลากิจ / ลาพักร้อน / ใช้วันหยุด\n"
    "เลือกได้ทั้งเต็มวัน / ครึ่งวันเช้า / ครึ่งวันบ่าย\n"
    "ตัวอย่าง: แจ้งลา ลาพักร้อน 17-20/9/2569\n"
    "ตัวอย่าง: แจ้งลา ลากิจ ครึ่งวันเช้า 18/9/2569\n"
    "ใบลาล่าสุด\n"
    "แก้ไขใบลา\n"
    "ยกเลิกใบลา\n\n"
    "แตะปุ่มด้านล่าง หรือพิมพ์คำสั่งได้เลย"
)


def _install_help_body(message: dict) -> None:
    contents = message.get("contents")
    if not isinstance(contents, dict):
        return
    body = contents.get("body")
    if not isinstance(body, dict):
        return
    body_contents = body.get("contents")
    if not isinstance(body_contents, list):
        return

    # Preserve the default greeting as the first line. The command guide is
    # supplemental discovery text and must never replace "มีอะไรให้ช่วยคะ".
    if any(
        isinstance(item, dict) and item.get("text") == HELP_TEXT
        for item in body_contents
    ):
        return
    help_block = {
        "type": "text",
        "text": HELP_TEXT,
        "wrap": True,
        "size": "sm",
    }
    if body_contents and isinstance(body_contents[0], dict) and body_contents[0].get("type") == "text":
        body_contents.insert(1, help_block)
    else:
        body_contents.insert(0, help_block)


def install(staff_bot_module) -> None:
    """Add leave + an explicit command guide to the default private palette.

    ``cmd=palette`` keeps the existing palette postback contract/fail-safe: if
    the leave button ever reaches the general bot instead of the leave
    interceptor, it simply re-opens the palette. ``leave=1`` is claimed first
    by the verified OA webhook and converted into the normal private leave
    flow.

    The palette also advertises the exact commands employees can type. The
    friendly label ``ความคิดเห็นลูกค้า`` is accepted as an alias too, so the
    text shown to employees is always executable, not documentation-only.
    """
    # The core bot already treats unknown text as "open palette". Add the one
    # friendly canonical alias used in the guide/palette label so typing it
    # directly performs the expected read instead of merely reopening help.
    if hasattr(staff_bot_module, "REQUEST_WORDS"):
        staff_bot_module.REQUEST_WORDS = frozenset(
            set(staff_bot_module.REQUEST_WORDS) | {"ความคิดเห็นลูกค้า"}
        )

    original = staff_bot_module.palette_message
    if getattr(original, "_hf_leave_palette_marker", None) == LEAVE_BUTTON_MARKER:
        return

    def palette_with_leave():
        message = original()
        _install_help_body(message)
        footer = (((message.get("contents") or {}).get("footer") or {}).get("contents"))
        if isinstance(footer, list) and not any(
            isinstance(item, dict)
            and ((item.get("action") or {}).get("data") == LEAVE_POSTBACK_DATA)
            for item in footer
        ):
            footer.append({
                "type": "button",
                "style": "secondary",
                "action": {
                    "type": "postback",
                    "label": "แจ้งลา",
                    "data": LEAVE_POSTBACK_DATA,
                    "displayText": "แจ้งลา",
                },
            })
        return message

    palette_with_leave._hf_leave_palette_marker = LEAVE_BUTTON_MARKER
    staff_bot_module.palette_message = palette_with_leave
