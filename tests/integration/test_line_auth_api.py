"""
Integration tests for LINE Auth API

Tests complete LINE OAuth authentication flow:
- OAuth login initiation
- OAuth callback handling
- Account linking with 6-digit codes
- Account unlinking (admin)
- JWT token verification
"""

import asyncio
import os
import time

import pytest
from datetime import datetime, timezone, timedelta, timezone

from app.models.models import Employee
from app.services.line_auth_service import line_auth_service


# ============================================================================
# OAuth Flow Integration Tests
# ============================================================================

class TestLineOAuthFlow:
    """Test LINE OAuth authentication flow"""

    @pytest.mark.skipif(
        not os.getenv("LINE_CHANNEL_ID") or not os.getenv("LINE_CHANNEL_SECRET"),
        reason="LINE OAuth credentials not configured (LINE_CHANNEL_ID and LINE_CHANNEL_SECRET required)"
    )
    def test_login_initiation(self, test_client):
        """Test LINE OAuth login initiation returns HTML redirect"""
        response = test_client.get("/api/public/auth/line/login")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "access.line.me" in response.text
        assert "LINE" in response.text

    def test_callback_with_error(self, test_client):
        """Test OAuth callback handles errors gracefully"""
        response = test_client.get(
            "/api/public/auth/line/callback?error=access_denied&error_description=User cancelled"
        )

        assert response.status_code == 400
        assert "text/html" in response.headers["content-type"]
        assert "ล้มเหลว" in response.text  # Thai for "failed"

    def test_callback_missing_parameters(self, test_client):
        """Test OAuth callback requires code and state"""
        response = test_client.get("/api/public/auth/line/callback")

        assert response.status_code == 400


class TestCallbackDoesNotBlockTheEventLoop:
    """The two LINE round-trips in the callback are blocking ``requests`` calls
    with a 10s timeout each. This is a single-process uvicorn deployment, so
    running them on the event loop parks EVERYTHING for up to ~20s per
    callback: /oidc/token and /oidc/jwks (which Cloudflare Access fetches
    synchronously while a user waits), the kiosk /wait and /elevate/wait
    long-polls, and every QR check-in API. They must run on a worker thread.

    The probe is ``asyncio.get_running_loop()``, which only succeeds on a
    thread that is actually running the loop — so a raised RuntimeError inside
    the call is proof it was handed off.
    """

    def _drive_callback(self, test_client, monkeypatch, recorder):
        state = "state-offloop-probe"
        line_auth_service._state_storage[state] = (time.time(), None)

        def fake_exchange(code):
            recorder("exchange")
            return {"access_token": "line-access-token"}

        def fake_profile(access_token):
            recorder("profile")
            return {
                "userId": "U-offloop-probe",
                "displayName": "LINE User",
                "pictureUrl": "",
            }

        monkeypatch.setattr(
            line_auth_service, "exchange_code_for_token", fake_exchange
        )
        monkeypatch.setattr(line_auth_service, "get_user_profile", fake_profile)

        return test_client.get(
            f"/api/public/auth/line/callback?code=line-code&state={state}"
        )

    def test_both_line_calls_run_off_the_event_loop(self, test_client, monkeypatch):
        on_loop = {}

        def recorder(which):
            try:
                asyncio.get_running_loop()
                on_loop[which] = True
            except RuntimeError:
                on_loop[which] = False

        response = self._drive_callback(test_client, monkeypatch, recorder)

        assert response.status_code == 200
        assert on_loop == {"exchange": False, "profile": False}

    def test_callback_behaviour_is_unchanged_by_the_offload(
        self, test_client, monkeypatch
    ):
        """Only WHERE the calls run changed — an unlinked LINE user still lands
        on the link-account page carrying their fresh JWT."""
        response = self._drive_callback(
            test_client, monkeypatch, lambda which: None
        )

        assert response.status_code == 200
        assert "/qr-checkin/link-account?jwt=" in response.text
        assert "U-offloop-probe" in response.text


# ============================================================================
# Account Linking Integration Tests
# ============================================================================

class TestAccountLinking:
    """Test LINE account linking with 6-digit codes"""

    def test_link_account_with_valid_code(self, test_client, test_db, test_employee_with_code):
        """Test successful account linking"""
        # Create JWT token for LINE user
        line_user_id = "U1234567890abcdef"
        token = line_auth_service.create_jwt_token(line_user_id, "temp_badge")

        response = test_client.post(
            "/api/public/auth/line/link-account",
            json={
                "linking_code": test_employee_with_code.line_linking_code,
                "jwt_token": token
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "เชื่อมต่อบัญชีสำเร็จ" in data["message"]
        assert data["employee"]["badge_number"] == test_employee_with_code.badge_number
        assert "token" in data

        # Verify employee is now linked
        test_db.refresh(test_employee_with_code)
        assert test_employee_with_code.line_user_id == line_user_id
        assert test_employee_with_code.line_linking_code is None

    def test_link_account_invalid_code(self, test_client):
        """Test linking fails with invalid code"""
        token = line_auth_service.create_jwt_token("U1234567890abcdef", "temp_badge")

        response = test_client.post(
            "/api/public/auth/line/link-account",
            json={
                "linking_code": "999999",
                "jwt_token": token
            }
        )

        assert response.status_code == 400

    def test_link_account_already_linked(self, test_client, test_employee_with_line):
        """Test linking fails for already linked employee"""
        token = line_auth_service.create_jwt_token("U_different_user", "temp_badge")

        response = test_client.post(
            "/api/public/auth/line/link-account",
            json={
                "linking_code": "123456",  # Any code
                "jwt_token": token
            }
        )

        # Should fail because employee is already linked
        assert response.status_code in [400, 404]

    def test_link_account_expired_code(self, test_client, test_db):
        """Test linking fails with expired code"""
        # Create employee with expired code
        employee = Employee(
            badge_number="TEST_EXPIRED",
            display_name="Expired Code Employee",
            english_name="Expired Code Employee",
            is_active=True,
            line_linking_code="888888",
            line_linking_code_generated_at=datetime.now(timezone.utc) - timedelta(hours=25)
        )
        test_db.add(employee)
        test_db.commit()

        token = line_auth_service.create_jwt_token("U1234567890abcdef", "temp_badge")

        response = test_client.post(
            "/api/public/auth/line/link-account",
            json={
                "linking_code": "888888",
                "jwt_token": token
            }
        )

        assert response.status_code == 400
        assert "หมดอายุ" in response.json()["detail"]  # Thai for "expired"

        # Cleanup
        test_db.delete(employee)
        test_db.commit()


# ============================================================================
# Account Unlinking Integration Tests
# ============================================================================

class TestAccountUnlinking:
    """Test LINE account self-unlinking.

    The endpoint is now self-service: it identifies the caller via a
    LINE JWT in the Authorization header and unlinks whichever employee
    is currently linked to that LINE user. Administrative unlink of
    arbitrary users moved to /api/private/admin/line-codes/unlink behind
    Cloudflare Access. See app/api/line_auth.py:735 for the contract.
    The old admin_passcode body field doesn't exist anymore.
    """

    def test_unlink_account_success(self, test_client, test_db, test_employee_with_line):
        """Caller with a valid LINE JWT can unlink their own account."""
        token = line_auth_service.create_jwt_token(
            test_employee_with_line.line_user_id,
            test_employee_with_line.badge_number,
        )
        response = test_client.post(
            "/api/public/auth/line/unlink-account",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "Testing unlink"},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["success"] is True

        # Verify employee is unlinked
        test_db.refresh(test_employee_with_line)
        assert test_employee_with_line.line_user_id is None

    def test_unlink_account_missing_bearer_token(self, test_client, test_employee_with_line):
        """Unlink without a Bearer token must be rejected as unauthorized."""
        response = test_client.post(
            "/api/public/auth/line/unlink-account",
            json={"reason": "Testing"},
        )
        assert response.status_code == 401

    def test_unlink_account_not_linked(self, test_client, test_employee):
        """A LINE user who isn't linked to any employee gets a 404."""
        token = line_auth_service.create_jwt_token(
            "U_some_unlinked_line_user", test_employee.badge_number
        )
        response = test_client.post(
            "/api/public/auth/line/unlink-account",
            headers={"Authorization": f"Bearer {token}"},
            json={"reason": "Testing"},
        )
        assert response.status_code == 404


# ============================================================================
# Password-less mobile dead-end guidance (Cloudflare Access / "oidc:" flow)
# ============================================================================

class TestPasswordlessMobileGuidance:
    """The interstitial on the one combination LINE has no usable screen for.

    Staff LINE accounts are made on a phone and normally have no email or
    password. On the Access flow we must send disable_auto_login (otherwise iOS
    hands off to the LINE app, the callback completes in a different cookie jar
    and the Access session started in the browser is stranded), and that makes
    LINE render its email/password FORM. The desktop escape hatch,
    initial_amr_display=lineqr, is useless on a phone — the user cannot scan a
    code shown on the screen they are holding.

    So on Access + mobile + non-LINE browser the user is told, before LINE ever
    renders, to open the tool from the LINE app rich menu (their primary path,
    where auto login works). It stays a page with a "continue" link rather than
    a block, because managers with a LINE password hit the same combination and
    the form works fine for them.

    Everything else must keep auto-redirecting exactly as before — these tests
    pin the scope, since a too-wide guidance page would put an extra tap in
    front of 80+ housekeeping staff on the path that already works.
    """

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

    @pytest.fixture(autouse=True)
    def _line_configured(self, monkeypatch):
        """LINE creds are unset in tests; /login 500s without a channel id."""
        monkeypatch.setattr(line_auth_service, "channel_id", "test_channel_id")

    def _login(self, test_client, *, redirect, user_agent):
        return test_client.get(
            f"/api/public/auth/line/login?redirect={redirect}",
            headers={"User-Agent": user_agent},
        )

    def test_mobile_external_browser_on_access_flow_gets_guidance(self, test_client):
        response = self._login(
            test_client, redirect="oidc%3Aticket123",
            user_agent=self.UA_MOBILE_SAFARI,
        )

        assert response.status_code == 200
        # Told what to do, and NOT auto-shipped to a form they cannot complete.
        assert "เปิดจากแอป LINE" in response.text
        assert "http-equiv=\"refresh\"" not in response.text
        assert "window.location.href" not in response.text

    def test_guidance_still_offers_the_real_login_url(self, test_client):
        """Not a dead end for anyone who does hold a LINE password: the button
        carries the identical URL the auto-redirect would have used."""
        response = self._login(
            test_client, redirect="oidc%3Aticket123",
            user_agent=self.UA_MOBILE_SAFARI,
        )

        assert "access.line.me/oauth2/v2.1/authorize" in response.text
        # The Safari cookie-jar guard is untouched by this page.
        assert "disable_auto_login=true" in response.text

    def test_line_in_app_browser_is_not_interrupted(self, test_client):
        """The maid's primary path — the rich menu inside LINE — keeps auto
        login and must keep auto-redirecting. Regressing this would put a wall
        in front of the flow that works today."""
        response = self._login(
            test_client, redirect="oidc%3Aticket123", user_agent=self.UA_LINE_IOS,
        )

        assert response.status_code == 200
        assert "http-equiv=\"refresh\"" in response.text
        assert "เปิดจากแอป LINE" not in response.text

    def test_desktop_access_flow_is_not_interrupted(self, test_client):
        """Desktop already has a working escape (the QR is scanned with the
        phone), so it must not see the guidance page."""
        response = self._login(
            test_client, redirect="oidc%3Aticket123",
            user_agent=self.UA_DESKTOP_CHROME,
        )

        assert "http-equiv=\"refresh\"" in response.text
        assert "initial_amr_display=lineqr" in response.text
        assert "เปิดจากแอป LINE" not in response.text

    def test_public_path_mobile_flows_are_not_interrupted(self, test_client):
        """QR clock-in, mobile check-in and onboarding hold no Access session,
        never get disable_auto_login, and so never hit the dead end."""
        for redirect in ("qr-scan-callback", "mobile-checkin", "onboard"):
            response = self._login(
                test_client, redirect=redirect, user_agent=self.UA_MOBILE_SAFARI,
            )
            assert "เปิดจากแอป LINE" not in response.text, redirect
            assert "http-equiv=\"refresh\"" in response.text, redirect

    def test_mobile_qr_login_is_never_forced(self, test_client):
        """The other tempting "fix" for this dead end, pinned as forbidden: a
        QR on a phone is a code the user is asked to scan with the device
        showing it."""
        response = self._login(
            test_client, redirect="oidc%3Aticket123",
            user_agent=self.UA_MOBILE_SAFARI,
        )

        assert "initial_amr_display" not in response.text


# ============================================================================
# JWT Token Verification Integration Tests
# ============================================================================

class TestJWTVerification:
    """Test JWT token verification endpoint"""

    def test_verify_valid_token(self, test_client):
        """Test verification of valid JWT token"""
        token = line_auth_service.create_jwt_token("U1234567890abcdef", "EMP001")

        response = test_client.post(
            "/api/public/auth/line/verify-token",
            json={"token": token}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["payload"]["line_user_id"] == "U1234567890abcdef"
        assert data["payload"]["employee_badge"] == "EMP001"

    def test_verify_invalid_token(self, test_client):
        """Test verification of invalid JWT token"""
        response = test_client.post(
            "/api/public/auth/line/verify-token",
            json={"token": "invalid.jwt.token"}
        )

        assert response.status_code == 401


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def test_employee_with_code(test_db):
    """Create test employee with valid linking code"""
    employee = Employee(
        badge_number="TEST_CODE",
        display_name="Employee With Code",
        english_name="Employee With Code",
        is_active=True,
        line_linking_code="123456",
        line_linking_code_generated_at=datetime.now(timezone.utc)
    )
    test_db.add(employee)
    test_db.commit()
    test_db.refresh(employee)
    yield employee
    test_db.delete(employee)
    test_db.commit()


@pytest.fixture
def test_employee_with_line(test_db):
    """Create test employee with linked LINE account"""
    employee = Employee(
        badge_number="TEST_LINE",
        display_name="Employee With LINE",
        english_name="Employee With LINE",
        is_active=True,
        line_user_id="U1234567890abcdef",
        line_display_name="LINE User",
        line_picture_url="https://example.com/pic.jpg"
    )
    test_db.add(employee)
    test_db.commit()
    test_db.refresh(employee)
    yield employee
    test_db.delete(employee)
    test_db.commit()
