"""Unit tests for automatic Employee Hub Role Menu provisioning (2026-08-14).

Covers app/services/staff_oa_provision.py plus the three places that fire
it (the admin grants endpoint, the 6-digit LINE link flow, onboarding
approval) and the hourly reconcile job in
app/services/background_scheduler.py.

WHAT THIS FEATURE IS FOR
------------------------
Before it, ticking "Housekeeping" in the Employee Management UI wrote a
grant row and nothing else — the maid's LINE menu appeared only after a
human ran ``scripts/staff_oa_sync.py --apply`` on the host. The owner's
requirement is that the grant alone is enough. The audience is 80+ year old
maids who will not report a missing menu, so the tests below are weighted
toward the SILENT failure modes: a menu that is never created, a revocation
that never reaches LINE, and — above all — a LINE outage that rolls back or
500s the admin's save.

NO NETWORK. Every LINE Messaging API call and the PIL render are
monkeypatched; a call this file does not stub would raise rather than reach
the internet.
"""
import asyncio

import pytest

from app.models.models import Employee, EmployeeAppGrant
from app.services import background_scheduler as scheduler_module
from app.services import staff_oa_menu, staff_oa_provision, staff_oa_service
from app.services.admin_auth_service import admin_auth_service

TOKEN = "test-channel-access-token"
SECRET = "test-channel-secret"

# The grant these tests provision against, and one that deliberately does not
# move the menu (see tests/unit/test_staff_oa_service.py). `housekeeping` was
# the ONLY menu-relevant grant until `reception` joined it (2026-09-01); it is
# still the one this file drives, so the constant keeps its meaning.
MENU_GRANT = "housekeeping"
MENU_IRRELEVANT_GRANT = "payroll"

HOUSEKEEPING_KEY = "base+housekeeping"

# A synthetic grant carrying enough extra buttons to push a variant one past
# the Hub's MAX_BUTTONS layout cap. No REAL grant combination can overflow
# today — the largest real variant (base+housekeeping+reception) sits at 7,
# one under the cap of 8 — so the over-cap guard has to be tested against a
# table that grew — exactly the fixture strategy tests/unit/test_staff_oa_sync
# .py uses for the same guard.
SYNTHETIC_GRANT = "extra"
# Derived from what MENU_GRANT ALONE reveals (base's แจ้งลา tile included),
# which is what the over-cap tests below actually grant — not from
# len(MENU_BUTTONS). Keying off MAX_BUTTONS + 1 rather than a hardcoded target
# is what keeps this fixture overflowing exactly one past whatever the layout
# cap is, however the button table changes shape.
_HOUSEKEEPING_BUTTON_COUNT = len(staff_oa_menu.buttons_for({MENU_GRANT}))  # 7 today
_SYNTHETIC_BUTTON_COUNT = max(
    1, (staff_oa_menu.MAX_BUTTONS + 1) - _HOUSEKEEPING_BUTTON_COUNT
)  # 2 today
SYNTHETIC_BUTTONS = tuple(
    staff_oa_menu.MenuButton(
        grant_app_id=SYNTHETIC_GRANT,
        label=f"ทดสอบ {index + 1}",
        # .invalid is reserved by RFC 2606 — never fetched, and unroutable
        # so that staying stubbed is not merely a convention.
        url=f"https://synthetic-{index + 1}.invalid/",
        glyph="clock",
    )
    for index in range(_SYNTHETIC_BUTTON_COUNT)
)


def _strip_base_button(buttons):
    """Every button except the ungated (grant_app_id=None) one(s)."""
    return tuple(button for button in buttons if button.grant_app_id is not None)


# A second synthetic grant, sized to still overflow the layout cap when the
# ungated base button is ALSO stripped out (base is one button lighter once
# removed, so this needs one more synthetic button than SYNTHETIC_BUTTONS to
# land past the cap again). Exists only for the defensive "base has no
# buttons" branch — unreachable with today's real MENU_BUTTONS (แจ้งลา is
# always there) but still code that has to work if a future table ever
# empties base again.
SYNTHETIC_GRANT_NO_BASE = "extra-no-base"
_HOUSEKEEPING_BUTTON_COUNT_NO_BASE = len(
    _strip_base_button(staff_oa_menu.buttons_for({MENU_GRANT}))
)  # 6 today
_SYNTHETIC_BUTTON_COUNT_NO_BASE = max(
    1, (staff_oa_menu.MAX_BUTTONS + 1) - _HOUSEKEEPING_BUTTON_COUNT_NO_BASE
)  # 3 today
SYNTHETIC_BUTTONS_NO_BASE = tuple(
    staff_oa_menu.MenuButton(
        grant_app_id=SYNTHETIC_GRANT_NO_BASE,
        label=f"ทดสอบข {index + 1}",
        url=f"https://synthetic-nobase-{index + 1}.invalid/",
        glyph="clock",
    )
    for index in range(_SYNTHETIC_BUTTON_COUNT_NO_BASE)
)


def _admin_cookies():
    return {"admin_session_token": admin_auth_service.create_session()}


def _make_employee(test_db, badge, **overrides):
    defaults = dict(
        badge_number=badge, display_name=f"emp-{badge}",
        is_active=True, is_hidden=False,
    )
    defaults.update(overrides)
    employee = Employee(**defaults)
    test_db.add(employee)
    test_db.commit()
    return employee


def _grant(test_db, badge, *app_ids):
    for app_id in app_ids:
        test_db.add(EmployeeAppGrant(employee_badge_number=badge, app_id=app_id))
    test_db.commit()


@pytest.fixture
def staff_oa_enabled(monkeypatch):
    monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", SECRET)


@pytest.fixture
def staff_oa_dark(monkeypatch):
    monkeypatch.delenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("STAFF_OA_CHANNEL_SECRET", raising=False)


@pytest.fixture
def line_api(monkeypatch):
    """Record every LINE call the provisioner can make; make none of them.

    ``deployed`` stands in for GET /v2/bot/richmenu/list and is read at call
    time, so a test can seed it with an already-deployed variant (the reuse
    case) or leave it empty (the create case). ``fail`` lets a test make one
    named operation raise the way a real LINE outage would.

    Note which calls are stubbed: ``delete_rich_menu``,
    ``set_default_rich_menu`` and ``clear_default_rich_menu`` are recorded
    even though this path is supposed to never make them — that is precisely
    so the "additive only" tests can assert an empty list instead of trusting
    that a missing stub would have blown up.
    """
    calls = {
        "listed": 0,
        "created": [],        # rich_menu_payload dicts
        "uploaded": [],       # (rich_menu_id, png_bytes)
        "linked": [],         # (line_user_id, rich_menu_id)
        "unlinked": [],       # line_user_id
        "deleted": [],        # rich_menu_id
        "default_set": [],
        "default_cleared": [],
        "rendered": [],       # button tuples handed to the PNG renderer
        "deployed": [],       # what the channel already carries
        "fail": {},           # operation name -> exception to raise
    }

    def _maybe_fail(operation):
        error = calls["fail"].get(operation)
        if error is not None:
            raise error

    def _get_rich_menu_list():
        _maybe_fail("get_rich_menu_list")
        calls["listed"] += 1
        return list(calls["deployed"])

    def _create_rich_menu(payload):
        _maybe_fail("create_rich_menu")
        calls["created"].append(payload)
        return f"richmenu-{len(calls['created'])}"

    def _upload_rich_menu_image(rich_menu_id, png_bytes):
        _maybe_fail("upload_rich_menu_image")
        calls["uploaded"].append((rich_menu_id, png_bytes))

    def _link_rich_menu_to_user(line_user_id, rich_menu_id):
        _maybe_fail("link_rich_menu_to_user")
        calls["linked"].append((line_user_id, rich_menu_id))

    def _unlink_rich_menu_from_user(line_user_id):
        _maybe_fail("unlink_rich_menu_from_user")
        calls["unlinked"].append(line_user_id)

    def _delete_rich_menu(rich_menu_id):
        _maybe_fail("delete_rich_menu")
        calls["deleted"].append(rich_menu_id)

    def _render_menu_image(buttons):
        calls["rendered"].append(tuple(buttons))
        return b"fake-png"

    monkeypatch.setattr(staff_oa_service, "get_rich_menu_list", _get_rich_menu_list)
    monkeypatch.setattr(staff_oa_service, "create_rich_menu", _create_rich_menu)
    monkeypatch.setattr(
        staff_oa_service, "upload_rich_menu_image", _upload_rich_menu_image
    )
    monkeypatch.setattr(
        staff_oa_service, "link_rich_menu_to_user", _link_rich_menu_to_user
    )
    monkeypatch.setattr(
        staff_oa_service, "unlink_rich_menu_from_user", _unlink_rich_menu_from_user
    )
    monkeypatch.setattr(staff_oa_service, "delete_rich_menu", _delete_rich_menu)
    monkeypatch.setattr(
        staff_oa_service, "set_default_rich_menu",
        lambda rich_menu_id: calls["default_set"].append(rich_menu_id),
    )
    monkeypatch.setattr(
        staff_oa_service, "clear_default_rich_menu",
        lambda: calls["default_cleared"].append(True),
    )
    # Real PNG rendering is PIL + a Thai font lookup: correct but slow, and
    # tested on its own in tests/unit/test_staff_oa_images.py.
    monkeypatch.setattr(
        staff_oa_provision.staff_oa_images, "render_menu_image", _render_menu_image
    )
    return calls


@pytest.fixture
def oversized_menu_table(monkeypatch):
    """Grow MENU_BUTTONS so ``base+extra+housekeeping`` is over MAX_BUTTONS.

    base keeps its real แจ้งลา tile — this fixture is for the LIVE
    disposition (base present -> the over-cap employee falls back to it).

    Every staff_oa_menu function reads these module globals at call time, so
    patching them is enough for buttons_for / menu_key / menu_size alike.
    """
    monkeypatch.setattr(
        staff_oa_menu, "MENU_BUTTONS", staff_oa_menu.MENU_BUTTONS + SYNTHETIC_BUTTONS
    )
    monkeypatch.setattr(
        staff_oa_menu,
        "MENU_GRANT_APP_IDS",
        staff_oa_menu.MENU_GRANT_APP_IDS | {SYNTHETIC_GRANT},
    )


@pytest.fixture
def empty_base_menu_table(monkeypatch):
    """Strip the ungated base button so ``base`` is empty again.

    Defensive-only: today's real MENU_BUTTONS always has แจ้งลา (2026-09-18).
    Proves the "grantless employee -> unlink" branch still works if a future
    table ever empties base again.
    """
    monkeypatch.setattr(
        staff_oa_menu, "MENU_BUTTONS", _strip_base_button(staff_oa_menu.MENU_BUTTONS)
    )


@pytest.fixture
def oversized_with_empty_base(monkeypatch):
    """Over-cap AND base itself has no buttons — the disposition must be
    UNLINK, not link, because there is nothing valid to fall back to.
    """
    stripped = _strip_base_button(staff_oa_menu.MENU_BUTTONS)
    new_buttons = stripped + SYNTHETIC_BUTTONS_NO_BASE
    monkeypatch.setattr(staff_oa_menu, "MENU_BUTTONS", new_buttons)
    monkeypatch.setattr(
        staff_oa_menu,
        "MENU_GRANT_APP_IDS",
        frozenset(
            grant
            for button in new_buttons
            for grant in button.grant_app_ids | button.hidden_by_grant_app_ids
        ),
    )


def _created_id_for(calls, name):
    for index, payload in enumerate(calls["created"]):
        if payload["name"] == name:
            return f"richmenu-{index + 1}"
    raise AssertionError(f"no created menu named {name!r}; created={calls['created']}")


class TestFixturePremise:
    """These fixtures encode assumptions about the menu table. Prove them,
    so the tests below cannot rot into asserting nothing."""

    def test_housekeeping_is_the_grant_these_tests_provision_against(self):
        # Was test_housekeeping_is_the_only_menu_relevant_grant. It is no
        # longer the only one (`reception` joined MENU_GRANT_APP_IDS on
        # 2026-09-01), but it is still the grant this file drives, and the key
        # it mints ALONE must stay base+housekeeping — every expectation below
        # is written against that variant.
        assert staff_oa_menu.menu_key({MENU_GRANT}) == HOUSEKEEPING_KEY
        assert MENU_GRANT in staff_oa_menu.MENU_GRANT_APP_IDS
        assert MENU_IRRELEVANT_GRANT not in staff_oa_menu.MENU_GRANT_APP_IDS

    def test_base_carries_the_leave_tile_so_a_grantless_employee_gets_a_menu(self):
        # แจ้งลา (2026-09-18) is the one ungated tile every linked employee
        # sees. Every "grantless employee -> linked to base" test below rests
        # on this; if it ever fails, those tests need to flip back to
        # expecting an unlink.
        buttons = staff_oa_menu.buttons_for(frozenset())
        assert len(buttons) == 1
        assert buttons[0].label == "แจ้งลา"

    def test_the_synthetic_table_really_does_overflow_the_layout_cap(
        self, oversized_menu_table
    ):
        buttons = staff_oa_menu.buttons_for({MENU_GRANT, SYNTHETIC_GRANT})
        assert len(buttons) > staff_oa_menu.MAX_BUTTONS
        with pytest.raises(ValueError):
            staff_oa_menu.menu_size(len(buttons))

    def test_the_no_base_synthetic_table_still_overflows_with_base_empty(
        self, oversized_with_empty_base
    ):
        assert staff_oa_menu.buttons_for(frozenset()) == ()
        buttons = staff_oa_menu.buttons_for({MENU_GRANT, SYNTHETIC_GRANT_NO_BASE})
        assert len(buttons) > staff_oa_menu.MAX_BUTTONS
        with pytest.raises(ValueError):
            staff_oa_menu.menu_size(len(buttons))

    def test_empty_base_fixture_alone_truly_empties_base(self, empty_base_menu_table):
        assert staff_oa_menu.buttons_for(frozenset()) == ()


class TestProvisionCreatesAndLinks:
    def test_grant_added_creates_the_missing_menu_and_links_the_user(
        self, staff_oa_enabled, line_api, test_db
    ):
        # The headline case: an admin ticks "Housekeeping" for a maid whose
        # grant combination has never existed on this channel before. This is
        # exactly what link_role_menu_for_line_user() could NOT do — it looks
        # the variant up and gives up with "run scripts/staff_oa_sync.py
        # --apply" when it is missing.
        _make_employee(test_db, "5001", line_user_id="U-maid")
        _grant(test_db, "5001", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5001")

        assert len(line_api["created"]) == 1
        payload = line_api["created"][0]
        assert payload["name"] == staff_oa_menu.rich_menu_name({MENU_GRANT})
        # Message-action buttons (แจ้งลา) carry no "uri" key — .get(..., "")
        # lines them up with their MenuButton.url, which is "" for those.
        assert [area["action"].get("uri", "") for area in payload["areas"]] == [
            button.url for button in staff_oa_menu.buttons_for({MENU_GRANT})
        ]
        # Image uploaded to the menu that was just created — a rich menu with
        # no image cannot be linked at all.
        assert line_api["uploaded"] == [("richmenu-1", b"fake-png")]
        assert line_api["linked"] == [("U-maid", "richmenu-1")]
        assert line_api["unlinked"] == []

    def test_menu_irrelevant_grants_do_not_change_the_variant(
        self, staff_oa_enabled, line_api, test_db
    ):
        # payroll is a real grant with no Hub tile. The maid's menu must be
        # the plain housekeeping variant, not a `base+housekeeping+payroll`
        # one the button table could not render.
        _make_employee(test_db, "5002", line_user_id="U-maid-2")
        _grant(test_db, "5002", MENU_GRANT, MENU_IRRELEVANT_GRANT)

        staff_oa_provision.provision_for_badge("5002")

        assert line_api["created"][0]["name"] == staff_oa_menu.rich_menu_name(
            {MENU_GRANT}
        )

    def test_existing_menu_is_reused_not_recreated(
        self, staff_oa_enabled, line_api, test_db
    ):
        # The signature in the rich-menu name is the idempotency key. A
        # second maid granted the same combination must land on the SAME
        # menu — recreating it per employee would burn through LINE's
        # per-channel rich-menu limit and re-upload the same PNG every time.
        line_api["deployed"] = [
            {
                "richMenuId": "rm-already-there",
                "name": staff_oa_menu.rich_menu_name({MENU_GRANT}),
            }
        ]
        _make_employee(test_db, "5003", line_user_id="U-maid-3")
        _grant(test_db, "5003", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5003")

        assert line_api["created"] == []
        assert line_api["uploaded"] == []
        assert line_api["rendered"] == []  # not even rendered
        assert line_api["linked"] == [("U-maid-3", "rm-already-there")]

    def test_a_stale_menu_for_the_same_variant_is_not_reused(
        self, staff_oa_enabled, line_api, test_db
    ):
        # Same variant KEY, different signature — i.e. the button table or
        # the image style changed since that menu was deployed. Matching on
        # the full name (key + signature) rather than the key is what makes a
        # look-and-feel change actually reach the maid's phone.
        line_api["deployed"] = [
            {"richMenuId": "rm-stale", "name": f"staffhub:{HOUSEKEEPING_KEY}:0000dead"}
        ]
        _make_employee(test_db, "5004", line_user_id="U-maid-4")
        _grant(test_db, "5004", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5004")

        assert len(line_api["created"]) == 1
        assert line_api["linked"] == [("U-maid-4", "richmenu-1")]
        # ...and the stale one is left alone: deleting a menu other
        # employees may still be linked to belongs to the full sync.
        assert line_api["deleted"] == []


class TestProvisionRevokesAndDeclines:
    def test_revoking_the_last_menu_grant_falls_back_to_the_base_menu(
        self, staff_oa_enabled, line_api, test_db
    ):
        # A demoted maid. Since แจ้งลา (2026-09-18) became an ungated base
        # tile, she keeps a menu — just the base one, not the maid one — the
        # same "beats a link to somebody else's stale menu" outcome
        # link_role_menu_for_line_user's over-cap fallback aims for.
        # Declining to relink would NOT be enough either way: her old
        # housekeeping link survives on LINE's side, leaving tiles that now
        # open a Cloudflare block page, unless it is explicitly repointed.
        base_name = staff_oa_menu.rich_menu_name(frozenset())
        _make_employee(test_db, "5005", line_user_id="U-demoted")
        _grant(test_db, "5005", MENU_IRRELEVANT_GRANT)

        staff_oa_provision.provision_for_badge("5005")

        assert line_api["unlinked"] == []
        assert len(line_api["created"]) == 1
        assert line_api["created"][0]["name"] == base_name
        assert line_api["linked"] == [("U-demoted", "richmenu-1")]

    def test_employee_with_no_grants_at_all_is_linked_to_base(
        self, staff_oa_enabled, line_api, test_db
    ):
        base_name = staff_oa_menu.rich_menu_name(frozenset())
        _make_employee(test_db, "5006", line_user_id="U-nobody")

        staff_oa_provision.provision_for_badge("5006")

        assert line_api["unlinked"] == []
        assert line_api["created"][0]["name"] == base_name
        assert line_api["linked"] == [("U-nobody", "richmenu-1")]

    def test_grantless_employee_is_unlinked_when_base_is_defensively_empty(
        self, staff_oa_enabled, line_api, test_db, empty_base_menu_table
    ):
        # The pre-2026-09-18 behaviour, still correct if a future MENU_BUTTONS
        # table ever removes the ungated base tile again.
        _make_employee(test_db, "5011", line_user_id="U-nobody-2")

        staff_oa_provision.provision_for_badge("5011")

        assert line_api["unlinked"] == ["U-nobody-2"]
        assert line_api["linked"] == []
        assert line_api["created"] == []

    def test_unlinked_employee_is_a_no_op_with_zero_line_calls(
        self, staff_oa_enabled, line_api, test_db
    ):
        # Grant-then-link: the admin grants housekeeping days before the maid
        # scans her Q-badge. There is no LINE user to act on yet, and the
        # link sites re-fire provisioning when there is.
        _make_employee(test_db, "5007")
        _grant(test_db, "5007", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5007")

        assert line_api["listed"] == 0
        assert line_api["created"] == []
        assert line_api["linked"] == []
        assert line_api["unlinked"] == []

    def test_inactive_employee_is_unlinked_not_merely_skipped(
        self, staff_oa_enabled, line_api, test_db
    ):
        # A deactivated employee must LOSE her menu. Skipping her would leave a
        # departed maid holding live tiles forever: the event triggers never
        # fire for her again, and reconcile_all walks only ACTIVE employees, so
        # nothing would ever converge it. Covers a self-onboarded row awaiting
        # approval too — those are is_active=False with line_user_id set.
        _make_employee(test_db, "5008", line_user_id="U-inactive", is_active=False)
        _grant(test_db, "5008", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5008")

        assert line_api["unlinked"] == ["U-inactive"]
        # Revoking access must never mint or hand out a menu.
        assert line_api["created"] == []
        assert line_api["linked"] == []
        assert line_api["listed"] == 0  # no menu lookup needed to revoke

    def test_inactive_employee_without_line_is_a_no_op(
        self, staff_oa_enabled, line_api, test_db
    ):
        # Nothing to unlink, and no LINE call should be attempted at all.
        _make_employee(test_db, "5009", line_user_id=None, is_active=False)
        _grant(test_db, "5009", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5009")

        assert line_api["unlinked"] == []
        assert line_api["linked"] == []
        assert line_api["listed"] == 0

    def test_unknown_badge_is_a_no_op(self, staff_oa_enabled, line_api, test_db):
        staff_oa_provision.provision_for_badge("no-such-badge")

        assert line_api["listed"] == 0
        assert line_api["linked"] == []
        assert line_api["unlinked"] == []

    def test_feature_dark_makes_no_line_calls_at_all(
        self, staff_oa_dark, line_api, test_db
    ):
        # The dark check comes first, before the database is even opened:
        # this is the state on every dev machine and in CI, so it has to cost
        # nothing and above all must not warn.
        _make_employee(test_db, "5009", line_user_id="U-dark")
        _grant(test_db, "5009", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5009")

        assert line_api["listed"] == 0
        assert line_api["created"] == []
        assert line_api["linked"] == []
        assert line_api["unlinked"] == []


class TestProvisionNeverRaises:
    """The whole point of the module: it runs behind an admin's save button."""

    @pytest.mark.parametrize(
        "operation",
        ["get_rich_menu_list", "create_rich_menu", "link_rich_menu_to_user"],
    )
    def test_a_line_failure_anywhere_in_the_happy_path_is_swallowed(
        self, staff_oa_enabled, line_api, test_db, operation
    ):
        line_api["fail"][operation] = staff_oa_service.StaffOaApiError(
            operation, 500, "boom"
        )
        _make_employee(test_db, "5101", line_user_id="U-maid")
        _grant(test_db, "5101", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5101")  # must not raise

    def test_a_failed_unlink_is_swallowed_too(
        self, staff_oa_enabled, line_api, test_db
    ):
        line_api["fail"]["unlink_rich_menu_from_user"] = (
            staff_oa_service.StaffOaApiError("unlink", 500, "boom")
        )
        _make_employee(test_db, "5102", line_user_id="U-demoted")

        staff_oa_provision.provision_for_badge("5102")  # must not raise

    def test_a_render_failure_is_swallowed_and_creates_nothing(
        self, staff_oa_enabled, line_api, test_db, monkeypatch
    ):
        # Rendering happens BEFORE the menu is created precisely so a PIL
        # failure leaves nothing behind on the channel to clean up.
        def _boom(buttons):
            raise OSError("cannot open font")

        monkeypatch.setattr(
            staff_oa_provision.staff_oa_images, "render_menu_image", _boom
        )
        _make_employee(test_db, "5103", line_user_id="U-maid")
        _grant(test_db, "5103", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5103")

        assert line_api["created"] == []
        assert line_api["linked"] == []


class TestImageUploadFailureConverges:
    def test_the_half_created_menu_is_deleted_so_a_retry_can_recreate_it(
        self, staff_oa_enabled, line_api, test_db
    ):
        # A rich menu with no image is UNUSABLE — LINE refuses to link it.
        # Left behind, it would poison every future run: the name lookup
        # would find it, hand back its id, and the link would fail forever.
        line_api["fail"]["upload_rich_menu_image"] = (
            staff_oa_service.StaffOaApiError("upload", 500, "boom")
        )
        _make_employee(test_db, "5201", line_user_id="U-maid")
        _grant(test_db, "5201", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5201")

        assert line_api["created"] != []
        assert line_api["deleted"] == ["richmenu-1"]
        assert line_api["linked"] == []

    def test_the_next_run_recreates_the_menu_and_links(
        self, staff_oa_enabled, line_api, test_db
    ):
        # Convergence, asserted end to end rather than inferred from the
        # delete: the retry must produce a WORKING menu, not a second
        # imageless one.
        line_api["fail"]["upload_rich_menu_image"] = (
            staff_oa_service.StaffOaApiError("upload", 500, "boom")
        )
        _make_employee(test_db, "5202", line_user_id="U-maid")
        _grant(test_db, "5202", MENU_GRANT)
        staff_oa_provision.provision_for_badge("5202")

        line_api["fail"].pop("upload_rich_menu_image")
        staff_oa_provision.provision_for_badge("5202")

        assert len(line_api["created"]) == 2
        assert line_api["uploaded"] == [("richmenu-2", b"fake-png")]
        assert line_api["linked"] == [("U-maid", "richmenu-2")]

    def test_a_failed_cleanup_delete_does_not_raise_either(
        self, staff_oa_enabled, line_api, test_db
    ):
        # Both calls down. This is the one state this path can leave that
        # needs a human, and it is logged as such — but it still must not
        # escape into the admin's request.
        line_api["fail"]["upload_rich_menu_image"] = (
            staff_oa_service.StaffOaApiError("upload", 500, "boom")
        )
        line_api["fail"]["delete_rich_menu"] = staff_oa_service.StaffOaApiError(
            "delete", 500, "boom"
        )
        _make_employee(test_db, "5203", line_user_id="U-maid")
        _grant(test_db, "5203", MENU_GRANT)

        staff_oa_provision.provision_for_badge("5203")  # must not raise


class TestOverCapVariant:
    def test_over_cap_variant_warns_and_falls_back_to_base(
        self, staff_oa_enabled, line_api, test_db, oversized_menu_table, caplog
    ):
        # Over the Hub's MAX_BUTTONS layout cap. Uncaught, menu_size() raises
        # from inside rich_menu_name() and this employee's provisioning
        # explodes. base carries buttons now (แจ้งลา), and base's buttons are
        # a strict subset of every other variant's, so falling back to it can
        # never hand out more than this employee is entitled to.
        base_name = staff_oa_menu.rich_menu_name(frozenset())
        _make_employee(test_db, "5301", line_user_id="U-overgranted")
        _grant(test_db, "5301", MENU_GRANT, SYNTHETIC_GRANT)

        with caplog.at_level("WARNING"):
            staff_oa_provision.provision_for_badge("5301")

        assert line_api["unlinked"] == []
        created_names = [payload["name"] for payload in line_api["created"]]
        assert created_names == [base_name]
        base_id = _created_id_for(line_api, base_name)
        assert line_api["linked"] == [("U-overgranted", base_id)]
        # The warning has to name WHO and WHICH variant, or an operator
        # cannot act on it.
        assert "5301" in caplog.text
        assert SYNTHETIC_GRANT in caplog.text

    def test_over_cap_variant_with_empty_base_unlinks(
        self, staff_oa_enabled, line_api, test_db, oversized_with_empty_base, caplog
    ):
        # The defensive branch: base itself has no buttons (only reachable
        # today via the synthetic empty-base fixture), so there is nothing
        # valid to fall back to and the employee is unlinked instead.
        _make_employee(test_db, "5302", line_user_id="U-overgranted-2")
        _grant(test_db, "5302", MENU_GRANT, SYNTHETIC_GRANT_NO_BASE)

        with caplog.at_level("WARNING"):
            staff_oa_provision.provision_for_badge("5302")

        assert line_api["created"] == []
        assert line_api["linked"] == []
        assert line_api["unlinked"] == ["U-overgranted-2"]
        assert "5302" in caplog.text
        assert SYNTHETIC_GRANT_NO_BASE in caplog.text


class TestReconcileAll:
    def test_converges_an_unlinked_but_granted_employee(
        self, staff_oa_enabled, line_api, test_db
    ):
        # The safety net's reason for existing: a grant written straight into
        # the database (or an event-path run that LINE ate) leaves a maid
        # holding the grant with no menu. The sweep fixes it with no admin
        # action at all.
        _make_employee(test_db, "5401", line_user_id="U-maid")
        _grant(test_db, "5401", MENU_GRANT)

        staff_oa_provision.reconcile_all()

        assert len(line_api["created"]) == 1
        assert line_api["linked"] == [("U-maid", "richmenu-1")]

    def test_deletes_nothing_and_never_touches_the_channel_default(
        self, staff_oa_enabled, line_api, test_db
    ):
        # STRICTLY ADDITIVE. Menu deletion and the channel default are
        # cross-employee operations — a sweep that deleted "unused" menus
        # could yank one another employee is still linked to, and the default
        # is what every un-onboarded follower sees. Both stay in
        # scripts/staff_oa_sync.py, which reasons about the whole channel.
        line_api["deployed"] = [
            {"richMenuId": "rm-stale", "name": "staffhub:base:0000dead"},
            {"richMenuId": "rm-foreign", "name": "someone-elses-menu"},
        ]
        _make_employee(test_db, "5402", line_user_id="U-maid")
        _grant(test_db, "5402", MENU_GRANT)
        _make_employee(test_db, "5403", line_user_id="U-nobody")

        staff_oa_provision.reconcile_all()

        assert line_api["deleted"] == []
        assert line_api["default_set"] == []
        assert line_api["default_cleared"] == []

    def test_skips_inactive_and_unlinked_employees(
        self, staff_oa_enabled, line_api, test_db
    ):
        _make_employee(test_db, "5404")  # no LINE account
        _make_employee(test_db, "5405", line_user_id="U-gone", is_active=False)

        staff_oa_provision.reconcile_all()

        assert line_api["listed"] == 0
        assert line_api["linked"] == []
        assert line_api["unlinked"] == []

    def test_one_employees_failure_does_not_stop_the_next(
        self, staff_oa_enabled, line_api, test_db, monkeypatch
    ):
        # A batch is only worth more than a single call if a poison row
        # cannot wedge it. Fail the FIRST badge the sweep reaches, whichever
        # that is, and assert the other one still converges.
        _make_employee(test_db, "5406", line_user_id="U-maid-a")
        _grant(test_db, "5406", MENU_GRANT)
        _make_employee(test_db, "5407", line_user_id="U-maid-b")
        _grant(test_db, "5407", MENU_GRANT)

        real_provision = staff_oa_provision.provision_for_badge
        seen = []

        def _flaky(badge_number):
            seen.append(badge_number)
            if len(seen) == 1:
                raise RuntimeError("LINE exploded")
            return real_provision(badge_number)

        monkeypatch.setattr(staff_oa_provision, "provision_for_badge", _flaky)

        staff_oa_provision.reconcile_all()  # must not raise

        assert len(seen) == 2
        assert len(line_api["linked"]) == 1

    def test_dark_reconcile_touches_neither_line_nor_the_database(
        self, staff_oa_dark, line_api, test_db
    ):
        _make_employee(test_db, "5408", line_user_id="U-maid")
        _grant(test_db, "5408", MENU_GRANT)

        staff_oa_provision.reconcile_all()

        assert line_api["listed"] == 0
        assert line_api["linked"] == []


class TestReconcileSchedulerJob:
    """app.services.background_scheduler._reconcile_staff_oa_menus.

    Driven with asyncio.run() rather than an async test: this suite has no
    pytest-asyncio mode configured, and the job is a plain coroutine.
    """

    def test_job_runs_the_reconcile_off_the_event_loop(
        self, staff_oa_enabled, line_api, test_db
    ):
        _make_employee(test_db, "5501", line_user_id="U-maid")
        _grant(test_db, "5501", MENU_GRANT)

        service = scheduler_module.BackgroundSchedulerService()
        asyncio.run(service._reconcile_staff_oa_menus())

        assert line_api["linked"] == [("U-maid", "richmenu-1")]

    def test_job_no_ops_entirely_when_the_feature_is_dark(
        self, staff_oa_dark, line_api, test_db, monkeypatch
    ):
        # Guarded in the job itself, not only inside reconcile_all: the dark
        # state is the norm until the staff OA secrets are delivered, and an
        # hourly job that opened a database session to learn that would be
        # pure waste.
        called = []
        monkeypatch.setattr(
            staff_oa_provision, "reconcile_all", lambda: called.append(True)
        )
        _make_employee(test_db, "5502", line_user_id="U-maid")

        service = scheduler_module.BackgroundSchedulerService()
        asyncio.run(service._reconcile_staff_oa_menus())

        assert called == []

    def test_job_never_throws_into_the_scheduler(
        self, staff_oa_enabled, line_api, test_db, monkeypatch
    ):
        # An APScheduler job error is logged at ERROR by _on_error, which in
        # this service reads as a DEVICE fault. A LINE outage must not look
        # like one.
        def _boom():
            raise RuntimeError("LINE exploded")

        monkeypatch.setattr(staff_oa_provision, "reconcile_all", _boom)

        service = scheduler_module.BackgroundSchedulerService()
        asyncio.run(service._reconcile_staff_oa_menus())  # must not raise

    def test_the_job_is_registered_hourly_and_not_at_startup(self):
        service = scheduler_module.BackgroundSchedulerService()
        service._register_jobs()

        job = service.scheduler.get_job("reconcile_staff_oa_menus")
        assert job is not None
        assert job.trigger.interval.total_seconds() == 3600


class TestGrantsEndpointSchedulesProvisioning:
    def test_put_grants_schedules_the_background_task(
        self, test_client, test_db, monkeypatch
    ):
        # Assert SCHEDULING, not a live call: the whole point of using
        # BackgroundTasks is that the LINE work happens after the response is
        # sent, and (because provision_for_badge is sync) in a threadpool
        # rather than on the event loop. Blocking LINE calls made on the loop
        # are what stalled /oidc/token in this repo earlier today.
        from fastapi import BackgroundTasks

        scheduled = []
        monkeypatch.setattr(
            BackgroundTasks, "add_task",
            lambda self, func, *args, **kwargs: scheduled.append((func, args)),
        )
        _make_employee(test_db, "5601", line_user_id="U-maid")

        response = test_client.put(
            "/api/private/admin/employees/5601/grants",
            json={"app_ids": [MENU_GRANT]},
            cookies=_admin_cookies(),
        )

        assert response.status_code == 200
        assert scheduled == [(staff_oa_provision.provision_for_badge, ("5601",))]

    def test_line_link_flow_schedules_provisioning(
        self, test_client, test_db, monkeypatch
    ):
        # Grant-then-link: the grant fired while line_user_id was still None
        # and returned early. Without THIS trigger that maid never gets a
        # menu, because nothing touches her grants again.
        from datetime import datetime, timezone

        from fastapi import BackgroundTasks

        from app.services.line_auth_service import line_auth_service

        scheduled = []
        monkeypatch.setattr(
            BackgroundTasks, "add_task",
            lambda self, func, *args, **kwargs: scheduled.append((func, args)),
        )
        _make_employee(
            test_db, "5602",
            line_linking_code="123456",
            line_linking_code_generated_at=datetime.now(timezone.utc),
        )
        token = line_auth_service.create_jwt_token(
            line_user_id="U-fresh", display_name="maid", picture_url=None
        )

        response = test_client.post(
            "/api/public/auth/line/link-account",
            json={"linking_code": "123456", "jwt_token": token},
        )

        assert response.status_code == 200
        assert scheduled == [(staff_oa_provision.provision_for_badge, ("5602",))]

    def test_onboarding_approval_schedules_provisioning(
        self, test_client, test_db, monkeypatch
    ):
        # A self-onboarded row already carries line_user_id but is inactive
        # until approval, so every earlier attempt returned early. Approval is
        # the moment the LINE link becomes effective.
        from fastapi import BackgroundTasks

        scheduled = []
        monkeypatch.setattr(
            BackgroundTasks, "add_task",
            lambda self, func, *args, **kwargs: scheduled.append((func, args)),
        )
        _make_employee(
            test_db, "Q5603",
            line_user_id="U-pending", is_active=False, pending_approval=True,
            join_source="self_onboard",
        )

        response = test_client.post(
            "/api/private/admin/onboarding/approve",
            json={"badge_number": "Q5603"},
            cookies=_admin_cookies(),
        )

        assert response.status_code == 200
        assert scheduled == [(staff_oa_provision.provision_for_badge, ("Q5603",))]


class TestGrantWriteSurvivesLineOutage:
    """THE test. Everything else is secondary to this one.

    The background task really executes here (TestClient runs background
    tasks before returning), with LINE failing — no add_task stub, no
    provisioning stub. If provisioning ever stops swallowing its exceptions,
    an admin ticking a checkbox during a LINE outage gets a 500 and, worse,
    is left unsure whether the grant took.
    """

    def test_line_outage_still_returns_200_and_commits_the_grant(
        self, staff_oa_enabled, line_api, test_client, test_db
    ):
        line_api["fail"]["get_rich_menu_list"] = staff_oa_service.StaffOaApiError(
            "list rich menus", 500, "LINE is down"
        )
        _make_employee(test_db, "5701", line_user_id="U-maid")

        response = test_client.put(
            "/api/private/admin/employees/5701/grants",
            json={"app_ids": [MENU_GRANT, MENU_IRRELEVANT_GRANT]},
            cookies=_admin_cookies(),
        )

        assert response.status_code == 200
        assert response.json()["granted_app_ids"] == sorted(
            [MENU_GRANT, MENU_IRRELEVANT_GRANT]
        )
        # The grant rows are really there — a rolled-back commit would show
        # up here, not in the response body, which is built from the same
        # session that did the write.
        test_db.expire_all()
        rows = (
            test_db.query(EmployeeAppGrant)
            .filter(EmployeeAppGrant.employee_badge_number == "5701")
            .all()
        )
        assert sorted(row.app_id for row in rows) == sorted(
            [MENU_GRANT, MENU_IRRELEVANT_GRANT]
        )
        # And provisioning genuinely ran and genuinely failed — otherwise
        # this test would pass for the wrong reason (e.g. the task never
        # being scheduled at all).
        assert line_api["linked"] == []

    def test_line_working_provisions_through_the_real_endpoint(
        self, staff_oa_enabled, line_api, test_client, test_db
    ):
        # The mirror image, end to end: admin ticks the box, maid gets the
        # menu, nobody runs a command. This is the owner's requirement,
        # asserted through the HTTP endpoint rather than the service.
        _make_employee(test_db, "5702", line_user_id="U-maid")

        response = test_client.put(
            "/api/private/admin/employees/5702/grants",
            json={"app_ids": [MENU_GRANT]},
            cookies=_admin_cookies(),
        )

        assert response.status_code == 200
        assert len(line_api["created"]) == 1
        assert line_api["linked"] == [("U-maid", "richmenu-1")]
