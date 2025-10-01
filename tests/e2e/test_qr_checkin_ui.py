"""
E2E Tests for QR Check-in UI Pages - Phase 4
Tests the three main UI components:
1. Account Linking Page (/qr-checkin/link-account)
2. Mobile Check-in Page (/qr-checkin/mobile)
3. QR Terminal Display (/qr-checkin/terminal)
"""

import pytest


@pytest.mark.e2e
@pytest.mark.cli
class TestQRCheckinPageAccessibility:
    """Test that all QR Check-in pages are accessible"""

    def test_link_account_page_loads(self, api_client, app_running):
        """Test that link account page loads successfully"""
        response = api_client.get("/qr-checkin/link-account")
        assert response.status_code == 200
        assert "เชื่อมต่อบัญชี LINE" in response.text
        assert "รหัสเชื่อมต่อ" in response.text

    def test_mobile_checkin_page_loads(self, api_client, app_running):
        """Test that mobile check-in page loads successfully"""
        response = api_client.get("/qr-checkin/mobile")
        assert response.status_code == 200
        assert "QR Check-in" in response.text
        assert "สแกน QR Code" in response.text

    def test_qr_terminal_page_loads(self, api_client, app_running):
        """Test that QR terminal display page loads successfully"""
        response = api_client.get("/qr-checkin/terminal")
        assert response.status_code == 200
        assert "QR Terminal" in response.text or "Check-in Terminal" in response.text

    def test_all_pages_have_proper_html_structure(self, api_client, app_running):
        """Test that all pages have proper HTML structure"""
        pages = [
            "/qr-checkin/link-account",
            "/qr-checkin/mobile",
            "/qr-checkin/terminal"
        ]

        for page in pages:
            response = api_client.get(page)
            assert response.status_code == 200
            html = response.text.lower()

            # Check for essential HTML elements
            assert "<!doctype html>" in html
            assert "<html" in html
            assert "<head>" in html
            assert "<body>" in html
            assert "charset=" in html
            assert "viewport" in html


@pytest.mark.e2e
@pytest.mark.cli
class TestLinkAccountPage:
    """Test Link LINE Account page functionality"""

    def test_page_has_required_elements(self, api_client, app_running):
        """Test that page contains all required elements"""
        response = api_client.get("/qr-checkin/link-account")
        html = response.text

        # Check for essential elements
        assert 'id="linkingCode"' in html  # Code input field
        assert 'id="linkingForm"' in html  # Form element
        assert 'id="profileSection"' in html  # Profile display section
        assert 'id="successSection"' in html  # Success state
        assert 'id="errorSection"' in html  # Error state

    def test_page_loads_javascript(self, api_client, app_running):
        """Test that JavaScript file is referenced"""
        response = api_client.get("/qr-checkin/link-account")
        html = response.text

        assert "link-line.js" in html

    def test_page_loads_css(self, api_client, app_running):
        """Test that CSS file is referenced"""
        response = api_client.get("/qr-checkin/link-account")
        html = response.text

        assert "link-line.css" in html

    def test_static_js_file_exists(self, api_client, app_running):
        """Test that JavaScript file is accessible"""
        response = api_client.get("/static/js/link-line.js")
        assert response.status_code == 200
        assert "text/javascript" in response.headers.get("content-type", "").lower() or \
               "application/javascript" in response.headers.get("content-type", "").lower()

    def test_static_css_file_exists(self, api_client, app_running):
        """Test that CSS file is accessible"""
        response = api_client.get("/static/css/link-line.css")
        assert response.status_code == 200
        assert "text/css" in response.headers.get("content-type", "").lower()


@pytest.mark.e2e
@pytest.mark.cli
class TestMobileCheckinPage:
    """Test Mobile Check-in page functionality"""

    def test_page_has_required_sections(self, api_client, app_running):
        """Test that page contains all required sections"""
        response = api_client.get("/qr-checkin/mobile")
        html = response.text

        # Check for essential sections
        assert 'id="loginSection"' in html  # Login state
        assert 'id="notLinkedSection"' in html  # Not linked state
        assert 'id="scannerSection"' in html  # Scanner active state
        assert 'id="videoElement"' in html  # Camera video element
        assert 'id="canvasElement"' in html  # Scanner canvas
        assert 'id="gpsStatus"' in html  # GPS status display

    def test_page_has_camera_controls(self, api_client, app_running):
        """Test that page has camera control buttons"""
        response = api_client.get("/qr-checkin/mobile")
        html = response.text

        assert 'id="startScanButton"' in html
        assert 'id="stopScanButton"' in html

    def test_page_has_recent_checkins_section(self, api_client, app_running):
        """Test that page has recent check-ins display"""
        response = api_client.get("/qr-checkin/mobile")
        html = response.text

        assert 'id="recentCheckIns"' in html
        assert "บันทึกล่าสุด" in html

    def test_page_loads_qr_scanner_library(self, api_client, app_running):
        """Test that jsQR library is loaded"""
        response = api_client.get("/qr-checkin/mobile")
        html = response.text

        assert "jsqr" in html.lower() or "jsQR" in html

    def test_static_js_file_exists(self, api_client, app_running):
        """Test that JavaScript file is accessible"""
        response = api_client.get("/static/js/mobile-checkin.js")
        assert response.status_code == 200

    def test_static_css_file_exists(self, api_client, app_running):
        """Test that CSS file is accessible"""
        response = api_client.get("/static/css/mobile-checkin.css")
        assert response.status_code == 200


@pytest.mark.e2e
@pytest.mark.cli
class TestQRTerminalPage:
    """Test QR Terminal Display page functionality"""

    def test_page_has_terminal_sections(self, api_client, app_running):
        """Test that page contains all terminal sections"""
        response = api_client.get("/qr-checkin/terminal")
        html = response.text

        # Check for essential sections
        assert 'id="terminalName"' in html  # Terminal name display
        assert 'id="qrCodeContainer"' in html  # QR code display
        assert 'id="countdown"' in html  # Countdown timer
        assert 'id="recentFeed"' in html  # Recent check-ins feed
        assert 'id="currentTime"' in html  # Clock display

    def test_page_has_terminal_info(self, api_client, app_running):
        """Test that page displays terminal information"""
        response = api_client.get("/qr-checkin/terminal")
        html = response.text

        assert 'id="terminalLocation"' in html
        assert 'id="footerGPS"' in html
        assert 'id="todayCount"' in html

    def test_page_has_fullscreen_button(self, api_client, app_running):
        """Test that page has fullscreen toggle"""
        response = api_client.get("/qr-checkin/terminal")
        html = response.text

        assert 'id="fullscreenButton"' in html

    def test_page_has_connection_status(self, api_client, app_running):
        """Test that page displays connection status"""
        response = api_client.get("/qr-checkin/terminal")
        html = response.text

        assert 'id="connectionStatus"' in html
        assert "status-dot" in html

    def test_terminal_page_with_terminal_id_parameter(self, api_client, app_running):
        """Test that page accepts terminal ID parameter"""
        response = api_client.get("/qr-checkin/terminal?terminal=1")
        assert response.status_code == 200

        response = api_client.get("/qr-checkin/terminal?terminal=2")
        assert response.status_code == 200

    def test_static_js_file_exists(self, api_client, app_running):
        """Test that JavaScript file is accessible"""
        response = api_client.get("/static/js/qr-terminal.js")
        assert response.status_code == 200

    def test_static_css_file_exists(self, api_client, app_running):
        """Test that CSS file is accessible"""
        response = api_client.get("/static/css/qr-terminal.css")
        assert response.status_code == 200


@pytest.mark.e2e
@pytest.mark.cli
class TestQRCheckinAPIIntegration:
    """Test that UI pages integrate with QR Check-in APIs"""

    def test_qr_checkin_api_endpoints_accessible(self, api_client, app_running):
        """Test that QR Check-in API endpoints are accessible"""
        # Test kiosk endpoint (should return 200 or 404 if terminal doesn't exist)
        response = api_client.get("/api/qr-checkin/kiosk/1")
        assert response.status_code in [200, 404]

        # Test validate-location endpoint
        response = api_client.get("/api/qr-checkin/validate-location?terminal_id=1&latitude=13.7563&longitude=100.5018")
        assert response.status_code in [200, 400, 404]

    def test_line_auth_api_endpoints_accessible(self, api_client, app_running):
        """Test that LINE Auth API endpoints are accessible"""
        # Test login endpoint (should redirect or return HTML)
        response = api_client.get("/api/auth/line/login", allow_redirects=False)
        assert response.status_code in [200, 302, 307]

    def test_admin_line_codes_api_accessible(self, api_client, app_running):
        """Test that Admin Line Codes API is accessible"""
        response = api_client.get("/api/admin/line-codes/stats")
        # Should return 401/403 without authentication, or 200 with auth
        assert response.status_code in [200, 401, 403]


@pytest.mark.e2e
@pytest.mark.cli
class TestResponsiveDesign:
    """Test that pages are responsive and mobile-friendly"""

    def test_pages_have_viewport_meta_tag(self, api_client, app_running):
        """Test that pages have proper viewport settings"""
        pages = [
            "/qr-checkin/link-account",
            "/qr-checkin/mobile",
            "/qr-checkin/terminal"
        ]

        for page in pages:
            response = api_client.get(page)
            html = response.text.lower()

            # Check for viewport meta tag
            assert 'name="viewport"' in html
            assert "width=device-width" in html

    def test_mobile_checkin_has_user_scalable_no(self, api_client, app_running):
        """Test that mobile check-in page prevents zooming (for scanner)"""
        response = api_client.get("/qr-checkin/mobile")
        html = response.text.lower()

        # Mobile check-in should prevent scaling for better QR scanning
        assert "user-scalable=no" in html


@pytest.mark.e2e
@pytest.mark.cli
class TestCacheControl:
    """Test that pages have proper cache control headers"""

    def test_pages_have_no_cache_headers(self, api_client, app_running):
        """Test that HTML pages are not cached"""
        pages = [
            "/qr-checkin/link-account",
            "/qr-checkin/mobile",
            "/qr-checkin/terminal"
        ]

        for page in pages:
            response = api_client.get(page)
            headers = {k.lower(): v for k, v in response.headers.items()}

            # Check for cache control headers
            assert "cache-control" in headers
            cache_control = headers["cache-control"].lower()
            assert "no-cache" in cache_control or "no-store" in cache_control


@pytest.mark.e2e
@pytest.mark.cli
class TestThaiLocalization:
    """Test that pages support Thai language properly"""

    def test_pages_have_thai_charset(self, api_client, app_running):
        """Test that pages support UTF-8 for Thai characters"""
        pages = [
            "/qr-checkin/link-account",
            "/qr-checkin/mobile",
            "/qr-checkin/terminal"
        ]

        for page in pages:
            response = api_client.get(page)
            html = response.text.lower()

            # Check for UTF-8 charset
            assert "utf-8" in html

    def test_pages_contain_thai_text(self, api_client, app_running):
        """Test that pages contain Thai language content"""
        test_cases = [
            ("/qr-checkin/link-account", "เชื่อมต่อบัญชี"),
            ("/qr-checkin/mobile", "สแกน QR Code"),
            ("/qr-checkin/terminal", "บันทึกการเข้างานล่าสุด")
        ]

        for page, expected_thai_text in test_cases:
            response = api_client.get(page)
            assert expected_thai_text in response.text
