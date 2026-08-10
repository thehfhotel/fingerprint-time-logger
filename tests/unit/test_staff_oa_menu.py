"""Unit tests for the Employee Hub Role Menu model (app.services.staff_oa_menu).

Pins the grant → menu computation: which buttons a grant set reveals, the
variant keys, the LINE canvas layout, and the idempotency signature the
sync script keys on.
"""
import pytest

from app.services import staff_oa_menu as menu


class TestMenuButtonsForGrants:
    def test_base_menu_has_exactly_clockin_and_reimbursement(self):
        buttons = menu.buttons_for(set())
        assert [b.url for b in buttons] == [
            "https://erp.thehfhotel.org/qr-checkin",
            "https://reimbursement.thehfhotel.org",
        ]

    def test_payroll_grant_adds_payroll_button(self):
        buttons = menu.buttons_for({"payroll"})
        assert "https://payroll.thehfhotel.org" in [b.url for b in buttons]
        assert len(buttons) == 3

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

    def test_housekeeping_grant_alone_yields_five_buttons(self):
        # 2 base + แม่บ้าน + แจ้งซ่อม + เบิกของ (docs/housekeeping-ops-interfaces.md).
        assert len(menu.buttons_for({"housekeeping"})) == 5

    def test_menu_irrelevant_grants_are_ignored(self):
        assert menu.buttons_for({"rooms", "portal"}) == menu.buttons_for(set())

    def test_unknown_grants_are_ignored(self):
        assert menu.buttons_for({"no-such-app"}) == menu.buttons_for(set())

    def test_button_order_follows_source_table_not_grant_order(self):
        buttons = menu.buttons_for({"housekeeping", "ota", "payroll"})
        labels = [b.label for b in buttons]
        assert labels == [
            "สแกนเข้างาน", "เบิกค่าใช้จ่าย", "เงินเดือน", "OTA Desk",
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

    def test_all_three_grant_apps_together_exceed_the_six_button_cap(self):
        """payroll + ota + housekeeping = 7 buttons — past LINE's 6-button
        max per canvas, now that housekeeping alone contributes 3 (แม่บ้าน,
        แจ้งซ่อม, เบิกของ). No employee currently holds all three grants at
        once (maids hold housekeeping only; docs/housekeeping-ops-plan.md) —
        staff_oa_sync.py only ever builds variants for grant combinations
        real linked employees actually hold, so this is a documented latent
        limit, not something hit in practice. Flagged for the team lead
        rather than solved here (locked interface contract)."""
        buttons = menu.buttons_for({"housekeeping", "ota", "payroll"})
        assert len(buttons) == 7
        with pytest.raises(ValueError):
            menu.menu_size(len(buttons))

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
        assert len(payload["areas"]) == 3

    def test_areas_are_uri_actions_within_canvas(self):
        # housekeeping (3 buttons) + ota (1) + 2 base = 6 — right at the
        # LINE cap (see test_all_three_grant_apps_together_exceed_the_six_
        # button_cap for the payroll-too combination that overflows it).
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
            "https://reimbursement.thehfhotel.org",
        ]
