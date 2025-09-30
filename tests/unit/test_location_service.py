"""
Unit tests for Location Service

Tests GPS validation, Haversine distance calculations, and terminal location management.
"""

import pytest
import json
from unittest.mock import Mock
from fastapi import HTTPException

from app.services.location_service import LocationService
from app.models.models import Device


@pytest.fixture
def location_service():
    """Create location service instance for testing"""
    return LocationService()


@pytest.fixture
def mock_db():
    """Create mock database session"""
    return Mock()


@pytest.fixture
def sample_terminal(mock_db):
    """Create sample QR terminal with GPS data"""
    terminal = Device(
        id=1,
        name="Front Desk Terminal",
        ip_address="192.168.1.100",
        device_type="qr_terminal",
        device_metadata=json.dumps({
            "gps": {
                "latitude": 13.7563,  # Bangkok coordinates
                "longitude": 100.5018,
                "radius": 200,  # 200m radius
                "location_name": "Front Desk"
            }
        })
    )

    mock_db.query.return_value.filter.return_value.first.return_value = terminal
    return terminal


class TestHaversineDistance:
    """Test Haversine distance calculation"""

    def test_haversine_distance_same_point(self, location_service):
        """Test distance between same point is zero"""
        lat, lon = 13.7563, 100.5018
        distance = location_service.haversine_distance(lat, lon, lat, lon)

        assert distance == 0.0

    def test_haversine_distance_known_points(self, location_service):
        """Test distance calculation between known points"""
        # Bangkok (13.7563, 100.5018) to Chiang Mai (18.7883, 98.9853)
        # Known distance: approximately 585 km
        distance = location_service.haversine_distance(
            13.7563, 100.5018,
            18.7883, 98.9853
        )

        # Should be approximately 585,000 meters
        assert 580000 < distance < 590000

    def test_haversine_distance_short_distance(self, location_service):
        """Test distance calculation for short distances"""
        # Two points very close together (approximately 100m apart)
        lat1, lon1 = 13.7563, 100.5018
        lat2, lon2 = 13.7572, 100.5018  # ~100m north

        distance = location_service.haversine_distance(lat1, lon1, lat2, lon2)

        # Should be approximately 100 meters
        assert 90 < distance < 110

    def test_haversine_distance_symmetric(self, location_service):
        """Test distance calculation is symmetric"""
        lat1, lon1 = 13.7563, 100.5018
        lat2, lon2 = 13.7572, 100.5025

        distance1 = location_service.haversine_distance(lat1, lon1, lat2, lon2)
        distance2 = location_service.haversine_distance(lat2, lon2, lat1, lon1)

        assert abs(distance1 - distance2) < 0.001  # Should be essentially equal

    def test_haversine_distance_negative_coordinates(self, location_service):
        """Test distance with negative coordinates (Southern/Western hemispheres)"""
        # Sydney (-33.8688, 151.2093) to Melbourne (-37.8136, 144.9631)
        # Known distance: approximately 714 km
        distance = location_service.haversine_distance(
            -33.8688, 151.2093,
            -37.8136, 144.9631
        )

        assert 710000 < distance < 720000


class TestGetTerminalLocation:
    """Test retrieving terminal location from database"""

    def test_get_terminal_location_success(self, location_service, mock_db, sample_terminal):
        """Test successful terminal location retrieval"""
        result = location_service.get_terminal_location(1, mock_db)

        assert result["latitude"] == 13.7563
        assert result["longitude"] == 100.5018
        assert result["radius"] == 200
        assert result["location_name"] == "Front Desk"

    def test_get_terminal_location_not_found(self, location_service, mock_db):
        """Test terminal not found"""
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            location_service.get_terminal_location(999, mock_db)

        assert exc_info.value.status_code == 404
        assert "ไม่พบ" in exc_info.value.detail

    def test_get_terminal_location_invalid_metadata(self, location_service, mock_db):
        """Test terminal with invalid JSON metadata"""
        terminal = Device(
            id=1,
            name="Broken Terminal",
            device_type="qr_terminal",
            device_metadata="invalid json{"
        )

        mock_db.query.return_value.filter.return_value.first.return_value = terminal

        with pytest.raises(HTTPException) as exc_info:
            location_service.get_terminal_location(1, mock_db)

        assert exc_info.value.status_code == 500
        assert "GPS" in exc_info.value.detail

    def test_get_terminal_location_missing_gps(self, location_service, mock_db):
        """Test terminal with missing GPS data"""
        terminal = Device(
            id=1,
            name="No GPS Terminal",
            device_type="qr_terminal",
            device_metadata=json.dumps({"other": "data"})  # No GPS data
        )

        mock_db.query.return_value.filter.return_value.first.return_value = terminal

        with pytest.raises(HTTPException) as exc_info:
            location_service.get_terminal_location(1, mock_db)

        assert exc_info.value.status_code == 500
        assert "GPS" in exc_info.value.detail

    def test_get_terminal_location_default_radius(self, location_service, mock_db):
        """Test terminal without radius uses default"""
        terminal = Device(
            id=1,
            name="Terminal",
            device_type="qr_terminal",
            device_metadata=json.dumps({
                "gps": {
                    "latitude": 13.7563,
                    "longitude": 100.5018
                    # No radius specified
                }
            })
        )

        mock_db.query.return_value.filter.return_value.first.return_value = terminal

        result = location_service.get_terminal_location(1, mock_db)

        assert result["radius"] == 200  # Default radius


class TestValidateGPSLocation:
    """Test GPS location validation"""

    def test_validate_gps_within_radius(self, location_service, mock_db, sample_terminal):
        """Test validation succeeds when within radius"""
        # Very close to terminal (within 200m)
        user_lat, user_lon = 13.7565, 100.5020

        result = location_service.validate_gps_location(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=10.0,
            terminal_id=1,
            db=mock_db
        )

        assert result["valid"] is True
        assert result["distance"] < 200
        assert "อยู่ในพื้นที่" in result["message"]

    def test_validate_gps_outside_radius(self, location_service, mock_db, sample_terminal):
        """Test validation fails when outside radius"""
        # Far from terminal (> 200m)
        user_lat, user_lon = 13.7600, 100.5100

        result = location_service.validate_gps_location(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=10.0,
            terminal_id=1,
            db=mock_db
        )

        assert result["valid"] is False
        assert result["distance"] > 200
        assert "นอกพื้นที่" in result["message"]

    def test_validate_gps_poor_accuracy(self, location_service, mock_db, sample_terminal):
        """Test validation fails with poor GPS accuracy"""
        user_lat, user_lon = 13.7565, 100.5020

        with pytest.raises(HTTPException) as exc_info:
            location_service.validate_gps_location(
                user_lat=user_lat,
                user_lon=user_lon,
                user_accuracy=100.0,  # Poor accuracy > 50m
                terminal_id=1,
                db=mock_db
            )

        assert exc_info.value.status_code == 400
        assert "ความแม่นยำ" in exc_info.value.detail

    def test_validate_gps_no_accuracy_provided(self, location_service, mock_db, sample_terminal):
        """Test validation works without accuracy parameter"""
        user_lat, user_lon = 13.7565, 100.5020

        result = location_service.validate_gps_location(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=None,  # No accuracy
            terminal_id=1,
            db=mock_db
        )

        assert result["valid"] is True

    def test_validate_gps_exact_radius_boundary(self, location_service, mock_db, sample_terminal):
        """Test validation at exact radius boundary"""
        # Create coordinates exactly 200m away
        # Using approximation: 1 degree latitude ≈ 111km
        # 200m ≈ 0.0018 degrees
        user_lat = 13.7563 + 0.0018
        user_lon = 100.5018

        result = location_service.validate_gps_location(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=10.0,
            terminal_id=1,
            db=mock_db
        )

        # Should be very close to 200m
        assert 190 < result["distance"] < 210


class TestValidateMultipleLocations:
    """Test validation against multiple terminals"""

    def test_validate_multiple_locations_within_one(self, location_service, mock_db):
        """Test validation finds nearest valid terminal"""
        # Create multiple terminals
        terminals = [
            Device(
                id=1,
                name="Terminal 1",
                device_type="qr_terminal",
                device_metadata=json.dumps({
                    "gps": {
                        "latitude": 13.7563,
                        "longitude": 100.5018,
                        "radius": 100,
                        "location_name": "Front Desk"
                    }
                })
            ),
            Device(
                id=2,
                name="Terminal 2",
                device_type="qr_terminal",
                device_metadata=json.dumps({
                    "gps": {
                        "latitude": 13.7600,
                        "longitude": 100.5050,
                        "radius": 150,
                        "location_name": "Back Office"
                    }
                })
            )
        ]

        mock_db.query.return_value.filter.return_value.all.return_value = terminals

        # Mock get_terminal_location calls
        def mock_get_terminal(terminal_id, db):
            metadata = json.loads(terminals[terminal_id - 1].device_metadata)
            return metadata["gps"]

        location_service.get_terminal_location = mock_get_terminal

        # User near Terminal 1
        user_lat, user_lon = 13.7565, 100.5020

        result = location_service.validate_multiple_locations(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=10.0,
            db=mock_db
        )

        assert result["valid"] is True
        assert result["nearest_terminal"]["terminal_id"] == 1
        assert len(result["all_terminals"]) == 2

    def test_validate_multiple_locations_outside_all(self, location_service, mock_db):
        """Test validation when outside all terminals"""
        terminals = [
            Device(
                id=1,
                name="Terminal 1",
                device_type="qr_terminal",
                device_metadata=json.dumps({
                    "gps": {
                        "latitude": 13.7563,
                        "longitude": 100.5018,
                        "radius": 100,
                        "location_name": "Front Desk"
                    }
                })
            )
        ]

        mock_db.query.return_value.filter.return_value.all.return_value = terminals

        def mock_get_terminal(terminal_id, db):
            metadata = json.loads(terminals[0].device_metadata)
            return metadata["gps"]

        location_service.get_terminal_location = mock_get_terminal

        # User far from all terminals
        user_lat, user_lon = 13.8000, 100.6000

        result = location_service.validate_multiple_locations(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=10.0,
            db=mock_db
        )

        assert result["valid"] is False
        assert result["nearest_terminal"]["valid"] is False

    def test_validate_multiple_locations_no_terminals(self, location_service, mock_db):
        """Test validation when no terminals exist"""
        mock_db.query.return_value.filter.return_value.all.return_value = []

        with pytest.raises(HTTPException) as exc_info:
            location_service.validate_multiple_locations(
                user_lat=13.7563,
                user_lon=100.5018,
                user_accuracy=10.0,
                db=mock_db
            )

        assert exc_info.value.status_code == 404
        assert "ไม่พบ" in exc_info.value.detail


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_validate_gps_at_equator(self, location_service):
        """Test distance calculation at equator"""
        distance = location_service.haversine_distance(
            0.0, 0.0,  # Equator, Prime Meridian
            0.0, 0.01  # 0.01 degrees east
        )

        # Should be approximately 1.11km
        assert 1100 < distance < 1120

    def test_validate_gps_at_poles(self, location_service):
        """Test distance calculation near poles"""
        # Near North Pole
        distance = location_service.haversine_distance(
            89.9, 0.0,
            89.9, 180.0
        )

        # Distance should be small near pole
        assert distance < 100000

    def test_haversine_180_degree_longitude_wrap(self, location_service):
        """Test distance across 180° longitude line"""
        # Points on opposite sides of date line
        distance = location_service.haversine_distance(
            0.0, 179.0,
            0.0, -179.0
        )

        # Should be approximately 222km (2 degrees at equator)
        assert 220000 < distance < 225000
