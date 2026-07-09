"""Unit tests for the rich-menu image renderer (app.services.staff_oa_images).

Pins the LINE contract (exact canvas sizes, PNG, <1MB) and the bundled
Thai font that makes rendering deterministic on any machine.
"""
import io

from PIL import Image

from app.services import staff_oa_images as images
from app.services.staff_oa_menu import buttons_for

LINE_IMAGE_MAX_BYTES = 1024 * 1024


def _render_and_open(grants):
    png_bytes = images.render_menu_image(buttons_for(grants))
    return png_bytes, Image.open(io.BytesIO(png_bytes))


class TestBundledThaiFont:
    def test_repo_bundles_a_thai_font(self):
        path = images.find_thai_font_path()
        assert path is not None
        assert "assets" in path and "Prompt" in path


class TestRenderMenuImage:
    def test_base_menu_renders_half_height_png(self):
        png_bytes, image = _render_and_open(set())
        assert image.format == "PNG"
        assert image.size == (2500, 843)
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    def test_five_button_menu_renders_full_height_png(self):
        png_bytes, image = _render_and_open({"payroll", "ota", "housekeeping"})
        assert image.format == "PNG"
        assert image.size == (2500, 1686)
        assert len(png_bytes) < LINE_IMAGE_MAX_BYTES

    def test_canvas_uses_hf_one_burgundy(self):
        _, image = _render_and_open(set())
        # A pixel on the gutter between panels is the burgundy base coat.
        assert image.getpixel((1250, 4)) == images.BURGUNDY
