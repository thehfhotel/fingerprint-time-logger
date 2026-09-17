"""Unit tests for scripts/split_staff_oa_icon_sheet.py — the manifest-driven
icon cropper.

The sheet is cropped, never regenerated: every asset is a pixel-exact
``Image.crop(box)`` of the owner-approved sheet named in the manifest, with
an alpha channel added by ``rounded_mask`` (pure Python, no PIL drawing
rasteriser involved, so it is bit-stable across Pillow versions). These
tests never assert on hand-computed RGB/alpha constants for the mask —
expected alpha always comes from calling ``rounded_mask`` itself — and the
synthetic-sheet tests build their own tiny RGB source so they run offline
and do not depend on the committed (large) sheet PNG.

``scripts/`` has no ``__init__.py``; imported the same way
tests/unit/test_staff_oa_render_menus.py imports scripts.staff_oa_render_menus
— as a top-level module with the repo root pushed onto ``sys.path``.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scripts.split_staff_oa_icon_sheet import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT,
    DEFAULT_SOURCE,
    MANIFEST_FORMAT,
    crop_icon_sheet,
    rounded_mask,
)


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_sheet(path: Path, width: int, height: int) -> Image.Image:
    """A deterministic, uniquely-patterned RGB sheet — no two pixels share a
    value by coincidence, so any resize, shift or reordering shows up as a
    pixel mismatch rather than passing by luck."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (x % 256, y % 256, (x * 3 + y * 7) % 256)
    image.save(path, format="PNG")
    return image


def _write_manifest(path: Path, spec: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(spec, handle)


def _base_spec(source_path: Path, width: int, height: int, crops: dict) -> dict:
    return {
        "format": MANIFEST_FORMAT,
        "source": {
            "file": source_path.name,
            "sha256": _sha256_of(source_path),
            "size": [width, height],
        },
        "crops": crops,
    }


class TestCropIconSheetSynthetic:
    """Item a: a synthetic sheet + manifest built entirely in tmp_path."""

    WIDTH, HEIGHT = 300, 200

    def _sheet_and_crops(self, tmp_path):
        source = tmp_path / "sheet.png"
        sheet = _make_sheet(source, self.WIDTH, self.HEIGHT)
        # Deliberately not alphabetical, so an "output order == manifest
        # order" bug (e.g. accidentally sorting the crop names) is caught.
        crops = {
            "zzz_first.png": {"box": [10, 10, 60, 50], "corner_radius": 8,
                               "sheet_label": "informational, tolerated"},
            "aaa_second.png": {"box": [100, 20, 180, 90], "corner_radius": 0},
            "mid_third.png": {"box": [0, 100, 300, 200], "corner_radius": 20},
        }
        return source, sheet, crops

    def test_crops_are_pixel_exact_alpha_matches_rounded_mask_order_preserved(self, tmp_path):
        source, sheet, crops = self._sheet_and_crops(tmp_path)
        manifest = tmp_path / "crops.json"
        _write_manifest(manifest, _base_spec(source, self.WIDTH, self.HEIGHT, crops))
        out_dir = tmp_path / "out"

        paths = crop_icon_sheet(source, manifest, out_dir)

        # Output order == manifest (insertion) order, not alphabetical.
        assert [path.name for path in paths] == list(crops.keys())

        for path, (name, entry) in zip(paths, crops.items()):
            left, top, right, bottom = entry["box"]
            width, height = right - left, bottom - top
            with Image.open(path) as crop:
                assert crop.mode == "RGBA"
                assert crop.size == (width, height)
                # Pixel-exact against the source crop — no resize/recolour.
                expected_rgb = sheet.crop((left, top, right, bottom)).convert("RGB").tobytes()
                assert crop.convert("RGB").tobytes() == expected_rgb
                # Alpha channel is exactly rounded_mask's output, never a
                # hand-computed constant.
                expected_alpha = rounded_mask(width, height, entry["corner_radius"])
                assert crop.split()[-1].tobytes() == expected_alpha.tobytes()

    def test_output_written_under_requested_directory(self, tmp_path):
        source, _sheet, crops = self._sheet_and_crops(tmp_path)
        manifest = tmp_path / "crops.json"
        _write_manifest(manifest, _base_spec(source, self.WIDTH, self.HEIGHT, crops))
        out_dir = tmp_path / "nested" / "out"

        paths = crop_icon_sheet(source, manifest, out_dir)

        assert all(path.parent == out_dir for path in paths)
        assert {path.name for path in paths} == set(crops.keys())


class TestCropIconSheetFailureModes:
    """Item b: every documented failure mode, each isolated to one field."""

    WIDTH, HEIGHT = 300, 200

    def _valid(self, tmp_path):
        source = tmp_path / "sheet.png"
        _make_sheet(source, self.WIDTH, self.HEIGHT)
        crops = {"only.png": {"box": [0, 0, 50, 50], "corner_radius": 4}}
        manifest = tmp_path / "crops.json"
        _write_manifest(manifest, _base_spec(source, self.WIDTH, self.HEIGHT, crops))
        return source, manifest

    def test_sha256_mismatch_raises_value_error(self, tmp_path):
        source, manifest = self._valid(tmp_path)
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        spec["source"]["sha256"] = "0" * 64
        _write_manifest(manifest, spec)
        with pytest.raises(ValueError):
            crop_icon_sheet(source, manifest, tmp_path / "out")

    def test_size_mismatch_raises_value_error(self, tmp_path):
        source, manifest = self._valid(tmp_path)
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        # sha256 stays correct (the file itself is untouched); only the
        # declared size disagrees with the actual PNG dimensions.
        spec["source"]["size"] = [self.WIDTH, self.HEIGHT - 1]
        _write_manifest(manifest, spec)
        with pytest.raises(ValueError):
            crop_icon_sheet(source, manifest, tmp_path / "out")

    def test_out_of_bounds_box_raises_value_error(self, tmp_path):
        source, manifest = self._valid(tmp_path)
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        spec["crops"]["only.png"]["box"] = [0, 0, self.WIDTH + 50, 50]
        _write_manifest(manifest, spec)
        with pytest.raises(ValueError):
            crop_icon_sheet(source, manifest, tmp_path / "out")

    def test_wrong_format_string_raises_value_error(self, tmp_path):
        source, manifest = self._valid(tmp_path)
        spec = json.loads(manifest.read_text(encoding="utf-8"))
        spec["format"] = "not-the-right-format"
        _write_manifest(manifest, spec)
        with pytest.raises(ValueError):
            crop_icon_sheet(source, manifest, tmp_path / "out")

    def test_missing_source_raises_file_not_found_error(self, tmp_path):
        _source, manifest = self._valid(tmp_path)
        missing_source = tmp_path / "does-not-exist.png"
        with pytest.raises(FileNotFoundError):
            crop_icon_sheet(missing_source, manifest, tmp_path / "out")


class TestRealRepoIntegrity:
    """Item c: the committed assets are exactly what the cropper produces
    from the committed sheet + manifest today — the regression guard that
    catches a hand-edited or stale asset in assets/staff_oa/icons/."""

    def test_crop_icon_sheet_reproduces_every_committed_asset_pixel_exactly(self, tmp_path):
        paths = crop_icon_sheet(DEFAULT_SOURCE, DEFAULT_MANIFEST, tmp_path)

        committed_names = {p.name for p in DEFAULT_OUTPUT.glob("*.png")}
        assert {p.name for p in paths} == committed_names

        for produced_path in paths:
            committed_path = DEFAULT_OUTPUT / produced_path.name
            with Image.open(produced_path) as produced, Image.open(committed_path) as committed:
                assert produced.convert("RGBA").tobytes() == committed.convert("RGBA").tobytes()


class TestRoundedMask:
    """Item d: the pure-Python mask arithmetic, independent of any PIL
    drawing rasteriser."""

    def test_zero_radius_is_fully_opaque(self):
        mask = rounded_mask(64, 48, 0)
        assert set(mask.getdata()) == {255}

    def test_radius_32_mask_corners_and_centre(self):
        width, height, radius = 200, 200, 32
        mask = rounded_mask(width, height, radius)
        assert mask.getpixel((0, 0)) == 0
        assert mask.getpixel((width - 1, 0)) == 0
        assert mask.getpixel((0, height - 1)) == 0
        assert mask.getpixel((width - 1, height - 1)) == 0
        assert mask.getpixel((width // 2, height // 2)) == 255
        # Mid-edges sit outside every corner's radius box, so they stay
        # fully opaque even though they are on the boundary.
        assert mask.getpixel((width // 2, 0)) == 255
        assert mask.getpixel((width // 2, height - 1)) == 255
        assert mask.getpixel((0, height // 2)) == 255
        assert mask.getpixel((width - 1, height // 2)) == 255
