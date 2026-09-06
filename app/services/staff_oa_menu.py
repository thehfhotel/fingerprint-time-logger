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
    ``employee_app_grants.app_id`` that reveals the button — the tile's HOME
    grant, the role whose job the tool primarily is. ``glyph`` names the icon
    the image renderer draws (see staff_oa_images).

    ``also_grant_app_ids`` is the minimal extension (2026-09-02) for a tool
    that BOTH roles need: the other grants that reveal this same tile. It
    exists because รายงานแม่บ้าน is one screen two roles work — the maid files
    the report, reception verifies or returns it — and neither a duplicate row
    per grant nor a whole second surface would be honest about that.

    ONE ROW, NOT ONE ROW PER GRANT, is the whole design. Dedup is then
    structural rather than a rule someone has to remember: ``buttons_for``
    walks MENU_BUTTONS once and yields each row at most once, so an employee
    holding housekeeping AND reception sees the shared tile exactly ONCE, in
    its table position, with no set arithmetic to get wrong. Two rows would
    have shown it twice on the six-cell canvas — the bug this shape makes
    unrepresentable.

    Use ``grant_app_ids`` (below), never the raw ``grant_app_id``, anywhere
    the question is "does this grant set reveal this tile".

    ``message_text`` (2026-09-06) turns the tile into a LINE ``message``
    action instead of ``uri``: tapping it sends this text into the 1:1 chat
    rather than opening a browser. It exists for a tool with no openable web
    page at all — งานซ่อมค้าง's board is Google-IdP-gated and cannot open
    inside LINE's in-app browser, so the tile instead sends the text the
    staff bot (``app/services/staff_bot.py``) already answers. ``url`` may be
    ``""`` for such a button; ``rich_menu_payload`` branches on
    ``message_text`` being set, never on ``url`` being empty.

    ``hidden_by_grant_app_ids`` (2026-09-06) is the cap-preserving counterpart
    to ``also_grant_app_ids``: it REMOVES a row, after the grant/also_grant
    reveal, from an employee who ALSO holds any of these grants. It exists
    because สถานะห้อง and แม่บ้าน open the identical board — an employee
    holding both `housekeeping` and `reception` gets full write access via
    แม่บ้าน, so the read-only สถานะห้อง tile would be a redundant duplicate
    slot on a canvas that is already at LINE's 6-tile cap. Hiding it (rather
    than leaving the duplicate) is what pays for a new tool's row without
    breaking the cap.
    """

    grant_app_id: Optional[str]
    label: str
    url: str
    glyph: str
    also_grant_app_ids: FrozenSet[str] = frozenset()
    message_text: Optional[str] = None
    hidden_by_grant_app_ids: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        # A base button is revealed by EVERYONE, so extra grants on one are
        # not merely redundant — they would leak into MENU_GRANT_APP_IDS and
        # mint variant keys whose menus are byte-identical to base's, i.e.
        # two keys with one signature. provision/sync both treat an exact
        # signature match as "this menu already exists", so that collision
        # would cross-link employees between variants. Refuse the row.
        if self.grant_app_id is None and self.also_grant_app_ids:
            raise ValueError(
                f"Base button {self.label!r} (grant_app_id=None) is revealed by "
                f"everyone; extra grants {sorted(self.also_grant_app_ids)} are "
                "meaningless and would mint phantom menu variants"
            )
        if self.grant_app_id in self.also_grant_app_ids:
            raise ValueError(
                f"Button {self.label!r} repeats its home grant "
                f"{self.grant_app_id!r} in also_grant_app_ids"
            )

    @property
    def grant_app_ids(self) -> FrozenSet[str]:
        """Every grant that reveals this tile; empty for a base button.

        The single accessor the rest of the module reads, so "one grant" and
        "several grants" are the same case everywhere downstream (buttons_for,
        MENU_GRANT_APP_IDS, the signature payload) instead of each site having
        to remember the second field exists.
        """
        if self.grant_app_id is None:
            return frozenset()
        return frozenset({self.grant_app_id}) | self.also_grant_app_ids


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
    # simply sees six tiles, the first and fifth pointing at the same board.
    #
    # This takes the both-grants variant to FIVE buttons — the 3+2 layout,
    # first real use of menu_rows(5). LINE's cap is 6, so exactly one tile of
    # headroom was left at this point; รายงานแม่บ้าน below spent it.
    #
    # HIDDEN FROM A HOUSEKEEPING HOLDER (2026-09-06): แม่บ้าน above opens this
    # SAME board with full write access, so a housekeeping+reception employee
    # gained nothing from a second, read-only tile pointing at it — it was a
    # duplicate slot on a canvas already at LINE's cap. Hiding it here is what
    # pays for งานซ่อมค้าง's new row below without the both-grants variant
    # going to 7. A reception-only employee (no housekeeping) still sees it —
    # the hide only fires when the write-access tile is ALSO on the menu.
    MenuButton(
        grant_app_id="reception",
        label="สถานะห้อง",
        url="https://hotel.thehfhotel.org/hk",
        glyph="clipboard",
        hidden_by_grant_app_ids=frozenset({"housekeeping"}),
    ),
    # รายงานแม่บ้าน — Report HK, the owner's paper room-report sheet digitized
    # (decisions grilled 2026-09-02; vocabulary in new-hotel CONTEXT.md
    # §Housekeeping "Room report" / "Report verification").
    #
    # WHY IT IS ON THE MENU AT ALL: it is the maid's daily obligation, once per
    # room — status code, the equipment checklist, and her photos — and it
    # replaces a paper sheet she used to carry. A tool she must reach in every
    # room of her round is exactly what the Hub is for; the alternative is a
    # URL nobody types, which is what the /hk board was before it got a tile.
    #
    # WHY BOTH GRANTS REVEAL IT — the first shared tile on this menu. A report
    # is TWO-SIDED by design: the maid fills it (status, exceptions, 1-4
    # photos), and any receptionist of the branch countersigns it with 1-4
    # photos of her OWN — a verify is a walk-up, not a desk stamp — or returns
    # it with a canned reason for the maid to file a fresh report against. Both
    # halves live on the SAME screen (the day overview at /hk/report, the heir
    # of the paper day-sheet and each side's work queue), so a maid-only tile
    # would leave reception with no way in, and a second reception-only tile
    # pointing at the same URL would be a second row here — and would then show
    # TWICE for the owner, who holds both grants. Hence also_grant_app_ids: one
    # row, revealed by either grant, rendered once. See the MenuButton
    # docstring.
    #
    # WHY THAT IS SAFE: the tile is a launcher, not an authorization. new-hotel
    # enforces the roles SERVER-side on every verb — POST /api/hk/rooms/{id}
    # /report is maid-only (the can_report=true side), verify/return are
    # reception-only, and a maid who also holds `reception` still cannot verify
    # (she is the maid side). The /hk/report UI hides the other side's
    # controls, but that is UX; the server is the enforcement, and this tile
    # stays correct even if the frontend regresses. Same argument the
    # สถานะห้อง tile above already rests on.
    #
    # LINE'S CAP IS NOW EXACTLY REACHED: the both-grants variant is SIX buttons
    # (3+3, the last layout menu_rows() has). There is no headroom left. A
    # seventh tool cannot be a seventh row — it needs a tile removed, or two
    # tools merged behind one tile, or a launcher screen. The over-cap guards
    # in scripts/staff_oa_sync.py and app/services/staff_oa_provision.py are no
    # longer theoretical insurance: one more row here and the both-grants
    # holders lose their menu entirely.
    MenuButton(
        grant_app_id="housekeeping",
        also_grant_app_ids=frozenset({"reception"}),
        label="รายงานแม่บ้าน",
        url="https://hotel.thehfhotel.org/hk/report",
        glyph="photo_sheet",
    ),
    # งานซ่อมค้าง — outstanding-maintenance report, for reception (owner
    # request 2026-09-06: "add menu for reception to view maintenance
    # outstanding in LINE HF ภายใน menu"). The reception web board
    # (works.thehfhotel.org) cannot open from LINE at all — it sits behind
    # Google-IdP Cloudflare Access, and Google refuses OAuth inside LINE's
    # in-app browser (disallowed_useragent), the exact dead-end Reimbursement
    # and payroll already hit (see the note atop this table). So this tile
    # carries no URL: it is a ``message`` action that sends the text งานค้าง
    # into the 1:1 chat, and the staff bot (app/services/staff_bot.py,
    # already live — งานค้าง is one of its DIGEST_WORDS) answers a linked
    # employee with the outstanding-maintenance report. No new web page, no
    # metered LINE push — a message action is a reply token spend, not a
    # push.
    #
    # GLYPH: a new one, ``wrench_list`` (app/services/staff_oa_images.py) — a
    # wrench beside two ruled rows, rather than reusing ``clipboard`` (that
    # mark is already สถานะห้อง's board-of-rooms) or the full ``wrench``
    # (that one means "go fix a room now", แจ้งซ่อม's action; this tile only
    # lists what is still open, read-only, so it needed its own mark rather
    # than borrowing either existing one).
    #
    # HIDDEN FROM A HOUSEKEEPING HOLDER (widened 2026-09-06, owner: "let maid
    # mark fix done too"): จัดการงานซ่อม below is now a SHARED tile a maid can
    # open too, on the SAME queue page a housekeeping+reception employee
    # already reaches with full write access — this chat-only, read-only
    # report would be a redundant second surface for the identical job on a
    # canvas already at LINE's 6-tile cap. A reception-only employee (no
    # housekeeping) is unaffected by the hide and still gets this tile; a
    # maid gets the queue page instead of the chat report, which is also what
    # keeps a housekeeping-only variant at the cap now that จัดการงานซ่อม
    # reaches her too. A reception-only employee still gets both tiles side
    # by side (สถานะห้อง's hide argument, restated for this pair).
    MenuButton(
        grant_app_id="reception",
        label="งานซ่อมค้าง",
        url="",
        glyph="wrench_list",
        message_text="งานค้าง",
        hidden_by_grant_app_ids=frozenset({"housekeeping"}),
    ),
    # จัดการงานซ่อม — owner decision 2026-09-06 ("launch both"), WIDENED the
    # same day ("let maid mark fix done too"): opens the actual queue page
    # where the work gets done (claim a card, move it, close it) — a `uri`
    # tile, since housekeeping.thehfhotel.org/staff/queue is on this domain's
    # own Cloudflare Access app and (unlike works.thehfhotel.org) does not hit
    # the Google-IdP-inside-LINE dead end. งานซ่อมค้าง above answers "what's
    # still open" as a chat message; this is where it gets closed.
    #
    # NOW A SHARED TILE, like รายงานแม่บ้าน — housekeeping's own /staff/queue
    # page already admits the `housekeeping` grant as well as `reception`
    # (the maids' half of "let maid mark fix done too"), so a maid needs this
    # launcher exactly as much as reception does. One row, revealed by either
    # grant, rendered once — the same shared-tile shape รายงานแม่บ้าน already
    # uses, and for the identical reason: a second, housekeeping-only row
    # would show TWICE for a housekeeping+reception holder.
    #
    # NO LONGER HIDDEN: unlike สถานะห้อง and งานซ่อมค้าง above, a
    # housekeeping+reception employee does NOT already have an equivalent tile
    # for this job — งานซ่อมค้าง is read-only chat, not the queue page — so
    # there is nothing redundant to drop here. That employee instead loses
    # งานซ่อมค้าง's slot to this one (see its ``hidden_by_grant_app_ids``
    # above), which is what keeps the both-grants variant at LINE's 6-tile
    # cap.
    #
    # GLYPH: reuses ``wrench`` rather than ``wrench_list`` — this tile is
    # where work actually gets DONE (the full corner-to-corner wrench, the
    # same "go act" mark แจ้งซ่อม already wears), not where it is merely
    # listed (wrench_list, งานซ่อมค้าง's mark, stays a read-only report).
    MenuButton(
        grant_app_id="reception",
        also_grant_app_ids=frozenset({"housekeeping"}),
        label="จัดการงานซ่อม",
        url="https://housekeeping.thehfhotel.org/staff/queue",
        glyph="wrench",
    ),
)

# Grants that actually change the menu. Any other grant (rooms, portal, …)
# is menu-irrelevant and ignored when computing variants. Unioned over each
# button's FULL grant set AND its hidden_by_grant_app_ids, so a grant that
# only ever appears as a shared tile's `also_grant_app_ids` — or only ever
# HIDES a row, never reveals one — still counts as menu-relevant. Without the
# hidden_by half, a hiding grant absent from every button's reveal set would
# be stripped out of `relevant` by menu_grants() before buttons_for() ever
# gets to check it, and the hide would silently never fire.
MENU_GRANT_APP_IDS: FrozenSet[str] = frozenset(
    grant
    for button in MENU_BUTTONS
    for grant in button.grant_app_ids | button.hidden_by_grant_app_ids
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
    """The buttons this grant set sees, in canonical table order.

    A shared tile (several grants on one row) is revealed by ANY of them and
    appears exactly ONCE regardless of how many the employee holds — this walk
    visits each row once, which is why the model puts several grants on one
    row rather than one row per grant.

    Hiding runs as a SECOND pass, after the grant/also_grant reveal above: a
    revealed row is then dropped if the employee holds ANY of its
    ``hidden_by_grant_app_ids``. Two passes, not one combined filter, because
    the questions are different — "is this row revealed at all" vs. "does a
    BETTER row already cover the same ground for this employee" — and merging
    them would let a hide accidentally suppress a row nothing else revealed.
    """
    relevant = menu_grants(granted_app_ids)
    revealed = (
        button
        for button in MENU_BUTTONS
        if not button.grant_app_ids or button.grant_app_ids & relevant
    )
    return tuple(
        button for button in revealed if not button.hidden_by_grant_app_ids & relevant
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
        # sorted() over the button's FULL grant set, not the raw
        # grant_app_id: JSON-safe (a frozenset is not), order-stable, and it
        # keeps the hash covering everything about the row that decides what
        # gets rendered — including a widened `also_grant_app_ids`.
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
