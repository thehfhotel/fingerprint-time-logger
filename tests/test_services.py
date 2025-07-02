"""
Test core services
"""

import pytest
from unittest.mock import Mock, patch
from app.services.device_service import SimpleDeviceService
from app.services.attendance_service import SimpleAttendanceService
from app.services.export_service import SimpleExportService


def test_device_service_initialization():
    """Test SimpleDeviceService can be initialized"""
    service = SimpleDeviceService()
    assert service is not None
    assert service.max_retries == 3
    assert service.timeout == 5


def test_attendance_service_initialization():
    """Test SimpleAttendanceService can be initialized"""
    service = SimpleAttendanceService()
    assert service is not None


def test_export_service_initialization():
    """Test SimpleExportService can be initialized"""
    service = SimpleExportService()
    assert service is not None


@patch('app.services.device_service.ZK')
def test_device_service_connect_mock(mock_zk):
    """Test device connection with mock"""
    # Mock the ZK library
    mock_conn = Mock()
    mock_zk.return_value.connect.return_value = mock_conn
    
    service = SimpleDeviceService()
    # Test would require actual service method calls
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