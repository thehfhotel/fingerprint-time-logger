"""Unit tests for the rich-menu image renderer (app.services.staff_oa_images).

Pins the LINE contract (exact canvas sizes, PNG, <1MB) and the bundled
Thai font that makes rendering deterministic on any machine.

WHICH BUTTON COUNTS ARE REAL, AND WHICH NEED SYNTHETIC BUTTONS
--------------------------------------------------------------
The table has 9 rows since 2026-09-18: แจ้งลา, the one ungated base tile
every linked employee sees (``grant_app_id=None``, a message action); then
แม่บ้าน / แจ้งซ่อม / สต๊อกของ / รับของมาส่ง behind `housekeeping`, สถานะห้อง /
งานซ่อมค้าง behind `reception`, and TWO shared tiles revealed by either
grant — the report tile (รายงานแม่บ้าน) and จัดการงานซ่อม (the
outstanding-maintenance queue page). Both สถานะห้อง and งานซ่อมค้าง carry
``hidden_by_grant_app_ids={"housekeeping"}`` (the same reasoning twice: a
housekeeping+reception holder already has a better tile for the same job via
แม่บ้าน / จัดการงานซ่อม respectively), so the row count and the SHOWN button
count are no longer the same number for either variant that includes
`housekeeping` — the real variants are `base` (1, แจ้งลา alone),
`base+reception` (5, แจ้งลา plus the original four), `base+housekeeping` (7,
since แจ้งลา joined every variant) and `base+housekeeping+reception` (7 —
สถานะห้อง and งานซ่อมค้าง both hidden, จัดการงานซ่อม shown in one of their
places).

That covers both canvases and three of the four two-row layouts anyone can
actually be handed: the 3+2 split (base+reception) and 4+3 (the
housekeeping variants). The counts no grant set can produce are 2, 3, 4, 6
and 8 (``MAX_BUTTONS``, the Hub's own layout ceiling since 2026-09-18 — LINE
itself allows up to 20 rich-menu areas). They are still live production
code — ``menu_size()`` switches on the button count and ``menu_rows()`` lays
4 through 8 out as 2+2 / 3+2 / 3+3 / 4+3 / 4+4 — and one MenuButton row (or
hide rule) leaving or arriving re-shuffles which counts are reachable, so
the fixtures DERIVE the unreachable set from what the real grants actually
SHOW (not from ``len(MENU_BUTTONS)``, which no longer equals the biggest
real variant) — see ``REAL_VARIANT_BUTTON_COUNTS`` below.
``TestFixturePremise`` asserts that derivation, so these tests can never
quietly stop covering a layout.

Base is a REAL, renderable one-tile menu now (2026-09-18) — ``buttons_for(
set())`` is no longer ``()``, ``menu_size(0)`` is the only thing that still
raises. ``REAL_VARIANT_GRANTS`` below includes the empty grant set for
exactly this reason.

REAL VS SYNTHETIC VARIANTS BELOW
---------------------------------
Real variants (``buttons_for({...})``) exercise the production grant table
end to end. Synthetic buttons (``_synthetic_buttons`` / ``_buttons_of_count``)
mint button lists no grant set produces, so the button-count-driven layout
code (``menu_size`` / ``menu_rows`` / ``menu_cells``) stays covered for the
counts (2, 3, 4, 6, 8) production never reaches. Synthetic buttons always
name one of the seven canonical asset keys directly (e.g. "time",
"announcement") rather than a MenuButton glyph alias, so they exercise real,
approved artwork through ``resolve_glyph_asset``'s identity entries — never
a placeholder. "leave" dropped out of that pool on 2026-09-18: it is now the
canonical key a REAL button (แจ้งลา) names directly, so ``ORPHANED_GLYPHS``
(derived, not listed) no longer offers it.
"""
import inspect
import io
import itertools
import json
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageOps, ImageStat

from app.services import staff_oa_images as images
from app.services.staff_oa_menu import (
    MAX_BUTTONS,
    MENU_BUTTONS,
    MENU_GRANT_APP_IDS,
    MenuButton,
    buttons_for,
    menu_cells,
    menu_size,
)

LINE_IMAGE_MAX_BYTES = 1024 * 1024

# The only two canvases LINE accepts, spelled out as literals on purpose:
# this file is where that external contract is pinned, so it must not be
# derived from the constants in staff_oa_menu that it is checking.
HALF_HEIGHT_CANVAS = (2500, 843)   # 1-3 buttons, one row
FULL_HEIGHT_CANVAS = (2500, 1686)  # 4-8 buttons, two rows

# Was ``len(MENU_BUTTONS)`` — true only while every row was actually SHOWN
# together. That stopped holding on 2026-09-06: สถานะห้อง and งานซ่อมค้าง
# both carry ``hidden_by_grant_app_ids={"housekeeping"}``, so the table has
# more rows than the biggest variant anyone is actually SHOWN (both grants).
# ``buttons_for(MENU_GRANT_APP_IDS)`` is what a real employee holding every
# menu-relevant grant actually sees, so it — not the row count — is the
# biggest real variant. Includes แจ้งลา (2026-09-18), the base tile every
# grant set reveals.
MAX_REAL_BUTTON_COUNT = len(buttons_for(MENU_GRANT_APP_IDS))

# The two real grants, and the button counts each reveals ALONE (both
# include แจ้งลา as their first tile since 2026-09-18). Named rather than
# inlined because several tests below turn on the maid menu and the
# both-grants menu — even though จัดการงานซ่อม's widening (2026-09-06) means
# they are now the SAME number, the two are still built from different grant
# sets and worth telling apart by name.
HOUSEKEEPING_BUTTON_COUNT = len(buttons_for({"housekeeping"}))
RECEPTION_BUTTON_COUNT = len(buttons_for({"reception"}))

# Every button count a REAL employee can be handed an image for — the
# powerset of the menu grants, INCLUDING the empty base, which is a real,
# renderable one-tile menu since แจ้งลา (2026-09-18) — there is no longer an
# empty variant to subtract. Derived rather than listed: which counts are
# reachable changes every time a MenuButton row is added, removed, or SHARED
# between grants, and the shared row is why the counts no longer simply add
# up (7 + 5 tiles - 1 (แจ้งลา, only counted once) - 2 (shared) - 2 (hidden)
# = 7, not 9).
REAL_VARIANT_BUTTON_COUNTS = frozenset(
    len(buttons_for(frozenset(combo)))
    for size in range(len(MENU_GRANT_APP_IDS) + 1)
    for combo in itertools.combinations(sorted(MENU_GRANT_APP_IDS), size)
)

# The layouts that exist in production code but that no grant set reaches, so
# their only coverage is the fixtures below. {2, 3, 4, 6, 8} today, derived
# against MAX_BUTTONS (the Hub's own layout ceiling, 2026-09-18) rather than
# a hard-coded LINE cap — LINE itself allows up to 20 rich-menu areas.
UNREACHABLE_BUTTON_COUNTS = tuple(
    count
    for count in range(1, MAX_BUTTONS + 1)
    if count not in REAL_VARIANT_BUTTON_COUNTS
)

# Canonical asset keys that resolve_glyph_asset already accepts directly (via
# GLYPH_ASSET_KEYS's identity entries) but that no current MenuButton names —
# every real button reaches its asset through one of its glyph aliases
# (broom, wrench, box, tray, clipboard, photo_sheet, wrench_list) or, since
# 2026-09-18, the "leave" identity entry directly (แจ้งลา). Used to pad
# synthetic buttons for counts no grant set reaches, so those fixtures wear
# canonical-key names nothing else in this file already covers and always
# resolve to real, approved artwork. Derived, not listed, so a canonical key
# a future MenuButton starts naming directly drops itself out of the padding
# pool automatically — "leave" is the proof: it dropped out the day แจ้งลา
# shipped.
ORPHANED_GLYPHS = tuple(
    sorted(set(images.GLYPH_ASSET_KEYS) - {button.glyph for button in MENU_BUTTONS})
)
PADDING_GLYPHS = ORPHANED_GLYPHS or tuple(sorted(images.GLYPH_ASSET_KEYS))

# One orphaned canonical key, used where a test needs "an asset no current
# tile happens to name" — derived rather than hard-coded to "leave" (which
# stopped being orphaned on 2026-09-18) so this keeps working the next time
# a MenuButton starts naming a previously-orphaned key directly.
ORPHANED_ASSET_KEY = ORPHANED_GLYPHS[0]

SYNTHETIC_GRANT = "extra"

REPO_ROOT = Path(__file__).resolve().parents[2]
CROPS_MANIFEST_PATH = REPO_ROOT / "assets" / "staff_oa" / "icons" / "crops.json"

EXPECTED_ICON_ASSETS = {
    "leave": "leave_calendar.png",
    "time": "time_clock.png",
    "announcement": "announcement_megaphone.png",
    "handbook": "handbook_document.png",
    "maintenance": "maintenance_tools.png",
    "contacts": "team_contacts.png",
    "suggestions": "suggestions_chat.png",
}

# The identity entries (canonical key -> itself) plus the seven MenuButton
# glyph aliases production actually uses today, spelled out on purpose: this
# file is where that mapping contract is pinned, so it must not be derived
# from GLYPH_ASSET_KEYS itself.
EXPECTED_GLYPH_ASSET_KEYS = {
    **{key: key for key in EXPECTED_ICON_ASSETS},
    "broom": "contacts",
    "wrench": "maintenance",
    "box": "handbook",
    "tray": "time",
    "clipboard": "handbook",
    "photo_sheet": "suggestions",
    "wrench_list": "maintenance",
}


def _render(buttons):
    png_bytes = images.render_menu_image(buttons)
    return png_bytes, Image.open(io.BytesIO(png_bytes))


def _render_and_open(grants):
    return _render(buttons_for(grants))


def _synthetic_buttons(count, glyphs=PADDING_GLYPHS):
    """``count`` buttons no grant set produces, for counts the real table
    cannot reach. Thai labels so the bundled font is still exercised;
    .invalid is reserved by RFC 2606 and resolves nowhere (the renderer only
    reads the URL for its English fallback label, but an unroutable host
    makes "none of this is real" explicit)."""
    return tuple(
        MenuButton(
            grant_app_id=SYNTHETIC_GRANT,
            label=f"ทดสอบ {index + 1}",
            url=f"https://synthetic-{index + 1}.invalid/",
            glyph=glyphs[index % len(glyphs)],
        )
        for index in range(count)
    )


def _with_glyph(button, glyph):
    """The same button wearing a different glyph — the pixel-diff control."""
    return MenuButton(
        grant_app_id=button.grant_app_id,
        also_grant_app_ids=button.also_grant_app_ids,
        label=button.label,
        url=button.url,
        glyph=glyph,
    )


def _buttons_of_count(button_count):
    """A legal button list of exactly ``button_count`` buttons, for counts no
    grant set produces.

    Real buttons first, padded with synthetic ones only if the real table is
    too short — which it no longer is for any count up to MAX_BUTTONS, now
    that the table sits at 9 rows. Deriving that (rather than hard-coding how
    many extras it takes) is the point: the sibling sync test broke once
    already by assuming a button count the real table no longer produced,
    and this keeps working whether the table shrinks again or the cap is
    somehow raised.
    """
    real = list(MENU_BUTTONS[:button_count])
    return tuple(real + list(_synthetic_buttons(button_count - len(real))))


class TestFixturePremise:
    """Some fixtures below drive counts no employee can be handed — prove
    they are the right counts, and that the real ones are covered for real."""

    def test_the_base_variant_is_a_real_one_tile_menu(self):
        # Production table, nothing patched. Owner decision 2026-09-18:
        # แจ้งลา is a base tile, so the empty grant set now renders a real,
        # one-tile menu instead of nothing — the single-button tests below
        # can (and some still do) use synthetic buttons for a PARTICULAR
        # asset, but buttons_for(set()) is no longer the reason they must.
        buttons = buttons_for(frozenset())
        assert len(buttons) == 1
        assert menu_size(len(buttons)) == HALF_HEIGHT_CANVAS

    def test_the_real_table_now_fills_the_layout_ceiling_close_to_exactly(self):
        # Production table, nothing patched. The biggest real variant reached
        # the two-row canvas on 2026-08-17 (4 tiles), LINE's old 6-button
        # informal cap on 2026-09-02 (รายงานแม่บ้าน), and now sits one tile
        # under MAX_BUTTONS = 8 (the Hub's own layout ceiling, 2026-09-18,
        # after แจ้งลา joined every variant). This assertion going red is the
        # headroom alarm.
        assert len(buttons_for(MENU_GRANT_APP_IDS)) == MAX_REAL_BUTTON_COUNT
        assert MAX_REAL_BUTTON_COUNT == 7 == MAX_BUTTONS - 1
        assert menu_size(MAX_REAL_BUTTON_COUNT) == FULL_HEIGHT_CANVAS

    def test_the_real_table_spans_both_canvases(self):
        # `base` alone (แจ้งลา, 2026-09-18) is the only real variant still on
        # the half-height canvas; `reception` (5 tiles) and `housekeeping` (7)
        # are both full-height — so the real table covers both canvases, and
        # only the padded fixtures below exercise the unreachable full-height
        # counts (2+2, 3+3, 4+4).
        assert RECEPTION_BUTTON_COUNT == 5
        assert HOUSEKEEPING_BUTTON_COUNT == 7
        assert menu_size(1) == HALF_HEIGHT_CANVAS
        assert menu_size(RECEPTION_BUTTON_COUNT) == FULL_HEIGHT_CANVAS
        assert menu_size(HOUSEKEEPING_BUTTON_COUNT) == FULL_HEIGHT_CANVAS

    def test_the_shared_and_hidden_tiles_are_why_the_counts_do_not_add_up(self):
        # 7 + 5 = 12, but the both-grants menu is SEVEN: แจ้งลา is counted
        # once (it is base, not part of either grant's own count, but both
        # counts already include it as their first tile — see the -1 below);
        # รายงานแม่บ้าน and จัดการงานซ่อม are each one row revealed by either
        # grant (counted once in the union, not twice); and both สถานะห้อง
        # and งานซ่อมค้าง are hidden entirely once `housekeeping` is also held
        # (แม่บ้าน / จัดการงานซ่อม already cover the same ground with full
        # access). If a future edit duplicates a shared row or drops a hide,
        # this goes red here — before the both-grants variant silently grows
        # past MAX_BUTTONS.
        shared = [
            button for button in MENU_BUTTONS
            if len(button.grant_app_ids) > 1
        ]
        assert len(shared) == 2
        assert {b.label for b in shared} == {"รายงานแม่บ้าน", "จัดการงานซ่อม"}
        hidden_in_both = [
            button for button in buttons_for({"reception"})
            if button not in buttons_for(MENU_GRANT_APP_IDS)
        ]
        assert len(hidden_in_both) == 2
        assert {b.label for b in hidden_in_both} == {"สถานะห้อง", "งานซ่อมค้าง"}
        leave_double_counted = 1  # แจ้งลา is in both HOUSEKEEPING_ and RECEPTION_BUTTON_COUNT
        assert (
            HOUSEKEEPING_BUTTON_COUNT + RECEPTION_BUTTON_COUNT
            - leave_double_counted - len(shared) - len(hidden_in_both)
            == MAX_REAL_BUTTON_COUNT
        )

    def test_the_unreachable_counts_are_the_ones_no_grant_set_produces(self):
        # Derived, not listed — the module docstring's claim, asserted.
        # {1, 5, 7} are reachable (base, reception, housekeeping/both);
        # {2, 3, 4, 6, 8} are not.
        assert REAL_VARIANT_BUTTON_COUNTS == {
            1, RECEPTION_BUTTON_COUNT, HOUSEKEEPING_BUTTON_COUNT, MAX_REAL_BUTTON_COUNT
        }
        assert REAL_VARIANT_BUTTON_COUNTS == {1, 5, 7}
        assert UNREACHABLE_BUTTON_COUNTS == (2, 3, 4, 6, 8)

    @pytest.mark.parametrize("button_count", UNREACHABLE_BUTTON_COUNTS)
    def test_the_fixture_mints_counts_the_real_table_cannot(self, button_count):
        buttons = _buttons_of_count(button_count)
        assert len(buttons) == button_count
        assert button_count not in REAL_VARIANT_BUTTON_COUNTS
        assert menu_size(button_count) in {HALF_HEIGHT_CANVAS, FULL_HEIGHT_CANVAS}


class TestBundledThaiFont:
    def test_repo_bundles_a_thai_font(self):
        path = images.find_thai_font_path()
        assert path is not None
        assert "assets" in path and "Prompt" in path


class TestApprovedIconAssetRegistry:
    """Item 1: ICON_ASSETS is exactly the seven approved keys, every file it
    names exists under ICON_ROOT, and that file set matches crops.json's —
    the manifest and the renderer must never drift apart."""

    def test_icon_assets_has_exactly_the_seven_canonical_keys(self):
        assert images.ICON_ASSETS == EXPECTED_ICON_ASSETS

    def test_icon_root_is_the_repo_assets_directory(self):
        expected = REPO_ROOT / "assets" / "staff_oa" / "icons"
        assert os.path.realpath(images.ICON_ROOT) == os.path.realpath(str(expected))

    def test_every_asset_file_exists_under_icon_root(self):
        for key, filename in images.ICON_ASSETS.items():
            path = images.icon_asset_path(key)
            assert path == os.path.join(images.ICON_ROOT, filename)
            assert os.path.isfile(path), f"{key} -> {filename} missing under ICON_ROOT"

    def test_icon_assets_files_equal_crops_json_names(self):
        with open(CROPS_MANIFEST_PATH, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest_names = set(manifest["crops"].keys())
        assert set(images.ICON_ASSETS.values()) == manifest_names
        on_disk = {p.name for p in Path(images.ICON_ROOT).glob("*.png")}
        assert on_disk == manifest_names


class TestApprovedIconAssetFiles:
    """Item 2: every asset, opened directly (not via load_icon_asset's own
    ``.convert("RGBA")``, which would mask an originally wrong mode), is a
    344x293 RGBA PNG — the guard against the old 64px JPEG thumbnails."""

    @pytest.mark.parametrize("key", sorted(EXPECTED_ICON_ASSETS))
    def test_asset_is_a_344x293_rgba_png(self, key):
        path = images.icon_asset_path(key)
        with Image.open(path) as opened:
            assert opened.format == "PNG"
            assert opened.mode == "RGBA"
            assert opened.size == (344, 293)


class TestGlyphResolution:
    """Item 3: every MenuButton glyph resolves to a real, existing asset, and
    the whole glyph->key table matches the owner-approved mapping exactly."""

    def test_glyph_asset_keys_matches_the_approved_table_exactly(self):
        assert images.GLYPH_ASSET_KEYS == EXPECTED_GLYPH_ASSET_KEYS

    @pytest.mark.parametrize(
        "button", MENU_BUTTONS, ids=[button.label for button in MENU_BUTTONS]
    )
    def test_every_menu_button_glyph_resolves_to_an_existing_asset(self, button):
        key = images.resolve_glyph_asset(button.glyph)
        assert key in images.ICON_ASSETS
        assert key == EXPECTED_GLYPH_ASSET_KEYS[button.glyph]
        assert os.path.isfile(images.icon_asset_path(key))


class TestUnknownGlyphFailsClosed:
    """Item 4: a glyph naming nothing in the registry must stop rendering,
    never silently skip the icon."""

    def test_unknown_glyph_raises_approved_asset_error(self):
        real_button = MENU_BUTTONS[0]
        unknown = _with_glyph(real_button, "no-such-glyph")
        with pytest.raises(images.ApprovedAssetError):
            images.render_menu_image((unknown,))

    def test_resolve_glyph_asset_itself_raises_for_unknown_glyph(self):
        with pytest.raises(images.ApprovedAssetError):
            images.resolve_glyph_asset("no-such-glyph")


@pytest.fixture
def isolated_icon_root(tmp_path, monkeypatch):
    """A writable copy of the real icon directory, swapped in for ICON_ROOT
    for the duration of one test — so a test can delete or corrupt an asset
    without touching the committed files. Clears the lru_cache before AND
    after, so neither a previous test's cached Image nor this test's leaks
    across the ICON_ROOT swap."""
    icons_copy = tmp_path / "icons"
    shutil.copytree(images.ICON_ROOT, icons_copy)
    monkeypatch.setattr(images, "ICON_ROOT", str(icons_copy))
    images.load_icon_asset.cache_clear()
    yield icons_copy
    images.load_icon_asset.cache_clear()


class TestMissingOrCorruptAssetsFailClosed:
    """Item 5: any way an approved asset can go missing or stop being a
    readable PNG must raise ApprovedAssetError, whether or not the current
    real table even uses that particular asset."""

    # แจ้งซ่อม (wrench) is a real MENU_BUTTONS row and resolves to
    # "maintenance" — used directly by this test as "the real tile".
    REAL_TILE = next(button for button in MENU_BUTTONS if button.glyph == "wrench")

    def test_deleting_the_asset_a_real_tile_uses_fails_closed(self, isolated_icon_root):
        key = images.resolve_glyph_asset(self.REAL_TILE.glyph)
        (isolated_icon_root / images.ICON_ASSETS[key]).unlink()
        with pytest.raises(images.ApprovedAssetError):
            images.render_menu_image((self.REAL_TILE,))

    def test_deleting_an_asset_no_current_tile_uses_still_fails_closed(self, isolated_icon_root):
        # ORPHANED_ASSET_KEY has no MenuButton glyph naming it today (see
        # ORPHANED_GLYPHS — "leave" itself dropped out of this pool on
        # 2026-09-18, since แจ้งลา now names it directly), so nothing in this
        # render would ask for it by name — verify_approved_assets() must
        # check it anyway.
        (isolated_icon_root / images.ICON_ASSETS[ORPHANED_ASSET_KEY]).unlink()
        with pytest.raises(images.ApprovedAssetError):
            images.render_menu_image((self.REAL_TILE,))

    def test_jpeg_saved_under_a_png_name_fails_closed(self, isolated_icon_root):
        key = images.resolve_glyph_asset(self.REAL_TILE.glyph)
        target = isolated_icon_root / images.ICON_ASSETS[key]
        Image.new("RGB", (344, 293), (10, 20, 30)).save(target, format="JPEG")
        with pytest.raises(images.ApprovedAssetError):
            images.render_menu_image((self.REAL_TILE,))

    def test_load_icon_asset_itself_raises_for_a_missing_file(self, isolated_icon_root):
        (isolated_icon_root / images.ICON_ASSETS[ORPHANED_ASSET_KEY]).unlink()
        with pytest.raises(images.ApprovedAssetError):
            images.load_icon_asset(ORPHANED_ASSET_KEY)


class TestNoLegacyFallback:
    """Item 6: nothing from the old programmatic-glyph-drawing era survives —
    no registry, no ``_glyph_*`` helpers, no leftover meal tile."""

    def test_no_glyph_renderers_registry(self):
        assert not hasattr(images, "_GLYPH_RENDERERS")

    def test_no_attribute_name_starts_with_glyph_underscore(self):
        assert not any(name.startswith("_glyph_") for name in vars(images))

    def test_module_defines_no_function_named_with_a_glyph_prefix(self):
        assert not any(
            name.startswith("_glyph") and inspect.isfunction(getattr(images, name))
            for name in dir(images)
        )

    def test_source_defines_no_legacy_registry(self):
        # Not a literal "_glyph_" substring scan: the approved public name
        # ``resolve_glyph_asset`` legitimately contains that substring, so
        # the source-level check that actually distinguishes "legacy helper"
        # from "approved public function" is the simplest one the spec
        # itself falls back to — no function name starts with "_glyph" (see
        # the two tests above) — plus the registry name itself never
        # reappears, literally, anywhere.
        source = inspect.getsource(images)
        assert "_GLYPH_RENDERERS" not in source

    def test_meal_is_gone(self):
        assert "meal" not in images.ICON_ASSETS
        assert "meal" not in images.GLYPH_ASSET_KEYS


REAL_VARIANT_GRANTS = (
    frozenset(),  # base — a real, renderable one-tile (แจ้งลา) menu since 2026-09-18
    frozenset({"reception"}),
    frozenset({"housekeeping"}),
    frozenset({"housekeeping", "reception"}),
)


def _variant_id(grants):
    return "+".join(sorted(grants)) or "base"


class TestRealVariantsRenderWithinLinesContract:
    """Item 7: PNG, exact canvas, under LINE's 1MB cap, for every real
    variant, base (2026-09-18) included."""

    @pytest.mark.parametrize("grants", REAL_VARIANT_GRANTS, ids=_variant_id)
    def test_real_variant_is_a_conforming_png(self, grants):
        buttons = buttons_for(grants)
        png_bytes, image = _render(buttons)
        assert image.format == "PNG"
        assert image.size == menu_size(len(buttons))
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES


def _expected_paste(button, cell):
    """Reproduce the renderer's own icon_size/centre/contain math (spec
    section "Rendering rules") to get the exact box the artwork should land
    in — never a hand-guessed rectangle."""
    key = images.resolve_glyph_asset(button.glyph)
    asset = images.load_icon_asset(key)
    icon_size = max(230, min(400, min(cell["width"], cell["height"]) * 48 // 100))
    cx = cell["x"] + cell["width"] // 2
    cy = cell["y"] + cell["height"] * 39 // 100
    fitted = ImageOps.contain(asset, (icon_size, icon_size), method=Image.Resampling.LANCZOS)
    left = cx - fitted.width // 2
    top = cy - fitted.height // 2
    box = (left, top, left + fitted.width, top + fitted.height)
    return fitted, box


def _fraction_differs_from_surface(region, threshold=24):
    surface_plane = Image.new("RGB", region.size, images.SURFACE)
    diff = ImageChops.difference(region, surface_plane)
    bands = diff.split()
    masks = [band.point(lambda v: 255 if v > threshold else 0) for band in bands]
    combined = masks[0]
    for mask in masks[1:]:
        combined = ImageChops.lighter(combined, mask)
    hits = ImageStat.Stat(combined).sum[0] / 255
    total = region.size[0] * region.size[1]
    return hits / total


class TestArtworkIsActuallyVisible:
    """Item 8: the pasted artwork, not a blank or mis-cropped tile — checked
    against decoded pixels only, never a rasteriser-dependent constant."""

    @pytest.mark.parametrize("grants", REAL_VARIANT_GRANTS, ids=_variant_id)
    def test_every_cell_shows_its_icon(self, grants):
        buttons = buttons_for(grants)
        png_bytes, _image = _render(buttons)
        rendered = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        cells = menu_cells(len(buttons))
        for button, cell in zip(buttons, cells):
            fitted, box = _expected_paste(button, cell)
            region = rendered.crop(box)

            # At least a fifth of the paste box must visibly differ from
            # plain SURFACE white — proves something was actually drawn.
            assert _fraction_differs_from_surface(region) >= 0.20, (
                f"{button.label!r} ({button.glyph!r}) looks blank in its cell"
            )

            # The region's mean colour must match the same asset, contained
            # the same way, composited on the same white — proves it is
            # THIS asset (not a mismatched crop or a stale cached one).
            white_canvas = Image.new("RGB", fitted.size, images.SURFACE)
            if fitted.mode == "RGBA":
                white_canvas.paste(fitted, (0, 0), fitted)
            else:
                white_canvas.paste(fitted, (0, 0))
            actual_mean = ImageStat.Stat(region).mean
            expected_mean = ImageStat.Stat(white_canvas).mean
            for actual, expected in zip(actual_mean, expected_mean):
                assert abs(actual - expected) <= 8, (
                    f"{button.label!r} ({button.glyph!r}) mean colour drifted "
                    f"from its own asset: {actual_mean} vs {expected_mean}"
                )


class TestDistinctAndDeterministicRendering:
    """Item 9: different assets really do produce different pixels, and the
    same input always produces the exact same bytes."""

    def test_distinct_glyphs_give_distinct_tiles(self):
        base = MenuButton(
            grant_app_id=SYNTHETIC_GRANT,
            label="ทดสอบ",
            url="https://synthetic.invalid/",
            glyph="wrench",
        )
        _wrench_bytes, wrench_image = _render((base,))
        _broom_bytes, broom_image = _render((_with_glyph(base, "broom"),))
        assert wrench_image.size == broom_image.size
        assert wrench_image.tobytes() != broom_image.tobytes()

    def test_identical_input_renders_identical_bytes(self):
        buttons = buttons_for({"reception"})
        first = images.render_menu_image(buttons)
        second = images.render_menu_image(buttons)
        assert first == second


class TestCanvasSizingAcrossButtonCounts:
    """Item 10: the half-height canvas still renders for 1-3 buttons naming
    canonical keys directly, and the full-height canvas still renders for
    4-8 (real buttons padded with synthetic canonical-key ones)."""

    @pytest.mark.parametrize("button_count", (1, 2, 3))
    def test_half_height_canvas_renders_with_canonical_key_glyphs(self, button_count):
        buttons = _synthetic_buttons(button_count, glyphs=("time", "announcement", "handbook"))
        png_bytes, image = _render(buttons)
        assert image.format == "PNG"
        assert image.size == HALF_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    @pytest.mark.parametrize("button_count", (4, 5, 6, 7, 8))
    def test_full_height_canvas_renders_png_within_lines_cap(self, button_count):
        # 5 (reception) and 7 (the maid menu and both-grants alike) are real
        # variants since แจ้งลา joined every variant (2026-09-18); 4, 6 and 8
        # are not, so those three are padded with synthetic canonical-key
        # buttons via _buttons_of_count(). This test predates that
        # distinction and stays as a direct, non-grant-driven check of the
        # 2+2 / 3+2 / 3+3 / 4+3 / 4+4 layout code itself, including
        # MAX_BUTTONS = 8 (the Hub's own layout ceiling, 2026-09-18) — the
        # 8-tile canvas is the one PNG-size test the spec calls out by name.
        png_bytes, image = _render(_buttons_of_count(button_count))
        assert image.format == "PNG"
        assert image.size == FULL_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES


# _draw_cell's own margin, spelled out here (not imported) for the same
# reason HALF_HEIGHT_CANVAS/FULL_HEIGHT_CANVAS are literals above: this file
# pins the external contract, so it must not silently track a renderer
# refactor that moves the constant.
_CELL_MARGIN = 28


def _expected_label_for(button, thai_capable):
    return button.label if thai_capable else images._english_fallback_label(button)


class TestLabelFitsCell:
    """Item 11 (2026-09-18): ``fit_label_font`` — the narrower 4-column rows
    (625 px cells) are why it exists at all. Every real variant's label, at
    whatever size the fitter lands on, must fit inside its own card."""

    @pytest.mark.parametrize("grants", REAL_VARIANT_GRANTS, ids=_variant_id)
    def test_every_real_label_fits_its_cell(self, grants):
        buttons = buttons_for(grants)
        cells = menu_cells(len(buttons))
        thai_capable = images.find_thai_font_path() is not None
        for button, cell in zip(buttons, cells):
            label = _expected_label_for(button, thai_capable)
            max_width = (cell["width"] - 2 * _CELL_MARGIN) - 60
            font, _ = images.fit_label_font(label, max_width)
            assert font.getlength(label) <= max_width, (
                f"{button.label!r} overflows its {cell['width']}px cell "
                f"at font size {font.size}"
            )

    def test_no_real_label_needs_to_shrink_below_the_start_size_today(self):
        # Documents the current headroom rather than asserting it can never
        # change: every real label fits its cell at the top of the range
        # (100px) without stepping down at all. If a future label change
        # makes this go red, that is fit_label_font doing its job — the
        # label still renders (see the test above), just at a smaller size —
        # not a bug in this test.
        thai_capable = images.find_thai_font_path() is not None
        for grants in REAL_VARIANT_GRANTS:
            buttons = buttons_for(grants)
            cells = menu_cells(len(buttons))
            for button, cell in zip(buttons, cells):
                label = _expected_label_for(button, thai_capable)
                max_width = (cell["width"] - 2 * _CELL_MARGIN) - 60
                font, _ = images.fit_label_font(label, max_width)
                assert font.size == 100, (
                    f"{button.label!r} unexpectedly needed to shrink "
                    f"(landed at {font.size}px)"
                )

    def test_fit_label_font_steps_down_toward_the_floor_when_it_must(self):
        # A label wide enough that even the widest real cell would refuse it
        # at 100px must shrink, in `step`-sized decrements, and land on the
        # largest size that actually fits.
        long_label = "ป้ายทดสอบยาวมากสำหรับช่องแคบ" * 3
        font, _ = images.fit_label_font(long_label, max_width=400)
        assert font.size < 100
        assert (100 - font.size) % 4 == 0  # the default step
        assert font.size >= 56  # the default floor

    def test_fit_label_font_never_returns_below_the_floor(self):
        # A label so long that even the floor size overflows the box must
        # still stop at the floor — never smaller — so the tile is at least
        # legible rather than vanishing toward zero.
        impossible_label = "ป้ายชื่อยาวเกินกว่าจะพอดีกับช่องที่แคบที่สุดของเมนูนี้ได้เลยจริงๆ" * 3
        font, _ = images.fit_label_font(impossible_label, max_width=10)
        assert font.size == 56

    def test_fit_label_font_respects_custom_start_floor_and_step(self):
        font, _ = images.fit_label_font(
            "กxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            max_width=50, start=40, floor=20, step=5,
        )
        assert font.size >= 20
        assert (40 - font.size) % 5 == 0

    def test_fit_label_font_returns_the_thai_capability_flag(self):
        # Same shape as _load_label_font's own return — callers (_draw_cell)
        # rely on this to decide nothing extra; fit_label_font must not drop
        # the flag silently.
        _font, thai_capable = images.fit_label_font("แจ้งลา", max_width=2000)
        assert thai_capable is (images.find_thai_font_path() is not None)
