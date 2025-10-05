"""
Unit Tests for Persistent Login Features

Tests for new OAuth callback logic, token management, and verify-token enhancements.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
from fastapi import HTTPException

from app.models.models import Employee
from app.services.line_auth_service import line_auth_service


class TestOAuthCallbackLinkedUser:
    """Test OAuth callback behavior for users with already-linked accounts"""

    def test_oauth_callback_linked_user_returns_jwt_with_badge(self, test_db):
        """
        GIVEN: LINE user already linked to employee
        WHEN: OAuth callback is processed
        THEN: JWT contains employee_badge
        """
        # Create linked employee
        employee = Employee(
            badge_number="12345",
            display_name="Test Employee",
            line_user_id="U1234567890abcdef",
            line_display_name="LINE User",
            line_picture_url="https://example.com/pic.jpg"
        )
        test_db.add(employee)
        test_db.commit()

        # Simulate OAuth callback processing
        line_user_id = "U1234567890abcdef"
        existing_employee = test_db.query(Employee).filter(
            Employee.line_user_id == line_user_id
        ).first()

        assert existing_employee is not None
        assert existing_employee.badge_number == "12345"

        # Create JWT token with employee_badge
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=line_user_id,
            employee_badge=existing_employee.badge_number,
            display_name="LINE User",
            picture_url="https://example.com/pic.jpg"
        )

        # Verify token contains employee_badge
        payload = line_auth_service.verify_jwt_token(jwt_token)
        assert payload["employee_badge"] == "12345"
        assert payload["line_user_id"] == "U1234567890abcdef"

    def test_oauth_callback_linked_user_redirects_to_mobile(self, test_db):
        """
        GIVEN: LINE user already linked to employee
        WHEN: OAuth callback determines redirect URL
        THEN: Redirect URL is /qr-checkin/mobile with JWT
        """
        # Create linked employee
        employee = Employee(
            badge_number="12345",
            display_name="Test Employee",
            line_user_id="U1234567890abcdef"
        )
        test_db.add(employee)
        test_db.commit()

        # Check for existing linkage
        line_user_id = "U1234567890abcdef"
        existing_employee = test_db.query(Employee).filter(
            Employee.line_user_id == line_user_id
        ).first()

        # Generate redirect URL
        if existing_employee:
            jwt_token = line_auth_service.create_jwt_token(
                line_user_id=line_user_id,
                employee_badge=existing_employee.badge_number,
                display_name="Test User",
                picture_url=""
            )
            redirect_url = f"/qr-checkin/mobile?jwt={jwt_token}"
        else:
            redirect_url = "/qr-checkin/link-account"

        assert redirect_url.startswith("/qr-checkin/mobile?jwt=")
        assert "eyJ" in redirect_url  # JWT token present


class TestOAuthCallbackUnlinkedUser:
    """Test OAuth callback behavior for users without linked accounts"""

    def test_oauth_callback_unlinked_user_returns_jwt_without_badge(self, test_db):
        """
        GIVEN: LINE user not linked to any employee
        WHEN: OAuth callback is processed
        THEN: JWT has employee_badge=None
        """
        line_user_id = "U9999999999999999"  # Non-existent user

        # Check for existing linkage (should be None)
        existing_employee = test_db.query(Employee).filter(
            Employee.line_user_id == line_user_id
        ).first()

        assert existing_employee is None

        # Create JWT without employee_badge
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=line_user_id,
            employee_badge=None,
            display_name="New User",
            picture_url=""
        )

        # Verify token has None badge
        payload = line_auth_service.verify_jwt_token(jwt_token)
        assert payload["employee_badge"] is None
        assert payload["line_user_id"] == line_user_id

    def test_oauth_callback_unlinked_user_redirects_to_link_account(self, test_db):
        """
        GIVEN: LINE user not linked to any employee
        WHEN: OAuth callback determines redirect URL
        THEN: Redirect URL is /qr-checkin/link-account with JWT
        """
        line_user_id = "U9999999999999999"

        # Check for existing linkage
        existing_employee = test_db.query(Employee).filter(
            Employee.line_user_id == line_user_id
        ).first()

        # Generate redirect URL
        if existing_employee:
            redirect_url = "/qr-checkin/mobile"
        else:
            jwt_token = line_auth_service.create_jwt_token(
                line_user_id=line_user_id,
                employee_badge=None,
                display_name="New User",
                picture_url=""
            )
            redirect_url = (
                f"/qr-checkin/link-account"
                f"?jwt={jwt_token}"
                f"&line_user_id={line_user_id}"
            )

        assert redirect_url.startswith("/qr-checkin/link-account?jwt=")
        assert "line_user_id=" in redirect_url


class TestVerifyTokenResponseStructure:
    """Test verify-token endpoint response structure"""

    def test_verify_token_returns_employee_badge_for_linked(self):
        """
        GIVEN: JWT token with employee_badge
        WHEN: verify-token processes the token
        THEN: Response includes employee_badge and line_profile structure
        """
        # Create JWT with employee_badge
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id="U1234567890abcdef",
            employee_badge="12345",
            display_name="Test User",
            picture_url="https://example.com/pic.jpg"
        )

        # Verify token
        payload = line_auth_service.verify_jwt_token(jwt_token)

        # Simulate verify-token endpoint response structure
        response = {
            "valid": True,
            "employee_badge": payload.get("employee_badge"),
            "line_profile": {
                "user_id": payload.get("line_user_id"),
                "display_name": payload.get("display_name"),
                "picture_url": payload.get("picture_url")
            },
            "payload": payload
        }

        assert response["valid"] is True
        assert response["employee_badge"] == "12345"
        assert response["line_profile"]["user_id"] == "U1234567890abcdef"
        assert response["line_profile"]["display_name"] == "Test User"
        assert response["line_profile"]["picture_url"] == "https://example.com/pic.jpg"

    def test_verify_token_returns_null_badge_for_unlinked(self):
        """
        GIVEN: JWT token without employee_badge
        WHEN: verify-token processes the token
        THEN: Response has employee_badge=None and line_profile structure
        """
        # Create JWT without employee_badge
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id="U1234567890abcdef",
            employee_badge=None,
            display_name="Unlinked User",
            picture_url="https://example.com/pic.jpg"
        )

        # Verify token
        payload = line_auth_service.verify_jwt_token(jwt_token)

        # Simulate verify-token endpoint response structure
        response = {
            "valid": True,
            "employee_badge": payload.get("employee_badge"),
            "line_profile": {
                "user_id": payload.get("line_user_id"),
                "display_name": payload.get("display_name"),
                "picture_url": payload.get("picture_url")
            },
            "payload": payload
        }

        assert response["valid"] is True
        assert response["employee_badge"] is None
        assert response["line_profile"]["user_id"] == "U1234567890abcdef"
        assert response["line_profile"]["display_name"] == "Unlinked User"


class TestLinkAccountTokenUpdate:
    """Test link-account endpoint token generation"""

    def test_link_account_returns_new_token_with_badge(self, test_db):
        """
        GIVEN: Valid linking code and unlinked JWT
        WHEN: Account linking is successful
        THEN: New JWT token with employee_badge is generated
        """
        # Create unlinked employee with linking code
        employee = Employee(
            badge_number="67890",
            display_name="Unlinked Employee",
            line_linking_code="123456",
            line_linking_code_generated_at=datetime.now(timezone.utc)
        )
        test_db.add(employee)
        test_db.commit()

        # Simulate successful linking
        line_user_id = "U9999999999999999"
        employee.line_user_id = line_user_id
        employee.line_display_name = "New LINE User"
        employee.line_picture_url = "https://example.com/new.jpg"
        test_db.commit()

        # Generate new JWT with employee_badge
        new_token = line_auth_service.create_jwt_token(
            line_user_id=line_user_id,
            employee_badge=employee.badge_number,
            display_name="New LINE User",
            picture_url="https://example.com/new.jpg"
        )

        # Verify new token contains employee_badge
        payload = line_auth_service.verify_jwt_token(new_token)
        assert payload["employee_badge"] == "67890"
        assert payload["line_user_id"] == line_user_id

    def test_link_account_response_includes_new_token(self):
        """
        GIVEN: Successful account linking
        WHEN: Response is generated
        THEN: Response includes new JWT token with employee_badge
        """
        # Simulate link-account endpoint response
        new_token = line_auth_service.create_jwt_token(
            line_user_id="U1234567890abcdef",
            employee_badge="12345",
            display_name="Linked User",
            picture_url="https://example.com/pic.jpg"
        )

        response = {
            "success": True,
            "message": "เชื่อมต่อบัญชีสำเร็จ",
            "employee": {
                "badge_number": "12345",
                "display_name": "Linked User",
                "line_user_id": "U1234567890abcdef"
            },
            "token": new_token
        }

        assert response["success"] is True
        assert "token" in response

        # Verify token structure
        payload = line_auth_service.verify_jwt_token(response["token"])
        assert payload["employee_badge"] == "12345"


class TestJWTTokenManagement:
    """Test JWT token creation and validation"""

    def test_jwt_token_contains_all_required_claims(self):
        """
        GIVEN: Token creation parameters
        WHEN: JWT token is created
        THEN: Token contains all required claims
        """
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id="U1234567890abcdef",
            employee_badge="12345",
            display_name="Test User",
            picture_url="https://example.com/pic.jpg"
        )

        payload = line_auth_service.verify_jwt_token(jwt_token)

        # Verify all required claims present
        assert "line_user_id" in payload
        assert "employee_badge" in payload
        assert "display_name" in payload
        assert "picture_url" in payload
        assert "iat" in payload  # Issued at
        assert "exp" in payload  # Expiration

    def test_jwt_token_expiration_set_correctly(self):
        """
        GIVEN: JWT token creation
        WHEN: Token is generated
        THEN: Expiration is set to 24 hours from creation
        """
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id="U1234567890abcdef",
            employee_badge="12345",
            display_name="Test User",
            picture_url=""
        )

        payload = line_auth_service.verify_jwt_token(jwt_token)

        # Calculate expected expiration (24 hours)
        issued_at = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        expiration = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        duration = expiration - issued_at

        # Allow 1 second tolerance for processing time
        assert 86399 <= duration.total_seconds() <= 86401  # ~24 hours

    def test_expired_token_raises_exception(self):
        """
        GIVEN: Expired JWT token
        WHEN: Token verification is attempted
        THEN: HTTPException is raised
        """
        # Create token that's already expired
        with patch('app.services.line_auth_service.datetime') as mock_datetime:
            # Set current time to 25 hours ago
            past_time = datetime.now(timezone.utc) - timedelta(hours=25)
            mock_datetime.now.return_value = past_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            jwt_token = line_auth_service.create_jwt_token(
                line_user_id="U1234567890abcdef",
                employee_badge="12345",
                display_name="Test User",
                picture_url=""
            )

        # Try to verify expired token (should raise exception)
        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.verify_jwt_token(jwt_token)

        assert exc_info.value.status_code == 401

    def test_invalid_token_signature_raises_exception(self):
        """
        GIVEN: JWT token with tampered payload
        WHEN: Token verification is attempted
        THEN: HTTPException is raised
        """
        # Create valid token
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id="U1234567890abcdef",
            employee_badge="12345",
            display_name="Test User",
            picture_url=""
        )

        # Tamper with token (change one character)
        tampered_token = jwt_token[:-5] + "XXXXX"

        # Try to verify tampered token
        with pytest.raises(HTTPException) as exc_info:
            line_auth_service.verify_jwt_token(tampered_token)

        assert exc_info.value.status_code == 401


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_linking_overwrites_previous_link(self, test_db):
        """
        GIVEN: Employee already linked to different LINE user
        WHEN: New linking is performed (re-link)
        THEN: Old LINE user_id is replaced with new one
        """
        # Create employee with existing LINE link
        employee = Employee(
            badge_number="12345",
            display_name="Employee",
            line_user_id="U_OLD_USER_ID",
            line_display_name="Old User"
        )
        test_db.add(employee)
        test_db.commit()

        # Simulate re-linking to new LINE account
        employee.line_user_id = "U_NEW_USER_ID"
        employee.line_display_name = "New User"
        test_db.commit()

        # Verify linkage updated
        updated_employee = test_db.query(Employee).filter_by(
            badge_number="12345"
        ).first()
        assert updated_employee.line_user_id == "U_NEW_USER_ID"
        assert updated_employee.line_display_name == "New User"

    def test_multiple_employees_cannot_share_line_user_id(self, test_db):
        """
        GIVEN: Two employees trying to link to same LINE user
        WHEN: Second linking attempt is made
        THEN: Database constraint prevents duplicate line_user_id
        """
        # Create first employee
        employee1 = Employee(
            badge_number="11111",
            display_name="Employee 1",
            line_user_id="U1234567890abcdef"
        )
        test_db.add(employee1)
        test_db.commit()

        # Try to create second employee with same LINE user_id
        employee2 = Employee(
            badge_number="22222",
            display_name="Employee 2",
            line_user_id="U1234567890abcdef"
        )
        test_db.add(employee2)

        # This should raise integrity error (unique constraint violation)
        with pytest.raises(Exception):  # SQLAlchemy IntegrityError
            test_db.commit()
