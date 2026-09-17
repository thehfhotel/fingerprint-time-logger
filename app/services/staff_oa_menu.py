"""Grant-driven LINE Employee Hub menu model.

This is the single source of truth for staff rich-menu buttons, grant-based
visibility, tap bounds and LINE payloads.  Presentation is rendered by
``staff_oa_images``.  Keep authorization on the destination services; a rich
menu is a launcher, never an access-control boundary.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

# v3 = HF Internal soft UI redesign (light cards, navy/teal icon system).
# The version participates in the signature so staff_oa_sync creates fresh
# LINE rich-menu objects and uploads fresh images instead of reusing v2.
IMAGE_STYLE_VERSION = 3

RICH_MENU_NAME_PREFIX = "staffhub"
CHAT_BAR_TEXT = "เมนูพนักงาน"
MENU_WIDTH = 2500
MENU_HEIGHT_HALF = 843
MENU_HEIGHT_FULL = 1686


@dataclass(frozen=True)
class MenuButton:
    grant_app_id: Optional[str]
    label: str
    url: str
    glyph: str
    also_grant_app_ids: FrozenSet[str] = frozenset()
    message_text: Optional[str] = None
    hidden_by_grant_app_ids: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        if self.grant_app_id is None and self.also_grant_app_ids:
            raise ValueError(
                f"Base button {self.label!r} (grant_app_id=None) is revealed by "
                f"everyone; extra grants {sorted(self.also_grant_app_ids)} are invalid"
            )
        if self.grant_app_id in self.also_grant_app_ids:
            raise ValueError(
                f"Button {self.label!r} repeats its home grant "
                f"{self.grant_app_id!r} in also_grant_app_ids"
            )

    @property
    def grant_app_ids(self) -> FrozenSet[str]:
        if self.grant_app_id is None:
            return frozenset()
        return frozenset({self.grant_app_id}) | self.also_grant_app_ids


# Order here is the visual/tap order.  There are deliberately no ungated base
# buttons; employees without a menu-relevant grant receive no Employee Hub.
MENU_BUTTONS: Tuple[MenuButton, ...] = (
    MenuButton(
        grant_app_id="housekeeping",
        label="แม่บ้าน",
        url="https://hotel.thehfhotel.org/hk",
        glyph="broom",
    ),
    MenuButton(
        grant_app_id="housekeeping",
        label="แจ้งซ่อม",
        url="https://housekeeping.thehfhotel.org/staff/report",
        glyph="wrench",
    ),
    MenuButton(
        grant_app_id="housekeeping",
        label="สต๊อกของ",
        url="https://housekeeping.thehfhotel.org/staff/stock",
        glyph="box",
    ),
    MenuButton(
        grant_app_id="housekeeping",
        label="รับของมาส่ง",
        url="https://housekeeping.thehfhotel.org/staff/receive",
        glyph="tray",
    ),
    MenuButton(
        grant_app_id="reception",
        label="สถานะห้อง",
        url="https://hotel.thehfhotel.org/hk",
        glyph="clipboard",
        hidden_by_grant_app_ids=frozenset({"housekeeping"}),
    ),
    MenuButton(
        grant_app_id="housekeeping",
        also_grant_app_ids=frozenset({"reception"}),
        label="รายงานแม่บ้าน",
        url="https://hotel.thehfhotel.org/hk/report",
        glyph="photo_sheet",
    ),
    MenuButton(
        grant_app_id="reception",
        label="งานซ่อมค้าง",
        url="",
        glyph="wrench_list",
        message_text="งานค้าง",
        hidden_by_grant_app_ids=frozenset({"housekeeping"}),
    ),
    MenuButton(
        grant_app_id="reception",
        also_grant_app_ids=frozenset({"housekeeping"}),
        label="จัดการงานซ่อม",
        url="https://housekeeping.thehfhotel.org/staff/queue",
        glyph="wrench",
    ),
)

MENU_GRANT_APP_IDS: FrozenSet[str] = frozenset(
    grant
    for button in MENU_BUTTONS
    for grant in button.grant_app_ids | button.hidden_by_grant_app_ids
)


def menu_grants(granted_app_ids: Iterable[str]) -> FrozenSet[str]:
    return frozenset(granted_app_ids) & MENU_GRANT_APP_IDS


def menu_key(granted_app_ids: Iterable[str]) -> str:
    relevant = sorted(menu_grants(granted_app_ids))
    return "+".join(["base"] + relevant) if relevant else "base"


def grants_for_menu_key(key: str) -> FrozenSet[str]:
    parts = key.split("+")
    if not parts or parts[0] != "base":
        raise ValueError(f"Not a staff-hub menu key: {key!r}")
    grants = frozenset(parts[1:])
    unknown = grants - MENU_GRANT_APP_IDS
    if unknown:
        raise ValueError(f"Unknown grant(s) in menu key {key!r}: {sorted(unknown)}")
    return grants


def buttons_for(granted_app_ids: Iterable[str]) -> Tuple[MenuButton, ...]:
    relevant = menu_grants(granted_app_ids)
    revealed = (
        button
        for button in MENU_BUTTONS
        if not button.grant_app_ids or button.grant_app_ids & relevant
    )
    return tuple(
        button
        for button in revealed
        if not button.hidden_by_grant_app_ids & relevant
    )


def menu_size(button_count: int) -> Tuple[int, int]:
    if not 1 <= button_count <= 6:
        raise ValueError(f"Unsupported button count: {button_count}")
    if button_count <= 3:
        return (MENU_WIDTH, MENU_HEIGHT_HALF)
    return (MENU_WIDTH, MENU_HEIGHT_FULL)


def menu_rows(button_count: int) -> Tuple[int, ...]:
    if not 1 <= button_count <= 6:
        raise ValueError(f"Unsupported button count: {button_count}")
    if button_count <= 3:
        return (button_count,)
    if button_count == 4:
        return (2, 2)
    return (3, button_count - 3)


def menu_cells(button_count: int) -> List[Dict[str, int]]:
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
    buttons = buttons_for(granted_app_ids)
    payload = {
        "style": IMAGE_STYLE_VERSION,
        "chat_bar": CHAT_BAR_TEXT,
        "size": menu_size(len(buttons)),
        "buttons": [
            [
                sorted(button.grant_app_ids),
                button.label,
                button.url,
                button.glyph,
                button.message_text,
            ]
            for button in buttons
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    return digest.hexdigest()[:12]


def rich_menu_name(granted_app_ids: Iterable[str]) -> str:
    return (
        f"{RICH_MENU_NAME_PREFIX}:{menu_key(granted_app_ids)}"
        f":{menu_signature(granted_app_ids)}"
    )


def is_staff_hub_menu_name(name: str) -> bool:
    return name.startswith(f"{RICH_MENU_NAME_PREFIX}:")


def rich_menu_payload(granted_app_ids: Iterable[str]) -> Dict:
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
                "action": (
                    {
                        "type": "message",
                        "label": button.label[:20],
                        "text": button.message_text,
                    }
                    if button.message_text
                    else {
                        "type": "uri",
                        "label": button.label[:20],
                        "uri": button.url,
                    }
                ),
            }
            for button, cell in zip(buttons, cells)
        ],
    }
