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


_GLYPH_RENDERERS = {
    "clock": _glyph_clock,
    "receipt": _glyph_receipt,
    "baht": _glyph_baht,
    "bell": _glyph_bell,
    "broom": _glyph_broom,
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
