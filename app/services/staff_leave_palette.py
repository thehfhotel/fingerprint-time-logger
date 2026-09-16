"""Small integration hook that adds leave intake to HF ภายใน's default palette."""
from __future__ import annotations

LEAVE_BUTTON_MARKER = "hf-leave-palette-v2"
LEAVE_POSTBACK_DATA = "cmd=palette&leave=1"


def install(staff_bot_module) -> None:
    """Add a single แจ้งลา postback button without changing the shared bot router.

    ``cmd=palette`` keeps the existing palette postback contract/fail-safe: if
    this event ever reaches the general bot instead of the leave interceptor,
    it simply re-opens the palette. ``leave=1`` is claimed first by the verified
    OA webhook and converted into the normal private ``แจ้งลา`` flow.
    Installation is idempotent for reloads/tests.
    """
    original = staff_bot_module.palette_message
    if getattr(original, "_hf_leave_palette_marker", None) == LEAVE_BUTTON_MARKER:
        return

    def palette_with_leave():
        message = original()
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
