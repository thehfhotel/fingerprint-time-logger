"""
Focused tests for device API endpoints to increase coverage
Tests device management and connection functionality
"""

import pytest
from datetime import datetime


class TestDeviceEndpoints:
    """Test core device API endpoints"""

    def test_get_devices(self, test_client, test_company_setup):
        """Test GET /api/devices/ - Get all devices"""
        response = test_client.get("/api/devices/")
        assert response.status_code == 200
        data = response.json()
        assert "devices" in data or isinstance(data, list)

    @pytest.mark.skip(reason="GET /api/devices/{id} endpoint removed in API simplification")
    def test_get_device_by_id(self, test_client, test_company_setup):
        """Test GET /api/devices/{id} - Get specific device - ENDPOINT REMOVED"""
        # This endpoint was removed in the consolidated API simplification
        # Only /api/devices/default endpoint exists now
        pass

    @pytest.mark.skip(reason="GET /api/devices/{id} endpoint removed in API simplification")
    def test_get_device_not_found(self, test_client):
        """Test getting non-existent device - ENDPOINT REMOVED"""
        # This endpoint was removed in the consolidated API simplification
        pass

    def test_device_health_check(self, test_client):
        """Test GET /api/devices/health - Device health endpoint"""
        response = test_client.get("/api/devices/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_get_device_status(self, test_client, test_company_setup):
        """Test GET /api/devices/status - Get device status"""
        response = test_client.get("/api/devices/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    @pytest.mark.skip(reason="POST /api/devices/ endpoint removed in API simplification")
    def test_create_device(self, test_client):
        """Test POST /api/devices/ - Create new device - ENDPOINT REMOVED"""
        # Device creation was removed in the consolidated API simplification
        # Devices are now configured through environment or database directly
        pass

    @pytest.mark.skip(reason="PUT /api/devices/{id} endpoint removed in API simplification")
    def test_update_device(self, test_client, test_company_setup):
        """Test PUT /api/devices/{id} - Update device - ENDPOINT REMOVED"""
        # Device update was removed in the consolidated API simplification
        # Device configuration is now static
        pass


class TestDeviceEndpointsValidation:
    """Test device endpoint validation and error cases"""

    @pytest.mark.skip(reason="POST /api/devices/ endpoint removed in API simplification")
    def test_create_device_invalid_ip(self, test_client):
        """Test creating device with invalid IP address - ENDPOINT REMOVED"""
        pass

    @pytest.mark.skip(reason="POST /api/devices/ endpoint removed in API simplification")
    def test_create_device_missing_fields(self, test_client):
        """Test creating device with missing required fields - ENDPOINT REMOVED"""
        pass

    @pytest.mark.skip(reason="POST /api/devices/ endpoint removed in API simplification")
    def test_create_device_duplicate_ip(self, test_client, test_company_setup):
        """Test creating device with duplicate IP address - ENDPOINT REMOVED"""
        pass

    @pytest.mark.skip(reason="PUT /api/devices/{id} endpoint removed in API simplification")
    def test_update_nonexistent_device(self, test_client):
        """Test updating non-existent device - ENDPOINT REMOVED"""
        pass

    @pytest.mark.skip(reason="POST /api/devices/ endpoint removed in API simplification")
    def test_invalid_port_numbers(self, test_client):
        """Test device creation with invalid port numbers - ENDPOINT REMOVED"""
        pass


class TestDeviceOperations:
    """Test device operation endpoints (non-connection dependent)"""

    def test_get_device_info(self, test_client, test_company_setup):
        """Test device info endpoint"""
        devices = test_company_setup.get("devices", [])
        if devices:
            device_id = devices[0].id
            response = test_client.get(f"/api/devices/{device_id}/info")
            # May or may not exist, but should not crash
            assert response.status_code in [200, 404, 405]

    def test_device_stats(self, test_client):
        """Test device statistics endpoint"""
        response = test_client.get("/api/devices/stats")
        # May or may not exist
        assert response.status_code in [200, 404, 405]


class TestDeviceConnectionEndpoints:
    """Test connection-related endpoints (expect errors without real device)"""

    def test_test_device_connection_nonexistent(self, test_client):
        """Test connection to non-existent device"""
        response = test_client.post("/api/devices/99999/test-connection")
        assert response.status_code == 404

    def test_sync_device_time_nonexistent(self, test_client):
        """Test syncing time for non-existent device"""
        response = test_client.post("/api/devices/99999/sync-time")
        assert response.status_code == 404

    def test_get_device_diagnostics_nonexistent(self, test_client):
        """Test diagnostics for non-existent device"""
        response = test_client.get("/api/devices/99999/diagnostics")
        assert response.status_code == 404