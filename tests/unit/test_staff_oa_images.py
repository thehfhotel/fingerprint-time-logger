"""Unit tests for the rich-menu image renderer (app.services.staff_oa_images).

Pins the LINE contract (exact canvas sizes, PNG, <1MB) and the bundled
Thai font that makes rendering deterministic on any machine.

WHICH BUTTON COUNTS ARE REAL, AND WHICH NEED SYNTHETIC BUTTONS
--------------------------------------------------------------
The table has 8 rows since 2026-09-06: แม่บ้าน / แจ้งซ่อม / สต๊อกของ /
รับของมาส่ง behind `housekeeping`, สถานะห้อง / งานซ่อมค้าง behind
`reception`, and TWO shared tiles revealed by either grant — the report tile
(รายงานแม่บ้าน) and, since the SAME day's owner decision "let maid mark fix
done too", จัดการงานซ่อม (the outstanding-maintenance queue page). Both
สถานะห้อง and งานซ่อมค้าง carry ``hidden_by_grant_app_ids={"housekeeping"}``
(the same reasoning twice: a housekeeping+reception holder already has a
better tile for the same job via แม่บ้าน / จัดการงานซ่อม respectively), so the
row count and the SHOWN button count are no longer the same number for
either variant that includes `housekeeping` — the real variants are `base`
(ZERO buttons, nothing to render at all), `base+reception` (4, since
งานซ่อมค้าง then จัดการงานซ่อม joined the same day), `base+housekeeping` (6,
since จัดการงานซ่อม's widening put a maid-only variant on LINE's cap for the
first time) and `base+housekeeping+reception` (6 — LINE's cap, exactly
reached: สถานะห้อง and งานซ่อมค้าง both hidden, จัดการงานซ่อม shown in one of
their places).

That covers both canvases and both two-row layouts anyone can actually be
handed: the 2+2 split and 3+3. The counts no grant set can produce are 1, 2,
3 and 5. They are still live production code — ``menu_size()`` switches on
the button count and ``menu_rows()`` lays 4/5/6 out as 2+2 / 3+2 / 3+3 — and
one MenuButton row (or hide rule) leaving or arriving re-shuffles which
counts are reachable, so the fixtures DERIVE the unreachable set from what
the real grants actually SHOW (not from ``len(MENU_BUTTONS)``, which no
longer equals the biggest real variant) — see ``REAL_VARIANT_BUTTON_COUNTS``
below. ``TestFixturePremise`` asserts that derivation, so these tests can
never quietly stop covering a layout.

The empty base is why nothing here renders ``buttons_for(set())``: there is
no image for a variant with no buttons, ``menu_size(0)`` raises, and the
sync script never asks for one (``base_has_buttons`` in
scripts/staff_oa_sync.py). The one-button cases below stay synthetic for a
second reason: they drive a PARTICULAR asset and a particular pixel through
the renderer, which a real variant could not do.

REAL VS SYNTHETIC VARIANTS BELOW
---------------------------------
Real variants (``buttons_for({...})``) exercise the production grant table
end to end. Synthetic buttons (``_synthetic_buttons`` / ``_buttons_of_count``)
mint button lists no grant set produces, so the button-count-driven layout
code (``menu_size`` / ``menu_rows`` / ``menu_cells``) stays covered for the
counts (1, 2, 3, 5) production never reaches. Synthetic buttons always name
one of the seven canonical asset keys directly (e.g. "time", "leave") rather
than a MenuButton glyph alias, so they exercise real, approved artwork
through ``resolve_glyph_asset``'s identity entries — never a placeholder.
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
    MENU_BUTTONS,
    MENU_GRANT_APP_IDS,
    MenuButton,
    buttons_for,
    menu_cells,
    menu_size,
)

LINE_IMAGE_MAX_BYTES = 1024 * 1024
LINE_BUTTON_CAP = 6

# The only two canvases LINE accepts, spelled out as literals on purpose:
# this file is where that external contract is pinned, so it must not be
# derived from the constants in staff_oa_menu that it is checking.
HALF_HEIGHT_CANVAS = (2500, 843)   # 1-3 buttons, one row
FULL_HEIGHT_CANVAS = (2500, 1686)  # 4-6 buttons, two rows

# Was ``len(MENU_BUTTONS)`` — true only while every row was actually SHOWN
# together. That stopped holding on 2026-09-06: สถานะห้อง and งานซ่อมค้าง
# both carry ``hidden_by_grant_app_ids={"housekeeping"}``, so the table has 8
# rows but the biggest variant anyone is actually SHOWN (both grants) is
# still 6. ``buttons_for(MENU_GRANT_APP_IDS)`` is what a real employee
# holding every menu-relevant grant actually sees, so it — not the row
# count — is the biggest real variant.
MAX_REAL_BUTTON_COUNT = len(buttons_for(MENU_GRANT_APP_IDS))

# The two real grants, and the button counts each reveals ALONE. Named rather
# than inlined because several tests below turn on the maid menu and the
# both-grants menu — even though จัดการงานซ่อม's widening (2026-09-06) means
# they are now the SAME number (6), the two are still built from different
# grant sets and worth telling apart by name.
HOUSEKEEPING_BUTTON_COUNT = len(buttons_for({"housekeeping"}))
RECEPTION_BUTTON_COUNT = len(buttons_for({"reception"}))

# Every button count a REAL employee can be handed an image for — the powerset
# of the menu grants, minus the empty base (which has no image at all). Derived
# rather than listed: which counts are reachable changes every time a
# MenuButton row is added, removed, or SHARED between grants, and the shared
# row is why the counts no longer simply add up (5 + 2 tiles = 6, not 7).
REAL_VARIANT_BUTTON_COUNTS = frozenset(
    len(buttons_for(frozenset(combo)))
    for size in range(len(MENU_GRANT_APP_IDS) + 1)
    for combo in itertools.combinations(sorted(MENU_GRANT_APP_IDS), size)
) - {0}

# The layouts that exist in production code but that no grant set reaches, so
# their only coverage is the fixtures below. 1, 2, 3 and 5 today — 3 joined
# this set on 2026-09-06 morning when จัดการงานซ่อม took the reception-only
# variant from 3 tiles to 4 (the 2+2 split), and 5 joined it the SAME
# afternoon when จัดการงานซ่อม was widened into a shared tile: the maid menu
# jumped straight from 5 to 6, leaving nothing that stops at 5 either.
UNREACHABLE_BUTTON_COUNTS = tuple(
    count
    for count in range(1, LINE_BUTTON_CAP + 1)
    if count not in REAL_VARIANT_BUTTON_COUNTS
)

# Canonical asset keys that resolve_glyph_asset already accepts directly (via
# GLYPH_ASSET_KEYS's identity entries) but that no current MenuButton names —
# every real button reaches its asset through one of the seven glyph aliases
# (broom, wrench, box, tray, clipboard, photo_sheet, wrench_list) instead.
# Used to pad synthetic buttons for counts no grant set reaches, so those
# fixtures wear canonical-key names nothing else in this file already covers
# and always resolve to real, approved artwork. Derived, not listed, so a
# canonical key a future MenuButton starts naming directly drops itself out
# of the padding pool automatically.
ORPHANED_GLYPHS = tuple(
    sorted(set(images.GLYPH_ASSET_KEYS) - {button.glyph for button in MENU_BUTTONS})
)
PADDING_GLYPHS = ORPHANED_GLYPHS or tuple(sorted(images.GLYPH_ASSET_KEYS))

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
    too short — which it no longer is for any count up to LINE's cap, now that
    the table sits at 6. Deriving that (rather than hard-coding how many
    extras it takes) is the point: the sibling sync test broke once already by
    assuming a button count the real table no longer produced, and this keeps
    working whether the table shrinks again or the cap is somehow raised.
    """
    real = list(MENU_BUTTONS[:button_count])
    return tuple(real + list(_synthetic_buttons(button_count - len(real))))


class TestFixturePremise:
    """Some fixtures below drive counts no employee can be handed — prove
    they are the right counts, and that the real ones are covered for real."""

    def test_the_base_variant_has_nothing_to_render(self):
        # Production table, nothing patched. The empty base is why the
        # single-button tests below use synthetic buttons instead of
        # buttons_for(set()) as they used to.
        assert buttons_for(frozenset()) == ()
        with pytest.raises(ValueError):
            menu_size(0)

    def test_the_real_table_now_fills_lines_canvas_exactly(self):
        # Production table, nothing patched. The biggest real variant reached
        # the two-row canvas on 2026-08-17 (4 tiles) and LINE's 6-button CAP on
        # 2026-09-02 (รายงานแม่บ้าน). At the cap there is no headroom left: a
        # seventh row in MENU_BUTTONS makes this variant unrenderable, and its
        # holders get unlinked by the over-cap guards rather than shown a menu.
        # This assertion going red is that alarm.
        assert len(buttons_for(MENU_GRANT_APP_IDS)) == MAX_REAL_BUTTON_COUNT
        assert MAX_REAL_BUTTON_COUNT == LINE_BUTTON_CAP == 6
        assert menu_size(MAX_REAL_BUTTON_COUNT) == FULL_HEIGHT_CANVAS

    def test_the_real_table_spans_both_canvases(self):
        # `reception` reaches the two-row canvas (4 tiles since
        # จัดการงานซ่อม, 2026-09-06), `housekeeping` also two-row (6, since
        # the same day's widening) — so the real table covers the full-height
        # canvas and no longer touches the half-height one at all; only the
        # padded fixtures below still exercise it.
        assert RECEPTION_BUTTON_COUNT == 4
        assert HOUSEKEEPING_BUTTON_COUNT == 6
        assert menu_size(RECEPTION_BUTTON_COUNT) == FULL_HEIGHT_CANVAS
        assert menu_size(HOUSEKEEPING_BUTTON_COUNT) == FULL_HEIGHT_CANVAS

    def test_the_shared_and_hidden_tiles_are_why_the_counts_do_not_add_up(self):
        # 6 + 4 = 10, but the both-grants menu is SIX: รายงานแม่บ้าน and
        # จัดการงานซ่อม are each one row revealed by either grant (counted
        # once in the union, not twice), and both สถานะห้อง and งานซ่อมค้าง
        # are hidden entirely once `housekeeping` is also held (แม่บ้าน /
        # จัดการงานซ่อม already cover the same ground with full access). If a
        # future edit duplicates a shared row or drops a hide, this goes red
        # here — before the both-grants variant silently becomes a 7-button
        # one LINE refuses.
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
        assert (
            HOUSEKEEPING_BUTTON_COUNT + RECEPTION_BUTTON_COUNT
            - len(shared) - len(hidden_in_both)
            == MAX_REAL_BUTTON_COUNT
        )

    def test_the_unreachable_counts_are_the_ones_no_grant_set_produces(self):
        # Derived, not listed — the module docstring's claim, asserted. 3
        # joined the unreachable set on 2026-09-06 morning when จัดการงานซ่อม
        # took `reception` alone from 3 tiles (after งานซ่อมค้าง) to 4; 5
        # joined it the same afternoon when จัดการงานซ่อม was widened into a
        # shared tile and the maid menu jumped straight from 5 to 6.
        assert REAL_VARIANT_BUTTON_COUNTS == {
            RECEPTION_BUTTON_COUNT, HOUSEKEEPING_BUTTON_COUNT, MAX_REAL_BUTTON_COUNT
        }
        assert UNREACHABLE_BUTTON_COUNTS == (1, 2, 3, 5)

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
        # "leave" has no MenuButton glyph naming it today (see
        # ORPHANED_GLYPHS), so nothing in this render would ask for it by
        # name — verify_approved_assets() must check it anyway.
        (isolated_icon_root / images.ICON_ASSETS["leave"]).unlink()
        with pytest.raises(images.ApprovedAssetError):
            images.render_menu_image((self.REAL_TILE,))

    def test_jpeg_saved_under_a_png_name_fails_closed(self, isolated_icon_root):
        key = images.resolve_glyph_asset(self.REAL_TILE.glyph)
        target = isolated_icon_root / images.ICON_ASSETS[key]
        Image.new("RGB", (344, 293), (10, 20, 30)).save(target, format="JPEG")
        with pytest.raises(images.ApprovedAssetError):
            images.render_menu_image((self.REAL_TILE,))

    def test_load_icon_asset_itself_raises_for_a_missing_file(self, isolated_icon_root):
        (isolated_icon_root / images.ICON_ASSETS["leave"]).unlink()
        with pytest.raises(images.ApprovedAssetError):
            images.load_icon_asset("leave")


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
    frozenset({"reception"}),
    frozenset({"housekeeping"}),
    frozenset({"housekeeping", "reception"}),
)


class TestRealVariantsRenderWithinLinesContract:
    """Item 7: PNG, exact canvas, under LINE's 1MB cap, for every real,
    non-empty variant."""

    @pytest.mark.parametrize(
        "grants", REAL_VARIANT_GRANTS, ids=lambda g: "+".join(sorted(g))
    )
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

    @pytest.mark.parametrize(
        "grants", REAL_VARIANT_GRANTS, ids=lambda g: "+".join(sorted(g))
    )
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
    4-6 (real buttons padded with synthetic canonical-key ones)."""

    @pytest.mark.parametrize("button_count", (1, 2, 3))
    def test_half_height_canvas_renders_with_canonical_key_glyphs(self, button_count):
        buttons = _synthetic_buttons(button_count, glyphs=("time", "leave", "announcement"))
        png_bytes, image = _render(buttons)
        assert image.format == "PNG"
        assert image.size == HALF_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    @pytest.mark.parametrize("button_count", (4, 5, 6))
    def test_full_height_canvas_renders_png_within_lines_cap(self, button_count):
        # 4 (reception) and 6 (the maid menu and both-grants alike) are real
        # variants; 5 is not any more — จัดการงานซ่อม's widening (2026-09-06)
        # skipped the maid menu straight from 5 to 6 — so 5 is padded with a
        # synthetic canonical-key button via _buttons_of_count(). This test
        # predates that distinction and stays as a direct, non-grant-driven
        # check of the 2+2 / 3+2 / 3+3 layout code itself.
        png_bytes, image = _render(_buttons_of_count(button_count))
        assert image.format == "PNG"
        assert image.size == FULL_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES
