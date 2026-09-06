"""Unit tests for scripts/staff_oa_sync.py — the empty `base` variant and
the >6-button variant guard.

Two independent ways a variant can fail to be a LINE rich menu, and this
file pins the sync's handling of both:

EMPTY BASE (live since 2026-08-14)
----------------------------------
The owner narrowed the Employee Hub to a maid tool and finally removed the
clock-in tile ("remove the clock-in button too"), which was the last button
not gated on the `housekeeping` grant. `base` — the variant an employee
with no menu-relevant grant resolves to — therefore has ZERO buttons.

That state used to be fatal: `menu_size(0)` raises, the >6-button guard
swallowed the ValueError and skipped the base variant, and three later
sites indexed `menu_ids["base"]` unconditionally → KeyError mid-run,
leaving the channel half-synced. It is now a NAMED, deliberate state:
``sync()`` computes ``base_has_buttons`` once, up front, and branches on
it — no base menu is created, the channel default is CLEARED rather than
set, and `base`-variant employees are UNLINKED. These tests pin all of
that, plus the exit code staying 0 (a deliberate configuration is not a
failure) and dry-run staying read-only.

OVER LINE'S 6-BUTTON CAP (insurance)
------------------------------------
LINE rich menus cap at 6 buttons. Uncaught, ``rich_menu_name()`` (via
``menu_signature`` -> ``menu_size``) raises mid-loop, so ONE over-granted
employee wedges rich-menu deployment for everyone. The guard skips just
that variant with a warning naming it and its employees; every other
variant still syncs and the run never raises.

WHY THE OVER-SIZED VARIANT IS SYNTHETIC
---------------------------------------
The table has 8 rows across two menu grants (`housekeeping` and
`reception`), but two of them (สถานะห้อง, งานซ่อมค้าง) hide behind
`housekeeping`, so the SHOWN variants are `base` (0 buttons), `base+reception`
(4), `base+housekeeping` (6, since จัดการงานซ่อม was widened 2026-09-06 into
a tile a maid reaches too) and `base+housekeeping+reception` (6). No real
grant combination can overflow LINE's cap — but as of 2026-09-02 the biggest
one SITS ON it, so the margin is a single shown row rather than the
four it used to be. The guard is load-bearing (the overflow actually
happened, back when payroll + ota + housekeeping = 7 buttons, and one more
tile would make it live again), so its test mints the over-sized variant
from a SYNTHETIC grant monkeypatched into
``MENU_BUTTONS`` / ``MENU_GRANT_APP_IDS``. The fixture is deliberately
unrealistic: it models "the table grew again", the state the guard exists
for. ``TestFixturePremise`` asserts both halves of that premise so the
fixture cannot silently rot into testing nothing.

AND WHY THERE IS A SECOND, NON-EMPTY-BASE FIXTURE
-------------------------------------------------
``sync_env_with_base`` adds a SYNTHETIC BASE button (``grant_app_id=None``)
— the one-line MENU_BUTTONS change that re-adding clock-in would be. It
exists so ``TestNonEmptyBaseBehavesExactlyAsBefore`` can prove the original
path is untouched: base menu created, channel default SET, base employees
LINKED, over-cap employees falling back to base, nothing unlinked, nothing
cleared. Without it the non-empty path would have no coverage at all now
that the real table cannot produce it. Since the real table reached LINE's
cap (2026-09-02) that fixture also has to TRIM a real row to pay for the
base button — see ``_real_buttons_leaving_room_for``; otherwise the maximal
real variant would go over cap and the fixture would prove the opposite of
what it claims.

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
# Every button in MENU_BUTTONS is either base or revealed by a grant in
# MENU_GRANT_APP_IDS, so len(MENU_BUTTONS) IS the biggest variant the real
# table can produce (2 today, both from `housekeeping`). To overflow we add
# a synthetic grant that carries however many extra buttons it takes to land
# on exactly 7 — one past LINE's cap of 6, the smallest count that trips
# menu_size(). Deriving the count from the real table (instead of hard-coding
# it) is the point: this file broke once already because it assumed a button
# count the real table no longer produced, and the table has since shrunk
# again.
#
# ONE synthetic grant carrying several buttons, rather than several
# one-button synthetic grants, because: the variant key stays short and
# readable ("base+extra+housekeeping", not "base+e1+e2+e3+e4+housekeeping");
# the synthetic side is a single obvious knob (how many buttons overflow
# takes); and a multi-button grant is exactly how the real `housekeeping`
# grant already behaves, so the fixture exercises the same shape production
# does rather than inventing a new one.
# ---------------------------------------------------------------------------
SYNTHETIC_GRANT = "extra"

LINE_BUTTON_CAP = 6

# Was ``len(staff_oa_menu.MENU_BUTTONS)`` — true only while every row in the
# table was actually SHOWN together. That stopped holding on 2026-09-06:
# ``MenuButton.hidden_by_grant_app_ids`` lets a row be defined but not shown
# for a particular grant combination (สถานะห้อง and งานซ่อมค้าง both hide
# behind `housekeeping`, so the both-grants variant stays at 6 even though
# the table itself grew to 8 rows that day). The biggest REAL variant is what
# ``buttons_for(MENU_GRANT_APP_IDS)`` actually returns, not the row count.
MAX_REAL_BUTTON_COUNT = len(
    staff_oa_menu.buttons_for(staff_oa_menu.MENU_GRANT_APP_IDS)
)  # 6 today
SYNTHETIC_BUTTON_COUNT = max(1, 7 - MAX_REAL_BUTTON_COUNT)  # 1 today
OVERSIZED_BUTTON_COUNT = MAX_REAL_BUTTON_COUNT + SYNTHETIC_BUTTON_COUNT  # 7 today

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

# A synthetic BASE button (no grant), for the fixture that puts the Hub back
# into its pre-2026-08-14 shape. grant_app_id=None is the whole difference:
# it is what `base has buttons` means, and re-adding clock-in would be
# exactly this row.
SYNTHETIC_BASE_BUTTON = staff_oa_menu.MenuButton(
    grant_app_id=None,
    label="ทดสอบฐาน",
    url="https://synthetic-base.invalid/",
    glyph="clock",
)


def _real_buttons_leaving_room_for(base_button_count):
    """The rows the real both-grants menu actually SHOWS, trimmed so
    ``base + these`` still fits LINE's cap.

    The real both-grants variant sits exactly ON the cap (6 shown, even
    though the table itself has grown to 8 rows since 2026-09-06 — see
    MAX_REAL_BUTTON_COUNT). Prepending a base button on top would push it to
    7 and silently move it into the over-cap branch — which is the branch
    ``sync_env_with_base`` exists to prove is NOT taken. The fixture would
    have gone green while testing the opposite thing, so it trims instead.

    Built from ``buttons_for(MENU_GRANT_APP_IDS)`` — the rows an employee
    holding both grants actually SEES, in the order they see them — rather
    than a raw slice of ``MENU_BUTTONS``: slicing the raw table risks keeping
    a hidden row (สถานะห้อง or งานซ่อมค้าง, both invisible whenever
    `housekeeping` is also granted) while dropping a shown one, which would
    silently change how many tiles this fixture's both-grants variant
    renders. Trimming the TAIL of
    the SHOWN list keeps `housekeeping` and `reception` both owning at least
    one visible row, so MENU_GRANT_APP_IDS and the variant keys stay exactly
    what the production module would mint.
    """
    shown = staff_oa_menu.buttons_for(staff_oa_menu.MENU_GRANT_APP_IDS)
    return shown[: LINE_BUTTON_CAP - base_button_count]

# The keys sync() will see, built the way staff_oa_menu.menu_key() builds
# them (base first, then grants sorted) so they always match what the module
# would mint: "base+extra+housekeeping" and "base+housekeeping" today.
# HOUSEKEEPING_KEY is the maximal REAL variant (every menu-relevant grant);
# `housekeeping` is the only one there is today, so the name says so.
BASE_KEY = "base"
HOUSEKEEPING_KEY = "+".join(["base"] + sorted(staff_oa_menu.MENU_GRANT_APP_IDS))
OVERSIZED_KEY = "+".join(
    ["base"] + sorted(set(staff_oa_menu.MENU_GRANT_APP_IDS) | {SYNTHETIC_GRANT})
)

REAL_GRANTS = frozenset(staff_oa_menu.MENU_GRANT_APP_IDS)

OVERSIZED_LINE_USER_IDS = ["U-owner-overgranted"]
HOUSEKEEPING_LINE_USER_IDS = ["U-maid-1", "U-maid-2"]
BASE_LINE_USER_IDS = ["U-base-1"]

# A `staffhub:base:*` menu from before the clock-in button was removed. It
# cannot be minted with rich_menu_name(set()) any more (that raises now, by
# design), so it is spelled out — which is honest anyway: the point of these
# fixtures is a menu whose signature no longer matches anything.
STALE_BASE_MENU_NAME = f"staffhub:{BASE_KEY}:0000deadbeef"


def _assignments() -> Dict[str, List[str]]:
    """One over-granted employee plus two ordinary variants, so the skip can
    be proved scoped to just the bad variant."""
    return {
        OVERSIZED_KEY: list(OVERSIZED_LINE_USER_IDS),
        HOUSEKEEPING_KEY: list(HOUSEKEEPING_LINE_USER_IDS),
        BASE_KEY: list(BASE_LINE_USER_IDS),
    }


class _FakeDb:
    """Stand-in for the SQLAlchemy Session — sync() only calls .close()."""

    def close(self):
        pass


def _install_sync_env(monkeypatch, base_buttons=()):
    """Patch every I/O boundary staff_oa_sync.sync() touches.

    ``base_buttons`` is prepended to MENU_BUTTONS: empty (the default) keeps
    the real, EMPTY base variant; passing a grant-less button restores the
    pre-2026-08-14 "base has buttons" world for the comparison tests.

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
    # Mint the over-sized variant (see the module docstring: no REAL grant
    # combination reaches 7 buttons any more), and optionally a base button.
    # Every staff_oa_menu function reads these module globals at call time,
    # so patching them is enough for buttons_for / grants_for_menu_key /
    # menu_key alike.
    real_buttons = (
        staff_oa_menu.MENU_BUTTONS
        if not base_buttons
        else _real_buttons_leaving_room_for(len(base_buttons))
    )
    monkeypatch.setattr(
        staff_oa_menu,
        "MENU_BUTTONS",
        tuple(base_buttons) + real_buttons + SYNTHETIC_BUTTONS,
    )
    monkeypatch.setattr(
        staff_oa_menu,
        "MENU_GRANT_APP_IDS",
        staff_oa_menu.MENU_GRANT_APP_IDS | {SYNTHETIC_GRANT},
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
    """The production shape: base is EMPTY, plus the synthetic over-sized
    variant."""
    return _install_sync_env(monkeypatch)


@pytest.fixture
def sync_env_with_base(monkeypatch):
    """The pre-2026-08-14 shape: base has a button (synthetic), plus the same
    synthetic over-sized variant. Proves the non-empty path is unchanged."""
    return _install_sync_env(monkeypatch, base_buttons=(SYNTHETIC_BASE_BUTTON,))


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

    def test_the_real_base_variant_is_empty(self):
        # No monkeypatching: this is the production table. Everything in
        # TestEmptyBaseIsDeliberate below is about this fact. If it fails, a
        # base button came back — re-point those tests at the new reality
        # (and sync_env_with_base becomes the redundant one), do not weaken
        # them.
        assert staff_oa_menu.buttons_for(frozenset()) == ()

    def test_real_table_alone_cannot_overflow_lines_cap(self):
        # Also the production table. The biggest real variant is
        # base+housekeeping+reception, and since 2026-09-02 it is exactly AT
        # the cap (6). If this ever fails, the real table grew past 6 and the
        # guard is live in production — keep the synthetic fixture anyway (it
        # pins the >6 path deterministically), but the docstring above needs
        # updating and real employees are losing their menus.
        assert len(staff_oa_menu.buttons_for(REAL_GRANTS)) <= LINE_BUTTON_CAP
        assert MAX_REAL_BUTTON_COUNT == len(staff_oa_menu.buttons_for(REAL_GRANTS))

    def test_fixture_mints_an_oversized_variant_the_real_table_cannot(self, sync_env):
        grants = staff_oa_menu.grants_for_menu_key(OVERSIZED_KEY)
        assert SYNTHETIC_GRANT in grants
        button_count = len(staff_oa_menu.buttons_for(grants))
        assert button_count == OVERSIZED_BUTTON_COUNT
        assert button_count > 6
        with pytest.raises(ValueError):
            staff_oa_menu.menu_size(button_count)

    def test_the_other_fixture_variants_are_real_ones(self, sync_env):
        # base and base+housekeeping must be honest-to-goodness production
        # variants, not synthetic — otherwise "every other variant still
        # syncs" would be proving nothing about the real system. Note base
        # stays EMPTY under this fixture: the synthetic grant adds buttons
        # only to its own variant.
        assert staff_oa_menu.grants_for_menu_key(HOUSEKEEPING_KEY) == REAL_GRANTS
        assert SYNTHETIC_GRANT not in HOUSEKEEPING_KEY
        assert len(staff_oa_menu.buttons_for(REAL_GRANTS)) == MAX_REAL_BUTTON_COUNT
        assert staff_oa_menu.buttons_for(frozenset()) == ()

    def test_the_base_fixture_gives_base_exactly_one_button(self, sync_env_with_base):
        # The other fixture's premise: base has buttons again, the maximal
        # REAL variant is still renderable, and the over-sized variant is
        # still over-sized.
        #
        # "Still renderable" is the load-bearing half and it stopped being
        # free on 2026-09-02: the real table now fills LINE's cap on its own,
        # so the base button is only affordable because
        # _real_buttons_leaving_room_for() trims a real row to pay for it.
        # Without that trim this variant would be 7 buttons and every test in
        # TestNonEmptyBaseBehavesExactlyAsBefore would be exercising the
        # over-cap branch it exists to prove is not taken.
        assert len(staff_oa_menu.buttons_for(frozenset())) == 1
        assert len(staff_oa_menu.buttons_for(REAL_GRANTS)) == LINE_BUTTON_CAP
        staff_oa_menu.menu_size(len(staff_oa_menu.buttons_for(REAL_GRANTS)))
        # Both grants still own a row, so the variant KEYS are unchanged.
        assert staff_oa_menu.grants_for_menu_key(HOUSEKEEPING_KEY) == REAL_GRANTS
        for grant in REAL_GRANTS:
            assert staff_oa_menu.buttons_for({grant}), grant
        oversized = staff_oa_menu.grants_for_menu_key(OVERSIZED_KEY)
        assert len(staff_oa_menu.buttons_for(oversized)) > LINE_BUTTON_CAP


class TestEmptyBaseIsDeliberate:
    """base has no buttons — a named state, not an incidental skip."""

    def test_sync_does_not_raise_and_exits_zero(self, sync_env):
        # Before base_has_buttons existed this was the KeyError run: the
        # >6-button guard skipped base, then `menu_ids["base"]` blew up at
        # the default-check and the run died half-synced.
        assert staff_oa_sync.sync(apply=True) == 0

    def test_no_base_menu_is_created(self, sync_env):
        staff_oa_sync.sync(apply=True)
        created_names = {payload["name"] for payload in sync_env["created"]}
        assert created_names == {staff_oa_menu.rich_menu_name(REAL_GRANTS)}
        assert not any(
            name.startswith(f"staffhub:{BASE_KEY}:") for name in created_names
        )

    def test_channel_default_is_cleared_when_one_is_set(self, sync_env, monkeypatch):
        # The ordering point from sync(): the old base menu is about to be
        # deleted as stale, so the channel default must stop naming it.
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_default_rich_menu_id",
            lambda: "richmenu-old-base",
        )
        staff_oa_sync.sync(apply=True)

        assert len(sync_env["default_cleared"]) == 1
        assert sync_env["default_set"] == []

    def test_channel_default_is_left_alone_when_already_unset(self, sync_env):
        # The steady state after the first apply run: nothing to clear, so
        # no call at all — re-running the sync must not churn the LINE API.
        staff_oa_sync.sync(apply=True)

        assert sync_env["default_cleared"] == []
        assert sync_env["default_set"] == []

    def test_base_variant_employees_are_unlinked_not_linked(self, sync_env):
        staff_oa_sync.sync(apply=True)

        assert set(BASE_LINE_USER_IDS) <= _unlinked_users(sync_env)
        # And emphatically not linked to anything — least of all the maid
        # menu, which they hold no grant for.
        assert _linked_ids_for(sync_env, BASE_LINE_USER_IDS) == []

    def test_empty_base_is_reported_as_deliberate_not_as_a_skip(self, sync_env, capsys):
        staff_oa_sync.sync(apply=True)
        out = capsys.readouterr().out

        assert "empty by design" in out
        # The only SKIP in the run is the genuine over-cap one. An empty base
        # must never be lumped in with it: one is a configuration, the other
        # is an employee whose grants LINE cannot render.
        assert out.count("SKIP") == 1
        assert OVERSIZED_KEY in out
        assert f"SKIP   variant {BASE_KEY!r}" not in out

    def test_dry_run_makes_no_api_calls(self, sync_env, capsys):
        # Read-only GETs (the menu list, the current default) are what a
        # dry-run IS; every WRITE recorder must stay empty.
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
        # ...but the plan still says what it would have done. The unlink
        # line reports a COUNT, like the link lines it sits beside and
        # unlike the over-cap SKIP: an empty base can mean every non-maid on
        # the payroll, and dumping hundreds of LINE user ids would bury the
        # one line an operator needs. The over-cap SKIP names ids because it
        # names people to go fix.
        assert "empty by design" in out
        assert f"unlink {len(BASE_LINE_USER_IDS)} user(s) <- {BASE_KEY!r}" in out

    def test_dry_run_reports_the_default_it_would_clear(self, sync_env, monkeypatch, capsys):
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_default_rich_menu_id",
            lambda: "richmenu-old-base",
        )
        assert staff_oa_sync.sync(apply=False) == 0
        out = capsys.readouterr().out

        assert sync_env["default_cleared"] == []
        assert "richmenu-old-base" in out
        assert "clear" in out.lower()

    def test_default_is_cleared_and_users_unlinked_before_stale_deletion(
        self, sync_env, monkeypatch
    ):
        # The whole ordering argument in one test: the old base menu is
        # deleted LAST, after nothing points at it any more. Reversed, the
        # channel default would name a deleted rich menu and base employees
        # would hold a link to it — the half-synced state this design exists
        # to prevent.
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_default_rich_menu_id",
            lambda: "richmenu-old-base",
        )
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_rich_menu_list",
            lambda: [
                {"name": STALE_BASE_MENU_NAME, "richMenuId": "richmenu-old-base"},
            ],
        )
        staff_oa_sync.sync(apply=True)

        kinds = [kind for kind, _ref in sync_env["order"]]
        delete_index = next(
            index
            for index, (kind, ref) in enumerate(sync_env["order"])
            if kind == "delete" and ref == "richmenu-old-base"
        )
        assert kinds.index("default-clear") < delete_index
        unlink_indexes = [
            index for index, (kind, _ref) in enumerate(sync_env["order"])
            if kind == "unlink"
        ]
        assert unlink_indexes
        assert max(unlink_indexes) < delete_index


class TestOversizedVariantIsSkippedNotFatal:
    def test_sync_does_not_raise(self, sync_env):
        # Without the guard this crashes mid-loop with an uncaught ValueError
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
        # was created is to check what *did* get created: the one real
        # variant with buttons (base+housekeeping), never a >6-button
        # payload.
        staff_oa_sync.sync(apply=True)
        assert len(sync_env["created"]) == 1
        for payload in sync_env["created"]:
            assert len(payload["areas"]) <= 6
        created_names = {payload["name"] for payload in sync_env["created"]}
        assert not any(SYNTHETIC_GRANT in name for name in created_names)
        # An image is uploaded for each created menu and nothing else.
        assert len(sync_env["uploaded"]) == len(sync_env["created"])


class TestOtherVariantsStillSyncNormally:
    def test_the_housekeeping_variant_is_created(self, sync_env):
        staff_oa_sync.sync(apply=True)
        created_names = {payload["name"] for payload in sync_env["created"]}
        assert staff_oa_menu.rich_menu_name(REAL_GRANTS) in created_names

    def test_housekeeping_menu_carries_the_real_buttons(self, sync_env):
        # The surviving variant is a real one, so its payload is worth
        # checking: every real button on the two-row canvas (6 since
        # รายงานแม่บ้าน, 2026-09-02 — the full 3+3 grid).
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

    def test_housekeeping_employees_are_linked_to_the_housekeeping_menu(self, sync_env):
        staff_oa_sync.sync(apply=True)
        housekeeping_name = staff_oa_menu.rich_menu_name(REAL_GRANTS)
        assert _linked_ids_for(sync_env, HOUSEKEEPING_LINE_USER_IDS) == [
            _created_ids(sync_env)[housekeeping_name]
        ]

    def test_housekeeping_employees_are_never_unlinked(self, sync_env):
        # The empty-base unlink must be scoped to the variants that have no
        # menu — a maid losing her menu would be the worst possible
        # regression here.
        staff_oa_sync.sync(apply=True)
        assert not set(HOUSEKEEPING_LINE_USER_IDS) & _unlinked_users(sync_env)


class TestOversizedEmployeeWithNoBaseMenuToFallBackOn:
    def test_oversized_variant_employee_is_unlinked_instead_of_keyerroring(
        self, sync_env
    ):
        # The fallback used to be bulk_link_rich_menu(users,
        # menu_ids["base"]). With no base menu that KeyErrors, so the
        # fallback is now an unlink: no menu is the honest state, and it
        # still beats a link to a menu that is about to be deleted.
        staff_oa_sync.sync(apply=True)

        assert set(OVERSIZED_LINE_USER_IDS) <= _unlinked_users(sync_env)
        assert _linked_ids_for(sync_env, OVERSIZED_LINE_USER_IDS) == []

    def test_oversized_employee_is_not_linked_to_another_employees_menu(self, sync_env):
        # Landing on the housekeeping menu would hand out buttons this
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
        assert "fallback" in out
        for line_user_id in OVERSIZED_LINE_USER_IDS:
            assert line_user_id in out


class TestStaleMenuDeletion:
    def test_a_still_used_menu_is_not_deleted(self, sync_env, monkeypatch):
        # Simulate a channel that already has the housekeeping menu deployed
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
        # Nothing was re-created either: matching signatures are reused.
        assert sync_env["created"] == []

    def test_the_old_base_menu_is_reclaimed(self, sync_env, monkeypatch):
        # The base menu left over from before the clock-in button was
        # removed. Nothing wants it any more — base is not a planned variant
        # — so the sweep must collect it rather than leave a menu on the
        # channel that no employee and no default points at.
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
        # Unlinking happens before deletion, so by the time this runs, no
        # employee is linked to it any more — reclaiming it as stale is safe,
        # not a "still in use" deletion.
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
        # Zero here means "clean run", not "everything got skipped": the one
        # variant with buttons deployed and no warning was printed.
        assert len(sync_env["created"]) == 1
        assert "SKIP" not in out
        assert "WARNING" not in out

    def test_an_all_maid_channel_needs_no_unlinks_at_all(self, sync_env, monkeypatch):
        # Every employee holds housekeeping: the empty-base branch is still
        # taken (no base menu, no default) but there is nobody to unlink, so
        # bulk_unlink_rich_menu is never called with an empty list either.
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "employee_menu_assignments",
            lambda db: {HOUSEKEEPING_KEY: list(HOUSEKEEPING_LINE_USER_IDS)},
        )
        assert staff_oa_sync.sync(apply=True) == 0
        assert sync_env["unlinked"] == []
        assert sync_env["default_set"] == []


class TestNonEmptyBaseBehavesExactlyAsBefore:
    """With a base button present, every step must behave as it did before
    the empty-base branch existed. This is the regression guard on the
    normal path — the real table can no longer produce it, so it is driven
    by the synthetic base button in ``sync_env_with_base``."""

    def test_the_base_menu_is_created_and_set_as_the_channel_default(
        self, sync_env_with_base
    ):
        staff_oa_sync.sync(apply=True)
        base_name = staff_oa_menu.rich_menu_name(set())
        created_names = {payload["name"] for payload in sync_env_with_base["created"]}

        assert base_name in created_names
        assert staff_oa_menu.rich_menu_name(REAL_GRANTS) in created_names
        assert len(sync_env_with_base["created"]) == 2
        assert sync_env_with_base["default_set"] == [
            _created_ids(sync_env_with_base)[base_name]
        ]
        assert sync_env_with_base["default_cleared"] == []

    def test_base_only_employees_are_linked_to_the_base_menu(self, sync_env_with_base):
        staff_oa_sync.sync(apply=True)
        base_name = staff_oa_menu.rich_menu_name(set())

        assert _linked_ids_for(sync_env_with_base, BASE_LINE_USER_IDS) == [
            _created_ids(sync_env_with_base)[base_name]
        ]

    def test_the_oversized_variant_employee_falls_back_to_the_base_menu(
        self, sync_env_with_base
    ):
        # The original fallback, unchanged: base is a strict subset of every
        # other variant's buttons, so it can never hand out more than the
        # employee is entitled to.
        staff_oa_sync.sync(apply=True)
        base_name = staff_oa_menu.rich_menu_name(set())

        assert _linked_ids_for(sync_env_with_base, OVERSIZED_LINE_USER_IDS) == [
            _created_ids(sync_env_with_base)[base_name]
        ]

    def test_nothing_is_ever_unlinked_and_no_default_is_cleared(
        self, sync_env_with_base, monkeypatch
    ):
        # Even with a channel default already set to something else — the
        # case that would tempt a clear — the non-empty path only ever
        # re-points the default.
        monkeypatch.setattr(
            staff_oa_sync.staff_oa_service,
            "get_default_rich_menu_id",
            lambda: "richmenu-some-old-default",
        )
        staff_oa_sync.sync(apply=True)

        assert sync_env_with_base["unlinked"] == []
        assert sync_env_with_base["default_cleared"] == []
        assert len(sync_env_with_base["default_set"]) == 1

    def test_output_never_claims_base_is_empty(self, sync_env_with_base, capsys):
        staff_oa_sync.sync(apply=True)
        out = capsys.readouterr().out

        assert "empty by design" not in out
        assert "fallback: base" in out  # the over-cap employees, as before

    def test_dry_run_still_makes_no_api_calls(self, sync_env_with_base):
        assert staff_oa_sync.sync(apply=False) == 0
        assert sync_env_with_base["order"] == []

    def test_exit_code_is_zero(self, sync_env_with_base):
        assert staff_oa_sync.sync(apply=True) == 0
