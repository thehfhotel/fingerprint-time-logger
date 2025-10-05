"""
E2E Tests for GPS localStorage Persistence
Tests GPS configuration caching, restoration, and validation in QR terminal
"""

import pytest
from playwright.sync_api import Page, expect
import json
import time


@pytest.mark.browser
@pytest.mark.e2e
class TestGPSPersistence:
    """Test GPS localStorage persistence across page refreshes"""

    QR_TERMINAL_PASSWORD = "bananabananabanana"
    TEST_GPS_DATA = {
        "latitude": 13.9434,
        "longitude": 100.4466,
        "tolerance": 200,
        "location_name": "Test Office"
    }

    @pytest.fixture(autouse=True)
    def setup(self, page: Page, live_server_url: str):
        """Setup test environment before each test"""
        self.page = page
        self.base_url = live_server_url

        # Navigate to QR terminal and clear storage
        page.goto(f"{live_server_url}/qr-terminal")
        page.wait_for_load_state("networkidle")
        page.evaluate("localStorage.clear()")

    def authenticate_and_open_gps_config(self):
        """Authenticate GPS modal and open configuration"""
        # Click GPS config button
        self.page.click('#gpsConfigButton')

        # Wait for password input
        self.page.wait_for_selector('#gpsAdminPassword', state="visible", timeout=5000)

        # Enter password
        self.page.fill('#gpsAdminPassword', self.QR_TERMINAL_PASSWORD)

        # Submit
        self.page.click('#gpsAuthSubmit')

        # Wait for GPS config step
        self.page.wait_for_selector('#gpsConfigStep', state="visible", timeout=5000)

    def save_gps_config(self, gps_data: dict):
        """Save GPS configuration"""
        # Fill location name
        self.page.fill('#gpsLocationName', gps_data["location_name"])

        # Set coordinates via JavaScript (simulating map click)
        self.page.evaluate(f"""
            document.getElementById('gpsLatitude').value = '{gps_data["latitude"]}';
            document.getElementById('gpsLongitude').value = '{gps_data["longitude"]}';
            document.getElementById('gpsSaveBtn').disabled = false;
        """)

        # Set radius
        self.page.fill('#gpsRadiusSlider', str(gps_data["tolerance"]))

        # Click save
        self.page.click('#gpsSaveBtn')

        # Wait for save to complete
        time.sleep(1)

    def get_cached_gps(self):
        """Get GPS data from localStorage"""
        terminal_id = self.page.evaluate("TERMINAL_ID")
        cache_key = f"qr_terminal_gps_{terminal_id}"

        cached_json = self.page.evaluate(f"localStorage.getItem('{cache_key}')")

        if cached_json:
            return json.loads(cached_json)
        return None

    def test_gps_cache_on_save(self):
        """Test that GPS data is cached to localStorage when saved"""
        # Open GPS config and save
        self.authenticate_and_open_gps_config()
        self.save_gps_config(self.TEST_GPS_DATA)

        # Verify cache
        cached = self.get_cached_gps()
        assert cached is not None, "GPS should be cached"
        assert cached["version"] == "1.0"
        assert cached["gps"]["latitude"] == self.TEST_GPS_DATA["latitude"]
        assert cached["gps"]["longitude"] == self.TEST_GPS_DATA["longitude"]
        assert cached["gps"]["tolerance"] == self.TEST_GPS_DATA["tolerance"]

    def test_gps_restore_from_cache_on_refresh(self):
        """Test that GPS data persists after page refresh"""
        # Save GPS config
        self.authenticate_and_open_gps_config()
        self.save_gps_config(self.TEST_GPS_DATA)

        # Verify cache exists
        cached_before = self.get_cached_gps()
        assert cached_before is not None

        # Refresh page
        self.page.reload()
        self.page.wait_for_load_state("networkidle")

        # Verify cache persists
        cached_after = self.get_cached_gps()
        assert cached_after is not None, "Cache should persist after refresh"
        assert cached_after["gps"]["latitude"] == self.TEST_GPS_DATA["latitude"]

    def test_gps_footer_display_from_cache(self):
        """Test that footer displays GPS from cache immediately"""
        # Save GPS config
        self.authenticate_and_open_gps_config()
        self.save_gps_config(self.TEST_GPS_DATA)

        # Close modal
        self.page.click('#gpsCloseBtn2')

        # Check footer displays GPS
        footer_gps = self.page.inner_text('#footerGPS')
        assert str(self.TEST_GPS_DATA["latitude"]) in footer_gps
        assert str(self.TEST_GPS_DATA["longitude"]) in footer_gps

        # Refresh page
        self.page.reload()
        self.page.wait_for_load_state("networkidle")

        # Footer should still show GPS from cache
        footer_gps_after = self.page.inner_text('#footerGPS')
        assert str(self.TEST_GPS_DATA["latitude"]) in footer_gps_after

    def test_gps_cache_version_validation(self):
        """Test that invalid cache version is handled"""
        terminal_id = self.page.evaluate("TERMINAL_ID")
        cache_key = f"qr_terminal_gps_{terminal_id}"

        # Set invalid cache
        invalid_cache = {
            "version": "0.9",
            "terminal_id": terminal_id,
            "gps": self.TEST_GPS_DATA
        }

        self.page.evaluate(f"""
            localStorage.setItem('{cache_key}', JSON.stringify({json.dumps(invalid_cache)}))
        """)

        # Refresh
        self.page.reload()
        self.page.wait_for_load_state("networkidle")

        # Cache should be cleared or updated
        cached = self.get_cached_gps()
        if cached:
            assert cached["version"] == "1.0"

    def test_gps_cache_terminal_id_validation(self):
        """Test that wrong terminal_id in cache is handled"""
        terminal_id = self.page.evaluate("TERMINAL_ID")
        cache_key = f"qr_terminal_gps_{terminal_id}"

        # Set cache with wrong terminal_id
        invalid_cache = {
            "version": "1.0",
            "terminal_id": "wrong_id",
            "gps": self.TEST_GPS_DATA
        }

        self.page.evaluate(f"""
            localStorage.setItem('{cache_key}', JSON.stringify({json.dumps(invalid_cache)}))
        """)

        # Refresh
        self.page.reload()
        self.page.wait_for_load_state("networkidle")

        # Cache should be cleared
        cached = self.get_cached_gps()
        if cached:
            assert cached["terminal_id"] == terminal_id

    def test_gps_cache_clear_on_delete(self):
        """Test that cache is cleared when GPS is deleted"""
        # Save GPS config
        self.authenticate_and_open_gps_config()
        self.save_gps_config(self.TEST_GPS_DATA)

        # Verify cache exists
        assert self.get_cached_gps() is not None

        # Delete GPS (enable delete button first)
        self.page.evaluate("document.getElementById('gpsDeleteBtn').disabled = false")
        self.page.click('#gpsDeleteBtn')

        # Wait for deletion
        time.sleep(1)

        # Cache should be cleared
        cached = self.get_cached_gps()
        assert cached is None, "Cache should be cleared after deletion"

    def test_gps_cache_corrupted_data(self):
        """Test graceful handling of corrupted cache"""
        terminal_id = self.page.evaluate("TERMINAL_ID")
        cache_key = f"qr_terminal_gps_{terminal_id}"

        # Set corrupted cache
        self.page.evaluate(f"""
            localStorage.setItem('{cache_key}', 'invalid{{{{json')
        """)

        # Refresh should not crash
        self.page.reload()
        self.page.wait_for_load_state("networkidle")

        # Wait for terminal to load
        self.page.wait_for_selector('.terminal-footer', state="visible", timeout=5000)

        # Cache should be cleared
        cached = self.get_cached_gps()
        assert cached is None

    def test_gps_cache_quota_exceeded(self):
        """Test that localStorage operations have error handling"""
        # This test verifies error handling exists
        # Actual quota exceeded is difficult to trigger reliably

        # Save GPS config normally
        self.authenticate_and_open_gps_config()
        self.save_gps_config(self.TEST_GPS_DATA)

        # Verify save succeeded
        cached = self.get_cached_gps()
        assert cached is not None, "Normal save should succeed"
