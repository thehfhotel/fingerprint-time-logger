"""Unit tests for scripts/staff_oa_sync.py — the >6-button variant guard.

LINE rich menus cap at 6 buttons. Since the reimbursement base button was
removed (2026-08-14), every REAL grant combination fits — all three grants
together now yield exactly 6 — so these tests mint the over-sized variant
with a synthetic fourth grant patched into the menu table (see ``sync_env``).
The guard itself must stay: the next button row added to ``MENU_BUTTONS``
re-overflows the all-grants combo. Uncaught, ``staff_oa_menu.
rich_menu_name()`` (via ``menu_signature`` -> ``menu_size``) raises
``ValueError`` mid-loop in ``sync()`` and blocks every *other* employee's
menu from syncing too.

These tests pin the guard: the over-sized variant is skipped with a warning
that names the variant and its employees, every other variant still syncs,
the run never raises, and the affected employee is never linked to the
wrong menu (they fall back to `base`, LINE's own default).

No network access: every LINE Messaging API call (``app.services.
staff_oa_service``) and image render (``app.services.staff_oa_images``) is
monkeypatched. ``scripts/`` has no ``__init__.py``, so the module is loaded
the same way the interpreter loads it directly — as a top-level import with
the repo root on ``sys.path`` (pytest already puts it there via
``tests/__init__.py``; see tests/conftest.py's own ``app.*`` imports).
"""
import os
import sys
from typing import Dict, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scripts import staff_oa_sync  # noqa: E402
from app.services import staff_oa_menu  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture data: one over-granted employee (all three real grants plus the
# synthetic ``extra`` grant sync_env patches in -> 7 buttons) plus two
# ordinary ones, so the assignments map has more than one variant to prove
# the skip is scoped to just the bad one.
# ---------------------------------------------------------------------------
OVERSIZED_KEY = "base+extra+housekeeping+ota+payroll"  # 1 + 1 + 3 + 1 + 1 = 7
PAYROLL_KEY = "base+payroll"
BASE_KEY = "base"

OVERSIZED_LINE_USER_IDS = ["U-owner-overgranted"]
PAYROLL_LINE_USER_IDS = ["U-payroll-1", "U-payroll-2"]
BASE_LINE_USER_IDS = ["U-base-1"]


def _assignments() -> Dict[str, List[str]]:
    return {
        OVERSIZED_KEY: list(OVERSIZED_LINE_USER_IDS),
        PAYROLL_KEY: list(PAYROLL_LINE_USER_IDS),
        BASE_KEY: list(BASE_LINE_USER_IDS),
    }


class _FakeDb:
    """Stand-in for the SQLAlchemy Session — sync() only calls .close()."""

    def close(self):
        pass


@pytest.fixture
def sync_env(monkeypatch):
    """Patch every I/O boundary staff_oa_sync.sync() touches.

    Returns a dict of call-recorders so tests can assert on what the LINE
    API *would* have been asked to do, without ever making a request.
    """
    calls = {
        "created": [],       # (payload,) for staff_oa_service.create_rich_menu
        "uploaded": [],       # (rich_menu_id, png_bytes)
        "linked": [],         # (line_user_ids, rich_menu_id)
        "deleted": [],        # rich_menu_id
        "default_set": [],    # rich_menu_id
    }

    monkeypatch.setattr(staff_oa_sync.staff_oa_service, "is_enabled", lambda: True)
    monkeypatch.setattr(staff_oa_sync, "SessionLocal", lambda: _FakeDb())
    # No real grant combination can overflow LINE's 6-button cap since the
    # reimbursement base button was removed (all three grants = exactly 6),
    # so the over-sized variant is minted with a synthetic fourth grant.
    # Every staff_oa_menu function reads these module globals at call time,
    # so patching them is enough for buttons_for/grants_for_menu_key alike.
    monkeypatch.setattr(
        staff_oa_menu,
        "MENU_BUTTONS",
        staff_oa_menu.MENU_BUTTONS
        + (
            staff_oa_menu.MenuButton(
                grant_app_id="extra",
                label="ทดสอบ",
                url="https://extra.thehfhotel.org",
                glyph="clock",
            ),
        ),
    )
    monkeypatch.setattr(
        staff_oa_menu,
        "MENU_GRANT_APP_IDS",
        staff_oa_menu.MENU_GRANT_APP_IDS | {"extra"},
    )
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service,
        "employee_menu_assignments",
        lambda db: _assignments(),
    )
    # No menus pre-exist on the channel: everything needed gets "created".
    monkeypatch.setattr(staff_oa_sync.staff_oa_service, "get_rich_menu_list", lambda: [])
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "get_default_rich_menu_id", lambda: None
    )

    def _create_rich_menu(payload):
        calls["created"].append(payload)
        return f"richmenu-{len(calls['created'])}"

    def _upload_rich_menu_image(rich_menu_id, png_bytes):
        calls["uploaded"].append((rich_menu_id, png_bytes))

    def _set_default_rich_menu(rich_menu_id):
        calls["default_set"].append(rich_menu_id)

    def _bulk_link_rich_menu(line_user_ids, rich_menu_id):
        calls["linked"].append((list(line_user_ids), rich_menu_id))

    def _delete_rich_menu(rich_menu_id):
        calls["deleted"].append(rich_menu_id)

    monkeypatch.setattr(staff_oa_sync.staff_oa_service, "create_rich_menu", _create_rich_menu)
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "upload_rich_menu_image", _upload_rich_menu_image
    )
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "set_default_rich_menu", _set_default_rich_menu
    )
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "bulk_link_rich_menu", _bulk_link_rich_menu
    )
    monkeypatch.setattr(staff_oa_sync.staff_oa_service, "delete_rich_menu", _delete_rich_menu)
    # Real PNG rendering (PIL + Thai font lookup) is irrelevant to this
    # guard and would just slow the test down — stub it out.
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_images, "render_menu_image", lambda buttons: b"fake-png"
    )

    return calls


class TestOversizedVariantIsSkippedNotFatal:
    def test_sync_does_not_raise(self, sync_env):
        # Before the fix this crashed mid-loop with an uncaught ValueError
        # from staff_oa_menu.menu_size(7) via rich_menu_name().
        exit_code = staff_oa_sync.sync(apply=True)
        assert exit_code == 0

    def test_warning_names_the_oversized_variant_and_its_employees(self, sync_env, capsys):
        staff_oa_sync.sync(apply=True)
        out = capsys.readouterr().out
        assert OVERSIZED_KEY in out
        for line_user_id in OVERSIZED_LINE_USER_IDS:
            assert line_user_id in out
        # Names the button count that broke LINE's cap, not just the key.
        assert "7 buttons" in out or "needs 7" in out

    def test_no_menu_is_created_for_the_oversized_variant(self, sync_env):
        # staff_oa_menu.rich_menu_name() itself cannot even be called for
        # the oversized grant set (that ValueError is exactly what the SKIP
        # branch avoids triggering) — so the only way to prove no such menu
        # was created is to check what *did* get created: 2 real variants
        # (base, base+payroll), never a 7-button payload.
        staff_oa_sync.sync(apply=True)
        assert len(sync_env["created"]) == 2
        for payload in sync_env["created"]:
            assert len(payload["areas"]) <= 6


class TestOtherVariantsStillSyncNormally:
    def test_base_and_payroll_variants_are_created(self, sync_env):
        staff_oa_sync.sync(apply=True)
        created_names = {payload["name"] for payload in sync_env["created"]}
        assert staff_oa_menu.rich_menu_name(set()) in created_names
        assert staff_oa_menu.rich_menu_name({"payroll"}) in created_names

    def test_payroll_employees_are_linked_to_the_payroll_menu(self, sync_env):
        staff_oa_sync.sync(apply=True)
        linked_by_menu = {rich_menu_id: users for users, rich_menu_id in sync_env["linked"]}
        payroll_menu_id = next(
            rid for users, rid in sync_env["linked"] if users == PAYROLL_LINE_USER_IDS
        )
        assert set(linked_by_menu[payroll_menu_id]) == set(PAYROLL_LINE_USER_IDS)

    def test_base_only_employees_are_linked_to_base(self, sync_env):
        staff_oa_sync.sync(apply=True)
        assert any(
            users == BASE_LINE_USER_IDS for users, _rich_menu_id in sync_env["linked"]
        )

    def test_channel_default_is_still_set_to_base(self, sync_env):
        staff_oa_sync.sync(apply=True)
        assert len(sync_env["default_set"]) == 1


class TestAffectedEmployeeFallsBackToBaseNotAWrongMenu:
    def test_oversized_variant_employee_is_linked_to_the_base_menu(self, sync_env):
        staff_oa_sync.sync(apply=True)
        base_rich_menu_id = next(
            rich_menu_id
            for users, rich_menu_id in sync_env["linked"]
            if set(users) & set(BASE_LINE_USER_IDS)
        )
        # The over-granted employee must land on that same base menu id —
        # not go unlinked (undefined LINE-side state) and not get a menu id
        # minted for their own too-big variant (there isn't one).
        oversized_linked_ids = [
            rich_menu_id
            for users, rich_menu_id in sync_env["linked"]
            if set(users) & set(OVERSIZED_LINE_USER_IDS)
        ]
        assert oversized_linked_ids == [base_rich_menu_id]

    def test_oversized_variant_employee_is_never_linked_to_a_nonexistent_menu_id(
        self, sync_env
    ):
        staff_oa_sync.sync(apply=True)
        created_ids = {f"richmenu-{i + 1}" for i in range(len(sync_env["created"]))}
        for users, rich_menu_id in sync_env["linked"]:
            if set(users) & set(OVERSIZED_LINE_USER_IDS):
                assert rich_menu_id in created_ids

    def test_dry_run_reports_the_fallback_without_calling_the_link_api(self, sync_env):
        # --apply is not passed: no LINE API call should fire at all, but
        # the plan (including the fallback) must still print and must not
        # raise.
        exit_code = staff_oa_sync.sync(apply=False)
        assert exit_code == 0
        assert sync_env["linked"] == []
        assert sync_env["created"] == []


class TestStaleMenuDeletionIsUnaffectedBySkip:
    def test_a_still_used_menu_is_not_deleted(self, sync_env, monkeypatch):
        # Simulate a channel that already has the base and payroll menus
        # deployed (correct signatures) plus a stray non-staffhub menu.
        base_name = staff_oa_menu.rich_menu_name(set())
        payroll_name = staff_oa_menu.rich_menu_name({"payroll"})
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_rich_menu_list",
            lambda: [
                {"name": base_name, "richMenuId": "richmenu-existing-base"},
                {"name": payroll_name, "richMenuId": "richmenu-existing-payroll"},
                {"name": "not-a-staffhub-menu", "richMenuId": "richmenu-unrelated"},
            ],
        )
        staff_oa_sync.sync(apply=True)
        assert "richmenu-existing-base" not in sync_env["deleted"]
        assert "richmenu-existing-payroll" not in sync_env["deleted"]
        assert "richmenu-unrelated" not in sync_env["deleted"]

    def test_a_stale_menu_for_the_oversized_variant_is_reclaimed_safely(
        self, sync_env, monkeypatch
    ):
        # A menu for the now-oversized variant somehow still exists on the
        # channel (e.g. created before housekeeping grew to 3 buttons).
        # Linking happens before deletion, so by the time this runs, no
        # employee is linked to it any more (they were moved to base) —
        # reclaiming it as stale is safe, not a "still in use" deletion.
        stale_name = f"staffhub:{OVERSIZED_KEY}:deadbeefcafe"
        base_name = staff_oa_menu.rich_menu_name(set())
        payroll_name = staff_oa_menu.rich_menu_name({"payroll"})
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_rich_menu_list",
            lambda: [
                {"name": stale_name, "richMenuId": "richmenu-stale-oversized"},
                {"name": base_name, "richMenuId": "richmenu-existing-base"},
                {"name": payroll_name, "richMenuId": "richmenu-existing-payroll"},
            ],
        )
        staff_oa_sync.sync(apply=True)
        assert "richmenu-stale-oversized" in sync_env["deleted"]
        assert "richmenu-existing-base" not in sync_env["deleted"]
        assert "richmenu-existing-payroll" not in sync_env["deleted"]


class TestExitCodeStaysZeroForAWarningOnlyRun:
    def test_partial_skip_is_not_a_fatal_run(self, sync_env):
        # A skipped over-sized variant is a data problem (one employee's
        # grants), not a sync failure — the rest of staff still got synced.
        assert staff_oa_sync.sync(apply=True) == 0

    def test_a_run_with_no_oversized_variant_is_also_zero(self, sync_env, monkeypatch):
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "employee_menu_assignments",
            lambda db: {PAYROLL_KEY: list(PAYROLL_LINE_USER_IDS)},
        )
        assert staff_oa_sync.sync(apply=True) == 0
