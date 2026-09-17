"""Unit tests for app.services.staff_oa_service.

Covers the fail-closed credential gate, LINE webhook signature
verification, the grant → menu-variant grouping the sync script uses, the
bulk link/unlink and channel-default calls, and the one-user relink helper
(LINE API mocked throughout — no HTTP).

MENU-RELEVANT VS MENU-IRRELEVANT GRANTS
---------------------------------------
Since the Employee Hub was re-scoped to a maid tool (2026-08-14),
`housekeeping` is the ONLY grant that changes the menu — it is all of
``staff_oa_menu.MENU_GRANT_APP_IDS`` — so the only variants are `base` and
`base+housekeeping`.

`payroll` and `ota` are still real grants: the apps exist, employees still
hold them, and they still open from a real browser. Only their Hub tiles
were removed. That means they must NOT change anyone's variant, which makes
them the sharpest fixture available for "an employee holds grants that do
not change their menu" — a case these tests previously could not express,
because every grant used to add a button. ``TestGrantFixturePremise`` pins
both roles so the fixtures cannot rot if a tile comes back.

AND `base` IS REAL AGAIN
------------------------
The 2026-09-18 แจ้งลา (file leave) tile made `base` an ungated, always-on
menu again: every linked employee sees it regardless of grants, so
``buttons_for(frozenset())`` is a single-button tuple, never ``()``.
``link_role_menu_for_line_user`` now links every employee — including one
with no grants at all, or only menu-irrelevant grants — to that base menu;
it declines (returns None) only when the feature is dark, the LINE user is
unknown, or the resolved variant's menu has not been deployed yet (run the
sync script). ``clear_default_rich_menu`` and ``bulk_unlink_rich_menu``
still exist for the (no-buttons) degenerate case, which is unreachable with
the current MENU_BUTTONS table but is kept as a fail-closed guard.
"""
import base64
import hashlib
import hmac
import json

import pytest

from app.models.models import Employee, EmployeeAppGrant
from app.services import staff_oa_menu
from app.services import staff_oa_service as service

TOKEN = "test-channel-access-token"
SECRET = "test-channel-secret"

# The one variant-changing grant, and two real grants that no longer are.
MENU_GRANT = "housekeeping"
MENU_IRRELEVANT_GRANTS = ("payroll", "ota")

BASE_KEY = "base"
HOUSEKEEPING_KEY = "base+housekeeping"


@pytest.fixture
def staff_oa_enabled(monkeypatch):
    monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", SECRET)


@pytest.fixture
def staff_oa_dark(monkeypatch):
    monkeypatch.delenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("STAFF_OA_CHANNEL_SECRET", raising=False)


def _sign(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


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


class TestGrantFixturePremise:
    """The grants below are chosen for their MENU ROLE, not their name —
    prove each still has the role it was picked for."""

    def test_housekeeping_is_the_menu_relevant_grant(self):
        assert MENU_GRANT in staff_oa_menu.MENU_GRANT_APP_IDS
        assert staff_oa_menu.menu_key({MENU_GRANT}) == HOUSEKEEPING_KEY

    def test_payroll_and_ota_are_menu_irrelevant(self):
        # If this fails, a removed tile came back and these grants now mint
        # variants of their own: re-point the "does not change the variant"
        # tests at a grant that is still menu-irrelevant — do not weaken them.
        for app_id in MENU_IRRELEVANT_GRANTS:
            assert app_id not in staff_oa_menu.MENU_GRANT_APP_IDS
            assert staff_oa_menu.menu_key({app_id}) == BASE_KEY

    def test_the_base_variant_has_exactly_the_leave_button(self):
        # The premise behind every "links the base menu" assertion below
        # (แจ้งลา shipped 2026-09-18 as the one ungated tile). If base ever
        # goes back to zero buttons, those tests are testing the wrong thing
        # and must be re-pointed, not deleted.
        base_buttons = staff_oa_menu.buttons_for(frozenset())
        assert len(base_buttons) == 1
        assert base_buttons[0].label == "แจ้งลา"
        assert staff_oa_menu.buttons_for({MENU_GRANT}) != base_buttons


class TestEnablement:
    def test_dark_when_both_env_vars_unset(self, staff_oa_dark):
        assert service.is_enabled() is False

    def test_dark_when_only_token_set(self, monkeypatch, staff_oa_dark):
        monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", TOKEN)
        assert service.is_enabled() is False

    def test_dark_when_secret_is_blank(self, monkeypatch, staff_oa_enabled):
        monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", "   ")
        assert service.is_enabled() is False

    def test_enabled_when_both_set(self, staff_oa_enabled):
        assert service.is_enabled() is True


class TestWebhookSignature:
    def test_should_accept_valid_signature(self, staff_oa_enabled):
        body = b'{"events":[]}'
        assert service.verify_webhook_signature(body, _sign(body)) is True

    def test_should_reject_wrong_signature(self, staff_oa_enabled):
        body = b'{"events":[]}'
        assert service.verify_webhook_signature(body, _sign(b"other")) is False

    def test_should_reject_signature_from_wrong_secret(self, staff_oa_enabled):
        body = b'{"events":[]}'
        forged = _sign(body, secret="not-the-channel-secret")
        assert service.verify_webhook_signature(body, forged) is False

    def test_should_reject_missing_signature(self, staff_oa_enabled):
        assert service.verify_webhook_signature(b"{}", None) is False
        assert service.verify_webhook_signature(b"{}", "") is False

    def test_should_reject_everything_when_dark(self, staff_oa_dark):
        body = b'{"events":[]}'
        assert service.verify_webhook_signature(body, _sign(body)) is False


class TestEmployeeMenuAssignments:
    def test_groups_linked_employees_by_menu_variant(self, test_db):
        # Was written around `payroll`, which no longer produces a variant of
        # its own; the grouping behaviour is unchanged, so it is re-pointed at
        # the grant that does (`housekeeping`).
        _make_employee(test_db, "1001", line_user_id="U-base")
        _make_employee(test_db, "1002", line_user_id="U-maid")
        _grant(test_db, "1002", MENU_GRANT)
        _make_employee(test_db, "1003", line_user_id="U-maid-2")
        _grant(test_db, "1003", MENU_GRANT, "rooms")  # rooms is menu-irrelevant

        assignments = service.employee_menu_assignments(test_db)

        assert assignments[BASE_KEY] == ["U-base"]
        assert sorted(assignments[HOUSEKEEPING_KEY]) == ["U-maid", "U-maid-2"]

    def test_removed_tile_grants_do_not_mint_a_variant_of_their_own(self, test_db):
        # payroll/ota holders belong in the plain `base` group now. This
        # matters beyond tidiness: the sync script deploys one rich menu per
        # key returned here, and a `base+payroll` key would name a variant
        # the button table can no longer render.
        _make_employee(test_db, "3001", line_user_id="U-payroll")
        _grant(test_db, "3001", "payroll")
        _make_employee(test_db, "3002", line_user_id="U-ota")
        _grant(test_db, "3002", "ota")
        _make_employee(test_db, "3003", line_user_id="U-maid-payroll")
        _grant(test_db, "3003", MENU_GRANT, "payroll")

        assignments = service.employee_menu_assignments(test_db)

        assert sorted(assignments[BASE_KEY]) == ["U-ota", "U-payroll"]
        assert assignments[HOUSEKEEPING_KEY] == ["U-maid-payroll"]
        assert set(assignments) == {BASE_KEY, HOUSEKEEPING_KEY}

    def test_ignores_unlinked_and_inactive_employees(self, test_db):
        _make_employee(test_db, "2001")  # no LINE account linked
        _make_employee(test_db, "2002", line_user_id="U-gone", is_active=False)

        assert service.employee_menu_assignments(test_db) == {}


class TestDeployedMenuIdsByKey:
    def test_maps_variant_key_to_menu_id(self):
        menus = [
            {"richMenuId": "rm-1", "name": f"staffhub:{BASE_KEY}:abc123"},
            {"richMenuId": "rm-2", "name": f"staffhub:{HOUSEKEEPING_KEY}:def456"},
            {"richMenuId": "rm-3", "name": "unrelated-menu"},
        ]
        mapping = service.deployed_menu_ids_by_key(menus)
        assert mapping == {BASE_KEY: "rm-1", HOUSEKEEPING_KEY: "rm-2"}


class _FakeResponse:
    """Minimal stand-in for requests.Response — status, body, .json()."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeRequests:
    """Records calls in place of the ``requests`` module.

    Substituted for ``service.requests`` wholesale rather than
    monkeypatching ``requests.post`` globally, so nothing outside this
    module can accidentally be affected — and so a call this fixture does
    not implement fails loudly instead of reaching the network.
    """

    def __init__(self):
        self.posts = []
        self.deletes = []
        self.next_response = _FakeResponse(200)

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self.next_response

    def delete(self, url, **kwargs):
        self.deletes.append((url, kwargs))
        return self.next_response


@pytest.fixture
def fake_requests(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(service, "requests", fake)
    return fake


class TestBulkUnlinkRichMenu:
    """POST /v2/bot/richmenu/bulk/unlink — the counterpart of bulk link.

    Added 2026-08-14 with the empty `base` variant: employees whose variant
    has no menu must be actively unlinked, not left pointing at a menu the
    sync is about to delete.
    """

    def test_posts_user_ids_without_a_rich_menu_id(
        self, staff_oa_enabled, fake_requests
    ):
        service.bulk_unlink_rich_menu(["U-1", "U-2"])

        assert len(fake_requests.posts) == 1
        url, kwargs = fake_requests.posts[0]
        assert url == f"{service.LINE_API_BASE}/v2/bot/richmenu/bulk/unlink"
        # No richMenuId: unlink means "this user holds no per-user menu",
        # not "detach this specific menu". Sending one is a 400 from LINE.
        assert kwargs["json"] == {"userIds": ["U-1", "U-2"]}
        assert "richMenuId" not in kwargs["json"]
        assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert kwargs["timeout"] == service._REQUEST_TIMEOUT_SECONDS

    def test_empty_list_fires_no_request_at_all(
        self, staff_oa_enabled, fake_requests
    ):
        # LINE rejects an empty userIds array, and the sync script reaches
        # this with whatever the base variant held — routinely nobody.
        service.bulk_unlink_rich_menu([])

        assert fake_requests.posts == []

    def test_chunks_exactly_like_bulk_link(self, staff_oa_enabled, fake_requests):
        chunk = service.BULK_LINK_CHUNK_SIZE
        user_ids = [f"U-{index}" for index in range(chunk + 3)]

        service.bulk_unlink_rich_menu(user_ids)
        unlink_chunks = [kwargs["json"]["userIds"] for _url, kwargs in fake_requests.posts]

        fake_requests.posts.clear()
        service.bulk_link_rich_menu(user_ids, "rm-1")
        link_chunks = [kwargs["json"]["userIds"] for _url, kwargs in fake_requests.posts]

        assert len(unlink_chunks) == 2
        assert [len(part) for part in unlink_chunks] == [chunk, 3]
        # Same chunking as the link call, asserted against it rather than
        # against a copy of its arithmetic, so the two cannot drift.
        assert unlink_chunks == link_chunks

    def test_non_2xx_raises_like_every_other_line_call(
        self, staff_oa_enabled, fake_requests
    ):
        fake_requests.next_response = _FakeResponse(500, text="boom")

        with pytest.raises(service.StaffOaApiError):
            service.bulk_unlink_rich_menu(["U-1"])


class TestClearDefaultRichMenu:
    """DELETE /v2/bot/user/all/richmenu — drop the channel default."""

    def test_deletes_the_same_path_the_getter_reads(
        self, staff_oa_enabled, fake_requests
    ):
        service.clear_default_rich_menu()

        assert len(fake_requests.deletes) == 1
        url, kwargs = fake_requests.deletes[0]
        assert url == f"{service.LINE_API_BASE}/v2/bot/user/all/richmenu"
        assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert kwargs["timeout"] == service._REQUEST_TIMEOUT_SECONDS

    def test_404_is_success_because_there_was_nothing_to_clear(
        self, staff_oa_enabled, fake_requests
    ):
        # Mirrors get_default_rich_menu_id()'s 404 -> None. "No default set"
        # is the state this call is trying to reach; finding it already
        # reached must not abort a sync run mid-way.
        fake_requests.next_response = _FakeResponse(404, text="not found")

        assert service.clear_default_rich_menu() is None

    def test_other_errors_still_raise(self, staff_oa_enabled, fake_requests):
        fake_requests.next_response = _FakeResponse(401, text="bad token")

        with pytest.raises(service.StaffOaApiError):
            service.clear_default_rich_menu()


class TestLinkRoleMenuForLineUser:
    @pytest.fixture
    def line_api(self, monkeypatch):
        """Mock the two LINE calls the helper makes; record link calls.

        ``deployed`` is what GET /v2/bot/richmenu/list returns — both real
        variants by default. It is read at call time, so a test can shrink it
        in place to model a channel the sync script has not caught up with.
        """
        calls = {
            "linked": [],
            "unlinked": [],
            "deployed": [
                {"richMenuId": "rm-base", "name": f"staffhub:{BASE_KEY}:aaa"},
                {
                    "richMenuId": "rm-housekeeping",
                    "name": f"staffhub:{HOUSEKEEPING_KEY}:bbb",
                },
            ],
        }
        monkeypatch.setattr(
            service, "get_rich_menu_list", lambda: list(calls["deployed"])
        )
        monkeypatch.setattr(
            service, "link_rich_menu_to_user",
            lambda user_id, menu_id: calls["linked"].append((user_id, menu_id)),
        )
        # Mocked because the no-buttons branch now actively unlinks. Without
        # this the helper would reach requests.delete for real — these tests
        # must never touch the network.
        monkeypatch.setattr(
            service, "unlink_rich_menu_from_user",
            lambda user_id: calls["unlinked"].append(user_id),
        )
        return calls

    def test_returns_none_when_dark(self, staff_oa_dark, test_db, line_api):
        assert service.link_role_menu_for_line_user(test_db, "U-1") is None
        assert line_api["linked"] == []

    def test_returns_none_for_unknown_line_user(self, staff_oa_enabled, test_db, line_api):
        assert service.link_role_menu_for_line_user(test_db, "U-stranger") is None
        assert line_api["linked"] == []

    def test_links_the_grant_driven_variant(self, staff_oa_enabled, test_db, line_api):
        # Re-pointed from `payroll` (which no longer adds a tile) to the one
        # grant that still drives a variant.
        _make_employee(test_db, "1001", line_user_id="U-1")
        _grant(test_db, "1001", MENU_GRANT)

        key = service.link_role_menu_for_line_user(test_db, "U-1")

        assert key == HOUSEKEEPING_KEY
        assert line_api["linked"] == [("U-1", "rm-housekeeping")]

    def test_links_base_when_every_grant_is_menu_irrelevant(
        self, staff_oa_enabled, test_db, line_api
    ):
        # Holding payroll/ota is still not "no grants", but neither grant
        # is menu-relevant, so this employee resolves to `base`. Since
        # แจ้งลา (2026-09-18) made `base` a real one-button menu, the
        # helper links it rather than declining — every linked employee,
        # maid or not, gets the leave tile.
        _make_employee(test_db, "1003", line_user_id="U-3")
        _grant(test_db, "1003", *MENU_IRRELEVANT_GRANTS)

        key = service.link_role_menu_for_line_user(test_db, "U-3")

        assert key == BASE_KEY
        assert line_api["linked"] == [("U-3", "rm-base")]

    def test_links_base_for_an_employee_with_no_grants_at_all(
        self, staff_oa_enabled, test_db, line_api
    ):
        # The commonest case in production: an ordinary non-maid employee.
        # Same outcome as above, reached without any grant rows — worth its
        # own test because it is the path most followers take, and it is
        # the whole point of แจ้งลา being an ungated tile.
        _make_employee(test_db, "1004", line_user_id="U-4")

        key = service.link_role_menu_for_line_user(test_db, "U-4")

        assert key == BASE_KEY
        assert line_api["linked"] == [("U-4", "rm-base")]

    def test_links_the_deployed_base_menu_not_some_other_variant(
        self, staff_oa_enabled, test_db, line_api
    ):
        # deployed_menu_ids_by_key() must resolve this employee to the
        # `staffhub:base:*` richMenuId specifically, not fall through to
        # whatever else happens to be deployed (e.g. the housekeeping
        # variant also present in `line_api["deployed"]`).
        _make_employee(test_db, "1005", line_user_id="U-5")

        key = service.link_role_menu_for_line_user(test_db, "U-5")

        assert key == BASE_KEY
        assert line_api["linked"] == [("U-5", "rm-base")]

    def test_a_demoted_maid_refollowing_is_relinked_to_base(
        self, staff_oa_enabled, test_db, line_api
    ):
        # The regression this used to guard was a stale per-user link
        # surviving a decline. Now that `base` always has a real menu, the
        # self-heal happens by relinking rather than unlinking: an employee
        # whose `housekeeping` grant was revoked, who blocks and re-adds the
        # OA before anyone runs --apply, is relinked straight to the base
        # menu — LINE's per-user link call replaces the previous one, so she
        # no longer keeps maid tiles that now open a Cloudflare block page.
        _make_employee(test_db, "1006", line_user_id="U-6")
        _grant(test_db, "1006", *MENU_IRRELEVANT_GRANTS)

        key = service.link_role_menu_for_line_user(test_db, "U-6")

        assert key == BASE_KEY
        assert line_api["linked"] == [("U-6", "rm-base")]
        assert line_api["unlinked"] == []

    def test_a_maid_with_a_menu_is_linked_not_unlinked(
        self, staff_oa_enabled, test_db, line_api
    ):
        # The mirror of the test above: the unlink must fire ONLY on the
        # no-buttons branch. Unlinking a real maid would blank the menu of
        # the exact person the Hub exists for.
        _make_employee(test_db, "1007", line_user_id="U-7")
        _grant(test_db, "1007", MENU_GRANT)

        assert service.link_role_menu_for_line_user(test_db, "U-7") == HOUSEKEEPING_KEY
        assert line_api["linked"] == [("U-7", "rm-housekeeping")]
        assert line_api["unlinked"] == []

    def test_returns_none_when_variant_not_deployed(self, staff_oa_enabled, test_db, line_api):
        # Was modelled with an `ota` grant, which mints no variant of its own
        # any more (it now resolves to `base`, which IS deployed — so the old
        # fixture asserted the opposite of what it meant). The undeployed
        # variant is now modelled honestly: a channel carrying only the base
        # menu because the sync script has not run since this employee got the
        # housekeeping grant. The helper must decline rather than link them to
        # a menu that is not theirs.
        line_api["deployed"] = [
            {"richMenuId": "rm-base", "name": f"staffhub:{BASE_KEY}:aaa"}
        ]
        _make_employee(test_db, "1002", line_user_id="U-2")
        _grant(test_db, "1002", MENU_GRANT)

        assert service.link_role_menu_for_line_user(test_db, "U-2") is None
        assert line_api["linked"] == []


# ===========================================================================
# fetch_message_content(max_bytes=...) + wait_for_transcoding (video support,
# 2026-09-06) — LINE's data-API content and transcoding-status endpoints,
# mocked at the module's own `requests` name (this module's convention for
# HTTP: see the fake `line_api` fixture above for the rich-menu endpoints).
# ===========================================================================

class _FakeMediaResponse:
    def __init__(self, status_code=200, content=b"", headers=None,
                 json_body=None, chunks=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._json_body = json_body
        self._chunks = chunks if chunks is not None else ([content] if content else [])
        self.closed = False

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body configured")
        return self._json_body

    def iter_content(self, chunk_size=None):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        self.closed = True


class _FakeMediaRequests:
    """A minimal stand-in for the ``requests`` module: ``.get`` pops fake
    responses in order and records every call's url/stream flag."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, timeout=None, stream=False):
        self.calls.append({"url": url, "headers": headers, "stream": stream})
        return self._responses.pop(0)


class TestFetchMessageContentPlain:
    """max_bytes=None (every photo call, unchanged since before video
    support): one-shot ``response.content``, no streaming."""

    def test_returns_bytes_and_content_type(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(
            status_code=200, content=b"hello", headers={"Content-Type": "image/jpeg"},
        )])
        monkeypatch.setattr(service, "requests", fake)
        assert service.fetch_message_content("m1") == (b"hello", "image/jpeg")
        assert fake.calls[0]["stream"] is False

    def test_non_2xx_is_none(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(status_code=404)])
        monkeypatch.setattr(service, "requests", fake)
        assert service.fetch_message_content("m1") is None

    def test_dark_channel_makes_no_request(self, monkeypatch, staff_oa_dark):
        fake = _FakeMediaRequests([])
        monkeypatch.setattr(service, "requests", fake)
        assert service.fetch_message_content("m1") is None
        assert fake.calls == []


class TestFetchMessageContentStreamed:
    """max_bytes given (video support, 2026-09-06): streamed, capped."""

    def test_streams_and_joins_chunks_under_the_cap(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(
            status_code=200, headers={"Content-Type": "video/mp4"},
            chunks=[b"ab", b"cd"],
        )])
        monkeypatch.setattr(service, "requests", fake)
        assert service.fetch_message_content("m1", max_bytes=10) == (b"abcd", "video/mp4")
        assert fake.calls[0]["stream"] is True

    def test_over_the_cap_raises_content_too_large(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(
            status_code=200, headers={"Content-Type": "video/mp4"},
            chunks=[b"a" * 6, b"b" * 6],
        )])
        monkeypatch.setattr(service, "requests", fake)
        with pytest.raises(service.ContentTooLarge):
            service.fetch_message_content("m1", max_bytes=10)

    def test_exactly_at_the_cap_succeeds(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(
            status_code=200, headers={"Content-Type": "video/mp4"},
            chunks=[b"a" * 10],
        )])
        monkeypatch.setattr(service, "requests", fake)
        data, content_type = service.fetch_message_content("m1", max_bytes=10)
        assert data == b"a" * 10

    def test_non_2xx_is_still_none_not_content_too_large(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(status_code=404)])
        monkeypatch.setattr(service, "requests", fake)
        assert service.fetch_message_content("m1", max_bytes=10) is None

    def test_dark_channel_makes_no_request(self, monkeypatch, staff_oa_dark):
        fake = _FakeMediaRequests([])
        monkeypatch.setattr(service, "requests", fake)
        assert service.fetch_message_content("m1", max_bytes=10) is None
        assert fake.calls == []


class TestWaitForTranscoding:
    def test_succeeded_on_the_first_poll_is_true(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(
            status_code=200, json_body={"status": "succeeded"},
        )])
        monkeypatch.setattr(service, "requests", fake)
        assert service.wait_for_transcoding("m1", 90.0) is True
        assert len(fake.calls) == 1

    def test_polls_through_processing_then_succeeds(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([
            _FakeMediaResponse(status_code=200, json_body={"status": "processing"}),
            _FakeMediaResponse(status_code=200, json_body={"status": "succeeded"}),
        ])
        monkeypatch.setattr(service, "requests", fake)
        monkeypatch.setattr(service.time, "sleep", lambda seconds: None)
        assert service.wait_for_transcoding("m1", 90.0) is True
        assert len(fake.calls) == 2

    def test_failed_status_is_false(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(
            status_code=200, json_body={"status": "failed"},
        )])
        monkeypatch.setattr(service, "requests", fake)
        assert service.wait_for_transcoding("m1", 90.0) is False

    def test_a_zero_timeout_gives_up_after_one_still_processing_poll(
        self, monkeypatch, staff_oa_enabled,
    ):
        fake = _FakeMediaRequests([_FakeMediaResponse(
            status_code=200, json_body={"status": "processing"},
        )])
        monkeypatch.setattr(service, "requests", fake)
        assert service.wait_for_transcoding("m1", 0.0) is False
        assert len(fake.calls) == 1

    def test_non_2xx_is_false(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(status_code=500)])
        monkeypatch.setattr(service, "requests", fake)
        assert service.wait_for_transcoding("m1", 90.0) is False

    def test_malformed_json_is_false(self, monkeypatch, staff_oa_enabled):
        fake = _FakeMediaRequests([_FakeMediaResponse(status_code=200, json_body=None)])
        monkeypatch.setattr(service, "requests", fake)
        assert service.wait_for_transcoding("m1", 90.0) is False

    def test_dark_channel_makes_no_request(self, monkeypatch, staff_oa_dark):
        fake = _FakeMediaRequests([])
        monkeypatch.setattr(service, "requests", fake)
        assert service.wait_for_transcoding("m1", 90.0) is False
        assert fake.calls == []
