#!/usr/bin/env python3
"""Crop the approved Staff OA icon sheet into repository icon assets.

This is deliberately a cropper, not an icon generator. Every asset is
``Image.crop(box)`` of the owner-approved sheet named in the manifest:
no redraw, no recolour, no filter, no sharpen, no resize. The only thing
added is an alpha channel with rounded corners so each pastel tile keeps
the sheet's tile shape when it is pasted onto a menu card; RGB values are
never touched.

The manifest (``assets/staff_oa/icons/crops.json``) pins the source sheet
by sha256 and size, so a crop can only ever come from that exact file.
``tests/unit/test_staff_oa_icon_sheet.py`` re-runs this cropper against the
committed sheet and proves every committed asset is byte-for-byte the
result.

Usage (defaults are the repository paths):
    python scripts/split_staff_oa_icon_sheet.py
    python scripts/split_staff_oa_icon_sheet.py --source sheet.png \
        --manifest crops.json --out /tmp/icons
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "assets" / "staff_oa" / "source" / "hf_internal_icon_sheet_2026-09-17.png"
DEFAULT_MANIFEST = REPO_ROOT / "assets" / "staff_oa" / "icons" / "crops.json"
DEFAULT_OUTPUT = REPO_ROOT / "assets" / "staff_oa" / "icons"
MANIFEST_FORMAT = "hf-staff-oa-icon-crops-v2"
MASK_SUPERSAMPLE = 4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid icon crop manifest: {message}")


def load_manifest(path: Path) -> dict:
    """Parse and validate ``crops.json``; raises ValueError on any defect."""
    if not path.is_file():
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as handle:
        spec = json.load(handle)
    _require(isinstance(spec, dict), "top level must be an object")
    _require(spec.get("format") == MANIFEST_FORMAT, f"format must be {MANIFEST_FORMAT!r}")

    source = spec.get("source")
    _require(isinstance(source, dict), "source must be an object")
    _require(isinstance(source.get("file"), str) and source["file"], "source.file must be a path")
    sha = source.get("sha256")
    _require(isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha),
             "source.sha256 must be 64 lowercase hex characters")
    size = source.get("size")
    _require(isinstance(size, list) and len(size) == 2
             and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in size),
             "source.size must be [width, height] positive integers")

    crops = spec.get("crops")
    _require(isinstance(crops, dict) and crops, "crops must be a non-empty object")
    for name, entry in crops.items():
        _require(isinstance(name, str) and name.endswith(".png") and "/" not in name and "\\" not in name,
                 f"crop name {name!r} must be a bare .png filename")
        _require(isinstance(entry, dict), f"crop {name!r} must be an object")
        box = entry.get("box")
        _require(isinstance(box, list) and len(box) == 4
                 and all(isinstance(v, int) and not isinstance(v, bool) for v in box),
                 f"crop {name!r} box must be four integers")
        left, top, right, bottom = box
        _require(0 <= left < right <= size[0] and 0 <= top < bottom <= size[1],
                 f"crop {name!r} box {box} is outside the {size[0]}x{size[1]} sheet")
        radius = entry.get("corner_radius")
        _require(isinstance(radius, int) and not isinstance(radius, bool) and radius >= 0,
                 f"crop {name!r} corner_radius must be a non-negative integer")
        _require(2 * radius <= min(right - left, bottom - top),
                 f"crop {name!r} corner_radius {radius} is too large for its box")
    return spec


def rounded_mask(width: int, height: int, radius: int, supersample: int = MASK_SUPERSAMPLE) -> Image.Image:
    """Opaque rectangle with rounded corners, computed arithmetically.

    Pure Python on purpose: PIL's drawing rasteriser may change between
    versions, and the committed assets must be reproducible bit-for-bit on
    any machine that runs the integrity test.
    """
    mask = Image.new("L", (width, height), 255)
    if radius <= 0:
        return mask
    pixels = mask.load()
    r = float(radius)
    samples = supersample * supersample
    for y in range(height):
        corner_y = y < radius or y >= height - radius
        if not corner_y:
            continue
        cy = r if y < radius else height - r
        for x in range(width):
            corner_x = x < radius or x >= width - radius
            if not corner_x:
                continue
            cx = r if x < radius else width - r
            inside = 0
            for sy in range(supersample):
                dy = y + (sy + 0.5) / supersample - cy
                for sx in range(supersample):
                    dx = x + (sx + 0.5) / supersample - cx
                    if dx * dx + dy * dy <= r * r:
                        inside += 1
            pixels[x, y] = round(255 * inside / samples)
    return mask


def crop_icon_sheet(source: Path, manifest: Path, output_dir: Path) -> list[Path]:
    """Write every crop named in ``manifest`` from ``source`` into ``output_dir``.

    Raises FileNotFoundError for a missing source/manifest and ValueError
    when the source is not the exact sheet the manifest pins (sha256 and
    size) or the manifest itself is malformed. Returns the written paths in
    manifest order.
    """
    spec = load_manifest(Path(manifest))
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = sha256_file(source)
    if digest != spec["source"]["sha256"]:
        raise ValueError("Source sheet sha256 does not match the manifest; refusing to crop a different image")

    output_dir = Path(output_dir)
    written: list[Path] = []
    with Image.open(source) as opened:
        if list(opened.size) != spec["source"]["size"]:
            raise ValueError(
                f"Source sheet is {opened.size[0]}x{opened.size[1]}; manifest pins "
                f"{spec['source']['size'][0]}x{spec['source']['size'][1]}"
            )
        # RGBA only adds an opaque alpha channel; RGB values are unchanged.
        sheet = opened.convert("RGBA")
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, entry in spec["crops"].items():
            left, top, right, bottom = entry["box"]
            crop = sheet.crop((left, top, right, bottom))
            crop.putalpha(rounded_mask(right - left, bottom - top, entry["corner_radius"]))
            path = output_dir / name
            crop.save(path, format="PNG", optimize=False, compress_level=9)
            written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crop the approved Staff OA icon sheet into pixel-exact PNG assets"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        paths = crop_icon_sheet(args.source, args.manifest, args.out)
    except Exception as exc:  # noqa: BLE001 - CLI should fail with one clean diagnostic
        print(f"Icon crop failed: {exc}", file=sys.stderr)
        return 1
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
