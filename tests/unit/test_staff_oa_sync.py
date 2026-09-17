"""Unit tests for scripts/staff_oa_sync.py — the real `base` variant and
the >MAX_BUTTONS variant guard.

Two independent ways a variant can fail to be a LINE rich menu, and this
file pins the sync's handling of both:

BASE IS A REAL VARIANT (live since 2026-09-18)
-----------------------------------------------
`base` — the variant an employee with no OTHER menu-relevant grant resolves
to — used to be empty (every button was gated on a grant, 2026-08-14 through
2026-09-17). The owner's 2026-09-18 decision added แจ้งลา (file a leave
request) as an UNGATED tile every linked employee sees, so `base` is now a
real, always-present variant: it is created, it is the channel default, and
every employee who resolves to it is LINKED, not unlinked.

The EMPTY-base branch (no menu created, default cleared, base employees
unlinked — see ``base_has_buttons`` in ``sync()``) still exists in the code
as a defensive fallback for a future MENU_BUTTONS table with no ungated row
at all. It is no longer the production reality, so it is covered by the
smaller ``TestEmptyBaseIsStillHandledDefensively`` class below, driven by a
synthetic fixture that strips the ungated row back out — the mirror image of
what ``sync_env_with_base`` used to do when the empty state was the default.

OVER THE HUB'S BUTTON LAYOUT CAP (insurance)
---------------------------------------------
The Hub's layout supports at most ``staff_oa_menu.MAX_BUTTONS`` (8) buttons
per menu — LINE itself allows up to 20 rich-menu areas, so this is our own
grid limit, not a LINE cap. Uncaught, ``rich_menu_name()`` (via
``menu_signature`` -> ``menu_size``) raises mid-loop, so ONE over-granted
employee wedges rich-menu deployment for everyone. The guard skips just that
variant with a warning naming it and its employees; every other variant
still syncs and the run never raises.

WHY THE OVER-SIZED VARIANT IS SYNTHETIC
----------------------------------------
The real table's biggest variant (every menu-relevant grant: `housekeeping`
+ `reception`) is 7 buttons — one under the cap of 8 — so no real grant
combination can overflow today. The guard is load-bearing anyway (the
overflow actually happened once, back when payroll + ota + housekeeping = 7
buttons against a 6-button cap), so its test mints an over-sized variant from
a SYNTHETIC grant monkeypatched into ``MENU_BUTTONS`` / ``MENU_GRANT_APP_IDS``
— sized from ``MAX_BUTTONS`` rather than hardcoded, so it stays exactly one
past the cap however the button table or the cap itself changes.
``TestFixturePremise`` asserts this so the fixture cannot silently rot into
testing nothing.

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
# Synthetic over-sized variant
#
# The real table's biggest variant is `buttons_for(MENU_GRANT_APP_IDS)` — an
# employee holding every menu-relevant grant. To overflow we add a synthetic
# grant that carries however many extra buttons it takes to land one past
# staff_oa_menu.MAX_BUTTONS. Deriving the count from the real table and the
# cap (instead of hard-coding it) is the point: this file broke once already
# because it assumed a button count the real table no longer produced.
#
# ONE synthetic grant carrying several buttons, rather than several
# one-button synthetic grants, because: the variant key stays short and
# readable; the synthetic side is a single obvious knob (how many buttons
# overflow takes); and a multi-button grant is exactly how the real
# `housekeeping` grant already behaves, so the fixture exercises the same
# shape production does rather than inventing a new one.
# ---------------------------------------------------------------------------
SYNTHETIC_GRANT = "extra"

# The biggest REAL variant is what `buttons_for(MENU_GRANT_APP_IDS)` actually
# returns (base's แจ้งลา tile plus every button a grant reveals), not a raw
# row count — `MenuButton.hidden_by_grant_app_ids` lets a row be defined but
# not shown for a particular grant combination.
MAX_REAL_BUTTON_COUNT = len(
    staff_oa_menu.buttons_for(staff_oa_menu.MENU_GRANT_APP_IDS)
)  # 7 today
SYNTHETIC_BUTTON_COUNT = max(
    1, (staff_oa_menu.MAX_BUTTONS + 1) - MAX_REAL_BUTTON_COUNT
)  # 2 today
OVERSIZED_BUTTON_COUNT = MAX_REAL_BUTTON_COUNT + SYNTHETIC_BUTTON_COUNT  # 9 today

# .invalid is reserved by RFC 2606 and resolves nowhere — these URLs are
# never fetched (nothing in sync() opens a socket, and image rendering is
# stubbed), but an unroutable host makes that explicit.
SYNTHETIC_BUTTONS = tuple(
    staff_oa_menu.MenuButton(
        grant_app_id=SYNTHETIC_GRANT,
        label=f"ทดสอบ {index + 1}",
        url=f"https://synthetic-{index + 1}.invalid/",
        glyph="clock",
    )
    for index in range(SYNTHETIC_BUTTON_COUNT)
)


def _strip_base_button(buttons):
    """Every button except the ungated (grant_app_id=None) one(s)."""
    return tuple(button for button in buttons if button.grant_app_id is not None)


# The defensive empty-base fixture's own synthetic grant: base is one button
# lighter with the ungated row stripped out, so this needs one more synthetic
# button than SYNTHETIC_BUTTONS to still land past the cap.
SYNTHETIC_GRANT_NO_BASE = "extra-no-base"
MAX_REAL_BUTTON_COUNT_NO_BASE = len(
    _strip_base_button(staff_oa_menu.buttons_for(staff_oa_menu.MENU_GRANT_APP_IDS))
)  # 6 today
SYNTHETIC_BUTTON_COUNT_NO_BASE = max(
    1, (staff_oa_menu.MAX_BUTTONS + 1) - MAX_REAL_BUTTON_COUNT_NO_BASE
)  # 3 today
SYNTHETIC_BUTTONS_NO_BASE = tuple(
    staff_oa_menu.MenuButton(
        grant_app_id=SYNTHETIC_GRANT_NO_BASE,
        label=f"ทดสอบข {index + 1}",
        url=f"https://synthetic-nobase-{index + 1}.invalid/",
        glyph="clock",
    )
    for index in range(SYNTHETIC_BUTTON_COUNT_NO_BASE)
)

# The keys sync() will see, built the way staff_oa_menu.menu_key() builds
# them (base first, then grants sorted) so they always match what the module
# would mint: "base+housekeeping+reception" and
# "base+extra+housekeeping+reception" today. HOUSEKEEPING_KEY is the maximal
# REAL variant (every menu-relevant grant, not just `housekeeping` — the name
# predates `reception` joining the table and is kept for continuity with the
# rest of this suite).
BASE_KEY = "base"
HOUSEKEEPING_KEY = "+".join(["base"] + sorted(staff_oa_menu.MENU_GRANT_APP_IDS))
OVERSIZED_KEY = "+".join(
    ["base"] + sorted(set(staff_oa_menu.MENU_GRANT_APP_IDS) | {SYNTHETIC_GRANT})
)
OVERSIZED_NO_BASE_KEY = "+".join(
    ["base"]
    + sorted(set(staff_oa_menu.MENU_GRANT_APP_IDS) | {SYNTHETIC_GRANT_NO_BASE})
)

REAL_GRANTS = frozenset(staff_oa_menu.MENU_GRANT_APP_IDS)

OVERSIZED_LINE_USER_IDS = ["U-owner-overgranted"]
HOUSEKEEPING_LINE_USER_IDS = ["U-maid-1", "U-maid-2"]
BASE_LINE_USER_IDS = ["U-base-1"]

# A `staffhub:base:*` menu whose signature predates the current button table
# (e.g. from before แจ้งลา was added, or before the image style changed). It
# cannot be minted with rich_menu_name(set()) any more (that would just
# produce today's signature) — which is honest anyway: the point of this
# fixture is a menu whose signature no longer matches anything current.
STALE_BASE_MENU_NAME = f"staffhub:{BASE_KEY}:0000deadbeef"


def _assignments(oversized_key: str = OVERSIZED_KEY) -> Dict[str, List[str]]:
    """One over-granted employee plus two ordinary variants, so the skip can
    be proved scoped to just the bad variant."""
    return {
        oversized_key: list(OVERSIZED_LINE_USER_IDS),
        HOUSEKEEPING_KEY: list(HOUSEKEEPING_LINE_USER_IDS),
        BASE_KEY: list(BASE_LINE_USER_IDS),
    }


class _FakeDb:
    """Stand-in for the SQLAlchemy Session — sync() only calls .close()."""

    def close(self):
        pass


def _install_sync_env(monkeypatch, empty_base=False):
    """Patch every I/O boundary staff_oa_sync.sync() touches.

    ``empty_base=True`` strips the ungated แจ้งลา row back out (plus swaps in
    the no-base synthetic grant), restoring the pre-2026-09-18 "base is
    empty" world for the defensive-path tests. The default keeps the real,
    production table — base already has a real button (แจ้งลา), nothing to
    patch there.

    Returns a dict of call-recorders so tests can assert on what the LINE
    API *would* have been asked to do, without ever making a request.
    """
    calls = {
        "created": [],        # (payload,) for staff_oa_service.create_rich_menu
        "uploaded": [],       # (rich_menu_id, png_bytes)
        "linked": [],         # (line_user_ids, rich_menu_id)
        "unlinked": [],       # line_user_ids
        "deleted": [],        # rich_menu_id
        "default_set": [],    # rich_menu_id
        "default_cleared": [],  # one entry per clear_default_rich_menu() call
        # Every write in call order, so tests can assert on SEQUENCE and not
        # just on the set of calls. sync()'s safety argument for reclaiming a
        # stale menu is an ordering argument ("nobody is linked to it, and
        # the channel default no longer names it, by the time we get here"),
        # and ordering is only checkable here.
        "order": [],          # (kind, reference)
    }

    monkeypatch.setattr(staff_oa_sync.staff_oa_service, "is_enabled", lambda: True)
    monkeypatch.setattr(staff_oa_sync, "SessionLocal", lambda: _FakeDb())
    # Every staff_oa_menu function reads these module globals at call time,
    # so patching them is enough for buttons_for / grants_for_menu_key /
    # menu_key alike.
    if empty_base:
        monkeypatch.setattr(
            staff_oa_menu,
            "MENU_BUTTONS",
            _strip_base_button(staff_oa_menu.MENU_BUTTONS) + SYNTHETIC_BUTTONS_NO_BASE,
        )
        monkeypatch.setattr(
            staff_oa_menu,
            "MENU_GRANT_APP_IDS",
            staff_oa_menu.MENU_GRANT_APP_IDS | {SYNTHETIC_GRANT_NO_BASE},
        )
    else:
        monkeypatch.setattr(
            staff_oa_menu,
            "MENU_BUTTONS",
            staff_oa_menu.MENU_BUTTONS + SYNTHETIC_BUTTONS,
        )
        monkeypatch.setattr(
            staff_oa_menu,
            "MENU_GRANT_APP_IDS",
            staff_oa_menu.MENU_GRANT_APP_IDS | {SYNTHETIC_GRANT},
        )
    oversized_key = OVERSIZED_NO_BASE_KEY if empty_base else OVERSIZED_KEY
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service,
        "employee_menu_assignments",
        lambda db: _assignments(oversized_key),
    )
    # No menus pre-exist on the channel: everything needed gets "created".
    monkeypatch.setattr(staff_oa_sync.staff_oa_service, "get_rich_menu_list", lambda: [])
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "get_default_rich_menu_id", lambda: None
    )

    def _create_rich_menu(payload):
        calls["created"].append(payload)
        rich_menu_id = f"richmenu-{len(calls['created'])}"
        calls["order"].append(("create", rich_menu_id))
        return rich_menu_id

    def _upload_rich_menu_image(rich_menu_id, png_bytes):
        calls["uploaded"].append((rich_menu_id, png_bytes))
        calls["order"].append(("upload", rich_menu_id))

    def _set_default_rich_menu(rich_menu_id):
        calls["default_set"].append(rich_menu_id)
        calls["order"].append(("default", rich_menu_id))

    def _clear_default_rich_menu():
        calls["default_cleared"].append(True)
        calls["order"].append(("default-clear", None))

    def _bulk_link_rich_menu(line_user_ids, rich_menu_id):
        calls["linked"].append((list(line_user_ids), rich_menu_id))
        calls["order"].append(("link", rich_menu_id))

    def _bulk_unlink_rich_menu(line_user_ids):
        calls["unlinked"].append(list(line_user_ids))
        calls["order"].append(("unlink", tuple(line_user_ids)))

    def _delete_rich_menu(rich_menu_id):
        calls["deleted"].append(rich_menu_id)
        calls["order"].append(("delete", rich_menu_id))

    monkeypatch.setattr(staff_oa_sync.staff_oa_service, "create_rich_menu", _create_rich_menu)
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "upload_rich_menu_image", _upload_rich_menu_image
    )
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "set_default_rich_menu", _set_default_rich_menu
    )
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "clear_default_rich_menu", _clear_default_rich_menu
    )
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "bulk_link_rich_menu", _bulk_link_rich_menu
    )
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_service, "bulk_unlink_rich_menu", _bulk_unlink_rich_menu
    )
    monkeypatch.setattr(staff_oa_sync.staff_oa_service, "delete_rich_menu", _delete_rich_menu)
    # Real PNG rendering (PIL + Thai font lookup) is irrelevant to these
    # guards and would just slow the tests down — stub it out.
    monkeypatch.setattr(
        staff_oa_sync.staff_oa_images, "render_menu_image", lambda buttons: b"fake-png"
    )

    return calls


@pytest.fixture
def sync_env(monkeypatch):
    """The production shape: base is real (แจ้งลา), plus the synthetic
    over-sized variant."""
    return _install_sync_env(monkeypatch)


@pytest.fixture
def sync_env_empty_base(monkeypatch):
    """The defensive shape: base has been stripped back to empty, plus its
    own synthetic over-sized variant. Proves the empty-base branch — no
    longer reachable with the real table — still behaves."""
    return _install_sync_env(monkeypatch, empty_base=True)


def _created_ids(calls):
    """name -> richMenuId, using the id the fake create_rich_menu minted."""
    return {
        payload["name"]: f"richmenu-{index + 1}"
        for index, payload in enumerate(calls["created"])
    }


def _linked_ids_for(calls, line_user_ids):
    return [
        rich_menu_id
        for users, rich_menu_id in calls["linked"]
        if set(users) & set(line_user_ids)
    ]


def _unlinked_users(calls):
    return {user for chunk in calls["unlinked"] for user in chunk}


class TestFixturePremise:
    """The fixtures are synthetic on purpose — prove they are synthetic for
    the right reason, so they can never quietly stop testing the guards."""

    def test_the_real_base_variant_has_the_leave_tile(self):
        # No monkeypatching: this is the production table. Everything in
        # TestBaseMenuIsCreatedAndDefaulted below is about this fact.
        buttons = staff_oa_menu.buttons_for(frozenset())
        assert len(buttons) == 1
        assert buttons[0].label == "แจ้งลา"

    def test_real_table_alone_cannot_overflow_the_layout_cap(self):
        # Also the production table. The biggest real variant is every
        # menu-relevant grant together, and it sits at 7 — one under
        # MAX_BUTTONS (8). If this ever fails, the real table grew past the
        # cap and the guard is live in production — keep the synthetic
        # fixture anyway (it pins the over-cap path deterministically), but
        # the docstring above needs updating and real employees are losing
        # their menus.
        assert len(staff_oa_menu.buttons_for(REAL_GRANTS)) <= staff_oa_menu.MAX_BUTTONS
        assert MAX_REAL_BUTTON_COUNT == len(staff_oa_menu.buttons_for(REAL_GRANTS))

    def test_fixture_mints_an_oversized_variant_the_real_table_cannot(self, sync_env):
        grants = staff_oa_menu.grants_for_menu_key(OVERSIZED_KEY)
        assert SYNTHETIC_GRANT in grants
        button_count = len(staff_oa_menu.buttons_for(grants))
        assert button_count == OVERSIZED_BUTTON_COUNT
        assert button_count > staff_oa_menu.MAX_BUTTONS
        with pytest.raises(ValueError):
            staff_oa_menu.menu_size(button_count)

    def test_the_other_fixture_variants_are_real_ones(self, sync_env):
        # base and the all-grants variant must be honest-to-goodness
        # production variants, not synthetic — otherwise "every other
        # variant still syncs" would be proving nothing about the real
        # system. base carries exactly its one real tile under this fixture:
        # the synthetic grant adds buttons only to its own variant.
        assert staff_oa_menu.grants_for_menu_key(HOUSEKEEPING_KEY) == REAL_GRANTS
        assert SYNTHETIC_GRANT not in HOUSEKEEPING_KEY
        assert len(staff_oa_menu.buttons_for(REAL_GRANTS)) == MAX_REAL_BUTTON_COUNT
        assert len(staff_oa_menu.buttons_for(frozenset())) == 1

    def test_the_empty_base_fixture_truly_empties_base(self, sync_env_empty_base):
        assert staff_oa_menu.buttons_for(frozenset()) == ()
        assert len(staff_oa_menu.buttons_for(REAL_GRANTS)) == MAX_REAL_BUTTON_COUNT_NO_BASE
        oversized = staff_oa_menu.grants_for_menu_key(OVERSIZED_NO_BASE_KEY)
        assert len(staff_oa_menu.buttons_for(oversized)) > staff_oa_menu.MAX_BUTTONS


class TestBaseMenuIsCreatedAndDefaulted:
    """base is a real variant — it gets a menu, it becomes the channel
    default, and employees who resolve to it are LINKED."""

    def test_sync_does_not_raise_and_exits_zero(self, sync_env):
        assert staff_oa_sync.sync(apply=True) == 0

    def test_the_base_menu_is_created(self, sync_env):
        staff_oa_sync.sync(apply=True)
        base_name = staff_oa_menu.rich_menu_name(frozenset())
        created_names = {payload["name"] for payload in sync_env["created"]}
        assert base_name in created_names

    def test_channel_default_is_set_to_the_base_menu(self, sync_env):
        staff_oa_sync.sync(apply=True)
        base_name = staff_oa_menu.rich_menu_name(frozenset())
        assert sync_env["default_set"] == [_created_ids(sync_env)[base_name]]
        assert sync_env["default_cleared"] == []

    def test_channel_default_is_left_alone_when_already_correct(self, sync_env, monkeypatch):
        # Steady state after a first apply run: re-running must not churn
        # the LINE API with a redundant set-default call.
        base_name = staff_oa_menu.rich_menu_name(frozenset())
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_rich_menu_list",
            lambda: [{"name": base_name, "richMenuId": "richmenu-existing-base"}],
        )
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_default_rich_menu_id",
            lambda: "richmenu-existing-base",
        )
        staff_oa_sync.sync(apply=True)

        assert sync_env["default_set"] == []
        assert sync_env["default_cleared"] == []

    def test_base_only_employees_are_linked_to_the_base_menu(self, sync_env):
        staff_oa_sync.sync(apply=True)
        base_name = staff_oa_menu.rich_menu_name(frozenset())
        assert _linked_ids_for(sync_env, BASE_LINE_USER_IDS) == [
            _created_ids(sync_env)[base_name]
        ]
        assert set(BASE_LINE_USER_IDS) & _unlinked_users(sync_env) == set()

    def test_dry_run_makes_no_api_calls(self, sync_env, capsys):
        exit_code = staff_oa_sync.sync(apply=False)
        out = capsys.readouterr().out

        assert exit_code == 0
        assert sync_env["created"] == []
        assert sync_env["uploaded"] == []
        assert sync_env["linked"] == []
        assert sync_env["unlinked"] == []
        assert sync_env["deleted"] == []
        assert sync_env["default_set"] == []
        assert sync_env["default_cleared"] == []
        assert sync_env["order"] == []
        # ...but the plan still says what it would have done.
        assert f"link   {len(BASE_LINE_USER_IDS)} user(s) -> {BASE_KEY!r}" in out


class TestOversizedVariantIsSkippedNotFatal:
    def test_sync_does_not_raise(self, sync_env):
        # Without the guard this crashes mid-loop with an uncaught ValueError
        # from staff_oa_menu.menu_size(9) via rich_menu_name().
        exit_code = staff_oa_sync.sync(apply=True)
        assert exit_code == 0

    def test_warning_names_the_oversized_variant_and_its_employees(self, sync_env, capsys):
        staff_oa_sync.sync(apply=True)
        out = capsys.readouterr().out
        assert OVERSIZED_KEY in out
        for line_user_id in OVERSIZED_LINE_USER_IDS:
            assert line_user_id in out
        # Names the button count that broke the layout cap, not just the key.
        assert (
            f"{OVERSIZED_BUTTON_COUNT} buttons" in out
            or f"needs {OVERSIZED_BUTTON_COUNT}" in out
        )
        # And the run-level summary flags it, so a log scraper sees one line
        # even if the per-variant SKIP scrolls past.
        assert "WARNING" in out

    def test_no_menu_is_created_for_the_oversized_variant(self, sync_env):
        # staff_oa_menu.rich_menu_name() itself cannot even be called for
        # the oversized grant set (that ValueError is exactly what the SKIP
        # branch avoids triggering) — so the only way to prove no such menu
        # was created is to check what *did* get created: base and the real
        # all-grants variant, never an over-cap payload.
        staff_oa_sync.sync(apply=True)
        assert len(sync_env["created"]) == 2
        for payload in sync_env["created"]:
            assert len(payload["areas"]) <= staff_oa_menu.MAX_BUTTONS
        created_names = {payload["name"] for payload in sync_env["created"]}
        assert not any(SYNTHETIC_GRANT in name for name in created_names)
        # An image is uploaded for each created menu and nothing else.
        assert len(sync_env["uploaded"]) == len(sync_env["created"])


class TestOtherVariantsStillSyncNormally:
    def test_the_all_grants_variant_is_created(self, sync_env):
        staff_oa_sync.sync(apply=True)
        created_names = {payload["name"] for payload in sync_env["created"]}
        assert staff_oa_menu.rich_menu_name(REAL_GRANTS) in created_names

    def test_the_all_grants_menu_carries_the_real_buttons(self, sync_env):
        # The surviving variant is a real one, so its payload is worth
        # checking: every real button on the full 4x2 grid (7 today).
        staff_oa_sync.sync(apply=True)
        housekeeping_name = staff_oa_menu.rich_menu_name(REAL_GRANTS)
        payload = next(
            item for item in sync_env["created"] if item["name"] == housekeeping_name
        )
        assert len(payload["areas"]) == MAX_REAL_BUTTON_COUNT
        assert payload["size"] == {
            "width": staff_oa_menu.MENU_WIDTH,
            "height": staff_oa_menu.MENU_HEIGHT_FULL,
        }

    def test_housekeeping_employees_are_linked_to_the_all_grants_menu(self, sync_env):
        staff_oa_sync.sync(apply=True)
        housekeeping_name = staff_oa_menu.rich_menu_name(REAL_GRANTS)
        assert _linked_ids_for(sync_env, HOUSEKEEPING_LINE_USER_IDS) == [
            _created_ids(sync_env)[housekeeping_name]
        ]

    def test_housekeeping_employees_are_never_unlinked(self, sync_env):
        staff_oa_sync.sync(apply=True)
        assert not set(HOUSEKEEPING_LINE_USER_IDS) & _unlinked_users(sync_env)


class TestOversizedEmployeeFallsBackToBaseMenu:
    def test_oversized_variant_employee_is_linked_to_base(self, sync_env):
        # base is a strict subset of every other variant's buttons, so
        # falling back to it can never hand out more than the employee is
        # entitled to.
        staff_oa_sync.sync(apply=True)
        base_name = staff_oa_menu.rich_menu_name(frozenset())

        assert _linked_ids_for(sync_env, OVERSIZED_LINE_USER_IDS) == [
            _created_ids(sync_env)[base_name]
        ]
        assert set(OVERSIZED_LINE_USER_IDS) & _unlinked_users(sync_env) == set()

    def test_oversized_employee_is_not_linked_to_another_employees_menu(self, sync_env):
        # Landing on the all-grants menu would hand out buttons this
        # employee's grants may not cover, so pin that it never happens.
        staff_oa_sync.sync(apply=True)
        housekeeping_name = staff_oa_menu.rich_menu_name(REAL_GRANTS)
        housekeeping_id = _created_ids(sync_env)[housekeeping_name]
        for users, rich_menu_id in sync_env["linked"]:
            if set(users) & set(OVERSIZED_LINE_USER_IDS):
                assert rich_menu_id != housekeeping_id

    def test_dry_run_reports_the_fallback_without_calling_the_api(
        self, sync_env, capsys
    ):
        # --apply is not passed: no LINE write should fire at all, but the
        # plan (including the fallback) must still print and must not raise.
        exit_code = staff_oa_sync.sync(apply=False)
        out = capsys.readouterr().out
        assert exit_code == 0
        assert sync_env["linked"] == []
        assert sync_env["unlinked"] == []
        assert sync_env["created"] == []
        assert sync_env["uploaded"] == []
        assert sync_env["default_set"] == []
        assert sync_env["default_cleared"] == []
        assert sync_env["deleted"] == []
        # The plan still tells the operator what would happen to the
        # affected employees.
        assert OVERSIZED_KEY in out
        assert "fallback: base" in out
        for line_user_id in OVERSIZED_LINE_USER_IDS:
            assert line_user_id in out


class TestStaleMenuDeletion:
    def test_a_still_used_menu_is_not_deleted(self, sync_env, monkeypatch):
        # Simulate a channel that already has the all-grants menu deployed
        # (correct signature) plus a stray non-staffhub menu.
        housekeeping_name = staff_oa_menu.rich_menu_name(REAL_GRANTS)
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_rich_menu_list",
            lambda: [
                {"name": housekeeping_name, "richMenuId": "richmenu-existing-hk"},
                {"name": "not-a-staffhub-menu", "richMenuId": "richmenu-unrelated"},
            ],
        )
        staff_oa_sync.sync(apply=True)
        assert "richmenu-existing-hk" not in sync_env["deleted"]
        assert "richmenu-unrelated" not in sync_env["deleted"]
        # base is still created fresh (nothing deployed for it yet), but the
        # already-current all-grants menu is reused, not re-created.
        created_names = {payload["name"] for payload in sync_env["created"]}
        assert housekeeping_name not in created_names

    def test_a_stale_base_menu_signature_is_reclaimed(self, sync_env, monkeypatch):
        # A base menu left over from before the current button table (e.g.
        # pre-แจ้งลา, or an older image style). Nothing wants that signature
        # any more, so the sweep must collect it after linking employees to
        # the freshly created current-signature base.
        housekeeping_name = staff_oa_menu.rich_menu_name(REAL_GRANTS)
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_rich_menu_list",
            lambda: [
                {"name": STALE_BASE_MENU_NAME, "richMenuId": "richmenu-old-base"},
                {"name": housekeeping_name, "richMenuId": "richmenu-existing-hk"},
            ],
        )
        staff_oa_sync.sync(apply=True)
        assert "richmenu-old-base" in sync_env["deleted"]
        assert "richmenu-existing-hk" not in sync_env["deleted"]

    def test_a_stale_menu_for_the_oversized_variant_is_reclaimed_safely(
        self, sync_env, monkeypatch
    ):
        # A menu for the now-oversized variant somehow still exists on the
        # channel (e.g. created before the grant's button row grew).
        # Unlinking/relinking happens before deletion, so by the time this
        # runs, no employee is linked to it any more — reclaiming it as
        # stale is safe, not a "still in use" deletion.
        stale_name = f"staffhub:{OVERSIZED_KEY}:deadbeefcafe"
        housekeeping_name = staff_oa_menu.rich_menu_name(REAL_GRANTS)
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_rich_menu_list",
            lambda: [
                {"name": stale_name, "richMenuId": "richmenu-stale-oversized"},
                {"name": housekeeping_name, "richMenuId": "richmenu-existing-hk"},
            ],
        )
        staff_oa_sync.sync(apply=True)
        assert "richmenu-stale-oversized" in sync_env["deleted"]
        assert "richmenu-existing-hk" not in sync_env["deleted"]
        # That "BEFORE" is the whole safety argument, so assert the order and
        # not merely the outcome.
        delete_index = next(
            index
            for index, (kind, ref) in enumerate(sync_env["order"])
            if kind == "delete" and ref == "richmenu-stale-oversized"
        )
        write_indexes = [
            index
            for index, (kind, _ref) in enumerate(sync_env["order"])
            if kind in {"link", "unlink"}
        ]
        assert write_indexes
        assert max(write_indexes) < delete_index


class TestExitCodeStaysZeroForAWarningOnlyRun:
    def test_partial_skip_is_not_a_fatal_run(self, sync_env):
        # A skipped over-sized variant is a data problem (one employee's
        # grants), not a sync failure — the rest of staff still got synced.
        assert staff_oa_sync.sync(apply=True) == 0

    def test_a_run_with_no_oversized_variant_is_also_zero(self, sync_env, monkeypatch, capsys):
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "employee_menu_assignments",
            lambda db: {HOUSEKEEPING_KEY: list(HOUSEKEEPING_LINE_USER_IDS)},
        )
        assert staff_oa_sync.sync(apply=True) == 0
        out = capsys.readouterr().out
        # Zero here means "clean run": base (always planned) plus the one
        # variant with buttons deployed and no warning was printed.
        assert len(sync_env["created"]) == 2
        assert "SKIP" not in out
        assert "WARNING" not in out

    def test_an_all_maid_channel_still_deploys_and_defaults_base(self, sync_env, monkeypatch):
        # Every employee holds housekeeping+reception: nobody is assigned to
        # `base` directly, but base is still planned unconditionally (it is
        # the channel default), so it is still created and set — and nobody
        # needs unlinking either way.
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "employee_menu_assignments",
            lambda db: {HOUSEKEEPING_KEY: list(HOUSEKEEPING_LINE_USER_IDS)},
        )
        assert staff_oa_sync.sync(apply=True) == 0
        base_name = staff_oa_menu.rich_menu_name(frozenset())
        assert sync_env["unlinked"] == []
        assert sync_env["default_set"] == [_created_ids(sync_env)[base_name]]


class TestEmptyBaseIsStillHandledDefensively:
    """base has no buttons — a synthetic, no-longer-live state, but the
    branch that handles it (no menu created, default cleared, base
    employees unlinked) has to keep working if a future MENU_BUTTONS table
    ever empties base again."""

    def test_sync_does_not_raise_and_exits_zero(self, sync_env_empty_base):
        assert staff_oa_sync.sync(apply=True) == 0

    def test_no_base_menu_is_created(self, sync_env_empty_base):
        staff_oa_sync.sync(apply=True)
        created_names = {payload["name"] for payload in sync_env_empty_base["created"]}
        assert not any(
            name.startswith(f"staffhub:{BASE_KEY}:") for name in created_names
        )

    def test_channel_default_is_cleared_when_one_is_set(
        self, sync_env_empty_base, monkeypatch
    ):
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_default_rich_menu_id",
            lambda: "richmenu-old-base",
        )
        staff_oa_sync.sync(apply=True)

        assert len(sync_env_empty_base["default_cleared"]) == 1
        assert sync_env_empty_base["default_set"] == []

    def test_base_variant_employees_are_unlinked_not_linked(self, sync_env_empty_base):
        staff_oa_sync.sync(apply=True)

        assert set(BASE_LINE_USER_IDS) <= _unlinked_users(sync_env_empty_base)
        assert _linked_ids_for(sync_env_empty_base, BASE_LINE_USER_IDS) == []

    def test_empty_base_is_reported_as_deliberate_not_as_a_skip(
        self, sync_env_empty_base, capsys
    ):
        staff_oa_sync.sync(apply=True)
        out = capsys.readouterr().out

        assert "empty by design" in out
        assert f"SKIP   variant {BASE_KEY!r}" not in out

    def test_oversized_employee_with_no_base_to_fall_back_on_is_unlinked(
        self, sync_env_empty_base
    ):
        # The fallback used to be bulk_link_rich_menu(users,
        # menu_ids["base"]). With no base menu that KeyErrors, so the
        # fallback is an unlink instead: no menu is the honest state.
        staff_oa_sync.sync(apply=True)

        assert set(OVERSIZED_LINE_USER_IDS) <= _unlinked_users(sync_env_empty_base)
        assert _linked_ids_for(sync_env_empty_base, OVERSIZED_LINE_USER_IDS) == []
