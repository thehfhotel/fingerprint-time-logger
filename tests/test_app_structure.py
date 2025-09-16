"""
Test the FastAPI application structure fixes

This validates that both direct and mounted app configurations work correctly.
Key fixes:
1. Test client properly accesses both app structures
2. Database dependency injection works for both configurations
3. URL paths are correct for mounted vs direct access
"""

import pytest
from fastapi.testclient import TestClient


class TestAppStructureFix:
    """Test class to validate app structure fixes"""

    def test_direct_app_basic_endpoints(self, test_client):
        """Test basic endpoints on direct fingerprint_app"""
        # Test dashboard
        response = test_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

        # Test API endpoint
        response = test_client.get("/api/employees/")
        assert response.status_code == 200
        data = response.json()
        assert "employees" in data

        # Test health check
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_mounted_app_basic_endpoints(self, mounted_test_client):
        """Test basic endpoints on mounted app (production structure)"""
        # Test root redirect
        response = mounted_test_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["dashboard"] == "/fingerprintlogs/"

        # Test mounted dashboard
        response = mounted_test_client.get("/fingerprintlogs/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

        # Test mounted API endpoint
        response = mounted_test_client.get("/fingerprintlogs/api/employees/")
        assert response.status_code == 200
        data = response.json()
        assert "employees" in data

        # Test mounted health check
        response = mounted_test_client.get("/fingerprintlogs/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_database_dependency_injection_direct(self, test_client, test_employee):
        """Test that database dependency injection works with direct app"""
        # Create an employee through fixture, then query via API
        response = test_client.get("/api/employees/")
        assert response.status_code == 200
        data = response.json()

        # Should have at least our test employee
        assert len(data["employees"]) >= 1

        # Find our test employee
        employee_found = False
        for emp in data["employees"]:
            if emp["badge_number"] == test_employee.badge_number:
                employee_found = True
                assert emp["english_name"] == test_employee.english_name
                break

        assert employee_found, f"Test employee {test_employee.badge_number} not found in API response"

    def test_database_dependency_injection_mounted(self, mounted_test_client, test_employee):
        """Test that database dependency injection works with mounted app"""
        # Create an employee through fixture, then query via API on mounted app
        response = mounted_test_client.get("/fingerprintlogs/api/employees/")
        assert response.status_code == 200
        data = response.json()

        # Should have at least our test employee
        assert len(data["employees"]) >= 1

        # Find our test employee
        employee_found = False
        for emp in data["employees"]:
            if emp["badge_number"] == test_employee.badge_number:
                employee_found = True
                assert emp["english_name"] == test_employee.english_name
                break

        assert employee_found, f"Test employee {test_employee.badge_number} not found in mounted API response"

    def test_url_path_differences(self, test_client, mounted_test_client):
        """Test that URL paths are correctly different between direct and mounted"""

        # Direct app - API at /api/*
        direct_response = test_client.get("/api/attendance/")
        assert direct_response.status_code == 200

        # Mounted app - API at /fingerprintlogs/api/*
        mounted_response = mounted_test_client.get("/fingerprintlogs/api/attendance/")
        assert mounted_response.status_code == 200

        # Verify the responses have the same structure (both should work)
        direct_data = direct_response.json()
        mounted_data = mounted_response.json()

        assert "records" in direct_data
        assert "records" in mounted_data
        assert "total" in direct_data
        assert "total" in mounted_data

    def test_404_handling_both_apps(self, test_client, mounted_test_client):
        """Test 404 handling works correctly on both app structures"""

        # Test 404 on direct app
        response = test_client.get("/api/nonexistent")
        assert response.status_code == 404

        # Test 404 on mounted app
        response = mounted_test_client.get("/fingerprintlogs/api/nonexistent")
        assert response.status_code == 404

        # Test that direct paths don't work on mounted app root
        response = mounted_test_client.get("/api/employees/")
        assert response.status_code == 404  # Should fail because it's not mounted at root

    def test_static_files_both_apps(self, test_client, mounted_test_client):
        """Test static file serving works on both app structures"""

        # Test static files on direct app
        response = test_client.get("/static/css/base.css")
        assert response.status_code == 200
        assert "text/css" in response.headers.get("content-type", "")

        # Test static files on mounted app
        response = mounted_test_client.get("/fingerprintlogs/static/css/base.css")
        assert response.status_code == 200
        assert "text/css" in response.headers.get("content-type", "")

    def test_websocket_both_apps(self, test_client, mounted_test_client):
        """Test WebSocket endpoints work on both app structures"""

        # Test WebSocket on direct app
        with test_client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "ping"})
            data = websocket.receive_json()
            assert data["type"] == "pong"

        # Test WebSocket on mounted app
        with mounted_test_client.websocket_connect("/fingerprintlogs/ws") as websocket:
            websocket.send_json({"type": "ping"})
            data = websocket.receive_json()
            assert data["type"] == "pong"


# Quick validation tests that can run independently

def test_quick_validation_direct_app(test_client):
    """Quick test to validate direct app works"""
    response = test_client.get("/api/employees/")
    assert response.status_code == 200


def test_quick_validation_mounted_app(mounted_test_client):
    """Quick test to validate mounted app works"""
    response = mounted_test_client.get("/fingerprintlogs/api/employees/")
    assert response.status_code == 200


def test_quick_validation_root_difference(test_client, mounted_test_client):
    """Quick test to validate the key difference between apps"""

    # Direct app root serves dashboard
    direct_response = test_client.get("/")
    assert direct_response.status_code == 200
    assert "text/html" in direct_response.headers.get("content-type", "")

    # Mounted app root serves JSON redirect info
    mounted_response = mounted_test_client.get("/")
    assert mounted_response.status_code == 200
    assert "application/json" in mounted_response.headers.get("content-type", "")

    mounted_data = mounted_response.json()
    assert "dashboard" in mounted_data
    assert mounted_data["dashboard"] == "/fingerprintlogs/"