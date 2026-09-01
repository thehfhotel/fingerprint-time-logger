#!/usr/bin/env python3
"""Employee Hub sync — deploy Role Menus to the staff LINE OA (2026-07).

Reconciles the staff Official Account's rich menus with the employee
registry, idempotently:

  1. Compute the menu variants actually needed: ``base`` (the channel
     default) plus every distinct grant-combination held by active
     employees with a linked LINE account (``employee_app_grants`` filtered
     to the menu-relevant grants in app/services/staff_oa_menu.py). When
     ``base`` has no buttons — its state since the Hub became a maid-only
     tool on 2026-08-14 — it is not a variant at all: no menu is created
     for it, the channel default is CLEARED instead of set, and the
     employees who resolve to it are UNLINKED (see ``base_has_buttons`` in
     ``sync()``). That is a deliberate configuration, not a failure.
  2. Ensure each variant exists on the channel — rich-menu names embed a
     content signature (``staffhub:<variant>:<sig>``), so an unchanged
     variant is reused, a changed one is re-created with a freshly rendered
     HF One image (app/services/staff_oa_images.py). A variant whose grant
     combination needs more than LINE's 6-button-per-menu cap is SKIPPED
     with a warning naming the variant and its employees — see ``sync()``.
  3. Make the ``base`` variant the channel default (or clear the default
     when base is empty).
  4. Link every linked employee to their variant (bulk link API, chunked);
     unlink the ones whose variant has no menu.
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


def _plan_variants(
    assignments: Dict[str, List[str]], base_has_buttons: bool = True
) -> List[str]:
    """Variant keys to deploy: base first, then the observed combinations.

    ``base`` is normally unconditional — it is the channel default, so it
    must exist even when no employee resolves to it. When the button table
    leaves base EMPTY (``base_has_buttons=False``; see ``sync()``), it is
    dropped instead — and dropped even if employees DID resolve to it,
    because a 0-button variant has no rich menu to deploy and no channel
    default to be. Those employees are unlinked further down in ``sync()``.
    """
    keys = set(assignments)
    if base_has_buttons:
        keys |= {"base"}
    else:
        keys -= {"base"}
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

    # Is `base` — the variant an employee with no menu-relevant grant
    # resolves to — a menu at all? Since the Hub became a maid-only tool
    # (owner, 2026-08-14: "remove the clock-in button too") every remaining
    # button is gated on the `housekeeping` grant, so base has ZERO buttons
    # and there is no base menu to deploy. That is a DELIBERATE state, not a
    # breakage, and it is computed once here so every step below can branch
    # on it explicitly instead of discovering it as a side effect of the
    # >6-button guard (which would skip base for the wrong reason, print a
    # scary SKIP for a configuration that is working as intended, and then
    # KeyError on menu_ids["base"] three steps later).
    #
    # A future MENU_BUTTONS row with grant_app_id=None flips this back to
    # True and restores the original behaviour exactly — both paths are
    # tested (tests/unit/test_staff_oa_sync.py).
    base_has_buttons = bool(staff_oa_menu.buttons_for(frozenset()))

    variant_keys = _plan_variants(assignments, base_has_buttons)
    linked_count = sum(len(users) for users in assignments.values())
    print(f"Linked employees: {linked_count}; menu variants needed: {variant_keys}")
    if not base_has_buttons:
        print(
            "  base has no buttons — empty by design (the Hub is a maid-only "
            "tool): no base menu will be created and no channel default will "
            "be set. Employees without a menu-relevant grant get no Employee "
            "Hub menu at all."
        )

    existing_menus = staff_oa_service.get_rich_menu_list()
    existing_by_name = {menu.get("name", ""): menu["richMenuId"] for menu in existing_menus}

    # --- Ensure each needed variant exists (create when name/signature is new)
    menu_ids: Dict[str, str] = {}
    desired_names = set()
    skipped_variants: List[str] = []
    for key in variant_keys:
        grants = staff_oa_menu.grants_for_menu_key(key)
        button_count = len(staff_oa_menu.buttons_for(grants))
        try:
            staff_oa_menu.menu_size(button_count)
        except ValueError as exc:
            # LINE caps a rich menu at 6 buttons. No grant combination an
            # employee can actually hold overflows today — but as of
            # 2026-09-02 (รายงานแม่บ้าน) the largest real variant,
            # base+housekeeping+reception, is EXACTLY 6. The margin is one
            # MenuButton row, so this guard is a step away from live rather
            # than the comfortable insurance it was. It earned its place
            # before: with payroll + ota + a 3-button housekeeping grant, one
            # employee holding all three minted a 7-button variant, and the
            # most likely person to do that was the owner self-granting
            # everything to test the system.
            #
            # Left uncaught, staff_oa_menu.rich_menu_name() below (via
            # menu_signature -> menu_size) raises mid-loop and blocks every
            # other employee's menu from syncing too. Mirror the preview
            # script's guard (scripts/staff_oa_render_menus.py): skip just
            # this variant, name it and its employees so the operator knows
            # exactly who to fix, and keep going.
            #
            # Note this branch can no longer be reached by an EMPTY variant:
            # menu_size(0) raises too, but base is filtered out of
            # variant_keys before the loop when it has no buttons (see
            # base_has_buttons), so a 0-button variant never lands here and
            # is never reported as a SKIP. Over-cap and empty-by-design are
            # different states and read differently in the output.
            skipped_variants.append(key)
            affected = assignments.get(key, [])
            # What happens to those employees below depends on whether there
            # is a base menu left to fall back to — say the true one.
            fallback_note = (
                "they keep the base menu in the meantime."
                if base_has_buttons
                else "they get no menu at all in the meantime — base is empty "
                     "by design, so there is nothing to fall back to."
            )
            print(
                f"  SKIP   variant {key!r} needs {button_count} buttons "
                f"(LINE cap is 6): {exc}. Affected employee LINE user "
                f"id(s): {affected}. Remove one of this variant's grants "
                f"from them (or ship a >6-button layout), then re-run — "
                f"{fallback_note}"
            )
            continue

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

    # --- Channel default = base variant (or none at all, when base is empty)
    current_default = staff_oa_service.get_default_rich_menu_id()
    if not base_has_buttons:
        # No base menu exists, so nothing can be the channel default. Clear
        # whatever is there instead of leaving it: the stale-menu sweep at
        # the bottom of this run is about to delete the old base menu (it is
        # a staffhub:* menu that nothing wants any more), and a channel
        # default pointing at a deleted rich menu is precisely the
        # half-synced state this script exists to avoid. Order matters —
        # clear BEFORE the delete, never after.
        if current_default is None:
            print("  default already unset (base is empty by design)")
        elif apply:
            staff_oa_service.clear_default_rich_menu()
            print(f"  default cleared (was {current_default}) — base is empty by design")
        else:
            print(
                f"  default -> cleared (was {current_default}) — "
                f"base is empty by design"
            )
    elif current_default == menu_ids["base"]:
        print(f"  default already {menu_ids['base']}")
    elif apply:
        staff_oa_service.set_default_rich_menu(menu_ids["base"])
        print(f"  default -> {menu_ids['base']}")
    else:
        print(f"  default -> {menu_ids['base']} (was {current_default})")

    # --- Per-user Role Menu links (bulk, chunked)
    for key in sorted(assignments):
        users = assignments[key]
        if key in skipped_variants:
            # No menu was created for this over-sized variant (see the SKIP
            # above), so menu_ids[key] does not exist — indexing it here
            # would KeyError and crash the run. Explicitly (re)link these
            # employees to `base` instead of just leaving them alone: base
            # is a strict subset of every other variant's buttons, so this
            # can never hand out more than the employee is entitled to, it
            # only ever hides buttons LINE's 6-button cap won't let this
            # particular combination show. Explicit beats "leave whatever
            # link they already had" because a prior sync could have linked
            # them to some other now-stale menu — this guarantees they land
            # on the current, valid channel-default menu instead.
            #
            # ...unless there IS no base menu (base is empty by design, see
            # base_has_buttons above). Then the fallback is to UNLINK them:
            # menu_ids["base"] does not exist to fall back to, and leaving
            # their existing link alone would point them at a menu the stale
            # sweep below is about to delete. Unlinked is the honest state —
            # LINE shows them no rich menu, which is exactly what an
            # employee whose buttons cannot be rendered should see, and it
            # still beats a link to another variant's menu.
            if apply:
                if base_has_buttons:
                    staff_oa_service.bulk_link_rich_menu(users, menu_ids["base"])
                else:
                    staff_oa_service.bulk_unlink_rich_menu(users)
            if base_has_buttons:
                print(
                    f"  link   {len(users)} user(s) -> {key!r} "
                    f"(fallback: base — variant exceeds LINE's 6-button cap)"
                )
            else:
                print(
                    f"  unlink {len(users)} user(s) <- {key!r} "
                    f"(fallback: none — variant exceeds LINE's 6-button cap "
                    f"and base is empty by design)"
                )
            continue
        if key == "base" and not base_has_buttons:
            # Employees whose whole variant is the empty base. There is no
            # menu for them, by design — unlink so they hold no rich menu at
            # all rather than a stale link to the base menu the sweep below
            # deletes. Deliberate, not a skip: printed plainly, no WARNING.
            if apply:
                staff_oa_service.bulk_unlink_rich_menu(users)
            print(
                f"  unlink {len(users)} user(s) <- {key!r} "
                f"(base is empty by design — no menu for them)"
            )
            continue
        if apply:
            staff_oa_service.bulk_link_rich_menu(users, menu_ids[key])
        print(f"  link   {len(users)} user(s) -> {key!r}")

    # --- Delete stale staffhub menus (superseded signatures, unused variants)
    # Runs AFTER per-user linking above, which matters for skipped variants:
    # kept_ids/desired_names are built only from menu_ids, which never gained
    # an entry for a skipped key (its create step never ran), so a skipped
    # variant's own menu is simply never protected here. That is safe, not
    # just harmless: every other variant's id/name was still added to
    # menu_ids/desired_names in the loop above regardless of what got
    # skipped, so this step keeps every menu that is genuinely in use. And
    # if an old menu for the *skipped* key happens to still exist (e.g. a
    # prior run created it back when that grant combination fit under 6
    # buttons), nobody is linked to it by the time we get here — the
    # per-user step above already moved its would-be employees onto `base`
    # first — so reclaiming it as "stale" here deletes a menu that is truly
    # unreferenced, not one still in use.
    #
    # The same ordering argument carries the empty-base case, which leans on
    # it harder: the old base menu is not in desired_names (base was never
    # planned), so this sweep DELETES it — and by now the channel default no
    # longer points at it (cleared above) and its employees no longer link
    # to it (unlinked above). Deleting last is what makes both true.
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

    if skipped_variants:
        disposition = (
            "employees were linked to the base menu instead"
            if base_has_buttons
            else "employees were unlinked instead (base is empty by design, "
                 "so there is no menu to fall back to)"
        )
        print(
            f"WARNING: {len(skipped_variants)} variant(s) skipped for "
            f"exceeding LINE's 6-button cap: {skipped_variants}. Their "
            f"{disposition}; every other variant and employee synced "
            f"normally."
        )

    print("Done." if apply else "Dry-run complete — nothing changed.")
    # Exit 0 even when variants were skipped. A skipped variant is a data
    # problem — an employee holding a grant combination LINE physically
    # cannot render as one menu — not a sync failure: every other variant
    # still deployed and every other (and this) employee still got linked
    # to a valid menu, so nothing here needs a human to intervene on the
    # sync itself. Per this repo's alerting guardrail (only page on
    # confirmed/unrecoverable failures; suppress self-recoverable blips),
    # that does not warrant turning a cron/CI run red — the WARNING line
    # above is what should reach an operator (e.g. via log/Slack scraping),
    # not a failed-job page. Genuine failures (missing credentials, a LINE
    # API error) already return/raise non-zero through their own paths
    # above and are unaffected by this.
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
