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

AND `base` IS NOW EMPTY
-----------------------
The clock-in tile — the last ungated button — was removed the same day
("remove the clock-in button too"), so the `base` variant has ZERO buttons.
An employee who resolves to it has no menu, which changes what this module
promises: ``link_role_menu_for_line_user`` must return None for them rather
than link them to anything, and the sync script needs the two calls added
alongside that, ``clear_default_rich_menu`` and ``bulk_unlink_rich_menu``.
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

    def test_the_base_variant_has_no_buttons(self):
        # The premise behind every "returns None / links nothing" assertion
        # below. If a base button ever comes back, those tests are testing
        # the wrong thing and must be re-pointed, not deleted.
        assert staff_oa_menu.buttons_for(frozenset()) == ()
        assert staff_oa_menu.buttons_for({MENU_GRANT}) != ()


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

    def test_returns_none_when_every_grant_is_menu_irrelevant(
        self, staff_oa_enabled, test_db, line_api
    ):
        # Was test_links_base_when_every_grant_is_menu_irrelevant, asserting
        # ("U-3", "rm-base"). Holding payroll/ota is still not "no grants" —
        # but since the clock-in tile left on 2026-08-14 the `base` variant
        # they resolve to has no buttons, so there is no menu to link. The
        # helper must decline, quietly: no exception (it runs inside the
        # follow webhook, where a raise is logged as a failed event) and
        # above all no link to some other variant's menu, which would hand
        # this employee maid tools they hold no grant for.
        _make_employee(test_db, "1003", line_user_id="U-3")
        _grant(test_db, "1003", *MENU_IRRELEVANT_GRANTS)

        assert service.link_role_menu_for_line_user(test_db, "U-3") is None
        assert line_api["linked"] == []

    def test_returns_none_for_an_employee_with_no_grants_at_all(
        self, staff_oa_enabled, test_db, line_api
    ):
        # The commonest case in production now: an ordinary non-maid
        # employee. Same outcome as above, reached without any grant rows —
        # worth its own test because it is the path most followers take.
        _make_employee(test_db, "1004", line_user_id="U-4")

        assert service.link_role_menu_for_line_user(test_db, "U-4") is None
        assert line_api["linked"] == []

    def test_does_not_raise_even_when_a_base_menu_is_still_deployed(
        self, staff_oa_enabled, test_db, line_api
    ):
        # A stale `staffhub:base:*` menu can sit on the channel between the
        # button removal and the next sync run. The helper must NOT link it
        # just because deployed_menu_ids_by_key() still finds it: the
        # employee's variant has no buttons, and that check comes first.
        _make_employee(test_db, "1005", line_user_id="U-5")

        assert service.link_role_menu_for_line_user(test_db, "U-5") is None
        assert line_api["linked"] == []

    def test_a_demoted_maid_refollowing_is_actively_unlinked(
        self, staff_oa_enabled, test_db, line_api
    ):
        # The regression this guards: declining to link is NOT enough, because
        # a previous link survives. An employee whose `housekeeping` grant was
        # revoked, who blocks and re-adds the OA before anyone runs
        # --apply, would otherwise keep her maid tiles — buttons that now open
        # a Cloudflare block page, which is exactly the dead-end this Hub has
        # been shedding. The refollow must self-heal rather than wait for the
        # next sync.
        _make_employee(test_db, "1006", line_user_id="U-6")
        _grant(test_db, "1006", *MENU_IRRELEVANT_GRANTS)

        assert service.link_role_menu_for_line_user(test_db, "U-6") is None
        assert line_api["linked"] == []
        assert line_api["unlinked"] == ["U-6"]

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


class TestGuestFeedbackForwarder:
    """LINE events relayed to the guest-feedback app (2026-09-05).

    LINE allows ONE Official Account per group chat. The staff group hosts
    the OA these tests have been about all along, so guest-feedback cannot
    be invited alongside it and cannot receive that group's webhook — HF ID
    forwards a reduced event instead (guest-feedback
    docs/CONTRACTS.md §15.4). Since the same day it also forwards 1:1
    ``message`` events, reduced to their ids, so an allowlisted manager can
    preview the pending requests privately (§15.5).

    TWO SHAPES, DELIBERATELY DIFFERENT. A group payload carries the groupId
    and NO userId (staff chatter and who said it stay here); a 1:1 payload
    carries the userId — it is the identity guest-feedback allowlists — and
    ``groupId: None``. Neither carries message text, no `room` event crosses
    at all, and `follow`/`unfollow` never do either: those are the Employee
    Hub's own. That, and "the forward can never fail the webhook", are the
    properties pinned below; the plumbing matters less than either.
    """

    FORWARD_URL = "http://feedback:4080/api/internal/line/event"
    FORWARD_SECRET = "guest-feedback-shared-secret"

    @pytest.fixture
    def forwarder_configured(self, monkeypatch):
        monkeypatch.setenv("GUEST_FEEDBACK_LINE_URL", self.FORWARD_URL)
        monkeypatch.setenv("GUEST_FEEDBACK_LINE_SECRET", self.FORWARD_SECRET)

    @pytest.fixture
    def forwarder_dark(self, monkeypatch):
        monkeypatch.delenv("GUEST_FEEDBACK_LINE_URL", raising=False)
        monkeypatch.delenv("GUEST_FEEDBACK_LINE_SECRET", raising=False)

    @staticmethod
    def _group_message(text="ห้อง 301 ทำความสะอาดแล้ว"):
        """A realistic group message — text included, as LINE sends it."""
        return {
            "type": "message",
            "replyToken": "reply-token-1",
            "timestamp": 1757000000000,
            "source": {"type": "group", "groupId": "Cgroup123", "userId": "Uspeaker"},
            "message": {"type": "text", "id": "m1", "text": text},
        }

    # -- what gets reduced, and to what ------------------------------------

    def test_group_message_reduces_to_the_documented_payload(self):
        assert service.group_event_forward_payload(self._group_message()) == {
            "type": "message",
            "replyToken": "reply-token-1",
            "timestamp": 1757000000000,
            "groupId": "Cgroup123",
            "channel": "staff-oa",
        }

    def test_the_payload_never_carries_message_text_or_the_speaker(self):
        # The whole privacy argument for this feature: staff chatter and who
        # said it stay inside LINE and this app. A payload that grew a
        # `message` or `userId` key would leak both to another app.
        payload = service.group_event_forward_payload(
            self._group_message("แขกห้อง 402 บ่นเรื่องแอร์")
        )
        assert set(payload) == {
            "type", "replyToken", "timestamp", "groupId", "channel"
        }
        assert "บ่น" not in json.dumps(payload, ensure_ascii=False)
        assert "Uspeaker" not in json.dumps(payload)

    @pytest.mark.parametrize("event_type", ["message", "join", "memberJoined", "leave"])
    def test_every_forwardable_type_survives(self, event_type):
        event = {
            "type": event_type,
            "timestamp": 1,
            "source": {"type": "group", "groupId": "Cg"},
        }
        payload = service.group_event_forward_payload(event)
        assert payload is not None and payload["type"] == event_type
        # replyToken is optional (leave/memberLeft carry none) and must be
        # sent as an explicit null rather than dropped — the receiver's
        # schema has the key.
        assert payload["replyToken"] is None

    @pytest.mark.parametrize("event_type", ["follow", "unfollow", "postback", "memberLeft"])
    def test_group_events_guest_feedback_does_not_act_on_are_dropped(self, event_type):
        event = {"type": event_type, "source": {"type": "group", "groupId": "Cg"}}
        assert service.group_event_forward_payload(event) is None

    @pytest.mark.parametrize(
        "event_type", ["message", "join", "memberJoined", "leave", "follow"]
    )
    def test_a_room_source_is_never_forwardable(self, event_type):
        # A multi-person room is a private conversation guest-feedback has no
        # business seeing, whatever the event type — and unlike a 1:1 there is
        # nothing it could do with one: the preview answers a person.
        event = {
            "type": event_type,
            "replyToken": "r",
            "source": {"type": "room", "roomId": "R1", "userId": "U1"},
        }
        assert service.group_event_forward_payload(event) is None

    def test_a_group_source_without_a_group_id_is_dropped(self):
        event = {"type": "message", "source": {"type": "group"}}
        assert service.group_event_forward_payload(event) is None

    # -- 1:1 (the private preview, guest-feedback §15.5) --------------------

    @staticmethod
    def _direct_message(text="ขอดูรายการที่ค้างหน่อยค่ะ"):
        """A realistic 1:1 message — text included, as LINE sends it."""
        return {
            "type": "message",
            "replyToken": "reply-token-direct",
            "timestamp": 1757000000001,
            "source": {"type": "user", "userId": "Umanager"},
            "message": {"type": "text", "id": "m9", "text": text},
        }

    def test_direct_message_reduces_to_the_documented_ids_only_payload(self):
        assert service.group_event_forward_payload(self._direct_message()) == {
            "type": "message",
            "replyToken": "reply-token-direct",
            "timestamp": 1757000000001,
            "userId": "Umanager",
            "groupId": None,
            "channel": "staff-oa",
        }

    def test_the_direct_payload_never_carries_message_text(self):
        # Same privacy rule as the group payload: the ids and the reply
        # window cross, the words never do. `groupId: None` is carried
        # explicitly rather than dropped — it is what tells guest-feedback to
        # answer this person instead of posting into the staff group.
        payload = service.group_event_forward_payload(
            self._direct_message("ห้อง 402 บ่นเรื่องแอร์")
        )
        assert set(payload) == {
            "type", "replyToken", "timestamp", "userId", "groupId", "channel"
        }
        assert payload["groupId"] is None
        assert "บ่น" not in json.dumps(payload, ensure_ascii=False)

    @pytest.mark.parametrize(
        "event_type", ["follow", "unfollow", "postback", "join", "leave"]
    )
    def test_only_message_crosses_from_a_1_to_1_chat(self, event_type):
        # `follow`/`unfollow` are the Employee Hub's own events — they link
        # and unlink Role Menus in app/api/staff_oa.py and must not leave
        # this app — and a menu tap (`postback`) is nobody else's business.
        event = {
            "type": event_type,
            "replyToken": "r",
            "source": {"type": "user", "userId": "Umanager"},
        }
        assert service.group_event_forward_payload(event) is None

    def test_a_user_source_without_a_user_id_is_dropped(self):
        # Nothing to allowlist and nobody to answer.
        event = {"type": "message", "replyToken": "r", "source": {"type": "user"}}
        assert service.group_event_forward_payload(event) is None

    def test_a_withheld_token_is_withheld_from_a_1_to_1_too(self):
        # The single-use-token rule is the same in both shapes, and it bites
        # hardest here: the staff bot answers every 1:1 text it is sent, so
        # this is the ROUTINE 1:1 payload, not the exception (see
        # docs/EMPLOYEE_HUB_SETUP.md, "Known limitation — the reply token").
        payload = service.group_event_forward_payload(
            self._direct_message(), withhold_reply_token=True
        )
        assert payload["replyToken"] is None
        assert payload["userId"] == "Umanager"  # the id still crosses

    def test_the_group_payload_did_not_grow_a_user_id_key(self):
        # The 1:1 shape carries userId; the group shape must not start to.
        # Asserted against the live reducer rather than a copy of it so the
        # two shapes cannot quietly converge.
        payload = service.group_event_forward_payload(self._group_message())
        assert "userId" not in payload
        assert "groupId" in payload

    @pytest.mark.parametrize("event", [None, "message", 7, {}, {"source": "group"}])
    def test_junk_events_reduce_to_none_instead_of_raising(self, event):
        assert service.group_event_forward_payload(event) is None

    # -- the POST ----------------------------------------------------------

    def test_posts_each_payload_with_the_shared_secret_header(
        self, forwarder_configured, fake_requests
    ):
        payloads = [
            service.group_event_forward_payload(self._group_message()),
            service.group_event_forward_payload(
                {"type": "join", "source": {"type": "group", "groupId": "Cg2"}}
            ),
        ]

        service.forward_group_events(payloads)

        assert len(fake_requests.posts) == 2
        url, kwargs = fake_requests.posts[0]
        assert url == self.FORWARD_URL
        assert kwargs["json"] == payloads[0]
        assert kwargs["headers"] == {"X-Reader-Secret": self.FORWARD_SECRET}
        assert kwargs["timeout"] == 2
        assert fake_requests.posts[1][1]["json"] == payloads[1]

    def test_dark_when_the_url_is_empty(self, forwarder_dark, fake_requests):
        service.forward_group_events([self._group_message()])
        assert fake_requests.posts == []

    def test_a_non_2xx_answer_is_swallowed(self, forwarder_configured, fake_requests):
        fake_requests.next_response = _FakeResponse(401, text="unauthorized")
        # No StaffOaApiError here, unlike every LINE call in this module:
        # this one hangs off a webhook that must answer 200 regardless.
        service.forward_group_events([self._group_message()])
        assert len(fake_requests.posts) == 1

    def test_a_transport_failure_is_swallowed_and_does_not_stop_the_batch(
        self, forwarder_configured, fake_requests, monkeypatch
    ):
        attempted = []

        def _explode(url, **kwargs):
            attempted.append(kwargs["json"]["groupId"])
            raise OSError("connection refused")

        monkeypatch.setattr(fake_requests, "post", _explode)
        service.forward_group_events([
            {"groupId": "Cg1", "type": "message"},
            {"groupId": "Cg2", "type": "join"},
        ])
        assert attempted == ["Cg1", "Cg2"]  # one bad event never eats the rest

    # -- the background hand-off -------------------------------------------

    def test_background_hand_off_runs_the_forward_off_the_caller(
        self, forwarder_configured, monkeypatch
    ):
        import threading as _threading

        seen = {}
        done = _threading.Event()

        def _record(payloads):
            seen["payloads"] = payloads
            seen["thread"] = _threading.current_thread()
            done.set()

        monkeypatch.setattr(service, "forward_group_events", _record)
        service.forward_group_events_in_background([{"type": "join"}])

        assert done.wait(timeout=5), "the forward never ran"
        assert seen["payloads"] == [{"type": "join"}]
        assert seen["thread"] is not _threading.current_thread()

    def test_background_hand_off_is_a_no_op_when_dark_or_empty(
        self, forwarder_dark, monkeypatch
    ):
        called = []
        monkeypatch.setattr(service, "forward_group_events", called.append)

        service.forward_group_events_in_background([{"type": "join"}])  # dark
        monkeypatch.setenv("GUEST_FEEDBACK_LINE_URL", self.FORWARD_URL)
        service.forward_group_events_in_background([])  # nothing to send

        assert called == []

    def test_background_hand_off_swallows_a_thread_that_cannot_start(
        self, forwarder_configured, monkeypatch
    ):
        # Belt and braces: the caller is a webhook, so even "the process is
        # out of threads" must not become a 500.
        class _CannotStart:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise RuntimeError("can't start new thread")

        monkeypatch.setattr(service.threading, "Thread", _CannotStart)
        service.forward_group_events_in_background([{"type": "join"}])  # no raise
