"""Unit tests for the card-reader identity API (app.api.reader).

Covers HF ID as the central card-login authority:
  * /resolve — direct UID -> employee lookup (app↔central).
  * /scan    — the ESP32 reader ingests a tap (reader↔central).
  * /claim   — an app backend pairs a terminal to a reader (app↔central).
  * /wait    — an app backend long-polls for the tap and receives a signed
               one-time card assertion (an RS256 OIDC id_token).
All server-to-server, guarded by the ``X-Reader-Secret`` shared secret.
"""
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
        _make_employee(test_db, "1001", display_name="สมชาย", nfc_card_uid="AABBCCDD")
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
