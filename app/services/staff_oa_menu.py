"""Employee Hub Role Menus — the grant-driven rich-menu model (2026-07).

The Employee Hub is the rich menu on the dedicated staff LINE Official
Account (ADR: HF-erp docs/adr/0001-employee-hub-is-line-rich-menu.md).
Buttons appear per app grant (``employee_app_grants``); since the Hub was
narrowed to a pure MAID tool (owner, 2026-08-14) there are no ungated base
buttons left at all, so the ``base`` variant is EMPTY and an employee
without the ``housekeeping`` grant gets no menu — see the comment at the
top of MENU_BUTTONS. This module is the single source of truth for which
buttons exist, which grant reveals each one, and how a grant set maps to a
rich-menu layout — everything else (image rendering, the LINE Messaging
API sync, the follow-event webhook) derives from it.

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
    # BASE IS DELIBERATELY EMPTY (owner directive 2026-08-14: "remove the
    # clock-in button too"). No MenuButton carries grant_app_id=None any
    # more, so `base` — the variant an employee with no menu-relevant grant
    # resolves to — has ZERO buttons, and that is the intended end state of
    # narrowing the Hub to a pure MAID tool: the only buttons left are the
    # two `housekeeping` ones below, so an employee WITHOUT that grant sees
    # no Employee Hub menu at all. Not a degraded menu, not a launcher with
    # one dead tile — nothing. That is the point: the Hub is for maids.
    #
    # This supersedes the old "keep สแกนเข้างาน because base must never be
    # empty" reasoning that lived here. The clock-in tile (glyph "clock") was
    # the last base button and it was kept partly to dodge a footgun rather
    # than on its own merits. Note what it actually SHIPPED as: the bare
    # https://erp.thehfhotel.org/qr-checkin, which 301s to http:// and then
    # 404s — dead on every linked employee's phone from the menu's first
    # commit (a816c86b, 2026-07-09) until it was removed on 2026-08-14. If a
    # clock-in tile ever returns, the correct target is
    # https://erp.thehfhotel.org/qr-checkin/mobile; see the "If a clock-in
    # button ever comes back" section of docs/EMPLOYEE_HUB_SETUP.md. The footgun is now handled head-on instead of
    # papered over with a button: scripts/staff_oa_sync.py computes
    # `base_has_buttons` once, up front, and branches on it — see sync() in
    # that file. When base is empty the sync deploys NO base menu, CLEARS
    # the channel default (rather than leaving it pointed at a menu the
    # stale-menu sweep is about to delete), and UNLINKS the employees whose
    # variant is `base` instead of linking them to a menu that no longer
    # exists. app/services/staff_oa_service.link_role_menu_for_line_user()
    # (the follow-webhook path) degrades the same way: no buttons ⇒ no menu
    # ⇒ return None, never a link to someone else's variant.
    #
    # Consequence to keep in mind before re-adding a base button: with base
    # empty, menu_size(0) still raises, so menu_signature / rich_menu_name /
    # rich_menu_payload cannot be called for the empty grant set at all.
    # That is deliberate — there is no LINE menu to name or render — and the
    # sync never calls them for base because it never plans that variant.
    #
    # Re-adding clock-in (or any other base tile) is a one-line change here;
    # the empty-base handling downstream is written to survive both states,
    # and tests pin both (tests/unit/test_staff_oa_sync.py runs the whole
    # sync against a synthetic base button as well as against the real,
    # empty base).
    #
    # Reimbursement is deliberately NOT on the menu (owner directive
    # 2026-08-14). The button opened reimbursement.thehfhotel.org inside
    # LINE's in-app browser, where Google refuses OAuth entirely
    # (disallowed_useragent) — managers reaching the Cloudflare Access
    # picker were dead-ended, which read as "reimbursement is LINE-only".
    # Reimbursement is a web app used from real browsers (desktop included);
    # don't re-add it here without solving the external-browser handoff.
    #
    # เงินเดือน (payroll) and OTA Desk were removed the same day, for scope
    # rather than breakage: the owner set the Hub's purpose as a MAID tool
    # ("notify reception of cleaning progress and maid inventory"), and
    # neither is a maid tool. Both are also dual-IdP with a Cloudflare picker,
    # so they render a Google button inside LINE — the same shape that
    # dead-ended Reimbursement. It bites less there because both are
    # grant-gated to HF ID (LINE) employees, who pick HF ID and get through;
    # it is a footgun, not a live outage. Removing the tiles removes only the
    # launcher — the grants still open both from a real browser, where they
    # work better. Nobody held the `ota` grant at all.
    #
    # แม่บ้าน (hotel.thehfhotel.org/hk) — RE-ADDED 2026-08-14 on the owner's
    # explicit go, after being deferred earlier the same day ("report clean
    # rooms defer"). Both conditions recorded at deferral were addressed by the
    # wave-4 stream in new-hotel: `?branch=` is now REQUIRED on every /hk room
    # endpoint (400 absent, 403 outside the HK_BRANCHES allowlist) instead of
    # silently defaulting to Branch::Hfhotel, and a maid mark-dirty verb now
    # exists. The immediate reason for the re-add is that V11 — a maid walking
    # start -> done on a real room — is meant to be exercised FROM this tile
    # rather than by typing the URL.
    #
    # TWO CAVEATS THAT ARE STILL OPEN, and they matter before other maids get
    # the `housekeeping` grant:
    #   1. The branch is PICKED BY THE MAID (a per-device picker whose options
    #      come from the global HK_BRANCHES env), not derived from her identity.
    #      A HF Ville maid can still choose HF Hotel and file against the wrong
    #      property. A per-employee guard keyed on HF ID's Employee.location is
    #      being built to close this; until it lands, the picker is the only
    #      thing standing between a mis-tap and a wrong-property write.
    #   2. Nothing notifies reception of anything. A maid's report reaches a
    #      30-second-poll board and no human — ht_hk_cleaning_events is read by
    #      nothing outside routes/hk.rs, so `started` has zero reception
    #      visibility, and only `done` lands, as a silent room_clean flip.
    #
    # Today the exposure of both is bounded: badge 421 (the owner) is the sole
    # `housekeeping` grant holder, so this tile reaches exactly one person who
    # knows the caveats. Re-check both before granting a real maid.
    #
    # Housekeeping Ops (docs/housekeeping-ops-interfaces.md, 2026-08-11): the
    # ~/HF/housekeeping app's maid-facing pages, revealed by the same
    # `housekeeping` grant. These two work end-to-end today.
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
    # Renamed from เบิกของ 2026-08-17: เบิก was switched off that day
    # (HK_STOCK_TAKE_ENABLED, maids self-manage stock for now) and รับของ moved
    # to its own screen, so the page behind this tile does neither of the things
    # the old label named. It is นับสต๊อก and ขอซื้อของ now. Same URL.
    MenuButton(
        grant_app_id="housekeeping",
        label="สต๊อกของ",
        url="https://housekeeping.thehfhotel.org/staff/stock",
        glyph="box",
    ),
    # A supplier drops one box covering several คำขอซื้อ; she books the whole
    # delivery in one submit. On the menu in its own right rather than behind
    # สต๊อกของ, because it is a distinct errand she does when the truck arrives,
    # not something she reaches for mid-corridor. Note this takes the maid menu
    # to FOUR buttons, so the canvas becomes the two-row 2500x1686 (rows 2+2,
    # no dead cell) — the first variant here to use it.
    MenuButton(
        grant_app_id="housekeeping",
        label="รับของมาส่ง",
        url="https://housekeeping.thehfhotel.org/staff/receive",
        glyph="tray",
    ),
    # สถานะห้อง — the SAME /hk board the maids' แม่บ้าน tile opens, revealed by
    # the new `reception` grant instead.
    #
    # WHY reception gets a tile at all: caveat 2 above ("nothing notifies
    # reception of anything") is what this closes from the reading side. A
    # maid's `started` reached a 30-second-poll board and no human; reception
    # now has that board one tap away on the same phone they already carry the
    # Hub on, instead of a URL nobody typed.
    #
    # WHY it is safe to point reception at a write surface: it is not one for
    # them. new-hotel's hk_access middleware admits EITHER grant, but the
    # `reception` grant is a READ-ONLY viewer — the write verbs (POST
    # .../cleaning, POST .../linen-shortage) require `housekeeping` and answer
    # a reception-only identity with a 403. The /hk UI hides the reporting
    # controls for them (GET /api/hk/me returns canReport:false), but that is
    # UX: the server is the enforcement, and the tile is safe even if the
    # frontend regresses. An employee holding BOTH grants is full-access and
    # simply sees five tiles, the first and fifth pointing at the same board.
    #
    # This takes the both-grants variant to FIVE buttons — the 3+2 layout,
    # first real use of menu_rows(5). LINE's cap is 6, so exactly one tile of
    # headroom is left; the next addition needs a rethink, not a row.
    MenuButton(
        grant_app_id="reception",
        label="สถานะห้อง",
        url="https://hotel.thehfhotel.org/hk",
        glyph="clipboard",
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
    """Stable human-readable variant key, e.g. ``base`` or ``base+housekeeping``."""
    relevant = sorted(menu_grants(granted_app_ids))
    return "+".join(["base"] + relevant) if relevant else "base"


def grants_for_menu_key(key: str) -> FrozenSet[str]:
    """Inverse of :func:`menu_key` — ``base+housekeeping`` -> {housekeeping}.

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
