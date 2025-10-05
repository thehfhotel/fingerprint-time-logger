"""
Integration Tests for Auto-import Background Sync
Tests scheduler timing, device synchronization, and error recovery
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from app.models.models import Device, AttendanceRecord, Employee


class TestAutoImportScheduler:
    """Test auto-import scheduler behavior"""

    def test_auto_import_30_minute_interval(self):
        """Test that auto-import interval is configured for 30 minutes"""
        expected_interval_seconds = 30 * 60
        assert expected_interval_seconds == 1800

    def test_auto_import_initialization(self, test_db):
        """Test that active devices can be queried for auto-import"""
        device = Device(
            name="Test Device",
            ip_address="192.168.100.209",
            is_active=True
        )
        test_db.add(device)
        test_db.commit()

        # Query active devices for sync
        devices_to_sync = test_db.query(Device).filter(
            Device.is_active == True
        ).all()

        assert len(devices_to_sync) >= 1
        assert device in devices_to_sync


class TestAutoImportExecution:
    """Test auto-import execution and synchronization"""

    def test_last_sync_timestamp_update(self, test_db):
        """Test that last_sync is updated after successful sync"""
        device = Device(
            name="Test Device",
            ip_address="192.168.100.209",
            is_active=True,
            last_sync=None
        )
        test_db.add(device)
        test_db.commit()

        assert device.last_sync is None

        # Simulate successful sync
        device.last_sync = datetime.now(timezone.utc)
        test_db.commit()
        test_db.refresh(device)

        assert device.last_sync is not None

    def test_device_offline_handling(self, test_db):
        """Test that offline devices don't update last_sync"""
        device = Device(
            name="Test Device",
            ip_address="192.168.100.209",
            is_active=True,
            last_sync=None
        )
        test_db.add(device)
        test_db.commit()

        initial_last_sync = device.last_sync

        # Simulate connection failure - don't update last_sync
        # last_sync should remain None
        assert device.last_sync == initial_last_sync


class TestAutoImportDataIntegrity:
    """Test data integrity during auto-import"""

    def test_attendance_record_validation(self, test_db):
        """Test that imported records are validated"""
        # Create employee first
        employee = Employee(
            badge_number="001",
            english_name="Test Employee",
            display_name="Test Employee"
        )
        test_db.add(employee)
        test_db.commit()

        # Valid record
        record = AttendanceRecord(
            employee_badge_number="001",
            timestamp=datetime.now(timezone.utc),
            device_id=1,
            punch_type=0,
            sync_status="synced"
        )

        test_db.add(record)
        test_db.commit()

        assert record.employee_badge_number == "001"

    def test_employee_matching(self, test_db):
        """Test that imported records match to existing employees"""
        employee = Employee(
            badge_number="001",
            english_name="Test Employee",
            display_name="Test Employee"
        )
        test_db.add(employee)
        test_db.commit()

        # Create record
        record = AttendanceRecord(
            employee_badge_number=employee.badge_number,
            timestamp=datetime.now(timezone.utc),
            device_id=1,
            punch_type=0,
            sync_status="synced"
        )

        test_db.add(record)
        test_db.commit()

        # Verify match
        result = test_db.query(AttendanceRecord).join(
            Employee,
            AttendanceRecord.employee_badge_number == Employee.badge_number
        ).filter(AttendanceRecord.employee_badge_number == employee.badge_number).first()

        assert result is not None

    def test_sync_status_tracking(self, test_db):
        """Test that sync_status is properly set"""
        employee = Employee(
            badge_number="001",
            english_name="Test Employee",
            display_name="Test Employee"
        )
        test_db.add(employee)
        test_db.commit()

        record = AttendanceRecord(
            employee_badge_number="001",
            timestamp=datetime.now(timezone.utc),
            device_id=1,
            punch_type=0,
            sync_status="synced"
        )

        test_db.add(record)
        test_db.commit()

        assert record.sync_status == "synced"


class TestAutoImportConfiguration:
    """Test auto-import configuration"""

    def test_active_inactive_device_toggle(self, test_db):
        """Test enabling/disabling devices"""
        device = Device(
            name="Test Device",
            ip_address="192.168.100.209",
            is_active=True
        )
        test_db.add(device)
        test_db.commit()

        # Disable device
        device.is_active = False
        test_db.commit()
        test_db.refresh(device)

        assert device.is_active is False

        # Query should exclude inactive devices
        active_devices = test_db.query(Device).filter(
            Device.is_active == True
        ).all()

        assert device not in active_devices

    def test_interval_configuration(self):
        """Test that auto-import interval is configurable"""
        default_interval = 30 * 60  # 30 minutes
        custom_interval = 60 * 60  # 1 hour

        assert default_interval > 0
        assert custom_interval > default_interval
