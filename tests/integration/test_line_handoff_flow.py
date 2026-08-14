"""Integration tests for the same-browser LINE completion hand-off.

Drives the real endpoints end to end with LINE mocked (no network):

    /oidc/authorize
      -> /api/public/auth/line/login   (mobile, non-LINE browser, Access flow)
         -> the polling page + the HttpOnly binding cookie
      -> LINE (mocked) -> /api/public/auth/line/callback
         -> the identity is parked; LINE's browser is told to go back
      -> /api/public/auth/line/handoff/wait  (the ORIGINAL tab, with cookie)
         -> the Cloudflare Access callback URL, carrying a fresh code

The point of the whole exercise is that the last step happens in the browser
that started the flow — the one holding the Access session — instead of in
LINE's in-app browser, which is a different cookie jar. So the security tests
here are not decoration: they are the feature.

Covered: happy path, single use, expiry, an UNRELATED poller (the load-bearing
one), login fixation, the two-poller race, the timeout/retry path, the
long-poll's 204-and-re-poll contract, and — with the hand-off switched ON — the
four paths that must not move: rich menu inside LINE, desktop, the public-path
flows, and kiosk elevate.
"""

import time
import urllib.parse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.main_unified import app
from app.models.models import Employee, EmployeeAppGrant
from app.services import line_handoff_store, oidc_service
from app.services.line_auth_service import line_auth_service


_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()

_CLIENT_ID = "cf-access-client"
_CLIENT_SECRET = "confidential-client-secret"
_REDIRECT_URI = oidc_service.DEFAULT_REDIRECT_URI
_LINE_USER = "Uhandoff0001"

UA_MOBILE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)
UA_LINE_IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Line/13.5.0"
)
UA_DESKTOP_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)

_WAIT_PATH = "/api/public/auth/line/handoff/wait"
_LOGIN_PATH = "/api/public/auth/line/login"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def _clean_state():
    """Both stores plus LINE's CSRF state map, so tests never see each other's
    tickets (several helpers below find "the" pending hand-off state)."""
    line_handoff_store.reset_state()
    oidc_service.reset_state()
    line_auth_service._state_storage.clear()
    yield
    line_handoff_store.reset_state()
    oidc_service.reset_state()
    line_auth_service._state_storage.clear()


@pytest.fixture
def handoff_env(monkeypatch):
    """HF ID configured, the hand-off switched ON, tiny long-poll budget."""
    monkeypatch.setenv("HFID_SIGNING_KEY", _PRIVATE_PEM)
    monkeypatch.setenv("HFID_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("HFID_CLIENT_SECRET", _CLIENT_SECRET)
    monkeypatch.delenv("HFID_ISSUER", raising=False)
    monkeypatch.delenv("HFID_REDIRECT_URIS", raising=False)
    monkeypatch.setenv("LINE_SAME_BROWSER_HANDOFF", "true")
    monkeypatch.setenv("LINE_HANDOFF_WAIT_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("LINE_HANDOFF_WAIT_TICK_SECONDS", "0.02")
    monkeypatch.delenv("LINE_HANDOFF_TICKET_TTL_SECONDS", raising=False)
    # LINE creds are unset in the test env; /login 500s without a channel id.
    monkeypatch.setattr(line_auth_service, "channel_id", "test_channel_id")
    yield


@pytest.fixture
def line_mocked(monkeypatch):
    """Stub LINE's two blocking round trips (NO NETWORK IN TESTS)."""
    monkeypatch.setattr(
        line_auth_service, "exchange_code_for_token",
        lambda code: {"access_token": "line-access-token"},
    )
    monkeypatch.setattr(
        line_auth_service, "get_user_profile",
        lambda access_token: {
            "userId": _LINE_USER,
            "displayName": "สมหญิง",
            "pictureUrl": "",
        },
    )
    yield


def _seed_employee(session, *, badge="Q900", line_user_id=_LINE_USER,
                   is_active=True, pending_approval=False, apps=("rooms",)):
    employee = Employee(
        badge_number=badge,
        display_name="พนักงาน สมหญิง",
        is_active=is_active,
        pending_approval=pending_approval,
        email=f"{badge.lower()}@emp.thehfhotel.org",
        line_user_id=line_user_id,
        join_source="self_onboard",
    )
    session.add(employee)
    for app_id in apps:
        session.add(EmployeeAppGrant(employee_badge_number=badge, app_id=app_id))
    session.commit()
    return employee


# ============================================================================
# Flow helpers
# ============================================================================

def _authorize(client, *, state="cf-state-1"):
    """Cloudflare Access's /oidc/authorize call; returns the /login URL."""
    params = {
        "client_id": _CLIENT_ID,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": "nonce-abc",
    }
    response = client.get(
        "/oidc/authorize?" + urllib.parse.urlencode(params), follow_redirects=False
    )
    assert response.status_code == 302
    return response.headers["location"]


def _start_handoff(client, *, login_url, user_agent=UA_MOBILE_SAFARI, headers=None):
    """The original tab hits /login and receives the polling page + cookie."""
    request_headers = {"User-Agent": user_agent}
    if headers:
        request_headers.update(headers)
    return client.get(login_url, headers=request_headers, follow_redirects=False)


def _pending_handoff_states():
    """Every LINE ``state`` whose server-side hint is a hand-off ticket.

    Reaching into line_auth_service's state store is the ONLY way a test can
    learn the ticket id — which is itself the point being demonstrated: the id
    never reaches the browser, so there is nothing in the response to read it
    out of.
    """
    return {
        state: hint[len("handoff:"):]
        for state, (_ts, hint) in line_auth_service._state_storage.items()
        if (hint or "").startswith("handoff:")
    }


def _pending_handoff_state(*, ignoring=()):
    """The single pending hand-off, as ``(state, ticket_id)``."""
    pending = {
        state: ticket
        for state, ticket in _pending_handoff_states().items()
        if state not in ignoring
    }
    assert len(pending) == 1, f"expected exactly one pending hand-off, got {len(pending)}"
    state, ticket_id = next(iter(pending.items()))
    return state, ticket_id


def _drive_line_callback(client, state, *, headers=None):
    """LINE's in-app browser returning to our callback."""
    return client.get(
        f"/api/public/auth/line/callback?code=line-code&state={state}",
        headers=headers or {},
        follow_redirects=False,
    )


def _fresh_browser(base_url="http://testserver"):
    """A second, cookie-less client on the same app — i.e. another browser.

    The shared ``test_client`` fixture has already installed the get_db and CF
    Access dependency overrides on this same ``app`` object, so a bare
    TestClient here picks them up.
    """
    return TestClient(app, base_url=base_url)


# ============================================================================
# Happy path
# ============================================================================

class TestHandoffHappyPath:
    def test_login_serves_the_polling_page_and_binds_a_cookie(
        self, test_client, test_db, handoff_env
    ):
        login_url = _authorize(test_client)
        response = _start_handoff(test_client, login_url=login_url)

        assert response.status_code == 200
        # The waiting state, in Thai, and the retry path already in the markup.
        assert "รอการยืนยันจาก LINE" in response.text
        assert "ลองใหม่อีกครั้ง" in response.text
        # Not the auto-redirect, and not the interim guidance page.
        assert 'http-equiv="refresh"' not in response.text
        assert "เปิดจากแอป LINE" not in response.text

        cookie = response.cookies.get(line_handoff_store.COOKIE_NAME)
        assert cookie
        set_cookie = response.headers["set-cookie"]
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie.replace("samesite", "SameSite")
        assert f"Path={line_handoff_store.COOKIE_PATH}" in set_cookie

    def test_auto_login_is_on_and_no_qr_is_forced(
        self, test_client, test_db, handoff_env
    ):
        """The two rejected parameter fixes, pinned as still rejected. The
        hand-off works by KEEPING auto login (so LINE finishes in its own
        browser) — it must not send disable_auto_login, and must never put a QR
        on a phone."""
        login_url = _authorize(test_client)
        response = _start_handoff(test_client, login_url=login_url)

        assert "access.line.me/oauth2/v2.1/authorize" in response.text
        assert "disable_auto_login" not in response.text
        assert "initial_amr_display" not in response.text

    def test_ticket_id_never_reaches_the_browser(
        self, test_client, test_db, handoff_env
    ):
        """Threat 1, at the wire level: the half of the secret that travels the
        LINE round trip must not be in the page, the URL or any header other
        than the HttpOnly cookie."""
        login_url = _authorize(test_client)
        response = _start_handoff(test_client, login_url=login_url)
        _state, ticket_id = _pending_handoff_state()

        assert ticket_id not in response.text
        assert ticket_id not in str(response.url)
        for name, value in response.headers.items():
            if name.lower() == "set-cookie":
                continue
            assert ticket_id not in value, name

    def test_full_flow_completes_in_the_original_tab(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        _seed_employee(test_db)
        login_url = _authorize(test_client, state="cf-state-xyz")
        _start_handoff(test_client, login_url=login_url)
        state, _ticket_id = _pending_handoff_state()

        # LINE's in-app browser finishes and is told to go back.
        callback = _drive_line_callback(test_client, state)
        assert callback.status_code == 200
        assert "ยืนยันตัวตนสำเร็จ" in callback.text
        # Nothing that could become a session is handed to LINE's browser.
        assert "code=" not in callback.text
        assert callback.headers.get("location") is None

        # The original tab collects it.
        wait = test_client.get(_WAIT_PATH)
        assert wait.status_code == 200
        body = wait.json()
        assert body["status"] == "ready"
        completion = body["completion_url"]
        assert completion.startswith(_REDIRECT_URI)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(completion).query)
        assert query["state"] == ["cf-state-xyz"]
        assert query["code"]

    def test_the_delivered_code_is_redeemable(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        """End of the line: the code the original tab receives really does buy
        the id_token Cloudflare Access is waiting for."""
        _seed_employee(test_db)
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)
        state, _ = _pending_handoff_state()
        _drive_line_callback(test_client, state)

        completion = test_client.get(_WAIT_PATH).json()["completion_url"]
        code = urllib.parse.parse_qs(
            urllib.parse.urlparse(completion).query
        )["code"][0]

        token = test_client.post(
            "/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _REDIRECT_URI,
                "client_id": _CLIENT_ID,
                "client_secret": _CLIENT_SECRET,
            },
        )
        assert token.status_code == 200
        assert token.json()["id_token"]

    def test_unregistered_line_user_is_sent_to_onboarding_in_the_original_tab(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        """The onboarding hand-off carries a bearer JWT in its URL, so it must
        be delivered to the originating browser, not left in LINE's."""
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)
        state, _ = _pending_handoff_state()
        _drive_line_callback(test_client, state)

        body = test_client.get(_WAIT_PATH).json()
        assert body["status"] == "ready"
        assert body["completion_url"].startswith("/qr-checkin/onboard?")
        assert "jwt=" in body["completion_url"]

    def test_pending_employee_surfaces_as_a_thai_failure_not_a_session(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        _seed_employee(test_db, pending_approval=True)
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)
        state, _ = _pending_handoff_state()
        _drive_line_callback(test_client, state)

        body = test_client.get(_WAIT_PATH).json()
        assert body["status"] == "failed"
        assert body["reason"] == "not_ready"
        assert "completion_url" not in body


# ============================================================================
# THE LOAD-BEARING SECURITY TEST — an unrelated poller gets nothing
# ============================================================================

class TestUnrelatedPollerCannotObtainTheSession:
    """The invariant, stated as a test:

        completing a LINE login must only ever yield a session to the browser
        that STARTED that specific flow.

    These are not happy-path variants with a wrong string. Each one gives the
    attacker the most it could realistically have — a completed, ready-to-claim
    ticket; the ticket id itself; a poll timed to race the real owner — and
    still requires them to come away empty while the real owner succeeds.
    """

    def _drive_to_ready(self, test_client, test_db):
        _seed_employee(test_db)
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)
        state, ticket_id = _pending_handoff_state()
        _drive_line_callback(test_client, state)
        return ticket_id

    def test_a_browser_with_no_cookie_gets_nothing(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        self._drive_to_ready(test_client, test_db)

        attacker = _fresh_browser()
        response = attacker.get(_WAIT_PATH)
        assert response.status_code == 404
        assert "completion_url" not in response.text

        # The real owner is unharmed and still collects the session.
        assert test_client.get(_WAIT_PATH).json()["status"] == "ready"

    def test_knowing_the_ticket_id_does_not_help(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        """The shoulder-surf / leaked-log threat, end to end. The attacker has
        the exact ticket id and tries every way of presenting it."""
        ticket_id = self._drive_to_ready(test_client, test_db)

        # As a query parameter, in case a future refactor ever adds one.
        attacker = _fresh_browser()
        for params in ({"ticket": ticket_id}, {"ticket_id": ticket_id}):
            response = attacker.get(_WAIT_PATH, params=params)
            assert response.status_code == 404, params
            assert "completion_url" not in response.text, params

        # And as the cookie, with the holder secret missing or invented.
        for cookie in (ticket_id, f"{ticket_id}.", f"{ticket_id}.guessed-secret"):
            attacker = _fresh_browser()
            attacker.cookies.set(line_handoff_store.COOKIE_NAME, cookie)
            response = attacker.get(_WAIT_PATH)
            assert response.status_code == 404, cookie
            assert "completion_url" not in response.text, cookie

        assert test_client.get(_WAIT_PATH).json()["status"] == "ready"

    def test_a_forged_cookie_gets_nothing(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        self._drive_to_ready(test_client, test_db)

        for forged in (".", "a.b", "x" * 64, f"{'y' * 32}.{'z' * 43}"):
            attacker = _fresh_browser()
            attacker.cookies.set(line_handoff_store.COOKIE_NAME, forged)
            response = attacker.get(_WAIT_PATH)
            assert response.status_code == 404, forged

    def test_a_second_users_cookie_cannot_claim_this_flow(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        """Two real, concurrent hand-offs. Browser B holds a perfectly valid
        cookie — for its OWN ticket — and must not be able to collect A's."""
        _seed_employee(test_db)

        # Browser B starts its own flow first and keeps its cookie.
        browser_b = _fresh_browser()
        b_login = _authorize(browser_b, state="cf-state-b")
        _start_handoff(browser_b, login_url=b_login)
        b_states = set(_pending_handoff_states())

        # Browser A starts, completes, and is ready to collect.
        a_login = _authorize(test_client, state="cf-state-a")
        _start_handoff(test_client, login_url=a_login)
        a_state, _a_ticket = _pending_handoff_state(ignoring=b_states)
        _drive_line_callback(test_client, a_state)

        # B polls with its own valid cookie and gets nothing but its own wait.
        b_response = browser_b.get(_WAIT_PATH)
        assert b_response.status_code == 204  # B's own ticket is still pending

        a_response = test_client.get(_WAIT_PATH)
        assert a_response.status_code == 200
        assert a_response.json()["status"] == "ready"

    def test_a_forged_handoff_hint_is_refused_at_login(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        """Fixation run backwards. A hand-off hint is only ever synthesized
        server-side, so a caller supplying one is trying to aim a LINE login at
        someone else's waiting tab. It must never get as far as the callback."""
        ticket_id = self._drive_to_ready(test_client, test_db)

        attacker = _fresh_browser()
        response = attacker.get(
            f"{_LOGIN_PATH}?redirect=handoff%3A{ticket_id}",
            headers={"User-Agent": UA_MOBILE_SAFARI},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "access.line.me" not in response.text

        # And the real owner's completion is still theirs.
        assert test_client.get(_WAIT_PATH).json()["status"] == "ready"

    def test_the_line_side_page_hands_out_no_session_material(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        """The LINE leg runs in the cookie jar we must never give a session to.
        Its response must be a dead end: no redirect, no code, no token."""
        _seed_employee(test_db)
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)
        state, _ = _pending_handoff_state()

        callback = _drive_line_callback(test_client, state)
        assert callback.status_code == 200
        assert "location" not in {k.lower() for k in callback.headers}
        assert _REDIRECT_URI not in callback.text
        assert "jwt=" not in callback.text
        assert "set-cookie" not in {k.lower() for k in callback.headers}


# ============================================================================
# Fixation
# ============================================================================

class TestFixation:
    """An attacker starts a flow on their own device, then phishes a victim
    into completing a LINE login onto the attacker's ticket. The attacker holds
    the cookie for their own ticket, so the cookie alone cannot stop this — the
    LINE leg is bound to the client IP the ticket was started from."""

    @pytest.fixture
    def proxied(self, monkeypatch):
        """Behind the proxy, so CF-Connecting-IP is the client identity — and
        so the binding cookie is Secure, hence the https test clients."""
        monkeypatch.setenv("BEHIND_PROXY", "true")
        yield
        monkeypatch.delenv("BEHIND_PROXY", raising=False)

    def test_victim_completion_into_a_planted_ticket_yields_nothing(
        self, test_client, test_db, handoff_env, line_mocked, proxied
    ):
        _seed_employee(test_db)

        attacker = _fresh_browser("https://testserver")
        login_url = _authorize(attacker, state="cf-state-attacker")
        started = _start_handoff(
            attacker, login_url=login_url,
            headers={"CF-Connecting-IP": "198.51.100.7"},
        )
        assert started.cookies.get(line_handoff_store.COOKIE_NAME)
        state, _ticket = _pending_handoff_state()

        # The victim, on their own network, completes the phished LINE URL.
        victim = _fresh_browser("https://testserver")
        callback = _drive_line_callback(
            victim, state, headers={"CF-Connecting-IP": "203.0.113.99"},
        )
        assert callback.status_code == 403
        assert "เริ่มใหม่จากเบราว์เซอร์ของคุณ" in callback.text

        # The attacker's tab polls and finds nothing parked.
        response = attacker.get(_WAIT_PATH)
        assert response.status_code == 204
        assert "completion_url" not in response.text

    def test_same_device_completion_still_works_behind_the_proxy(
        self, test_client, test_db, handoff_env, line_mocked, proxied
    ):
        """The real flow is same-phone: Safari and LINE's in-app browser leave
        by the same egress IP, so the binding must not cost the honest user
        anything."""
        _seed_employee(test_db)

        browser = _fresh_browser("https://testserver")
        login_url = _authorize(browser, state="cf-state-real")
        _start_handoff(
            browser, login_url=login_url,
            headers={"CF-Connecting-IP": "198.51.100.7"},
        )
        state, _ = _pending_handoff_state()
        _drive_line_callback(
            browser, state, headers={"CF-Connecting-IP": "198.51.100.7"},
        )

        response = browser.get(_WAIT_PATH)
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


# ============================================================================
# Single use, race, expiry, timeout
# ============================================================================

class TestSingleUseAndRace:
    def test_the_completion_is_delivered_exactly_once(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        _seed_employee(test_db)
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)
        state, _ = _pending_handoff_state()
        _drive_line_callback(test_client, state)

        first = test_client.get(_WAIT_PATH)
        second = test_client.get(_WAIT_PATH)
        assert first.status_code == 200
        # Same cookie, same browser, second tab: the ticket is gone.
        assert second.status_code == 404

    def test_a_second_line_completion_cannot_reopen_a_used_ticket(
        self, test_client, test_db, handoff_env, line_mocked
    ):
        _seed_employee(test_db)
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)
        state, ticket_id = _pending_handoff_state()
        _drive_line_callback(test_client, state)
        assert test_client.get(_WAIT_PATH).status_code == 200

        # Replay the LINE leg against the same ticket.
        line_auth_service._state_storage["replayed"] = (
            time.time(), f"handoff:{ticket_id}"
        )
        replay = _drive_line_callback(test_client, "replayed")
        assert replay.status_code == 400
        assert "หมดอายุ" in replay.text


class TestTimeoutAndAbandonment:
    def test_pending_wait_times_out_with_204_and_the_ticket_survives(
        self, test_client, test_db, handoff_env
    ):
        """The long-poll hands the connection back rather than holding it, and
        the browser re-polls with the same cookie — reader.py's contract."""
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)

        first = test_client.get(_WAIT_PATH)
        assert first.status_code == 204
        second = test_client.get(_WAIT_PATH)
        assert second.status_code == 204

    def test_the_wait_does_not_park_a_connection_for_a_stranger(
        self, test_client, test_db, handoff_env, monkeypatch
    ):
        """A caller with no cookie is answered immediately, not parked for the
        whole slice — otherwise the long-poll is a connection sink."""
        monkeypatch.setenv("LINE_HANDOFF_WAIT_TIMEOUT_SECONDS", "5")
        _authorize(test_client)

        started = time.monotonic()
        response = _fresh_browser().get(_WAIT_PATH)
        elapsed = time.monotonic() - started

        assert response.status_code == 404
        assert elapsed < 1.0

    def test_an_abandoned_handoff_expires_into_the_retry_path(
        self, test_client, test_db, handoff_env, monkeypatch
    ):
        """The maid who wanders off. Once the budget is spent the ticket is
        gone and the wait answers 404 — the signal the polling page turns into
        its Thai retry panel."""
        monkeypatch.setenv("LINE_HANDOFF_TICKET_TTL_SECONDS", "0.1")
        login_url = _authorize(test_client)
        page = _start_handoff(test_client, login_url=login_url)

        # The retry panel and its restart button ship with the page, so the
        # browser never has to reach the server to render the way out.
        assert "หมดเวลารอ" in page.text
        assert "ลองใหม่อีกครั้ง" in page.text
        assert '"retryUrl"' in page.text
        assert "เปิดแอป LINE" in page.text or "เปิดห้องแชท" in page.text

        time.sleep(0.15)
        assert test_client.get(_WAIT_PATH).status_code == 404

    def test_the_retry_button_restarts_the_same_login(
        self, test_client, test_db, handoff_env
    ):
        """Restarting must reuse the still-valid inner OIDC request rather than
        dead-ending, so the user is not bounced back to Cloudflare."""
        login_url = _authorize(test_client)
        page = _start_handoff(test_client, login_url=login_url)
        assert urllib.parse.quote(login_url, safe="/?=:&") in page.text or (
            login_url in page.text
        )

        again = _start_handoff(test_client, login_url=login_url)
        assert again.status_code == 200
        assert again.cookies.get(line_handoff_store.COOKIE_NAME)

    def test_the_page_carries_a_bounded_budget(
        self, test_client, test_db, handoff_env
    ):
        """No infinite spinner: the page stops on its own."""
        login_url = _authorize(test_client)
        page = _start_handoff(test_client, login_url=login_url)
        assert '"budgetMs":' in page.text
        budget = int(page.text.split('"budgetMs":')[1].split("}")[0].strip())
        assert 0 < budget <= line_handoff_store.HANDOFF_TICKET_TTL_SECONDS * 1000


class TestCeilings:
    def test_over_the_waiter_ceiling_the_answer_is_a_retry_not_a_failure(
        self, test_client, test_db, handoff_env, monkeypatch
    ):
        monkeypatch.setattr(line_handoff_store, "MAX_CONCURRENT_WAITERS", 0)
        login_url = _authorize(test_client)
        _start_handoff(test_client, login_url=login_url)

        response = test_client.get(_WAIT_PATH)
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "2"

    def test_a_full_ticket_store_falls_back_to_the_guidance_page(
        self, test_client, test_db, handoff_env, monkeypatch
    ):
        """Degrade to today's proven behaviour, never to an error page."""
        monkeypatch.setattr(line_handoff_store, "MAX_TICKETS", 0)
        login_url = _authorize(test_client)
        response = _start_handoff(test_client, login_url=login_url)

        assert response.status_code == 200
        assert "เปิดจากแอป LINE" in response.text
        # And the fallback keeps the Safari cookie-jar guard it always had.
        assert "disable_auto_login=true" in response.text
        assert response.cookies.get(line_handoff_store.COOKIE_NAME) is None


# ============================================================================
# Dark by default, and the paths that must not move
# ============================================================================

class TestDarkByDefault:
    @pytest.fixture
    def handoff_off(self, monkeypatch):
        monkeypatch.setenv("HFID_SIGNING_KEY", _PRIVATE_PEM)
        monkeypatch.setenv("HFID_CLIENT_ID", _CLIENT_ID)
        monkeypatch.setenv("HFID_CLIENT_SECRET", _CLIENT_SECRET)
        monkeypatch.delenv("LINE_SAME_BROWSER_HANDOFF", raising=False)
        monkeypatch.setattr(line_auth_service, "channel_id", "test_channel_id")
        yield

    def test_wait_endpoint_is_404_while_the_feature_is_off(
        self, test_client, test_db, handoff_off
    ):
        assert test_client.get(_WAIT_PATH).status_code == 404

    def test_the_guidance_interstitial_is_untouched_while_off(
        self, test_client, test_db, handoff_off
    ):
        login_url = _authorize(test_client)
        response = _start_handoff(test_client, login_url=login_url)

        assert "เปิดจากแอป LINE" in response.text
        assert "disable_auto_login=true" in response.text
        assert response.cookies.get(line_handoff_store.COOKIE_NAME) is None


class TestTheFourWorkingPathsDoNotMove:
    """Requirement 6, tested with the hand-off switched ON — a scope test that
    only runs with the feature off would prove nothing."""

    def _login(self, client, *, redirect, user_agent):
        return client.get(
            f"{_LOGIN_PATH}?redirect={redirect}",
            headers={"User-Agent": user_agent},
            follow_redirects=False,
        )

    def test_rich_menu_inside_line_still_auto_redirects(
        self, test_client, test_db, handoff_env
    ):
        response = self._login(
            test_client, redirect="oidc%3Aticket123", user_agent=UA_LINE_IOS
        )
        assert 'http-equiv="refresh"' in response.text
        assert "disable_auto_login" not in response.text
        assert response.cookies.get(line_handoff_store.COOKIE_NAME) is None
        assert "รอการยืนยันจาก LINE" not in response.text

    def test_desktop_still_gets_the_qr_escape(
        self, test_client, test_db, handoff_env
    ):
        response = self._login(
            test_client, redirect="oidc%3Aticket123", user_agent=UA_DESKTOP_CHROME
        )
        assert 'http-equiv="refresh"' in response.text
        assert "initial_amr_display=lineqr" in response.text
        assert "disable_auto_login=true" in response.text
        assert response.cookies.get(line_handoff_store.COOKIE_NAME) is None

    def test_public_path_mobile_flows_still_auto_redirect(
        self, test_client, test_db, handoff_env
    ):
        for redirect in ("qr-scan-callback", "mobile-checkin", "onboard"):
            response = self._login(
                test_client, redirect=redirect, user_agent=UA_MOBILE_SAFARI
            )
            assert 'http-equiv="refresh"' in response.text, redirect
            assert "disable_auto_login" not in response.text, redirect
            assert response.cookies.get(line_handoff_store.COOKIE_NAME) is None, redirect
            assert "รอการยืนยันจาก LINE" not in response.text, redirect

    def test_kiosk_elevate_still_auto_redirects(
        self, test_client, test_db, handoff_env
    ):
        """The kiosk QR is scanned by a phone in an external browser — the same
        UA shape as the hand-off path — so its hint must not be wrapped."""
        response = self._login(
            test_client, redirect="elevate%3Aticket123", user_agent=UA_MOBILE_SAFARI
        )
        assert 'http-equiv="refresh"' in response.text
        assert "disable_auto_login" not in response.text
        assert response.cookies.get(line_handoff_store.COOKIE_NAME) is None
        assert "รอการยืนยันจาก LINE" not in response.text
