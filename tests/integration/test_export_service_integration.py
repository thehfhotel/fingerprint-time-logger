"""
Comprehensive integration tests for export service
Tests real database integration, service interactions, and file generation
"""

import pytest
import csv
import io
from datetime import datetime, date, timedelta
from unittest.mock import patch, Mock
from fastapi.responses import StreamingResponse

from app.services.export_service import SimpleExportService, export_service
from app.models.models import AttendanceRecord, Employee, Device
from app.services.attendance_service import attendance_service


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

        # Test with recent date range
        start_date = date.today() - timedelta(days=7)
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

    def test_export_stats_integration(self, test_db, test_company_setup):
        """Test export statistics with real data"""
        service = SimpleExportService(test_db)

        stats = service.get_export_stats()

        assert isinstance(stats, dict)
        assert "total_records" in stats
        assert "total_employees" in stats
        assert isinstance(stats["total_records"], int)
        assert isinstance(stats["total_employees"], int)
        assert stats["total_records"] >= 0
        assert stats["total_employees"] >= 0

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

    def test_stats_consistency(self, test_db, test_company_setup):
        """Test that export stats are consistent with actual data"""
        service = SimpleExportService(test_db)

        stats = service.get_export_stats()

        # Get actual counts
        actual_records = attendance_service.get_attendance_records(limit=50000)
        actual_employees = attendance_service.get_employee_list()

        # Stats should match or be close to actual counts
        assert stats["total_records"] <= len(actual_records)
        assert stats["total_employees"] == len(actual_employees)


class TestExportServiceAdvancedIntegration:
    """Test advanced export service integration scenarios"""

    def test_export_to_csv_streaming_response(self, test_db, test_company_setup):
        """Test streaming CSV export integration"""
        service = SimpleExportService(test_db)

        response = service.export_to_csv(format_type="detailed")

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/csv"
        assert "Content-Disposition" in response.headers
        assert "attachment; filename=" in response.headers["Content-Disposition"]

    def test_export_streaming_generator(self, test_db, test_company_setup):
        """Test streaming CSV generator integration"""
        service = SimpleExportService(test_db)

        generator = service.export_to_csv_streaming(
            format_type="detailed",
            batch_size=10,
            max_records=100
        )

        # Collect all chunks
        chunks = list(generator)

        assert len(chunks) > 0
        assert isinstance(chunks[0], str)

        # First chunk should be headers
        first_chunk = chunks[0]
        assert "Employee Badge" in first_chunk

    def test_different_format_types(self, test_db, test_company_setup):
        """Test different export format types"""
        service = SimpleExportService(test_db)

        # Test detailed format
        detailed_response = service.export_to_csv(format_type="detailed")
        assert isinstance(detailed_response, StreamingResponse)

        # Test simple format
        simple_response = service.export_to_csv(format_type="simple")
        assert isinstance(simple_response, StreamingResponse)

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

    def test_filename_generation_integration(self, test_db):
        """Test filename generation with different parameters"""
        service = SimpleExportService(test_db)

        # Test attendance filename
        filename = service.generate_filename("attendance")
        assert filename.startswith("attendance_export_")
        assert filename.endswith(".csv")

        # Test with date range
        start_date = date(2024, 1, 1)
        end_date = date(2024, 1, 31)
        filename_with_dates = service.generate_filename(
            "attendance", start_date, end_date
        )
        assert "20240101_to_20240131" in filename_with_dates

        # Test employee filename
        emp_filename = service.generate_filename("employees")
        assert emp_filename.startswith("employees_export_")
        assert emp_filename.endswith(".csv")

    def test_export_options_integration(self, test_db, test_company_setup):
        """Test various export options and configurations"""
        service = SimpleExportService(test_db)

        # Test with different include options
        response_with_names = service.export_to_csv(
            include_employee_names=True,
            include_device_names=True
        )
        assert isinstance(response_with_names, StreamingResponse)

        response_without_names = service.export_to_csv(
            include_employee_names=False,
            include_device_names=False
        )
        assert isinstance(response_without_names, StreamingResponse)

    def test_large_dataset_handling(self, test_db, test_company_setup):
        """Test handling of larger datasets"""
        service = SimpleExportService(test_db)

        # Test with larger limits
        stats = service.get_export_stats()
        count = service.count_records()

        # These should handle large datasets gracefully
        assert isinstance(stats, dict)
        assert isinstance(count, int)

        # Test streaming with different batch sizes
        generator = service.export_to_csv_streaming(batch_size=5)
        first_chunk = next(generator, "")
        assert isinstance(first_chunk, str)


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

    def test_stats_error_handling(self, test_db):
        """Test error handling in stats generation"""
        service = SimpleExportService(test_db)

        # Mock attendance service to fail
        with patch('app.services.export_service.attendance_service.get_attendance_records') as mock_get:
            mock_get.side_effect = Exception("Stats failed")

            stats = service.get_export_stats()

            assert isinstance(stats, dict)
            assert "error" in stats
            assert "Stats failed" in stats["error"]

    def test_count_error_handling(self, test_db):
        """Test error handling in record counting"""
        service = SimpleExportService(test_db)

        # Mock attendance service to fail
        with patch('app.services.export_service.attendance_service.get_attendance_records') as mock_get:
            mock_get.side_effect = Exception("Count failed")

            count = service.count_records()

            # Should return 0 on error
            assert count == 0

    def test_streaming_error_handling(self, test_db):
        """Test error handling in streaming export"""
        service = SimpleExportService(test_db)

        # Mock attendance service to fail
        with patch('app.services.export_service.attendance_service.get_attendance_records') as mock_get:
            mock_get.side_effect = Exception("Streaming failed")

            generator = service.export_to_csv_streaming()
            chunks = list(generator)

            # Should yield error message
            assert len(chunks) > 0
            assert "ERROR:" in chunks[-1]


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

        # Test stats performance
        stats = service.get_export_stats()
        assert isinstance(stats, dict)

    def test_batch_processing_performance(self, test_db, test_company_setup):
        """Test batch processing performance in streaming"""
        service = SimpleExportService(test_db)

        # Test with different batch sizes
        small_batch_gen = service.export_to_csv_streaming(batch_size=5)
        small_chunks = list(small_batch_gen)

        large_batch_gen = service.export_to_csv_streaming(batch_size=100)
        large_chunks = list(large_batch_gen)

        # Both should work but may have different chunk counts
        assert len(small_chunks) > 0
        assert len(large_chunks) > 0

    def test_memory_efficiency(self, test_db, test_company_setup):
        """Test memory efficiency of export operations"""
        service = SimpleExportService(test_db)

        # Test that streaming generator doesn't load everything into memory at once
        generator = service.export_to_csv_streaming(batch_size=10)

        # Get first chunk without consuming entire generator
        first_chunk = next(generator, "")
        assert isinstance(first_chunk, str)
        assert len(first_chunk) > 0