"""
Unit tests for the schedule-version tier of
``app.services.shift_service.effective_shift``.

These pin the 3-tier precedence introduced with EmployeeSchedule:

  1. Per-day ShiftAssignment override (unchanged legacy behaviour).
  2. The schedule version in force as-of the date (greatest
     effective_from <= on_date): reception → off, explicit
     work_days/hours → schedule or off-day, role-only → role default,
     otherwise untracked.
  3. No schedule version → the legacy fallback path (proven still intact
     by tests/unit/test_shift_service.py + the by-date integration suite).
"""
from datetime import date, time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.models import (
    Employee,
    EmployeeSchedule,
    Shift,
    ShiftAssignment,
)
from app.services.shift_service import effective_shift


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
        Shift(code="NORMAL",    letter=None, name_th="ปกติ", start_time=time(8, 0),  end_time=time(17, 0)),
        Shift(code="MORNING",   letter="A", name_th="เช้า", start_time=time(7, 0),  end_time=time(16, 0)),
        Shift(code="MID",       letter="C", name_th="สาย", start_time=time(11, 0), end_time=time(20, 0)),
        Shift(code="AFTERNOON", letter="B", name_th="บ่าย", start_time=time(13, 0), end_time=time(22, 0)),
        Shift(code="NIGHT",     letter="D", name_th="ดึก", start_time=time(22, 0), end_time=time(7, 0)),
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


def _add_schedule(
    db,
    badge,
    effective_from,
    *,
    role=None,
    work_days=None,
    work_start=None,
    work_end=None,
):
    """Insert one EmployeeSchedule version row."""
    version = EmployeeSchedule(
        employee_badge_number=badge,
        effective_from=effective_from,
        role=role,
        work_days=work_days,
        work_start=work_start,
        work_end=work_end,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


# --- as-of version selection ---------------------------------------------


class TestScheduleAsOfSelection:
    """The applicable version is the latest with effective_from <= date."""

    def test_may_date_resolves_january_version(self, db, seeded_shifts):
        emp = _make_emp(db, "S1", role="technician")
        _add_schedule(
            db, "S1", date(2026, 1, 1), role="technician",
            work_days="0,1,2,3,4", work_start=time(8, 0), work_end=time(17, 0),
        )
        _add_schedule(
            db, "S1", date(2026, 6, 15), role="technician",
            work_days="0,1,2,3,4", work_start=time(7, 0), work_end=time(16, 0),
        )

        # Thursday 2026-05-14 → January version (08:00–17:00 = NORMAL).
        result = effective_shift(db, emp, date(2026, 5, 14))
        assert result.source == "schedule"
        assert result.shift.code == "NORMAL"

    def test_july_date_resolves_june_version(self, db, seeded_shifts):
        emp = _make_emp(db, "S2", role="technician")
        _add_schedule(
            db, "S2", date(2026, 1, 1), role="technician",
            work_days="0,1,2,3,4", work_start=time(8, 0), work_end=time(17, 0),
        )
        _add_schedule(
            db, "S2", date(2026, 6, 15), role="technician",
            work_days="0,1,2,3,4", work_start=time(7, 0), work_end=time(16, 0),
        )

        # Wednesday 2026-07-01 → June version (07:00–16:00 = MORNING).
        result = effective_shift(db, emp, date(2026, 7, 1))
        assert result.source == "schedule"
        assert result.shift.code == "MORNING"


# --- work-day on/off ------------------------------------------------------


class TestScheduleWorkDays:
    """work_days lists the scheduled weekdays; others are off (not absent)."""

    def test_saturday_is_off_day(self, db, seeded_shifts):
        emp = _make_emp(db, "W1", role="technician")
        _add_schedule(
            db, "W1", date(2026, 1, 1), role="technician",
            work_days="0,1,2,3,4", work_start=time(8, 0), work_end=time(17, 0),
        )

        # 2026-06-13 is a Saturday (weekday 5, not in Mon–Fri set).
        result = effective_shift(db, emp, date(2026, 6, 13))
        assert result.is_off is True
        assert result.shift is None
        assert result.source == "schedule_off_day"

    def test_tuesday_is_a_work_day(self, db, seeded_shifts):
        emp = _make_emp(db, "W2", role="technician")
        _add_schedule(
            db, "W2", date(2026, 1, 1), role="technician",
            work_days="0,1,2,3,4", work_start=time(8, 0), work_end=time(17, 0),
        )

        # 2026-06-16 is a Tuesday (weekday 1, in the set).
        result = effective_shift(db, emp, date(2026, 6, 16))
        assert result.is_off is False
        assert result.source == "schedule"
        assert result.shift.code == "NORMAL"


# --- custom vs seeded hours ----------------------------------------------


class TestScheduleHoursMatching:
    """Standard hours reuse the seeded shift; novel hours yield CUSTOM."""

    def test_custom_hours_yield_transient_custom_shift(self, db, seeded_shifts):
        emp = _make_emp(db, "C1", role="technician")
        _add_schedule(
            db, "C1", date(2026, 1, 1), role="technician",
            work_days="0,1,2,3,4", work_start=time(9, 0), work_end=time(18, 0),
        )

        # Tuesday 2026-06-16, 09:00–18:00 matches no seeded shift.
        result = effective_shift(db, emp, date(2026, 6, 16))
        assert result.source == "schedule"
        assert result.shift.code == "CUSTOM"
        assert result.shift.start_time == time(9, 0)
        assert result.shift.end_time == time(18, 0)

    def test_standard_hours_reuse_seeded_normal(self, db, seeded_shifts):
        emp = _make_emp(db, "C2", role="technician")
        _add_schedule(
            db, "C2", date(2026, 1, 1), role="technician",
            work_days="0,1,2,3,4", work_start=time(8, 0), work_end=time(17, 0),
        )

        result = effective_shift(db, emp, date(2026, 6, 16))  # Tuesday
        assert result.shift.code == "NORMAL"
        assert result.shift.name_th == "ปกติ"


# --- reception version ----------------------------------------------------


class TestScheduleReception:
    """Reception versions are roster-driven: off unless a per-day override."""

    def test_reception_version_is_off(self, db, seeded_shifts):
        emp = _make_emp(db, "RC1", role="reception")
        _add_schedule(db, "RC1", date(2026, 1, 1), role="reception")

        result = effective_shift(db, emp, date(2026, 6, 16))
        assert result.is_off is True
        assert result.shift is None
        assert result.source == "schedule_reception_off"

    def test_per_day_override_beats_reception_version(self, db, seeded_shifts):
        emp = _make_emp(db, "RC2", role="reception")
        _add_schedule(db, "RC2", date(2026, 1, 1), role="reception")
        target = date(2026, 6, 16)
        db.add(ShiftAssignment(
            employee_badge_number="RC2",
            date=target,
            shift_id=seeded_shifts["MID"].id,
        ))
        db.commit()

        result = effective_shift(db, emp, target)
        assert result.source == "override"
        assert result.shift.code == "MID"
        assert result.is_off is False


# --- role-only / untracked versions --------------------------------------


class TestScheduleUntracked:
    """A version with no role and no hours is untracked."""

    def test_role_none_no_hours_is_untracked(self, db, seeded_shifts):
        emp = _make_emp(db, "U1", role=None)
        _add_schedule(db, "U1", date(2026, 1, 1), role=None)

        result = effective_shift(db, emp, date(2026, 6, 16))
        assert result.shift is None
        assert result.is_off is False
        assert result.source == "untracked"


# --- legacy fallback (no schedule rows) ----------------------------------


class TestLegacyFallbackWithoutSchedule:
    """Employees with no EmployeeSchedule rows resolve via the legacy path."""

    def test_technician_without_schedule_uses_role_default(self, db, seeded_shifts):
        emp = _make_emp(db, "L1", role="technician")  # no schedule rows

        result = effective_shift(db, emp, date(2026, 6, 16))
        assert result.source == "role_default"
        assert result.shift.code == "NORMAL"
        assert result.is_off is False
