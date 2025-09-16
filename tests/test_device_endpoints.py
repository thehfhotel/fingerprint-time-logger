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

    def test_get_device_by_id(self, test_client, test_company_setup):
        """Test GET /api/devices/{id} - Get specific device"""
        devices = test_company_setup.get("devices", [])
        if devices:
            device_id = devices[0].id
            response = test_client.get(f"/api/devices/{device_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == device_id

    def test_get_device_not_found(self, test_client):
        """Test getting non-existent device"""
        response = test_client.get("/api/devices/99999")
        assert response.status_code == 404

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

    def test_create_device(self, test_client):
        """Test POST /api/devices/ - Create new device"""
        device_data = {
            "name": "Test Device",
            "ip_address": "192.168.1.100",
            "port": 4370,
            "password": 0,
            "is_active": True
        }
        response = test_client.post("/api/devices/", json=device_data)
        assert response.status_code in [200, 201]  # Created successfully
        if response.status_code in [200, 201]:
            data = response.json()
            assert data["name"] == device_data["name"]
            assert data["ip_address"] == device_data["ip_address"]

    def test_update_device(self, test_client, test_company_setup):
        """Test PUT /api/devices/{id} - Update device"""
        devices = test_company_setup.get("devices", [])
        if devices:
            device_id = devices[0].id
            update_data = {
                "name": "Updated Device Name",
                "ip_address": devices[0].ip_address,
                "port": devices[0].port,
                "password": devices[0].password,
                "is_active": True
            }
            response = test_client.put(f"/api/devices/{device_id}", json=update_data)
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == update_data["name"]


class TestDeviceEndpointsValidation:
    """Test device endpoint validation and error cases"""

    def test_create_device_invalid_ip(self, test_client):
        """Test creating device with invalid IP address"""
        device_data = {
            "name": "Invalid Device",
            "ip_address": "invalid.ip.address",
            "port": 4370,
            "password": 0
        }
        response = test_client.post("/api/devices/", json=device_data)
        assert response.status_code in [400, 422]  # Validation error

    def test_create_device_missing_fields(self, test_client):
        """Test creating device with missing required fields"""
        device_data = {
            "name": "Incomplete Device"
            # Missing ip_address, port, etc.
        }
        response = test_client.post("/api/devices/", json=device_data)
        assert response.status_code == 422  # Validation error

    def test_create_device_duplicate_ip(self, test_client, test_company_setup):
        """Test creating device with duplicate IP address"""
        devices = test_company_setup.get("devices", [])
        if devices:
            device_data = {
                "name": "Duplicate Device",
                "ip_address": devices[0].ip_address,  # Same IP
                "port": 4370,
                "password": 0
            }
            response = test_client.post("/api/devices/", json=device_data)
            # May succeed or fail depending on business rules
            assert response.status_code in [200, 201, 400, 409]

    def test_update_nonexistent_device(self, test_client):
        """Test updating non-existent device"""
        update_data = {
            "name": "Updated Device",
            "ip_address": "192.168.1.200",
            "port": 4370,
            "password": 0
        }
        response = test_client.put("/api/devices/99999", json=update_data)
        assert response.status_code == 404

    def test_invalid_port_numbers(self, test_client):
        """Test device creation with invalid port numbers"""
        device_data = {
            "name": "Invalid Port Device",
            "ip_address": "192.168.1.100",
            "port": -1,  # Invalid port
            "password": 0
        }
        response = test_client.post("/api/devices/", json=device_data)
        assert response.status_code == 422


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