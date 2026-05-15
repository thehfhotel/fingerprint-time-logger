"""
Shared test configuration and fixtures for Fingerprint Time Logger
Provides common test setup, database configuration, and reusable fixtures
"""
import os
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.main_unified import app, fingerprint_app
from tests.fixtures.test_factories import *
from tests.fixtures.zkteco_simulator import ZKTecoSimulatorFactory, MockZKConnection

# Test database configuration
TEST_DATABASE_URL = "sqlite:///./test_attendance.db"
TEST_MEMORY_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_engine(monkeypatch):
    """Create test database engine optimized for speed"""
    # Use in-memory database with speed optimizations
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
            "isolation_level": None,  # Use autocommit mode
        },
        poolclass=StaticPool,
        pool_pre_ping=False,  # Disable ping for speed
        echo=False
    )

    # Speed up SQLite for testing
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # Speed optimizations for testing
        cursor.execute("PRAGMA synchronous = OFF")
        cursor.execute("PRAGMA journal_mode = MEMORY")
        cursor.execute("PRAGMA temp_store = MEMORY")
        cursor.close()

    # Import all models once
    from app.models.models import Employee, Device, AttendanceRecord

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Redirect the module-level ``SessionLocal`` so anything that does
    # ``next(get_db())`` directly (e.g. attendance_service, export_service)
    # hits this in-memory engine instead of the prod sqlite file. Without
    # this redirect, services bypass the FastAPI dependency-override and
    # error out on stale schema in the prod DB (e.g. the line_user_id
    # migration the test schema includes but the prod file doesn't).
    import app.core.database as _db_module
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(_db_module, "SessionLocal", TestingSessionLocal)

    yield engine

    # Fast cleanup
    engine.dispose()


@pytest.fixture(scope="function")
def test_db(test_engine):
    """Create test database session with transaction rollback for isolation"""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()

    # Configure Factory Boy to use this session
    from tests.fixtures.test_factories import EmployeeFactory, DeviceFactory, AttendanceRecordFactory
    EmployeeFactory._meta.sqlalchemy_session = session
    DeviceFactory._meta.sqlalchemy_session = session
    AttendanceRecordFactory._meta.sqlalchemy_session = session

    try:
        yield session
    finally:
        # Clean up Factory Boy session
        EmployeeFactory._meta.sqlalchemy_session = None
        DeviceFactory._meta.sqlalchemy_session = None
        AttendanceRecordFactory._meta.sqlalchemy_session = None
        # Rollback any uncommitted changes and close
        import warnings
        from sqlalchemy.exc import SAWarning
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=SAWarning)
            session.rollback()
        session.close()


@pytest.fixture(scope="function")
def test_client(test_engine, monkeypatch):
    """Create FastAPI test client on the root app with DB dependency overrides on both apps.

    Post Oct-2025 routing reorg: all API routers live on the root ``app``;
    ``fingerprint_app`` only serves legacy admin dashboard HTML/static under
    ``/fingerprintlogs``. Both apps share the same ``get_db`` dependency.

    Also redirects the module-level ``SessionLocal`` to the test engine so
    services that call ``next(get_db())`` directly (e.g. ``attendance_service``
    via ``export_service``) hit the in-memory test DB.
    """

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    fingerprint_app.dependency_overrides[get_db] = override_get_db

    # Redirect module-level SessionLocal so direct ``next(get_db())`` callers
    # use the test DB, not the production sqlite file.
    import app.core.database as _db_module
    monkeypatch.setattr(_db_module, "SessionLocal", TestingSessionLocal)

    # Construct without ``with`` to skip the production lifespan (scheduler /
    # zk_session). Tests don't need those daemons; engaging them per-test
    # also leaks an asyncio loop into subsequent test cases.
    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()
    fingerprint_app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def mounted_test_client(test_engine, monkeypatch):
    """Alias for ``test_client`` retained for backward compatibility.

    Pre-reorg, this fixture distinguished the mounted production-like layout
    (root app with ``fingerprint_app`` mounted at ``/fingerprintlogs``). Now
    both fixtures resolve to the same root ``app`` because the API routers
    moved off ``fingerprint_app`` onto the root ``app``.
    """

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    fingerprint_app.dependency_overrides[get_db] = override_get_db

    import app.core.database as _db_module
    monkeypatch.setattr(_db_module, "SessionLocal", TestingSessionLocal)

    client = TestClient(app)
    yield client

    app.dependency_overrides.clear()
    fingerprint_app.dependency_overrides.clear()


# ZKTeco Device Simulator Fixtures

@pytest.fixture
def healthy_device_simulator():
    """Fixture for healthy ZKTeco device simulator"""
    return ZKTecoSimulatorFactory.create_healthy_device()


@pytest.fixture
def network_issues_simulator():
    """Fixture for ZKTeco device with network issues"""
    return ZKTecoSimulatorFactory.create_network_issues_device()


@pytest.fixture
def error_prone_simulator():
    """Fixture for ZKTeco device with errors"""
    return ZKTecoSimulatorFactory.create_error_prone_device()


@pytest.fixture
def populated_device_simulator():
    """Fixture for ZKTeco device with test data"""
    return ZKTecoSimulatorFactory.create_populated_device(user_count=10, attendance_days=7)


@pytest.fixture
def mock_zk_connection(healthy_device_simulator):
    """Fixture for mock ZK connection object"""
    return MockZKConnection(healthy_device_simulator)


# Test Data Fixtures using Factory Boy

@pytest.fixture
def test_employee(test_db):
    """Create a test employee"""
    employee = EmployeeFactory()
    test_db.add(employee)
    test_db.commit()
    test_db.refresh(employee)
    return employee


@pytest.fixture
def test_device(test_db):
    """Create a test device"""
    device = DeviceFactory()
    test_db.add(device)
    test_db.commit()
    test_db.refresh(device)
    return device


@pytest.fixture
def test_employees(test_db):
    """Create multiple test employees"""
    employees = []
    for i in range(5):
        employee = EmployeeFactory(badge_number=f"{i+1:04d}")
        test_db.add(employee)
        employees.append(employee)

    test_db.commit()

    for employee in employees:
        test_db.refresh(employee)

    return employees


@pytest.fixture
def test_attendance_records(test_db, test_employee, test_device):
    """Create test attendance records"""
    records = []
    for i in range(3):
        record = AttendanceRecordFactory(
            employee_badge_number=test_employee.badge_number,
            device_id=test_device.id
        )
        test_db.add(record)
        records.append(record)

    test_db.commit()

    for record in records:
        test_db.refresh(record)

    return records


@pytest.fixture
def test_company_setup(test_db):
    """Create complete test company with devices, employees, and attendance"""
    # Create test data
    company_data = create_test_company(
        employee_count=5,
        device_count=2,
        days_of_history=7,
        session=test_db
    )

    # Add to database
    for device in company_data['devices']:
        test_db.add(device)

    for employee in company_data['employees']:
        test_db.add(employee)

    for record in company_data['attendance_records']:
        test_db.add(record)

    test_db.commit()

    # Refresh objects
    for device in company_data['devices']:
        test_db.refresh(device)

    for employee in company_data['employees']:
        test_db.refresh(employee)

    for record in company_data['attendance_records']:
        test_db.refresh(record)

    return company_data


# Mock Service Fixtures

@pytest.fixture
def mock_device_service(healthy_device_simulator):
    """Mock device service with simulator"""
    from unittest.mock import Mock
    from app.services.device_service import device_service

    # Mock the device service methods
    original_connect = device_service.connect_to_device
    original_get_attendance_records = device_service.get_attendance_records

    def mock_connect(device):
        connection = MockZKConnection(healthy_device_simulator)
        return connection if connection.connect() else None

    def mock_get_attendance_records(device):
        return healthy_device_simulator.get_attendance()

    device_service.connect_to_device = Mock(side_effect=mock_connect)
    device_service.get_attendance_records = Mock(side_effect=mock_get_attendance_records)

    yield device_service

    # Restore original methods
    device_service.connect_to_device = original_connect
    device_service.get_attendance_records = original_get_attendance_records


# API Testing Utilities

@pytest.fixture
def api_headers():
    """Standard API headers for testing"""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }


@pytest.fixture
def authenticated_headers(api_headers):
    """Headers with authentication (if implemented)"""
    # Add authentication headers when auth is implemented
    return api_headers


# Environment Configuration

@pytest.fixture(autouse=True)
def test_environment():
    """Set up test environment variables"""
    os.environ['TESTING'] = 'true'
    os.environ['DATABASE_URL'] = TEST_MEMORY_DATABASE_URL

    yield

    # Cleanup
    if 'TESTING' in os.environ:
        del os.environ['TESTING']


# Performance Testing Fixtures

@pytest.fixture
def performance_dataset(test_db):
    """Large dataset for performance testing"""
    # Create larger dataset for performance tests
    company_data = create_test_company(
        employee_count=100,
        device_count=5,
        days_of_history=90,
        session=test_db
    )

    # Add to database in batches for performance
    batch_size = 50

    # Add devices
    for device in company_data['devices']:
        test_db.add(device)

    # Add employees in batches
    for i in range(0, len(company_data['employees']), batch_size):
        batch = company_data['employees'][i:i + batch_size]
        for employee in batch:
            test_db.add(employee)
        test_db.commit()

    # Add attendance records in batches
    for i in range(0, len(company_data['attendance_records']), batch_size):
        batch = company_data['attendance_records'][i:i + batch_size]
        for record in batch:
            test_db.add(record)
        test_db.commit()

    test_db.commit()
    return company_data


# Utility Functions for Tests

def assert_response_success(response):
    """Assert that an API response is successful"""
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    return response.json()


def assert_response_created(response):
    """Assert that an API response indicates creation"""
    assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
    return response.json()


def assert_response_not_found(response):
    """Assert that an API response indicates not found"""
    assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"


def assert_response_bad_request(response):
    """Assert that an API response indicates bad request"""
    assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"


# Cleanup fixtures

@pytest.fixture(autouse=True)
def cleanup_test_files():
    """Clean up any test files created during tests"""
    yield

    # Clean up test database file if it exists
    if os.path.exists("test_attendance.db"):
        os.remove("test_attendance.db")

    # Clean up any other test artifacts
    test_files = [
        "test_export.csv",
        "test_logs.txt"
    ]

    for file in test_files:
        if os.path.exists(file):
            os.remove(file)


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "e2e: mark test as an end-to-end test"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as a performance test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )