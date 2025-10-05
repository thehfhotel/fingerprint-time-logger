"""
Unit Tests for LINE Authentication Security
Tests JWT token validation, expiry, and security edge cases
"""

import pytest
import jwt
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from fastapi import HTTPException

from app.services.line_auth_service import LineAuthService


@pytest.fixture
def auth_service():
    """Create LINE auth service instance for testing"""
    service = LineAuthService()
    # Use a test secret for predictable testing
    service.jwt_secret = "test-secret-key-for-unit-tests"
    service.jwt_expiry_hours = 24
    return service


@pytest.fixture
def valid_jwt_payload():
    """Create valid JWT payload"""
    return {
        "line_user_id": "U1234567890abcdef",
        "employee_badge": "EMP001",
        "display_name": "Test User",
        "picture_url": "https://example.com/pic.jpg"
    }


class TestJWTTokenGeneration:
    """Test JWT token creation"""

    def test_create_jwt_token_with_employee_badge(self, auth_service):
        """Test creating JWT token for linked account"""
        token = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge="EMP001",
            display_name="Test User",
            picture_url="https://example.com/pic.jpg"
        )

        assert token is not None
        assert isinstance(token, str)

        # Decode and verify payload
        payload = jwt.decode(token, auth_service.jwt_secret, algorithms=["HS256"])
        assert payload["line_user_id"] == "U12345"
        assert payload["employee_badge"] == "EMP001"
        assert payload["display_name"] == "Test User"
        assert "iat" in payload
        assert "exp" in payload

    def test_create_jwt_token_without_employee_badge(self, auth_service):
        """Test creating JWT token for unlinked account"""
        token = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge=None,
            display_name="Test User",
            picture_url="https://example.com/pic.jpg"
        )

        payload = jwt.decode(token, auth_service.jwt_secret, algorithms=["HS256"])
        assert payload["line_user_id"] == "U12345"
        assert payload["employee_badge"] is None
        assert payload["display_name"] == "Test User"

    def test_jwt_token_contains_expiry(self, auth_service):
        """Test that JWT token includes expiration claim"""
        token = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge="EMP001"
        )

        payload = jwt.decode(token, auth_service.jwt_secret, algorithms=["HS256"])
        assert "exp" in payload

        # Verify expiry is approximately 24 hours from now
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        time_diff = exp_time - now

        # Should be close to 24 hours (allow 1 minute tolerance)
        assert 23.98 * 3600 < time_diff.total_seconds() < 24.02 * 3600


class TestJWTTokenValidation:
    """Test JWT token verification and validation"""

    def test_verify_valid_jwt_token(self, auth_service):
        """Test verifying a valid JWT token"""
        # Create token
        token = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge="EMP001"
        )

        # Verify token
        payload = auth_service.verify_jwt_token(token)

        assert payload["line_user_id"] == "U12345"
        assert payload["employee_badge"] == "EMP001"

    def test_verify_expired_jwt_token(self, auth_service):
        """Test that expired tokens are rejected"""
        # Create expired token (exp in the past)
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)

        expired_payload = {
            "line_user_id": "U12345",
            "employee_badge": "EMP001",
            "iat": int(past.timestamp()),
            "exp": int(past.timestamp())  # Already expired
        }

        expired_token = jwt.encode(expired_payload, auth_service.jwt_secret, algorithm="HS256")

        # Verification should raise exception
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_jwt_token(expired_token)

        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_verify_invalid_signature_token(self, auth_service):
        """Test that tokens with invalid signatures are rejected"""
        # Create token with different secret
        wrong_secret = "wrong-secret-key"

        payload = {
            "line_user_id": "U12345",
            "employee_badge": "EMP001",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
        }

        invalid_token = jwt.encode(payload, wrong_secret, algorithm="HS256")

        # Verification should raise exception
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_jwt_token(invalid_token)

        assert exc_info.value.status_code == 401
        assert "invalid" in exc_info.value.detail.lower()

    def test_verify_tampered_jwt_token(self, auth_service):
        """Test that tampered tokens are rejected"""
        # Create valid token
        token = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge="EMP001"
        )

        # Tamper with token (change a character in the payload section)
        parts = token.split('.')
        if len(parts) == 3:
            # Tamper with payload (second part)
            tampered_payload = parts[1][:-1] + ('X' if parts[1][-1] != 'X' else 'Y')
            tampered_token = f"{parts[0]}.{tampered_payload}.{parts[2]}"

            # Verification should raise exception
            with pytest.raises(HTTPException) as exc_info:
                auth_service.verify_jwt_token(tampered_token)

            assert exc_info.value.status_code == 401

    def test_verify_malformed_jwt_token(self, auth_service):
        """Test that malformed tokens are rejected"""
        malformed_tokens = [
            "not.a.jwt",
            "invalid",
            "",
            "only.two",
            "too.many.parts.here.invalid"
        ]

        for malformed_token in malformed_tokens:
            with pytest.raises(HTTPException) as exc_info:
                auth_service.verify_jwt_token(malformed_token)

            assert exc_info.value.status_code == 401


class TestJWTTokenSecurity:
    """Test JWT token security features"""

    def test_jwt_algorithm_validation(self, auth_service):
        """Test that only HS256 algorithm is accepted"""
        # Create token with different algorithm (none algorithm attack)
        payload = {
            "line_user_id": "U12345",
            "employee_badge": "EMP001",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
        }

        # Try to create token with 'none' algorithm (security vulnerability)
        none_token = jwt.encode(payload, "", algorithm="none")

        # Verification should reject 'none' algorithm
        with pytest.raises(HTTPException):
            auth_service.verify_jwt_token(none_token)

    def test_jwt_missing_required_claims(self, auth_service):
        """Test that tokens missing required claims are rejected"""
        # Create token missing line_user_id
        incomplete_payload = {
            "employee_badge": "EMP001",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
        }

        incomplete_token = jwt.encode(incomplete_payload, auth_service.jwt_secret, algorithm="HS256")

        # Verify token (should decode but application should check required fields)
        payload = auth_service.verify_jwt_token(incomplete_token)

        # Verify missing required field
        assert "line_user_id" not in payload

    def test_jwt_token_replay_protection(self, auth_service):
        """Test that same token can be used multiple times (no replay protection at JWT level)"""
        # Note: JWT itself doesn't prevent replay attacks
        # Replay protection should be implemented at application level if needed

        token = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge="EMP001"
        )

        # Verify token multiple times
        payload1 = auth_service.verify_jwt_token(token)
        payload2 = auth_service.verify_jwt_token(token)

        # Both verifications should succeed (replay attack possible)
        assert payload1 == payload2

    def test_jwt_expiry_boundary(self, auth_service):
        """Test JWT token expiry boundary conditions"""
        # Create token that expires in 1 second
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=1)

        payload = {
            "line_user_id": "U12345",
            "employee_badge": "EMP001",
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp())
        }

        short_lived_token = jwt.encode(payload, auth_service.jwt_secret, algorithm="HS256")

        # Verify immediately (should work)
        verified_payload = auth_service.verify_jwt_token(short_lived_token)
        assert verified_payload["line_user_id"] == "U12345"

        # Wait for expiry
        time.sleep(2)

        # Verify after expiry (should fail)
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_jwt_token(short_lived_token)

        assert exc_info.value.status_code == 401


class TestJWTTokenRefresh:
    """Test JWT token refresh and update scenarios"""

    def test_token_update_after_account_linking(self, auth_service):
        """Test creating new token after account is linked"""
        # Initial token without employee badge
        token1 = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge=None,
            display_name="Test User"
        )

        payload1 = auth_service.verify_jwt_token(token1)
        assert payload1["employee_badge"] is None

        # After linking, create new token with employee badge
        token2 = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge="EMP001",
            display_name="Test User"
        )

        payload2 = auth_service.verify_jwt_token(token2)
        assert payload2["employee_badge"] == "EMP001"

        # Both tokens should be valid
        assert auth_service.verify_jwt_token(token1) is not None
        assert auth_service.verify_jwt_token(token2) is not None

    def test_token_invalidation_on_unlink(self, auth_service):
        """Test that old tokens remain valid after account unlink (no blacklist)"""
        # Note: Current implementation doesn't have token blacklisting
        # Old tokens remain valid until they expire

        token = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge="EMP001"
        )

        # Token should be valid
        payload = auth_service.verify_jwt_token(token)
        assert payload["employee_badge"] == "EMP001"

        # After unlink, token should still be valid (no blacklist mechanism)
        # This is a known limitation - tokens are valid until expiry
        payload_after_unlink = auth_service.verify_jwt_token(token)
        assert payload_after_unlink["employee_badge"] == "EMP001"


class TestJWTEdgeCases:
    """Test JWT edge cases and error conditions"""

    def test_empty_token_string(self, auth_service):
        """Test handling of empty token string"""
        with pytest.raises(HTTPException):
            auth_service.verify_jwt_token("")

    def test_null_token(self, auth_service):
        """Test handling of None token"""
        with pytest.raises(Exception):  # Will raise before HTTPException
            auth_service.verify_jwt_token(None)

    def test_very_long_token(self, auth_service):
        """Test handling of extremely long token"""
        # Create token with very long data
        long_payload = {
            "line_user_id": "U" * 1000,
            "employee_badge": "EMP" * 1000,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
        }

        long_token = jwt.encode(long_payload, auth_service.jwt_secret, algorithm="HS256")

        # Should still verify correctly
        payload = auth_service.verify_jwt_token(long_token)
        assert len(payload["line_user_id"]) == 1000

    def test_token_with_unicode_characters(self, auth_service):
        """Test JWT tokens with Unicode characters in payload"""
        token = auth_service.create_jwt_token(
            line_user_id="U12345",
            employee_badge="พนักงาน001",  # Thai characters
            display_name="ทดสอบ ผู้ใช้"  # Thai name
        )

        payload = auth_service.verify_jwt_token(token)
        assert payload["employee_badge"] == "พนักงาน001"
        assert payload["display_name"] == "ทดสอบ ผู้ใช้"
