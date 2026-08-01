"""
Unit tests for Consolidated Attendance API Router
Tests all 13 endpoints in consolidated_attendance.py
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient


class TestConsolidatedAttendanceAPI:
    """Test suite for consolidated attendance endpoints"""

    def test_get_attendance_list(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/ - List attendance records"""
        response = test_client.get("/api/private/attendance/")
        assert response.status_code == 200
        data = response.json()
        assert "records" in data
        assert "total" in data
        assert isinstance(data["records"], list)

    def test_get_attendance_list_with_pagination(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/ with pagination parameters"""
        response = test_client.get("/api/private/attendance/?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["records"]) <= 5

    def test_get_attendance_list_with_date_filter(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/ with date filter"""
        today = datetime.now().strftime("%Y-%m-%d")
        response = test_client.get(f"/api/private/attendance/?start_date={today}&end_date={today}")
        assert response.status_code == 200

    def test_get_attendance_summary(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/summary - Daily attendance summary"""
        response = test_client.get("/api/private/attendance/summary")
        assert response.status_code == 200
        data = response.json()
        # Cache-first response wraps summary in ``data`` + ``cache_metadata``.
        assert "data" in data
        assert "cache_metadata" in data
        summary = data["data"]
        assert "total_employees" in summary
        assert "total_records" in summary
        assert "last_import" in summary

    def test_get_attendance_today(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/today - Today's attendance"""
        response = test_client.get("/api/private/attendance/today")
        assert response.status_code == 200
        data = response.json()
        assert "date" in data
        assert "records" in data
        assert "total" in data
        assert isinstance(data["records"], list)

    def test_get_employee_attendance(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/employee/badge/{badge_number}"""
        # Get first employee from test data
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            response = test_client.get(f"/api/private/attendance/employee/badge/{badge_number}")
            assert response.status_code == 200
            data = response.json()
            assert "employee_badge" in data
            assert "records" in data
            assert isinstance(data["records"], list)

    def test_get_employee_attendance_not_found(self, test_client):
        """Test GET /api/private/attendance/employee/badge/{badge_number} - Employee not found"""
        response = test_client.get("/api/private/attendance/employee/badge/9999")
        assert response.status_code == 404

    def test_attendance_health_check(self, test_client):
        """Test GET /api/private/attendance/health - Health check"""
        response = test_client.get("/api/private/attendance/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_get_calendar_config(self, test_client):
        """Test GET /api/private/attendance/calendar/config - Calendar configuration"""
        response = test_client.get("/api/private/attendance/calendar/config")
        assert response.status_code == 200
        data = response.json()
        assert "working_days" in data
        assert "violation_threshold_minutes" in data
        assert "status_colors" in data

    def test_get_calendar_data(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/calendar/{year}/{month} - Calendar data"""
        year = datetime.now().year
        month = datetime.now().month
        response = test_client.get(f"/api/private/attendance/calendar/{year}/{month}")
        assert response.status_code == 200
        data = response.json()
        assert "year" in data
        assert "month" in data
        assert "calendar_data" in data

    def test_sync_attendance(self, test_client):
        """Test POST /api/private/attendance/sync - Sync attendance from device"""
        response = test_client.post("/api/private/attendance/sync")
        assert response.status_code in [200, 503]  # Success or Service Unavailable

    def test_sync_attendance_full_param(self, test_client):
        """Test POST /api/private/attendance/sync?full=true - full reconcile bypasses lookback floor"""
        response = test_client.post("/api/private/attendance/sync?full=true")
        assert response.status_code in [200, 503]  # Success or Service Unavailable

    def test_get_sync_status(self, test_client):
        """Test GET /api/private/attendance/sync/status - Get sync status"""
        response = test_client.get("/api/private/attendance/sync/status")
        assert response.status_code == 200
        data = response.json()
        assert "last_sync" in data

    def test_export_attendance_csv(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/export/csv - Export to CSV"""
        response = test_client.get("/api/private/attendance/export/csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    def test_export_attendance_csv_with_date_range(self, test_client, test_company_setup):
        """Test GET /api/private/attendance/export/csv with date range"""
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        response = test_client.get(f"/api/private/attendance/export/csv?start_date={start_date}&end_date={end_date}")
        assert response.status_code == 200



class TestConsolidatedAttendanceAPIEdgeCases:
    """Edge case tests for attendance API"""

    def test_invalid_date_format_calendar(self, test_client):
        """Test calendar data with invalid date format"""
        response = test_client.get("/api/private/attendance/calendar/invalid/month")
        assert response.status_code == 422  # Validation error

    def test_future_date_calendar(self, test_client):
        """Test calendar data with future date"""
        future_year = datetime.now().year + 10
        response = test_client.get(f"/api/private/attendance/calendar/{future_year}/1")
        assert response.status_code == 200  # Should still work

    def test_csv_export_with_invalid_dates(self, test_client):
        """Test CSV export with invalid date format"""
        response = test_client.get("/api/private/attendance/export/csv?start_date=invalid-date&end_date=2024-12-31")
        assert response.status_code == 422  # Validation error


    def test_sync_with_device_connection_failure(self, test_client, network_issues_simulator):
        """Test sync when device connection fails"""
        response = test_client.post("/api/private/attendance/sync")
        assert response.status_code in [200, 503]  # Success or Service Unavailable


class TestConsolidatedAttendanceAPIPerformance:
    """Performance tests for attendance API"""

    @pytest.mark.performance
    def test_attendance_summary_performance(self, test_client, performance_dataset):
        """Test performance of attendance summary with large dataset"""
        response = test_client.get("/api/private/attendance/summary")
        assert response.status_code == 200
        # Should complete in reasonable time even with large dataset

    @pytest.mark.performance
    def test_csv_export_performance(self, test_client, performance_dataset):
        """Test performance of CSV export with large dataset"""
        response = test_client.get("/api/private/attendance/export/csv")
        assert response.status_code == 200
        # Should handle large dataset export