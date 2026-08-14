#!/usr/bin/env python3
"""Render Employee Hub rich-menu images to PNG files — no LINE credentials.

Preview tool for the Role Menu artwork (app/services/staff_oa_images.py):
renders every possible menu variant (or just the ones you name) at the
exact LINE canvas sizes, so the images can be eyeballed before the staff
OA even exists. The sync script (scripts/staff_oa_sync.py) renders the
same images itself when deploying — this script is only for humans.

Usage:
    python scripts/staff_oa_render_menus.py --out /tmp/staffhub-previews
    python scripts/staff_oa_render_menus.py --out previews base+housekeeping
"""
import argparse
import itertools
import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.services import staff_oa_images, staff_oa_menu  # noqa: E402


def all_variant_keys() -> List[str]:
    """Every grant-combination the menu model can produce (2^n variants)."""
    grant_ids = sorted(staff_oa_menu.MENU_GRANT_APP_IDS)
    keys = []
    for r in range(len(grant_ids) + 1):
        for combo in itertools.combinations(grant_ids, r):
            keys.append(staff_oa_menu.menu_key(combo))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render Employee Hub menu PNGs for preview."
    )
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument(
        "variants", nargs="*",
        help="variant keys to render (e.g. base+housekeeping); "
             "default: all combinations",
    )
    args = parser.parse_args()

    keys = args.variants or all_variant_keys()
    os.makedirs(args.out, exist_ok=True)

    font_path = staff_oa_images.find_thai_font_path()
    if font_path:
        print(f"Thai font: {font_path}")
    else:
        print("WARNING: no Thai font found — labels fall back to English hosts.")

    for key in keys:
        try:
            grants = staff_oa_menu.grants_for_menu_key(key)  # validates the key
        except ValueError as exc:
            # A key naming a grant that no longer has a button — e.g. the
            # `base+payroll` this script's own usage line advertised until
            # 2026-08-14, or a stale `staffhub:base+ota:*` name still sitting
            # on the live channel. A human typo lands here too. Report it and
            # keep sweeping rather than dying on an uncaught traceback: a
            # preview tool must never be harder to use than the thing it
            # previews.
            print(f"  {key:<40} SKIPPED — {exc}")
            continue
        buttons = staff_oa_menu.buttons_for(grants)
        try:
            size = staff_oa_menu.menu_size(len(buttons))
        except ValueError as exc:
            # Either past LINE's 6-button cap, or EMPTY. Empty is the live
            # case since the 2026-08-14 maid-only re-scope: `base` has no
            # buttons at all, by design, and an employee without the
            # `housekeeping` grant is meant to see no menu (see
            # docs/EMPLOYEE_HUB_SETUP.md). There is nothing to draw, so skip.
            # Over-cap is now only reachable by adding buttons; staff_oa_sync
            # carries its own guard for that, since unlike this
            # all-combinations sweep it only builds variants real linked
            # employees actually hold.
            print(f"  {key:<40} SKIPPED — {exc}")
            continue
        png_bytes = staff_oa_images.render_menu_image(buttons)
        path = os.path.join(args.out, f"staffhub-{key.replace('+', '-')}.png")
        with open(path, "wb") as file:
            file.write(png_bytes)
        print(f"  {key:<40} {size[0]}x{size[1]}  {len(png_bytes):>7} bytes  {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
