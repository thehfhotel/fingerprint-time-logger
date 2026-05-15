"""
Integration tests for GET /api/private/attendance/by-date.

Endpoint contract (see plan section "New backend endpoint"):
  - Path: /api/private/attendance/by-date
  - Query: date=YYYY-MM-DD (Bangkok-local, defaults to today)
  - Response: { date, expected_start_time, rows: [...] }
  - One row per ACTIVE employee
  - status enum: on_time | late ("absent"/"off" not emitted today;
    "absent" was dropped 2026-05 when the endpoint stopped surfacing
    no-punch employees — see _compute_status docstring)

These tests hit the ROOT app (where /api/private/* is mounted) using a
fresh TestClient + dependency override pattern. We don't reuse the shared
test_client fixture because that one binds to fingerprint_app, which has
no /api/private routes.
"""

import os
from datetime import datetime, date as date_type, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main_unified import app
from app.models.models import AttendanceRecord, Device, Employee
from app.utils.timezone import BANGKOK_TZ


BY_DATE_PATH = "/api/private/attendance/by-date"


# ---------------------------------------------------------------------------
# Fixtures (local to this file — don't share session with the global one
# because the global test_client binds to fingerprint_app, not the root app)
# ---------------------------------------------------------------------------


@pytest.fixture
def by_date_engine():
    """Isolated in-memory SQLite engine for by-date tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA synchronous = OFF")
        cursor.execute("PRAGMA journal_mode = MEMORY")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def by_date_session(by_date_engine):
    """Session bound to the local engine."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=by_date_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def by_date_client(by_date_engine):
    """
    TestClient for the ROOT app with a dependency override that uses the
    by_date_engine. Yields a tuple (client, session_factory) so tests can
    seed data through the same engine.

    IMPORTANT: We deliberately do NOT use TestClient as a context manager.
    Doing so triggers the FastAPI lifespan, which boots the APScheduler
    background tasks — these reach into the (already-closed) asyncio event
    loop after the first test and crash subsequent tests. Skipping the
    lifespan is safe: the /by-date endpoint is purely DB-backed and has no
    startup dependencies.
    """
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=by_date_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client, SessionLocal
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def seed_device(by_date_session):
    """Single device used as foreign key for all attendance records."""
    device = Device(
        name="test-zk-device",
        ip_address="192.168.1.10",
        port=4370,
        password=0,
        is_active=True,
    )
    by_date_session.add(device)
    by_date_session.commit()
    by_date_session.refresh(device)
    return device


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_employee(
    session,
    badge: str,
    display_name: str,
    is_active: bool = True,
    english_name: str | None = None,
) -> Employee:
    employee = Employee(
        badge_number=badge,
        english_name=english_name,
        thai_name=None,
        display_name=display_name,
        is_active=is_active,
        is_hidden=False,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


def _bangkok_to_utc_naive(bangkok_dt: datetime) -> datetime:
    """Match the storage convention: convert Bangkok-aware → UTC-naive."""
    if bangkok_dt.tzinfo is None:
        bangkok_dt = bangkok_dt.replace(tzinfo=BANGKOK_TZ)
    return bangkok_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _add_punch(
    session,
    badge: str,
    device_id: int,
    bangkok_dt: datetime,
    punch_type: int = 0,
) -> AttendanceRecord:
    record = AttendanceRecord(
        employee_badge_number=badge,
        device_id=device_id,
        timestamp=_bangkok_to_utc_naive(bangkok_dt),
        punch_type=punch_type,
        status=0,
    )
    session.add(record)
    session.commit()
    return record


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestByDateEndpoint:
    """Contract tests for /api/private/attendance/by-date."""

    def test_empty_day_returns_zero_rows(
        self, by_date_client, by_date_session, seed_device
    ):
        """No punches that day → empty rows list.

        Pre 2026-05 this returned one absent row per active employee.
        Absence tracking now waits on per-employee schedules; today the
        endpoint only emits rows for employees who actually punched.
        """
        _make_employee(by_date_session, "1001", "Somchai")
        _make_employee(by_date_session, "1002", "Niran")

        client, _ = by_date_client
        target = date_type(2026, 5, 14)
        response = client.get(BY_DATE_PATH, params={"date": target.isoformat()})

        assert response.status_code == 200
        body = response.json()
        assert body["date"] == "2026-05-14"
        assert body["expected_start_time"] == "09:00"
        assert body["rows"] == []

    def test_two_punches_around_expected_start_yields_on_time(
        self, by_date_client, by_date_session, seed_device
    ):
        """First punch before 09:00 + last punch after → on_time with hours."""
        _make_employee(by_date_session, "2001", "Somchai")

        target = date_type(2026, 5, 14)
        first_in = datetime(2026, 5, 14, 8, 52, tzinfo=BANGKOK_TZ)
        last_out = datetime(2026, 5, 14, 17, 31, tzinfo=BANGKOK_TZ)
        _add_punch(by_date_session, "2001", seed_device.id, first_in, punch_type=0)
        _add_punch(by_date_session, "2001", seed_device.id, last_out, punch_type=1)

        client, _ = by_date_client
        response = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        assert response.status_code == 200
        body = response.json()
        assert len(body["rows"]) == 1
        row = body["rows"][0]
        assert row["badge_number"] == "2001"
        assert row["display_name"] == "Somchai"
        assert row["first_in"] == "08:52"
        assert row["last_out"] == "17:31"
        assert row["status"] == "on_time"
        # 17:31 - 08:52 = 8h 39m = 8.65 hours (rounded to 2 decimals)
        assert row["hours_worked"] == pytest.approx(8.65, abs=0.01)

    def test_first_punch_after_expected_start_yields_late(
        self, by_date_client, by_date_session, seed_device
    ):
        """First punch at 09:15 → status='late'."""
        _make_employee(by_date_session, "3001", "LateBird")

        target = date_type(2026, 5, 14)
        first_in = datetime(2026, 5, 14, 9, 15, tzinfo=BANGKOK_TZ)
        last_out = datetime(2026, 5, 14, 18, 0, tzinfo=BANGKOK_TZ)
        _add_punch(by_date_session, "3001", seed_device.id, first_in, punch_type=0)
        _add_punch(by_date_session, "3001", seed_device.id, last_out, punch_type=1)

        client, _ = by_date_client
        response = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        assert response.status_code == 200
        row = response.json()["rows"][0]
        assert row["status"] == "late"
        assert row["first_in"] == "09:15"
        assert row["last_out"] == "18:00"

    def test_inactive_employees_excluded(
        self, by_date_client, by_date_session, seed_device
    ):
        """is_active=False employees never appear, even if they punched.

        We have to give both employees punches now that the endpoint
        filters to "actually punched today" — otherwise neither would
        appear and the inactive-filter behaviour wouldn't be exercised.
        """
        _make_employee(by_date_session, "4001", "ActiveAlice")
        _make_employee(by_date_session, "4002", "InactiveBob", is_active=False)

        target = date_type(2026, 5, 14)
        for badge in ("4001", "4002"):
            _add_punch(
                by_date_session, badge, seed_device.id,
                datetime(2026, 5, 14, 9, 0, tzinfo=BANGKOK_TZ),
            )

        client, _ = by_date_client
        response = client.get(
            BY_DATE_PATH, params={"date": target.isoformat()}
        )
        assert response.status_code == 200
        badges = [row["badge_number"] for row in response.json()["rows"]]
        assert "4001" in badges
        assert "4002" not in badges

    def test_invalid_date_format_returns_400(self, by_date_client):
        """Bad date string → 400 with helpful detail."""
        client, _ = by_date_client
        response = client.get(BY_DATE_PATH, params={"date": "not-a-date"})
        assert response.status_code == 400
        assert "YYYY-MM-DD" in response.json()["detail"]

    def test_date_defaults_to_today_bangkok_when_omitted(
        self, by_date_client, by_date_session, seed_device
    ):
        """No date param → response.date equals today in Bangkok."""
        _make_employee(by_date_session, "5001", "Today")
        client, _ = by_date_client
        response = client.get(BY_DATE_PATH)
        assert response.status_code == 200
        today_bangkok = datetime.now(BANGKOK_TZ).date().isoformat()
        assert response.json()["date"] == today_bangkok

    def test_sort_order_late_then_on_time_then_name(
        self, by_date_client, by_date_session, seed_device
    ):
        """Verify the sort: late > on_time, then by display_name.

        Absent rows were dropped 2026-05 — the no-punch employee from
        the previous version of this test (ZenAbsent) is removed because
        it would no longer appear in the response at all.
        """
        target = date_type(2026, 5, 14)

        # on_time — comes after late
        _make_employee(by_date_session, "9002", "Alpha")
        _add_punch(
            by_date_session,
            "9002",
            seed_device.id,
            datetime(2026, 5, 14, 8, 30, tzinfo=BANGKOK_TZ),
        )

        # late — comes first
        _make_employee(by_date_session, "9003", "Bravo")
        _add_punch(
            by_date_session,
            "9003",
            seed_device.id,
            datetime(2026, 5, 14, 10, 0, tzinfo=BANGKOK_TZ),
        )

        # second on_time, for the alphabetical tie-break check
        _make_employee(by_date_session, "9004", "Charlie")
        _add_punch(
            by_date_session,
            "9004",
            seed_device.id,
            datetime(2026, 5, 14, 7, 45, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        response = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        assert response.status_code == 200
        statuses = [row["status"] for row in response.json()["rows"]]
        names = [row["display_name"] for row in response.json()["rows"]]

        assert statuses == ["late", "on_time", "on_time"]
        # Within on_time, Alpha < Charlie alphabetically
        assert names[1:] == ["Alpha", "Charlie"]

    def test_employee_with_no_punches_omitted(
        self, by_date_client, by_date_session, seed_device
    ):
        """A second active employee with no punches today doesn't appear.

        Pins the new contract: only employees who actually punched are
        emitted. Was "absent" pre 2026-05; now omitted entirely.
        """
        target = date_type(2026, 5, 14)
        _make_employee(by_date_session, "PNCH", "Puncher")
        _add_punch(
            by_date_session, "PNCH", seed_device.id,
            datetime(2026, 5, 14, 8, 0, tzinfo=BANGKOK_TZ),
        )
        _make_employee(by_date_session, "NONE", "NoPunchToday")  # active, no punches

        client, _ = by_date_client
        response = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        assert response.status_code == 200
        badges = [row["badge_number"] for row in response.json()["rows"]]
        assert badges == ["PNCH"]

    def test_single_punch_yields_null_hours_worked(
        self, by_date_client, by_date_session, seed_device
    ):
        """One punch → first_in == last_out → hours_worked is null."""
        _make_employee(by_date_session, "6001", "SinglePunch")
        target = date_type(2026, 5, 14)
        _add_punch(
            by_date_session,
            "6001",
            seed_device.id,
            datetime(2026, 5, 14, 8, 0, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        response = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        assert response.status_code == 200
        row = response.json()["rows"][0]
        assert row["first_in"] == "08:00"
        # last_out equals first_in because there's only one timestamp
        assert row["last_out"] == "08:00"
        assert row["hours_worked"] is None

    def test_respects_expected_start_time_env_var(
        self, by_date_client, by_date_session, seed_device
    ):
        """EXPECTED_START_TIME=10:00 → 09:30 punch counts as on_time."""
        _make_employee(by_date_session, "7001", "FlexHours")
        target = date_type(2026, 5, 14)
        _add_punch(
            by_date_session,
            "7001",
            seed_device.id,
            datetime(2026, 5, 14, 9, 30, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        with patch.dict(os.environ, {"EXPECTED_START_TIME": "10:00"}):
            response = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        assert response.status_code == 200
        body = response.json()
        assert body["expected_start_time"] == "10:00"
        assert body["rows"][0]["status"] == "on_time"

    def test_bangkok_day_boundary_excludes_previous_day_punches(
        self, by_date_client, by_date_session, seed_device
    ):
        """A 23:55 punch on May 13 must NOT appear in the May 14 result."""
        _make_employee(by_date_session, "8001", "BoundaryCase")
        _add_punch(
            by_date_session,
            "8001",
            seed_device.id,
            datetime(2026, 5, 13, 23, 55, tzinfo=BANGKOK_TZ),
        )
        # And a real May-14 punch to confirm filtering works both ways
        _add_punch(
            by_date_session,
            "8001",
            seed_device.id,
            datetime(2026, 5, 14, 8, 45, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        response = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        assert response.status_code == 200
        row = response.json()["rows"][0]
        # first_in is the May-14 punch, not the May-13 one
        assert row["first_in"] == "08:45"
