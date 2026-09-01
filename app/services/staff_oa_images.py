"""Employee Hub rich-menu image renderer (PIL) — HF One palette (2026-07).

Renders the 2500x843 / 2500x1686 PNGs the LINE rich-menu API requires, one
per Role Menu variant, from the button model in
:mod:`app.services.staff_oa_menu`. Flat HF One look: burgundy panels, gold
accents, white Thai labels, simple geometric glyphs (drawn with PIL
primitives — no emoji fonts needed).

Thai labels need a Thai-capable font. Search order:

1. ``assets/fonts/Prompt-*.ttf`` — bundled with the repo (SIL OFL 1.1, the
   same family the web UI uses). This is the path that always works, on
   dev machines, in the Docker container, and in CI.
2. Common system Thai fonts (macOS Thonburi, Linux Noto Sans Thai).
3. DejaVu / PIL default — **English-only fallback**: DejaVu has no Thai
   glyphs, so labels fall back to each button's URL host. Only reachable
   if someone deletes the bundled fonts.
"""

import io
import logging
import os
from typing import Optional, Sequence, Tuple
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from app.services.staff_oa_menu import MenuButton, menu_cells, menu_size

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HF One palette (design/HF-ONE.md) — flat, high-contrast, big touch targets.
# ---------------------------------------------------------------------------
BURGUNDY = (79, 14, 14)          # #4f0e0e — canvas base
BURGUNDY_LIGHT = (99, 24, 24)    # alternate cell panel
BURGUNDY_DARK = (60, 10, 10)     # alternate cell panel
GOLD = (201, 162, 39)            # #c9a227 — accents
WHITE = (255, 255, 255)
GOLD_SOFT = (222, 194, 106)      # lighter gold for glyph detail

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Thai-capable candidates, best first. The bundled Prompt files make the
# renderer deterministic everywhere; the system paths are a courtesy.
_THAI_FONT_CANDIDATES = (
    os.path.join(_REPO_ROOT, "assets", "fonts", "Prompt-SemiBold.ttf"),
    os.path.join(_REPO_ROOT, "assets", "fonts", "Prompt-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",          # macOS
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/truetype/tlwg/Loma.ttf",                  # Debian fonts-tlwg
)

# English-only last resorts (no Thai glyphs).
_FALLBACK_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def find_thai_font_path() -> Optional[str]:
    """First existing Thai-capable font file, or None when unavailable."""
    for path in _THAI_FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _load_label_font(size: int) -> Tuple[ImageFont.FreeTypeFont, bool]:
    """(font, thai_capable). Falls back to English-only fonts with a warning."""
    thai_path = find_thai_font_path()
    if thai_path:
        return ImageFont.truetype(thai_path, size), True

    logger.warning(
        "No Thai-capable font found (bundled assets/fonts missing?) — "
        "menu labels will fall back to English URL hosts."
    )
    for path in _FALLBACK_FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size), False
    return ImageFont.load_default(size=size), False


def _english_fallback_label(button: MenuButton) -> str:
    """ASCII-safe stand-in when no Thai font exists: the tool's host name."""
    if button.label.isascii():
        return button.label
    return urlparse(button.url).hostname or button.url


# ---------------------------------------------------------------------------
# Glyphs — simple flat line-art, one per staff_oa_menu glyph name.
# Each draws inside the square (x0, y0)..(x0+size, y0+size).
# ---------------------------------------------------------------------------

def _glyph_clock(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Wall clock — QR clock-in."""
    draw.ellipse([x0, y0, x0 + size, y0 + size], outline=GOLD, width=stroke)
    cx, cy = x0 + size // 2, y0 + size // 2
    draw.line([cx, cy, cx, y0 + size // 4], fill=GOLD, width=stroke)          # minute hand
    draw.line([cx, cy, x0 + size * 2 // 3, cy + size // 8], fill=GOLD, width=stroke)  # hour hand


def _glyph_receipt(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Receipt with ruled lines — reimbursement."""
    inset = size // 8
    left, right = x0 + inset, x0 + size - inset
    draw.rounded_rectangle([left, y0, right, y0 + size], radius=size // 12,
                           outline=GOLD, width=stroke)
    for i in range(1, 4):
        y = y0 + i * size // 4
        draw.line([left + inset, y, right - inset, y], fill=GOLD_SOFT, width=max(2, stroke // 2))


def _glyph_baht(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Coin bearing ฿ (drawn as B + vertical bar so no Thai font is needed)."""
    draw.ellipse([x0, y0, x0 + size, y0 + size], outline=GOLD, width=stroke)
    cx = x0 + size // 2
    try:
        font = ImageFont.truetype(_FALLBACK_FONT_CANDIDATES[0], size // 2)
    except OSError:
        font = ImageFont.load_default(size=size // 2)
    draw.text((cx, y0 + size // 2), "B", font=font, fill=GOLD, anchor="mm")
    draw.line([cx, y0 + size // 5, cx, y0 + size * 4 // 5], fill=GOLD, width=max(2, stroke // 2))


def _glyph_bell(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Reception desk bell — OTA Desk."""
    dome_top = y0 + size // 5
    draw.pieslice([x0, dome_top, x0 + size, dome_top + size], 180, 360,
                  outline=GOLD, width=stroke)
    base_y = dome_top + size // 2
    draw.line([x0, base_y + stroke, x0 + size, base_y + stroke], fill=GOLD, width=stroke)
    cx = x0 + size // 2
    knob = size // 10
    draw.ellipse([cx - knob, y0, cx + knob, y0 + 2 * knob], outline=GOLD, width=max(2, stroke // 2))


def _glyph_broom(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Broom — housekeeping."""
    draw.line([x0 + size * 3 // 4, y0, x0 + size // 3, y0 + size * 3 // 5],
              fill=GOLD, width=stroke)
    head = [
        (x0 + size // 2, y0 + size // 2),
        (x0 + size // 8, y0 + size * 7 // 8),
        (x0 + size * 5 // 8, y0 + size),
        (x0 + size * 3 // 4, y0 + size * 5 // 8),
    ]
    draw.polygon(head, outline=GOLD, width=stroke)
    for i in range(1, 4):
        x = x0 + size // 8 + i * size // 8
        draw.line([x, y0 + size * 3 // 4, x + size // 16, y0 + size * 15 // 16],
                  fill=GOLD_SOFT, width=max(2, stroke // 2))


def _glyph_wrench(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Wrench — breakage report / work order (แจ้งซ่อม)."""
    draw.line(
        [x0 + size // 6, y0 + size * 5 // 6, x0 + size * 3 // 4, y0 + size // 6],
        fill=GOLD, width=stroke * 2,
    )
    head = size * 2 // 5
    hx0, hy0 = x0 + size - head, y0
    draw.ellipse([hx0, hy0, hx0 + head, hy0 + head], outline=GOLD, width=stroke)
    knob = size // 8
    kx, ky = x0 + size // 6, y0 + size * 5 // 6
    draw.ellipse(
        [kx - knob, ky - knob, kx + knob, ky + knob],
        outline=GOLD_SOFT, width=max(2, stroke // 2),
    )


def _glyph_box(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Storage carton — stock ledger (สต๊อกของ)."""
    inset = size // 8
    left, right = x0 + inset, x0 + size - inset
    top, bottom = y0 + size // 6, y0 + size
    draw.rounded_rectangle(
        [left, top, right, bottom], radius=size // 14, outline=GOLD, width=stroke,
    )
    mid_y = top + (bottom - top) // 3
    draw.line([left, mid_y, right, mid_y], fill=GOLD, width=stroke)
    cx = x0 + size // 2
    draw.line([cx, top, cx, mid_y], fill=GOLD_SOFT, width=max(2, stroke // 2))


def _glyph_tray(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Arrow down into a tray — a delivery arriving (รับของมาส่ง).

    Deliberately the mirror of the box glyph's neighbour on the menu: box is
    what is ON the shelf, this is what is coming IN. Matches the DownTrayIcon
    the housekeeping app puts on the same action, so the tile and the screen
    it opens carry the same mark.
    """
    inset = size // 8
    left, right = x0 + inset, x0 + size - inset
    cx = x0 + size // 2
    # The tray: an open-topped U across the bottom third.
    tray_top = y0 + size * 2 // 3
    draw.line([left, tray_top, left, y0 + size], fill=GOLD, width=stroke)
    draw.line([right, tray_top, right, y0 + size], fill=GOLD, width=stroke)
    draw.line([left, y0 + size, right, y0 + size], fill=GOLD, width=stroke)
    # The arrow dropping into it.
    draw.line([cx, y0, cx, tray_top - stroke], fill=GOLD, width=stroke)
    head = size // 4
    draw.line([cx - head, tray_top - stroke - head, cx, tray_top - stroke], fill=GOLD, width=stroke)
    draw.line([cx + head, tray_top - stroke - head, cx, tray_top - stroke], fill=GOLD, width=stroke)


def _glyph_clipboard(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Clipboard with ruled rows — reception's room-status board (สถานะห้อง).

    A list someone READS, so the mark carries no verb: a board and its rows,
    where the maid tiles all carry an action (a broom sweeping, an arrow
    dropping into a tray). Geometry is deliberately the box glyph's — same
    inset, same top offset, same corner radius — because both are rectangles
    and inconsistent ones would read as a rendering bug at 2500px; the clip
    straddling the top edge is the whole difference between them, and the
    GOLD_SOFT half-stroke rows are the receipt glyph's ruling.

    Not the existing `bell` glyph, even though that one is literally a
    reception desk bell: a bell is a summons (its tile was OTA Desk, where
    someone acts on a booking), and this tile summons nobody.
    """
    inset = size // 8
    left, right = x0 + inset, x0 + size - inset
    top, bottom = y0 + size // 6, y0 + size
    draw.rounded_rectangle(
        [left, top, right, bottom], radius=size // 14, outline=GOLD, width=stroke,
    )
    # The clip, straddling the board's top edge (drawn after, so it sits on it).
    cx = x0 + size // 2
    clip_half = size // 5
    draw.rounded_rectangle(
        [cx - clip_half, y0, cx + clip_half, top + stroke],
        radius=size // 20, outline=GOLD, width=stroke,
    )
    # The rows — one room per line.
    for i in range(1, 4):
        y = top + i * (bottom - top) // 4
        draw.line(
            [left + inset, y, right - inset, y],
            fill=GOLD_SOFT, width=max(2, stroke // 2),
        )


def _glyph_photo_sheet(draw: ImageDraw.ImageDraw, x0: int, y0: int, size: int, stroke: int) -> None:
    """Ticked sheet with a camera lens — the daily room report (รายงานแม่บ้าน).

    Two marks in one, because the tile is two things at once: a checklist
    (ครบทุกรายการ, or the items she flags หาย / ชำรุด) and the photo evidence
    both sides attach — the maid's 1-4 on submit, reception's 1-4 on verify.
    The lens is what stops this reading as "another list".

    Deliberately NOT the clipboard, which is สถานะห้อง's: the two tiles sit
    side by side on a receptionist's menu, and a second clipboard there would
    read as the same tile drawn twice. The clipboard is a board someone READS,
    so it carries no verb; this one is filled in, so it carries the tick.

    House geometry: the same ``size // 14`` corner radius the box and
    clipboard use, and the receipt's GOLD_SOFT half-stroke rules. The sheet is
    inset from the square (and stops short of its bottom) so the lens can
    straddle the bottom-right corner without leaving the cell — the same
    "detail drawn last, sitting on the shape" move as the clipboard's clip.
    """
    left, right = x0 + size // 6, x0 + size * 5 // 6
    top, bottom = y0, y0 + size * 5 // 6
    thin = max(2, stroke // 2)
    draw.rounded_rectangle(
        [left, top, right, bottom], radius=size // 14, outline=GOLD, width=stroke,
    )
    # Three ticked lines — an item, and the mark that says it was checked.
    tick = size // 12
    tick_x = left + size // 6
    for i in range(1, 4):
        y = top + i * (bottom - top) // 4
        draw.line([tick_x - tick, y, tick_x - tick // 3, y + tick], fill=GOLD, width=thin)
        draw.line([tick_x - tick // 3, y + tick, tick_x + tick, y - tick], fill=GOLD, width=thin)
        draw.line(
            [tick_x + size // 6, y, right - size // 12, y],
            fill=GOLD_SOFT, width=thin,
        )
    # The lens, straddling the sheet's bottom-right corner (drawn after it).
    lens = size // 3
    lx0, ly0 = x0 + size - lens, y0 + size - lens
    draw.ellipse([lx0, ly0, lx0 + lens, ly0 + lens], outline=GOLD, width=stroke)
    draw.ellipse(
        [lx0 + lens // 4, ly0 + lens // 4, lx0 + lens * 3 // 4, ly0 + lens * 3 // 4],
        outline=GOLD_SOFT, width=thin,
    )


_GLYPH_RENDERERS = {
    "clock": _glyph_clock,
    "clipboard": _glyph_clipboard,
    "photo_sheet": _glyph_photo_sheet,
    "tray": _glyph_tray,
    "receipt": _glyph_receipt,
    "baht": _glyph_baht,
    "bell": _glyph_bell,
    "broom": _glyph_broom,
    "wrench": _glyph_wrench,
    "box": _glyph_box,
}


def _draw_cell(
    draw: ImageDraw.ImageDraw,
    button: MenuButton,
    cell: dict,
    index: int,
    font: ImageFont.FreeTypeFont,
    thai_capable: bool,
) -> None:
    """One flat button panel: alternating burgundy, gold keyline, glyph, label."""
    x0, y0 = cell["x"], cell["y"]
    x1, y1 = x0 + cell["width"], y0 + cell["height"]

    panel = BURGUNDY_LIGHT if index % 2 else BURGUNDY_DARK
    margin = 20
    draw.rounded_rectangle(
        [x0 + margin, y0 + margin, x1 - margin, y1 - margin],
        radius=36, fill=panel, outline=GOLD, width=6,
    )

    glyph_size = min(cell["width"], cell["height"]) // 3
    stroke = max(8, glyph_size // 12)
    glyph_x = x0 + (cell["width"] - glyph_size) // 2
    glyph_y = y0 + cell["height"] // 6
    renderer = _GLYPH_RENDERERS.get(button.glyph)
    if renderer:
        renderer(draw, glyph_x, glyph_y, glyph_size, stroke)

    label = button.label if thai_capable else _english_fallback_label(button)
    label_y = y0 + cell["height"] * 3 // 4
    draw.text((x0 + cell["width"] // 2, label_y), label, font=font, fill=WHITE, anchor="mm")

    accent_half = min(140, cell["width"] // 6)
    accent_y = min(label_y + font.size, y1 - margin - 18)
    draw.line(
        [x0 + cell["width"] // 2 - accent_half, accent_y,
         x0 + cell["width"] // 2 + accent_half, accent_y],
        fill=GOLD, width=8,
    )


def render_menu_image(buttons: Sequence[MenuButton]) -> bytes:
    """Render one Role Menu's PNG (exact LINE canvas size, well under 1MB)."""
    width, height = menu_size(len(buttons))
    cells = menu_cells(len(buttons))

    image = Image.new("RGB", (width, height), BURGUNDY)
    draw = ImageDraw.Draw(image)

    label_font, thai_capable = _load_label_font(size=110)
    for index, (button, cell) in enumerate(zip(buttons, cells)):
        _draw_cell(draw, button, cell, index, label_font, thai_capable)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
