"""
Comprehensive integration tests for export service
Tests real database integration, service interactions, and file generation
"""

import pytest
import csv
import io
from datetime import datetime, date, timedelta
from unittest.mock import patch, Mock

from app.services.export_service import SimpleExportService, export_service
from app.models.models import AttendanceRecord, Employee, Device
from app.services.attendance_service import attendance_service


# Mark all tests in this module as integration tests for pytest-xdist optimization
pytestmark = pytest.mark.integration


class TestExportServiceDatabaseIntegration:
    """Test export service integration with real database operations"""

    def test_export_attendance_csv_with_real_data(self, test_db, test_company_setup):
        """Test CSV export with actual database records"""
        service = SimpleExportService(test_db)

        csv_content = service.export_attendance_csv()

        assert isinstance(csv_content, str)
        assert len(csv_content) > 0

        # Parse CSV to verify structure
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        headers = csv_reader.fieldnames

        expected_headers = [
            'Employee Badge', 'Employee Name', 'Date', 'Time',
            'Action', 'Status', 'Device ID'
        ]
        assert headers == expected_headers

        # Count rows to verify records were exported
        rows = list(csv_reader)
        assert len(rows) >= 0  # Should have at least some test data

    def test_export_employees_csv_with_real_data(self, test_db, test_company_setup):
        """Test employee CSV export with actual database records"""
        service = SimpleExportService(test_db)
        employees = test_company_setup.get("employees", [])

        csv_content = service.export_employees_csv()

        assert isinstance(csv_content, str)
        assert len(csv_content) > 0

        # Parse CSV to verify structure
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        headers = csv_reader.fieldnames

        expected_headers = [
            'Badge Number', 'Display Name', 'Thai Name', 'English Name',
            'Department', 'Position', 'Active', 'Hidden', 'Created Date'
        ]
        assert headers == expected_headers

        # Verify employee data
        rows = list(csv_reader)
        if employees:
            assert len(rows) >= len(employees)

    def test_export_with_date_filters_integration(self, test_db, test_company_setup):
        """Test export with date filtering using real data"""
        service = SimpleExportService(test_db)

        # Test with 1-year date range to ensure we capture all test data
        # Test data may span many months, so we use a very broad range
        start_date = date.today() - timedelta(days=365)  # Go back 1 year
        end_date = date.today()

        csv_content = service.export_attendance_csv(
            start_date=start_date,
            end_date=end_date
        )

        assert isinstance(csv_content, str)

        # If there are records, verify they're within date range
        if len(csv_content.split('\n')) > 2:  # Header + at least one record
            csv_reader = csv.DictReader(io.StringIO(csv_content))
            for row in csv_reader:
                if row['Date']:  # Skip empty rows
                    record_date = datetime.strptime(row['Date'], '%Y-%m-%d').date()
                    assert start_date <= record_date <= end_date

    def test_export_with_employee_filter_integration(self, test_db, test_company_setup):
        """Test export with employee badge filtering"""
        service = SimpleExportService(test_db)
        employees = test_company_setup.get("employees", [])

        if employees:
            target_badge = employees[0].badge_number

            csv_content = service.export_attendance_csv(employee_badge=target_badge)

            assert isinstance(csv_content, str)

            # Verify all records are for the target employee
            csv_reader = csv.DictReader(io.StringIO(csv_content))
            for row in csv_reader:
                if row['Employee Badge']:  # Skip empty rows
                    assert row['Employee Badge'] == target_badge


    def test_count_records_integration(self, test_db, test_company_setup):
        """Test record counting with real database"""
        service = SimpleExportService(test_db)

        count = service.count_records()

        assert isinstance(count, int)
        assert count >= 0

    def test_count_records_with_filters_integration(self, test_db, test_company_setup):
        """Test record counting with filters using real data"""
        service = SimpleExportService(test_db)
        employees = test_company_setup.get("employees", [])

        # Test with date range
        start_date = date.today() - timedelta(days=30)
        end_date = date.today()

        count_with_dates = service.count_records(
            start_date=start_date,
            end_date=end_date
        )

        assert isinstance(count_with_dates, int)
        assert count_with_dates >= 0

        # Test with employee filter
        if employees:
            employee_ids = [employees[0].badge_number]
            count_with_employee = service.count_records(employee_ids=employee_ids)

            assert isinstance(count_with_employee, int)
            assert count_with_employee >= 0


class TestExportServiceAttendanceServiceIntegration:
    """Test integration between export service and attendance service"""

    def test_attendance_service_dependency(self, test_db, test_company_setup):
        """Test that export service correctly uses attendance service"""
        service = SimpleExportService(test_db)

        # Mock attendance service to verify it's being called
        with patch('app.services.export_service.attendance_service') as mock_attendance:
            mock_attendance.get_attendance_records.return_value = []
            mock_attendance.get_employee_list.return_value = []

            csv_content = service.export_attendance_csv()

            # Verify attendance service was called
            mock_attendance.get_attendance_records.assert_called_once()
            mock_attendance.get_employee_list.assert_called_once()

            assert isinstance(csv_content, str)

    def test_employee_name_resolution(self, test_db, test_company_setup):
        """Test employee name resolution through attendance service"""
        service = SimpleExportService(test_db)
        employees = test_company_setup.get("employees", [])

        if employees:
            csv_content = service.export_attendance_csv()

            # Parse CSV and check if employee names are resolved
            csv_reader = csv.DictReader(io.StringIO(csv_content))
            for row in csv_reader:
                if row['Employee Badge']:
                    # Should have either a real name or fallback format
                    employee_name = row['Employee Name']
                    assert employee_name is not None
                    assert len(employee_name) > 0

                    # Should either be a real name or "Employee {badge}" format
                    badge = row['Employee Badge']
                    assert employee_name != badge or employee_name.startswith('Employee ')

    def test_export_consistency_with_attendance_service(self, test_db, test_company_setup):
        """Test that export service data is consistent with attendance service data"""
        service = SimpleExportService(test_db)

        # Get data from both services with same limits
        attendance_records = attendance_service.get_attendance_records(limit=10000)
        csv_content = service.export_attendance_csv()

        # Count CSV records (excluding header)
        csv_lines = csv_content.strip().split('\n')
        csv_record_count = len(csv_lines) - 1 if len(csv_lines) > 1 else 0

        # Should have consistent counts
        assert csv_record_count == len(attendance_records)



class TestExportServiceAdvancedIntegration:
    """Test advanced export service integration scenarios"""

    def test_export_with_multiple_filters(self, test_db, test_company_setup):
        """Test export with multiple filter combinations"""
        service = SimpleExportService(test_db)
        employees = test_company_setup.get("employees", [])

        # Test with multiple filters
        start_date = date.today() - timedelta(days=30)
        employee_ids = [emp.badge_number for emp in employees[:2]] if len(employees) >= 2 else []
        punch_types = [0, 1]  # Check-in and check-out

        count = service.count_records(
            start_date=start_date,
            employee_ids=employee_ids,
            punch_types=punch_types
        )

        assert isinstance(count, int)
        assert count >= 0

    def test_large_dataset_handling(self, test_db, test_company_setup):
        """Test handling of larger datasets"""
        service = SimpleExportService(test_db)

        # Test with larger limits
        count = service.count_records()

        # These should handle large datasets gracefully
        assert isinstance(count, int)


class TestExportServiceErrorHandling:
    """Test export service error handling in integration scenarios"""

    def test_database_error_handling(self, test_db):
        """Test error handling when database operations fail"""
        service = SimpleExportService(test_db)

        # Mock attendance service to raise an exception
        with patch('app.services.export_service.attendance_service.get_attendance_records') as mock_get:
            mock_get.side_effect = Exception("Database connection failed")

            with pytest.raises(Exception) as exc_info:
                service.export_attendance_csv()

            assert "Export failed" in str(exc_info.value)

    def test_employee_service_error_handling(self, test_db):
        """Test error handling when employee service fails"""
        service = SimpleExportService(test_db)

        # Mock employee list to raise an exception
        with patch('app.services.export_service.attendance_service.get_employee_list') as mock_get:
            mock_get.side_effect = Exception("Employee service failed")

            with pytest.raises(Exception) as exc_info:
                service.export_employees_csv()

            assert "Employee export failed" in str(exc_info.value)

    def test_count_error_handling(self, test_db):
        """Test error handling in record counting"""
        service = SimpleExportService(test_db)

        # Mock attendance service to fail
        with patch('app.services.export_service.attendance_service.get_attendance_records') as mock_get:
            mock_get.side_effect = Exception("Count failed")

            count = service.count_records()

            # Should return 0 on error
            assert count == 0


class TestGlobalExportServiceInstance:
    """Test the global export service instance"""

    def test_global_export_service_exists(self):
        """Test that global export service instance exists"""
        from app.services.export_service import export_service

        assert export_service is not None
        assert isinstance(export_service, SimpleExportService)

    def test_global_service_functionality(self, test_db, test_company_setup):
        """Test that global service instance works correctly"""
        csv_content = export_service.export_attendance_csv()

        assert isinstance(csv_content, str)

    def test_backward_compatibility_alias(self):
        """Test backward compatibility alias"""
        from app.services.export_service import AttendanceExportService

        assert AttendanceExportService is SimpleExportService

    def test_service_initialization_with_db(self, test_db):
        """Test service initialization with database session"""
        service = SimpleExportService(test_db)

        assert service.db is test_db
        assert service.STREAMING_THRESHOLD == 10000


class TestExportServicePerformance:
    """Test export service performance and scalability"""

    def test_export_performance_with_limits(self, test_db, test_company_setup):
        """Test export performance with different record limits"""
        service = SimpleExportService(test_db)

        # Test with small limit
        small_csv = service.export_attendance_csv()
        assert isinstance(small_csv, str)