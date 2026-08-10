"""Employee Hub Role Menus — the grant-driven rich-menu model (2026-07).

The Employee Hub is the rich menu on the dedicated staff LINE Official
Account (ADR: HF-erp docs/adr/0001-employee-hub-is-line-rich-menu.md).
Every employee sees the base buttons; extra buttons appear per app grant
(``employee_app_grants``). This module is the single source of truth for
which buttons exist, which grant reveals each one, and how a grant set
maps to a rich-menu layout — everything else (image rendering, the LINE
Messaging API sync, the follow-event webhook) derives from it.

Pure functions only — no I/O, no LINE calls, no database. That keeps the
menu-computation logic trivially testable and reusable by both the sync
script and the webhook handler.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

# Bump when the rendered look changes (colors, font, glyphs, layout) so the
# sync script re-creates menus whose image is stale even though the buttons
# and URLs are unchanged. The version participates in the menu signature.
IMAGE_STYLE_VERSION = 2

# Rich-menu names created by the sync script start with this prefix so the
# script can tell its own menus apart from anything else on the channel.
RICH_MENU_NAME_PREFIX = "staffhub"

# Text on the chat-bar toggle that opens the menu (LINE cap: 14 chars).
CHAT_BAR_TEXT = "เมนูพนักงาน"

# LINE rich-menu canvas sizes (the only two full-width sizes LINE accepts).
MENU_WIDTH = 2500
MENU_HEIGHT_HALF = 843   # single row — up to 3 buttons
MENU_HEIGHT_FULL = 1686  # two rows — up to 6 buttons


@dataclass(frozen=True)
class MenuButton:
    """One launchable tool on the Employee Hub.

    ``grant_app_id`` is None for base buttons (everyone gets them) or the
    ``employee_app_grants.app_id`` that reveals the button. ``glyph`` names
    the icon the image renderer draws (see staff_oa_images).
    """

    grant_app_id: Optional[str]
    label: str
    url: str
    glyph: str


# ---------------------------------------------------------------------------
# THE source table. Order here = button order on the menu (base first, then
# grant extras in table order). Add a row to add a tool to the Hub.
# ---------------------------------------------------------------------------
MENU_BUTTONS: Tuple[MenuButton, ...] = (
    MenuButton(
        grant_app_id=None,
        label="สแกนเข้างาน",
        url="https://erp.thehfhotel.org/qr-checkin",
        glyph="clock",
    ),
    MenuButton(
        grant_app_id=None,
        label="เบิกค่าใช้จ่าย",
        url="https://reimbursement.thehfhotel.org",
        glyph="receipt",
    ),
    MenuButton(
        grant_app_id="payroll",
        label="เงินเดือน",
        url="https://payroll.thehfhotel.org",
        glyph="baht",
    ),
    MenuButton(
        grant_app_id="ota",
        label="OTA Desk",
        url="https://ota.thehfhotel.org",
        glyph="bell",
    ),
    MenuButton(
        grant_app_id="housekeeping",
        label="แม่บ้าน",
        url="https://hotel.thehfhotel.org/hk",
        glyph="broom",
    ),
    # Housekeeping Ops (docs/housekeeping-ops-interfaces.md, 2026-08-11): the
    # new ~/housekeeping app's maid-facing pages, same `housekeeping` grant
    # that already reveals แม่บ้าน above — one grant, three surfaces.
    MenuButton(
        grant_app_id="housekeeping",
        label="แจ้งซ่อม",
        url="https://housekeeping.thehfhotel.org/staff/report",
        glyph="wrench",
    ),
    MenuButton(
        grant_app_id="housekeeping",
        label="เบิกของ",
        url="https://housekeeping.thehfhotel.org/staff/stock",
        glyph="box",
    ),
)

# Grants that actually change the menu. Any other grant (rooms, portal, …)
# is menu-irrelevant and ignored when computing variants.
MENU_GRANT_APP_IDS: FrozenSet[str] = frozenset(
    button.grant_app_id for button in MENU_BUTTONS if button.grant_app_id
)


def menu_grants(granted_app_ids: Iterable[str]) -> FrozenSet[str]:
    """Reduce an employee's full grant set to the menu-relevant subset."""
    return frozenset(granted_app_ids) & MENU_GRANT_APP_IDS


def menu_key(granted_app_ids: Iterable[str]) -> str:
    """Stable human-readable variant key, e.g. ``base`` or ``base+ota+payroll``."""
    relevant = sorted(menu_grants(granted_app_ids))
    return "+".join(["base"] + relevant) if relevant else "base"


def grants_for_menu_key(key: str) -> FrozenSet[str]:
    """Inverse of :func:`menu_key` — ``base+ota+payroll`` -> {ota, payroll}.

    Raises ValueError for keys this module could not have minted, so a
    corrupted rich-menu name can never silently map to the wrong menu.
    """
    parts = key.split("+")
    if parts[0] != "base":
        raise ValueError(f"Not a staff-hub menu key: {key!r}")
    grants = frozenset(parts[1:])
    unknown = grants - MENU_GRANT_APP_IDS
    if unknown:
        raise ValueError(f"Unknown grant(s) in menu key {key!r}: {sorted(unknown)}")
    return grants


def buttons_for(granted_app_ids: Iterable[str]) -> Tuple[MenuButton, ...]:
    """The buttons this grant set sees, in canonical table order."""
    relevant = menu_grants(granted_app_ids)
    return tuple(
        button
        for button in MENU_BUTTONS
        if button.grant_app_id is None or button.grant_app_id in relevant
    )


def menu_size(button_count: int) -> Tuple[int, int]:
    """Canvas size for a button count: one row up to 3 buttons, else two."""
    if not 1 <= button_count <= 6:
        raise ValueError(f"Unsupported button count: {button_count}")
    if button_count <= 3:
        return (MENU_WIDTH, MENU_HEIGHT_HALF)
    return (MENU_WIDTH, MENU_HEIGHT_FULL)


def menu_rows(button_count: int) -> Tuple[int, ...]:
    """Buttons per row, keeping cells big and rows full-bleed: one row of n
    for n<=3, then 2+2 / 3+2 / 3+3 — never a dead empty cell."""
    if not 1 <= button_count <= 6:
        raise ValueError(f"Unsupported button count: {button_count}")
    if button_count <= 3:
        return (button_count,)
    if button_count == 4:
        return (2, 2)
    return (3, button_count - 3)


def menu_cells(button_count: int) -> List[Dict[str, int]]:
    """Pixel bounds (x, y, width, height) of each button cell, row-major.

    Every row spans the full canvas width (its cells split it evenly, the
    last cell absorbing rounding), so tap areas never overlap and never
    leave dead gutters.
    """
    width, height = menu_size(button_count)
    rows = menu_rows(button_count)
    row_height = height // len(rows)

    cells: List[Dict[str, int]] = []
    for row_index, row_columns in enumerate(rows):
        y = row_index * row_height
        h = height - y if row_index == len(rows) - 1 else row_height
        cell_width = width // row_columns
        for column in range(row_columns):
            x = column * cell_width
            w = width - x if column == row_columns - 1 else cell_width
            cells.append({"x": x, "y": y, "width": w, "height": h})
    return cells


def menu_signature(granted_app_ids: Iterable[str]) -> str:
    """Content hash of everything that defines this variant (buttons, URLs,
    layout, image style). Two menus with equal signatures are identical, so
    the sync script can skip re-creating them — that is its idempotency key.
    """
    buttons = buttons_for(granted_app_ids)
    payload = {
        "style": IMAGE_STYLE_VERSION,
        "chat_bar": CHAT_BAR_TEXT,
        "size": menu_size(len(buttons)),
        "buttons": [
            [button.grant_app_id, button.label, button.url, button.glyph]
            for button in buttons
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    return digest.hexdigest()[:12]


def rich_menu_name(granted_app_ids: Iterable[str]) -> str:
    """LINE rich-menu name: ``staffhub:<variant>:<signature>`` (<=300 chars)."""
    return (
        f"{RICH_MENU_NAME_PREFIX}:{menu_key(granted_app_ids)}"
        f":{menu_signature(granted_app_ids)}"
    )


def is_staff_hub_menu_name(name: str) -> bool:
    """Whether a rich-menu name was minted by this module."""
    return name.startswith(f"{RICH_MENU_NAME_PREFIX}:")


def rich_menu_payload(granted_app_ids: Iterable[str]) -> Dict:
    """The POST /v2/bot/richmenu body for this grant set's Role Menu."""
    buttons = buttons_for(granted_app_ids)
    width, height = menu_size(len(buttons))
    cells = menu_cells(len(buttons))
    return {
        "size": {"width": width, "height": height},
        "selected": True,
        "name": rich_menu_name(granted_app_ids),
        "chatBarText": CHAT_BAR_TEXT,
        "areas": [
            {
                "bounds": cell,
                "action": {
                    "type": "uri",
                    "label": button.label[:20],
                    "uri": button.url,
                },
            }
            for button, cell in zip(buttons, cells)
        ],
    }
