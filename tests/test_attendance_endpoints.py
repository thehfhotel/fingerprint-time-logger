"""
Focused tests for attendance API endpoints to increase coverage
Tests key attendance functionality with realistic scenarios
"""

import pytest
from datetime import datetime, timedelta
import json


class TestAttendanceEndpoints:
    """Test core attendance API endpoints"""

    def test_get_attendance_list(self, test_client, test_company_setup):
        """Test GET /api/attendance/ - Get attendance records"""
        response = test_client.get("/api/attendance/")
        assert response.status_code == 200
        data = response.json()
        assert "attendance_records" in data or "records" in data or "data" in data

    def test_get_attendance_summary(self, test_client, test_company_setup):
        """Test GET /api/attendance/summary - Get attendance summary"""
        response = test_client.get("/api/attendance/summary")
        assert response.status_code == 200
        data = response.json()
        # Should have some summary data structure
        assert isinstance(data, dict)

    def test_get_attendance_today(self, test_client, test_company_setup):
        """Test GET /api/attendance/today - Get today's attendance"""
        response = test_client.get("/api/attendance/today")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_get_employee_attendance(self, test_client, test_company_setup):
        """Test GET /api/attendance/employee/{badge} - Get employee attendance"""
        employees = test_company_setup["employees"]
        if employees:
            badge = employees[0].badge_number
            response = test_client.get(f"/api/attendance/employee/{badge}")
            assert response.status_code in [200, 404]  # May not have records
            if response.status_code == 200:
                data = response.json()
                assert isinstance(data, dict)

    def test_get_employee_attendance_not_found(self, test_client):
        """Test employee attendance for non-existent employee"""
        response = test_client.get("/api/attendance/employee/99999")
        assert response.status_code == 404

    def test_attendance_health_check(self, test_client):
        """Test GET /api/attendance/health - Health check endpoint"""
        response = test_client.get("/api/attendance/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_get_calendar_config(self, test_client):
        """Test GET /api/attendance/calendar/config - Calendar configuration"""
        response = test_client.get("/api/attendance/calendar/config")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_get_calendar_data(self, test_client, test_company_setup):
        """Test GET /api/attendance/calendar/{year}/{month} - Calendar data"""
        now = datetime.now()
        response = test_client.get(f"/api/attendance/calendar/{now.year}/{now.month}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_get_sync_status(self, test_client):
        """Test GET /api/attendance/sync/status - Sync status"""
        response = test_client.get("/api/attendance/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_export_attendance_csv(self, test_client, test_company_setup):
        """Test GET /api/attendance/export/csv - Export to CSV"""
        response = test_client.get("/api/attendance/export/csv")
        assert response.status_code == 200
        # Should be CSV content type or similar
        assert "text" in response.headers.get("content-type", "").lower() or "csv" in response.headers.get("content-type", "").lower()

    def test_export_attendance_csv_with_date_range(self, test_client, test_company_setup):
        """Test CSV export with date range parameters"""
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        response = test_client.get(f"/api/attendance/export/csv?start_date={start_date}&end_date={end_date}")
        assert response.status_code == 200


class TestAttendanceEndpointsEdgeCases:
    """Test edge cases and error conditions"""

    def test_invalid_date_format_calendar(self, test_client):
        """Test calendar with invalid date format"""
        response = test_client.get("/api/attendance/calendar/invalid/month")
        assert response.status_code == 422  # Validation error

    def test_future_date_calendar(self, test_client):
        """Test calendar with future date"""
        future_year = datetime.now().year + 10
        response = test_client.get(f"/api/attendance/calendar/{future_year}/1")
        assert response.status_code == 200  # Should work but return empty data

    def test_csv_export_with_invalid_dates(self, test_client):
        """Test CSV export with invalid date parameters"""
        response = test_client.get("/api/attendance/export/csv?start_date=invalid&end_date=2024-12-31")
        assert response.status_code in [400, 422]  # Validation or bad request error

    def test_employee_attendance_invalid_badge(self, test_client):
        """Test employee attendance with invalid badge format"""
        response = test_client.get("/api/attendance/employee/")
        assert response.status_code in [404, 405]  # Not found or method not allowed


class TestAttendanceRecordAdjustments:
    """Test attendance record adjustment endpoints"""

    def test_get_record_adjustments_invalid_id(self, test_client):
        """Test getting adjustments for non-existent record"""
        response = test_client.get("/api/attendance/records/99999/adjustments")
        assert response.status_code == 404

    def test_mark_attendance_late_invalid_id(self, test_client):
        """Test marking non-existent record as late"""
        adjustment_data = {
            "is_marked_late": True,
            "late_reason": "Traffic jam"
        }
        response = test_client.post("/api/attendance/records/99999/mark-late", json=adjustment_data)
        assert response.status_code == 404

    def test_delete_adjustment_invalid_ids(self, test_client):
        """Test deleting non-existent adjustment"""
        response = test_client.delete("/api/attendance/records/99999/adjustments/99999")
        assert response.status_code == 404


class TestAttendanceSyncOperations:
    """Test sync-related endpoints (that don't require actual device)"""

    def test_sync_status_structure(self, test_client):
        """Test sync status response structure"""
        response = test_client.get("/api/attendance/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have some status information
        assert "status" in data or "sync" in data or "last" in data