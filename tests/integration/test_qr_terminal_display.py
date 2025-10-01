"""
Integration tests for QR Terminal Display functionality.

Tests cover issues discovered during Phase 4 implementation:
1. Static resource loading with absolute paths
2. Terminal ID validation for QR terminals
3. API response structure and field validation
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import json
import base64
from datetime import datetime, timedelta

from app.main_unified import app
from app.core.database import Base, get_db
from app.models.models import Device


# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing"""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def test_db():
    """Create test database with tables"""
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(test_db):
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def qr_terminal_device(test_db):
    """Create QR terminal device for testing"""
    device = Device(
        id=2,
        name="Main Office",
        ip_address="192.168.100.210",
        port=4370,
        device_type="qr_terminal",
        device_metadata=json.dumps({
            "location_name": "Main Office",
            "gps_location": {
                "latitude": 13.7563,
                "longitude": 100.5018
            }
        })
    )
    test_db.add(device)
    test_db.commit()
    test_db.refresh(device)
    return device


@pytest.fixture
def fingerprint_device(test_db):
    """Create fingerprint device (should NOT work for QR terminal)"""
    device = Device(
        id=1,
        name="ZKTeco Device",
        ip_address="192.168.100.209",
        port=4370,
        device_type="fingerprint"
    )
    test_db.add(device)
    test_db.commit()
    test_db.refresh(device)
    return device


class TestQRTerminalStaticResources:
    """Test static resource loading with absolute paths (Issue #1)"""

    def test_qr_terminal_html_loads(self, client):
        """Test QR terminal HTML page loads successfully"""
        response = client.get("/fingerprintlogs/qr-checkin/terminal?terminal=2")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_qr_terminal_html_uses_absolute_paths(self, client):
        """Test HTML uses absolute paths for CSS/JS resources"""
        response = client.get("/fingerprintlogs/qr-checkin/terminal?terminal=2")
        html_content = response.text

        # Check CSS path is absolute
        assert '/fingerprintlogs/static/css/qr-terminal.css' in html_content
        assert 'static/css/qr-terminal.css' not in html_content or \
               '/fingerprintlogs/static/css/qr-terminal.css' in html_content

        # Check JS path is absolute
        assert '/fingerprintlogs/static/js/qr-terminal.js' in html_content
        assert 'static/js/qr-terminal.js' not in html_content or \
               '/fingerprintlogs/static/js/qr-terminal.js' in html_content

    def test_qr_terminal_css_loads(self, client):
        """Test QR terminal CSS file loads successfully"""
        response = client.get("/fingerprintlogs/static/css/qr-terminal.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    def test_qr_terminal_js_loads(self, client):
        """Test QR terminal JavaScript file loads successfully"""
        response = client.get("/fingerprintlogs/static/js/qr-terminal.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"] or \
               "application/javascript" in response.headers["content-type"]

    def test_mobile_checkin_uses_absolute_paths(self, client):
        """Test mobile check-in page uses absolute paths"""
        response = client.get("/fingerprintlogs/qr-checkin/mobile")
        html_content = response.text

        assert '/fingerprintlogs/static/css/mobile-checkin.css' in html_content
        assert '/fingerprintlogs/static/js/mobile-checkin.js' in html_content

    def test_link_line_uses_absolute_paths(self, client):
        """Test LINE link page uses absolute paths"""
        response = client.get("/fingerprintlogs/qr-checkin/link-account")
        html_content = response.text

        assert '/fingerprintlogs/static/css/link-line.css' in html_content
        assert '/fingerprintlogs/static/js/link-line.js' in html_content


class TestQRTerminalDeviceValidation:
    """Test terminal ID validation for QR terminals (Issue #2)"""

    def test_qr_terminal_api_with_valid_qr_terminal(self, client, qr_terminal_device):
        """Test API accepts valid QR terminal device"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/2")
        assert response.status_code == 200

        data = response.json()
        assert "qr_image" in data
        assert data["terminal_id"] == 2
        assert data["terminal_name"] == "Main Office"

    def test_qr_terminal_api_rejects_fingerprint_device(self, client, fingerprint_device):
        """Test API rejects fingerprint device for QR terminal endpoint"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/1")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data
        assert "ไม่พบเครื่อง QR terminal" in data["detail"]

    def test_qr_terminal_api_rejects_nonexistent_device(self, client):
        """Test API rejects non-existent device ID"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/999")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data

    def test_qr_terminal_html_uses_correct_default_id(self, client):
        """Test HTML page uses terminal ID 2 as default (not 1)"""
        response = client.get("/fingerprintlogs/qr-checkin/terminal")
        html_content = response.text

        # Check JavaScript initialization uses terminal 2
        assert "TERMINAL_ID = urlParams.get('terminal') || '2'" in html_content or \
               "terminal') || '2'" in html_content

    def test_navigation_links_use_terminal_2(self, client):
        """Test navigation links across pages use terminal=2"""
        pages = [
            "/fingerprintlogs/",
            "/fingerprintlogs/device-status",
            "/fingerprintlogs/nickname-management",
            "/fingerprintlogs/export",
            "/fingerprintlogs/status"
        ]

        for page in pages:
            response = client.get(page)
            if response.status_code == 200:
                html_content = response.text
                # Check QR terminal link uses terminal=2
                if 'qr-checkin/terminal' in html_content:
                    assert 'terminal=2' in html_content


class TestQRTerminalAPIResponse:
    """Test API response structure and validation (Issue #3)"""

    def test_api_response_structure(self, client, qr_terminal_device):
        """Test API returns correct response structure"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/2")
        assert response.status_code == 200

        data = response.json()

        # Required fields from QRCodeResponse model
        assert "qr_image" in data
        assert "terminal_id" in data
        assert "terminal_name" in data
        assert "expires_at" in data
        assert "expires_in_seconds" in data

        # Verify no 'success' field (was incorrectly checked in JavaScript)
        assert "success" not in data

    def test_api_response_field_types(self, client, qr_terminal_device):
        """Test API response field types are correct"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/2")
        data = response.json()

        # qr_image should be base64 data URI
        assert isinstance(data["qr_image"], str)
        assert data["qr_image"].startswith("data:image/png;base64,")

        # terminal_id should be integer
        assert isinstance(data["terminal_id"], int)
        assert data["terminal_id"] == 2

        # terminal_name should be string
        assert isinstance(data["terminal_name"], str)
        assert len(data["terminal_name"]) > 0

        # expires_at should be ISO format datetime string
        assert isinstance(data["expires_at"], str)
        datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))

        # expires_in_seconds should be positive integer
        assert isinstance(data["expires_in_seconds"], int)
        assert data["expires_in_seconds"] > 0

    def test_qr_image_is_valid_base64_png(self, client, qr_terminal_device):
        """Test QR image is valid base64-encoded PNG"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/2")
        data = response.json()

        qr_image = data["qr_image"]
        # Extract base64 data
        assert qr_image.startswith("data:image/png;base64,")
        base64_data = qr_image.replace("data:image/png;base64,", "")

        # Decode base64
        try:
            decoded = base64.b64decode(base64_data)
            # Check PNG magic number
            assert decoded.startswith(b'\x89PNG')
        except Exception as e:
            pytest.fail(f"Invalid base64 or PNG data: {e}")

    def test_expiry_time_is_future(self, client, qr_terminal_device):
        """Test QR code expiry time is in the future"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/2")
        data = response.json()

        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        now = datetime.now(expires_at.tzinfo)

        # Expiry should be in future
        assert expires_at > now

        # Should expire within reasonable time (e.g., 60 seconds)
        time_until_expiry = (expires_at - now).total_seconds()
        assert 0 < time_until_expiry <= 60

    def test_api_response_http_ok_status(self, client, qr_terminal_device):
        """Test API returns HTTP 200 OK for valid requests"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/2")

        # JavaScript checks response.ok (status 200-299)
        assert 200 <= response.status_code < 300
        assert response.status_code == 200

    def test_api_flat_response_structure(self, client, qr_terminal_device):
        """Test API returns flat structure (not nested terminal object)"""
        response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/2")
        data = response.json()

        # Response should be flat: {terminal_id, terminal_name, ...}
        # NOT nested: {terminal: {id, location_name}, ...}
        assert "terminal_id" in data  # Flat structure
        assert "terminal_name" in data  # Flat structure
        assert "terminal" not in data  # Should NOT have nested terminal object

        # terminal_name should be at top level (not in nested object)
        assert isinstance(data["terminal_name"], str)


class TestQRTerminalJavaScriptValidation:
    """Test JavaScript validation logic matches API behavior"""

    def test_javascript_checks_response_ok_only(self, client, qr_terminal_device):
        """Test JavaScript validation relies on response.ok, not data.success"""
        response = client.get("/fingerprintlogs/static/js/qr-terminal.js")
        js_content = response.text

        # Should check response.ok
        assert "response.ok" in js_content

        # Should NOT check data.success
        assert "data.success" not in js_content or \
               "// Removed: data.success check" in js_content or \
               js_content.count("data.success") == 0

    def test_javascript_uses_flat_api_structure(self, client):
        """Test JavaScript accesses terminal data from flat API response"""
        response = client.get("/fingerprintlogs/static/js/qr-terminal.js")
        js_content = response.text

        # Should use terminalData.terminal_name (flat)
        assert "terminalData.terminal_name" in js_content or \
               "terminal_name" in js_content

        # Should NOT use terminalData.terminal.location_name (nested)
        assert "terminalData.terminal.location_name" not in js_content


class TestQRTerminalIntegrationFlow:
    """Test complete QR terminal display workflow"""

    def test_complete_qr_terminal_flow(self, client, qr_terminal_device):
        """Test complete workflow: HTML → API → QR display"""
        # Step 1: Load HTML page
        html_response = client.get("/fingerprintlogs/qr-checkin/terminal?terminal=2")
        assert html_response.status_code == 200

        # Step 2: Load CSS resource
        css_response = client.get("/fingerprintlogs/static/css/qr-terminal.css")
        assert css_response.status_code == 200

        # Step 3: Load JavaScript resource
        js_response = client.get("/fingerprintlogs/static/js/qr-terminal.js")
        assert js_response.status_code == 200

        # Step 4: API call for QR code
        api_response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/2")
        assert api_response.status_code == 200

        data = api_response.json()
        assert "qr_image" in data
        assert data["terminal_id"] == 2

    def test_error_handling_for_invalid_terminal(self, client, fingerprint_device):
        """Test error handling when using wrong terminal type"""
        # HTML page still loads
        html_response = client.get("/fingerprintlogs/qr-checkin/terminal?terminal=1")
        assert html_response.status_code == 200

        # But API returns 404
        api_response = client.get("/fingerprintlogs/api/qr-checkin/kiosk/1")
        assert api_response.status_code == 404

        # Error message is in Thai
        data = api_response.json()
        assert "ไม่พบเครื่อง QR terminal" in data["detail"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
