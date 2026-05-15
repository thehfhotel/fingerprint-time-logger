"""
Test API endpoints
"""

import pytest


def test_root_endpoint_mounted(mounted_test_client):
    """Test that the root endpoint returns application info"""
    response = mounted_test_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "dashboard" in data


def test_dashboard_endpoint(test_client):
    """Dashboard HTML now lives on the mounted fingerprint_app under /fingerprintlogs/."""
    response = test_client.get("/fingerprintlogs/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_health_endpoint(test_client):
    """Health endpoint lives on fingerprint_app (mounted under /fingerprintlogs)."""
    response = test_client.get("/fingerprintlogs/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"


def test_device_health_endpoint(test_client):
    """Test device health endpoint"""
    response = test_client.get("/api/private/devices/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


def test_attendance_endpoint(test_client, test_company_setup):
    """Test attendance data endpoint"""
    response = test_client.get("/api/private/attendance/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "records" in data
    assert "total" in data
    assert isinstance(data["records"], list)


def test_employees_endpoint(test_client, test_company_setup):
    """Test employees endpoint"""
    response = test_client.get("/api/private/employees/")
    assert response.status_code == 200
    data = response.json()
    assert "employees" in data
    assert isinstance(data["employees"], list)


def test_404_endpoint(test_client):
    """Test that non-existent endpoints return 404"""
    response = test_client.get("/api/nonexistent")
    assert response.status_code == 404


def test_static_css_files(test_client):
    """Test that CSS files are served correctly"""
    css_files = ["base.css", "dashboard.css", "modal.css"]

    for css_file in css_files:
        response = test_client.get(f"/static/css/{css_file}")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]
