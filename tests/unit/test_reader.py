"""Unit tests for the card-reader identity API (app.api.reader).

Covers HF ID as the central card-login authority:
  * /resolve — direct UID -> employee lookup (app↔central).
  * /resolve-badge — the same lookup keyed by badge, for an app that already
               holds an identity and needs the employee's branch location
               (app↔central).
  * /scan    — the ESP32 reader ingests a tap (reader↔central).
  * /claim   — an app backend pairs a terminal to a reader (app↔central).
  * /wait    — an app backend long-polls for the tap and receives a signed
               one-time card assertion (an RS256 OIDC id_token).
All server-to-server, guarded by the ``X-Reader-Secret`` shared secret.
"""
import urllib.parse

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api import reader as reader_module
from app.models.models import Employee, EmployeeAppGrant
from app.services import oidc_service
from app.services.line_auth_service import line_auth_service

SECRET = "testsecret"          # READER_RESOLVE_SECRET (app↔central)
READER_SECRET = "readersecret"  # READER_SECRET (reader↔central)

# One RSA key for the whole module — the HF ID signing key used to mint (and,
# via its public half, verify) card assertions.
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = _PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()
_ISSUER = "https://id.thehfhotel.org/oidc"


def _make_employee(test_db, badge, **overrides):
    defaults = dict(
        badge_number=badge, display_name=f"emp-{badge}", is_active=True, is_hidden=False
    )
    defaults.update(overrides)
    employee = Employee(**defaults)
    test_db.add(employee)
    test_db.commit()
    test_db.refresh(employee)
    return employee


def _grant(test_db, badge, *app_ids):
    for app_id in app_ids:
        test_db.add(EmployeeAppGrant(employee_badge_number=badge, app_id=app_id))
    test_db.commit()


def _headers(secret=SECRET):
    return {"X-Reader-Secret": secret}


@pytest.fixture(autouse=True)
def _reset_reader_state():
    """Clear the module-level tap/claim stores between tests for isolation."""
    reader_module.reset_state()
    yield
    reader_module.reset_state()


@pytest.fixture
def card_login_enabled(monkeypatch):
    """Enable the full card-login surface with a tiny long-poll budget so /wait
    timeout tests finish in a blink instead of 25 seconds."""
    monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
    monkeypatch.setenv("READER_SECRET", READER_SECRET)
    monkeypatch.setenv("HFID_SIGNING_KEY", _PRIVATE_PEM)
    monkeypatch.delenv("HFID_ISSUER", raising=False)
    monkeypatch.setenv("READER_WAIT_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("READER_WAIT_TICK_SECONDS", "0.02")
    oidc_service.reset_state()
    yield
    oidc_service.reset_state()


class TestReaderResolveAuth:
    def test_dark_returns_404_when_secret_unset(self, test_client, test_db, monkeypatch):
        # No READER_RESOLVE_SECRET in the environment -> the surface is dark.
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        _make_employee(test_db, "1001", nfc_card_uid="AABBCCDD")

        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "AABBCCDD"},
            headers=_headers(),
        )
        assert response.status_code == 404

    def test_missing_header_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "AABBCCDD"},
        )
        assert response.status_code == 401

    def test_wrong_secret_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "AABBCCDD"},
            headers=_headers("not-the-secret"),
        )
        assert response.status_code == 401


class TestReaderResolve:
    def test_found_returns_identity_and_apps(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(
            test_db, "1001", display_name="สมชาย", nfc_card_uid="AABBCCDD",
            location="HF_VILLE",
        )
        test_db.add(EmployeeAppGrant(employee_badge_number="1001", app_id="rooms"))
        test_db.add(EmployeeAppGrant(employee_badge_number="1001", app_id="portal"))
        test_db.commit()

        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "AABBCCDD"},
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json() == {
            "found": True,
            "badge": "1001",
            "display_name": "สมชาย",
            "apps": ["portal", "rooms"],  # ordered by app_id
            "active": True,
            "pending": False,
            "location": "HF_VILLE",
        }

    def test_unknown_uid_returns_found_false(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "NOSUCHUID"},
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json() == {
            "found": False,
            "badge": None,
            "display_name": None,
            "apps": [],
            "active": False,
            "pending": False,
            "location": None,
        }

    def test_case_insensitive_match(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        # Stored lowercase (mixed-case legacy data); the reader sends uppercase.
        _make_employee(test_db, "1002", nfc_card_uid="deadbeef")

        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "DEADBEEF"},
            headers=_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["badge"] == "1002"

    def test_inactive_pending_employee_still_found_with_flags(
        self, test_client, test_db, monkeypatch
    ):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(
            test_db,
            "1003",
            nfc_card_uid="CAFEBABE",
            is_active=False,
            pending_approval=True,
        )

        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "CAFEBABE"},
            headers=_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["badge"] == "1003"
        assert data["active"] is False
        assert data["pending"] is True


# ============================================================================
# /resolve-badge — badge -> identity + branch location (READER_RESOLVE_SECRET)
# ============================================================================
#
# The badge-keyed sibling of /resolve. It must behave IDENTICALLY on the auth
# axis (dark 404 / 401 / 200) and on the not-found axis (200 found=false), so
# these mirror the /resolve tests above deliberately rather than testing a
# reduced surface.


class TestReaderResolveBadgeAuth:
    def test_dark_returns_404_when_secret_unset(self, test_client, test_db, monkeypatch):
        # No READER_RESOLVE_SECRET in the environment -> the surface is dark,
        # exactly like /resolve: indistinguishable from a route that isn't there.
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        _make_employee(test_db, "1001", location="HF_VILLE")

        response = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "1001"},
            headers=_headers(),
        )
        assert response.status_code == 404

    def test_missing_header_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "1001"},
        )
        assert response.status_code == 401

    def test_wrong_secret_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(test_db, "1001", location="HF_VILLE")

        response = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "1001"},
            headers=_headers("not-the-secret"),
        )
        assert response.status_code == 401


class TestReaderResolveBadge:
    def test_found_returns_identity_apps_and_location(
        self, test_client, test_db, monkeypatch
    ):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(
            test_db, "2001", display_name="สมหญิง", location="HF_VILLE"
        )
        _grant(test_db, "2001", "rooms", "portal")

        response = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "2001"},
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json() == {
            "found": True,
            "badge": "2001",
            "display_name": "สมหญิง",
            "apps": ["portal", "rooms"],  # ordered by app_id
            "active": True,
            "pending": False,
            "location": "HF_VILLE",
        }

    def test_hf_location_passes_through(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(test_db, "2002", location="HF")

        response = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "2002"},
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json()["location"] == "HF"

    def test_null_location_stays_null_and_is_not_defaulted(
        self, test_client, test_db, monkeypatch
    ):
        """LOAD-BEARING: an employee with no branch on file must answer null.

        The consumer refuses a branch-scoped action when HF ID does not know
        the employee's branch. If this endpoint ever coerced NULL to "HF" the
        refusal would silently become "file it against HF Hotel" — the exact
        wrong-property bug the endpoint exists to prevent.
        """
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(test_db, "2003")  # location left unset -> NULL

        response = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "2003"},
            headers=_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        # The key is PRESENT (so the consumer can tell "unknown" from "the
        # server is too old to answer") and its value is null, not "HF".
        assert "location" in data
        assert data["location"] is None

    def test_unknown_badge_returns_found_false(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "9999"},
            headers=_headers(),
        )
        # Not an error: an unknown badge is a normal answer, like /resolve's
        # unknown UID.
        assert response.status_code == 200
        assert response.json() == {
            "found": False,
            "badge": None,
            "display_name": None,
            "apps": [],
            "active": False,
            "pending": False,
            "location": None,
        }

    def test_inactive_pending_employee_still_found_with_flags(
        self, test_client, test_db, monkeypatch
    ):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(
            test_db,
            "2004",
            is_active=False,
            pending_approval=True,
            location="HF_VILLE",
        )

        response = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "2004"},
            headers=_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        # Reported accurately rather than hidden — the caller decides what an
        # inactive employee may do, exactly as with /resolve.
        assert data["found"] is True
        assert data["badge"] == "2004"
        assert data["active"] is False
        assert data["pending"] is True
        assert data["location"] == "HF_VILLE"

    def test_badge_match_is_exact_but_trimmed(self, test_client, test_db, monkeypatch):
        """Whitespace is stripped; case is NOT folded (unlike the UID lookup).

        A badge is the identity key itself, unique case-sensitively, so folding
        case could map two distinct badges onto one employee.
        """
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(test_db, "hk1", location="HF_VILLE")

        padded = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "  hk1  "},
            headers=_headers(),
        )
        assert padded.status_code == 200
        assert padded.json()["found"] is True

        wrong_case = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "HK1"},
            headers=_headers(),
        )
        assert wrong_case.status_code == 200
        assert wrong_case.json()["found"] is False

        blank = test_client.post(
            "/api/private/reader/resolve-badge",
            json={"badge": "   "},
            headers=_headers(),
        )
        assert blank.status_code == 200
        assert blank.json()["found"] is False


# ============================================================================
# /scan — the reader ingest (guarded by READER_SECRET)
# ============================================================================

class TestScanAuth:
    def test_dark_returns_404_when_reader_secret_unset(self, test_client, test_db, monkeypatch):
        # READER_SECRET (not READER_RESOLVE_SECRET) guards /scan.
        monkeypatch.delenv("READER_SECRET", raising=False)
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)  # resolve set, scan still dark
        _make_employee(test_db, "1001", nfc_card_uid="AABBCCDD")

        response = test_client.post(
            "/api/private/reader/scan",
            json={"uid": "AABBCCDD", "reader": "reader-1"},
            headers={"X-Reader-Secret": READER_SECRET},
        )
        assert response.status_code == 404

    def test_wrong_secret_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_SECRET", READER_SECRET)
        response = test_client.post(
            "/api/private/reader/scan",
            json={"uid": "AABBCCDD", "reader": "reader-1"},
            headers={"X-Reader-Secret": "nope"},
        )
        assert response.status_code == 401

    def test_resolve_secret_does_not_authorize_scan(self, test_client, test_db, monkeypatch):
        # A caller holding only the app secret must not be able to forge taps.
        monkeypatch.setenv("READER_SECRET", READER_SECRET)
        response = test_client.post(
            "/api/private/reader/scan",
            json={"uid": "AABBCCDD", "reader": "reader-1"},
            headers={"X-Reader-Secret": SECRET},
        )
        assert response.status_code == 401


class TestScan:
    def test_unknown_uid_returns_403(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_SECRET", READER_SECRET)
        response = test_client.post(
            "/api/private/reader/scan",
            json={"uid": "NOSUCHUID", "reader": "reader-1"},
            headers={"X-Reader-Secret": READER_SECRET},
        )
        assert response.status_code == 403
        # Nothing buffered for an unauthorized tap.
        assert reader_module.consume_pending_tap("reader-1") is None

    def test_inactive_or_pending_employee_returns_403(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_SECRET", READER_SECRET)
        _make_employee(
            test_db, "1003", nfc_card_uid="CAFEBABE",
            is_active=False, pending_approval=True,
        )
        response = test_client.post(
            "/api/private/reader/scan",
            json={"uid": "CAFEBABE", "reader": "reader-1"},
            headers={"X-Reader-Secret": READER_SECRET},
        )
        assert response.status_code == 403

    def test_good_tap_stashes_and_returns_name(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_SECRET", READER_SECRET)
        _make_employee(test_db, "1001", display_name="สมชาย", nfc_card_uid="AABBCCDD")
        _grant(test_db, "1001", "payroll", "rooms")

        response = test_client.post(
            "/api/private/reader/scan",
            json={"uid": "aabbccdd", "reader": "reader-1"},  # lowercase → case-insensitive
            headers={"X-Reader-Secret": READER_SECRET},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "display_name": "สมชาย"}

        # The tap is buffered under the reader id with badge + grant keys.
        tap = reader_module.consume_pending_tap("reader-1")
        assert tap is not None
        assert tap["badge"] == "1001"
        assert sorted(tap["apps"]) == ["payroll", "rooms"]


# ============================================================================
# /claim — an app backend pairs a terminal to a reader (READER_RESOLVE_SECRET)
# ============================================================================

class TestClaim:
    def test_dark_returns_404_when_secret_unset(self, test_client, monkeypatch):
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        response = test_client.post(
            "/api/private/reader/claim",
            json={"reader_id": "reader-1", "app": "payroll"},
            headers=_headers(),
        )
        assert response.status_code == 404

    def test_bad_secret_returns_401(self, test_client, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/claim",
            json={"reader_id": "reader-1", "app": "payroll"},
            headers=_headers("wrong"),
        )
        assert response.status_code == 401

    def test_returns_claim_token(self, test_client, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/claim",
            json={"reader_id": "reader-1", "app": "payroll"},
            headers=_headers(),
        )
        assert response.status_code == 200
        token = response.json()["claim_token"]
        assert isinstance(token, str)
        assert len(token) == 64  # 32 random bytes as hex
        # The claim binds the token to (reader_id, app).
        claim = reader_module.lookup_claim(token)
        assert claim["reader_id"] == "reader-1"
        assert claim["app"] == "payroll"


# ============================================================================
# /wait — long-poll for the tap, receive a signed card assertion
# ============================================================================

def _scan(test_client, uid, reader):
    return test_client.post(
        "/api/private/reader/scan",
        json={"uid": uid, "reader": reader},
        headers={"X-Reader-Secret": READER_SECRET},
    )


def _claim(test_client, reader_id, app):
    resp = test_client.post(
        "/api/private/reader/claim",
        json={"reader_id": reader_id, "app": app},
        headers=_headers(),
    )
    return resp.json()["claim_token"]


def _wait(test_client, claim_token):
    return test_client.post(
        "/api/private/reader/wait",
        json={"claim_token": claim_token},
        headers=_headers(),
    )


class TestWaitAuth:
    def test_dark_returns_404_when_secret_unset(self, test_client, monkeypatch):
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        response = test_client.post(
            "/api/private/reader/wait",
            json={"claim_token": "whatever"},
            headers=_headers(),
        )
        assert response.status_code == 404

    def test_bad_secret_returns_401(self, test_client, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/wait",
            json={"claim_token": "whatever"},
            headers=_headers("wrong"),
        )
        assert response.status_code == 401

    def test_unknown_claim_returns_404(self, test_client, card_login_enabled):
        response = _wait(test_client, "no-such-claim")
        assert response.status_code == 404


class TestWait:
    def test_delivers_signed_assertion_for_authorized_tap(
        self, test_client, test_db, card_login_enabled
    ):
        _make_employee(test_db, "1001", display_name="สมชาย", nfc_card_uid="AABBCCDD")
        _grant(test_db, "1001", "payroll", "rooms")

        assert _scan(test_client, "AABBCCDD", "reader-1").status_code == 200
        token = _claim(test_client, "reader-1", "payroll")

        response = _wait(test_client, token)
        assert response.status_code == 200
        assertion = response.json()["assertion"]

        # Verify exactly as a consuming app must: signature via the HF ID public
        # key, issuer, audience == its own app grant key.
        claims = jwt.decode(
            assertion, _PUBLIC_PEM, algorithms=["RS256"],
            audience="payroll", issuer=_ISSUER,
        )
        assert claims["sub"] == "1001"
        assert claims["badge"] == "1001"
        assert claims["aud"] == "payroll"
        assert claims["email"] == "1001@emp.thehfhotel.org"
        assert claims["name"] == "สมชาย"
        assert "payroll" in claims["apps"]
        # The assertion is RS256 (resists alg-confusion downgrade).
        assert jwt.get_unverified_header(assertion)["alg"] == "RS256"

    def test_tap_without_app_grant_returns_403(
        self, test_client, test_db, card_login_enabled
    ):
        # Employee holds "rooms" but not the claimed "payroll" grant.
        _make_employee(test_db, "1002", nfc_card_uid="DEADBEEF")
        _grant(test_db, "1002", "rooms")

        assert _scan(test_client, "DEADBEEF", "reader-2").status_code == 200
        token = _claim(test_client, "reader-2", "payroll")

        response = _wait(test_client, token)
        assert response.status_code == 403
        assert response.json() == {"error": "not_authorized"}
        # Tap was consumed so it does not loop on the next poll.
        assert reader_module.consume_pending_tap("reader-2") is None

    def test_timeout_returns_204_when_no_tap(self, test_client, card_login_enabled):
        token = _claim(test_client, "reader-empty", "payroll")
        response = _wait(test_client, token)
        assert response.status_code == 204

    def test_assertion_delivered_only_once(
        self, test_client, test_db, card_login_enabled
    ):
        _make_employee(test_db, "1001", nfc_card_uid="AABBCCDD")
        _grant(test_db, "1001", "payroll")

        assert _scan(test_client, "AABBCCDD", "reader-1").status_code == 200
        token = _claim(test_client, "reader-1", "payroll")

        first = _wait(test_client, token)
        assert first.status_code == 200
        assert "assertion" in first.json()

        # Same claim re-polled after the tap was consumed → 204 (no replay).
        second = _wait(test_client, token)
        assert second.status_code == 204


# ============================================================================
# Employee self-service card-login (PUBLIC — no reader secret)
#   POST /api/public/reader/self-login/start  {reader_id} -> {login_ticket}
#   GET  /api/public/reader/self-login/wait?ticket=...    -> {token,...}|204|403|404
# Reader-secret-free (the browser is the employee's own terminal); the tap is
# resolved IN-PROCESS and turned into the SAME LINE-JWT self-service session the
# LINE-login path mints. Dark (404) until READER_SECRET is set.
# ============================================================================


@pytest.fixture
def self_login_env(monkeypatch):
    """Enable the public self-service card-login surface with a tiny long-poll
    budget so /self-login/wait timeout tests finish in a blink."""
    monkeypatch.setenv("READER_SECRET", READER_SECRET)
    monkeypatch.setenv("READER_WAIT_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("READER_WAIT_TICK_SECONDS", "0.02")
    yield


def _self_login_start(test_client, reader_id):
    return test_client.post(
        "/api/public/reader/self-login/start",
        json={"reader_id": reader_id},
    )


def _self_login_wait(test_client, ticket):
    return test_client.get(
        "/api/public/reader/self-login/wait",
        params={"ticket": ticket},
    )


def _decode_session(token):
    """Decode a minted self-service session exactly as verify-token does."""
    return jwt.decode(token, line_auth_service.jwt_secret, algorithms=["HS256"])


class TestSelfLoginDark:
    def test_start_dark_returns_404_when_reader_secret_unset(self, test_client, monkeypatch):
        # READER_SECRET (the reader ingest secret) gates the whole surface: with
        # no reader provisioned there is nothing to tap, so card-login is dark.
        monkeypatch.delenv("READER_SECRET", raising=False)
        response = _self_login_start(test_client, "reader-1")
        assert response.status_code == 404

    def test_wait_dark_returns_404_when_reader_secret_unset(self, test_client, monkeypatch):
        monkeypatch.delenv("READER_SECRET", raising=False)
        response = _self_login_wait(test_client, "whatever")
        assert response.status_code == 404


class TestSelfLoginStart:
    def test_returns_login_ticket_bound_to_reader(self, test_client, self_login_env):
        response = _self_login_start(test_client, "reader-1")
        assert response.status_code == 200
        ticket = response.json()["login_ticket"]
        assert isinstance(ticket, str)
        assert len(ticket) == 64  # 32 random bytes as hex
        # The ticket binds to the reader_id (and carries NO app grant).
        record = reader_module.lookup_self_login_ticket(ticket)
        assert record["reader_id"] == "reader-1"
        assert "app" not in record

    def test_blank_reader_id_returns_400(self, test_client, self_login_env):
        response = _self_login_start(test_client, "   ")
        assert response.status_code == 400


class TestSelfLoginWait:
    def test_unknown_ticket_returns_404(self, test_client, self_login_env):
        response = _self_login_wait(test_client, "no-such-ticket")
        assert response.status_code == 404

    def test_timeout_returns_204_when_no_tap(self, test_client, self_login_env):
        start = _self_login_start(test_client, "reader-empty")
        ticket = start.json()["login_ticket"]
        response = _self_login_wait(test_client, ticket)
        assert response.status_code == 204

    def test_delivers_self_service_session_for_active_employee(
        self, test_client, test_db, self_login_env
    ):
        # A fully-linked employee: card-login mints a session equivalent to the
        # LINE path's, including the real line_user_id (QR check-in keeps working).
        _make_employee(
            test_db, "1001", display_name="สมชาย", nfc_card_uid="AABBCCDD",
            line_user_id="U-line-1001", line_display_name="ชาย LINE",
        )

        assert _scan(test_client, "AABBCCDD", "reader-1").status_code == 200
        ticket = _self_login_start(test_client, "reader-1").json()["login_ticket"]

        response = _self_login_wait(test_client, ticket)
        assert response.status_code == 200
        data = response.json()
        assert data["employee_badge"] == "1001"

        # The token is the SAME LINE-JWT session the LINE-login path mints.
        claims = _decode_session(data["token"])
        assert claims["employee_badge"] == "1001"
        assert claims["line_user_id"] == "U-line-1001"
        # LINE display name preferred, mirroring create_jwt_token usage.
        assert claims["display_name"] == "ชาย LINE"

        # And it verifies through the exact endpoint the frontend calls.
        verify = test_client.post(
            "/api/public/auth/line/verify-token", json={"token": data["token"]}
        )
        assert verify.status_code == 200
        assert verify.json()["employee_badge"] == "1001"

    def test_active_employee_without_line_link_still_logs_in(
        self, test_client, test_db, self_login_env
    ):
        # Card-login is for viewing your own data — an employee who never linked
        # LINE (line_user_id is None) can still self-serve via their card.
        _make_employee(
            test_db, "1005", display_name="พนักงานใหม่", nfc_card_uid="FEEDFACE",
        )

        assert _scan(test_client, "FEEDFACE", "reader-5").status_code == 200
        ticket = _self_login_start(test_client, "reader-5").json()["login_ticket"]

        response = _self_login_wait(test_client, ticket)
        assert response.status_code == 200
        claims = _decode_session(response.json()["token"])
        assert claims["employee_badge"] == "1005"
        assert claims["line_user_id"] is None  # no LINE link, still a valid session
        assert claims["display_name"] == "พนักงานใหม่"

    def test_inactive_or_pending_employee_rejected(
        self, test_client, test_db, self_login_env
    ):
        # Defense-in-depth: /scan already blocks these, so stash a tap directly
        # to prove the mint step RE-verifies (e.g. deactivated between tap and
        # consume). No session is minted.
        _make_employee(
            test_db, "1003", display_name="ไม่ผ่าน", nfc_card_uid="CAFEBABE",
            is_active=False, pending_approval=True,
        )
        reader_module.stash_pending_tap(
            reader="reader-3", badge="1003", display_name="ไม่ผ่าน", apps=[]
        )
        ticket = _self_login_start(test_client, "reader-3").json()["login_ticket"]

        response = _self_login_wait(test_client, ticket)
        assert response.status_code == 403
        assert response.json() == {"error": "not_authorized"}
        # Tap was consumed so it does not loop on the next poll.
        assert reader_module.consume_pending_tap("reader-3") is None

    def test_unknown_badge_rejected(self, test_client, test_db, self_login_env):
        # A tap whose badge has no employee row (e.g. deleted) -> 403, no session.
        reader_module.stash_pending_tap(
            reader="reader-x", badge="9999", display_name="ghost", apps=[]
        )
        ticket = _self_login_start(test_client, "reader-x").json()["login_ticket"]

        response = _self_login_wait(test_client, ticket)
        assert response.status_code == 403
        assert response.json() == {"error": "not_authorized"}

    def test_session_delivered_only_once(self, test_client, test_db, self_login_env):
        _make_employee(test_db, "1001", nfc_card_uid="AABBCCDD")

        assert _scan(test_client, "AABBCCDD", "reader-1").status_code == 200
        ticket = _self_login_start(test_client, "reader-1").json()["login_ticket"]

        first = _self_login_wait(test_client, ticket)
        assert first.status_code == 200
        assert "token" in first.json()

        # Same ticket re-polled after the tap was consumed -> 204 (no replay).
        second = _self_login_wait(test_client, ticket)
        assert second.status_code == 204

    def test_app_consumer_and_self_terminal_share_one_tap(
        self, test_client, test_db, self_login_env, monkeypatch
    ):
        # One-terminal-per-reader assumption: a tap is delivered ONCE. If a
        # self-service terminal and an app-consumer both pair to the same reader,
        # whoever polls first consumes it; the other sees nothing. Here the
        # self-service wait wins, so a subsequent app /wait times out (204).
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(test_db, "1001", nfc_card_uid="AABBCCDD")
        _grant(test_db, "1001", "payroll")

        assert _scan(test_client, "AABBCCDD", "reader-1").status_code == 200
        self_ticket = _self_login_start(test_client, "reader-1").json()["login_ticket"]
        claim_token = _claim(test_client, "reader-1", "payroll")

        # Self-service consumes the single tap first.
        assert _self_login_wait(test_client, self_ticket).status_code == 200
        # The app-consumer's /wait now finds nothing -> 204 (no double delivery).
        assert _wait(test_client, claim_token).status_code == 204


# ============================================================================
# Kiosk LINE-scan elevation (Phase 3b — LINE as the card tap's equal)
#   POST /api/private/reader/elevate/start {app,label} -> {elevate_token}
#   GET  /api/public/reader/elevate/{ticket}           -> phone confirm page
#   (LINE callback) continue_elevate_after_line        -> parks the assertion
#   POST /api/private/reader/elevate/wait {elevate_token}
#        -> {assertion} | 204 pending | 403 not_authorized | 404 unknown
# The assertion is the IDENTICAL one-time RS256 card assertion /wait mints for
# a tap — one admission rule (grants ∋ app), whatever the Authenticator.
# ============================================================================


@pytest.fixture
def elevate_env(monkeypatch):
    """Enable the elevate surface with a tiny long-poll budget so
    /elevate/wait timeout tests finish in a blink instead of 25 seconds."""
    monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
    monkeypatch.setenv("HFID_SIGNING_KEY", _PRIVATE_PEM)
    monkeypatch.delenv("HFID_ISSUER", raising=False)
    monkeypatch.setenv("READER_WAIT_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("READER_WAIT_TICK_SECONDS", "0.02")
    oidc_service.reset_state()
    yield
    oidc_service.reset_state()


def _elevate_start(test_client, app="portal", label="office-1", secret=SECRET):
    return test_client.post(
        "/api/private/reader/elevate/start",
        json={"app": app, "label": label},
        headers=_headers(secret),
    )


def _elevate_wait(test_client, token, secret=SECRET):
    return test_client.post(
        "/api/private/reader/elevate/wait",
        json={"elevate_token": token},
        headers=_headers(secret),
    )


def _confirm_page(test_client, ticket):
    return test_client.get(f"/api/public/reader/elevate/{ticket}")


def _continue_elevate(ticket, line_user_id, db):
    return reader_module.continue_elevate_after_line(
        ticket_id=ticket, line_user_id=line_user_id, db=db
    )


class TestElevateStart:
    def test_dark_returns_404_when_secret_unset(self, test_client, monkeypatch):
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        assert _elevate_start(test_client).status_code == 404

    def test_wrong_secret_returns_401(self, test_client, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        assert _elevate_start(test_client, secret="wrong").status_code == 401

    def test_blank_app_returns_400(self, test_client, elevate_env):
        assert _elevate_start(test_client, app="   ").status_code == 400

    def test_returns_pending_ticket_bound_to_app_and_label(
        self, test_client, elevate_env
    ):
        response = _elevate_start(test_client)
        assert response.status_code == 200
        token = response.json()["elevate_token"]
        assert isinstance(token, str)
        assert len(token) == 64  # 32 random bytes as hex

        record = reader_module.lookup_elevate_ticket(token)
        assert record["app"] == "portal"
        assert record["label"] == "office-1"
        assert record["status"] == "pending"
        assert record["assertion"] is None

    def test_label_is_optional_and_length_capped(self, test_client, elevate_env):
        response = _elevate_start(test_client, label="x" * 500)
        record = reader_module.lookup_elevate_ticket(
            response.json()["elevate_token"]
        )
        assert len(record["label"]) == reader_module.ELEVATE_LABEL_MAX_CHARS

        response = test_client.post(
            "/api/private/reader/elevate/start",
            json={"app": "portal"},
            headers=_headers(),
        )
        record = reader_module.lookup_elevate_ticket(
            response.json()["elevate_token"]
        )
        assert record["label"] == ""


class TestElevateConfirmPage:
    def test_dark_returns_404_when_secret_unset(self, test_client, monkeypatch):
        # With no READER_RESOLVE_SECRET nothing can mint tickets — whole
        # phone-side surface is dark.
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        assert _confirm_page(test_client, "whatever").status_code == 404

    def test_unknown_ticket_gets_restart_page(self, test_client, elevate_env):
        response = _confirm_page(test_client, "no-such-ticket")
        assert response.status_code == 404
        assert "หมดอายุ" in response.text  # friendly HTML, not a bare JSON 404

    def test_pending_ticket_shows_line_button_and_label(
        self, test_client, elevate_env
    ):
        ticket = _elevate_start(test_client).json()["elevate_token"]
        response = _confirm_page(test_client, ticket)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        # The one action: the stock LINE login with the elevate continuation.
        assert (
            f"/api/public/auth/line/login?redirect=elevate%3A{ticket}"
            in response.text
        )
        # The person sees WHICH terminal is asking.
        assert "office-1" in response.text

    def test_resolved_ticket_gets_restart_page(
        self, test_client, test_db, elevate_env
    ):
        _make_employee(
            test_db, "1001", display_name="สมชาย", line_user_id="U-line-1001"
        )
        _grant(test_db, "1001", "portal")
        ticket = _elevate_start(test_client).json()["elevate_token"]
        _continue_elevate(ticket, "U-line-1001", test_db)

        assert _confirm_page(test_client, ticket).status_code == 404


class TestElevateContinue:
    def test_granted_employee_parks_the_card_assertion(
        self, test_client, test_db, elevate_env
    ):
        _make_employee(
            test_db, "1001", display_name="สมชาย", line_user_id="U-line-1001"
        )
        _grant(test_db, "1001", "portal", "payroll")
        ticket = _elevate_start(test_client).json()["elevate_token"]

        page = _continue_elevate(ticket, "U-line-1001", test_db)
        assert page.status_code == 200
        assert "เข้าสู่ระบบสำเร็จ".encode() in page.body

        response = _elevate_wait(test_client, ticket)
        assert response.status_code == 200
        assertion = response.json()["assertion"]

        # Verify exactly as the kiosk backend must — and exactly as it already
        # verifies CARD assertions: HF ID public key, issuer, aud = app grant.
        claims = jwt.decode(
            assertion, _PUBLIC_PEM, algorithms=["RS256"],
            audience="portal", issuer=_ISSUER,
        )
        assert claims["sub"] == "1001"
        assert claims["badge"] == "1001"
        assert claims["aud"] == "portal"
        assert claims["email"] == "1001@emp.thehfhotel.org"
        assert claims["name"] == "สมชาย"
        assert sorted(claims["apps"]) == ["payroll", "portal"]
        assert jwt.get_unverified_header(assertion)["alg"] == "RS256"

    def test_employee_without_grant_is_denied(
        self, test_client, test_db, elevate_env
    ):
        # Same admission rule as a card tap: no app grant → not_authorized.
        _make_employee(test_db, "1002", line_user_id="U-line-1002")
        _grant(test_db, "1002", "rooms")
        ticket = _elevate_start(test_client).json()["elevate_token"]

        page = _continue_elevate(ticket, "U-line-1002", test_db)
        assert page.status_code == 403

        response = _elevate_wait(test_client, ticket)
        assert response.status_code == 403
        assert response.json() == {"error": "not_authorized"}
        # Denial consumed the ticket — no replay.
        assert _elevate_wait(test_client, ticket).status_code == 404

    def test_inactive_or_pending_employee_leaves_ticket_pending(
        self, test_client, test_db, elevate_env
    ):
        # Card path parallel: /scan rejects these taps and the kiosk keeps
        # waiting — so here the ticket stays pending for the right person.
        _make_employee(
            test_db, "1003", line_user_id="U-line-1003",
            is_active=False, pending_approval=True,
        )
        ticket = _elevate_start(test_client).json()["elevate_token"]

        page = _continue_elevate(ticket, "U-line-1003", test_db)
        assert page.status_code == 403

        assert _elevate_wait(test_client, ticket).status_code == 204
        assert reader_module.lookup_elevate_ticket(ticket)["status"] == "pending"

    def test_unknown_line_user_redirected_to_onboarding(
        self, test_client, test_db, elevate_env
    ):
        ticket = _elevate_start(test_client).json()["elevate_token"]

        page = _continue_elevate(ticket, "U-never-seen", test_db)
        assert page.status_code == 302

        location = page.headers["location"]
        path, _, query = location.partition("?")
        assert path == "/qr-checkin/onboard"

        # The hand-off must CARRY the identity LINE just proved. A bare
        # /qr-checkin/onboard made the phone log into LINE a second time and,
        # on a device more than one person uses, let onboard.html adopt the
        # previous person's cached line_jwt_token — a wrong-identity write.
        params = urllib.parse.parse_qs(query)
        assert params["src"] == ["line"]
        claims = line_auth_service.verify_jwt_token(params["jwt"][0])
        assert claims["line_user_id"] == "U-never-seen"
        assert claims["employee_badge"] is None  # not an employee yet

        # Ticket stays pending — the QR is still usable by a real employee.
        assert _elevate_wait(test_client, ticket).status_code == 204

    def test_onboarding_handoff_carries_the_line_profile(
        self, test_client, test_db, elevate_env
    ):
        """The LINE display name/picture the callback already holds ride along
        in the hand-off token, so the onboarding form can prefill without a
        second LINE round-trip (public_onboarding reads them from the JWT)."""
        ticket = _elevate_start(test_client).json()["elevate_token"]

        page = reader_module.continue_elevate_after_line(
            ticket_id=ticket,
            line_user_id="U-never-seen",
            db=test_db,
            display_name="สมหญิง",
            picture_url="https://profile.line-scdn.net/abc",
        )
        query = page.headers["location"].partition("?")[2]
        token = urllib.parse.parse_qs(query)["jwt"][0]

        claims = line_auth_service.verify_jwt_token(token)
        assert claims["display_name"] == "สมหญิง"
        assert claims["picture_url"] == "https://profile.line-scdn.net/abc"

    def test_completion_is_one_time(self, test_client, test_db, elevate_env):
        _make_employee(test_db, "1001", line_user_id="U-line-1001")
        _grant(test_db, "1001", "portal")
        _make_employee(test_db, "1004", line_user_id="U-line-1004")
        _grant(test_db, "1004", "portal")
        ticket = _elevate_start(test_client).json()["elevate_token"]

        assert _continue_elevate(ticket, "U-line-1001", test_db).status_code == 200
        # A second completion against the same QR can never overwrite the first.
        second = _continue_elevate(ticket, "U-line-1004", test_db)
        assert second.status_code == 404

        claims = jwt.decode(
            _elevate_wait(test_client, ticket).json()["assertion"],
            _PUBLIC_PEM, algorithms=["RS256"],
            audience="portal", issuer=_ISSUER,
        )
        assert claims["sub"] == "1001"

    def test_unknown_ticket_gets_restart_page(self, test_db, elevate_env):
        page = _continue_elevate("no-such-ticket", "U-line-1001", test_db)
        assert page.status_code == 404


class TestElevateWait:
    def test_dark_returns_404_when_secret_unset(self, test_client, monkeypatch):
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        assert _elevate_wait(test_client, "whatever").status_code == 404

    def test_wrong_secret_returns_401(self, test_client, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        assert _elevate_wait(test_client, "whatever", secret="wrong").status_code == 401

    def test_unknown_ticket_returns_404(self, test_client, elevate_env):
        assert _elevate_wait(test_client, "no-such-ticket").status_code == 404

    def test_pending_ticket_times_out_with_204(self, test_client, elevate_env):
        ticket = _elevate_start(test_client).json()["elevate_token"]
        assert _elevate_wait(test_client, ticket).status_code == 204
        # Still pending afterwards — the kiosk re-polls with the same token.
        assert reader_module.lookup_elevate_ticket(ticket)["status"] == "pending"


class TestElevateCallbackHook:
    def test_line_callback_routes_elevate_hint_to_continuation(
        self, test_client, test_db, elevate_env, monkeypatch
    ):
        """End-to-end through the REAL LINE callback endpoint: the
        ``elevate:<ticket>`` redirect hint must land in
        continue_elevate_after_line and park a waitable assertion."""
        _make_employee(
            test_db, "1001", display_name="สมชาย", line_user_id="U-line-1001"
        )
        _grant(test_db, "1001", "portal")
        ticket = _elevate_start(test_client).json()["elevate_token"]

        monkeypatch.setattr(
            line_auth_service, "validate_state",
            lambda state: (True, f"elevate:{ticket}"),
        )
        monkeypatch.setattr(
            line_auth_service, "exchange_code_for_token",
            lambda code: {"access_token": "stub-access-token"},
        )
        monkeypatch.setattr(
            line_auth_service, "get_user_profile",
            lambda token: {
                "userId": "U-line-1001",
                "displayName": "ชาย LINE",
                "pictureUrl": "",
            },
        )

        response = test_client.get(
            "/api/public/auth/line/callback",
            params={"code": "stub-code", "state": "stub-state"},
        )
        assert response.status_code == 200
        assert "เข้าสู่ระบบสำเร็จ" in response.text

        wait = _elevate_wait(test_client, ticket)
        assert wait.status_code == 200
        claims = jwt.decode(
            wait.json()["assertion"], _PUBLIC_PEM, algorithms=["RS256"],
            audience="portal", issuer=_ISSUER,
        )
        assert claims["sub"] == "1001"


# ===========================================================================
# The secret is checked BEFORE the body — every endpoint on the surface
# ===========================================================================
#
# Regression pin for the 2026-09 fix (see ``_secret_guard`` in app/api/reader.py).
# The guard used to be the first STATEMENT of each handler, which meant FastAPI
# had already validated the body by the time it ran: an unauthenticated caller
# posting a wrong-shaped body got 422 with a full pydantic error list — every
# field name, its type, and which keys were missing — instead of 401. That is a
# schema disclosure on a server-to-server surface, and it affected ALL EIGHT
# endpoints, /hk-escalate included (its existing
# ``test_auth_is_checked_before_the_body`` only ever sent a structurally VALID
# body with bad VALUES, so it never caught this).
#
# The guard is now a route-level ``dependencies=[...]`` entry, which FastAPI
# solves before body validation. These tests pin that ordering per endpoint, so
# a future endpoint added with the old in-handler pattern fails here.

#: (path, the env var whose secret guards it). /scan is guarded by the distinct
#: reader↔central READER_SECRET; everything else by READER_RESOLVE_SECRET.
SECRET_GUARDED_ENDPOINTS = [
    ("/api/private/reader/resolve", "READER_RESOLVE_SECRET"),
    ("/api/private/reader/resolve-badge", "READER_RESOLVE_SECRET"),
    ("/api/private/reader/hk-escalate", "READER_RESOLVE_SECRET"),
    ("/api/private/reader/claim", "READER_RESOLVE_SECRET"),
    ("/api/private/reader/wait", "READER_RESOLVE_SECRET"),
    ("/api/private/reader/elevate/start", "READER_RESOLVE_SECRET"),
    ("/api/private/reader/elevate/wait", "READER_RESOLVE_SECRET"),
    ("/api/private/reader/scan", "READER_SECRET"),
]

#: Structurally valid JSON of entirely the wrong shape: no field any of these
#: endpoints declares. Every one of them 422s on it once the caller is known.
MALFORMED_BODY = {"not_a_field_any_endpoint_declares": "x"}


def _correct_secret_for(env_var):
    return READER_SECRET if env_var == "READER_SECRET" else SECRET


@pytest.mark.parametrize("path,env_var", SECRET_GUARDED_ENDPOINTS)
class TestSecretIsCheckedBeforeBody:
    def test_wrong_secret_with_malformed_body_returns_401_not_422(
        self, test_client, test_db, card_login_enabled, path, env_var
    ):
        """A caller with the WRONG secret learns nothing about the schema."""
        response = test_client.post(
            path, json=MALFORMED_BODY, headers=_headers("not-the-secret")
        )
        assert response.status_code == 401
        # And the 401 body names no field of the rejected request.
        assert "not_a_field_any_endpoint_declares" not in response.text

    def test_missing_header_with_malformed_body_returns_401_not_422(
        self, test_client, test_db, card_login_enabled, path, env_var
    ):
        """Same for a caller that presents no secret at all."""
        response = test_client.post(path, json=MALFORMED_BODY)
        assert response.status_code == 401
        assert "not_a_field_any_endpoint_declares" not in response.text

    def test_right_secret_with_malformed_body_still_returns_422(
        self, test_client, test_db, card_login_enabled, path, env_var
    ):
        """Body validation is preempted, not disabled: an AUTHENTICATED caller
        still gets the full 422 it needs to fix its request."""
        response = test_client.post(
            path, json=MALFORMED_BODY, headers=_headers(_correct_secret_for(env_var))
        )
        assert response.status_code == 422

    def test_dark_beats_malformed_body_too(
        self, test_client, test_db, monkeypatch, path, env_var
    ):
        """The dark-when-unset posture is unchanged and also outranks the body:
        with the guarding secret unset the route is 404, indistinguishable from
        one that does not exist, whatever the caller posts."""
        monkeypatch.delenv(env_var, raising=False)
        response = test_client.post(
            path, json=MALFORMED_BODY, headers=_headers("anything")
        )
        assert response.status_code == 404
