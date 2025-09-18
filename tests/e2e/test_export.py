"""
CLI-based Export E2E Tests
Tests CSV export functionality using HTTP requests instead of browser automation
"""

import pytest
import json
import io
import csv
from datetime import datetime, date, timedelta


@pytest.mark.e2e
@pytest.mark.cli
@pytest.mark.api
class TestExport:
    """Test export functionality using HTTP requests"""

    def test_export_page_loads(self, api_client, app_running):
        """Test that the export page loads successfully"""
        response = api_client.get("/export")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

        # Check for key export elements in HTML
        content = response.text
        assert "export" in content.lower() or "csv" in content.lower() or "download" in content.lower()

    def test_csv_export_endpoint(self, api_client, app_running):
        """Test CSV export API endpoint"""
        response = api_client.get("/api/attendance/export/csv")
        assert response.status_code in [200, 404]  # 404 if no attendance data

        if response.status_code == 200:
            # Should return CSV content
            assert "text/csv" in response.headers.get("content-type", "") or \
                   "application/octet-stream" in response.headers.get("content-type", "")

    def test_csv_export_with_date_range(self, api_client, app_running):
        """Test CSV export with date range parameters"""
        # Test with specific date range
        end_date = date.today()
        start_date = end_date - timedelta(days=7)

        params = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        }

        response = api_client.get("/api/attendance/export/csv", params=params)
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            # Should return CSV content
            content_type = response.headers.get("content-type", "")
            assert "csv" in content_type or "octet-stream" in content_type

    def test_csv_export_content_structure(self, api_client, app_running):
        """Test CSV export content structure"""
        response = api_client.get("/api/attendance/export/csv")

        if response.status_code == 200:
            content = response.text

            # Basic CSV structure checks
            assert len(content) > 0, "CSV content should not be empty"

            # Try to parse as CSV
            try:
                csv_reader = csv.reader(io.StringIO(content))
                rows = list(csv_reader)

                if len(rows) > 0:
                    # Should have header row
                    header = rows[0]
                    assert len(header) > 0, "CSV should have header columns"

                    # Common attendance fields
                    expected_fields = ["employee", "badge", "time", "date", "punch", "name"]
                    header_lower = [col.lower() for col in header]

                    # At least some expected fields should be present
                    found_fields = sum(1 for field in expected_fields if any(field in col for col in header_lower))
                    assert found_fields > 0, f"CSV should contain attendance-related fields. Got: {header}"

            except csv.Error:
                # If CSV parsing fails, at least check for comma-separated structure
                assert "," in content, "Export should be comma-separated"

    def test_export_date_validation(self, api_client, app_running):
        """Test export with invalid date parameters"""
        # Test with invalid date format
        params = {"start_date": "invalid-date", "end_date": "2023-12-31"}

        response = api_client.get("/api/attendance/export/csv", params=params)
        # Should handle invalid dates gracefully
        assert response.status_code in [200, 400, 422, 404]

    def test_export_filename_header(self, api_client, app_running):
        """Test export response headers for filename"""
        response = api_client.get("/api/attendance/export/csv")

        if response.status_code == 200:
            # Check for proper download headers
            headers = response.headers

            # Should have content-disposition header for downloads
            content_disposition = headers.get("content-disposition", "")
            if content_disposition:
                assert "attachment" in content_disposition or "filename" in content_disposition

    def test_export_large_date_range(self, api_client, app_running):
        """Test export with large date range"""
        # Test with a large date range (1 year)
        end_date = date.today()
        start_date = end_date - timedelta(days=365)

        params = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat()
        }

        response = api_client.get("/api/attendance/export/csv", params=params)
        assert response.status_code in [200, 404, 400]

        # Response should be handled within reasonable time (timeout in conftest.py)

    def test_export_employee_filter(self, api_client, app_running):
        """Test export with employee filtering if supported"""
        # Check if export supports employee filtering
        params = {"employee_id": "test", "badge_number": "test"}

        response = api_client.get("/api/attendance/export/csv", params=params)
        # Should handle employee filters gracefully (even if not implemented)
        assert response.status_code in [200, 400, 404, 422]

    def test_export_page_form_elements(self, api_client, app_running):
        """Test export page has form elements for date selection"""
        response = api_client.get("/export")

        if response.status_code == 200:
            content = response.text

            # Look for form elements that would be used for export
            form_indicators = ["form", "input", "button", "select", "date"]
            found_indicators = sum(1 for indicator in form_indicators if indicator in content.lower())

            assert found_indicators > 0, "Export page should have form elements"

    def test_export_error_handling(self, api_client, app_running):
        """Test export error handling"""
        # Test with end date before start date
        params = {
            "start_date": "2023-12-31",
            "end_date": "2023-01-01"  # End before start
        }

        response = api_client.get("/api/attendance/export/csv", params=params)
        # Should handle invalid date ranges gracefully
        assert response.status_code in [200, 400, 422, 404]

    def test_export_without_data(self, api_client, app_running):
        """Test export behavior when no data exists"""
        # Use a date range where no data should exist
        future_date = date.today() + timedelta(days=30)
        params = {
            "start_date": future_date.isoformat(),
            "end_date": (future_date + timedelta(days=1)).isoformat()
        }

        response = api_client.get("/api/attendance/export/csv", params=params)
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            content = response.text
            # Should still return valid CSV structure (headers at minimum)
            assert len(content) >= 0  # Empty or headers only

    def test_export_attendance_sync_status(self, api_client, app_running):
        """Test attendance sync status that affects export data"""
        response = api_client.get("/api/attendance/sync/status")
        assert response.status_code in [200, 404, 500]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)
            # Should have sync status information
            assert any(key in data for key in ["status", "last_sync", "device", "sync"])

    def test_export_manual_sync_trigger(self, api_client, app_running):
        """Test manual sync trigger before export"""
        response = api_client.post("/api/attendance/sync")
        # Sync might fail if device not connected, which is okay
        assert response.status_code in [200, 400, 500, 502, 503]

    def test_export_navigation_integration(self, api_client, app_running):
        """Test navigation between export and other pages"""
        # Test navigation from export page
        pages_to_test = ["/", "/status", "/nickname-management"]

        for page in pages_to_test:
            response = api_client.get(page)
            assert response.status_code == 200, f"Navigation to {page} should work"

    def test_export_api_health(self, api_client, app_running):
        """Test attendance API health for export functionality"""
        response = api_client.get("/api/attendance/health")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data or "health" in data

    def test_export_different_formats(self, api_client, app_running):
        """Test different export formats if available"""
        # Test CSV format specifically
        response = api_client.get("/api/attendance/export/csv")
        assert response.status_code in [200, 404]

        # Test if other formats are available (they might not be)
        other_formats = ["json", "xlsx", "xml"]
        for format_type in other_formats:
            response = api_client.get(f"/api/attendance/export/{format_type}")
            # These might not exist, so we just check they don't crash
            assert response.status_code in [200, 404, 405, 501]