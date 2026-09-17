"""Employee Hub rich-menu image renderer — HF Internal soft UI (2026-09).

Renders deterministic 2500x843 / 2500x1686 PNGs for the LINE staff OA.
The interaction model and tap bounds live in :mod:`staff_oa_menu`; this
module is presentation only.  The visual language is intentionally closer
to a modern hotel staff app than the former burgundy/gold board: pale canvas,
white cards, navy typography, teal line icons, and soft blue/mint icon badges.
"""

import io
import logging
import os
from typing import Optional, Sequence, Tuple
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from app.services.staff_oa_menu import MenuButton, menu_cells, menu_size

logger = logging.getLogger(__name__)

# HF Internal soft palette.  BURGUNDY/GOLD names remain as compatibility
# aliases because older tests and the glyph helpers import those symbols.
CANVAS = (246, 249, 252)          # #F6F9FC
SURFACE = (255, 255, 255)         # #FFFFFF
SURFACE_ALT = (251, 253, 255)     # #FBFDFF
BORDER = (220, 230, 238)          # #DCE6EE
SHADOW = (229, 236, 242)          # #E5ECF2
NAVY = (24, 58, 84)               # #183A54
NAVY_SOFT = (76, 103, 124)        # #4C677C
TEAL = (35, 154, 156)             # #239A9C
TEAL_DETAIL = (91, 185, 185)      # #5BB9B9
MINT_BADGE = (221, 244, 239)       # #DDF4EF
BLUE_BADGE = (228, 240, 250)       # #E4F0FA
WARM_BADGE = (253, 238, 213)       # #FDEED5
ROSE_BADGE = (250, 229, 226)       # #FAE5E2

# Backward-compatible public palette names used by existing tests/helpers.
BURGUNDY = CANVAS
BURGUNDY_LIGHT = SURFACE
BURGUNDY_DARK = SURFACE_ALT
GOLD = TEAL
GOLD_SOFT = TEAL_DETAIL
WHITE = NAVY

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_THAI_FONT_CANDIDATES = (
    os.path.join(_REPO_ROOT, "assets", "fonts", "Prompt-SemiBold.ttf"),
    os.path.join(_REPO_ROOT, "assets", "fonts", "Prompt-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/truetype/tlwg/Loma.ttf",
)
_FALLBACK_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)


def find_thai_font_path() -> Optional[str]:
    for path in _THAI_FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _load_label_font(size: int) -> Tuple[ImageFont.FreeTypeFont, bool]:
    thai_path = find_thai_font_path()
    if thai_path:
        return ImageFont.truetype(thai_path, size), True
    logger.warning("No Thai-capable font found; using English fallback labels")
    for path in _FALLBACK_FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size), False
    return ImageFont.load_default(size=size), False


def _english_fallback_label(button: MenuButton) -> str:
    if button.label.isascii():
        return button.label
    if button.message_text:
        return urlparse(button.url).hostname or button.message_text
    return urlparse(button.url).hostname or button.url


def _glyph_clock(draw, x0, y0, size, stroke):
    draw.ellipse([x0, y0, x0 + size, y0 + size], outline=GOLD, width=stroke)
    cx, cy = x0 + size // 2, y0 + size // 2
    draw.line([cx, cy, cx, y0 + size // 4], fill=GOLD, width=stroke)
    draw.line([cx, cy, x0 + size * 2 // 3, cy + size // 8], fill=GOLD, width=stroke)


def _glyph_receipt(draw, x0, y0, size, stroke):
    inset = size // 8
    left, right = x0 + inset, x0 + size - inset
    draw.rounded_rectangle([left, y0, right, y0 + size], radius=size // 12,
                           outline=GOLD, width=stroke)
    for i in range(1, 4):
        y = y0 + i * size // 4
        draw.line([left + inset, y, right - inset, y], fill=GOLD_SOFT,
                  width=max(2, stroke // 2))


def _glyph_baht(draw, x0, y0, size, stroke):
    draw.ellipse([x0, y0, x0 + size, y0 + size], outline=GOLD, width=stroke)
    cx = x0 + size // 2
    try:
        font = ImageFont.truetype(_FALLBACK_FONT_CANDIDATES[0], size // 2)
    except OSError:
        font = ImageFont.load_default(size=size // 2)
    draw.text((cx, y0 + size // 2), "B", font=font, fill=GOLD, anchor="mm")
    draw.line([cx, y0 + size // 5, cx, y0 + size * 4 // 5], fill=GOLD,
              width=max(2, stroke // 2))


def _glyph_bell(draw, x0, y0, size, stroke):
    dome_top = y0 + size // 5
    draw.pieslice([x0, dome_top, x0 + size, dome_top + size], 180, 360,
                  outline=GOLD, width=stroke)
    base_y = dome_top + size // 2
    draw.line([x0, base_y + stroke, x0 + size, base_y + stroke], fill=GOLD, width=stroke)
    cx, knob = x0 + size // 2, size // 10
    draw.ellipse([cx - knob, y0, cx + knob, y0 + 2 * knob], outline=GOLD,
                 width=max(2, stroke // 2))


def _glyph_broom(draw, x0, y0, size, stroke):
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


def _glyph_wrench(draw, x0, y0, size, stroke):
    draw.line([x0 + size // 6, y0 + size * 5 // 6,
               x0 + size * 3 // 4, y0 + size // 6], fill=GOLD, width=stroke * 2)
    head = size * 2 // 5
    hx0, hy0 = x0 + size - head, y0
    draw.ellipse([hx0, hy0, hx0 + head, hy0 + head], outline=GOLD, width=stroke)
    knob = size // 8
    kx, ky = x0 + size // 6, y0 + size * 5 // 6
    draw.ellipse([kx - knob, ky - knob, kx + knob, ky + knob], outline=GOLD_SOFT,
                 width=max(2, stroke // 2))


def _glyph_box(draw, x0, y0, size, stroke):
    inset = size // 8
    left, right = x0 + inset, x0 + size - inset
    top, bottom = y0 + size // 6, y0 + size
    draw.rounded_rectangle([left, top, right, bottom], radius=size // 14,
                           outline=GOLD, width=stroke)
    mid_y = top + (bottom - top) // 3
    draw.line([left, mid_y, right, mid_y], fill=GOLD, width=stroke)
    cx = x0 + size // 2
    draw.line([cx, top, cx, mid_y], fill=GOLD_SOFT, width=max(2, stroke // 2))


def _glyph_tray(draw, x0, y0, size, stroke):
    inset = size // 8
    left, right, cx = x0 + inset, x0 + size - inset, x0 + size // 2
    tray_top = y0 + size * 2 // 3
    draw.line([left, tray_top, left, y0 + size], fill=GOLD, width=stroke)
    draw.line([right, tray_top, right, y0 + size], fill=GOLD, width=stroke)
    draw.line([left, y0 + size, right, y0 + size], fill=GOLD, width=stroke)
    draw.line([cx, y0, cx, tray_top - stroke], fill=GOLD, width=stroke)
    head = size // 4
    draw.line([cx - head, tray_top - stroke - head, cx, tray_top - stroke], fill=GOLD, width=stroke)
    draw.line([cx + head, tray_top - stroke - head, cx, tray_top - stroke], fill=GOLD, width=stroke)


def _glyph_clipboard(draw, x0, y0, size, stroke):
    inset = size // 8
    left, right = x0 + inset, x0 + size - inset
    top, bottom = y0 + size // 6, y0 + size
    draw.rounded_rectangle([left, top, right, bottom], radius=size // 14,
                           outline=GOLD, width=stroke)
    cx, clip_half = x0 + size // 2, size // 5
    draw.rounded_rectangle([cx - clip_half, y0, cx + clip_half, top + stroke],
                           radius=size // 20, outline=GOLD, width=stroke)
    for i in range(1, 4):
        y = top + i * (bottom - top) // 4
        draw.line([left + inset, y, right - inset, y], fill=GOLD_SOFT,
                  width=max(2, stroke // 2))


def _glyph_photo_sheet(draw, x0, y0, size, stroke):
    left, right = x0 + size // 6, x0 + size * 5 // 6
    top, bottom = y0, y0 + size * 5 // 6
    thin = max(2, stroke // 2)
    draw.rounded_rectangle([left, top, right, bottom], radius=size // 14,
                           outline=GOLD, width=stroke)
    tick, tick_x = size // 12, left + size // 6
    for i in range(1, 4):
        y = top + i * (bottom - top) // 4
        draw.line([tick_x - tick, y, tick_x - tick // 3, y + tick], fill=GOLD, width=thin)
        draw.line([tick_x - tick // 3, y + tick, tick_x + tick, y - tick], fill=GOLD, width=thin)
        draw.line([tick_x + size // 6, y, right - size // 12, y], fill=GOLD_SOFT, width=thin)
    lens = size // 3
    lx0, ly0 = x0 + size - lens, y0 + size - lens
    draw.ellipse([lx0, ly0, lx0 + lens, ly0 + lens], outline=GOLD, width=stroke)
    draw.ellipse([lx0 + lens // 4, ly0 + lens // 4,
                  lx0 + lens * 3 // 4, ly0 + lens * 3 // 4], outline=GOLD_SOFT, width=thin)


def _glyph_wrench_list(draw, x0, y0, size, stroke):
    half, thin = size // 2, max(2, stroke // 2)
    draw.line([x0 + half // 6, y0 + half * 5 // 6,
               x0 + half * 3 // 4, y0 + half // 6], fill=GOLD, width=stroke)
    head = half * 2 // 5
    hx0 = x0 + half - head
    draw.ellipse([hx0, y0, hx0 + head, y0 + head], outline=GOLD, width=thin)
    knob = half // 8
    kx, ky = x0 + half // 6, y0 + half * 5 // 6
    draw.ellipse([kx - knob, ky - knob, kx + knob, ky + knob], outline=GOLD_SOFT, width=thin)
    rows_left, rows_right = x0 + half + size // 10, x0 + size - size // 12
    for i in (1, 2):
        y = y0 + size * i // 3
        draw.line([rows_left, y, rows_right, y], fill=GOLD_SOFT, width=thin)


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
    "wrench_list": _glyph_wrench_list,
    "box": _glyph_box,
}

_BADGES = (BLUE_BADGE, MINT_BADGE, WARM_BADGE, ROSE_BADGE)


def _draw_cell(draw, button, cell, index, font, thai_capable):
    x0, y0 = cell["x"], cell["y"]
    x1, y1 = x0 + cell["width"], y0 + cell["height"]
    margin = 28
    radius = 48

    # Subtle offset shadow followed by a clean white card.  It remains flat
    # enough to compress well below LINE's 1 MB upload limit.
    shadow_offset = 10
    draw.rounded_rectangle(
        [x0 + margin + shadow_offset, y0 + margin + shadow_offset,
         x1 - margin + shadow_offset, y1 - margin + shadow_offset],
        radius=radius, fill=SHADOW,
    )
    draw.rounded_rectangle(
        [x0 + margin, y0 + margin, x1 - margin, y1 - margin],
        radius=radius, fill=SURFACE, outline=BORDER, width=3,
    )

    cell_min = min(cell["width"], cell["height"])
    badge_size = max(230, min(390, cell_min * 48 // 100))
    badge_x = x0 + cell["width"] // 2
    badge_y = y0 + cell["height"] * 39 // 100
    half_badge = badge_size // 2
    draw.ellipse(
        [badge_x - half_badge, badge_y - half_badge,
         badge_x + half_badge, badge_y + half_badge],
        fill=_BADGES[index % len(_BADGES)],
    )

    glyph_size = badge_size * 54 // 100
    stroke = max(7, glyph_size // 15)
    glyph_x = badge_x - glyph_size // 2
    glyph_y = badge_y - glyph_size // 2
    renderer = _GLYPH_RENDERERS.get(button.glyph)
    if renderer:
        renderer(draw, glyph_x, glyph_y, glyph_size, stroke)

    label = button.label if thai_capable else _english_fallback_label(button)
    label_y = y0 + cell["height"] * 75 // 100
    draw.text((x0 + cell["width"] // 2, label_y), label, font=font,
              fill=NAVY, anchor="mm")

    # Tiny teal pill: enough brand accent to connect the cards without the
    # heavy underline of the old design.
    pill_w, pill_h = 92, 8
    pill_y = min(label_y + font.size * 2 // 3, y1 - margin - 26)
    draw.rounded_rectangle(
        [x0 + cell["width"] // 2 - pill_w // 2, pill_y,
         x0 + cell["width"] // 2 + pill_w // 2, pill_y + pill_h],
        radius=pill_h // 2, fill=TEAL,
    )


def render_menu_image(buttons: Sequence[MenuButton]) -> bytes:
    """Render one Role Menu PNG at the exact LINE canvas size."""
    width, height = menu_size(len(buttons))
    cells = menu_cells(len(buttons))
    image = Image.new("RGB", (width, height), CANVAS)
    draw = ImageDraw.Draw(image)

    label_font, thai_capable = _load_label_font(size=100)
    for index, (button, cell) in enumerate(zip(buttons, cells)):
        _draw_cell(draw, button, cell, index, label_font, thai_capable)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
