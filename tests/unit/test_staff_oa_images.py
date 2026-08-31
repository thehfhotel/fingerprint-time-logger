"""Unit tests for the rich-menu image renderer (app.services.staff_oa_images).

Pins the LINE contract (exact canvas sizes, PNG, <1MB) and the bundled
Thai font that makes rendering deterministic on any machine.

WHY THE 6-BUTTON TESTS USE SYNTHETIC BUTTONS
--------------------------------------------
The real table is 5 buttons since สถานะห้อง arrived (2026-09-01): แม่บ้าน /
แจ้งซ่อม / สต๊อกของ / รับของมาส่ง behind `housekeeping`, plus สถานะห้อง behind
the new `reception` grant. So the real variants are `base` (ZERO buttons,
nothing to render at all), `base+housekeeping` (4), `base+reception` (1) and
`base+housekeeping+reception` (5) — and the last two mean the real table now
covers BOTH the one-row and the two-row canvas, and both of menu_rows()'s
multi-row shapes (2+2 and 3+2), without any padding. Only 6 still needs
synthetic buttons, being the one count no grant set can produce.

The empty base is why nothing here renders ``buttons_for(set())``: there is
no image for a variant with no buttons, ``menu_size(0)`` raises, and the
sync script never asks for one (``base_has_buttons`` in
scripts/staff_oa_sync.py). The one-button cases below stay synthetic even
though `base+reception` is now a real one-button variant: they drive
particular glyphs and a particular pixel through the renderer, which a real
variant pinned to สถานะห้อง's clipboard could not do. The real one-button
variant is rendered on its own, next to them.

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
# (5 today: 4 housekeeping + 1 reception, base being empty).
MAX_REAL_BUTTON_COUNT = len(MENU_BUTTONS)

# The two real grants, and the button counts each reveals ALONE. Named rather
# than inlined because three tests below turn on the difference between "the
# maid menu" (4) and "the biggest menu anyone can hold" (5) — a distinction
# that did not exist while one grant owned every button.
HOUSEKEEPING_BUTTON_COUNT = len(buttons_for({"housekeeping"}))
RECEPTION_BUTTON_COUNT = len(buttons_for({"reception"}))

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
        assert MAX_REAL_BUTTON_COUNT == 5
        assert menu_size(MAX_REAL_BUTTON_COUNT) == FULL_HEIGHT_CANVAS

    def test_the_real_table_now_spans_both_canvases(self):
        # New on 2026-09-01. `reception` reveals exactly one tile, so the real
        # table reaches the half-height canvas again — for the first time since
        # the clock-in tile left and base went empty on 2026-08-14. That is why
        # the module docstring no longer claims 5-button padding is needed.
        assert RECEPTION_BUTTON_COUNT == 1
        assert HOUSEKEEPING_BUTTON_COUNT == 4
        assert HOUSEKEEPING_BUTTON_COUNT + RECEPTION_BUTTON_COUNT == MAX_REAL_BUTTON_COUNT
        assert menu_size(RECEPTION_BUTTON_COUNT) == HALF_HEIGHT_CANVAS
        assert menu_size(HOUSEKEEPING_BUTTON_COUNT) == FULL_HEIGHT_CANVAS

    @pytest.mark.parametrize("button_count", (6,))
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
        # no longer the ONLY real variant with an image — that stopped being
        # true on 2026-09-01 — so it is pinned against the maid grant's own
        # count rather than the whole table's. Still the only variant that
        # exercises the broom/wrench/box/tray glyphs together.
        png_bytes, image = _render_and_open({"housekeeping"})
        assert len(buttons_for({"housekeeping"})) == HOUSEKEEPING_BUTTON_COUNT
        assert image.format == "PNG"
        assert image.size == FULL_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    def test_reception_menu_renders_half_height_png(self):
        # The reception variant is one real tile (สถานะห้อง), so it renders on
        # the single-row canvas — the first REAL variant to do so since base
        # went empty. Its glyph is the new clipboard; nothing else draws it, so
        # this is where a clipboard that raised at render time would surface as
        # more than the registry sweep at the bottom of the file.
        png_bytes, image = _render_and_open({"reception"})
        assert len(buttons_for({"reception"})) == 1
        assert image.format == "PNG"
        assert image.size == HALF_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    def test_both_grants_render_the_five_button_menu(self):
        # An employee holding housekeeping AND reception — the maximal real
        # variant, and the first real use of the 3+2 row split. Five cells on
        # the two-row canvas, still inside LINE's 1MB cap.
        buttons = buttons_for({"housekeeping", "reception"})
        assert len(buttons) == MAX_REAL_BUTTON_COUNT == 5
        png_bytes, image = _render(buttons)
        assert image.format == "PNG"
        assert image.size == FULL_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    @pytest.mark.parametrize("button_count", (4, 5, 6))
    def test_full_height_canvas_renders_png_within_lines_cap(self, button_count):
        # 4 is the REAL maid menu since 2026-08-17 and 5 is the REAL
        # both-grants menu since 2026-09-01, so _padded_to() adds nothing for
        # either — only 6 is still synthetic.
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

    The real table names broom/wrench/box/tray/clipboard, so clock, receipt,
    baht and bell have no tile giving them incidental coverage. They are still
    in the production registry, so cover them directly — reading the registry
    rather than listing names, because the registry is the thing under test,
    and because that is what makes a NEW glyph (clipboard, 2026-09-01) covered
    the moment it is registered rather than when someone remembers to add it.
    """

    @pytest.mark.parametrize("glyph", sorted(images._GLYPH_RENDERERS))
    def test_glyph_renders_on_a_single_button_menu(self, glyph):
        png_bytes, image = _render(_synthetic_buttons(1, glyphs=(glyph,)))
        assert image.format == "PNG"
        assert image.size == HALF_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    def test_the_reception_tile_glyph_actually_paints(self):
        """Rendering without raising is NOT evidence a glyph drew anything.

        ``_draw_cell`` does ``_GLYPH_RENDERERS.get(button.glyph)`` and simply
        skips when the name is unknown — no exception, no warning, just a tile
        with a label and no mark. A typo'd glyph name on a MenuButton would
        therefore sail through every other test in this file. So compare
        pixels: the real สถานะห้อง tile against the identical tile naming a
        glyph that does not exist. If clipboard were misspelled in either
        module, the two would be identical and this goes red.
        """
        reception = buttons_for({"reception"})
        assert len(reception) == 1
        assert reception[0].glyph == "clipboard"
        assert "clipboard" in images._GLYPH_RENDERERS

        unglyphed = (
            MenuButton(
                grant_app_id=reception[0].grant_app_id,
                label=reception[0].label,
                url=reception[0].url,
                glyph="no-such-glyph",
            ),
        )
        _, drawn = _render(reception)
        _, undrawn = _render(unglyphed)
        assert drawn.size == undrawn.size
        assert drawn.tobytes() != undrawn.tobytes()
