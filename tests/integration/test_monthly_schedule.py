"""
End-to-end integration tests: the monthly report driven by effective-dated
EmployeeSchedule rows (the 2026-06 upgrade). Proves the three behaviours the
schedule feature adds, all the way through GET /attendance/monthly:

  1. Per-employee workdays — days off the weekly pattern read as "off",
     NOT "absent".
  2. Custom per-employee hours — lateness is measured against the
     employee's own start time, not a role-default shift.
  3. Effective-dated role/schedule history — each day uses the schedule
     version that applied on that date (a mid-month role change is
     honoured retroactively-correctly).

Mirrors the fixture pattern of test_monthly_endpoint.py.
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
    AttendanceRecord, Device, Employee, EmployeeSchedule, Shift,
)
from app.utils.timezone import BANGKOK_TZ


def _path(year, month):
    return f"/api/private/attendance/monthly/{year}/{month}"


# --- Fixtures ---------------------------------------------------------------


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, echo=False,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client(engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def device(session):
    d = Device(name="zk", ip_address="192.168.1.10", port=4370, password=0, is_active=True)
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


@pytest.fixture
def shifts(session):
    rows = [
        Shift(code="NORMAL", letter=None, name_th="ปกติ", start_time=time(8, 0), end_time=time(17, 0)),
        Shift(code="MORNING", letter="A", name_th="เช้า", start_time=time(7, 0), end_time=time(16, 0)),
        Shift(code="MID", letter="C", name_th="สาย", start_time=time(11, 0), end_time=time(20, 0)),
        Shift(code="AFTERNOON", letter="B", name_th="บ่าย", start_time=time(13, 0), end_time=time(22, 0)),
        Shift(code="NIGHT", letter="D", name_th="ดึก", start_time=time(22, 0), end_time=time(7, 0)),
    ]
    for r in rows:
        session.add(r)
    session.commit()
    return {r.code: r for r in rows}


# --- Helpers ----------------------------------------------------------------


def _emp(session, badge, name, *, role=None, location=None):
    e = Employee(
        badge_number=badge, display_name=name, is_active=True, is_hidden=False,
        role=role, location=location,
    )
    session.add(e)
    session.commit()
    return e


def _schedule(session, badge, effective_from, *, role, work_days=None,
              work_start=None, work_end=None):
    session.add(EmployeeSchedule(
        employee_badge_number=badge,
        effective_from=effective_from,
        role=role,
        work_days=work_days,
        work_start=work_start,
        work_end=work_end,
    ))
    session.commit()


def _punch(session, badge, device_id, bkk_dt):
    utc = bkk_dt.astimezone(timezone.utc).replace(tzinfo=None)
    session.add(AttendanceRecord(
        employee_badge_number=badge, device_id=device_id,
        timestamp=utc, punch_type=0, status=0,
    ))
    session.commit()


def _emp_row(body, badge):
    return next(e for e in body["employees"] if e["badge_number"] == badge)


# --- 1. Workdays -------------------------------------------------------------


class TestScheduleWorkdays:
    def test_off_pattern_days_are_off_not_absent(self, client, session, device, shifts):
        """Technician, Mon–Fri only, no punches all month → weekdays read
        'absent', weekends read 'off' (driven purely by work_days)."""
        _emp(session, "T1", "Tech", role="technician")
        _schedule(session, "T1", date_type(2026, 5, 1), role="technician",
                  work_days="0,1,2,3,4", work_start=time(8, 0), work_end=time(17, 0))

        body = client.get(_path(2026, 5)).json()
        days = _emp_row(body, "T1")["days"]
        for d in days:
            wd = date_type.fromisoformat(d["date"]).weekday()
            if wd in (0, 1, 2, 3, 4):
                assert d["status"] == "absent", d
            else:
                assert d["status"] == "off", d

        t = _emp_row(body, "T1")["totals"]
        # May 2026: count weekdays vs weekend days.
        weekdays = sum(1 for n in range(1, 32) if date_type(2026, 5, n).weekday() < 5)
        weekend = 31 - weekdays
        assert t["absent_days"] == weekdays
        assert t["off_days"] == weekend
        assert t["worked_days"] == 0


# --- 2. Custom hours ---------------------------------------------------------


class TestScheduleCustomHours:
    def test_lateness_uses_custom_start(self, client, session, device, shifts):
        """Custom 09:00 start; a 09:20 punch is 20 min late (tier 2). With a
        NORMAL 08:00 shift it would have been 80 min (severe) — proving the
        per-employee start time is what's used."""
        _emp(session, "T2", "Tech2", role="technician")
        _schedule(session, "T2", date_type(2026, 5, 1), role="technician",
                  work_days="0,1,2,3,4,5,6", work_start=time(9, 0), work_end=time(18, 0))
        _punch(session, "T2", device.id, datetime(2026, 5, 4, 9, 20, tzinfo=BANGKOK_TZ))
        _punch(session, "T2", device.id, datetime(2026, 5, 4, 18, 0, tzinfo=BANGKOK_TZ))

        body = client.get(_path(2026, 5)).json()
        day = _emp_row(body, "T2")["days"][3]  # May 4
        assert day["status"] == "present"
        assert day["shift"]["start_time"] == "09:00"
        assert day["late_minutes"] == 20
        assert day["late_tier"] == 2
        assert day["hours_worked"] == 8.67  # 09:20 -> 18:00


# --- 3. Effective-dated role change -----------------------------------------


class TestScheduleHistory:
    def test_mid_month_role_change_is_date_aware(self, client, session, device, shifts):
        """Technician until Jun 15, reception from Jun 15. Before the change a
        no-punch workday is 'absent' (technician, tracked daily); after it,
        a day with no roster assignment is 'off' (reception is roster-driven).
        Same employee, same month — each day uses the version in force then."""
        _emp(session, "M1", "Malee", role="reception")  # current role cache = latest
        _schedule(session, "M1", date_type(2000, 1, 1), role="technician",
                  work_days="0,1,2,3,4,5,6", work_start=time(8, 0), work_end=time(17, 0))
        _schedule(session, "M1", date_type(2026, 6, 15), role="reception")

        body = client.get(_path(2026, 6)).json()
        days = _emp_row(body, "M1")["days"]
        assert days[9]["status"] == "absent"   # Jun 10 — technician, no punch
        assert days[19]["status"] == "off"     # Jun 20 — reception, no roster
