"""
Test database models
"""

import pytest
from datetime import datetime
from app.models.models import Employee, AttendanceRecord, Device


def test_employee_model():
    """Test Employee model basic properties"""
    employee = Employee(
        badge_number="12345",
        english_name="John Doe",
        thai_name="จอห์น โด",
        display_name="จอห์น โด",
        department="IT",
        position="Developer"
    )
    
    assert employee.badge_number == "12345"
    assert employee.english_name == "John Doe"
    assert employee.thai_name == "จอห์น โด"
    assert employee.display_name == "จอห์น โด"
    assert employee.department == "IT"
    assert employee.position == "Developer"


def test_employee_display_name():
    """Test employee display name logic"""
    # Employee with Thai name
    employee_with_thai = Employee(
        badge_number="12345",
        english_name="John Doe",
        thai_name="จอห์น โด"
    )
    
    # Employee without Thai name
    employee_without_thai = Employee(
        badge_number="67890",
        english_name="Jane Smith",
        thai_name=None
    )
    
    # Test display names would be handled by business logic
    assert employee_with_thai.thai_name is not None
    assert employee_without_thai.thai_name is None


def test_attendance_record_model():
    """Test AttendanceRecord model basic properties"""
    record = AttendanceRecord(
        employee_badge_number="12345",
        timestamp=datetime.now(),
        punch_type=1,
        device_id=1
    )
    
    assert record.employee_badge_number == "12345"
    assert isinstance(record.timestamp, datetime)
    assert record.punch_type == 1
    assert record.device_id == 1


def test_device_model():
    """Test Device model basic properties"""
    device = Device(
        name="Main Entrance",
        ip_address="192.168.100.209",
        port=4370
    )
    
    assert device.name == "Main Entrance"
    assert device.ip_address == "192.168.100.209"
    assert device.port == 4370