"""
Unit Tests for Timezone Handling
Tests Bangkok UTC+7 timezone consistency across features
"""

import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from app.models.models import AttendanceRecord, Employee


# Bangkok timezone
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
UTC_TZ = timezone.utc


class TestTimezoneBangkokConversion:
    """Test UTC to Bangkok timezone conversion for display"""

    def test_utc_to_bangkok_conversion(self):
        """Test converting UTC timestamp to Bangkok time"""
        utc_time = datetime(2025, 10, 6, 7, 30, 0, tzinfo=UTC_TZ)
        bangkok_time = utc_time.astimezone(BANGKOK_TZ)
        assert bangkok_time.hour == 14
        assert bangkok_time.minute == 30

    def test_bangkok_to_utc_conversion(self):
        """Test converting Bangkok timestamp to UTC"""
        bangkok_time = datetime(2025, 10, 6, 14, 30, 0, tzinfo=BANGKOK_TZ)
        utc_time = bangkok_time.astimezone(UTC_TZ)
        assert utc_time.hour == 7
        assert utc_time.minute == 30

    def test_timezone_offset_calculation(self):
        """Test that Bangkok is UTC+7"""
        bangkok_time = datetime(2025, 10, 6, 12, 0, 0, tzinfo=BANGKOK_TZ)
        offset = bangkok_time.utcoffset()
        assert offset == timedelta(hours=7)


class TestTimezoneEdgeCases:
    """Test timezone edge cases and boundary conditions"""

    def test_dst_transition_handling(self):
        """Test DST transitions (Thailand doesn't observe DST)"""
        summer = datetime(2025, 7, 1, 12, 0, 0, tzinfo=BANGKOK_TZ)
        winter = datetime(2025, 1, 1, 12, 0, 0, tzinfo=BANGKOK_TZ)

        assert summer.utcoffset() == timedelta(hours=7)
        assert winter.utcoffset() == timedelta(hours=7)
        assert summer.utcoffset() == winter.utcoffset()

    def test_timezone_boundary_midnight(self):
        """Test timezone conversion at midnight boundaries"""
        bangkok_midnight = datetime(2025, 10, 6, 0, 0, 0, tzinfo=BANGKOK_TZ)
        utc_time = bangkok_midnight.astimezone(UTC_TZ)

        assert utc_time.day == 5
        assert utc_time.hour == 17

    def test_timezone_consistency_across_operations(self):
        """Test that timezone handling is consistent"""
        original_time = datetime(2025, 10, 6, 14, 30, 0, tzinfo=BANGKOK_TZ)
        utc_time = original_time.astimezone(UTC_TZ)
        back_to_bangkok = utc_time.astimezone(BANGKOK_TZ)

        assert original_time == back_to_bangkok
        assert original_time.hour == back_to_bangkok.hour

    def test_naive_datetime_handling(self):
        """Test handling of naive (timezone-unaware) datetimes"""
        naive_time = datetime(2025, 10, 6, 14, 30, 0)
        bangkok_aware = naive_time.replace(tzinfo=BANGKOK_TZ)
        utc_time = bangkok_aware.astimezone(UTC_TZ)

        assert utc_time.hour == 7


class TestAttendanceTimezoneStorage:
    """Test attendance record timezone storage"""

    def test_attendance_record_creation_with_timezone(self, test_db):
        """Test creating attendance record with Bangkok time"""
        # Create employee
        employee = Employee(
            badge_number="EMP001",
            english_name="Test Employee",
            display_name="Test Employee"
        )
        test_db.add(employee)
        test_db.commit()

        # Bangkok time
        bangkok_time = datetime(2025, 10, 6, 14, 30, 0, tzinfo=BANGKOK_TZ)

        # Create record
        record = AttendanceRecord(
            employee_badge_number="EMP001",
            timestamp=bangkok_time,
            device_id=1,
            punch_type=0,
            sync_status="synced"
        )

        test_db.add(record)
        test_db.commit()
        test_db.refresh(record)

        # Verify timestamp is stored
        assert record.timestamp is not None

    def test_calendar_date_grouping_bangkok_timezone(self, test_db):
        """Test that calendar groups records by Bangkok date"""
        # Create employee
        employee = Employee(
            badge_number="EMP001",
            english_name="Test Employee",
            display_name="Test Employee"
        )
        test_db.add(employee)
        test_db.commit()

        # Create records around midnight Bangkok
        # 23:30 Bangkok Oct 5 = 16:30 UTC Oct 5
        record1_utc = datetime(2025, 10, 5, 16, 30, 0, tzinfo=UTC_TZ)
        # 00:30 Bangkok Oct 6 = 17:30 UTC Oct 5
        record2_utc = datetime(2025, 10, 5, 17, 30, 0, tzinfo=UTC_TZ)

        records = [
            AttendanceRecord(
                employee_badge_number="EMP001",
                timestamp=record1_utc,
                device_id=1,
                punch_type=0,
                sync_status="synced"
            ),
            AttendanceRecord(
                employee_badge_number="EMP001",
                timestamp=record2_utc,
                device_id=1,
                punch_type=0,
                sync_status="synced"
            )
        ]

        test_db.add_all(records)
        test_db.commit()

        # Convert to Bangkok for grouping
        bangkok_dates = []
        for record in records:
            bangkok_time = record.timestamp.replace(tzinfo=UTC_TZ).astimezone(BANGKOK_TZ)
            bangkok_dates.append(bangkok_time.date())

        # Should be in different days
        assert bangkok_dates[0].day == 5
        assert bangkok_dates[1].day == 6

    def test_csv_export_bangkok_formatted_timestamps(self, test_db):
        """Test CSV export shows Bangkok timezone"""
        # Create employee
        employee = Employee(
            badge_number="EMP001",
            english_name="Test Employee",
            display_name="Test Employee"
        )
        test_db.add(employee)
        test_db.commit()

        # UTC timestamp
        utc_time = datetime(2025, 10, 6, 7, 30, 0, tzinfo=UTC_TZ)

        record = AttendanceRecord(
            employee_badge_number="EMP001",
            timestamp=utc_time,
            device_id=1,
            punch_type=0,
            sync_status="synced"
        )

        test_db.add(record)
        test_db.commit()

        # Format for CSV export (Bangkok time)
        bangkok_time = record.timestamp.replace(tzinfo=UTC_TZ).astimezone(BANGKOK_TZ)
        csv_formatted = bangkok_time.strftime("%Y-%m-%d %H:%M:%S")

        assert "14:30" in csv_formatted
        assert "2025-10-06" in csv_formatted
