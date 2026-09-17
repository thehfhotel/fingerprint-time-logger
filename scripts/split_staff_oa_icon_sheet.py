#!/usr/bin/env python3
"""Split the approved Staff OA icon sheet into six pixel-exact PNG assets.

This is deliberately a cropper, not an icon generator. It never redraws,
recolours, filters, sharpens, resizes, or otherwise synthesizes pixels.
The source sheet is divided left-to-right, top-to-bottom as a 3x2 grid.

Usage:
    python scripts/split_staff_oa_icon_sheet.py source.png output-dir

The generic filenames are intentional: visual/button mapping belongs in the
renderer manifest after the six crops are reviewed. Keeping extraction and
semantic mapping separate prevents an accidental reorder from changing pixels.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image

COLUMNS = 3
ROWS = 2
COUNT = COLUMNS * ROWS


def split_icon_sheet(source: Path, output_dir: Path) -> list[Path]:
    if not source.is_file():
        raise FileNotFoundError(source)

    with Image.open(source) as opened:
        image = opened.convert("RGBA")
        width, height = image.size
        if width < COLUMNS or height < ROWS:
            raise ValueError("Icon sheet is too small for a 3x2 split")
        if width % COLUMNS or height % ROWS:
            raise ValueError(
                f"Icon sheet must divide exactly into 3x2 cells; got {width}x{height}"
            )

        cell_width = width // COLUMNS
        cell_height = height // ROWS
        output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []

        index = 0
        for row in range(ROWS):
            for column in range(COLUMNS):
                index += 1
                left = column * cell_width
                top = row * cell_height
                crop = image.crop((left, top, left + cell_width, top + cell_height))
                path = output_dir / f"icon-{index:02d}.png"
                crop.save(path, format="PNG", optimize=False, compress_level=9)
                written.append(path)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split an approved Staff OA icon sheet into six exact 3x2 PNG crops"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    try:
        paths = split_icon_sheet(args.source, args.output_dir)
    except Exception as exc:  # noqa: BLE001 - CLI should fail with one clean diagnostic
        print(f"Icon split failed: {exc}", file=sys.stderr)
        return 1

    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
