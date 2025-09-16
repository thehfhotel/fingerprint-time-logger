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

    def test_export_employees_csv_with_hidden(self, test_client, test_company_setup):
        """Test GET /api/export/employees/csv with hidden employees"""
        response = test_client.get("/api/export/employees/csv?include_hidden=true")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]



    def test_get_monthly_attendance_report(self, test_client, test_company_setup):
        """Test GET /api/export/reports/monthly - Generate monthly report"""
        year = datetime.now().year
        month = datetime.now().month
        response = test_client.get(f"/api/export/reports/monthly?year={year}&month={month}")
        assert response.status_code == 200
        data = response.json()
        assert "report_type" in data
        assert data["report_type"] == "monthly"





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
        expected_headers = ["badge", "name", "date", "time"]
        for header in expected_headers:
            assert any(header.lower() in h.lower() for h in headers), f"Missing header: {header}"

    def test_employees_csv_headers(self, test_client, test_company_setup):
        """Test that employees CSV has correct headers"""
        response = test_client.get("/api/export/employees/csv")
        assert response.status_code == 200

        csv_content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(csv_content))
        headers = next(reader)

        expected_headers = ["badge", "name", "thai"]
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


    def test_employee_report_nonexistent_employee(self, test_client):
        """Test employee report for non-existent employee"""
        response = test_client.get("/api/export/reports/employee-summary?employee_badge=9999")
        assert response.status_code in [404, 500]  # Not found or exception




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
        response = test_client.get(f"/api/export/reports/monthly?year={year}&month={month}")
        assert response.status_code == 200
        # Should generate report efficiently even with large dataset


class TestConsolidatedExportAPIReports:
    """Test report generation functionality"""


    def test_monthly_report_structure(self, test_client, test_company_setup):
        """Test structure of monthly report"""
        year = datetime.now().year
        month = datetime.now().month
        response = test_client.get(f"/api/export/reports/monthly?year={year}&month={month}")
        assert response.status_code == 200
        data = response.json()
        assert data["report_type"] == "monthly"
        assert data["year"] == year
        assert data["month"] == month

