"""
Integration tests for Multi-office GPS Configuration

Tests terminal-specific GPS configuration, isolation validation, and multi-location
check-in workflows across different office locations.
"""

import pytest
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone

from app.models.models import Base, Device, Employee, AttendanceRecord
from app.services.location_service import location_service


@pytest.fixture
def test_db():
    """Create in-memory test database with multi-office setup"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    # Create test employees
    employee1 = Employee(
        badge_number="EMP001",
        english_name="Test Employee 1",
        display_name="Employee 1",
        is_active=True
    )
    employee2 = Employee(
        badge_number="EMP002",
        english_name="Test Employee 2",
        display_name="Employee 2",
        is_active=True
    )
    db.add_all([employee1, employee2])

    # Create main office terminal
    main_office = Device(
        name="Main Office Terminal",
        ip_address="192.168.1.100",
        device_type="qr_terminal",
        is_active=True,
        device_metadata=json.dumps({
            "gps": {
                "latitude": 13.7563,
                "longitude": 100.5018,
                "radius": 200,
                "location_name": "Main Office"
            }
        })
    )

    # Create branch office terminal
    branch_office = Device(
        name="Branch Office Terminal",
        ip_address="192.168.2.100",
        device_type="qr_terminal",
        is_active=True,
        device_metadata=json.dumps({
            "gps": {
                "latitude": 13.8000,
                "longitude": 100.5500,
                "radius": 150,
                "location_name": "Branch Office"
            }
        })
    )

    # Create warehouse terminal
    warehouse = Device(
        name="Warehouse Terminal",
        ip_address="192.168.3.100",
        device_type="qr_terminal",
        is_active=True,
        device_metadata=json.dumps({
            "gps": {
                "latitude": 13.7200,
                "longitude": 100.4800,
                "radius": 300,
                "location_name": "Warehouse"
            }
        })
    )

    db.add_all([main_office, branch_office, warehouse])
    db.commit()

    yield db
    db.close()


class TestMultiOfficeGPSConfiguration:
    """Test GPS configuration for multiple office locations"""

    def test_terminal_specific_gps_configuration(self, test_db):
        """Test that each terminal maintains its own GPS configuration"""
        terminals = test_db.query(Device).filter(
            Device.device_type == "qr_terminal"
        ).all()

        assert len(terminals) == 3

        # Verify each terminal has unique GPS config
        gps_configs = []
        for terminal in terminals:
            metadata = json.loads(terminal.device_metadata)
            gps = metadata["gps"]
            gps_configs.append((gps["latitude"], gps["longitude"]))

        # All GPS coordinates should be unique
        assert len(set(gps_configs)) == 3

    def test_terminal_gps_isolation(self, test_db):
        """Test that GPS validation is isolated per terminal"""
        # Get terminals
        main_office = test_db.query(Device).filter(
            Device.name == "Main Office Terminal"
        ).first()
        branch_office = test_db.query(Device).filter(
            Device.name == "Branch Office Terminal"
        ).first()

        # User location near main office
        user_lat, user_lon = 13.7565, 100.5020

        # Should be valid at main office
        result_main = location_service.validate_gps_location(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=10.0,
            terminal_id=main_office.id,
            db=test_db
        )

        # Should be invalid at branch office
        result_branch = location_service.validate_gps_location(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=10.0,
            terminal_id=branch_office.id,
            db=test_db
        )

        assert result_main["valid"] is True
        assert result_branch["valid"] is False

    def test_different_radius_per_terminal(self, test_db):
        """Test that each terminal can have different radius settings"""
        terminals = test_db.query(Device).filter(
            Device.device_type == "qr_terminal"
        ).all()

        radii = []
        for terminal in terminals:
            location = location_service.get_terminal_location(terminal.id, test_db)
            radii.append(location["radius"])

        # Verify different radii: 200m, 150m, 300m
        assert 200 in radii
        assert 150 in radii
        assert 300 in radii

    def test_terminal_location_name_uniqueness(self, test_db):
        """Test that each terminal has unique location name"""
        terminals = test_db.query(Device).filter(
            Device.device_type == "qr_terminal"
        ).all()

        location_names = []
        for terminal in terminals:
            location = location_service.get_terminal_location(terminal.id, test_db)
            location_names.append(location["location_name"])

        # All location names should be unique
        assert len(set(location_names)) == 3
        assert "Main Office" in location_names
        assert "Branch Office" in location_names
        assert "Warehouse" in location_names


class TestMultiLocationCheckIn:
    """Test check-in workflows across multiple office locations"""

    def test_employee_checkin_at_different_locations(self, test_db):
        """Test employee can check in at different office locations"""
        employee = test_db.query(Employee).filter(
            Employee.badge_number == "EMP001"
        ).first()

        main_office = test_db.query(Device).filter(
            Device.name == "Main Office Terminal"
        ).first()
        branch_office = test_db.query(Device).filter(
            Device.name == "Branch Office Terminal"
        ).first()

        # Check in at main office
        record1 = AttendanceRecord(
            employee_badge_number=employee.badge_number,
            timestamp=datetime.now(timezone.utc),
            punch_type=0,  # check_in
            sync_status="synced",
            device_id=main_office.id
        )
        test_db.add(record1)
        test_db.commit()

        # Check in at branch office (different time)
        record2 = AttendanceRecord(
            employee_badge_number=employee.badge_number,
            timestamp=datetime.now(timezone.utc),
            punch_type=0,  # check_in
            sync_status="synced",
            device_id=branch_office.id
        )
        test_db.add(record2)
        test_db.commit()

        # Verify both records exist with different device IDs
        records = test_db.query(AttendanceRecord).filter(
            AttendanceRecord.employee_badge_number == employee.badge_number
        ).all()

        assert len(records) == 2
        device_ids = [record.device_id for record in records]
        assert main_office.id in device_ids
        assert branch_office.id in device_ids

    def test_validate_nearest_terminal_multi_office(self, test_db):
        """Test validation finds nearest terminal across multiple offices"""
        # User location between main office and warehouse, closer to main office
        user_lat, user_lon = 13.7500, 100.4950

        result = location_service.validate_multiple_locations(
            user_lat=user_lat,
            user_lon=user_lon,
            user_accuracy=10.0,
            db=test_db
        )

        # Should identify all 3 terminals
        assert len(result["all_terminals"]) == 3

        # Should be sorted by distance
        distances = [t["distance"] for t in result["all_terminals"]]
        assert distances == sorted(distances)

        # Verify nearest terminal
        assert result["nearest_terminal"] is not None
