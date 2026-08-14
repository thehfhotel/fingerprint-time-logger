"""Unit tests for the Employee Hub Role Menu model (app.services.staff_oa_menu).

Pins the grant → menu computation: which buttons a grant set reveals, the
variant keys, the LINE canvas layout, and the idempotency signature the
sync script keys on.
"""
import pytest

from app.services import staff_oa_menu as menu


class TestMenuButtonsForGrants:
    def test_base_menu_has_exactly_clockin(self):
        # Reimbursement was removed from base 2026-08-14 (owner directive):
        # inside LINE's in-app browser Google OAuth is refused, dead-ending
        # managers at the Access picker. See the MENU_BUTTONS comment.
        buttons = menu.buttons_for(set())
        assert [b.url for b in buttons] == [
            "https://erp.thehfhotel.org/qr-checkin",
        ]

    def test_reimbursement_is_not_on_any_menu(self):
        every_grant = menu.buttons_for(menu.MENU_GRANT_APP_IDS)
        assert "https://reimbursement.thehfhotel.org" not in [
            b.url for b in every_grant
        ]

    def test_payroll_grant_adds_payroll_button(self):
        buttons = menu.buttons_for({"payroll"})
        assert "https://payroll.thehfhotel.org" in [b.url for b in buttons]
        assert len(buttons) == 2

    def test_ota_grant_adds_ota_desk_button(self):
        buttons = menu.buttons_for({"ota"})
        assert "https://ota.thehfhotel.org" in [b.url for b in buttons]

    def test_housekeeping_grant_adds_housekeeping_button(self):
        buttons = menu.buttons_for({"housekeeping"})
        assert "https://hotel.thehfhotel.org/hk" in [b.url for b in buttons]

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

    def test_housekeeping_grant_alone_yields_four_buttons(self):
        # 1 base + แม่บ้าน + แจ้งซ่อม + เบิกของ (docs/housekeeping-ops-interfaces.md).
        assert len(menu.buttons_for({"housekeeping"})) == 4

    def test_menu_irrelevant_grants_are_ignored(self):
        assert menu.buttons_for({"rooms", "portal"}) == menu.buttons_for(set())

    def test_unknown_grants_are_ignored(self):
        assert menu.buttons_for({"no-such-app"}) == menu.buttons_for(set())

    def test_button_order_follows_source_table_not_grant_order(self):
        buttons = menu.buttons_for({"housekeeping", "ota", "payroll"})
        labels = [b.label for b in buttons]
        assert labels == [
            "สแกนเข้างาน", "เงินเดือน", "OTA Desk",
            "แม่บ้าน", "แจ้งซ่อม", "เบิกของ",
        ]


class TestMenuKeys:
    def test_no_grants_is_base(self):
        assert menu.menu_key(set()) == "base"

    def test_key_is_sorted_and_stable(self):
        assert menu.menu_key({"payroll", "ota"}) == "base+ota+payroll"
        assert menu.menu_key(["ota", "payroll"]) == "base+ota+payroll"

    def test_key_ignores_menu_irrelevant_grants(self):
        assert menu.menu_key({"rooms", "portal", "payroll"}) == "base+payroll"

    def test_grants_for_menu_key_inverts_menu_key(self):
        grants = frozenset({"ota", "housekeeping"})
        assert menu.grants_for_menu_key(menu.menu_key(grants)) == grants

    def test_grants_for_menu_key_rejects_foreign_keys(self):
        with pytest.raises(ValueError):
            menu.grants_for_menu_key("richmenu-something")
        with pytest.raises(ValueError):
            menu.grants_for_menu_key("base+no-such-grant")


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

    def test_all_three_grant_apps_together_now_fit_the_six_button_cap(self):
        """payroll + ota + housekeeping = 6 buttons — exactly LINE's max.
        Dropping reimbursement from base (2026-08-14) took this combo from
        7 (over the cap; the variant was skipped by staff_oa_sync's guard)
        back down to a legal menu. The very next button row added to
        MENU_BUTTONS re-overflows it — the sync guard stays, and
        test_staff_oa_sync.py keeps it red-capable with a synthetic grant."""
        buttons = menu.buttons_for({"housekeeping", "ota", "payroll"})
        assert len(buttons) == 6
        assert menu.menu_size(len(buttons)) == (2500, 1686)

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
        assert menu.menu_signature({"payroll"}) == menu.menu_signature({"payroll"})

    def test_signature_differs_between_variants(self):
        assert menu.menu_signature(set()) != menu.menu_signature({"payroll"})

    def test_rich_menu_name_embeds_prefix_key_and_signature(self):
        name = menu.rich_menu_name({"ota"})
        prefix, key, signature = name.split(":")
        assert prefix == "staffhub"
        assert key == "base+ota"
        assert signature == menu.menu_signature({"ota"})
        assert len(name) <= 300  # LINE's rich-menu name cap

    def test_is_staff_hub_menu_name(self):
        assert menu.is_staff_hub_menu_name(menu.rich_menu_name(set()))
        assert not menu.is_staff_hub_menu_name("some-other-menu")


class TestRichMenuPayload:
    def test_payload_matches_line_richmenu_schema(self):
        payload = menu.rich_menu_payload({"payroll"})
        assert payload["size"] == {"width": 2500, "height": 843}
        assert payload["selected"] is True
        assert payload["name"] == menu.rich_menu_name({"payroll"})
        assert len(payload["chatBarText"]) <= 14  # LINE cap
        assert len(payload["areas"]) == 2

    def test_areas_are_uri_actions_within_canvas(self):
        # housekeeping (3 buttons) + ota (1) + 1 base = 5 (the payroll-too
        # combination sits exactly at the 6 cap; see test_all_three_grant_
        # apps_together_now_fit_the_six_button_cap).
        payload = menu.rich_menu_payload({"housekeeping", "ota"})
        width = payload["size"]["width"]
        height = payload["size"]["height"]
        for area in payload["areas"]:
            bounds = area["bounds"]
            assert bounds["x"] + bounds["width"] <= width
            assert bounds["y"] + bounds["height"] <= height
            assert area["action"]["type"] == "uri"
            assert area["action"]["uri"].startswith("https://")

    def test_payload_urls_follow_button_table(self):
        payload = menu.rich_menu_payload(set())
        uris = [area["action"]["uri"] for area in payload["areas"]]
        assert uris == [
            "https://erp.thehfhotel.org/qr-checkin",
        ]
