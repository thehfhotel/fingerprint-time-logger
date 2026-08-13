"""
Unit tests for LINE Auth Service

Tests all LINE OAuth authentication service functionality:
- Authorization URL generation with CSRF state management
- Token exchange for LINE access tokens
- LINE user profile retrieval
- JWT token creation and verification
- State validation and TTL expiry
"""

import pytest
import time
import jwt
from datetime import datetime, timezone, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock

from app.services.line_auth_service import LineAuthService, is_line_in_app_browser
from fastapi import HTTPException


# Real-world User-Agents, kept verbatim so the token-boundary matching is
# exercised against what phones actually send.
UA_LINE_IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Line/13.5.0"
)
UA_LINE_ANDROID_LIFF = (
    "Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36 Line/13.19.0/IAB"
)
UA_MOBILE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def line_auth_service():
    """Create LINE auth service instance with test configuration"""
    service = LineAuthService()
    # Override with test config
    service.channel_id = "test_channel_id"
    service.channel_secret = "test_channel_secret"
    service.callback_url = "http://localhost:5000/api/auth/line/callback"
    service.jwt_secret = "test_jwt_secret"
    return service


# ============================================================================
# Authorization URL Generation Tests
# ============================================================================

class TestAuthorizationURL:
    """Test LINE OAuth authorization URL generation"""

    def test_generate_auth_url_with_state(self, line_auth_service):
        """Test authorization URL generation with provided state"""
        test_state = "test_state_12345"
        result = line_auth_service.generate_authorization_url(state=test_state)

        assert "auth_url" in result
        assert "state" in result
        assert result["state"] == test_state
        assert "access.line.me/oauth2/v2.1/authorize" in result["auth_url"]
        assert f"client_id={line_auth_service.channel_id}" in result["auth_url"]
        assert f"state={test_state}" in result["auth_url"]
        assert "response_type=code" in result["auth_url"]

    def test_qr_checkin_keeps_the_line_app_handoff(self, line_auth_service):
        """QR clock-in and every other public-path caller must KEEP auto login:
        they hold no Cloudflare session to lose, and the app hand-off is the
        whole experience. Disabling it globally broke check-in."""
        for hint in (None, "qr-scan-callback", "mobile-checkin", "onboard"):
            result = line_auth_service.generate_authorization_url(state="s", redirect_hint=hint)
            assert "disable_auto_login" not in result["auth_url"], hint

    def test_auth_url_disables_auto_login_in_an_external_browser(self, line_auth_service):
        """Auto login hands off to the LINE app, which finishes the callback in
        its own LIFF browser; the Cloudflare session lives in the browser that
        started the flow and never sees it ("Invalid session"). Keeping login
        in-browser is the fix, so an external browser on the Access flow must
        still get this parameter."""
        result = line_auth_service.generate_authorization_url(
            state="s", redirect_hint="oidc:abc123", user_agent=UA_MOBILE_SAFARI
        )

        assert "disable_auto_login=true" in result["auth_url"]

    def test_auth_url_keeps_auto_login_inside_the_line_browser(self, line_auth_service):
        """Inside LINE's own in-app browser the Safari hand-off cannot happen —
        there is no external session to strand — while disabling auto login
        forces LINE's web login FORM, which password-less staff accounts (made
        on a phone, no email set) cannot complete. So the flag is dropped."""
        for ua in (UA_LINE_IOS, UA_LINE_ANDROID_LIFF):
            result = line_auth_service.generate_authorization_url(
                state="s", redirect_hint="oidc:abc123", user_agent=ua
            )
            assert "disable_auto_login" not in result["auth_url"], ua

    def test_auth_url_disables_auto_login_when_user_agent_unknown(self, line_auth_service):
        """Fail-safe: an absent UA must be treated as NOT-LINE. The carve-out is
        only ever allowed to remove the login-form wall inside LINE, never to
        hand the "Invalid session" bug back to an unknown caller."""
        result = line_auth_service.generate_authorization_url(
            state="s", redirect_hint="oidc:abc123"
        )

        assert "disable_auto_login=true" in result["auth_url"]

    def test_line_browser_does_not_change_non_oidc_flows(self, line_auth_service):
        """The carve-out lives inside the oidc branch, so a LINE UA on a public
        -path flow changes nothing: the flag was never sent there anyway."""
        for hint in (None, "qr-scan-callback", "mobile-checkin", "onboard"):
            result = line_auth_service.generate_authorization_url(
                state="s", redirect_hint=hint, user_agent=UA_LINE_IOS
            )
            assert "disable_auto_login" not in result["auth_url"], hint

    def test_auth_url_offers_qr_on_desktop(self, line_auth_service):
        """Desktop: QR first, since staff accounts usually have no password."""
        result = line_auth_service.generate_authorization_url(state="s", prefer_qr=True)

        assert "initial_amr_display=lineqr" in result["auth_url"]

    def test_auth_url_omits_qr_on_mobile(self, line_auth_service):
        """Mobile: no QR — a phone cannot scan a code shown on its own screen."""
        result = line_auth_service.generate_authorization_url(state="s", prefer_qr=False)

        assert "initial_amr_display" not in result["auth_url"]

    def test_auth_url_keeps_email_login_available(self, line_auth_service):
        """switch_amr must stay unset (defaults true) so the "log in with email"
        link remains — this reorders the options, it does not remove one."""
        result = line_auth_service.generate_authorization_url(state="s", prefer_qr=True)

        assert "switch_amr" not in result["auth_url"]

    def test_generate_auth_url_without_state(self, line_auth_service):
        """Test authorization URL generation with auto-generated state"""
        result = line_auth_service.generate_authorization_url()

        assert "auth_url" in result
        assert "state" in result
        assert len(result["state"]) > 20  # State should be sufficiently long
        assert result["state"] in result["auth_url"]

    def test_generate_auth_url_missing_channel_id(self, line_auth_service):
        """Test authorization URL generation fails without channel ID"""
        line_auth_service.channel_id = ""

        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.generate_authorization_url()

        assert exc_info.value.status_code == 500
        assert "not configured" in exc_info.value.detail.lower()

    def test_generate_auth_url_stores_state(self, line_auth_service):
        """State now stores (timestamp, redirect_hint) — see
        app/services/line_auth_service.py:111 — to support smart
        OAuth-callback redirects for users mid-flow.
        """
        result = line_auth_service.generate_authorization_url()
        state = result["state"]

        assert state in line_auth_service._state_storage
        entry = line_auth_service._state_storage[state]
        assert isinstance(entry, tuple)
        assert isinstance(entry[0], float)  # timestamp


# ============================================================================
# LINE In-App Browser Detection Tests
# ============================================================================

class TestLineInAppBrowserDetection:
    """Test User-Agent detection for LINE's in-app browser.

    This gates whether disable_auto_login is sent on the Cloudflare Access
    flow, so both error directions are covered here — a false NEGATIVE only
    leaves the old behaviour, but a false POSITIVE strips the flag from a real
    external browser and brings back "Invalid session. Please try logging in
    again."
    """

    def test_detects_line_in_app_browser(self):
        """The `Line/<version>` product token, iOS and the Android LIFF form."""
        assert is_line_in_app_browser(UA_LINE_IOS) is True
        assert is_line_in_app_browser(UA_LINE_ANDROID_LIFF) is True

    def test_detects_line_regardless_of_token_case(self):
        """Case is not what keeps false positives out (the token boundary is),
        so a differently-cased product token still counts as LINE."""
        assert is_line_in_app_browser("Mozilla/5.0 (iPhone) LINE/13.5.0") is True

    def test_ordinary_browser_is_not_line(self):
        """Mobile Safari and desktop Chrome must read as external browsers."""
        assert is_line_in_app_browser(UA_MOBILE_SAFARI) is False
        assert is_line_in_app_browser(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ) is False

    def test_does_not_match_line_inside_another_word(self):
        """"line" is a common tail of ordinary product names. Matching one of
        these would strip disable_auto_login from a genuine external browser."""
        for ua in (
            "Mozilla/5.0 (iPhone) Streamline/2.0",
            "Mozilla/5.0 (iPhone) StreamLine/2.0",
            "Mozilla/5.0 (iPhone) Airline/1.4",
            "Mozilla/5.0 (iPhone) Baseline/9.0",
        ):
            assert is_line_in_app_browser(ua) is False, ua

    def test_requires_a_version_after_the_slash(self):
        """A bare word is not a product token; LINE always sends a version."""
        assert is_line_in_app_browser("Mozilla/5.0 (iPhone) Line") is False
        assert is_line_in_app_browser("Mozilla/5.0 online/offline") is False

    def test_unknown_user_agent_is_not_line(self):
        """None/empty means "unknown", which must fall on the not-LINE side so
        the caller keeps the conservative behaviour."""
        assert is_line_in_app_browser(None) is False
        assert is_line_in_app_browser("") is False


# ============================================================================
# State Validation Tests
# ============================================================================

class TestStateValidation:
    """Test CSRF state token validation"""

    # validate_state now returns (ok: bool, redirect_hint: Optional[str])
    # rather than a bare bool — see app/services/line_auth_service.py:130.
    # _state_storage entries are likewise (timestamp, redirect_hint) tuples.

    def test_validate_valid_state(self, line_auth_service):
        """Test validation of valid state token"""
        result = line_auth_service.generate_authorization_url()
        state = result["state"]

        ok, _hint = line_auth_service.validate_state(state)
        assert ok is True

        # State should be consumed (one-time use)
        assert state not in line_auth_service._state_storage

    def test_validate_invalid_state(self, line_auth_service):
        """Test validation of invalid state token"""
        ok, _hint = line_auth_service.validate_state("invalid_state_token")
        assert ok is False

    def test_validate_expired_state(self, line_auth_service):
        """Test validation of expired state token"""
        result = line_auth_service.generate_authorization_url()
        state = result["state"]

        # 11 minutes ago, past the 10-min TTL.
        line_auth_service._state_storage[state] = (time.time() - 660, None)

        ok, _hint = line_auth_service.validate_state(state)
        assert ok is False
        assert state not in line_auth_service._state_storage

    def test_validate_state_boundary_10_minutes(self, line_auth_service):
        """Test state at exactly 10 minute boundary"""
        result = line_auth_service.generate_authorization_url()
        state = result["state"]

        line_auth_service._state_storage[state] = (time.time() - 600, None)

        ok, _hint = line_auth_service.validate_state(state)
        assert ok is False

    def test_state_cleanup_removes_expired(self, line_auth_service):
        """Test that cleanup removes expired states"""
        fresh_state = "fresh_state"
        expired_state = "expired_state"

        line_auth_service._state_storage[fresh_state] = (time.time(), None)
        line_auth_service._state_storage[expired_state] = (time.time() - 700, None)

        line_auth_service._cleanup_expired_states()

        assert fresh_state in line_auth_service._state_storage
        assert expired_state not in line_auth_service._state_storage


# ============================================================================
# Token Exchange Tests
# ============================================================================

class TestTokenExchange:
    """Test LINE OAuth token exchange"""

    @patch('app.services.line_auth_service.requests.post')
    def test_exchange_code_success(self, mock_post, line_auth_service):
        """Test successful code to token exchange"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "token_type": "Bearer",
            "expires_in": 2592000,
            "refresh_token": "test_refresh_token"
        }
        mock_post.return_value = mock_response

        result = line_auth_service.exchange_code_for_token("test_code")

        assert result["access_token"] == "test_access_token"
        assert result["token_type"] == "Bearer"
        assert "refresh_token" in result

        # Verify correct API call
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert line_auth_service.line_token_url in call_args[0]

    @patch('app.services.line_auth_service.requests.post')
    def test_exchange_code_network_error(self, mock_post, line_auth_service):
        """Test token exchange handles network errors"""
        import requests
        mock_post.side_effect = requests.exceptions.RequestException("Network error")

        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.exchange_code_for_token("test_code")

        assert exc_info.value.status_code == 502
        assert "Failed to exchange code" in exc_info.value.detail

    @patch('app.services.line_auth_service.requests.post')
    def test_exchange_code_http_error(self, mock_post, line_auth_service):
        """Test token exchange handles HTTP errors"""
        import requests
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("HTTP 400 error")
        mock_post.return_value = mock_response

        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.exchange_code_for_token("test_code")

        assert exc_info.value.status_code == 502

    def test_exchange_code_missing_credentials(self, line_auth_service):
        """Test token exchange fails without credentials"""
        line_auth_service.channel_id = ""
        line_auth_service.channel_secret = ""

        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.exchange_code_for_token("test_code")

        assert exc_info.value.status_code == 500
        assert "not configured" in exc_info.value.detail.lower()


# ============================================================================
# User Profile Tests
# ============================================================================

class TestUserProfile:
    """Test LINE user profile retrieval"""

    @patch('app.services.line_auth_service.requests.get')
    def test_get_profile_success(self, mock_get, line_auth_service):
        """Test successful user profile retrieval"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "userId": "U1234567890abcdef",
            "displayName": "Test User",
            "pictureUrl": "https://example.com/pic.jpg",
            "statusMessage": "Hello!"
        }
        mock_get.return_value = mock_response

        result = line_auth_service.get_user_profile("test_access_token")

        assert result["userId"] == "U1234567890abcdef"
        assert result["displayName"] == "Test User"
        assert "pictureUrl" in result

        # Verify Authorization header
        call_args = mock_get.call_args
        assert "Authorization" in call_args[1]["headers"]
        assert "Bearer test_access_token" in call_args[1]["headers"]["Authorization"]

    @patch('app.services.line_auth_service.requests.get')
    def test_get_profile_network_error(self, mock_get, line_auth_service):
        """Test profile retrieval handles network errors"""
        import requests
        mock_get.side_effect = requests.exceptions.RequestException("Network error")

        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.get_user_profile("test_access_token")

        assert exc_info.value.status_code == 502
        assert "Failed to get LINE profile" in exc_info.value.detail

    @patch('app.services.line_auth_service.requests.get')
    def test_get_profile_mobile_safari_user_agent(self, mock_get, line_auth_service):
        """Test that Mobile Safari User-Agent is included"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"userId": "test"}
        mock_get.return_value = mock_response

        line_auth_service.get_user_profile("test_access_token")

        call_args = mock_get.call_args
        user_agent = call_args[1]["headers"]["User-Agent"]
        assert "iPhone" in user_agent or "Safari" in user_agent


# ============================================================================
# JWT Token Tests
# ============================================================================

class TestJWTTokens:
    """Test JWT token creation and verification"""

    def test_create_jwt_token(self, line_auth_service):
        """Test JWT token creation"""
        line_user_id = "U1234567890abcdef"
        employee_badge = "EMP001"

        token = line_auth_service.create_jwt_token(line_user_id, employee_badge)

        assert isinstance(token, str)
        assert len(token) > 50  # JWT should be substantial length

        # Verify token contents
        payload = jwt.decode(token, line_auth_service.jwt_secret, algorithms=["HS256"])
        assert payload["line_user_id"] == line_user_id
        assert payload["employee_badge"] == employee_badge
        assert "iat" in payload
        assert "exp" in payload

    def test_verify_valid_jwt_token(self, line_auth_service):
        """Test verification of valid JWT token"""
        line_user_id = "U1234567890abcdef"
        employee_badge = "EMP001"

        token = line_auth_service.create_jwt_token(line_user_id, employee_badge)
        payload = line_auth_service.verify_jwt_token(token)

        assert payload["line_user_id"] == line_user_id
        assert payload["employee_badge"] == employee_badge

    def test_verify_expired_jwt_token(self, line_auth_service):
        """Test verification of expired JWT token"""
        # Create token with immediate expiry
        now = datetime.now(timezone.utc)
        exp = now - timedelta(hours=1)  # Expired 1 hour ago

        payload = {
            "line_user_id": "test_user",
            "employee_badge": "EMP001",
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp())
        }

        expired_token = jwt.encode(payload, line_auth_service.jwt_secret, algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.verify_jwt_token(expired_token)

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_verify_invalid_jwt_token(self, line_auth_service):
        """Test verification of invalid JWT token"""
        invalid_token = "invalid.jwt.token"

        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.verify_jwt_token(invalid_token)

        assert exc_info.value.status_code == 401
        assert "invalid" in exc_info.value.detail.lower()

    def test_verify_jwt_wrong_secret(self, line_auth_service):
        """Test verification fails with wrong secret"""
        token = jwt.encode({"test": "data"}, "wrong_secret", algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.verify_jwt_token(token)

        assert exc_info.value.status_code == 401

    def test_jwt_token_expiry_24_hours(self, line_auth_service):
        """Test that JWT tokens expire in 24 hours"""
        token = line_auth_service.create_jwt_token("test_user", "EMP001")
        payload = jwt.decode(token, line_auth_service.jwt_secret, algorithms=["HS256"])

        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expiry_duration = (exp - iat).total_seconds() / 3600

        assert expiry_duration == 24  # 24 hours
