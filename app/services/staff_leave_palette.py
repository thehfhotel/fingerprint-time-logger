"""Small integration hook that adds leave intake to HF ภายใน's default palette."""
from __future__ import annotations

LEAVE_BUTTON_MARKER = "hf-leave-palette-v1"


def install(staff_bot_module) -> None:
    """Add a single แจ้งลา message button without changing the shared bot router.

    The button emits ordinary text, so the verified OA webhook routes it through
    staff_leave before the general bot. Installation is idempotent for reloads/tests.
    """
    original = staff_bot_module.palette_message
    if getattr(original, "_hf_leave_palette_marker", None) == LEAVE_BUTTON_MARKER:
        return

    def palette_with_leave():
        message = original()
        footer = (((message.get("contents") or {}).get("footer") or {}).get("contents"))
        if isinstance(footer, list) and not any(
            isinstance(item, dict)
            and ((item.get("action") or {}).get("text") == "แจ้งลา")
            for item in footer
        ):
            footer.append({
                "type": "button",
                "style": "secondary",
                "action": {"type": "message", "label": "แจ้งลา", "text": "แจ้งลา"},
            })
        return message

    palette_with_leave._hf_leave_palette_marker = LEAVE_BUTTON_MARKER
    staff_bot_module.palette_message = palette_with_leave
