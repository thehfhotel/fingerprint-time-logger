"""
Unit tests for QR Code Service

Tests QR token generation, validation, replay prevention, and QR code image generation.
"""

import pytest
import jwt
import time
from datetime import datetime, timedelta
from fastapi import HTTPException

from app.services.qr_service import QRCodeService


@pytest.fixture
def qr_service():
    """Create QR service instance for testing"""
    return QRCodeService()


class TestQRTokenGeneration:
    """Test QR token generation functionality"""

    def test_generate_qr_token_basic(self, qr_service):
        """Test basic QR token generation"""
        terminal_id = 1
        result = qr_service.generate_qr_token(terminal_id)

        assert "token" in result
        assert "nonce" in result
        assert "expires_at" in result
        assert "expires_in_seconds" in result
        assert isinstance(result["token"], str)
        assert len(result["token"]) > 50
        assert result["expires_in_seconds"] == 30

    def test_generate_qr_token_payload(self, qr_service):
        """Test QR token contains correct payload"""
        terminal_id = 42
        result = qr_service.generate_qr_token(terminal_id)

        # Decode token to verify payload
        payload = jwt.decode(result["token"], qr_service.jwt_secret, algorithms=["HS256"])
        assert payload["terminal_id"] == terminal_id
        assert payload["nonce"] == result["nonce"]
        assert "timestamp" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_generate_qr_token_unique_nonces(self, qr_service):
        """Test that each token has unique nonce"""
        token1 = qr_service.generate_qr_token(1)
        token2 = qr_service.generate_qr_token(1)

        assert token1["nonce"] != token2["nonce"]
        assert token1["token"] != token2["token"]

    def test_generate_qr_token_expiry_time(self, qr_service):
        """Test token expiry time is correct"""
        result = qr_service.generate_qr_token(1)

        # Decode and check expiry
        payload = jwt.decode(result["token"], qr_service.jwt_secret, algorithms=["HS256"])
        exp_time = datetime.utcfromtimestamp(payload["exp"])
        now = datetime.utcnow()

        # Should expire in approximately 30 seconds
        time_diff = (exp_time - now).total_seconds()
        assert 29 <= time_diff <= 31  # Allow 1 second tolerance


class TestQRTokenValidation:
    """Test QR token validation functionality"""

    def test_validate_qr_token_valid(self, qr_service):
        """Test validation of valid token"""
        token_data = qr_service.generate_qr_token(1)
        payload = qr_service.validate_qr_token(token_data["token"])

        assert payload["terminal_id"] == 1
        assert payload["nonce"] == token_data["nonce"]

    def test_validate_qr_token_expired(self, qr_service):
        """Test validation rejects expired token"""
        # Create expired token
        now = datetime.utcnow()
        exp = now - timedelta(seconds=1)  # Expired 1 second ago

        payload = {
            "terminal_id": 1,
            "timestamp": int(now.timestamp()),
            "nonce": "test_nonce",
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp())
        }

        expired_token = jwt.encode(payload, qr_service.jwt_secret, algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            qr_service.validate_qr_token(expired_token)

        assert exc_info.value.status_code == 400
        assert "หมดอายุ" in exc_info.value.detail

    def test_validate_qr_token_invalid_signature(self, qr_service):
        """Test validation rejects token with invalid signature"""
        # Create token with wrong secret
        payload = {
            "terminal_id": 1,
            "timestamp": int(datetime.utcnow().timestamp()),
            "nonce": "test_nonce",
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(seconds=30)).timestamp())
        }

        invalid_token = jwt.encode(payload, "wrong_secret", algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            qr_service.validate_qr_token(invalid_token)

        assert exc_info.value.status_code == 400
        assert "ไม่ถูกต้อง" in exc_info.value.detail

    def test_validate_qr_token_missing_nonce(self, qr_service):
        """Test validation rejects token without nonce"""
        payload = {
            "terminal_id": 1,
            "timestamp": int(datetime.utcnow().timestamp()),
            "iat": int(datetime.utcnow().timestamp()),
            "exp": int((datetime.utcnow() + timedelta(seconds=30)).timestamp())
            # nonce is missing
        }

        token = jwt.encode(payload, qr_service.jwt_secret, algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            qr_service.validate_qr_token(token)

        assert exc_info.value.status_code == 400
        assert "nonce" in exc_info.value.detail


class TestReplayPrevention:
    """Test replay attack prevention with nonce tracking"""

    def test_validate_qr_token_replay_attack(self, qr_service):
        """Test that same token cannot be used twice"""
        token_data = qr_service.generate_qr_token(1)

        # First validation should succeed
        qr_service.validate_qr_token(token_data["token"])

        # Second validation should fail (replay attack)
        with pytest.raises(HTTPException) as exc_info:
            qr_service.validate_qr_token(token_data["token"])

        assert exc_info.value.status_code == 400
        assert "ถูกใช้งานไปแล้ว" in exc_info.value.detail

    def test_nonce_cleanup(self, qr_service):
        """Test that nonce cleanup works"""
        # Generate and validate a token
        token_data = qr_service.generate_qr_token(1)
        qr_service.validate_qr_token(token_data["token"])

        # Verify nonce is in storage
        assert token_data["nonce"] in qr_service._used_nonces

        # Force cleanup by setting last cleanup time to past
        qr_service._last_cleanup = time.time() - 61  # 61 seconds ago

        # Generate and validate another token (should trigger cleanup)
        new_token = qr_service.generate_qr_token(2)
        qr_service.validate_qr_token(new_token["token"])

        # Old nonce should be cleared
        assert token_data["nonce"] not in qr_service._used_nonces
        # New nonce should be present
        assert new_token["nonce"] in qr_service._used_nonces


class TestQRCodeImage:
    """Test QR code image generation"""

    def test_generate_qr_code_image_basic(self, qr_service):
        """Test basic QR code image generation"""
        data = "test_data_123"
        image = qr_service.generate_qr_code_image(data)

        assert isinstance(image, str)
        assert image.startswith("data:image/png;base64,")
        assert len(image) > 100  # Should be a substantial base64 string

    def test_generate_qr_code_image_custom_size(self, qr_service):
        """Test QR code image with custom size"""
        data = "test_data"
        image_300 = qr_service.generate_qr_code_image(data, size=300)
        image_500 = qr_service.generate_qr_code_image(data, size=500)

        # Larger size should produce larger base64 string
        assert len(image_500) > len(image_300)

    def test_generate_qr_code_image_with_token(self, qr_service):
        """Test QR code image generation with JWT token"""
        token_data = qr_service.generate_qr_token(1)
        image = qr_service.generate_qr_code_image(token_data["token"])

        assert isinstance(image, str)
        assert image.startswith("data:image/png;base64,")


class TestCompleteQRGeneration:
    """Test complete QR code generation for terminal display"""

    def test_generate_qr_code_for_terminal(self, qr_service):
        """Test complete QR code generation"""
        terminal_id = 5
        result = qr_service.generate_qr_code_for_terminal(terminal_id)

        assert "qr_image" in result
        assert "token" in result
        assert "expires_at" in result
        assert "expires_in_seconds" in result
        assert "terminal_id" in result

        assert result["terminal_id"] == terminal_id
        assert result["qr_image"].startswith("data:image/png;base64,")
        assert isinstance(result["token"], str)
        assert result["expires_in_seconds"] == 30

    def test_generate_qr_code_for_terminal_custom_size(self, qr_service):
        """Test QR code generation with custom size"""
        result = qr_service.generate_qr_code_for_terminal(1, size=400)

        assert result["qr_image"].startswith("data:image/png;base64,")
        # Larger size produces larger image
        assert len(result["qr_image"]) > 1000

    def test_generate_qr_code_token_is_valid(self, qr_service):
        """Test that generated QR code contains valid token"""
        result = qr_service.generate_qr_code_for_terminal(1)

        # Token should be valid and verifiable
        payload = qr_service.validate_qr_token(result["token"])
        assert payload["terminal_id"] == 1


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_generate_token_different_terminals(self, qr_service):
        """Test tokens for different terminals are distinct"""
        token1 = qr_service.generate_qr_token(1)
        token2 = qr_service.generate_qr_token(2)

        payload1 = jwt.decode(token1["token"], qr_service.jwt_secret, algorithms=["HS256"])
        payload2 = jwt.decode(token2["token"], qr_service.jwt_secret, algorithms=["HS256"])

        assert payload1["terminal_id"] == 1
        assert payload2["terminal_id"] == 2
        assert token1["token"] != token2["token"]

    def test_validate_malformed_token(self, qr_service):
        """Test validation of malformed token"""
        with pytest.raises(HTTPException) as exc_info:
            qr_service.validate_qr_token("not_a_valid_token")

        assert exc_info.value.status_code == 400

    def test_generate_qr_image_empty_data(self, qr_service):
        """Test QR code generation with empty data"""
        image = qr_service.generate_qr_code_image("")

        # Should still generate valid image
        assert image.startswith("data:image/png;base64,")
