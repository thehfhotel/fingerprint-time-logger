"""Unit tests for the rich-menu image renderer (app.services.staff_oa_images).

Pins the LINE contract (exact canvas sizes, PNG, <1MB) and the bundled
Thai font that makes rendering deterministic on any machine.

WHICH BUTTON COUNTS ARE REAL, AND WHICH NEED SYNTHETIC BUTTONS
--------------------------------------------------------------
The real table is 6 buttons since รายงานแม่บ้าน arrived (2026-09-02):
แม่บ้าน / แจ้งซ่อม / สต๊อกของ / รับของมาส่ง behind `housekeeping`, สถานะห้อง
behind `reception`, and the SHARED report tile revealed by either. So the
real variants are `base` (ZERO buttons, nothing to render at all),
`base+reception` (2), `base+housekeeping` (5) and
`base+housekeeping+reception` (6 — LINE's cap, exactly reached).

That covers both canvases and both of the layouts anyone can actually be
handed: one row of 2, and the two-row 3+2 and 3+3. Note 6 stopped needing
synthetic buttons on 2026-09-02 and 4 (the 2+2 split) started: the counts no
grant set can produce are now 1, 3 and 4. They are still live production
code — ``menu_size()`` switches on the button count and ``menu_rows()`` lays
4/5/6 out as 2+2 / 3+2 / 3+3 — and one MenuButton row leaving or arriving
re-shuffles which counts are reachable, so the fixtures DERIVE the
unreachable set from the real table instead of listing it.
``TestFixturePremise`` asserts that derivation, so these tests can never
quietly stop covering a layout.

The empty base is why nothing here renders ``buttons_for(set())``: there is
no image for a variant with no buttons, ``menu_size(0)`` raises, and the
sync script never asks for one (``base_has_buttons`` in
scripts/staff_oa_sync.py). The one-button cases below stay synthetic for a
second reason: they drive a PARTICULAR glyph and a particular pixel through
the renderer, which a real variant could not do.
"""
import io

import pytest
from PIL import Image

import itertools

from app.services import staff_oa_images as images
from app.services.staff_oa_menu import (
    MENU_BUTTONS,
    MENU_GRANT_APP_IDS,
    MenuButton,
    buttons_for,
    menu_size,
)

LINE_IMAGE_MAX_BYTES = 1024 * 1024
LINE_BUTTON_CAP = 6

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
# than inlined because several tests below turn on the difference between "the
# maid menu" (5) and "the biggest menu anyone can hold" (6) — a distinction
# that did not exist while one grant owned every button.
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
# their only coverage is the fixtures below. 1, 3 and 4 today — note 4 (the
# 2+2 split) only joined this set on 2026-09-02, when the maid menu grew from
# four tiles to five.
UNREACHABLE_BUTTON_COUNTS = tuple(
    count
    for count in range(1, LINE_BUTTON_CAP + 1)
    if count not in REAL_VARIANT_BUTTON_COUNTS
)

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


def _with_glyph(button, glyph):
    """The same button wearing a different glyph — the pixel-diff control."""
    return MenuButton(
        grant_app_id=button.grant_app_id,
        also_grant_app_ids=button.also_grant_app_ids,
        label=button.label,
        url=button.url,
        glyph=glyph,
    )


def _report_button():
    """The one SHARED tile in the real table (รายงานแม่บ้าน).

    Found by its grant set rather than by label or URL, so it keeps being
    found if either is edited — and so this file states the property that
    makes it the shared tile.
    """
    shared = [b for b in MENU_BUTTONS if len(b.grant_app_ids) > 1]
    assert len(shared) == 1, "expected exactly one shared tile"
    return shared[0]


def _buttons_of_count(button_count):
    """A legal button list of exactly ``button_count`` buttons, for counts no
    grant set produces.

    Real buttons first, padded with synthetic ones only if the real table is
    too short — which it no longer is for any count up to LINE's cap, now that
    the table sits at 6. Deriving that (rather than hard-coding how many
    extras it takes) is the point: the sibling sync test broke once already by
    assuming a button count the real table no longer produced, and this keeps
    working whether the table shrinks again or the cap is somehow raised.

    Was ``_padded_to``; renamed because "padded" stopped describing what it
    usually does on 2026-09-02.
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
        # `reception` reaches the half-height canvas (2 tiles), `housekeeping`
        # the two-row one (5) — so the real table covers both without padding,
        # as it has since 2026-09-01.
        assert RECEPTION_BUTTON_COUNT == 2
        assert HOUSEKEEPING_BUTTON_COUNT == 5
        assert menu_size(RECEPTION_BUTTON_COUNT) == HALF_HEIGHT_CANVAS
        assert menu_size(HOUSEKEEPING_BUTTON_COUNT) == FULL_HEIGHT_CANVAS

    def test_the_shared_tile_is_why_the_counts_do_not_add_up(self):
        # 5 + 2 = 7, but the both-grants menu is SIX: รายงานแม่บ้าน is one row
        # revealed by either grant, so it is counted once in the union. If a
        # future edit duplicates it into two rows, this goes red here — before
        # the both-grants variant silently becomes a 7-button one LINE refuses.
        shared = [
            button for button in MENU_BUTTONS
            if len(button.grant_app_ids) > 1
        ]
        assert len(shared) == 1
        assert (
            HOUSEKEEPING_BUTTON_COUNT + RECEPTION_BUTTON_COUNT - len(shared)
            == MAX_REAL_BUTTON_COUNT
        )

    def test_the_unreachable_counts_are_the_ones_no_grant_set_produces(self):
        # Derived, not listed — the module docstring's claim, asserted. 4 is
        # in here since 2026-09-02 and 6 left it the same day; both were the
        # other way round the day before.
        assert REAL_VARIANT_BUTTON_COUNTS == {
            RECEPTION_BUTTON_COUNT, HOUSEKEEPING_BUTTON_COUNT, MAX_REAL_BUTTON_COUNT
        }
        assert UNREACHABLE_BUTTON_COUNTS == (1, 3, 4)

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
        # The reception variant is two real tiles (สถานะห้อง and the shared
        # report tile), so it still renders on the single-row canvas. Its
        # glyphs — clipboard and photo_sheet — are drawn by nothing else, so
        # this is where either raising at render time would surface as more
        # than the registry sweep at the bottom of the file.
        png_bytes, image = _render_and_open({"reception"})
        assert len(buttons_for({"reception"})) == RECEPTION_BUTTON_COUNT == 2
        assert image.format == "PNG"
        assert image.size == HALF_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    def test_both_grants_render_the_six_button_menu(self):
        # An employee holding housekeeping AND reception — the maximal real
        # variant, six cells filling the 3+3 grid, which is LINE's cap and the
        # count where the PNG is largest and the 1MB limit closest. It is a
        # REAL variant since 2026-09-02; until then this canvas could only be
        # reached with synthetic padding.
        buttons = buttons_for({"housekeeping", "reception"})
        assert len(buttons) == MAX_REAL_BUTTON_COUNT == LINE_BUTTON_CAP
        png_bytes, image = _render(buttons)
        assert image.format == "PNG"
        assert image.size == FULL_HEIGHT_CANVAS
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    @pytest.mark.parametrize("button_count", (4, 5, 6))
    def test_full_height_canvas_renders_png_within_lines_cap(self, button_count):
        # 5 is the REAL maid menu and 6 the REAL both-grants menu since
        # 2026-09-02, so _buttons_of_count() takes them straight from the
        # table; only 4 (the 2+2 split) is a count no grant set produces any
        # more, and it is live layout code either way.
        png_bytes, image = _render(_buttons_of_count(button_count))
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

    The real table names broom/wrench/box/tray/clipboard/photo_sheet, so
    clock, receipt, baht and bell have no tile giving them incidental
    coverage. They are still in the production registry, so cover them
    directly — reading the registry rather than listing names, because the
    registry is the thing under test, and because that is what makes a NEW
    glyph (clipboard 2026-09-01, photo_sheet 2026-09-02) covered the moment it
    is registered rather than when someone remembers to add it.
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
        assert len(reception) == RECEPTION_BUTTON_COUNT
        assert reception[0].glyph == "clipboard"
        assert "clipboard" in images._GLYPH_RENDERERS

        board = reception[0]
        unglyphed = (_with_glyph(board, "no-such-glyph"),)
        _, drawn = _render((board,))
        _, undrawn = _render(unglyphed)
        assert drawn.size == undrawn.size
        assert drawn.tobytes() != undrawn.tobytes()

    def test_the_report_tile_glyph_actually_paints(self):
        """Same idiom for photo_sheet, the tile added 2026-09-02.

        A typo'd glyph name is silent — ``_draw_cell`` just skips an unknown
        one — so "it rendered" proves nothing. The real รายงานแม่บ้าน tile is
        compared against the identical tile naming a glyph that does not
        exist; if photo_sheet were misspelled in either module the two would
        be identical and this goes red.
        """
        report = _report_button()
        assert report.glyph == "photo_sheet"
        assert "photo_sheet" in images._GLYPH_RENDERERS

        _, drawn = _render((report,))
        _, undrawn = _render((_with_glyph(report, "no-such-glyph"),))
        assert drawn.size == undrawn.size
        assert drawn.tobytes() != undrawn.tobytes()

    def test_the_report_tile_does_not_reuse_the_room_status_mark(self):
        """The two tiles sit side by side on a receptionist's menu.

        A report tile that drew สถานะห้อง's clipboard would render as the same
        tile twice — which no other test in this file would catch, because
        both names are registered and both draw something. Comparing the two
        marks in the SAME cell (one button, same label, same url) isolates the
        glyph as the only difference.
        """
        report = _report_button()
        _, as_photo_sheet = _render((report,))
        _, as_clipboard = _render((_with_glyph(report, "clipboard"),))
        assert as_photo_sheet.size == as_clipboard.size
        assert as_photo_sheet.tobytes() != as_clipboard.tobytes()
