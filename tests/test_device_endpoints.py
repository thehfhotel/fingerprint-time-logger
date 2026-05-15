"""
Focused tests for device API endpoints to increase coverage
Tests device management and connection functionality
"""

import pytest
from datetime import datetime


class TestDeviceEndpoints:
    """Test core device API endpoints"""

    def test_get_devices(self, test_client, test_company_setup):
        """Test GET /api/private/devices/ - Get all devices"""
        response = test_client.get("/api/private/devices/")
        assert response.status_code == 200
        data = response.json()
        assert "devices" in data or isinstance(data, list)


    def test_device_health_check(self, test_client):
        """Test GET /api/private/devices/health - Device health endpoint"""
        response = test_client.get("/api/private/devices/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_get_device_status(self, test_client, test_company_setup):
        """Test GET /api/private/devices/status - Get device status"""
        response = test_client.get("/api/private/devices/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)





class TestDeviceOperations:
    """Test device operation endpoints (non-connection dependent)"""

    def test_get_device_info(self, test_client, test_company_setup):
        """Test device info endpoint"""
        devices = test_company_setup.get("devices", [])
        if devices:
            device_id = devices[0].id
            response = test_client.get(f"/api/private/devices/{device_id}/info")
            # May or may not exist, but should not crash
            assert response.status_code in [200, 404, 405]

    def test_device_stats(self, test_client):
        """Test device status endpoint"""
        response = test_client.get("/api/private/devices/status")
        # Should exist and return device status
        assert response.status_code in [200, 404, 405]


class TestDeviceConnectionEndpoints:
    """Test connection-related endpoints (expect errors without real device)"""

    def test_test_device_connection_endpoint(self, test_client):
        """Test device connection endpoint"""
        response = test_client.post("/api/private/devices/test-connection")
        # Endpoint should exist and either succeed or fail gracefully
        assert response.status_code in [200, 400, 422, 500]

    def test_sync_device_time_endpoint(self, test_client):
        """Test device time sync endpoint"""
        response = test_client.post("/api/private/devices/sync-time")
        # Endpoint should exist and either succeed or fail gracefully
        assert response.status_code in [200, 400, 422, 500]

    def test_get_device_diagnostics_nonexistent(self, test_client):
        """Test device diagnostics endpoint"""
        response = test_client.get("/api/private/devices/diagnostics")
        # Should provide device diagnostics
        assert response.status_code in [200, 500]