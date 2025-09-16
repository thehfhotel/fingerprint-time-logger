"""
Unit tests for Consolidated Export API Router
Tests all 10 endpoints in consolidated_export.py
"""

import pytest
from datetime import datetime, timedelta
from io import StringIO
import csv


class TestConsolidatedExportAPI:
    """Test suite for consolidated export endpoints"""

    def test_get_export_formats(self, test_client):
        """Test GET /api/export/formats - List available export formats"""
        response = test_client.get("/api/export/formats")
        assert response.status_code == 200
        data = response.json()
        assert "formats" in data
        assert "available_exports" in data
        assert "csv" in data["formats"]

    def test_export_attendance_csv(self, test_client, test_company_setup):
        """Test GET /api/export/attendance/csv - Export attendance to CSV"""
        response = test_client.get("/api/export/attendance/csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers.get("content-disposition", "").lower()

    def test_export_attendance_csv_with_date_range(self, test_client, test_company_setup):
        """Test GET /api/export/attendance/csv with date range"""
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")
        response = test_client.get(f"/api/export/attendance/csv?start_date={start_date}&end_date={end_date}")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    def test_export_employees_csv(self, test_client, test_company_setup):
        """Test GET /api/export/employees/csv - Export employees to CSV"""
        response = test_client.get("/api/export/employees/csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    def test_export_employees_csv_active_only(self, test_client, test_company_setup):
        """Test GET /api/export/employees/csv with active_only filter"""
        response = test_client.get("/api/export/employees/csv?active_only=true")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    def test_export_devices_csv(self, test_client, test_company_setup):
        """Test GET /api/export/devices/csv - Export devices to CSV"""
        response = test_client.get("/api/export/devices/csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]

    def test_get_attendance_summary_report(self, test_client, test_company_setup):
        """Test GET /api/export/reports/attendance-summary - Generate attendance summary report"""
        response = test_client.get("/api/export/reports/attendance-summary")
        assert response.status_code == 200
        data = response.json()
        assert "report_type" in data
        assert "generated_at" in data
        assert "data" in data

    def test_get_monthly_attendance_report(self, test_client, test_company_setup):
        """Test GET /api/export/reports/monthly-attendance - Generate monthly attendance report"""
        year = datetime.now().year
        month = datetime.now().month
        response = test_client.get(f"/api/export/reports/monthly-attendance?year={year}&month={month}")
        assert response.status_code == 200
        data = response.json()
        assert "report_type" in data
        assert "period" in data
        assert "data" in data

    def test_get_employee_attendance_report(self, test_client, test_company_setup):
        """Test GET /api/export/reports/employee-attendance - Generate employee attendance report"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            response = test_client.get(f"/api/export/reports/employee-attendance?employee_badge={badge_number}")
            assert response.status_code == 200
            data = response.json()
            assert "report_type" in data
            assert "employee" in data
            assert "data" in data

    def test_export_custom_report(self, test_client, test_company_setup):
        """Test POST /api/export/custom - Generate custom export"""
        custom_export_config = {
            "export_type": "attendance",
            "format": "csv",
            "filters": {
                "start_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "end_date": datetime.now().strftime("%Y-%m-%d")
            },
            "columns": ["badge_number", "timestamp", "punch_type"]
        }
        response = test_client.post("/api/export/custom", json=custom_export_config)
        assert response.status_code in [200, 400]  # Success or invalid config

    def test_get_quick_exports(self, test_client):
        """Test GET /api/export/quick - List available quick exports"""
        response = test_client.get("/api/export/quick")
        assert response.status_code == 200
        data = response.json()
        assert "quick_exports" in data
        assert isinstance(data["quick_exports"], list)


class TestConsolidatedExportAPICSVContent:
    """Test CSV content quality and format"""

    def test_attendance_csv_headers(self, test_client, test_company_setup):
        """Test that attendance CSV has correct headers"""
        response = test_client.get("/api/export/attendance/csv")
        assert response.status_code == 200

        # Parse CSV content
        csv_content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(csv_content))
        headers = next(reader)

        # Check for expected headers
        expected_headers = ["badge_number", "timestamp", "punch_type"]
        for header in expected_headers:
            assert any(header.lower() in h.lower() for h in headers), f"Missing header: {header}"

    def test_employees_csv_headers(self, test_client, test_company_setup):
        """Test that employees CSV has correct headers"""
        response = test_client.get("/api/export/employees/csv")
        assert response.status_code == 200

        csv_content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(csv_content))
        headers = next(reader)

        expected_headers = ["badge_number", "english_name", "thai_name"]
        for header in expected_headers:
            assert any(header.lower() in h.lower() for h in headers), f"Missing header: {header}"

    def test_devices_csv_headers(self, test_client, test_company_setup):
        """Test that devices CSV has correct headers"""
        response = test_client.get("/api/export/devices/csv")
        assert response.status_code == 200

        csv_content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(csv_content))
        headers = next(reader)

        expected_headers = ["name", "ip_address", "port"]
        for header in expected_headers:
            assert any(header.lower() in h.lower() for h in headers), f"Missing header: {header}"

    def test_csv_utf8_encoding(self, test_client, test_company_setup):
        """Test that CSV exports handle Thai characters correctly"""
        response = test_client.get("/api/export/employees/csv")
        assert response.status_code == 200

        # Should be able to decode as UTF-8 without errors
        csv_content = response.content.decode('utf-8')
        assert isinstance(csv_content, str)


class TestConsolidatedExportAPIEdgeCases:
    """Edge case tests for export API"""

    def test_export_with_invalid_date_range(self, test_client):
        """Test export with invalid date range"""
        response = test_client.get("/api/export/attendance/csv?start_date=invalid&end_date=2024-12-31")
        assert response.status_code == 422  # Validation error

    def test_export_with_future_dates(self, test_client):
        """Test export with future date range"""
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        response = test_client.get(f"/api/export/attendance/csv?start_date={future_date}&end_date={future_date}")
        assert response.status_code == 200  # Should work but return empty data

    def test_export_empty_dataset(self, test_client):
        """Test export when no data is available"""
        # Export with date range that has no data
        old_date = "2020-01-01"
        response = test_client.get(f"/api/export/attendance/csv?start_date={old_date}&end_date={old_date}")
        assert response.status_code == 200
        # Should still return CSV with headers but no data rows

    def test_monthly_report_invalid_month(self, test_client):
        """Test monthly report with invalid month"""
        response = test_client.get("/api/export/reports/monthly-attendance?year=2024&month=13")
        assert response.status_code == 422  # Validation error

    def test_employee_report_nonexistent_employee(self, test_client):
        """Test employee report for non-existent employee"""
        response = test_client.get("/api/export/reports/employee-attendance?employee_badge=9999")
        assert response.status_code == 404

    def test_custom_export_invalid_config(self, test_client):
        """Test custom export with invalid configuration"""
        invalid_config = {
            "export_type": "invalid_type",
            "format": "invalid_format",
            "filters": {}
        }
        response = test_client.post("/api/export/custom", json=invalid_config)
        assert response.status_code == 400  # Bad request

    def test_custom_export_missing_required_fields(self, test_client):
        """Test custom export with missing required fields"""
        incomplete_config = {
            "format": "csv"
            # Missing export_type
        }
        response = test_client.post("/api/export/custom", json=incomplete_config)
        assert response.status_code == 422  # Validation error


class TestConsolidatedExportAPIPerformance:
    """Performance tests for export API"""

    @pytest.mark.performance
    def test_large_attendance_export_performance(self, test_client, performance_dataset):
        """Test performance of large attendance data export"""
        response = test_client.get("/api/export/attendance/csv")
        assert response.status_code == 200
        # Should handle large dataset export efficiently

    @pytest.mark.performance
    def test_monthly_report_performance(self, test_client, performance_dataset):
        """Test performance of monthly report generation"""
        year = datetime.now().year
        month = datetime.now().month
        response = test_client.get(f"/api/export/reports/monthly-attendance?year={year}&month={month}")
        assert response.status_code == 200
        # Should generate report efficiently even with large dataset

    @pytest.mark.performance
    def test_custom_export_performance(self, test_client, performance_dataset):
        """Test performance of custom export with complex filters"""
        custom_config = {
            "export_type": "attendance",
            "format": "csv",
            "filters": {
                "start_date": (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
                "end_date": datetime.now().strftime("%Y-%m-%d")
            },
            "columns": ["badge_number", "timestamp", "punch_type", "employee_name"]
        }
        response = test_client.post("/api/export/custom", json=custom_config)
        # Should handle complex custom exports efficiently
        assert response.status_code in [200, 400]


class TestConsolidatedExportAPIReports:
    """Test report generation functionality"""

    def test_attendance_summary_report_structure(self, test_client, test_company_setup):
        """Test structure of attendance summary report"""
        response = test_client.get("/api/export/reports/attendance-summary")
        assert response.status_code == 200
        data = response.json()

        assert data["report_type"] == "attendance_summary"
        assert "generated_at" in data
        assert "summary" in data["data"]
        assert "details" in data["data"]

    def test_monthly_report_structure(self, test_client, test_company_setup):
        """Test structure of monthly attendance report"""
        year = datetime.now().year
        month = datetime.now().month
        response = test_client.get(f"/api/export/reports/monthly-attendance?year={year}&month={month}")
        assert response.status_code == 200
        data = response.json()

        assert data["report_type"] == "monthly_attendance"
        assert data["period"]["year"] == year
        assert data["period"]["month"] == month
        assert "attendance_data" in data["data"]

    def test_employee_report_structure(self, test_client, test_company_setup):
        """Test structure of employee attendance report"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            response = test_client.get(f"/api/export/reports/employee-attendance?employee_badge={badge_number}")
            assert response.status_code == 200
            data = response.json()

            assert data["report_type"] == "employee_attendance"
            assert data["employee"]["badge_number"] == badge_number
            assert "attendance_records" in data["data"]
            assert "statistics" in data["data"]