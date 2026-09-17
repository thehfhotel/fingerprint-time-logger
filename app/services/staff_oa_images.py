"""Employee Hub rich-menu renderer — approved HF Internal artwork only.

Every icon on the Employee Hub rich menu is a pixel-exact crop of the
owner-approved HF Internal icon sheet supplied 2026-09-17 22:23
(``assets/staff_oa/source/hf_internal_icon_sheet_2026-09-17.png``), cut by
``scripts/split_staff_oa_icon_sheet.py`` per ``assets/staff_oa/icons/crops.json``
into the seven PNGs under ``assets/staff_oa/icons/``. This renderer never
draws, synthesizes, recolours, filters or sharpens icon artwork — it may
only scale an approved PNG (LANCZOS) and alpha-paste it onto the card. See
``assets/staff_oa/icons/README.md`` for full provenance and fit notes.

Canonical asset keys (``ICON_ASSETS``) and the ``MenuButton.glyph`` values
that resolve to them (``GLYPH_ASSET_KEYS``), with a fit note per glyph
(owner-confirmed 2026-09-17 — see the README for the full rationale):

    key            asset                          glyphs -> key (fit)
    leave          leave_calendar.png              leave -> leave (exact)
    time           time_clock.png                  time -> time (exact); tray -> time (weak)
    announcement   announcement_megaphone.png      announcement -> announcement (exact)
    handbook       handbook_document.png           handbook -> handbook (exact); box -> handbook (weak);
                                                     clipboard -> handbook (reasonable)
    maintenance    maintenance_tools.png           maintenance -> maintenance (exact); wrench -> maintenance (exact);
                                                     wrench_list -> maintenance (reasonable)
    contacts       team_contacts.png               contacts -> contacts (exact); broom -> contacts (reasonable)
    suggestions    suggestions_chat.png            suggestions -> suggestions (exact); photo_sheet -> suggestions (weak)

(There is no ``meal`` key or asset any more — the approved sheet has seven
tiles, not eight.)

Fail-closed contract: ``resolve_glyph_asset``, ``icon_asset_path`` and
``load_icon_asset`` all raise ``ApprovedAssetError`` instead of ever
falling back to a blank tile or a legacy drawn glyph — for an unknown
glyph, an unknown asset key, a missing file, an unreadable file, or a file
that is not a PNG. ``render_menu_image`` calls ``verify_approved_assets()``
before drawing anything, so even an asset that no button on the requested
variant currently uses must still be present and valid.
"""
from functools import lru_cache
import io
import logging
import os
from typing import Optional, Sequence, Tuple
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.staff_oa_menu import MenuButton, menu_cells, menu_size

logger = logging.getLogger(__name__)
CANVAS = (246, 249, 252)
SURFACE = (255, 255, 255)
SURFACE_ALT = (251, 253, 255)
BORDER = (220, 230, 238)
SHADOW = (229, 236, 242)
NAVY = (24, 58, 84)
NAVY_SOFT = (76, 103, 124)
TEAL = (35, 154, 156)
TEAL_DETAIL = (91, 185, 185)
MINT_BADGE = (221, 244, 239)
BLUE_BADGE = (228, 240, 250)
WARM_BADGE = (253, 238, 213)
ROSE_BADGE = (250, 229, 226)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICON_ROOT = os.path.join(_REPO_ROOT, "assets", "staff_oa", "icons")
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

# Canonical key -> approved asset filename under ICON_ROOT. Exactly the
# seven tiles on the 2026-09-17 22:23 HF Internal sheet.
ICON_ASSETS: dict[str, str] = {
    "leave": "leave_calendar.png",
    "time": "time_clock.png",
    "announcement": "announcement_megaphone.png",
    "handbook": "handbook_document.png",
    "maintenance": "maintenance_tools.png",
    "contacts": "team_contacts.png",
    "suggestions": "suggestions_chat.png",
}

# MenuButton.glyph -> canonical key. Identity for the seven canonical keys,
# plus the seven glyphs MENU_BUTTONS uses today. Naming anything else
# (clock/receipt/baht/bell/meal, all gone) fails closed.
GLYPH_ASSET_KEYS: dict[str, str] = {
    **{key: key for key in ICON_ASSETS},
    "broom": "contacts",
    "wrench": "maintenance",
    "box": "handbook",
    "tray": "time",
    "clipboard": "handbook",
    "photo_sheet": "suggestions",
    "wrench_list": "maintenance",
}


class ApprovedAssetError(RuntimeError):
    """Raised whenever an approved icon asset can't be resolved or loaded.

    The renderer fails closed on every path that touches artwork: an
    unknown glyph, an unknown asset key, a missing file, an unreadable
    file, or a file that isn't a PNG. There is no blank-tile fallback.
    """


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


def resolve_glyph_asset(glyph: str) -> str:
    """MenuButton.glyph -> canonical ICON_ASSETS key. Fails closed."""
    try:
        return GLYPH_ASSET_KEYS[glyph]
    except KeyError as exc:
        raise ApprovedAssetError(f"Unknown Employee Hub icon glyph: {glyph!r}") from exc


def icon_asset_path(asset_key: str) -> str:
    """Canonical key -> absolute path under ICON_ROOT. Fails closed."""
    try:
        filename = ICON_ASSETS[asset_key]
    except KeyError as exc:
        raise ApprovedAssetError(f"Unknown approved Staff OA icon asset key: {asset_key!r}") from exc
    return os.path.join(ICON_ROOT, filename)


@lru_cache(maxsize=len(ICON_ASSETS))
def load_icon_asset(asset_key: str) -> Image.Image:
    """Load an approved icon asset as RGBA. Fails closed; never a fallback.

    Cached by asset_key; tests that swap ICON_ROOT call
    ``load_icon_asset.cache_clear()`` before and after.
    """
    path = icon_asset_path(asset_key)
    if not os.path.isfile(path):
        raise ApprovedAssetError(f"Approved Staff OA icon asset is missing: {path}")
    try:
        with Image.open(path) as opened:
            if opened.format != "PNG":
                raise ApprovedAssetError(f"Approved Staff OA icon asset is not a PNG: {path}")
            return opened.convert("RGBA").copy()
    except OSError as exc:
        raise ApprovedAssetError(f"Approved Staff OA icon asset is unreadable: {path}") from exc


def verify_approved_assets() -> None:
    """Load every approved asset, even ones the current variant skips.

    Fails closed as a whole even when a broken/missing asset belongs to a
    tile that isn't on the menu being rendered right now.
    """
    for asset_key in ICON_ASSETS:
        load_icon_asset(asset_key)


def _draw_cell(image, draw, button, cell, font, thai_capable):
    x0, y0 = cell["x"], cell["y"]
    x1, y1 = x0 + cell["width"], y0 + cell["height"]
    margin, radius, shadow_offset = 28, 48, 10
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
    icon_size = max(230, min(400, cell_min * 48 // 100))
    cx = x0 + cell["width"] // 2
    cy = y0 + cell["height"] * 39 // 100
    asset_key = resolve_glyph_asset(button.glyph)
    fitted = ImageOps.contain(
        load_icon_asset(asset_key), (icon_size, icon_size), method=Image.Resampling.LANCZOS
    )
    image.paste(fitted, (cx - fitted.width // 2, cy - fitted.height // 2), fitted)

    label = button.label if thai_capable else _english_fallback_label(button)
    label_y = y0 + cell["height"] * 75 // 100
    draw.text((cx, label_y), label, font=font, fill=NAVY, anchor="mm")
    pill_w, pill_h = 92, 8
    pill_y = min(label_y + font.size * 2 // 3, y1 - margin - 26)
    draw.rounded_rectangle(
        [cx - pill_w // 2, pill_y, cx + pill_w // 2, pill_y + pill_h],
        radius=pill_h // 2, fill=TEAL,
    )


def render_menu_image(buttons: Sequence[MenuButton]) -> bytes:
    verify_approved_assets()
    width, height = menu_size(len(buttons))
    cells = menu_cells(len(buttons))
    image = Image.new("RGB", (width, height), CANVAS)
    draw = ImageDraw.Draw(image)
    label_font, thai_capable = _load_label_font(size=100)
    for button, cell in zip(buttons, cells):
        _draw_cell(image, draw, button, cell, label_font, thai_capable)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True, compress_level=9)
    return buffer.getvalue()
