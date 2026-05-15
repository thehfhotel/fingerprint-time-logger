"""
Integration tests for /api/private/shifts/* and the role/default-shift
endpoint on /api/private/employees/{badge}/shift.

Lifecycle covered:
  1. GET /api/private/shifts/ — lists active shifts (seeded in fixture).
  2. PUT /api/private/employees/{badge}/shift — sets role + default.
  3. GET /api/private/shifts/assignments — lists per-day overrides.
  4. PUT /api/private/shifts/assignments/{badge}/{date} — set/clear one.
  5. DELETE /api/private/shifts/assignments/{badge}/{date} — remove.

Uses the same isolated-engine fixture pattern as test_by_date_endpoint.py
to avoid lifespan-scheduler interference.
"""
from datetime import date as date_type, time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main_unified import app
from app.models.models import Employee, Shift


SHIFTS_ROOT = "/api/private/shifts"


@pytest.fixture
def shifts_engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi, _rec):
        c = dbapi.cursor()
        c.execute("PRAGMA synchronous = OFF")
        c.close()

    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def shifts_session(shifts_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=shifts_engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def shifts_client(shifts_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=shifts_engine)

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


@pytest.fixture
def seeded_shifts(shifts_session):
    rows = [
        Shift(code="NORMAL",    name_th="ปกติ", start_time=time(8, 0),  end_time=time(17, 0)),
        Shift(code="MORNING",   name_th="เช้า", start_time=time(7, 0),  end_time=time(16, 0)),
        Shift(code="MID",       name_th="สาย", start_time=time(11, 0), end_time=time(20, 0)),
        Shift(code="AFTERNOON", name_th="บ่าย", start_time=time(13, 0), end_time=time(22, 0)),
        Shift(code="NIGHT",     name_th="ดึก", start_time=time(22, 0), end_time=time(7, 0)),
    ]
    for r in rows:
        shifts_session.add(r)
    shifts_session.commit()
    for r in rows:
        shifts_session.refresh(r)
    return {r.code: r for r in rows}


@pytest.fixture
def seeded_employee(shifts_session):
    e = Employee(
        badge_number="EMP01",
        display_name="Test Employee",
        is_active=True,
        is_hidden=False,
    )
    shifts_session.add(e)
    shifts_session.commit()
    shifts_session.refresh(e)
    return e


class TestListShifts:
    def test_list_returns_seeded_active_shifts_sorted_by_start_time(
        self, shifts_client, seeded_shifts
    ):
        resp = shifts_client.get(SHIFTS_ROOT + "/")
        assert resp.status_code == 200
        codes = [r["code"] for r in resp.json()]
        # Sorted by start_time: MORNING 07, NORMAL 08, MID 11, AFTERNOON 13, NIGHT 22
        assert codes == ["MORNING", "NORMAL", "MID", "AFTERNOON", "NIGHT"]

    def test_list_includes_crosses_midnight_flag(
        self, shifts_client, seeded_shifts
    ):
        resp = shifts_client.get(SHIFTS_ROOT + "/")
        night = next(r for r in resp.json() if r["code"] == "NIGHT")
        assert night["crosses_midnight"] is True
        normal = next(r for r in resp.json() if r["code"] == "NORMAL")
        assert normal["crosses_midnight"] is False


class TestEmployeeShiftAssignment:
    """PUT /api/private/employees/{badge}/shift — set role + default."""

    URL = "/api/private/employees/EMP01/shift"

    def test_set_role_and_default_shift(
        self, shifts_client, seeded_shifts, seeded_employee, shifts_session
    ):
        resp = shifts_client.put(self.URL, json={
            "role": "housekeeping",
            "default_shift_code": "MORNING",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "housekeeping"
        assert body["default_shift_code"] == "MORNING"

        shifts_session.expire_all()
        emp = shifts_session.query(Employee).filter_by(badge_number="EMP01").first()
        assert emp.role == "housekeeping"
        assert emp.default_shift.code == "MORNING"

    def test_clear_role(
        self, shifts_client, seeded_shifts, seeded_employee, shifts_session
    ):
        # First set, then clear with null.
        shifts_client.put(self.URL, json={"role": "technician"})
        resp = shifts_client.put(self.URL, json={"role": None})
        assert resp.status_code == 200
        assert resp.json()["role"] is None

    def test_invalid_role_rejected(
        self, shifts_client, seeded_shifts, seeded_employee
    ):
        resp = shifts_client.put(self.URL, json={"role": "not-a-role"})
        assert resp.status_code == 400
        assert "role" in resp.json()["detail"]

    def test_unknown_shift_code_rejected(
        self, shifts_client, seeded_shifts, seeded_employee
    ):
        resp = shifts_client.put(self.URL, json={"default_shift_code": "ZZZ"})
        assert resp.status_code == 400

    def test_404_for_unknown_employee(self, shifts_client, seeded_shifts):
        resp = shifts_client.put(
            "/api/private/employees/UNKNOWN/shift",
            json={"role": "admin"},
        )
        assert resp.status_code == 404


class TestPerDayAssignments:
    """The override CRUD: GET range, PUT one, DELETE one."""

    def test_put_creates_assignment_with_shift(
        self, shifts_client, seeded_shifts, seeded_employee, shifts_session
    ):
        resp = shifts_client.put(
            f"{SHIFTS_ROOT}/assignments/EMP01/2026-05-14",
            json={"shift_code": "NIGHT"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["employee_badge_number"] == "EMP01"
        assert body["date"] == "2026-05-14"
        assert body["shift_code"] == "NIGHT"

    def test_put_with_null_shift_code_means_off(
        self, shifts_client, seeded_shifts, seeded_employee
    ):
        resp = shifts_client.put(
            f"{SHIFTS_ROOT}/assignments/EMP01/2026-05-14",
            json={"shift_code": None},
        )
        assert resp.status_code == 200
        assert resp.json()["shift_code"] is None

    def test_put_is_idempotent(
        self, shifts_client, seeded_shifts, seeded_employee, shifts_session
    ):
        url = f"{SHIFTS_ROOT}/assignments/EMP01/2026-05-14"
        shifts_client.put(url, json={"shift_code": "MORNING"})
        shifts_client.put(url, json={"shift_code": "NIGHT"})
        # Only one row should exist for that (badge, date) pair.
        from app.models.models import ShiftAssignment
        rows = shifts_session.query(ShiftAssignment).all()
        assert len(rows) == 1
        assert rows[0].shift.code == "NIGHT"

    def test_put_404_for_unknown_employee(
        self, shifts_client, seeded_shifts
    ):
        resp = shifts_client.put(
            f"{SHIFTS_ROOT}/assignments/UNKNOWN/2026-05-14",
            json={"shift_code": "MORNING"},
        )
        assert resp.status_code == 404

    def test_put_400_for_unknown_shift_code(
        self, shifts_client, seeded_shifts, seeded_employee
    ):
        resp = shifts_client.put(
            f"{SHIFTS_ROOT}/assignments/EMP01/2026-05-14",
            json={"shift_code": "BOGUS"},
        )
        assert resp.status_code == 400

    def test_get_assignments_in_range(
        self, shifts_client, seeded_shifts, seeded_employee
    ):
        for d in ("2026-05-14", "2026-05-15", "2026-05-20"):
            shifts_client.put(
                f"{SHIFTS_ROOT}/assignments/EMP01/{d}",
                json={"shift_code": "MID"},
            )
        # Range 2026-05-14 to 2026-05-15 inclusive → 2 rows.
        resp = shifts_client.get(
            f"{SHIFTS_ROOT}/assignments",
            params={"from": "2026-05-14", "to": "2026-05-15"},
        )
        assert resp.status_code == 200
        dates = sorted(r["date"] for r in resp.json())
        assert dates == ["2026-05-14", "2026-05-15"]

    def test_get_assignments_400_when_to_before_from(self, shifts_client):
        resp = shifts_client.get(
            f"{SHIFTS_ROOT}/assignments",
            params={"from": "2026-05-15", "to": "2026-05-14"},
        )
        assert resp.status_code == 400

    def test_get_assignments_400_when_range_over_31_days(self, shifts_client):
        resp = shifts_client.get(
            f"{SHIFTS_ROOT}/assignments",
            params={"from": "2026-01-01", "to": "2026-03-01"},
        )
        assert resp.status_code == 400

    def test_delete_assignment(
        self, shifts_client, seeded_shifts, seeded_employee, shifts_session
    ):
        url = f"{SHIFTS_ROOT}/assignments/EMP01/2026-05-14"
        shifts_client.put(url, json={"shift_code": "MORNING"})
        resp = shifts_client.delete(url)
        assert resp.status_code == 204

        from app.models.models import ShiftAssignment
        assert shifts_session.query(ShiftAssignment).count() == 0

    def test_delete_is_idempotent(self, shifts_client, seeded_shifts, seeded_employee):
        """Deleting a non-existent assignment is fine — returns 204."""
        resp = shifts_client.delete(
            f"{SHIFTS_ROOT}/assignments/EMP01/2026-05-14"
        )
        assert resp.status_code == 204
