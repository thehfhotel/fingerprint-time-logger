"""Unit tests for the rich-menu image renderer (app.services.staff_oa_images).

Pins the LINE contract (exact canvas sizes, PNG, <1MB) and the bundled
Thai font that makes rendering deterministic on any machine.

WHY THE 5- AND 6-BUTTON TESTS USE SYNTHETIC BUTTONS
---------------------------------------------------
The real table is 4 buttons since รับของมาส่ง got its own tile (2026-08-17)
— แม่บ้าน / แจ้งซ่อม / สต๊อกของ / รับของมาส่ง, all behind the `housekeeping`
grant. So the real variants are `base` (ZERO buttons, nothing to render at
all) and `base+housekeeping` (4), and the latter DOES reach the 2500x1686
two-row canvas: it is covered by the real table, not by padding. Only 5 and
6 still need synthetic buttons, being counts no grant set can produce.

The empty base is why nothing here renders ``buttons_for(set())``: there is
no image for a variant with no buttons, ``menu_size(0)`` raises, and the
sync script never asks for one (``base_has_buttons`` in
scripts/staff_oa_sync.py). The one-button cases below are therefore
synthetic too — a count the real table can no longer produce, but live code
the moment any button comes back.

That canvas is still live production code — ``menu_size()`` switches on the
button count, ``menu_rows()`` lays 4/5/6 out as 2+2 / 3+2 / 3+3, and
``render_menu_image()`` has to fill two rows and still come in under LINE's
1MB cap. One MenuButton row coming back (the deferred แม่บ้าน tile, say)
re-activates it in a single commit. So those tests keep running, driven by
SYNTHETIC buttons the same way tests/unit/test_staff_oa_sync.py mints its
over-sized variant: the padding count is DERIVED from the real table rather
than hard-coded, so the fixture cannot rot the next time MENU_BUTTONS
changes. ``TestFixturePremise`` asserts both halves of that premise, so
these tests can never quietly stop covering the two-row path.
"""
import io

import pytest
from PIL import Image

from app.services import staff_oa_images as images
from app.services.staff_oa_menu import (
    MENU_BUTTONS,
    MENU_GRANT_APP_IDS,
    MenuButton,
    buttons_for,
    menu_size,
)

LINE_IMAGE_MAX_BYTES = 1024 * 1024

# The only two canvases LINE accepts, spelled out as literals on purpose:
# this file is where that external contract is pinned, so it must not be
# derived from the constants in staff_oa_menu that it is checking.
HALF_HEIGHT_CANVAS = (2500, 843)   # 1-3 buttons, one row
FULL_HEIGHT_CANVAS = (2500, 1686)  # 4-6 buttons, two rows

# Every button is either base or revealed by a grant in MENU_GRANT_APP_IDS,
# so the whole table IS the biggest variant the real table can produce
# (3 today: 1 base + 2 housekeeping).
MAX_REAL_BUTTON_COUNT = len(MENU_BUTTONS)

# Glyph renderers that no current MenuButton names: the tiles that used them
# were removed or deferred on 2026-08-14 (เบิกค่าใช้จ่าย/receipt,
# เงินเดือน/baht, OTA Desk/bell, แม่บ้าน/broom — broom explicitly deferred,
# not deleted). They are still registered in production, so the synthetic
# padding below wears them: that keeps the glyph coverage the removed tiles
# used to provide incidentally. Derived, not listed, so a returning tile
# silently moves back to being covered by its own real variant instead.
ORPHANED_GLYPHS = tuple(
    sorted(set(images._GLYPH_RENDERERS) - {button.glyph for button in MENU_BUTTONS})
)
PADDING_GLYPHS = ORPHANED_GLYPHS or tuple(sorted(images._GLYPH_RENDERERS))

SYNTHETIC_GRANT = "extra"


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


def _padded_to(button_count):
    """The real table's buttons padded with synthetic ones up to
    ``button_count``.

    Real buttons first, so what gets rendered is still mostly the production
    menu and only the padding pushes it onto a canvas no grant set reaches
    today. Taking ``MENU_BUTTONS[:button_count]`` (rather than hard-coding
    how many extras it takes) is the point: the sibling sync test broke once
    already by assuming a button count the real table no longer produces, and
    this keeps working whether the table shrinks further or grows past 4.
    """
    real = list(MENU_BUTTONS[:button_count])
    return tuple(real + list(_synthetic_buttons(button_count - len(real))))


class TestFixturePremise:
    """The full-height fixtures are synthetic on purpose — prove they are
    synthetic for the right reason."""

    def test_the_base_variant_has_nothing_to_render(self):
        # Production table, nothing patched. The empty base is why the
        # single-button tests below use synthetic buttons instead of
        # buttons_for(set()) as they used to.
        assert buttons_for(frozenset()) == ()
        with pytest.raises(ValueError):
            menu_size(0)

    def test_the_real_variant_reaches_the_full_height_canvas(self):
        # Production table, nothing patched. This flipped on 2026-08-17: the
        # maid menu grew to 4 real buttons, so the biggest real variant now
        # renders on the two-row canvas rather than the single-row one. If it
        # drops back to 3 or fewer, invert this and update the module
        # docstring; the synthetic tests below stay either way.
        assert len(buttons_for(MENU_GRANT_APP_IDS)) == MAX_REAL_BUTTON_COUNT
        assert MAX_REAL_BUTTON_COUNT == 4
        assert menu_size(MAX_REAL_BUTTON_COUNT) == FULL_HEIGHT_CANVAS

    @pytest.mark.parametrize("button_count", (5, 6))
    def test_padding_mints_counts_the_real_table_cannot(self, button_count):
        buttons = _padded_to(button_count)
        assert len(buttons) == button_count
        assert button_count > MAX_REAL_BUTTON_COUNT
        assert any(button.grant_app_id == SYNTHETIC_GRANT for button in buttons)
        assert menu_size(button_count) == FULL_HEIGHT_CANVAS


class TestBundledThaiFont:
    def test_repo_bundles_a_thai_font(self):
        path = images.find_thai_font_path()
        assert path is not None
        assert "assets" in path and "Prompt" in path


class TestRenderMenuImage:
    def test_single_button_menu_renders_half_height_png(self):
        # Was test_base_menu_renders_half_height_png, rendering
        # buttons_for(set()) back when base carried the clock-in tile. Base
        # is empty since 2026-08-14 and has no image at all, so the
        # one-button canvas is exercised synthetically — it is still live
        # code (menu_size/menu_rows both special-case small counts) and one
        # button is what any single returning tile would produce.
        png_bytes, image = _render(_synthetic_buttons(1))
        assert image.format == "PNG"
        assert image.size == HALF_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    def test_the_empty_base_variant_cannot_be_rendered(self):
        # Not a gap in coverage — a contract. render_menu_image goes through
        # menu_size(), so a 0-button variant raises rather than silently
        # producing a blank burgundy rectangle that the sync would then
        # upload to LINE as if it were a menu.
        with pytest.raises(ValueError):
            images.render_menu_image(buttons_for(frozenset()))

    def test_housekeeping_menu_renders_full_height_png(self):
        # This test has followed the maid menu up and down: full height when
        # the variant was 5 buttons, half when the 2026-08-14 re-scope cut it
        # to 2, and full again since รับของมาส่ง made it 4 (2026-08-17). It is
        # the ONLY real variant with an image at all, which is why the count is
        # asserted against the table rather than written as a literal. Still
        # the only variant that exercises the broom/wrench/box/tray glyphs.
        png_bytes, image = _render_and_open({"housekeeping"})
        assert len(buttons_for({"housekeeping"})) == MAX_REAL_BUTTON_COUNT
        assert image.format == "PNG"
        assert image.size == FULL_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    @pytest.mark.parametrize("button_count", (4, 5, 6))
    def test_full_height_canvas_renders_png_within_lines_cap(self, button_count):
        # 4 is the REAL maid menu since 2026-08-17; 5 and 6 stay synthetic.
        # Replaces test_six_button_menu_renders_full_height_png, whose
        # premise (housekeeping 3 + ota 1 + 2 base = 6) died with the ota and
        # reimbursement tiles. Synthetic per the module docstring: the
        # two-row renderer is live code and 6 is LINE's cap, the count where
        # the PNG is largest and the 1MB limit is closest.
        png_bytes, image = _render(_padded_to(button_count))
        assert image.format == "PNG"
        assert image.size == FULL_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    def test_canvas_uses_hf_one_burgundy(self):
        # Same single-button canvas this always used (it was buttons_for(set())
        # while base still had the clock-in tile); the pixel checked is in the
        # margin above the panels, so the button count is incidental.
        _, image = _render(_synthetic_buttons(1))
        # A pixel on the gutter between panels is the burgundy base coat.
        assert image.getpixel((1250, 4)) == images.BURGUNDY


class TestGlyphRenderers:
    """Every registered glyph must still draw.

    The real table names only clock/wrench/box now, so receipt, baht, bell
    and broom lost the incidental coverage they had from the removed tiles.
    They are still in the production registry (แม่บ้าน/broom is deferred, not
    deleted), so cover them directly — reading the registry rather than
    listing names, because the registry is the thing under test.
    """

    @pytest.mark.parametrize("glyph", sorted(images._GLYPH_RENDERERS))
    def test_glyph_renders_on_a_single_button_menu(self, glyph):
        png_bytes, image = _render(_synthetic_buttons(1, glyphs=(glyph,)))
        assert image.format == "PNG"
        assert image.size == HALF_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES
