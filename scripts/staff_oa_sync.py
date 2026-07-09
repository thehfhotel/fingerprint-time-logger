#!/usr/bin/env python3
"""Employee Hub sync — deploy Role Menus to the staff LINE OA (2026-07).

Reconciles the staff Official Account's rich menus with the employee
registry, idempotently:

  1. Compute the menu variants actually needed: ``base`` (the channel
     default) plus every distinct grant-combination held by active
     employees with a linked LINE account (``employee_app_grants`` filtered
     to the menu-relevant grants in app/services/staff_oa_menu.py).
  2. Ensure each variant exists on the channel — rich-menu names embed a
     content signature (``staffhub:<variant>:<sig>``), so an unchanged
     variant is reused, a changed one is re-created with a freshly rendered
     HF One image (app/services/staff_oa_images.py).
  3. Make the ``base`` variant the channel default.
  4. Link every linked employee to their variant (bulk link API, chunked).
  5. Delete stale ``staffhub:*`` menus nothing references any more.

DRY-RUN by default: prints the reconciliation plan (read-only GETs against
LINE). Pass ``--apply`` to execute. Re-run whenever grants change — or call
app/services/staff_oa_service.link_role_menu_for_line_user() to relink a
single user without a full sync.

FAIL CLOSED: refuses to run (exit 2) until both STAFF_OA_CHANNEL_ACCESS_TOKEN
and STAFF_OA_CHANNEL_SECRET are set (see app/core/config.py).

Usage:
    python scripts/staff_oa_sync.py                 # dry-run (plan only)
    python scripts/staff_oa_sync.py --apply         # execute the plan
    python scripts/staff_oa_sync.py --render-dir X  # also save variant PNGs

Inside the container:
    docker exec fingerprint-time-logger python scripts/staff_oa_sync.py --apply
"""
import argparse
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.core.database import SessionLocal  # noqa: E402
from app.services import staff_oa_images, staff_oa_menu, staff_oa_service  # noqa: E402


def _plan_variants(assignments: Dict[str, List[str]]) -> List[str]:
    """Variant keys to deploy: base first, then the observed combinations."""
    keys = set(assignments) | {"base"}
    return sorted(keys, key=lambda key: (key != "base", key))


def _render_variant_png(key: str) -> bytes:
    grants = staff_oa_menu.grants_for_menu_key(key)
    return staff_oa_images.render_menu_image(staff_oa_menu.buttons_for(grants))


def _save_render(render_dir: str, key: str, png_bytes: bytes) -> str:
    os.makedirs(render_dir, exist_ok=True)
    path = os.path.join(render_dir, f"staffhub-{key.replace('+', '-')}.png")
    with open(path, "wb") as file:
        file.write(png_bytes)
    return path


def sync(apply: bool, render_dir: str = "") -> int:
    if not staff_oa_service.is_enabled():
        print(
            "REFUSING to sync: STAFF_OA_CHANNEL_ACCESS_TOKEN and/or "
            "STAFF_OA_CHANNEL_SECRET are not set (the Employee Hub is dark).\n"
            "Create the staff LINE OA, then deliver both secrets to the "
            "environment (prod: host compose .env) and re-run."
        )
        return 2

    mode = "APPLY" if apply else "DRY-RUN (pass --apply to execute)"
    print(f"Staff OA rich-menu sync — {mode}")

    db = SessionLocal()
    try:
        assignments = staff_oa_service.employee_menu_assignments(db)
    finally:
        db.close()

    variant_keys = _plan_variants(assignments)
    linked_count = sum(len(users) for users in assignments.values())
    print(f"Linked employees: {linked_count}; menu variants needed: {variant_keys}")

    existing_menus = staff_oa_service.get_rich_menu_list()
    existing_by_name = {menu.get("name", ""): menu["richMenuId"] for menu in existing_menus}

    # --- Ensure each needed variant exists (create when name/signature is new)
    menu_ids: Dict[str, str] = {}
    desired_names = set()
    for key in variant_keys:
        grants = staff_oa_menu.grants_for_menu_key(key)
        name = staff_oa_menu.rich_menu_name(grants)
        desired_names.add(name)

        png_bytes = _render_variant_png(key) if (render_dir or name not in existing_by_name) else b""
        if render_dir:
            print(f"  rendered {key!r} -> {_save_render(render_dir, key, png_bytes)}")

        if name in existing_by_name:
            menu_ids[key] = existing_by_name[name]
            print(f"  keep   {name} ({menu_ids[key]})")
            continue

        if apply:
            rich_menu_id = staff_oa_service.create_rich_menu(
                staff_oa_menu.rich_menu_payload(grants)
            )
            staff_oa_service.upload_rich_menu_image(rich_menu_id, png_bytes)
            menu_ids[key] = rich_menu_id
            print(f"  create {name} ({rich_menu_id}, image {len(png_bytes)} bytes)")
        else:
            menu_ids[key] = f"<new:{key}>"
            print(f"  create {name} (image {len(png_bytes)} bytes)")

    # --- Channel default = base variant
    current_default = staff_oa_service.get_default_rich_menu_id()
    if current_default == menu_ids["base"]:
        print(f"  default already {menu_ids['base']}")
    elif apply:
        staff_oa_service.set_default_rich_menu(menu_ids["base"])
        print(f"  default -> {menu_ids['base']}")
    else:
        print(f"  default -> {menu_ids['base']} (was {current_default})")

    # --- Per-user Role Menu links (bulk, chunked)
    for key in sorted(assignments):
        users = assignments[key]
        if apply:
            staff_oa_service.bulk_link_rich_menu(users, menu_ids[key])
        print(f"  link   {len(users)} user(s) -> {key!r}")

    # --- Delete stale staffhub menus (superseded signatures, unused variants)
    kept_ids = set(menu_ids.values())
    for menu in existing_menus:
        name = menu.get("name", "")
        if not staff_oa_menu.is_staff_hub_menu_name(name):
            continue  # never touch menus this script didn't create
        if name in desired_names and menu["richMenuId"] in kept_ids:
            continue
        if apply:
            staff_oa_service.delete_rich_menu(menu["richMenuId"])
        print(f"  delete {name} ({menu['richMenuId']})")

    print("Done." if apply else "Dry-run complete — nothing changed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync Employee Hub rich menus to the staff LINE OA "
                    "(dry-run by default)."
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="execute the plan (default is a read-only dry-run)",
    )
    parser.add_argument(
        "--render-dir", default="",
        help="also write each variant's PNG here (preview / debugging)",
    )
    args = parser.parse_args()
    return sync(apply=args.apply, render_dir=args.render_dir)


if __name__ == "__main__":
    sys.exit(main())
