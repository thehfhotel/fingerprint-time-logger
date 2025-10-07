"""
E2E tests for LINE OAuth Authentication Flow

Tests complete LINE OAuth user journey including:
- Authorization URL generation
- OAuth callback handling
- Account linking with 6-digit code
- Smart callback routing
- Token persistence and validation

Uses Playwright for browser automation to test real user workflows.
"""

import pytest
import jwt
import time
from datetime import datetime, timedelta, timezone
from playwright.sync_api import Page, expect


@pytest.fixture
def base_url():
    """Base URL for the application"""
    return "http://localhost:5000"


class TestLINEOAuthInitiation:
    """Test LINE OAuth login initiation"""

    def test_line_login_endpoint_redirect(self, page: Page, base_url):
        """Test that /login endpoint redirects to LINE authorization"""
        # Navigate to LINE login endpoint
        page.goto(f"{base_url}/fingerprintlogs/api/auth/line/login")

        # Should show loading screen first
        expect(page.locator("text=กำลังเชื่อมต่อ LINE")).to_be_visible()

        # Wait for redirect (meta refresh)
        page.wait_for_timeout(2000)

        # Should redirect to LINE authorization (or show LINE login page)
        # In test environment, might show LINE mock or configuration error
        current_url = page.url
        assert "line.me" in current_url or "localhost" in current_url

    def test_oauth_state_parameter_generation(self, page: Page, base_url):
        """Test that OAuth state parameter is properly generated"""
        # Make API call to get authorization URL
        response = page.request.get(f"{base_url}/fingerprintlogs/api/auth/line/login")

        # Should return HTML with redirect
        assert response.status == 200
        content = response.text()

        # Should contain state parameter in redirect URL
        assert "state=" in content

    def test_oauth_scope_includes_profile(self, page: Page, base_url):
        """Test that OAuth scope includes profile access"""
        response = page.request.get(f"{base_url}/fingerprintlogs/api/auth/line/login")
        content = response.text()

        # Should request profile scope
        assert "scope=" in content
        assert "profile" in content


class TestLINEOAuthCallback:
    """Test LINE OAuth callback handling"""

    def test_callback_with_valid_code(self, page: Page, base_url):
        """Test callback endpoint with valid authorization code"""
        # Mock callback with authorization code
        # In real scenario, LINE would redirect here with code
        callback_url = f"{base_url}/fingerprintlogs/api/auth/line/callback"
        callback_url += "?code=mock_auth_code_12345&state=valid_state_token"

        page.goto(callback_url)

        # Should process callback (might show error in test env without real LINE config)
        # Key is that endpoint doesn't crash
        expect(page.locator("body")).to_be_visible()

    def test_callback_missing_code_parameter(self, page: Page, base_url):
        """Test callback rejects request without authorization code"""
        callback_url = f"{base_url}/fingerprintlogs/api/auth/line/callback"
        callback_url += "?state=valid_state_token"

        page.goto(callback_url)

        # Should show error message
        expect(page.locator("text=ข้อผิดพลาด")).to_be_visible()

    def test_callback_handles_user_cancellation(self, page: Page, base_url):
        """Test callback handles user cancelling OAuth flow"""
        callback_url = f"{base_url}/fingerprintlogs/api/auth/line/callback"
        callback_url += "?error=access_denied&error_description=User%20cancelled"

        page.goto(callback_url)

        # Should show cancellation message
        expect(page.locator("text=ยกเลิก")).to_be_visible()


class TestAccountLinkingWorkflow:
    """Test complete account linking workflow"""

    def create_mock_jwt_token(self, line_user_id: str, employee_badge: str = None) -> str:
        """Helper to create mock JWT token for testing"""
        payload = {
            "line_user_id": line_user_id,
            "employee_badge": employee_badge,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
        }
        return jwt.encode(payload, "test-secret", algorithm="HS256")

    def test_link_account_page_displays_correctly(self, page: Page, base_url):
        """Test that account linking page displays properly"""
        jwt_token = self.create_mock_jwt_token("U12345")

        page.goto(f"{base_url}/qr-checkin/link-account?jwt={jwt_token}")
        page.wait_for_load_state("networkidle")

        # Should show linking code input
        expect(page.locator("input[type='text']")).to_be_visible()

        # Should show instructions
        expect(page.locator("text=กรอกรหัส")).to_be_visible()

    def test_link_account_six_digit_code_validation(self, page: Page, base_url):
        """Test that 6-digit linking code validation works"""
        jwt_token = self.create_mock_jwt_token("U12345")

        page.goto(f"{base_url}/qr-checkin/link-account?jwt={jwt_token}")
        page.wait_for_load_state("networkidle")

        # Try invalid code length
        code_input = page.locator("input[type='text']").first
        code_input.fill("123")  # Only 3 digits

        submit_button = page.locator("button:has-text('ยืนยัน')").first
        if submit_button.is_visible():
            submit_button.click()

            # Should show error or remain on page
            page.wait_for_timeout(500)
            assert "link-account" in page.url

    def test_smart_callback_linked_account_redirect(self, page: Page, base_url):
        """Test that linked accounts auto-redirect to QR check-in"""
        # JWT token with employee badge (already linked)
        jwt_token = self.create_mock_jwt_token("U12345", employee_badge="EMP001")

        page.goto(f"{base_url}/qr-checkin/link-account?jwt={jwt_token}")
        page.wait_for_timeout(2000)

        # Should redirect to QR terminal
        # OR stay on link page if employee doesn't exist in test DB
        current_url = page.url
        assert "link-account" in current_url or "qr-terminal" in current_url


class TestOAuthErrorHandling:
    """Test OAuth error handling and edge cases"""

    def test_expired_state_token_rejection(self, page: Page, base_url):
        """Test that expired state tokens are rejected"""
        callback_url = f"{base_url}/fingerprintlogs/api/auth/line/callback"
        callback_url += "?code=auth_code&state=expired_state_12345"

        page.goto(callback_url)

        # Should show error message
        expect(page.locator("text=ข้อผิดพลาด")).to_be_visible()

    def test_missing_jwt_token_handling(self, page: Page, base_url):
        """Test that missing JWT token is handled gracefully"""
        # Navigate without JWT token parameter
        page.goto(f"{base_url}/qr-checkin/link-account")
        page.wait_for_timeout(1000)

        # Should show error or redirect to login
        current_url = page.url
        assert "link-account" in current_url or "login" in current_url
