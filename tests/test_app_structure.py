"""
Test the FastAPI application structure

After the Oct-2025 routing reorg, all API routers live on the root ``app``
and ``fingerprint_app`` is mounted at ``/fingerprintlogs`` to serve legacy
admin dashboard HTML/static only. ``test_client`` and ``mounted_test_client``
are therefore both ``TestClient(app)`` under the hood.
"""

import pytest
from fastapi.testclient import TestClient


class TestAppStructureFix:
    """Validate the post-reorg routing layout."""

    def test_root_api_endpoints(self, test_client):
        """API endpoints live on the root app under /api/private/*."""
        response = test_client.get("/api/private/employees/")
        assert response.status_code == 200
        data = response.json()
        assert "employees" in data

    def test_dashboard_under_mount(self, test_client):
        """Dashboard HTML is served by the mounted fingerprint_app."""
        response = test_client.get("/fingerprintlogs/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_health_under_mount(self, test_client):
        """Health check is served by the mounted fingerprint_app."""
        response = test_client.get("/fingerprintlogs/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_root_redirect_metadata(self, mounted_test_client):
        """Root ``/`` on the root app returns JSON pointing at /fingerprintlogs/."""
        response = mounted_test_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["dashboard"] == "/fingerprintlogs/"

    def test_database_dependency_injection(self, test_client, test_employee):
        """Verify dependency override flows through to API responses."""
        response = test_client.get("/api/private/employees/")
        assert response.status_code == 200
        data = response.json()
        assert len(data["employees"]) >= 1

        employee_found = any(
            emp["badge_number"] == test_employee.badge_number
            for emp in data["employees"]
        )
        assert employee_found, (
            f"Test employee {test_employee.badge_number} not found in API response"
        )

    def test_api_paths_only_under_private(self, test_client):
        """Legacy unprefixed ``/api/...`` paths should 404 after the reorg."""
        legacy = test_client.get("/api/employees/")
        assert legacy.status_code == 404

        legacy_under_mount = test_client.get("/fingerprintlogs/api/employees/")
        assert legacy_under_mount.status_code == 404

    def test_404_handling(self, test_client):
        """Unknown paths return 404 on both root and mounted prefixes."""
        assert test_client.get("/api/nonexistent").status_code == 404
        assert test_client.get("/fingerprintlogs/api/nonexistent").status_code == 404

    def test_static_files_root_and_mounted(self, test_client):
        """Static CSS is served from both the root mount and the fingerprintlogs mount."""
        root_resp = test_client.get("/static/css/base.css")
        assert root_resp.status_code == 200
        assert "text/css" in root_resp.headers.get("content-type", "")

        mounted_resp = test_client.get("/fingerprintlogs/static/css/base.css")
        assert mounted_resp.status_code == 200
        assert "text/css" in mounted_resp.headers.get("content-type", "")

    @pytest.mark.skip(
        reason="Dashboard /ws now requires admin_session_token cookie; "
        "exercised in security/auth tests, not here."
    )
    def test_websocket_dashboard(self, test_client):
        """Dashboard WebSocket gates on admin session and is covered elsewhere."""
        pass


# Quick validation tests that can run independently


def test_quick_validation_root_api(test_client):
    """Quick test: root app serves /api/private/* APIs."""
    response = test_client.get("/api/private/employees/")
    assert response.status_code == 200


def test_quick_validation_mounted_dashboard(mounted_test_client):
    """Quick test: mounted fingerprint_app serves /fingerprintlogs/ dashboard HTML."""
    response = mounted_test_client.get("/fingerprintlogs/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_quick_validation_root_returns_json(test_client):
    """Root ``/`` on the root app returns JSON metadata, not HTML."""
    response = test_client.get("/")
    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")
    data = response.json()
    assert "dashboard" in data
    assert data["dashboard"] == "/fingerprintlogs/"
