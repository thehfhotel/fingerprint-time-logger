"""
Unit Tests for Consolidated Attendance API
Tests all endpoints in consolidated_attendance.py router
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from tests.conftest import assert_response_success, assert_response_not_found


@pytest.mark.unit
class TestAttendanceAPI:
    """Test suite for attendance API endpoints"""

    def test_get_attendance_summary(self, test_client: TestClient, test_company_setup):
        """Test GET /api/attendance/summary endpoint"""
        response = test_client.get("/api/attendance/summary")
        data = assert_response_success(response)

        # Verify response structure
        assert "data" in data
        assert "last_update" in data
        assert "total_employees" in data
        assert "total_records" in data
        assert isinstance(data["data"], dict)
        assert data["total_employees"] > 0
        assert data["total_records"] > 0

    def test_get_attendance_today(self, test_client: TestClient, test_company_setup):
        """Test GET /api/attendance/today endpoint"""
        response = test_client.get("/api/attendance/today")
        data = assert_response_success(response)

        # Verify response structure
        assert "records" in data
        assert "date" in data
        assert "total" in data
        assert isinstance(data["records"], list)

    def test_get_employee_attendance(self, test_client: TestClient, test_employees):
        """Test GET /api/attendance/employee/{employee_badge} endpoint"""
        employee = test_employees[0]
        response = test_client.get(f"/api/attendance/employee/{employee.badge_number}")
        data = assert_response_success(response)

        # Verify response structure
        assert "employee_badge" in data
        assert "records" in data
        assert data["employee_badge"] == employee.badge_number
        assert isinstance(data["records"], list)

    def test_get_employee_attendance_not_found(self, test_client: TestClient):
        """Test GET /api/attendance/employee/{employee_badge} with non-existent employee"""
        response = test_client.get("/api/attendance/employee/9999")
        assert_response_not_found(response)

    def test_attendance_health_check(self, test_client: TestClient):
        """Test GET /api/attendance/health endpoint"""
        response = test_client.get("/api/attendance/health")
        data = assert_response_success(response)

        # Verify health response
        assert "status" in data
        assert data["status"] in ["healthy", "unhealthy", "warning"]
        assert "device_connected" in data
        assert "has_recent_data" in data

    def test_get_calendar_config(self, test_client: TestClient):
        """Test GET /api/attendance/calendar/config endpoint"""
        response = test_client.get("/api/attendance/calendar/config")
        data = assert_response_success(response)

        # Verify calendar config structure
        assert "working_days" in data
        assert "violation_threshold_minutes" in data
        assert "status_colors" in data
        assert isinstance(data["working_days"], list)

    def test_get_calendar_data(self, test_client: TestClient, test_company_setup):
        """Test GET /api/attendance/calendar/{year}/{month} endpoint"""
        current_date = datetime.now()
        year = current_date.year
        month = current_date.month

        response = test_client.get(f"/api/attendance/calendar/{year}/{month}")
        data = assert_response_success(response)

        # Verify calendar data structure
        assert "year" in data
        assert "month" in data
        assert "calendar_data" in data
        assert data["year"] == year
        assert data["month"] == month
        assert isinstance(data["calendar_data"], dict)

    def test_sync_attendance(self, test_client: TestClient, mock_device_service):
        """Test POST /api/attendance/sync endpoint"""
        response = test_client.post("/api/attendance/sync")
        data = assert_response_success(response)

        # Verify sync response
        assert "success" in data
        assert "message" in data
        assert isinstance(data["success"], bool)

    def test_get_sync_status(self, test_client: TestClient):
        """Test GET /api/attendance/sync/status endpoint"""
        response = test_client.get("/api/attendance/sync/status")
        data = assert_response_success(response)

        # Verify sync status structure
        assert "last_sync" in data
        assert "status" in data
        assert "device_status" in data
        assert data["status"] in ["healthy", "unhealthy", "warning"]

    def test_export_attendance_csv(self, test_client: TestClient, test_company_setup):
        """Test GET /api/attendance/export/csv endpoint"""
        # Test basic CSV export
        response = test_client.get("/api/attendance/export/csv")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers.get("content-disposition", "")

        # Verify CSV content has headers
        csv_content = response.text
        assert "Employee Badge" in csv_content or "badge" in csv_content.lower()
        assert "timestamp" in csv_content.lower() or "time" in csv_content.lower()

    def test_export_attendance_csv_with_date_range(self, test_client: TestClient, test_company_setup):
        """Test CSV export with date range filters"""
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        response = test_client.get(
            f"/api/attendance/export/csv",
            params={
                "start_date": start_date,
                "end_date": end_date
            }
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"

    def test_mark_attendance_late(self, test_client: TestClient, test_attendance_records, api_headers):
        """Test POST /api/attendance/records/{record_id}/mark-late endpoint"""
        record = test_attendance_records[0]

        request_data = {
            "is_marked_late": True,
            "late_reason": "Traffic jam"
        }

        response = test_client.post(
            f"/api/attendance/records/{record.id}/mark-late",
            json=request_data,
            headers=api_headers
        )

        data = assert_response_success(response)

        # Verify late marking response
        assert "record_id" in data
        assert "success" in data
        assert "message" in data
        assert "adjustment_id" in data
        assert data["success"] is True

    def test_get_record_adjustments(self, test_client: TestClient, test_attendance_records):
        """Test GET /api/attendance/records/{record_id}/adjustments endpoint"""
        record = test_attendance_records[0]

        response = test_client.get(f"/api/attendance/records/{record.id}/adjustments")
        data = assert_response_success(response)

        # Verify adjustments response structure
        assert "record_id" in data
        assert "adjustments" in data
        assert isinstance(data["adjustments"], list)

    def test_delete_record_adjustment(self, test_client: TestClient, test_attendance_records):
        """Test DELETE /api/attendance/records/{record_id}/adjustments/{adjustment_id} endpoint"""
        record = test_attendance_records[0]

        # First mark as late to create an adjustment
        self.test_mark_attendance_late(test_client, test_attendance_records, {"Content-Type": "application/json"})

        # Get adjustments to find adjustment ID
        adjustments_response = test_client.get(f"/api/attendance/records/{record.id}/adjustments")
        adjustments_data = adjustments_response.json()

        if adjustments_data["adjustments"]:
            adjustment_id = adjustments_data["adjustments"][0]["id"]

            # Delete the adjustment
            response = test_client.delete(f"/api/attendance/records/{record.id}/adjustments/{adjustment_id}")
            data = assert_response_success(response)

            assert "message" in data
            assert "deleted" in data["message"].lower()


@pytest.mark.unit
class TestAttendanceAPIEdgeCases:
    """Test edge cases and error scenarios for attendance API"""

    def test_invalid_date_format_calendar(self, test_client: TestClient):
        """Test calendar endpoint with invalid date format"""
        response = test_client.get("/api/attendance/calendar/invalid/month")
        assert response.status_code == 422  # Validation error

    def test_future_date_calendar(self, test_client: TestClient):
        """Test calendar endpoint with future dates"""
        future_year = datetime.now().year + 10
        response = test_client.get(f"/api/attendance/calendar/{future_year}/1")
        data = assert_response_success(response)

        # Should return empty calendar data for future dates
        assert data["calendar_data"] == {} or len(data["calendar_data"]) == 0

    def test_csv_export_with_invalid_dates(self, test_client: TestClient):
        """Test CSV export with invalid date parameters"""
        response = test_client.get(
            "/api/attendance/export/csv",
            params={
                "start_date": "invalid-date",
                "end_date": "2024-12-31"
            }
        )
        assert response.status_code == 422  # Validation error

    def test_mark_late_nonexistent_record(self, test_client: TestClient, api_headers):
        """Test marking non-existent record as late"""
        request_data = {
            "is_marked_late": True,
            "late_reason": "Test"
        }

        response = test_client.post(
            "/api/attendance/records/99999/mark-late",
            json=request_data,
            headers=api_headers
        )
        assert_response_not_found(response)

    def test_sync_with_device_connection_failure(self, test_client: TestClient, network_issues_simulator):
        """Test sync when device connection fails"""
        # This would need proper mocking of device service with connection failure
        response = test_client.post("/api/attendance/sync")

        # Even with connection failure, API should return gracefully
        assert response.status_code in [200, 503]  # Success or Service Unavailable


@pytest.mark.performance
class TestAttendanceAPIPerformance:
    """Performance tests for attendance API endpoints"""

    def test_attendance_summary_performance(self, test_client: TestClient, performance_dataset):
        """Test attendance summary performance with large dataset"""
        import time

        start_time = time.time()
        response = test_client.get("/api/attendance/summary")
        end_time = time.time()

        assert_response_success(response)
        assert (end_time - start_time) < 1.0  # Should complete in under 1 second

    def test_csv_export_performance(self, test_client: TestClient, performance_dataset):
        """Test CSV export performance with large dataset"""
        import time

        start_time = time.time()
        response = test_client.get("/api/attendance/export/csv")
        end_time = time.time()

        assert response.status_code == 200
        assert (end_time - start_time) < 5.0  # Should complete in under 5 seconds