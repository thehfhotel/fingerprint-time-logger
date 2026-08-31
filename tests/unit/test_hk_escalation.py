"""Unit tests for the housekeeping room-check escalation.

Covers HF ID's half of new-hotel ADR 0008:
  * POST /api/private/reader/hk-escalate — the app↔central endpoint new-hotel's
    scheduler calls when a ขอเช็คห้อง signal sits unacked for 2 minutes.
  * app.services.hk_escalation_service.on_duty_maids — the "On-duty maid"
    glossary rule (clocked in TODAY at THAT branch's device, not clocked out).
  * app.services.staff_oa_service.multicast_text_message — the LINE payload.

THE ENTIRE LINE BOUNDARY IS STUBBED. The autouse ``_block_line_http`` fixture
replaces ``staff_oa_service.requests`` with an object that raises on ANY
attribute access, so no test in this module can reach api.line.me even by an
unexpected code path; tests that need the HTTP layer swap in their own
recording fake. This is deliberate belt-and-braces: an earlier unstubbed path
in this repo really did fire live requests at LINE.
"""
from datetime import datetime, timedelta, timezone

import pytest
import requests

from app.models.models import AttendanceRecord, Device, Employee
from app.services import hk_escalation_service, staff_oa_service

SECRET = "testsecret"  # READER_RESOLVE_SECRET (app↔central)
OA_TOKEN = "staff-oa-token"

ESCALATE_PATH = "/api/private/reader/hk-escalate"

BANGKOK = timezone(timedelta(hours=7))

# A pinned "now" so every day-boundary assertion is deterministic.
NOW_BKK = datetime(2026, 9, 1, 10, 0, tzinfo=BANGKOK)


def _bkk_to_naive_utc(dt: datetime) -> datetime:
    """Bangkok wall-clock -> the naive-UTC value AttendanceRecord stores."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _headers(secret=SECRET):
    return {"X-Reader-Secret": secret}


def _body(branch="HF", room_no="104", url="https://hotel.thehfhotel.org/hk/rooms/7"):
    return {"branch": branch, "roomNo": room_no, "url": url}


# ---------------------------------------------------------------------------
# LINE boundary stubs
# ---------------------------------------------------------------------------


class _ExplodingRequests:
    """Stand-in for the ``requests`` module that refuses every call."""

    def __getattr__(self, name):
        def _boom(*args, **kwargs):
            raise AssertionError(
                f"LINE boundary escaped the stub: requests.{name}{args!r}"
            )

        return _boom


class _FakeResponse:
    def __init__(self, status_code=200, body="{}"):
        self.status_code = status_code
        self.text = body

    def json(self):
        return {}


class _RecordingRequests:
    """Records outbound calls and answers with a canned status code."""

    def __init__(self, status_code=200):
        self.status_code = status_code
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None, **kwargs):
        self.calls.append(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return _FakeResponse(self.status_code)


@pytest.fixture(autouse=True)
def _block_line_http(monkeypatch):
    """No test in this module may reach api.line.me, by any route."""
    monkeypatch.setattr(staff_oa_service, "requests", _ExplodingRequests())


@pytest.fixture
def escalation_enabled(monkeypatch):
    """Secret + staff OA token set: the endpoint is live and can push."""
    monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
    monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", OA_TOKEN)
    monkeypatch.setenv("STAFF_OA_CHANNEL_SECRET", "staff-oa-secret")


@pytest.fixture
def sent_messages(monkeypatch):
    """Capture multicasts at the service seam (no HTTP at all)."""
    calls = []

    def _fake_multicast(line_user_ids, text):
        calls.append({"to": list(line_user_ids), "text": text})

    monkeypatch.setattr(staff_oa_service, "multicast_text_message", _fake_multicast)
    return calls


# ---------------------------------------------------------------------------
# Fixtures for the attendance world
# ---------------------------------------------------------------------------


def _device(test_db, name):
    device = Device(name=name, ip_address=None, port=4370, is_active=True)
    test_db.add(device)
    test_db.commit()
    test_db.refresh(device)
    return device


def _maid(test_db, badge, **overrides):
    defaults = dict(
        badge_number=badge,
        display_name=f"maid-{badge}",
        is_active=True,
        is_hidden=False,
        role="housekeeping",
        line_user_id=f"U{badge}",
        location="HF",
    )
    defaults.update(overrides)
    employee = Employee(**defaults)
    test_db.add(employee)
    test_db.commit()
    test_db.refresh(employee)
    return employee


def _punch(test_db, badge, device, punch_type, when_bkk):
    record = AttendanceRecord(
        employee_badge_number=badge,
        device_id=device.id,
        timestamp=_bkk_to_naive_utc(when_bkk),
        punch_type=punch_type,
    )
    test_db.add(record)
    test_db.commit()
    return record


@pytest.fixture
def branches(test_db):
    return {"HF": _device(test_db, "HF"), "HF_VILLE": _device(test_db, "HF Ville")}


def _badges(employees):
    return [employee.badge_number for employee in employees]


# ===========================================================================
# Secret gate — mirrors /resolve exactly (dark 404, 401 on mismatch)
# ===========================================================================


class TestEscalateAuth:
    def test_dark_returns_404_when_secret_unset(self, test_client, test_db, monkeypatch):
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        response = test_client.post(ESCALATE_PATH, json=_body(), headers=_headers())
        assert response.status_code == 404

    def test_missing_header_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(ESCALATE_PATH, json=_body())
        assert response.status_code == 401

    def test_wrong_secret_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            ESCALATE_PATH, json=_body(), headers=_headers("not-the-secret")
        )
        assert response.status_code == 401

    def test_auth_is_checked_before_the_body(
        self, test_client, test_db, monkeypatch, sent_messages
    ):
        """A bad secret never reveals whether the branch/room were valid."""
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            ESCALATE_PATH,
            json=_body(branch="NOPE", room_no=""),
            headers=_headers("wrong"),
        )
        assert response.status_code == 401
        assert sent_messages == []


# ===========================================================================
# Body validation
# ===========================================================================


class TestEscalateValidation:
    @pytest.mark.parametrize("branch", ["", "hf", "HF_HOTEL", "HFVILLE", "hf_ville", "*"])
    def test_unknown_branch_returns_400(
        self, test_client, test_db, escalation_enabled, sent_messages, branch
    ):
        response = test_client.post(
            ESCALATE_PATH, json=_body(branch=branch), headers=_headers()
        )
        assert response.status_code == 400
        assert sent_messages == []

    @pytest.mark.parametrize(
        "room_no",
        [
            "",
            "   ",
            "1" * 17,                       # over the cap
            "104\nกรุณากดรับ",              # newline injection into our text
            "<script>",
            "104‮",                    # bidi override
        ],
    )
    def test_bad_room_no_returns_400(
        self, test_client, test_db, escalation_enabled, sent_messages, room_no
    ):
        response = test_client.post(
            ESCALATE_PATH, json=_body(room_no=room_no), headers=_headers()
        )
        assert response.status_code == 400
        assert sent_messages == []

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "javascript:alert(1)",
            "hotel.thehfhotel.org/hk",       # no scheme
            "https://" + "x" * 300,          # over the cap
        ],
    )
    def test_bad_url_returns_400(
        self, test_client, test_db, escalation_enabled, sent_messages, url
    ):
        response = test_client.post(
            ESCALATE_PATH, json=_body(url=url), headers=_headers()
        )
        assert response.status_code == 400
        assert sent_messages == []

    def test_missing_field_returns_422(self, test_client, test_db, escalation_enabled):
        response = test_client.post(
            ESCALATE_PATH, json={"branch": "HF", "url": "https://x.invalid"},
            headers=_headers(),
        )
        assert response.status_code == 422


# ===========================================================================
# The ON-DUTY MAID rule (service level, pinned "now")
# ===========================================================================


class TestOnDutyResolution:
    def test_clocked_in_at_branch_device_is_on_duty(self, test_db, branches):
        maid = _maid(test_db, "2001")
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=2))

        assert _badges(
            hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK)
        ) == ["2001"]

    def test_clocked_in_at_hf_is_not_on_duty_at_ville(self, test_db, branches):
        maid = _maid(test_db, "2001")
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=2))

        assert hk_escalation_service.on_duty_maids(
            test_db, "HF_VILLE", now=NOW_BKK
        ) == []

    def test_device_beats_home_branch(self, test_db, branches):
        """A maid whose Employee.location is HF, covering HF Ville today, is
        on-duty at HF VILLE — the day's punch device decides the branch."""
        maid = _maid(test_db, "2002", location="HF")
        _punch(
            test_db, maid.badge_number, branches["HF_VILLE"], 0,
            NOW_BKK - timedelta(hours=3),
        )

        assert _badges(
            hk_escalation_service.on_duty_maids(test_db, "HF_VILLE", now=NOW_BKK)
        ) == ["2002"]
        assert hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK) == []

    def test_clocked_out_is_not_on_duty(self, test_db, branches):
        maid = _maid(test_db, "2003")
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=5))
        _punch(test_db, maid.badge_number, branches["HF"], 1, NOW_BKK - timedelta(hours=1))

        assert hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK) == []

    def test_clocked_out_on_the_other_branch_device_still_counts(
        self, test_db, branches
    ):
        """'Last punch today' is ANY device — a maid who checked in at HF and
        clocked out at HF Ville has gone home, not stayed on duty at HF."""
        maid = _maid(test_db, "2004")
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=6))
        _punch(
            test_db, maid.badge_number, branches["HF_VILLE"], 1,
            NOW_BKK - timedelta(hours=1),
        )

        assert hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK) == []

    def test_clocked_back_in_after_clocking_out_is_on_duty(self, test_db, branches):
        maid = _maid(test_db, "2005")
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=6))
        _punch(test_db, maid.badge_number, branches["HF"], 1, NOW_BKK - timedelta(hours=4))
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=2))

        assert _badges(
            hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK)
        ) == ["2005"]

    def test_no_punch_today_is_not_on_duty(self, test_db, branches):
        _maid(test_db, "2006")

        assert hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK) == []

    def test_yesterdays_check_in_does_not_carry_over(self, test_db, branches):
        maid = _maid(test_db, "2007")
        # 23:30 Bangkok YESTERDAY — still "yesterday" despite being 16:30Z.
        _punch(
            test_db, maid.badge_number, branches["HF"], 0,
            NOW_BKK.replace(hour=23, minute=30) - timedelta(days=1),
        )

        assert hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK) == []

    def test_check_in_just_after_bangkok_midnight_counts(self, test_db, branches):
        """00:30 Bangkok today is 17:30Z YESTERDAY in storage — the window has
        to be Bangkok-day-shaped, not UTC-day-shaped."""
        maid = _maid(test_db, "2008")
        _punch(
            test_db, maid.badge_number, branches["HF"], 0,
            NOW_BKK.replace(hour=0, minute=30),
        )

        assert _badges(
            hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK)
        ) == ["2008"]

    def test_inactive_maid_is_excluded(self, test_db, branches):
        maid = _maid(test_db, "2009", is_active=False)
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=2))

        assert hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK) == []

    @pytest.mark.parametrize("line_user_id", [None, ""])
    def test_maid_without_line_user_id_is_excluded(
        self, test_db, branches, line_user_id
    ):
        maid = _maid(test_db, "2010", line_user_id=line_user_id)
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=2))

        assert hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK) == []

    @pytest.mark.parametrize("role", ["reception", "technician", "admin", None])
    def test_non_housekeeping_role_is_excluded(self, test_db, branches, role):
        maid = _maid(test_db, "2011", role=role)
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=2))

        assert hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK) == []

    def test_unspecified_punch_type_opens_a_shift(self, test_db, branches):
        """255 (unspecified) DOES open a shift — measured prod reality: the ZK
        devices record ~62% of maid punches as 255, so a strict check-in-only
        rule would answer nobody_on_duty for most real shifts (see the
        CHECK_IN_PUNCH_TYPES comment). Only an explicit check-out closes."""
        maid = _maid(test_db, "2012")
        _punch(
            test_db, maid.badge_number, branches["HF"], 255,
            NOW_BKK - timedelta(hours=2),
        )

        assert _badges(
            hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK)
        ) == ["2012"]

    def test_unspecified_last_punch_does_not_close_a_shift(self, test_db, branches):
        maid = _maid(test_db, "2013")
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=4))
        _punch(
            test_db, maid.badge_number, branches["HF"], 255,
            NOW_BKK - timedelta(hours=1),
        )

        assert _badges(
            hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK)
        ) == ["2013"]

    def test_multiple_maids_returned_ordered_by_badge(self, test_db, branches):
        for badge in ("2030", "2010", "2020"):
            maid = _maid(test_db, badge)
            _punch(
                test_db, maid.badge_number, branches["HF"], 0,
                NOW_BKK - timedelta(hours=2),
            )

        assert _badges(
            hk_escalation_service.on_duty_maids(test_db, "HF", now=NOW_BKK)
        ) == ["2010", "2020", "2030"]

    def test_unknown_branch_resolves_to_nobody(self, test_db, branches):
        maid = _maid(test_db, "2014")
        _punch(test_db, maid.badge_number, branches["HF"], 0, NOW_BKK - timedelta(hours=2))

        assert hk_escalation_service.on_duty_maids(test_db, "NOPE", now=NOW_BKK) == []

    def test_missing_branch_device_row_resolves_to_nobody(self, test_db):
        """No 'HF Ville' device configured: nobody can have clocked in there."""
        hf = _device(test_db, "HF")
        maid = _maid(test_db, "2015")
        _punch(test_db, maid.badge_number, hf, 0, NOW_BKK - timedelta(hours=2))

        assert hk_escalation_service.on_duty_maids(
            test_db, "HF_VILLE", now=NOW_BKK
        ) == []


# ===========================================================================
# The endpoint: outcomes
# ===========================================================================


class TestEscalateOutcomes:
    def test_nobody_on_duty_returns_200_sent_false_and_pushes_nothing(
        self, test_client, test_db, branches, escalation_enabled, sent_messages
    ):
        _maid(test_db, "3001")  # employed, but no punch today

        response = test_client.post(ESCALATE_PATH, json=_body(), headers=_headers())

        assert response.status_code == 200
        assert response.json() == {
            "sent": False,
            "recipients": 0,
            "reason": "nobody_on_duty",
        }
        assert sent_messages == []

    def test_on_duty_maids_receive_one_multicast(
        self, test_client, test_db, branches, escalation_enabled, sent_messages
    ):
        for badge in ("3010", "3011"):
            maid = _maid(test_db, badge)
            _punch(test_db, maid.badge_number, branches["HF"], 0, datetime.now(BANGKOK))
        # An HF Ville maid must not be in the HF audience.
        ville = _maid(test_db, "3012")
        _punch(test_db, ville.badge_number, branches["HF_VILLE"], 0, datetime.now(BANGKOK))

        response = test_client.post(
            ESCALATE_PATH,
            json=_body(room_no="104", url="https://hotel.thehfhotel.org/hk/rooms/42"),
            headers=_headers(),
        )

        assert response.status_code == 200
        assert response.json() == {"sent": True, "recipients": 2}
        assert len(sent_messages) == 1
        assert sent_messages[0]["to"] == ["U3010", "U3011"]
        assert sent_messages[0]["text"] == (
            "ขอเช็คห้อง 104 ยังไม่มีคนรับ กรุณากดรับในเมนูแม่บ้าน\n"
            "https://hotel.thehfhotel.org/hk/rooms/42"
        )

    def test_ville_escalation_reaches_only_ville_maids(
        self, test_client, test_db, branches, escalation_enabled, sent_messages
    ):
        hf = _maid(test_db, "3020")
        _punch(test_db, hf.badge_number, branches["HF"], 0, datetime.now(BANGKOK))
        ville = _maid(test_db, "3021")
        _punch(test_db, ville.badge_number, branches["HF_VILLE"], 0, datetime.now(BANGKOK))

        response = test_client.post(
            ESCALATE_PATH, json=_body(branch="HF_VILLE"), headers=_headers()
        )

        assert response.status_code == 200
        assert response.json() == {"sent": True, "recipients": 1}
        assert sent_messages[0]["to"] == ["U3021"]

    def test_message_carries_no_emoji(
        self, test_client, test_db, branches, escalation_enabled, sent_messages
    ):
        maid = _maid(test_db, "3030")
        _punch(test_db, maid.badge_number, branches["HF"], 0, datetime.now(BANGKOK))

        test_client.post(ESCALATE_PATH, json=_body(), headers=_headers())

        text = sent_messages[0]["text"]
        assert not any(ord(ch) >= 0x1F000 for ch in text)
        assert not any(0x2600 <= ord(ch) <= 0x27BF for ch in text)

    def test_line_api_failure_returns_502(
        self, test_client, test_db, branches, escalation_enabled, monkeypatch
    ):
        maid = _maid(test_db, "3040")
        _punch(test_db, maid.badge_number, branches["HF"], 0, datetime.now(BANGKOK))

        def _boom(line_user_ids, text):
            raise staff_oa_service.StaffOaApiError("multicast message", 429, "quota")

        monkeypatch.setattr(staff_oa_service, "multicast_text_message", _boom)

        response = test_client.post(ESCALATE_PATH, json=_body(), headers=_headers())
        assert response.status_code == 502

    def test_line_network_error_returns_502(
        self, test_client, test_db, branches, escalation_enabled, monkeypatch
    ):
        maid = _maid(test_db, "3041")
        _punch(test_db, maid.badge_number, branches["HF"], 0, datetime.now(BANGKOK))

        def _boom(line_user_ids, text):
            raise requests.exceptions.ConnectTimeout("api.line.me unreachable")

        monkeypatch.setattr(staff_oa_service, "multicast_text_message", _boom)

        response = test_client.post(ESCALATE_PATH, json=_body(), headers=_headers())
        assert response.status_code == 502

    def test_resolution_error_returns_502(
        self, test_client, test_db, branches, escalation_enabled, monkeypatch,
        sent_messages,
    ):
        def _boom(db, branch, *, now=None):
            raise RuntimeError("database gone")

        monkeypatch.setattr(hk_escalation_service, "on_duty_maids", _boom)

        response = test_client.post(ESCALATE_PATH, json=_body(), headers=_headers())
        assert response.status_code == 502
        assert sent_messages == []

    def test_staff_oa_token_unset_returns_503_without_pushing(
        self, test_client, test_db, branches, monkeypatch, sent_messages
    ):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        monkeypatch.delenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", raising=False)
        maid = _maid(test_db, "3050")
        _punch(test_db, maid.badge_number, branches["HF"], 0, datetime.now(BANGKOK))

        response = test_client.post(ESCALATE_PATH, json=_body(), headers=_headers())

        assert response.status_code == 503
        assert sent_messages == []


# ===========================================================================
# The LINE multicast payload (real client code, faked transport)
# ===========================================================================


class TestMulticastPayload:
    def test_payload_shape(self, monkeypatch):
        monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", OA_TOKEN)
        fake = _RecordingRequests()
        monkeypatch.setattr(staff_oa_service, "requests", fake)

        staff_oa_service.multicast_text_message(["U1", "U2"], "ทดสอบ\nhttps://x.invalid")

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["url"] == "https://api.line.me/v2/bot/message/multicast"
        assert call["headers"]["Authorization"] == f"Bearer {OA_TOKEN}"
        assert call["headers"]["Content-Type"] == "application/json"
        assert call["json"] == {
            "to": ["U1", "U2"],
            "messages": [{"type": "text", "text": "ทดสอบ\nhttps://x.invalid"}],
        }
        assert call["timeout"] == staff_oa_service._REQUEST_TIMEOUT_SECONDS

    def test_empty_recipient_list_sends_nothing(self, monkeypatch):
        """LINE rejects an empty ``to`` array; 'nobody to tell' must be a no-op."""
        monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", OA_TOKEN)
        fake = _RecordingRequests()
        monkeypatch.setattr(staff_oa_service, "requests", fake)

        staff_oa_service.multicast_text_message([], "ignored")

        assert fake.calls == []

    def test_recipients_are_chunked_at_the_line_cap(self, monkeypatch):
        monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", OA_TOKEN)
        fake = _RecordingRequests()
        monkeypatch.setattr(staff_oa_service, "requests", fake)

        ids = [f"U{i}" for i in range(staff_oa_service.MULTICAST_CHUNK_SIZE + 3)]
        staff_oa_service.multicast_text_message(ids, "hi")

        assert len(fake.calls) == 2
        assert len(fake.calls[0]["json"]["to"]) == staff_oa_service.MULTICAST_CHUNK_SIZE
        assert len(fake.calls[1]["json"]["to"]) == 3

    def test_non_2xx_raises(self, monkeypatch):
        monkeypatch.setenv("STAFF_OA_CHANNEL_ACCESS_TOKEN", OA_TOKEN)
        fake = _RecordingRequests(status_code=429)
        monkeypatch.setattr(staff_oa_service, "requests", fake)

        with pytest.raises(staff_oa_service.StaffOaApiError):
            staff_oa_service.multicast_text_message(["U1"], "hi")


# ===========================================================================
# Message construction
# ===========================================================================


class TestBuildMessage:
    def test_two_lines_room_then_url(self):
        text = hk_escalation_service.build_message("104", "https://x.invalid/hk/rooms/1")
        assert text.splitlines() == [
            "ขอเช็คห้อง 104 ยังไม่มีคนรับ กรุณากดรับในเมนูแม่บ้าน",
            "https://x.invalid/hk/rooms/1",
        ]

    def test_fields_are_clamped_defensively(self):
        text = hk_escalation_service.build_message(
            "9" * 40, "https://x.invalid/" + "y" * 400
        )
        room_line, url_line = text.splitlines()
        assert room_line.count("9") == hk_escalation_service.ROOM_NO_MAX_CHARS
        assert len(url_line) == hk_escalation_service.URL_MAX_CHARS
