"""
Integration tests for GET /api/private/attendance/monthly/{year}/{month}.

Endpoint contract:
  - Path: /api/private/attendance/monthly/{year}/{month}
  - Query: location=HF|HF_VILLE (optional)
  - Response: { year, month, days_in_month, employees: [...] }
  - One employee entry per ACTIVE, trackable employee (untracked all
    month → omitted). Each entry has `days` (length == days_in_month,
    indexed day-1) and `totals`.
  - Per-day status: present | absent | off | leave | untracked
  - Lateness tiers on present days: 0 grace, 1 late, 2 late+minutes, 3 severe.

Mirrors the fixture/seed pattern of test_by_date_endpoint.py.
"""

from datetime import datetime, date as date_type, time, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main_unified import app
from app.models.models import (
    AttendanceRecord, Device, Employee, EmployeeLeave, PublicHoliday,
    Shift, ShiftAssignment,
)
from app.utils.timezone import BANGKOK_TZ


def _path(year, month):
    return f"/api/private/attendance/monthly/{year}/{month}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def monthly_engine():
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
def monthly_session(monthly_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=monthly_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def monthly_client(monthly_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=monthly_engine)

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
def seed_device(monthly_session):
    device = Device(
        name="test-zk-device", ip_address="192.168.1.10",
        port=4370, password=0, is_active=True,
    )
    monthly_session.add(device)
    monthly_session.commit()
    monthly_session.refresh(device)
    return device


@pytest.fixture
def seeded_shifts(monthly_session):
    rows = [
        Shift(code="NORMAL",    letter=None, name_th="ปกติ", start_time=time(8, 0),  end_time=time(17, 0)),
        Shift(code="MORNING",   letter="A", name_th="เช้า", start_time=time(7, 0),  end_time=time(16, 0)),
        Shift(code="MID",       letter="C", name_th="สาย", start_time=time(11, 0), end_time=time(20, 0)),
        Shift(code="AFTERNOON", letter="B", name_th="บ่าย", start_time=time(13, 0), end_time=time(22, 0)),
        Shift(code="NIGHT",     letter="D", name_th="ดึก", start_time=time(22, 0), end_time=time(7, 0)),
    ]
    for r in rows:
        monthly_session.add(r)
    monthly_session.commit()
    for r in rows:
        monthly_session.refresh(r)
    return {r.code: r for r in rows}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_employee(session, badge, display_name, *, is_active=True, role=None,
                   default_shift=None, location=None):
    e = Employee(
        badge_number=badge, english_name=None, thai_name=None,
        display_name=display_name, is_active=is_active, is_hidden=False,
        role=role, default_shift_id=default_shift.id if default_shift else None,
        location=location,
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


def _bangkok_to_utc_naive(bangkok_dt):
    if bangkok_dt.tzinfo is None:
        bangkok_dt = bangkok_dt.replace(tzinfo=BANGKOK_TZ)
    return bangkok_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _add_punch(session, badge, device_id, bangkok_dt, punch_type=0):
    session.add(AttendanceRecord(
        employee_badge_number=badge, device_id=device_id,
        timestamp=_bangkok_to_utc_naive(bangkok_dt), punch_type=punch_type, status=0,
    ))
    session.commit()


def _assign(session, badge, on_date, shift=None):
    session.add(ShiftAssignment(
        employee_badge_number=badge, date=on_date,
        shift_id=shift.id if shift else None,
    ))
    session.commit()


def _emp(body, badge):
    return next(e for e in body["employees"] if e["badge_number"] == badge)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMonthlyShape:
    def test_empty_db(self, monthly_client, seed_device, seeded_shifts):
        resp = monthly_client.get(_path(2026, 5))
        assert resp.status_code == 200
        body = resp.json()
        assert body["year"] == 2026
        assert body["month"] == 5
        assert body["days_in_month"] == 31
        assert body["employees"] == []

    def test_february_days_in_month(self, monthly_client, seed_device, seeded_shifts):
        body = monthly_client.get(_path(2026, 2)).json()
        assert body["days_in_month"] == 28

    def test_days_array_aligns_to_calendar(self, monthly_client, monthly_session,
                                           seed_device, seeded_shifts):
        _make_employee(monthly_session, "T1", "Tech", role="technician")
        body = monthly_client.get(_path(2026, 2)).json()
        days = _emp(body, "T1")["days"]
        assert len(days) == 28
        assert days[0]["date"] == "2026-02-01"
        assert days[-1]["date"] == "2026-02-28"


class TestMonthlyUntracked:
    def test_untracked_all_month_is_omitted(self, monthly_client, monthly_session,
                                            seed_device, seeded_shifts):
        # No role + no default shift → untracked every day → omitted.
        _make_employee(monthly_session, "U1", "Untracked")
        _add_punch(monthly_session, "U1", seed_device.id,
                   datetime(2026, 5, 14, 8, 0, tzinfo=BANGKOK_TZ))
        body = monthly_client.get(_path(2026, 5)).json()
        assert body["employees"] == []

    def test_inactive_excluded(self, monthly_client, monthly_session,
                               seed_device, seeded_shifts):
        _make_employee(monthly_session, "A1", "Active", role="technician")
        _make_employee(monthly_session, "A2", "Inactive", role="technician",
                       is_active=False)
        body = monthly_client.get(_path(2026, 5)).json()
        assert [e["badge_number"] for e in body["employees"]] == ["A1"]


class TestMonthlyLatenessTiers:
    """One reception employee, NORMAL (08:00) assigned May 1–6, exercising
    every lateness tier plus an absent day. Reception is only tracked on
    assigned days, so all other days are 'off' — giving deterministic totals."""

    def _seed(self, session, device, shifts):
        _make_employee(session, "RC1", "Reception One", role="reception", location="HF")
        for day in range(1, 7):
            _assign(session, "RC1", date_type(2026, 5, day), shifts["NORMAL"])

        def punch(day, h, m):
            _add_punch(session, "RC1", device.id,
                       datetime(2026, 5, day, h, m, tzinfo=BANGKOK_TZ))

        # May 1: on the dot → on-time (tier 0), out 17:00 → 9.0h
        punch(1, 8, 0); punch(1, 17, 0)
        # May 2: 8 min late → tier 1
        punch(2, 8, 8); punch(2, 17, 0)
        # May 3: 20 min late → tier 2
        punch(3, 8, 20); punch(3, 17, 0)
        # May 4: 45 min late → tier 3 (severe)
        punch(4, 8, 45); punch(4, 17, 0)
        # May 5: 3 min late → grace, still tier 0
        punch(5, 8, 3); punch(5, 17, 0)
        # May 6: assigned but no punch → absent

    def test_per_day_tiers(self, monthly_client, monthly_session, seed_device, seeded_shifts):
        self._seed(monthly_session, seed_device, seeded_shifts)
        body = monthly_client.get(_path(2026, 5)).json()
        days = _emp(body, "RC1")["days"]

        # index = day - 1
        assert days[0]["status"] == "present"
        assert days[0]["late_tier"] == 0
        assert days[0]["late_minutes"] == 0
        assert days[0]["hours_worked"] == 9.0
        assert days[0]["first_in"] == "08:00"
        assert days[0]["last_out"] == "17:00"

        assert days[1]["late_tier"] == 1
        assert days[1]["late_minutes"] == 8

        assert days[2]["late_tier"] == 2
        assert days[2]["late_minutes"] == 20

        assert days[3]["late_tier"] == 3
        assert days[3]["late_minutes"] == 45

        assert days[4]["status"] == "present"
        assert days[4]["late_tier"] == 0   # 3 min is within grace
        assert days[4]["late_minutes"] == 3

        assert days[5]["status"] == "absent"
        assert days[5]["first_in"] is None

    def test_totals(self, monthly_client, monthly_session, seed_device, seeded_shifts):
        self._seed(monthly_session, seed_device, seeded_shifts)
        body = monthly_client.get(_path(2026, 5)).json()
        t = _emp(body, "RC1")["totals"]

        assert t["worked_days"] == 5
        assert t["absent_days"] == 1
        assert t["late_count"] == 3            # tiers 1,2,3 (May 2,3,4)
        assert t["late_minutes_total"] == 8 + 20 + 45
        assert t["severe_count"] == 1          # May 4
        # All other days of May (31 - 6 assigned) are reception-off.
        assert t["off_days"] == 31 - 6
        assert t["hours_total"] > 0


class TestMonthlyLeavesAndHolidays:
    def test_vacation_is_leave(self, monthly_client, monthly_session,
                               seed_device, seeded_shifts):
        _make_employee(monthly_session, "L1", "Vac", role="technician")
        monthly_session.add(EmployeeLeave(
            employee_badge_number="L1", date=date_type(2026, 5, 10),
            leave_type="vacation",
        ))
        monthly_session.commit()
        body = monthly_client.get(_path(2026, 5)).json()
        emp = _emp(body, "L1")
        day = emp["days"][9]  # May 10
        assert day["status"] == "leave"
        assert day["leave_type"] == "vacation"
        assert emp["totals"]["leave_days"] == 1

    def test_public_holiday_is_off(self, monthly_client, monthly_session,
                                   seed_device, seeded_shifts):
        _make_employee(monthly_session, "H1", "Tech", role="technician")
        monthly_session.add(PublicHoliday(date=date_type(2026, 5, 5), name="วันหยุด"))
        monthly_session.commit()
        # Even with a punch, the holiday wins.
        _add_punch(monthly_session, "H1", seed_device.id,
                   datetime(2026, 5, 5, 8, 0, tzinfo=BANGKOK_TZ))
        body = monthly_client.get(_path(2026, 5)).json()
        day = _emp(body, "H1")["days"][4]  # May 5
        assert day["status"] == "off"
        assert day["leave_type"] == "public_holiday"


class TestMonthlyValidation:
    def test_bad_month(self, monthly_client):
        assert monthly_client.get(_path(2026, 13)).status_code == 400

    def test_bad_year(self, monthly_client):
        assert monthly_client.get(_path(1999, 5)).status_code == 400

    def test_bad_location(self, monthly_client, seed_device, seeded_shifts):
        resp = monthly_client.get(_path(2026, 5), params={"location": "MARS"})
        assert resp.status_code == 400
        assert "location" in resp.json()["detail"]


class TestMonthlyLocationFilter:
    def test_filter_hf(self, monthly_client, monthly_session, seed_device, seeded_shifts):
        _make_employee(monthly_session, "HF1", "HFTech", role="technician", location="HF")
        _make_employee(monthly_session, "HV1", "VilleTech", role="technician", location="HF_VILLE")
        body = monthly_client.get(_path(2026, 5), params={"location": "HF"}).json()
        assert [e["badge_number"] for e in body["employees"]] == ["HF1"]
