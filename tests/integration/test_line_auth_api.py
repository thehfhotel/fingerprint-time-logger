"""
Integration tests for LINE Auth API

Tests complete LINE OAuth authentication flow:
- OAuth login initiation
- OAuth callback handling
- Account linking with 6-digit codes
- Account unlinking (admin)
- JWT token verification
"""

import os
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
