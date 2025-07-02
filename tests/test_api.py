"""
Test API endpoints
"""

import pytest
from fastapi.testclient import TestClient
from app.main_unified import app

client = TestClient(app)


def test_root_endpoint():
    """Test that the root endpoint serves the dashboard"""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_health_endpoint():
    """Test device health endpoint"""
    response = client.get("/api/devices/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


def test_attendance_endpoint():
    """Test attendance data endpoint"""
    response = client.get("/api/attendance/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_employees_endpoint():
    """Test employees endpoint"""
    response = client.get("/api/employees/thai-names/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_export_formats_endpoint():
    """Test export formats endpoint"""
    response = client.get("/api/export/formats")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert "csv" in data


def test_404_endpoint():
    """Test that non-existent endpoints return 404"""
    response = client.get("/api/nonexistent")
    assert response.status_code == 404


def test_static_css_files():
    """Test that CSS files are served correctly"""
    css_files = ["base.css", "dashboard.css", "modal.css"]
    
    for css_file in css_files:
        response = client.get(f"/static/css/{css_file}")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]