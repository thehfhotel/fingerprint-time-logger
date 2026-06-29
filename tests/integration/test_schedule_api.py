"""
Integration tests for the employee schedule-history endpoints.

Endpoints under test (mounted at /api/private/employees):
  - GET    /{badge}/schedule                 → list versions, newest first
  - PUT    /{badge}/schedule                 → upsert one effective-dated version
  - DELETE /{badge}/schedule/{effective_from} → remove one version (204)

Each EmployeeSchedule row is the schedule that takes effect on its
effective_from date. Employee.role is a denormalised cache of the
as-of-today (Bangkok) version. These tests hit the ROOT app (where
/api/private/* is mounted) using a fresh TestClient + dependency
override, mirroring tests/integration/test_by_date_endpoint.py.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main_unified import app
from app.models.models import Employee, EmployeeSchedule
from app.utils.timezone import BANGKOK_TZ


def _schedule_path(badge):
    return f"/api/private/employees/{badge}/schedule"


def _today_bangkok_iso():
    return datetime.now(BANGKOK_TZ).date().isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def schedule_engine():
    """Isolated in-memory SQLite engine for schedule tests."""
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
def schedule_session(schedule_engine):
    """Session bound to the local engine for direct row assertions."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=schedule_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def schedule_client(schedule_engine):
    """TestClient for the ROOT app with a get_db override.

    Skipping the lifespan (no ``with`` block) keeps the APScheduler /
    zk_session daemons from booting and leaking event loops between tests.
    """
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=schedule_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_employee(session, badge, display_name="Worker", *, role=None, location=None):
    """Create a minimal Employee row."""
    employee = Employee(
        badge_number=badge,
        display_name=display_name,
        is_active=True,
        is_hidden=False,
        role=role,
        location=location,
    )
    session.add(employee)
    session.commit()
    session.refresh(employee)
    return employee


def _fetch_schedule(session, badge, effective_from):
    """Fresh query for one schedule row (bypasses stale identity-map state)."""
    session.expire_all()
    return (
        session.query(EmployeeSchedule)
        .filter(
            EmployeeSchedule.employee_badge_number == badge,
            EmployeeSchedule.effective_from == effective_from,
        )
        .first()
    )


def _fetch_employee_role(session, badge):
    session.expire_all()
    employee = session.query(Employee).filter(Employee.badge_number == badge).first()
    return employee.role


# ---------------------------------------------------------------------------
# PUT — create / upsert
# ---------------------------------------------------------------------------


class TestSchedulePutCreate:
    def test_put_creates_version_row_and_response(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E001")
        body = {
            "effective_from": "2026-06-01",
            "role": "technician",
            "work_days": [0, 1, 2, 3, 4],
            "work_start": "09:00",
            "work_end": "18:00",
        }
        resp = schedule_client.put(_schedule_path("E001"), json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["badge_number"] == "E001"
        assert data["effective_from"] == "2026-06-01"
        assert data["role"] == "technician"
        assert data["work_days"] == [0, 1, 2, 3, 4]
        assert data["work_start"] == "09:00"
        assert data["work_end"] == "18:00"

        from datetime import date as date_type, time as time_type

        row = _fetch_schedule(schedule_session, "E001", date_type(2026, 6, 1))
        assert row is not None
        assert row.role == "technician"
        assert row.work_days == "0,1,2,3,4"
        assert row.work_start == time_type(9, 0)
        assert row.work_end == time_type(18, 0)

    def test_put_dedupes_and_sorts_work_days(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E002")
        body = {
            "effective_from": "2026-06-01",
            "role": "housekeeping",
            "work_days": [4, 1, 1, 0],
            "work_start": "07:00",
            "work_end": "16:00",
        }
        resp = schedule_client.put(_schedule_path("E002"), json=body)
        assert resp.status_code == 200
        assert resp.json()["work_days"] == [0, 1, 4]

        from datetime import date as date_type

        row = _fetch_schedule(schedule_session, "E002", date_type(2026, 6, 1))
        assert row.work_days == "0,1,4"

    def test_put_empty_work_days_stores_null(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E003")
        body = {
            "effective_from": "2026-06-01",
            "role": "admin",
            "work_days": [],
        }
        resp = schedule_client.put(_schedule_path("E003"), json=body)
        assert resp.status_code == 200
        assert resp.json()["work_days"] == []

        from datetime import date as date_type

        row = _fetch_schedule(schedule_session, "E003", date_type(2026, 6, 1))
        assert row.work_days is None

    def test_put_upserts_same_effective_from(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E010")
        first = {
            "effective_from": "2026-06-01",
            "role": "technician",
            "work_days": [0, 1, 2],
            "work_start": "09:00",
            "work_end": "18:00",
        }
        assert schedule_client.put(_schedule_path("E010"), json=first).status_code == 200

        second = {
            "effective_from": "2026-06-01",
            "role": "housekeeping",
            "work_days": [5, 6],
            "work_start": "07:00",
            "work_end": "16:00",
        }
        resp = schedule_client.put(_schedule_path("E010"), json=second)
        assert resp.status_code == 200
        assert resp.json()["role"] == "housekeeping"
        assert resp.json()["work_days"] == [5, 6]

        schedule_session.expire_all()
        rows = (
            schedule_session.query(EmployeeSchedule)
            .filter(EmployeeSchedule.employee_badge_number == "E010")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].role == "housekeeping"
        assert rows[0].work_days == "5,6"

    def test_put_reception_forces_workdays_and_hours_null(
        self, schedule_client, schedule_session
    ):
        _make_employee(schedule_session, "R001")
        body = {
            "effective_from": "2026-06-01",
            "role": "reception",
            "work_days": [0, 1, 2, 3, 4],
            "work_start": "09:00",
            "work_end": "18:00",
        }
        resp = schedule_client.put(_schedule_path("R001"), json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "reception"
        assert data["work_days"] == []
        assert data["work_start"] is None
        assert data["work_end"] is None

        from datetime import date as date_type

        row = _fetch_schedule(schedule_session, "R001", date_type(2026, 6, 1))
        assert row.work_days is None
        assert row.work_start is None
        assert row.work_end is None

    def test_put_writes_location_to_employee(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E020")
        body = {
            "effective_from": "2026-06-01",
            "role": "technician",
            "work_days": [0, 1, 2, 3, 4],
            "work_start": "09:00",
            "work_end": "18:00",
            "location": "HF_VILLE",
        }
        assert schedule_client.put(_schedule_path("E020"), json=body).status_code == 200

        schedule_session.expire_all()
        employee = (
            schedule_session.query(Employee)
            .filter(Employee.badge_number == "E020")
            .first()
        )
        assert employee.location == "HF_VILLE"

    def test_put_updates_role_denormalised_cache(self, schedule_client, schedule_session):
        """A version effective today sets Employee.role to that role."""
        _make_employee(schedule_session, "E030", role=None)
        body = {
            "effective_from": _today_bangkok_iso(),
            "role": "technician",
            "work_days": [0, 1, 2, 3, 4],
            "work_start": "09:00",
            "work_end": "18:00",
        }
        assert schedule_client.put(_schedule_path("E030"), json=body).status_code == 200
        assert _fetch_employee_role(schedule_session, "E030") == "technician"

    def test_put_future_version_does_not_change_role_cache(
        self, schedule_client, schedule_session
    ):
        """A version effective in the future must not become the current role."""
        _make_employee(schedule_session, "E031", role=None)
        body = {
            "effective_from": "2999-01-01",
            "role": "technician",
            "work_days": [0, 1, 2, 3, 4],
            "work_start": "09:00",
            "work_end": "18:00",
        }
        assert schedule_client.put(_schedule_path("E031"), json=body).status_code == 200
        assert _fetch_employee_role(schedule_session, "E031") is None


# ---------------------------------------------------------------------------
# PUT — validation
# ---------------------------------------------------------------------------


class TestSchedulePutValidation:
    def test_put_unknown_employee_returns_404(self, schedule_client):
        body = {"effective_from": "2026-06-01", "role": "technician"}
        resp = schedule_client.put(_schedule_path("NOPE"), json=body)
        assert resp.status_code == 404

    def test_put_bad_effective_from_returns_400(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E100")
        resp = schedule_client.put(
            _schedule_path("E100"), json={"effective_from": "not-a-date"}
        )
        assert resp.status_code == 400
        assert "YYYY-MM-DD" in resp.json()["detail"]

    def test_put_bad_role_returns_400(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E101")
        resp = schedule_client.put(
            _schedule_path("E101"),
            json={"effective_from": "2026-06-01", "role": "manager"},
        )
        assert resp.status_code == 400
        assert "role" in resp.json()["detail"]

    def test_put_work_days_out_of_range_returns_400(
        self, schedule_client, schedule_session
    ):
        _make_employee(schedule_session, "E102")
        resp = schedule_client.put(
            _schedule_path("E102"),
            json={
                "effective_from": "2026-06-01",
                "role": "technician",
                "work_days": [0, 7],
            },
        )
        assert resp.status_code == 400
        assert "work_days" in resp.json()["detail"]

    def test_put_only_work_start_returns_400(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E103")
        resp = schedule_client.put(
            _schedule_path("E103"),
            json={
                "effective_from": "2026-06-01",
                "role": "technician",
                "work_start": "09:00",
            },
        )
        assert resp.status_code == 400
        assert "work_start" in resp.json()["detail"]

    def test_put_only_work_end_returns_400(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E104")
        resp = schedule_client.put(
            _schedule_path("E104"),
            json={
                "effective_from": "2026-06-01",
                "role": "technician",
                "work_end": "18:00",
            },
        )
        assert resp.status_code == 400

    def test_put_bad_time_format_returns_400(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E105")
        resp = schedule_client.put(
            _schedule_path("E105"),
            json={
                "effective_from": "2026-06-01",
                "role": "technician",
                "work_start": "9am",
                "work_end": "6pm",
            },
        )
        assert resp.status_code == 400

    def test_put_bad_location_returns_400(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "E106")
        resp = schedule_client.put(
            _schedule_path("E106"),
            json={
                "effective_from": "2026-06-01",
                "role": "technician",
                "work_days": [0, 1, 2, 3, 4],
                "work_start": "09:00",
                "work_end": "18:00",
                "location": "MARS",
            },
        )
        assert resp.status_code == 400
        assert "location" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET — list
# ---------------------------------------------------------------------------


class TestScheduleGet:
    def test_get_unknown_employee_returns_404(self, schedule_client):
        assert schedule_client.get(_schedule_path("NOPE")).status_code == 404

    def test_get_empty_history_returns_empty_list(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "G000")
        resp = schedule_client.get(_schedule_path("G000"))
        assert resp.status_code == 200
        assert resp.json() == {"badge_number": "G000", "schedules": []}

    def test_get_returns_versions_descending_with_parsed_fields(
        self, schedule_client, schedule_session
    ):
        _make_employee(schedule_session, "G001")
        versions = [
            {
                "effective_from": "2026-01-01",
                "role": "housekeeping",
                "work_days": [0, 1, 2, 3, 4],
                "work_start": "07:00",
                "work_end": "16:00",
            },
            {
                "effective_from": "2026-03-01",
                "role": "technician",
                "work_days": [1, 2, 3],
                "work_start": "09:30",
                "work_end": "18:30",
            },
            {
                "effective_from": "2026-02-01",
                "role": "admin",
                "work_days": [],
            },
        ]
        for version in versions:
            assert schedule_client.put(_schedule_path("G001"), json=version).status_code == 200

        resp = schedule_client.get(_schedule_path("G001"))
        assert resp.status_code == 200
        schedules = resp.json()["schedules"]

        effective_dates = [s["effective_from"] for s in schedules]
        assert effective_dates == ["2026-03-01", "2026-02-01", "2026-01-01"]

        newest = schedules[0]
        assert newest["role"] == "technician"
        assert newest["work_days"] == [1, 2, 3]
        assert newest["work_start"] == "09:30"
        assert newest["work_end"] == "18:30"

        middle = schedules[1]
        assert middle["work_days"] == []
        assert middle["work_start"] is None
        assert middle["work_end"] is None


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


class TestScheduleDelete:
    def test_delete_removes_version(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "D001")
        body = {
            "effective_from": "2026-06-01",
            "role": "technician",
            "work_days": [0, 1, 2, 3, 4],
            "work_start": "09:00",
            "work_end": "18:00",
        }
        assert schedule_client.put(_schedule_path("D001"), json=body).status_code == 200

        resp = schedule_client.delete(_schedule_path("D001") + "/2026-06-01")
        assert resp.status_code == 204

        assert schedule_client.get(_schedule_path("D001")).json()["schedules"] == []

    def test_delete_recomputes_role_cache_to_none(self, schedule_client, schedule_session):
        """Deleting the only (current) version clears Employee.role."""
        _make_employee(schedule_session, "D002", role=None)
        today = _today_bangkok_iso()
        body = {
            "effective_from": today,
            "role": "technician",
            "work_days": [0, 1, 2, 3, 4],
            "work_start": "09:00",
            "work_end": "18:00",
        }
        assert schedule_client.put(_schedule_path("D002"), json=body).status_code == 200
        assert _fetch_employee_role(schedule_session, "D002") == "technician"

        resp = schedule_client.delete(_schedule_path("D002") + f"/{today}")
        assert resp.status_code == 204
        assert _fetch_employee_role(schedule_session, "D002") is None

    def test_delete_unknown_employee_returns_404(self, schedule_client):
        resp = schedule_client.delete(_schedule_path("NOPE") + "/2026-06-01")
        assert resp.status_code == 404

    def test_delete_missing_version_returns_404(self, schedule_client, schedule_session):
        _make_employee(schedule_session, "D003")
        resp = schedule_client.delete(_schedule_path("D003") + "/2026-06-01")
        assert resp.status_code == 404
