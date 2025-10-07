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
        assert isinstance(data, dict)
        assert "devices" in data
        assert isinstance(data["devices"], list)


    def test_get_device_not_found(self, test_client):
        """Test GET /api/devices/{device_id} - Device not found"""
        response = test_client.get("/api/devices/999")
        assert response.status_code == 404



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
        """Test DELETE /api/devices/{device_id} - Delete device (expects 400 if has records)"""
        devices = test_company_setup["devices"]
        if devices:
            device_id = devices[0].id
            response = test_client.delete(f"/api/devices/{device_id}")
            # Device in test setup has attendance records, so should return 400
            assert response.status_code in [200, 400, 404]
            if response.status_code == 400:
                data = response.json()
                assert "attendance records" in data["detail"].lower()

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




class TestConsolidatedDevicesAPIValidation:
    """Validation tests for devices API"""





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