"""Unit tests for the Employee Hub Role Menu model (app.services.staff_oa_menu).

Pins the grant → menu computation: which buttons a grant set reveals, the
variant keys, the LINE canvas layout, and the idempotency signature the
sync script keys on.

Scope note (2026-08-14): the owner re-scoped the Hub to a MAID tool —
"notify reception of cleaning progress and maid inventory" — so payroll,
OTA Desk and Reimbursement left MENU_BUTTONS, แม่บ้าน was deferred, and
finally the clock-in tile went too ("remove the clock-in button too"). That
left ``housekeeping`` as the only menu-relevant grant, which is why payroll
and ota are used throughout as *menu-irrelevant* examples: real app grants
an employee genuinely holds that must not move the menu.

Scope note (2026-09-01): the OTHER half of that re-scope finally landed.
"Notify reception" was the stated purpose and reception had no surface at
all — a maid's report reached a poll-driven board and no human. ``reception``
is now a second menu-relevant grant carrying one tile, สถานะห้อง, pointed at
the SAME https://hotel.thehfhotel.org/hk board as the maids' แม่บ้าน tile.
It is a READ-ONLY viewer there: new-hotel's hk_access admits either grant,
but the write verbs require ``housekeeping``. So this file now pins a menu
model with TWO menu grants and FOUR reachable variants for the first time.

Scope note (2026-09-02): รายงานแม่บ้าน (Report HK) is the first SHARED tile —
one MenuButton row revealed by EITHER grant, because a room report is
two-sided by design (the maid files it, reception verifies or returns it,
both attach photos) and both halves live on the same /hk/report screen. That
is what ``MenuButton.also_grant_app_ids`` exists for, and the property this
file pins hardest is that a holder of BOTH grants sees it exactly ONCE.

The four reachable variants are now base (0 buttons), base+reception (2),
base+housekeeping (5, the 3+2 layout) and base+housekeeping+reception (6 —
LINE's cap, exactly reached, 3+3). There is no headroom left: a seventh tile
would have to replace one, not join them.

BASE IS EMPTY, AND THAT IS THE CONTRACT
---------------------------------------
With no ungated buttons left, ``buttons_for(set())`` is ``()``. Everything
downstream of a button count therefore refuses the empty grant set:
``menu_size(0)`` raises, and so do ``menu_signature`` / ``rich_menu_name``
/ ``rich_menu_payload`` through it. That is deliberate — there is no LINE
menu to name or render for a variant with nothing on it — and it is why the
sync script never plans the ``base`` variant at all when base is empty
(``base_has_buttons`` in scripts/staff_oa_sync.py). These tests pin the
empty-base contract on both sides: no buttons, and no renderable menu.
"""
import itertools

import pytest

from app.services import staff_oa_menu as menu

# The clock-in tile's URL, spelled out rather than read back from the module
# under test — pinning it here is the point. The tile is GONE (2026-08-14),
# but the URL shape it got wrong for five weeks is still worth guarding
# against for anything that re-adds it. See
# test_no_button_points_at_the_bare_qr_checkin_404.
CLOCK_IN_URL = "https://erp.thehfhotel.org/qr-checkin/mobile"
BARE_QR_CHECKIN_404 = "https://erp.thehfhotel.org/qr-checkin"

# The grants that produce buttons. MENU_GRANT keeps its old meaning (the maid
# grant) so the tests written against it still read straight; RECEPTION_GRANT
# is the read-only viewer added 2026-09-01.
MENU_GRANT = "housekeeping"
RECEPTION_GRANT = "reception"

# The one board both grants open. Reception reaches it read-only; the maids
# write to it. Same URL on purpose — spelled out here because two tiles now
# carry it and a test asserting "the url is present" no longer identifies
# which tile it came from.
HK_BOARD_URL = "https://hotel.thehfhotel.org/hk"

# The Report HK day overview — the shared tile's target (2026-09-02). Both
# roles open the SAME screen; which half of it they get is decided
# server-side by new-hotel, not by which tile they tapped.
HK_REPORT_URL = "https://hotel.thehfhotel.org/hk/report"
REPORT_LABEL = "รายงานแม่บ้าน"


def _real_variants():
    """Every grant set a real employee can present to the menu model.

    ``staff_oa_service.employee_menu_assignments`` funnels each employee's
    grants through ``menu_key``/``menu_grants``, so the reachable variants
    are exactly the powerset of MENU_GRANT_APP_IDS — no more, no less.
    """
    apps = sorted(menu.MENU_GRANT_APP_IDS)
    for size in range(len(apps) + 1):
        for combo in itertools.combinations(apps, size):
            yield frozenset(combo)


class TestMenuButtonsForGrants:
    def test_base_menu_is_empty_by_design(self):
        # Was test_base_menu_has_exactly_clockin. The clock-in tile was the
        # last ungated button and the owner removed it on 2026-08-14
        # ("remove the clock-in button too"), completing the narrowing of the
        # Hub to a maid tool. An employee with no menu-relevant grant now
        # sees NO menu at all — the whole downstream design (sync,
        # follow-webhook) keys off this being empty, so pin it directly.
        assert menu.buttons_for(set()) == ()
        assert not any(
            button.grant_app_id is None for button in menu.MENU_BUTTONS
        )

    def test_the_empty_base_variant_has_no_renderable_menu(self):
        # The other half of the contract: nothing downstream will pretend a
        # 0-button variant is a LINE menu. If any of these ever stops
        # raising, staff_oa_sync would silently create an empty rich menu
        # instead of taking its deliberate no-base path.
        for call in (
            lambda: menu.menu_size(0),
            lambda: menu.menu_signature(set()),
            lambda: menu.rich_menu_name(set()),
            lambda: menu.rich_menu_payload(set()),
        ):
            with pytest.raises(ValueError):
                call()

    def test_no_button_points_at_the_bare_qr_checkin_404(self):
        """Guards the specific regression that shipped for five weeks.

        The bare /qr-checkin path has no route: it 301s to http:// (protocol
        downgrade) and then 404s. It sat on the clock-in tile from the menu's
        first commit (a816c86b, 2026-07-09) until 2026-08-14, so every linked
        employee had a dead clock-in button. The registered pages are
        /qr-checkin/{terminal,mobile,link-account,onboard}; the Hub is a phone
        surface, so /mobile is the correct one.

        The tile itself is gone now (same day, owner directive), so this no
        longer asserts the fixed URL is present — that would just re-add the
        button by test. It keeps the shape rule, which outlives the tile: any
        qr-checkin link that comes back on this menu must carry a real
        sub-page.
        """
        urls = [button.url for button in menu.MENU_BUTTONS]
        assert BARE_QR_CHECKIN_404 not in urls
        # Nothing may point at the /qr-checkin root under any spelling —
        # a real sub-page must follow it.
        for url in urls:
            if url.startswith(BARE_QR_CHECKIN_404):
                assert url[len(BARE_QR_CHECKIN_404):].startswith("/")

    def test_clock_in_tile_is_gone_from_every_variant(self):
        # The removal itself, pinned across the whole powerset rather than
        # just the base variant: no grant combination may bring it back by
        # accident.
        for grants in _real_variants():
            assert CLOCK_IN_URL not in [b.url for b in menu.buttons_for(grants)]

    def test_reimbursement_is_not_on_any_menu(self):
        every_grant = menu.buttons_for(menu.MENU_GRANT_APP_IDS)
        assert "https://reimbursement.thehfhotel.org" not in [
            b.url for b in every_grant
        ]

    def test_payroll_grant_no_longer_changes_the_menu(self):
        # Was test_payroll_grant_adds_payroll_button. เงินเดือน left the Hub
        # on 2026-08-14 (scope: not a maid tool; also dual-IdP, so it renders
        # a Google button inside LINE). The grant still exists and still opens
        # payroll from a real browser — it just no longer mints a tile, and
        # therefore no longer mints a menu variant either.
        assert "payroll" not in menu.MENU_GRANT_APP_IDS
        assert menu.buttons_for({"payroll"}) == menu.buttons_for(set())
        assert "https://payroll.thehfhotel.org" not in [
            b.url for b in menu.MENU_BUTTONS
        ]

    def test_ota_grant_no_longer_changes_the_menu(self):
        # Was test_ota_grant_adds_ota_desk_button. Same 2026-08-14 re-scope;
        # nobody held the `ota` grant at all.
        assert "ota" not in menu.MENU_GRANT_APP_IDS
        assert menu.buttons_for({"ota"}) == menu.buttons_for(set())
        assert "https://ota.thehfhotel.org" not in [
            b.url for b in menu.MENU_BUTTONS
        ]

    def test_housekeeping_grant_adds_the_cleaning_board_button(self):
        # Was test_deferred_cleaning_board_is_not_on_any_menu, an absence
        # assertion whose whole job was to go red the moment the tile came
        # back — which it did. แม่บ้าน (hotel.thehfhotel.org/hk) was RE-ADDED
        # 2026-08-14 on the owner's explicit go, once wave-4 made `?branch=`
        # required on /hk instead of defaulting to Branch::Hfhotel.
        #
        # It is behind the `housekeeping` grant, so it must NOT appear for an
        # employee who lacks it — that half is still worth pinning, because
        # /hk is a write surface onto real room state.
        assert "https://hotel.thehfhotel.org/hk" in [
            b.url for b in menu.buttons_for({"housekeeping"})
        ]
        assert "https://hotel.thehfhotel.org/hk" not in [
            b.url for b in menu.buttons_for(set())
        ]

    def test_housekeeping_grant_adds_breakage_report_button(self):
        buttons = menu.buttons_for({"housekeeping"})
        assert "https://housekeeping.thehfhotel.org/staff/report" in [
            b.url for b in buttons
        ]

    def test_housekeeping_grant_adds_stock_button(self):
        buttons = menu.buttons_for({"housekeeping"})
        assert "https://housekeeping.thehfhotel.org/staff/stock" in [
            b.url for b in buttons
        ]

    def test_housekeeping_grant_alone_yields_five_buttons(self):
        # The count has tracked every scope change this menu has had: 4 with
        # clock-in + แม่บ้าน, 3 after clock-in went, 2 while แม่บ้าน was
        # deferred, 3 again once it was back (2026-08-14), and 4 since
        # รับของมาส่ง got its own tile (2026-08-17) — which is also the first
        # time a REAL variant needs the two-row canvas.
        #
        # No longer the largest variant, and no longer the only one with any
        # buttons: `reception` arrived 2026-09-01. So the old
        # `len(buttons) == len(MENU_BUTTONS)` assertion is gone — it said
        # "housekeeping owns the whole table", which is exactly what stopped
        # being true. What replaces it says the useful half: this grant must
        # not pick up the reception-only tile.
        #
        # Five since รายงานแม่บ้าน landed (2026-09-02). The maid's own tile
        # count moved even though that tile is SHARED, because `housekeeping`
        # is its home grant — a maid reaches it whether or not anyone in
        # reception exists.
        buttons = menu.buttons_for({MENU_GRANT})
        assert len(buttons) == 5
        assert [b.label for b in buttons] == [
            "แม่บ้าน",
            "แจ้งซ่อม",
            "สต๊อกของ",
            "รับของมาส่ง",
            REPORT_LABEL,
        ]
        assert all(MENU_GRANT in b.grant_app_ids for b in buttons)
        assert "สถานะห้อง" not in [b.label for b in buttons]
        assert menu.menu_size(len(buttons)) == (menu.MENU_WIDTH, menu.MENU_HEIGHT_FULL)
        assert menu.menu_rows(len(buttons)) == (3, 2)

    def test_reception_grant_reveals_the_board_and_the_report(self):
        # Was test_reception_grant_reveals_exactly_the_room_status_tile, when
        # the grant carried one tile. It carries TWO since 2026-09-02: the
        # room-status board it reads, and the report screen it must reach to
        # verify or return what the maids filed — the shared tile.
        #
        # What has not changed is the gate: a reception-only identity must
        # still NOT pick up the maid tiles. แจ้งซ่อม / สต๊อกของ / รับของมาส่ง
        # are write surfaces in the housekeeping app, and the read-only-ness of
        # the two tiles it DOES get is a property of new-hotel's server-side
        # role checks, not of the URLs themselves.
        buttons = menu.buttons_for({RECEPTION_GRANT})
        assert [b.label for b in buttons] == ["สถานะห้อง", REPORT_LABEL]

        board, report = buttons
        assert board.url == HK_BOARD_URL
        assert board.grant_app_ids == frozenset({RECEPTION_GRANT})
        assert board.glyph == "clipboard"

        assert report.url == HK_REPORT_URL
        assert report.grant_app_ids == frozenset({MENU_GRANT, RECEPTION_GRANT})
        assert report.glyph == "photo_sheet"

        # Two buttons ⇒ still the single-row canvas.
        assert menu.menu_size(len(buttons)) == (menu.MENU_WIDTH, menu.MENU_HEIGHT_HALF)
        assert menu.menu_rows(len(buttons)) == (2,)

    def test_reception_tile_points_at_the_same_board_the_maids_use(self):
        # Deliberate, not a copy-paste slip: reception READS the board the
        # maids write to. If someone ever gives reception its own URL, this is
        # where the decision gets re-made rather than drifting.
        maid_tile = menu.buttons_for({MENU_GRANT})[0]
        reception_tile = menu.buttons_for({RECEPTION_GRANT})[0]
        assert maid_tile.url == reception_tile.url == HK_BOARD_URL
        assert maid_tile.label != reception_tile.label
        assert maid_tile.glyph != reception_tile.glyph

    def test_both_grants_yield_six_buttons_maids_first(self):
        # An employee holding both is full-access in new-hotel, and here just
        # sees the union of both tile sets — table order, so the four maid
        # tiles, then สถานะห้อง, then the shared report tile.
        #
        # SIX is LINE's cap, exactly reached (3+3, the last layout menu_rows()
        # has). This assertion is therefore also the headroom alarm: adding a
        # seventh row to MENU_BUTTONS turns this variant into one LINE cannot
        # render, and its holders get UNLINKED by the over-cap guards rather
        # than a menu. A seventh tool has to replace a tile, not join them.
        buttons = menu.buttons_for({MENU_GRANT, RECEPTION_GRANT})
        assert [b.label for b in buttons] == [
            "แม่บ้าน",
            "แจ้งซ่อม",
            "สต๊อกของ",
            "รับของมาส่ง",
            "สถานะห้อง",
            REPORT_LABEL,
        ]
        assert len(buttons) == len(menu.MENU_BUTTONS) == 6
        assert menu.menu_size(6) == (menu.MENU_WIDTH, menu.MENU_HEIGHT_FULL)
        assert menu.menu_rows(6) == (3, 3)

    def test_the_shared_report_tile_appears_exactly_once_for_a_both_grant_holder(self):
        # THE property the shared-tile model exists to guarantee. Modelled as
        # two rows (one per grant) instead of one row with two grants, the
        # owner — who holds both — would see รายงานแม่บ้าน TWICE, and the
        # variant would need seven cells on a six-cell canvas: not a cosmetic
        # bug, a menu that cannot be created at all.
        #
        # Checked by URL as well as label, since a duplicate row would most
        # likely differ in label ("รายงานแม่บ้าน" vs "ตรวจรายงาน") while
        # pointing at the same screen.
        for grants in ({MENU_GRANT}, {RECEPTION_GRANT}, {MENU_GRANT, RECEPTION_GRANT}):
            buttons = menu.buttons_for(grants)
            assert [b.label for b in buttons].count(REPORT_LABEL) == 1
            assert [b.url for b in buttons].count(HK_REPORT_URL) == 1

    def test_reception_tiles_are_hidden_without_a_menu_grant(self):
        # The gate itself. /hk and /hk/report are real room-state surfaces; a
        # tile onto either must never appear for an employee holding neither
        # grant, nor be revealed by a menu-irrelevant grant.
        for grants in (set(), {"rooms", "portal"}, {"payroll", "ota"},
                       {"housekeeping_admin"}):
            labels = [b.label for b in menu.buttons_for(grants)]
            assert "สถานะห้อง" not in labels
            assert REPORT_LABEL not in labels

    def test_menu_irrelevant_grants_are_ignored(self):
        assert menu.buttons_for({"rooms", "portal"}) == menu.buttons_for(set())

    def test_unknown_grants_are_ignored(self):
        assert menu.buttons_for({"no-such-app"}) == menu.buttons_for(set())

    def test_button_order_follows_source_table_not_grant_order(self):
        # MENU_BUTTONS order — never the order the grants happened to arrive,
        # and never set-iteration order. (Base buttons would come first if
        # any still existed; none do since 2026-08-14.)
        expected = ["แม่บ้าน", "แจ้งซ่อม", "สต๊อกของ", "รับของมาส่ง", REPORT_LABEL]
        assert [b.label for b in menu.buttons_for(
            ["housekeeping", "payroll", "rooms"]
        )] == expected
        assert [b.label for b in menu.buttons_for(
            ["rooms", "payroll", "housekeeping"]
        )] == expected
        assert [b.label for b in menu.buttons_for(
            {"housekeeping", "ota", "payroll"}
        )] == expected


class TestSharedTileModel:
    """``MenuButton.also_grant_app_ids`` — the 2026-09-02 model extension.

    One row, several grants, revealed by ANY of them and rendered once. These
    tests are on the mechanism rather than on รายงานแม่บ้าน specifically, so
    they keep holding when the next shared tool arrives.
    """

    def test_grant_app_ids_is_the_single_accessor_for_both_shapes(self):
        # A single-grant row and a shared row must answer the same question
        # the same way — that is the whole point of the property. Everything
        # downstream (buttons_for, MENU_GRANT_APP_IDS, the signature payload)
        # reads it and never the raw grant_app_id.
        single = menu.MenuButton(
            grant_app_id="housekeeping", label="x", url="https://x.invalid/",
            glyph="broom",
        )
        shared = menu.MenuButton(
            grant_app_id="housekeeping",
            also_grant_app_ids=frozenset({"reception"}),
            label="y", url="https://y.invalid/", glyph="broom",
        )
        base = menu.MenuButton(
            grant_app_id=None, label="z", url="https://z.invalid/", glyph="clock",
        )
        assert single.grant_app_ids == frozenset({"housekeeping"})
        assert shared.grant_app_ids == frozenset({"housekeeping", "reception"})
        assert base.grant_app_ids == frozenset()

    def test_a_base_button_may_not_carry_extra_grants(self):
        # Not pedantry. A base row is revealed by everyone, so its extra
        # grants would still land in MENU_GRANT_APP_IDS and mint variant keys
        # whose button lists — and therefore signatures — are identical to
        # base's. provision and sync both treat "same signature" as "this menu
        # already exists", so the collision would cross-link employees between
        # variants. Refuse the row at construction instead.
        with pytest.raises(ValueError):
            menu.MenuButton(
                grant_app_id=None,
                also_grant_app_ids=frozenset({"reception"}),
                label="x", url="https://x.invalid/", glyph="clock",
            )

    def test_a_row_may_not_repeat_its_home_grant(self):
        with pytest.raises(ValueError):
            menu.MenuButton(
                grant_app_id="housekeeping",
                also_grant_app_ids=frozenset({"housekeeping", "reception"}),
                label="x", url="https://x.invalid/", glyph="clock",
            )

    def test_menu_grant_app_ids_unions_every_row_s_full_grant_set(self):
        # The derivation that would silently break if MENU_GRANT_APP_IDS kept
        # reading grant_app_id: a grant appearing ONLY as a shared tile's
        # extra would not be menu-relevant, so menu_key() would drop it, and
        # its holders would resolve to a variant that does not show them the
        # tile they were granted.
        assert menu.MENU_GRANT_APP_IDS == frozenset(
            grant for button in menu.MENU_BUTTONS for grant in button.grant_app_ids
        )
        assert {MENU_GRANT, RECEPTION_GRANT} <= menu.MENU_GRANT_APP_IDS

    def test_a_grant_that_only_ever_shares_a_tile_is_still_menu_relevant(
        self, monkeypatch
    ):
        # `reception` has a tile of its own today, so the real table cannot
        # demonstrate this. Mint the pure case: a grant that exists ONLY as an
        # extra on somebody else's row.
        shared_only = menu.MenuButton(
            grant_app_id="housekeeping",
            also_grant_app_ids=frozenset({"inspector"}),
            label="ทดสอบ", url="https://synthetic.invalid/", glyph="clock",
        )
        monkeypatch.setattr(menu, "MENU_BUTTONS", (shared_only,))
        monkeypatch.setattr(
            menu, "MENU_GRANT_APP_IDS",
            frozenset(g for b in menu.MENU_BUTTONS for g in b.grant_app_ids),
        )
        assert menu.menu_key({"inspector"}) == "base+inspector"
        assert menu.buttons_for({"inspector"}) == (shared_only,)
        assert menu.buttons_for({"housekeeping", "inspector"}) == (shared_only,)

    def test_signature_covers_the_full_grant_set_of_each_row(self, monkeypatch):
        # Widening a row's grants changes what other variants render, so the
        # hash must move with it — otherwise sync/provision would skip
        # re-creating a menu whose tiles have actually changed.
        rows = (
            menu.MenuButton(
                grant_app_id="housekeeping", label="ทดสอบ",
                url="https://synthetic.invalid/", glyph="clock",
            ),
        )
        monkeypatch.setattr(menu, "MENU_BUTTONS", rows)
        narrow = menu.menu_signature({"housekeeping"})

        monkeypatch.setattr(
            menu, "MENU_BUTTONS",
            (menu.MenuButton(
                grant_app_id="housekeeping",
                also_grant_app_ids=frozenset({"reception"}),
                label="ทดสอบ", url="https://synthetic.invalid/", glyph="clock",
            ),),
        )
        assert menu.menu_signature({"housekeeping"}) != narrow


class TestMenuKeys:
    def test_no_grants_is_base(self):
        assert menu.menu_key(set()) == "base"

    def test_key_is_sorted_and_stable(self):
        # Written against MENU_GRANT_APP_IDS rather than a hardcoded pair
        # (was "base+ota+payroll") so it keeps testing the sort when a second
        # menu grant returns. It returned on 2026-09-01 — `reception` — so the
        # reversed-input case below is finally load-bearing again rather than a
        # one-element no-op.
        every = sorted(menu.MENU_GRANT_APP_IDS)
        expected = "+".join(["base"] + every)
        assert expected == "base+housekeeping+reception"
        assert menu.menu_key(set(every)) == expected
        assert menu.menu_key(list(reversed(every))) == expected
        assert menu.menu_key(["reception", "housekeeping"]) == expected
        # Set iteration order of the caller's grants must not leak into the key.
        assert menu.menu_key({"rooms", "housekeeping", "portal"}) == "base+housekeeping"
        assert menu.menu_key(["housekeeping", "rooms", "portal"]) == "base+housekeeping"

    def test_key_ignores_menu_irrelevant_grants(self):
        # payroll and ota are real, currently-held app grants that no longer
        # touch the menu — the strongest possible irrelevance examples, since
        # a regression re-admitting them would mint variants that have no
        # buttons to show for themselves.
        assert menu.menu_key({"rooms", "portal", "payroll", "ota"}) == "base"
        assert menu.menu_key(
            {"rooms", "portal", "payroll", "ota", "housekeeping"}
        ) == "base+housekeeping"

    def test_grants_for_menu_key_inverts_menu_key(self):
        grants = frozenset({"housekeeping"})
        assert menu.grants_for_menu_key(menu.menu_key(grants)) == grants
        # Menu-irrelevant grants round-trip to nothing, not to themselves.
        assert menu.grants_for_menu_key(menu.menu_key({"payroll", "ota"})) == frozenset()

    def test_every_real_variant_key_round_trips(self):
        for grants in _real_variants():
            assert menu.grants_for_menu_key(menu.menu_key(grants)) == grants

    def test_grants_for_menu_key_rejects_foreign_keys(self):
        with pytest.raises(ValueError):
            menu.grants_for_menu_key("richmenu-something")
        with pytest.raises(ValueError):
            menu.grants_for_menu_key("base+no-such-grant")
        # Keys minted before the 2026-08-14 re-scope name grants that are no
        # longer menu-relevant. A stale rich menu still on the channel must
        # fail loudly rather than silently map to some other variant.
        with pytest.raises(ValueError):
            menu.grants_for_menu_key("base+payroll")
        with pytest.raises(ValueError):
            menu.grants_for_menu_key("base+ota+payroll")


class TestMenuLayout:
    def test_up_to_three_buttons_use_half_height_canvas(self):
        assert menu.menu_size(2) == (2500, 843)
        assert menu.menu_size(3) == (2500, 843)

    def test_four_or_more_buttons_use_full_height_canvas(self):
        assert menu.menu_size(4) == (2500, 1686)
        assert menu.menu_size(6) == (2500, 1686)

    def test_rejects_unsupported_button_counts(self):
        with pytest.raises(ValueError):
            menu.menu_size(0)
        with pytest.raises(ValueError):
            menu.menu_size(7)

    def test_every_real_variant_is_either_renderable_or_the_empty_base(self):
        """Every variant employee_menu_assignments can mint is accounted for.

        Sweeps the powerset of MENU_GRANT_APP_IDS — exactly the variants
        menu_key() can produce for a real employee — and requires each to be
        either a legal LINE menu (1..6 buttons, cells that match) or the
        EMPTY base variant, which is legal in a different way: it has no menu
        at all, and the sync script must not try to build one.

        Was test_every_real_variant_fits_the_line_button_cap, which required
        ``1 <= len(buttons)`` for every variant. That premise died on
        2026-08-14 when the clock-in tile left and base hit zero buttons —
        the very case the old docstring predicted ("or a base button is
        removed and the base variant hits zero"). The empty case is now an
        expected outcome rather than a failure, but it is pinned to base
        alone: any OTHER variant with zero buttons would still be a bug.

        staff_oa_sync.py's over-cap SKIP guard stays regardless — this test
        proves the guard is currently unreachable in production, not that it is
        unnecessary (test_staff_oa_sync.py keeps it red-capable with a
        synthetic grant).
        """
        checked = 0
        empty_keys = []
        for grants in _real_variants():
            buttons = menu.buttons_for(grants)
            key = menu.menu_key(grants)
            if not buttons:
                empty_keys.append(key)
                with pytest.raises(ValueError):
                    menu.menu_size(0)
                checked += 1
                continue
            assert 1 <= len(buttons) <= 6, f"{key}: {len(buttons)} buttons"
            assert menu.menu_size(len(buttons)) in {(2500, 843), (2500, 1686)}
            assert len(menu.menu_cells(len(buttons))) == len(buttons)
            checked += 1
        assert checked == 2 ** len(menu.MENU_GRANT_APP_IDS)
        # Exactly one empty variant, and it is `base` — an empty
        # base+something would mean a grant that reveals nothing.
        assert empty_keys == ["base"]

    def test_five_buttons_split_three_plus_two_with_no_dead_cell(self):
        assert menu.menu_rows(5) == (3, 2)

    @pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 6])
    def test_cells_tile_the_canvas_exactly(self, count):
        width, height = menu.menu_size(count)
        cells = menu.menu_cells(count)
        assert len(cells) == count
        covered = sum(cell["width"] * cell["height"] for cell in cells)
        assert covered == width * height
        for cell in cells:
            assert cell["x"] + cell["width"] <= width
            assert cell["y"] + cell["height"] <= height


class TestMenuSignatureAndName:
    def test_signature_is_deterministic(self):
        assert menu.menu_signature({"housekeeping"}) == menu.menu_signature(
            {"housekeeping"}
        )

    def test_the_empty_base_variant_has_no_signature(self):
        # Was half of test_signature_differs_between_variants (set() vs
        # {"housekeeping"}). set() no longer HAS a signature: hashing a menu
        # that does not exist would give the sync script something to
        # compare, and a rich-menu name to mint, for a variant it must never
        # deploy. Failing loudly is the safer contract.
        with pytest.raises(ValueError):
            menu.menu_signature(set())

    def test_signature_differs_between_variants(self, monkeypatch):
        # Only ONE real variant has buttons today, so a genuine two-variant
        # comparison needs a second button set. A synthetic base button is
        # the honest way to mint one: it is exactly the change that would
        # bring base back (re-adding clock-in is a one-line MENU_BUTTONS
        # edit), so this also pins that signatures still separate base from
        # base+housekeeping the day that happens.
        synthetic_base = menu.MenuButton(
            grant_app_id=None,
            label="ทดสอบ",
            url="https://synthetic.invalid/",
            glyph="clock",
        )
        monkeypatch.setattr(
            menu, "MENU_BUTTONS", (synthetic_base,) + menu.MENU_BUTTONS
        )
        assert menu.menu_signature(set()) != menu.menu_signature({"housekeeping"})

    def test_signature_ignores_menu_irrelevant_grants(self):
        # The sync script skips re-creating a menu whose signature is
        # unchanged. Granting payroll or ota must therefore not churn a menu
        # whose buttons are identical. (The base pairing this used to make —
        # menu_signature({"payroll"}) == menu_signature(set()) — cannot be
        # written any more: neither side has a menu. The equality is asserted
        # on the housekeeping variant instead, which is where a spurious
        # re-create would actually cost something.)
        assert menu.menu_signature(
            {"housekeeping", "payroll", "rooms"}
        ) == menu.menu_signature({"housekeeping"})
        for irrelevant in ({"payroll"}, {"ota"}, {"rooms", "portal"}):
            with pytest.raises(ValueError):
                menu.menu_signature(irrelevant)  # resolves to the empty base

    def test_every_real_variant_has_a_distinct_signature(self):
        # The sync script and provision_for_badge both SKIP re-creating a menu
        # whose signature already matches. So a signature collision between two
        # variants is not a cosmetic bug: it would leave holders of one variant
        # linked to the other's menu — e.g. reception silently handed the four
        # maid write-tiles. Sweep the whole powerset rather than spot-checking
        # the pair added today, so this keeps holding as grants are added.
        signatures = {}
        for grants in _real_variants():
            buttons = menu.buttons_for(grants)
            if not buttons:
                continue  # the empty base has no signature at all
            signatures[menu.menu_key(grants)] = menu.menu_signature(grants)
        assert len(set(signatures.values())) == len(signatures) == 3
        assert set(signatures) == {
            "base+housekeeping",
            "base+reception",
            "base+housekeeping+reception",
        }

    def test_granting_reception_churns_an_existing_maid_menu(self):
        # The upgrade path, stated as the thing that must be true for it to
        # work: a maid who is also given `reception` moves to a DIFFERENT
        # variant with a DIFFERENT signature, so her rich menu is re-created
        # and re-linked instead of being left on the 4-tile image.
        assert menu.menu_signature({MENU_GRANT}) != menu.menu_signature(
            {MENU_GRANT, RECEPTION_GRANT}
        )
        assert menu.rich_menu_name({MENU_GRANT}) != menu.rich_menu_name(
            {MENU_GRANT, RECEPTION_GRANT}
        )

    def test_rich_menu_name_embeds_prefix_key_and_signature(self):
        name = menu.rich_menu_name({"housekeeping"})
        prefix, key, signature = name.split(":")
        assert prefix == "staffhub"
        assert key == "base+housekeeping"
        assert signature == menu.menu_signature({"housekeeping"})
        assert len(name) <= 300  # LINE's rich-menu name cap

    def test_is_staff_hub_menu_name(self):
        # Was built from rich_menu_name(set()), which now raises — the empty
        # base has no name because it has no menu. Any real name works here;
        # the check is on the prefix, not the variant.
        assert menu.is_staff_hub_menu_name(menu.rich_menu_name({MENU_GRANT}))
        assert not menu.is_staff_hub_menu_name("some-other-menu")
        # Stale base menus from before 2026-08-14 are still staffhub menus —
        # the sync must recognise them to reclaim them.
        assert menu.is_staff_hub_menu_name("staffhub:base:0000deadbeef")


class TestRichMenuPayload:
    def test_payload_matches_line_richmenu_schema(self):
        # base+housekeeping, on the two-row 1686 canvas since it grew past 3
        # (รับของมาส่ง, 2026-08-17). Five tiles since รายงานแม่บ้าน
        # (2026-09-02). It stopped being the MAXIMAL variant on 2026-09-01
        # (base+housekeeping+reception) — that one is covered below.
        payload = menu.rich_menu_payload({"housekeeping"})
        assert payload["size"] == {"width": 2500, "height": 1686}
        assert payload["selected"] is True
        assert payload["name"] == menu.rich_menu_name({"housekeeping"})
        assert len(payload["chatBarText"]) <= 14  # LINE cap
        assert len(payload["areas"]) == 5

    def test_areas_are_uri_actions_within_canvas(self):
        # ota is menu-irrelevant since 2026-08-14, so this is the same
        # 4-button base+housekeeping menu — the only menu a real employee can
        # be assigned (see
        # test_every_real_variant_is_either_renderable_or_the_empty_base).
        # Worth more now than when it was one row: with two rows the bounds
        # check actually exercises a non-zero y offset.
        payload = menu.rich_menu_payload({"housekeeping", "ota"})
        width = payload["size"]["width"]
        height = payload["size"]["height"]
        assert len(payload["areas"]) == 5
        assert any(area["bounds"]["y"] > 0 for area in payload["areas"])
        for area in payload["areas"]:
            bounds = area["bounds"]
            assert bounds["x"] + bounds["width"] <= width
            assert bounds["y"] + bounds["height"] <= height
            assert area["action"]["type"] == "uri"
            assert area["action"]["uri"].startswith("https://")

    def test_payload_urls_follow_button_table(self):
        # The base half of this test is gone with the base buttons — an empty
        # variant has no payload at all (pinned in
        # test_the_empty_base_variant_has_no_renderable_menu).
        # The full maid menu, in table order, end to end:
        hk_uris = [
            area["action"]["uri"]
            for area in menu.rich_menu_payload({"housekeeping"})["areas"]
        ]
        assert hk_uris == [
            HK_BOARD_URL,
            "https://housekeeping.thehfhotel.org/staff/report",
            "https://housekeeping.thehfhotel.org/staff/stock",
            "https://housekeeping.thehfhotel.org/staff/receive",
            HK_REPORT_URL,
        ]

    def test_reception_payload_is_two_tiles_on_the_half_canvas(self):
        # Two tiles since the shared report tile (2026-09-02): the board it
        # reads and the report screen it verifies on. Still one row.
        payload = menu.rich_menu_payload({RECEPTION_GRANT})
        assert payload["size"] == {"width": 2500, "height": 843}
        assert payload["name"] == menu.rich_menu_name({RECEPTION_GRANT})
        assert [area["action"] for area in payload["areas"]] == [
            {"type": "uri", "label": "สถานะห้อง", "uri": HK_BOARD_URL},
            {"type": "uri", "label": REPORT_LABEL, "uri": HK_REPORT_URL},
        ]
        # The two split the canvas with nothing left over — no dead space to
        # tap into, and the second cell absorbs the odd pixel.
        assert [area["bounds"] for area in payload["areas"]] == [
            {"x": 0, "y": 0, "width": 1250, "height": 843},
            {"x": 1250, "y": 0, "width": 1250, "height": 843},
        ]

    def test_both_grants_payload_is_six_tiles_split_three_plus_three(self):
        payload = menu.rich_menu_payload({MENU_GRANT, RECEPTION_GRANT})
        assert payload["size"] == {"width": 2500, "height": 1686}
        assert len(payload["areas"]) == 6
        assert [area["action"]["uri"] for area in payload["areas"]] == [
            HK_BOARD_URL,
            "https://housekeeping.thehfhotel.org/staff/report",
            "https://housekeeping.thehfhotel.org/staff/stock",
            "https://housekeeping.thehfhotel.org/staff/receive",
            HK_BOARD_URL,
            HK_REPORT_URL,
        ]
        # The shared tile is ONE tap area, not two — the payload is where a
        # duplicated row would have become a seventh area LINE rejects.
        assert [a["action"]["uri"] for a in payload["areas"]].count(HK_REPORT_URL) == 1
        # 3+3: the full two-row grid, LINE's maximum. Pinned through the
        # bounds rather than menu_rows() because this is the payload LINE
        # actually receives, and 6 is the first real variant to fill it.
        top = [a["bounds"] for a in payload["areas"] if a["bounds"]["y"] == 0]
        bottom = [a["bounds"] for a in payload["areas"] if a["bounds"]["y"] > 0]
        assert len(top) == 3 and len(bottom) == 3
        assert sum(b["width"] for b in top) == 2500
        assert sum(b["width"] for b in bottom) == 2500
