"""
Enhanced service layer tests with real method testing
Tests actual service functionality with database integration
"""

import pytest
from datetime import datetime, date, timedelta
from io import StringIO
import csv

from app.services.device_service import SimpleDeviceService
from app.services.attendance_service import SimpleAttendanceService
from app.services.export_service import SimpleExportService
from app.models.models import AttendanceRecord, Employee, Device


class TestEnhancedAttendanceService:
    """Enhanced tests for attendance service with real functionality"""

    def test_get_attendance_records_basic(self, test_db, test_company_setup):
        """Test getting attendance records with basic functionality"""
        service = SimpleAttendanceService()

        records = service.get_attendance_records()

        # Should return a list (may be empty)
        assert isinstance(records, list)
        # All records should be AttendanceRecord instances
        for record in records:
            assert isinstance(record, AttendanceRecord)

    def test_get_attendance_records_with_date_filter(self, test_db, test_company_setup):
        """Test attendance records with date filtering"""
        service = SimpleAttendanceService()

        # Test with date range
        start_date = date.today() - timedelta(days=7)
        end_date = date.today()

        records = service.get_attendance_records(
            start_date=start_date,
            end_date=end_date
        )

        assert isinstance(records, list)
        # Verify all records are within date range
        for record in records:
            record_date = record.timestamp.date()
            assert start_date <= record_date <= end_date

    def test_get_attendance_records_with_employee_filter(self, test_db, test_company_setup):
        """Test attendance records filtered by employee"""
        service = SimpleAttendanceService()
        employees = test_company_setup["employees"]

        if employees:
            badge = employees[0].badge_number
            records = service.get_attendance_records(employee_badge=badge)

            assert isinstance(records, list)
            # All records should be for specified employee
            for record in records:
                assert record.employee_badge_number == badge

    def test_get_attendance_records_with_limit(self, test_db, test_company_setup):
        """Test attendance records with limit parameter"""
        service = SimpleAttendanceService()

        records = service.get_attendance_records(limit=5)

        assert isinstance(records, list)
        assert len(records) <= 5

    def test_get_attendance_summary(self, test_db, test_company_setup):
        """Test attendance summary generation"""
        service = SimpleAttendanceService()

        summary = service.get_attendance_summary()

        assert isinstance(summary, dict)
        # Should have expected summary fields
        expected_fields = ["total_records", "recent_records", "unique_employees"]
        for field in expected_fields:
            if field in summary:  # Some fields may not exist if no data
                assert isinstance(summary[field], (int, list))

    def test_get_employee_list(self, test_db, test_company_setup):
        """Test getting employee list"""
        service = SimpleAttendanceService()

        employees = service.get_employee_list()

        assert isinstance(employees, list)
        for employee in employees:
            assert isinstance(employee, Employee)



class TestEnhancedExportService:
    """Enhanced tests for export service with real functionality"""

    def test_export_attendance_csv_basic(self, test_db, test_company_setup):
        """Test basic CSV export functionality"""
        service = SimpleExportService()

        csv_content = service.export_attendance_csv()

        assert isinstance(csv_content, str)
        if csv_content.strip():  # If there's content
            # Should look like CSV format
            lines = csv_content.strip().split('\n')
            assert len(lines) >= 1  # At least header line

    def test_export_attendance_csv_with_date_range(self, test_db, test_company_setup):
        """Test CSV export with date range"""
        service = SimpleExportService()

        start_date = date.today() - timedelta(days=30)
        end_date = date.today()

        csv_content = service.export_attendance_csv(
            start_date=start_date,
            end_date=end_date
        )

        assert isinstance(csv_content, str)

    def test_export_employees_csv(self, test_db, test_company_setup):
        """Test employee CSV export"""
        service = SimpleExportService()

        csv_content = service.export_employees_csv()

        assert isinstance(csv_content, str)
        if csv_content.strip():
            # Should be valid CSV format
            lines = csv_content.strip().split('\n')
            assert len(lines) >= 1




    def test_count_records(self, test_db, test_company_setup):
        """Test record counting functionality"""
        service = SimpleExportService()

        count = service.count_records()

        assert isinstance(count, int)
        assert count >= 0

    def test_count_records_with_filters(self, test_db, test_company_setup):
        """Test record counting with filters"""
        service = SimpleExportService()

        start_date = date.today() - timedelta(days=30)
        end_date = date.today()

        count = service.count_records(
            start_date=start_date,
            end_date=end_date
        )

        assert isinstance(count, int)
        assert count >= 0


class TestEnhancedDeviceService:
    """Enhanced tests for device service — pure-DB device lookups only.

    fix/zk-ingestion-loss removed all device I/O from `SimpleDeviceService`
    (`connect_to_device`, `get_attendance_records`, `sync_attendance_data`,
    the `from zk import ZK` import, and the `max_retries`/`timeout`
    attributes that configured that I/O). All device access now goes
    exclusively through `zk_session`/`zk_client` — see
    `tests/unit/test_zk_session.py` and `tests/unit/test_zk_client.py`. This
    service keeps only `get_default_device()`, a plain DB lookup with
    real callers (`consolidated_devices.py`, `consolidated_attendance.py`).
    """

    def test_get_default_device_returns_existing_active_device(self, test_db):
        """Returns the lowest-id active device when one already exists."""
        from app.models.models import Device

        device = Device(name="Existing Device", ip_address="192.168.1.50",
                        port=4370, is_active=True)
        test_db.add(device)
        test_db.commit()

        service = SimpleDeviceService()
        result = service.get_default_device()

        assert result is not None
        assert result.ip_address == "192.168.1.50"

    def test_get_default_device_creates_one_from_env_when_none_exists(self, test_db):
        """No active device configured -> creates one from env var defaults."""
        service = SimpleDeviceService()
        result = service.get_default_device()

        assert result is not None
        assert result.is_active is True
        assert result.id is not None  # persisted


class TestServiceIntegration:
    """Integration tests between services"""

    def test_attendance_and_export_integration(self, test_db, test_company_setup):
        """Test integration between attendance and export services"""
        attendance_service = SimpleAttendanceService()
        export_service = SimpleExportService()

        # Get records through attendance service
        records = attendance_service.get_attendance_records(limit=10)

        # Export through export service
        csv_content = export_service.export_attendance_csv()

        # Both should work consistently
        assert isinstance(records, list)
        assert isinstance(csv_content, str)

    def test_service_database_consistency(self, test_db, test_company_setup):
        """Test services work consistently with database"""
        attendance_service = SimpleAttendanceService()
        export_service = SimpleExportService()

        # Get employee count through attendance service
        employees = attendance_service.get_employee_list()

        # Export employees through export service
        employee_csv = export_service.export_employees_csv()

        # Should be consistent (both work or both handle empty gracefully)
        assert isinstance(employees, list)
        assert isinstance(employee_csv, str)


class TestServiceErrorHandling:
    """Test service error handling and edge cases"""

    def test_attendance_service_invalid_dates(self, test_db):
        """Test attendance service with invalid dates"""
        service = SimpleAttendanceService()

        # Future dates should be handled
        future_date = date.today() + timedelta(days=3650)  # 10 years
        records = service.get_attendance_records(start_date=future_date)

        assert isinstance(records, list)

    def test_export_service_empty_data(self, test_db):
        """Test export service with no data"""
        service = SimpleExportService()

        # Should handle empty data gracefully
        csv_content = service.export_attendance_csv()
        assert isinstance(csv_content, str)

    def test_services_handle_none_parameters(self, test_db):
        """Test services handle None parameters gracefully"""
        attendance_service = SimpleAttendanceService()
        export_service = SimpleExportService()

        # Should not crash with None parameters
        records = attendance_service.get_attendance_records(
            start_date=None,
            end_date=None,
            employee_badge=None
        )
        assert isinstance(records, list)

        count = export_service.count_records(
            start_date=None,
            end_date=None
        )
        assert isinstance(count, int)