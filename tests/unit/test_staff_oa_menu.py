"""Unit tests for the Employee Hub Role Menu model (app.services.staff_oa_menu).

Pins the grant → menu computation: which buttons a grant set reveals, the
variant keys, the LINE canvas layout, and the idempotency signature the
sync script keys on.

Scope note (2026-08-14): the owner re-scoped the Hub to a MAID tool —
"notify reception of cleaning progress and maid inventory" — so payroll,
OTA Desk and Reimbursement left MENU_BUTTONS, แม่บ้าน was deferred, and
finally the clock-in tile went too ("remove the clock-in button too").
``housekeeping`` is now the ONLY menu-relevant grant AND the only grant of
any kind that produces a button, which makes payroll and ota the sharpest
available examples of *menu-irrelevant* grants: real app grants an employee
genuinely holds that must not move the menu.

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

# The one grant that produces buttons, and the variant it mints.
MENU_GRANT = "housekeeping"


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

    def test_housekeeping_grant_alone_yields_three_buttons(self):
        # The count has tracked every scope change this menu has had: 4 with
        # clock-in + แม่บ้าน, 3 after clock-in went, 2 while แม่บ้าน was
        # deferred, and 3 again now that it is back (2026-08-14). Still the
        # LARGEST variant a real employee can get, and still the ONLY variant
        # with any buttons at all — `base` is deliberately empty.
        buttons = menu.buttons_for({"housekeeping"})
        assert len(buttons) == 3
        assert [b.label for b in buttons] == ["แม่บ้าน", "แจ้งซ่อม", "เบิกของ"]
        assert len(buttons) == len(menu.MENU_BUTTONS)

    def test_menu_irrelevant_grants_are_ignored(self):
        assert menu.buttons_for({"rooms", "portal"}) == menu.buttons_for(set())

    def test_unknown_grants_are_ignored(self):
        assert menu.buttons_for({"no-such-app"}) == menu.buttons_for(set())

    def test_button_order_follows_source_table_not_grant_order(self):
        # MENU_BUTTONS order — never the order the grants happened to arrive,
        # and never set-iteration order. (Base buttons would come first if
        # any still existed; none do since 2026-08-14.)
        expected = ["แม่บ้าน", "แจ้งซ่อม", "เบิกของ"]
        assert [b.label for b in menu.buttons_for(
            ["housekeeping", "payroll", "rooms"]
        )] == expected
        assert [b.label for b in menu.buttons_for(
            ["rooms", "payroll", "housekeeping"]
        )] == expected
        assert [b.label for b in menu.buttons_for(
            {"housekeeping", "ota", "payroll"}
        )] == expected


class TestMenuKeys:
    def test_no_grants_is_base(self):
        assert menu.menu_key(set()) == "base"

    def test_key_is_sorted_and_stable(self):
        # Written against MENU_GRANT_APP_IDS rather than a hardcoded pair
        # (was "base+ota+payroll") so it keeps testing the sort when a second
        # menu grant returns. Today it also pins the maximal key.
        every = sorted(menu.MENU_GRANT_APP_IDS)
        expected = "+".join(["base"] + every)
        assert expected == "base+housekeeping"
        assert menu.menu_key(set(every)) == expected
        assert menu.menu_key(list(reversed(every))) == expected
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
        # The maximal — and only — real variant is base+housekeeping, now 3
        # buttons after แม่บ้าน came back (2026-08-14). Still one row: the
        # half canvas holds up to 3.
        payload = menu.rich_menu_payload({"housekeeping"})
        assert payload["size"] == {"width": 2500, "height": 843}
        assert payload["selected"] is True
        assert payload["name"] == menu.rich_menu_name({"housekeeping"})
        assert len(payload["chatBarText"]) <= 14  # LINE cap
        assert len(payload["areas"]) == 3

    def test_areas_are_uri_actions_within_canvas(self):
        # ota is menu-irrelevant since 2026-08-14, so this is the same
        # 3-button base+housekeeping menu — the only menu a real employee can
        # be assigned (see
        # test_every_real_variant_is_either_renderable_or_the_empty_base).
        payload = menu.rich_menu_payload({"housekeeping", "ota"})
        width = payload["size"]["width"]
        height = payload["size"]["height"]
        assert len(payload["areas"]) == 3
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
            "https://hotel.thehfhotel.org/hk",
            "https://housekeeping.thehfhotel.org/staff/report",
            "https://housekeeping.thehfhotel.org/staff/stock",
        ]
