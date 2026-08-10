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

from app.services.line_auth_service import LineAuthService
from fastapi import HTTPException


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

    def test_auth_url_disables_auto_login(self, line_auth_service):
        """Auto login hands off to the LINE app, which finishes the callback in
        its own LIFF browser; the Cloudflare session lives in the browser that
        started the flow and never sees it ("Invalid session"). Keeping login
        in-browser is the whole fix, so this parameter must always be sent."""
        result = line_auth_service.generate_authorization_url(state="s")

        assert "disable_auto_login=true" in result["auth_url"]

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
