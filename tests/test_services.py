"""
Test core services
"""

import pytest
from app.services.device_service import SimpleDeviceService
from app.services.attendance_service import SimpleAttendanceService
from app.services.export_service import SimpleExportService


def test_device_service_initialization():
    """Test SimpleDeviceService can be initialized.

    fix/zk-ingestion-loss removed `max_retries`/`timeout` (and all device
    I/O) from this service — it's now a pure-DB `get_default_device()`
    lookup; all device I/O goes through `zk_session`/`zk_client`.
    """
    service = SimpleDeviceService()
    assert service is not None
    assert hasattr(service, "get_default_device")


def test_attendance_service_initialization():
    """Test SimpleAttendanceService can be initialized"""
    service = SimpleAttendanceService()
    assert service is not None


def test_export_service_initialization():
    """Test SimpleExportService can be initialized"""
    service = SimpleExportService()
    assert service is not None


def test_export_service_basic_functionality():
    """Test export service basic functionality"""
    service = SimpleExportService()
    
    # Test that service exists and can be used
    assert service is not None


def test_attendance_service_basic_functionality():
    """Test attendance service basic functionality"""
    service = SimpleAttendanceService()
    
    # Test basic service functionality
    assert service is not None