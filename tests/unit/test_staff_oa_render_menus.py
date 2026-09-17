"""Unit tests for scripts/staff_oa_render_menus.py — the offline PNG preview.

Renders every real Employee Hub variant to a temp directory (no LINE
credentials, no network) and checks the PNGs actually land at the exact
canvas size ``menu_size()`` calls for. This is the regression guard for the
2026-09-18 change (owner decision: แจ้งลา is a BASE tile every linked
employee sees — see staff_oa_menu.MENU_BUTTONS's own comment): a layout bug
in any of the four real variants — including `base` itself, now a real,
renderable one-tile menu instead of nothing to skip — would otherwise only
surface by eyeballing the preview images by hand.

``scripts/`` has no ``__init__.py``, so it is imported the same way
tests/unit/test_staff_oa_sync.py imports scripts.staff_oa_sync — as a
top-level module with the repo root pushed onto ``sys.path``.
"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scripts import staff_oa_render_menus as render_menus  # noqa: E402
from app.services import staff_oa_menu  # noqa: E402

# The four real variants as of 2026-09-18 — `base` is now included: แจ้งลา
# makes it a real, renderable one-tile menu rather than the empty variant
# the sync script used to skip entirely.
REAL_VARIANT_KEYS = (
    "base", "base+reception", "base+housekeeping", "base+housekeeping+reception",
)


def test_the_four_real_variants_are_exactly_what_this_file_expects():
    # Fixture premise: if a grant is added or removed, this file's constant
    # goes stale before any test using it does — catch that here first.
    assert set(REAL_VARIANT_KEYS) == {
        staff_oa_menu.menu_key(grants)
        for grants in (
            set(), {"reception"}, {"housekeeping"}, {"housekeeping", "reception"},
        )
    }


def test_render_menus_writes_every_real_variant_at_its_exact_canvas_size(tmp_path):
    out_dir = str(tmp_path / "staffhub-previews")
    # main() reads argv via argparse — drive it through sys.argv rather than
    # shelling out to a subprocess, so this test stays in-process and fast.
    saved_argv = sys.argv
    try:
        sys.argv = ["staff_oa_render_menus.py", "--out", out_dir, *REAL_VARIANT_KEYS]
        exit_code = render_menus.main()
    finally:
        sys.argv = saved_argv

    assert exit_code == 0
    for key in REAL_VARIANT_KEYS:
        grants = staff_oa_menu.grants_for_menu_key(key)
        expected_size = staff_oa_menu.menu_size(len(staff_oa_menu.buttons_for(grants)))
        path = os.path.join(out_dir, f"staffhub-{key.replace('+', '-')}.png")
        assert os.path.isfile(path), f"{key}: no PNG written to {path}"
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == expected_size, f"{key}: {image.size} != {expected_size}"


def test_render_menus_default_sweep_covers_all_real_variants_without_error(tmp_path):
    # No variant args ⇒ every grant-combination the model can produce,
    # including any over-cap combination. None of that may raise — a preview
    # tool must never be harder to use than the thing it previews (see the
    # script's own SKIPPED-branch comments).
    out_dir = str(tmp_path / "staffhub-all")
    saved_argv = sys.argv
    try:
        sys.argv = ["staff_oa_render_menus.py", "--out", out_dir]
        exit_code = render_menus.main()
    finally:
        sys.argv = saved_argv

    assert exit_code == 0
    for key in REAL_VARIANT_KEYS:
        path = os.path.join(out_dir, f"staffhub-{key.replace('+', '-')}.png")
        assert os.path.isfile(path)
    # base IS written now (2026-09-18) — แจ้งลา makes it a real, renderable
    # one-tile menu, not the empty variant the script used to skip.
    assert os.path.isfile(os.path.join(out_dir, "staffhub-base.png"))
