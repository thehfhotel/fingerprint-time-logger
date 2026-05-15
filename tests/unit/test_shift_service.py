"""
Unit tests for app.services.shift_service.

The two surfaces under test:

  1. ``effective_shift(db, employee, on_date)`` — pins the resolution
     contract: override beats employee.default beats role-default.
     Reception is special: no override == off (not absent).
  2. ``shift_window_for(shift, on_date)`` — pins the math for the punch
     window, including the overnight (22:00–07:00) case where the
     window crosses midnight.
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.models import Employee, Shift, ShiftAssignment
from app.services.shift_service import (
    SHIFT_WINDOW_BUFFER,
    EffectiveShift,
    effective_shift,
    shift_window_for,
)
from app.utils.timezone import BANGKOK_TZ


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture
def db(engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def seeded_shifts(db):
    """Insert the 5 standard shifts and return them keyed by code."""
    rows = [
        Shift(code="NORMAL",    name_th="ปกติ", start_time=time(8, 0),  end_time=time(17, 0)),
        Shift(code="MORNING",   name_th="เช้า", start_time=time(7, 0),  end_time=time(16, 0)),
        Shift(code="MID",       name_th="สาย", start_time=time(11, 0), end_time=time(20, 0)),
        Shift(code="AFTERNOON", name_th="บ่าย", start_time=time(13, 0), end_time=time(22, 0)),
        Shift(code="NIGHT",     name_th="ดึก", start_time=time(22, 0), end_time=time(7, 0)),
    ]
    for r in rows:
        db.add(r)
    db.commit()
    for r in rows:
        db.refresh(r)
    return {r.code: r for r in rows}


def _make_emp(db, badge, *, role=None, default_shift=None):
    e = Employee(
        badge_number=badge,
        display_name=f"พนักงาน {badge}",
        is_active=True,
        role=role,
        default_shift_id=default_shift.id if default_shift else None,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


# --- effective_shift -----------------------------------------------------


class TestEffectiveShiftResolution:
    """Order of precedence: override > employee default > role default > untracked."""

    def test_explicit_override_wins(self, db, seeded_shifts):
        """A ShiftAssignment row beats the employee's default."""
        emp = _make_emp(db, "E1", role="reception", default_shift=seeded_shifts["NORMAL"])
        db.add(ShiftAssignment(
            employee_badge_number="E1",
            date=date(2026, 5, 15),
            shift_id=seeded_shifts["NIGHT"].id,
        ))
        db.commit()

        result = effective_shift(db, emp, date(2026, 5, 15))
        assert result.shift.code == "NIGHT"
        assert result.is_off is False
        assert result.source == "override"

    def test_override_with_null_shift_means_off(self, db, seeded_shifts):
        """shift_id=NULL on an assignment row marks the day as off."""
        emp = _make_emp(db, "E2", role="housekeeping")  # role would normally → MORNING
        db.add(ShiftAssignment(
            employee_badge_number="E2",
            date=date(2026, 5, 15),
            shift_id=None,
        ))
        db.commit()

        result = effective_shift(db, emp, date(2026, 5, 15))
        assert result.shift is None
        assert result.is_off is True
        assert result.source == "override_off"

    def test_employee_default_used_when_no_override(self, db, seeded_shifts):
        emp = _make_emp(db, "E3", role=None, default_shift=seeded_shifts["AFTERNOON"])

        result = effective_shift(db, emp, date(2026, 5, 15))
        assert result.shift.code == "AFTERNOON"
        assert result.is_off is False
        assert result.source == "employee_default"

    def test_housekeeping_role_default_is_morning(self, db, seeded_shifts):
        emp = _make_emp(db, "E4", role="housekeeping")
        result = effective_shift(db, emp, date(2026, 5, 15))
        assert result.shift.code == "MORNING"
        assert result.source == "role_default"

    def test_technician_role_default_is_normal(self, db, seeded_shifts):
        emp = _make_emp(db, "E5", role="technician")
        result = effective_shift(db, emp, date(2026, 5, 15))
        assert result.shift.code == "NORMAL"
        assert result.source == "role_default"

    def test_admin_role_default_is_normal(self, db, seeded_shifts):
        emp = _make_emp(db, "E6", role="admin")
        result = effective_shift(db, emp, date(2026, 5, 15))
        assert result.shift.code == "NORMAL"
        assert result.source == "role_default"

    def test_reception_without_assignment_is_off_not_absent(self, db, seeded_shifts):
        """Reception staff need explicit per-day assignment. No row = off."""
        emp = _make_emp(db, "E7", role="reception")
        result = effective_shift(db, emp, date(2026, 5, 15))
        assert result.shift is None
        assert result.is_off is True
        assert result.source == "override_off"

    def test_no_role_no_default_is_untracked(self, db, seeded_shifts):
        """An existing-prod employee with role=NULL falls through to
        untracked — the by-date page won't surface them."""
        emp = _make_emp(db, "E8", role=None)
        result = effective_shift(db, emp, date(2026, 5, 15))
        assert result.shift is None
        assert result.is_off is False
        assert result.source == "untracked"


# --- shift_window_for ----------------------------------------------------


def _bkk(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=BANGKOK_TZ)


def _utc_naive(dt_bkk):
    return dt_bkk.astimezone(timezone.utc).replace(tzinfo=None)


class TestShiftWindowFor:
    """Window math, including the overnight crossing case."""

    def test_normal_dayshift_window(self, db, seeded_shifts):
        """NORMAL 08:00–17:00 on 2026-05-15 → window 06:00–19:00 Bangkok."""
        w = shift_window_for(seeded_shifts["NORMAL"], date(2026, 5, 15))
        assert w.crosses_midnight is False
        assert w.shift_start_bkk == _bkk(2026, 5, 15, 8, 0)
        assert w.start_utc == _utc_naive(_bkk(2026, 5, 15, 6, 0))  # 08:00 - 2h
        assert w.end_utc == _utc_naive(_bkk(2026, 5, 15, 19, 0))   # 17:00 + 2h

    def test_morning_shift_window(self, db, seeded_shifts):
        """MORNING 07:00–16:00 → window 05:00–18:00 Bangkok."""
        w = shift_window_for(seeded_shifts["MORNING"], date(2026, 5, 15))
        assert w.crosses_midnight is False
        assert w.shift_start_bkk == _bkk(2026, 5, 15, 7, 0)
        assert w.start_utc == _utc_naive(_bkk(2026, 5, 15, 5, 0))
        assert w.end_utc == _utc_naive(_bkk(2026, 5, 15, 18, 0))

    def test_night_shift_crosses_midnight(self, db, seeded_shifts):
        """NIGHT 22:00–07:00 on 2026-05-15 → window 20:00 May-15 to 09:00 May-16."""
        w = shift_window_for(seeded_shifts["NIGHT"], date(2026, 5, 15))
        assert w.crosses_midnight is True
        assert w.shift_start_bkk == _bkk(2026, 5, 15, 22, 0)
        assert w.start_utc == _utc_naive(_bkk(2026, 5, 15, 20, 0))
        assert w.end_utc == _utc_naive(_bkk(2026, 5, 16, 9, 0))  # next day

    def test_buffer_is_two_hours(self):
        """Pin the buffer choice. If anyone changes SHIFT_WINDOW_BUFFER
        they have to update this test, which is a useful trip-wire."""
        assert SHIFT_WINDOW_BUFFER == timedelta(hours=2)
