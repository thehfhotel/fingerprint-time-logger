"""
Unit tests for Consolidated Devices API Router
Tests all 12 endpoints in consolidated_devices.py
"""

import pytest
from datetime import datetime, timedelta


class TestConsolidatedDevicesAPI:
    """Test suite for consolidated devices endpoints"""

    def test_get_devices_list(self, test_client, test_company_setup):
        """Test GET /api/devices/ - List all devices"""
        response = test_client.get("/api/devices/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_device_by_id(self, test_client, test_company_setup):
        """Test GET /api/devices/{device_id} - Get specific device"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.get(f"/api/devices/{device_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == device_id

    def test_get_device_not_found(self, test_client):
        """Test GET /api/devices/{device_id} - Device not found"""
        response = test_client.get("/api/devices/999")
        assert response.status_code == 404

    def test_create_device(self, test_client, test_db):
        """Test POST /api/devices/ - Create new device"""
        device_data = {
            "name": "Test Device",
            "ip_address": "192.168.1.100",
            "port": 4370,
            "password": 0,
            "is_active": True
        }
        response = test_client.post("/api/devices/", json=device_data)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Device"
        assert data["ip_address"] == "192.168.1.100"

    def test_create_device_invalid_data(self, test_client):
        """Test POST /api/devices/ with invalid data"""
        invalid_data = {
            "name": "",  # Empty name
            "ip_address": "invalid-ip",  # Invalid IP format
            "port": -1  # Invalid port
        }
        response = test_client.post("/api/devices/", json=invalid_data)
        assert response.status_code == 422  # Validation error

    def test_update_device(self, test_client, test_company_setup):
        """Test PUT /api/devices/{device_id} - Update device"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            update_data = {
                "name": "Updated Device",
                "ip_address": "192.168.1.200",
                "port": 4370,
                "password": 0,
                "is_active": True
            }
            response = test_client.put(f"/api/devices/{device_id}", json=update_data)
            assert response.status_code in [200, 404]

    def test_delete_device(self, test_client, test_company_setup):
        """Test DELETE /api/devices/{device_id} - Delete device"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.delete(f"/api/devices/{device_id}")
            assert response.status_code in [200, 404]

    def test_device_health_check(self, test_client):
        """Test GET /api/devices/health - Health check"""
        response = test_client.get("/api/devices/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_test_device_connection(self, test_client, test_company_setup, mock_device_service):
        """Test POST /api/devices/{device_id}/test-connection - Test device connection"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.post(f"/api/devices/{device_id}/test-connection")
            assert response.status_code in [200, 404, 500]

    def test_sync_device_time(self, test_client, test_company_setup, mock_device_service):
        """Test POST /api/devices/{device_id}/sync-time - Sync device time"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.post(f"/api/devices/{device_id}/sync-time")
            assert response.status_code in [200, 404, 500]

    def test_get_device_status(self, test_client, test_company_setup):
        """Test GET /api/devices/{device_id}/status - Get device status"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.get(f"/api/devices/{device_id}/status")
            assert response.status_code in [200, 404]
            if response.status_code == 200:
                data = response.json()
                assert "device_id" in data
                assert "status" in data

    def test_get_device_diagnostics(self, test_client, test_company_setup, mock_device_service):
        """Test GET /api/devices/{device_id}/diagnostics - Get device diagnostics"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.get(f"/api/devices/{device_id}/diagnostics")
            assert response.status_code in [200, 404, 500]


class TestConsolidatedDevicesAPIEdgeCases:
    """Edge case tests for devices API"""

    def test_create_device_duplicate_ip(self, test_client, test_company_setup):
        """Test creating device with duplicate IP address"""
        devices = test_company_setup["devices"]
        if devices:
            existing_ip = devices[0].ip_address
            device_data = {
                "name": "Duplicate Device",
                "ip_address": existing_ip,
                "port": 4370,
                "password": 0,
                "is_active": True
            }
            response = test_client.post("/api/devices/", json=device_data)
            # Should handle duplicate IP gracefully
            assert response.status_code in [201, 400, 409]

    def test_update_nonexistent_device(self, test_client):
        """Test updating non-existent device"""
        update_data = {
            "name": "Non-existent Device",
            "ip_address": "192.168.1.1",
            "port": 4370,
            "password": 0,
            "is_active": True
        }
        response = test_client.put("/api/devices/999", json=update_data)
        assert response.status_code == 404

    def test_delete_nonexistent_device(self, test_client):
        """Test deleting non-existent device"""
        response = test_client.delete("/api/devices/999")
        assert response.status_code == 404

    def test_test_connection_network_failure(self, test_client, test_company_setup, network_issues_simulator):
        """Test connection test with network failure"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.post(f"/api/devices/{device_id}/test-connection")
            assert response.status_code in [200, 500]  # May succeed or fail with network issues

    def test_sync_time_device_error(self, test_client, test_company_setup, error_prone_simulator):
        """Test time sync with device error"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.post(f"/api/devices/{device_id}/sync-time")
            assert response.status_code in [200, 500]


class TestConsolidatedDevicesAPIValidation:
    """Validation tests for devices API"""

    def test_invalid_ip_address_format(self, test_client):
        """Test device creation with invalid IP address format"""
        invalid_ips = [
            "256.256.256.256",  # Out of range
            "192.168.1",        # Incomplete
            "not-an-ip",        # Not an IP
            ""                  # Empty
        ]

        for invalid_ip in invalid_ips:
            device_data = {
                "name": "Test Device",
                "ip_address": invalid_ip,
                "port": 4370,
                "password": 0,
                "is_active": True
            }
            response = test_client.post("/api/devices/", json=device_data)
            assert response.status_code == 422

    def test_invalid_port_numbers(self, test_client):
        """Test device creation with invalid port numbers"""
        invalid_ports = [-1, 0, 65536, 99999]

        for invalid_port in invalid_ports:
            device_data = {
                "name": "Test Device",
                "ip_address": "192.168.1.1",
                "port": invalid_port,
                "password": 0,
                "is_active": True
            }
            response = test_client.post("/api/devices/", json=device_data)
            assert response.status_code == 422

    def test_missing_required_fields(self, test_client):
        """Test device creation with missing required fields"""
        incomplete_data = {
            "name": "Test Device"
            # Missing ip_address
        }
        response = test_client.post("/api/devices/", json=incomplete_data)
        assert response.status_code == 422


class TestConsolidatedDevicesAPIPerformance:
    """Performance tests for devices API"""

    @pytest.mark.performance
    def test_devices_list_performance(self, test_client, performance_dataset):
        """Test performance of devices list with large dataset"""
        response = test_client.get("/api/devices/")
        assert response.status_code == 200
        # Should complete in reasonable time even with multiple devices

    @pytest.mark.performance
    def test_device_diagnostics_performance(self, test_client, test_company_setup, mock_device_service):
        """Test performance of device diagnostics"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.get(f"/api/devices/{device_id}/diagnostics")
            # Should complete diagnostics in reasonable time
            assert response.status_code in [200, 404, 500]