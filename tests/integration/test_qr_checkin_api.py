"""
Integration tests for QR Check-In API

Tests complete QR check-in flow including QR scanning, GPS validation,
and attendance record creation.
"""

import pytest
import json
from datetime import datetime, timezone, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main_unified import app
from app.core.database import get_db, Base
from app.models.models import Device, Employee, AttendanceRecord
from app.services.qr_service import qr_service
from app.services.line_auth_service import line_auth_service


# Test database setup with StaticPool for shared in-memory database
from sqlalchemy.pool import StaticPool
TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool  # Required for in-memory database to work with FastAPI TestClient
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def test_db():
    """Create test database and tables"""
    # Ensure all models are imported and registered with Base
    from app.models.models import Employee, Device, AttendanceRecord
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_client(test_db):
    """Create test client with database dependency override"""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def qr_terminal(test_db):
    """Create QR terminal device with GPS data"""
    terminal = Device(
        name="Front Desk QR Terminal",
        ip_address="192.168.1.100",
        device_type="qr_terminal",
        device_metadata=json.dumps({
            "gps": {
                "latitude": 13.7563,
                "longitude": 100.5018,
                "radius": 200,
                "location_name": "Front Desk"
            }
        })
    )
    test_db.add(terminal)
    test_db.commit()
    test_db.refresh(terminal)
    return terminal


@pytest.fixture
def linked_employee(test_db):
    """Create employee linked with LINE account"""
    employee = Employee(
        badge_number="EMP001",
        display_name="ทดสอบ พนักงาน",
        is_active=True,
        line_user_id="U1234567890abcdef",
        line_display_name="Test User",
        line_linking_code=None  # Already linked
    )
    test_db.add(employee)
    test_db.commit()
    test_db.refresh(employee)
    return employee


class TestQRCodeGeneration:
    """Test QR code generation endpoints"""

    def test_get_qr_code_for_kiosk_success(self, test_client, qr_terminal):
        """Test successful QR code generation for kiosk"""
        response = test_client.get(f"/api/public/qr-checkin/kiosk/{qr_terminal.id}")

        assert response.status_code == 200
        data = response.json()

        assert "qr_image" in data
        assert "terminal_id" in data
        assert "terminal_name" in data
        assert "expires_at" in data
        assert "expires_in_seconds" in data

        assert data["terminal_id"] == qr_terminal.id
        assert data["terminal_name"] == "Front Desk"
        assert data["qr_image"].startswith("data:image/png;base64,")
        # qr_service.qr_token_expiry_seconds is 60 (was 30 in an earlier
        # iteration). The kiosk's countdown UI relies on this matching
        # QR_TOKEN_VALIDITY in qr-terminal.js.
        assert data["expires_in_seconds"] == 60

    def test_get_qr_code_terminal_not_found(self, test_client):
        """Test QR code generation for non-existent terminal"""
        response = test_client.get("/api/public/qr-checkin/kiosk/999")

        assert response.status_code == 404
        assert "ไม่พบ" in response.json()["detail"]

    def test_refresh_qr_code_success(self, test_client, qr_terminal):
        """Test manual QR code refresh"""
        response = test_client.post(f"/api/public/qr-checkin/refresh/{qr_terminal.id}")

        assert response.status_code == 200
        data = response.json()

        assert data["terminal_id"] == qr_terminal.id
        assert data["qr_image"].startswith("data:image/png;base64,")

    def test_qr_code_contains_valid_token(self, test_client, qr_terminal):
        """Test that generated QR code contains valid JWT token"""
        response = test_client.get(f"/api/public/qr-checkin/kiosk/{qr_terminal.id}")
        data = response.json()

        # Extract token from QR code (in real scenario, would scan QR image)
        # For testing, we can use the token directly
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)
        token = qr_data["token"]

        # Verify token is valid
        payload = qr_service.validate_qr_token(token)
        assert payload["terminal_id"] == qr_terminal.id


class TestQRScanning:
    """Test QR code scanning and check-in flow"""

    def test_scan_qr_success(self, test_client, qr_terminal, linked_employee):
        """Test successful QR code scan and check-in"""
        # Generate QR token
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        # Generate LINE JWT token
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )

        # Scan QR code (user near terminal)
        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 13.7565,  # Close to terminal
            "longitude": 100.5020,
            "accuracy": 10.0
        })

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "บันทึกเวลาสำเร็จ" in data["message"]
        assert data["attendance_record"]["badge_number"] == linked_employee.badge_number
        assert data["location_validation"]["distance"] < 200

    def test_scan_qr_invalid_jwt_token(self, test_client, qr_terminal):
        """Test scan with invalid LINE JWT token"""
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": "invalid_token",
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 10.0
        })

        assert response.status_code == 401
        assert "เข้าสู่ระบบ" in response.json()["detail"]

    def test_scan_qr_expired_qr_token(self, test_client, linked_employee):
        """Token past the 60s validity + 15s grace period must be rejected.

        qr_service.qr_grace_period_seconds = 15. A token that's only ~1s
        past expiry would still be accepted by the grace-period logic, so
        we forge one well outside the grace window (60s past exp) to make
        sure the rejection path actually fires.
        """
        # Create expired QR token
        import jwt
        now = datetime.now(timezone.utc)
        exp = now - timedelta(seconds=60)  # > grace_period (15s)

        payload = {
            "terminal_id": 1,
            "timestamp": int(now.timestamp()),
            "nonce": "test_nonce",
            "iat": int((now - timedelta(seconds=120)).timestamp()),
            "exp": int(exp.timestamp())
        }

        expired_token = jwt.encode(payload, qr_service.jwt_secret, algorithm="HS256")

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )

        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": expired_token,
            "jwt_token": jwt_token,
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 10.0
        })

        assert response.status_code == 400
        assert "หมดอายุ" in response.json()["detail"]

    def test_scan_qr_outside_radius(self, test_client, qr_terminal, linked_employee):
        """Test scan when user is outside terminal radius"""
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )

        # User far from terminal (> 200m)
        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 13.7600,
            "longitude": 100.5100,
            "accuracy": 10.0
        })

        assert response.status_code == 400
        assert "นอกพื้นที่" in response.json()["detail"]

    def test_scan_qr_poor_gps_accuracy(self, test_client, qr_terminal, linked_employee):
        """Test scan with poor GPS accuracy"""
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )

        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 100.0  # Poor accuracy
        })

        assert response.status_code == 400
        assert "ความแม่นยำ" in response.json()["detail"]

    def test_scan_qr_employee_not_linked(self, test_client, qr_terminal, test_db):
        """Test scan when employee is not linked with LINE"""
        # Create unlinked employee
        employee = Employee(
            badge_number="EMP002",
            display_name="Unlinked Employee",
            is_active=True,
            line_user_id=None  # Not linked
        )
        test_db.add(employee)
        test_db.commit()

        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id="U_unlinked_user",
            employee_badge=employee.badge_number
        )

        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 10.0
        })

        assert response.status_code == 400
        assert "ไม่พบข้อมูลพนักงาน" in response.json()["detail"]

    def test_scan_qr_same_token_within_validity_allowed(
        self, test_client, qr_terminal, linked_employee
    ):
        """Replay protection is intentionally disabled.

        qr_service.validate_qr_token has a comment explaining why: a single
        kiosk QR is shared across multiple employees scanning in quick
        succession, so the same token has to be re-usable inside its 60s
        validity window. Security stands on:
          - 60s token expiry + 15s grace = ~75s of life
          - GPS proximity check
          - LINE JWT verification
          - QR JWT signature verification
        This test pins that decision: two scans with the same token (and
        two distinct LINE JWTs) both succeed.
        """
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )

        scan_request = {
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 10.0
        }

        response1 = test_client.post("/api/public/qr-checkin/scan", json=scan_request)
        assert response1.status_code == 200

        # Fresh LINE JWT, same QR token — must succeed (no replay block).
        jwt_token2 = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )
        scan_request["jwt_token"] = jwt_token2

        response2 = test_client.post("/api/public/qr-checkin/scan", json=scan_request)
        assert response2.status_code == 200


class TestAttendanceRecording:
    """Test attendance record creation from QR check-in"""

    def test_attendance_record_created(self, test_client, qr_terminal, linked_employee, test_db):
        """Test that attendance record is created correctly"""
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )

        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 10.0
        })

        assert response.status_code == 200

        # Verify attendance record in database
        record = test_db.query(AttendanceRecord).filter(
            AttendanceRecord.employee_badge_number == linked_employee.badge_number
        ).first()

        assert record is not None
        assert record.device_id == qr_terminal.id
        assert record.sync_status == "synced"
        assert "QR Check-in" in record.validation_message
        assert "Front Desk" in record.validation_message
        assert "GPS:" in record.validation_message

    def test_attendance_metadata_includes_gps(self, test_client, qr_terminal, linked_employee, test_db):
        """Test that attendance metadata includes GPS coordinates"""
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )

        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 10.0
        })

        record = test_db.query(AttendanceRecord).first()

        assert "13.7565" in record.validation_message
        assert "100.50" in record.validation_message  # Coordinate may be rounded
        assert "Distance:" in record.validation_message


class TestLocationValidation:
    """Test GPS location validation endpoint"""

    def test_validate_location_specific_terminal(self, test_client, qr_terminal):
        """Test location validation for specific terminal"""
        response = test_client.get(
            f"/api/public/qr-checkin/validate-location"
            f"?latitude=13.7565&longitude=100.5020&accuracy=10.0&terminal_id={qr_terminal.id}"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["validation"]["valid"] is True
        assert data["validation"]["distance"] < 200

    def test_validate_location_all_terminals(self, test_client, qr_terminal):
        """Test location validation against all terminals"""
        response = test_client.get(
            "/api/public/qr-checkin/validate-location"
            "?latitude=13.7565&longitude=100.5020&accuracy=10.0"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["validation"]["valid"] is True
        assert data["validation"]["nearest_terminal"]["terminal_id"] == qr_terminal.id


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_scan_qr_invalid_coordinates(self, test_client, qr_terminal, linked_employee):
        """Test scan with invalid GPS coordinates"""
        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_employee.line_user_id,
            employee_badge=linked_employee.badge_number
        )

        # Invalid latitude (> 90)
        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 95.0,  # Invalid
            "longitude": 100.5020,
            "accuracy": 10.0
        })

        assert response.status_code == 422  # Validation error

    def test_scan_qr_inactive_employee(self, test_client, qr_terminal, test_db):
        """Test scan by inactive employee"""
        # Create inactive employee
        employee = Employee(
            badge_number="EMP003",
            display_name="Inactive Employee",
            is_active=False,  # Inactive
            line_user_id="U_inactive"
        )
        test_db.add(employee)
        test_db.commit()

        qr_data = qr_service.generate_qr_code_for_terminal(qr_terminal.id)

        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=employee.line_user_id,
            employee_badge=employee.badge_number
        )

        response = test_client.post("/api/public/qr-checkin/scan", json={
            "qr_token": qr_data["token"],
            "jwt_token": jwt_token,
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 10.0
        })

        assert response.status_code == 400
        assert "ไม่พบข้อมูลพนักงาน" in response.json()["detail"]
