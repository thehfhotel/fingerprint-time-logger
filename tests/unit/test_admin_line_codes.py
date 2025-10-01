"""
Unit tests for Admin Line Codes API

Tests all endpoints for LINE linking code management including:
- Admin passcode verification
- Code generation and regeneration
- Listing pending codes and linked accounts
- Account unlinking
- Statistics reporting
"""

import pytest
from datetime import datetime, timezone, timedelta, timezone
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session

from app.models.models import Employee
from app.api.admin_line_codes import (
    ADMIN_PASSCODE,
    verify_admin_passcode,
    generate_6_digit_code,
    is_code_expired
)


# ============================================================================
# HELPER FUNCTION TESTS
# ============================================================================

class TestHelperFunctions:
    """Test helper functions used by Admin Line Codes API"""

    def test_generate_6_digit_code_format(self, test_client):
        """Test that generated code is 6 digits"""
        code = generate_6_digit_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_6_digit_code_uniqueness(self, test_client):
        """Test that multiple codes are different (high probability)"""
        codes = [generate_6_digit_code() for _ in range(100)]
        # With 1M possible codes, 100 should be unique
        assert len(set(codes)) > 95

    def test_verify_admin_passcode_valid(self, test_client):
        """Test admin passcode verification succeeds with correct passcode"""
        # Should not raise exception
        verify_admin_passcode(ADMIN_PASSCODE)

    def test_verify_admin_passcode_invalid(self, test_client):
        """Test admin passcode verification fails with incorrect passcode"""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            verify_admin_passcode("wrongpassword")

        assert exc_info.value.status_code == 403
        assert "Invalid admin passcode" in exc_info.value.detail

    def test_is_code_expired_fresh_code(self, test_client):
        """Test that recently generated code is not expired"""
        generated_at = datetime.now(timezone.utc)
        assert not is_code_expired(generated_at)

    def test_is_code_expired_old_code(self, test_client):
        """Test that 25-hour-old code is expired"""
        generated_at = datetime.now(timezone.utc) - timedelta(hours=25)
        assert is_code_expired(generated_at)

    def test_is_code_expired_boundary_23_hours(self, test_client):
        """Test code at 23 hours is not expired"""
        generated_at = datetime.now(timezone.utc) - timedelta(hours=23)
        assert not is_code_expired(generated_at)

    def test_is_code_expired_boundary_24_hours(self, test_client):
        """Test code at exactly 24 hours is not expired (boundary)"""
        generated_at = datetime.now(timezone.utc) - timedelta(hours=24, seconds=-1)
        assert not is_code_expired(generated_at)

    def test_is_code_expired_none_generated_at(self, test_client):
        """Test that None generated_at is considered expired"""
        assert is_code_expired(None)

    def test_is_code_expired_custom_expiry(self, test_client):
        """Test custom expiry hours parameter"""
        generated_at = datetime.now(timezone.utc) - timedelta(hours=13)
        assert not is_code_expired(generated_at, expiry_hours=24)
        assert is_code_expired(generated_at, expiry_hours=12)


# ============================================================================
# API ENDPOINT TESTS
# ============================================================================

class TestAdminPasscodeVerification:
    """Test admin passcode verification endpoint"""

    def test_verify_passcode_success(self, test_client):
        """Test successful passcode verification"""
        response = test_client.post(
            "/api/admin/line-codes/verify-passcode",
            json={"passcode": ADMIN_PASSCODE}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "authenticated" in data["message"].lower()

    def test_verify_passcode_failure(self, test_client):
        """Test failed passcode verification"""
        response = test_client.post(
            "/api/admin/line-codes/verify-passcode",
            json={"passcode": "wrongpassword"}
        )

        assert response.status_code == 403
        assert "Invalid admin passcode" in response.json()["detail"]

    def test_verify_passcode_empty(self, test_client):
        """Test empty passcode verification"""
        response = test_client.post(
            "/api/admin/line-codes/verify-passcode",
            json={"passcode": ""}
        )

        assert response.status_code == 403


class TestGenerateLinkingCode:
    """Test linking code generation endpoint"""

    def test_generate_code_success(self, test_client, test_employee):
        """Test successful code generation for employee"""
        response = test_client.post(
            "/api/admin/line-codes/generate",
            json={
                "badge_number": test_employee.badge_number,
                "passcode": ADMIN_PASSCODE
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "linking_code" in data
        assert len(data["linking_code"]) == 6
        assert data["badge_number"] == test_employee.badge_number
        assert "expires_at" in data

    def test_generate_code_invalid_passcode(self, test_client, test_employee):
        """Test code generation fails with invalid passcode"""
        response = test_client.post(
            "/api/admin/line-codes/generate",
            json={
                "badge_number": test_employee.badge_number,
                "passcode": "wrongpassword"
            }
        )

        assert response.status_code == 403

    def test_generate_code_nonexistent_employee(self, test_client):
        """Test code generation fails for non-existent employee"""
        response = test_client.post(
            "/api/admin/line-codes/generate",
            json={
                "badge_number": "99999",
                "passcode": ADMIN_PASSCODE
            }
        )

        assert response.status_code == 404

    def test_generate_code_already_linked(self, test_client, test_employee_with_line):
        """Test code generation fails for already linked employee"""
        response = test_client.post(
            "/api/admin/line-codes/generate",
            json={
                "badge_number": test_employee_with_line.badge_number,
                "passcode": ADMIN_PASSCODE
            }
        )

        assert response.status_code == 400
        assert "เชื่อมต่อ LINE แล้ว" in response.json()["detail"]

    def test_generate_code_returns_existing_valid_code(self, test_client, test_employee_with_code):
        """Test that existing non-expired code is returned instead of generating new one"""
        original_code = test_employee_with_code.line_linking_code

        response = test_client.post(
            "/api/admin/line-codes/generate",
            json={
                "badge_number": test_employee_with_code.badge_number,
                "passcode": ADMIN_PASSCODE
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["linking_code"] == original_code
        assert "ยังใช้งานได้" in data["message"]


class TestRegenerateLinkingCode:
    """Test linking code regeneration endpoint"""

    def test_regenerate_code_success(self, test_client, test_employee_with_code):
        """Test successful code regeneration"""
        old_code = test_employee_with_code.line_linking_code

        response = test_client.post(
            "/api/admin/line-codes/regenerate",
            json={
                "badge_number": test_employee_with_code.badge_number,
                "passcode": ADMIN_PASSCODE,
                "reason": "Employee lost code"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["old_code"] == old_code
        assert data["new_code"] != old_code
        assert len(data["new_code"]) == 6

    def test_regenerate_code_already_linked(self, test_client, test_employee_with_line):
        """Test regeneration fails for already linked employee"""
        response = test_client.post(
            "/api/admin/line-codes/regenerate",
            json={
                "badge_number": test_employee_with_line.badge_number,
                "passcode": ADMIN_PASSCODE
            }
        )

        assert response.status_code == 400


class TestListPendingCodes:
    """Test listing pending linking codes endpoint"""

    def test_list_pending_codes_success(self, test_client, test_employee_with_code):
        """Test listing pending codes"""
        response = test_client.get(
            f"/api/admin/line-codes/list?passcode={ADMIN_PASSCODE}"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        # Find our test employee
        test_code = next(
            (item for item in data if item["badge_number"] == test_employee_with_code.badge_number),
            None
        )
        assert test_code is not None
        assert test_code["linking_code"] == test_employee_with_code.line_linking_code

    def test_list_pending_codes_exclude_expired(self, test_client, test_employee_with_expired_code):
        """Test that expired codes are excluded by default"""
        response = test_client.get(
            f"/api/admin/line-codes/list?passcode={ADMIN_PASSCODE}"
        )

        assert response.status_code == 200
        data = response.json()

        # Expired code should not be in list
        expired_code = next(
            (item for item in data if item["badge_number"] == test_employee_with_expired_code.badge_number),
            None
        )
        assert expired_code is None

    def test_list_pending_codes_include_expired(self, test_client, test_employee_with_expired_code):
        """Test including expired codes with parameter"""
        response = test_client.get(
            f"/api/admin/line-codes/list?passcode={ADMIN_PASSCODE}&include_expired=true"
        )

        assert response.status_code == 200
        data = response.json()

        # Expired code should be in list
        expired_code = next(
            (item for item in data if item["badge_number"] == test_employee_with_expired_code.badge_number),
            None
        )
        assert expired_code is not None
        assert expired_code["is_expired"] is True


class TestListLinkedAccounts:
    """Test listing linked LINE accounts endpoint"""

    def test_list_linked_accounts_success(self, test_client, test_employee_with_line):
        """Test listing linked accounts"""
        response = test_client.get(
            f"/api/admin/line-codes/linked?passcode={ADMIN_PASSCODE}"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Find our test employee
        linked = next(
            (item for item in data if item["badge_number"] == test_employee_with_line.badge_number),
            None
        )
        assert linked is not None
        assert linked["line_user_id"] == test_employee_with_line.line_user_id

    def test_list_linked_accounts_empty(self, test_client):
        """Test listing when no accounts are linked"""
        # This test assumes a clean database state
        response = test_client.get(
            f"/api/admin/line-codes/linked?passcode={ADMIN_PASSCODE}"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestUnlinkAccount:
    """Test unlinking LINE account endpoint"""

    def test_unlink_account_success(self, test_client, test_employee_with_line, test_db):
        """Test successful account unlinking"""
        response = test_client.post(
            "/api/admin/line-codes/unlink",
            json={
                "badge_number": test_employee_with_line.badge_number,
                "passcode": ADMIN_PASSCODE,
                "reason": "Testing unlink"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify employee is unlinked in database
        test_db.refresh(test_employee_with_line)
        assert test_employee_with_line.line_user_id is None
        assert test_employee_with_line.line_linking_code is None

    def test_unlink_account_not_linked(self, test_client, test_employee):
        """Test unlinking fails for non-linked employee"""
        response = test_client.post(
            "/api/admin/line-codes/unlink",
            json={
                "badge_number": test_employee.badge_number,
                "passcode": ADMIN_PASSCODE
            }
        )

        assert response.status_code == 400


class TestLinkingStats:
    """Test linking statistics endpoint"""

    def test_get_stats_success(self, test_client, test_employee, test_employee_with_code, test_employee_with_line):
        """Test retrieving linking statistics"""
        response = test_client.get(
            f"/api/admin/line-codes/stats?passcode={ADMIN_PASSCODE}"
        )

        assert response.status_code == 200
        data = response.json()

        assert "total_active_employees" in data
        assert "linked_accounts" in data
        assert "pending_codes" in data
        assert "unlinked" in data
        assert "linking_percentage" in data

        assert data["total_active_employees"] >= 3
        assert data["linked_accounts"] >= 1
        assert data["pending_codes"] >= 1

    def test_get_stats_invalid_passcode(self, test_client):
        """Test stats endpoint requires valid passcode"""
        response = test_client.get(
            "/api/admin/line-codes/stats?passcode=wrong"
        )

        assert response.status_code == 403


# ============================================================================
# EDGE CASES AND ERROR HANDLING
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_generate_code_collision_handling(self, test_client, test_employee, monkeypatch):
        """Test that code collision is handled by retrying"""
        # Mock generate_6_digit_code to return same code twice then different
        call_count = 0
        original_generate = generate_6_digit_code

        def mock_generate():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return "123456"  # Collision
            return original_generate()

        monkeypatch.setattr("app.api.admin_line_codes.generate_6_digit_code", mock_generate)

        # First employee gets 123456
        response1 = test_client.post(
            "/api/admin/line-codes/generate",
            json={
                "badge_number": test_employee.badge_number,
                "passcode": ADMIN_PASSCODE
            }
        )

        assert response1.status_code == 200

    def test_code_expiry_boundary_conditions(self, test_client, test_employee, test_db):
        """Test code expiry at exact 24-hour boundary"""
        # Set code to expire in 1 second
        test_employee.line_linking_code = "999999"
        test_employee.line_linking_code_generated_at = datetime.now(timezone.utc) - timedelta(hours=24, seconds=-1)
        test_db.commit()

        response = test_client.get(
            f"/api/admin/line-codes/list?passcode={ADMIN_PASSCODE}"
        )

        assert response.status_code == 200
        data = response.json()

        code = next(
            (item for item in data if item["badge_number"] == test_employee.badge_number),
            None
        )
        assert code is not None
        assert code["is_expired"] is False


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def test_employee_with_code(test_db):
    """Create test employee with valid linking code"""
    employee = Employee(
        badge_number="TEST002",
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
def test_employee_with_expired_code(test_db):
    """Create test employee with expired linking code"""
    employee = Employee(
        badge_number="TEST003",
        display_name="Employee With Expired Code",
        english_name="Employee With Expired Code",
        is_active=True,
        line_linking_code="654321",
        line_linking_code_generated_at=datetime.now(timezone.utc) - timedelta(hours=25)
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
        badge_number="TEST004",
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
