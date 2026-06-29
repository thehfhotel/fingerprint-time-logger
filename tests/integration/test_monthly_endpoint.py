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

from app.api.consolidated_attendance import _build_month_day
from app.core.database import Base, get_db
from app.main_unified import app
from app.models.models import (
    AttendanceRecord, Device, Employee, EmployeeLeave, PublicHoliday,
    Shift, ShiftAssignment,
)
from app.services.shift_service import EffectiveShift
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


class TestMonthlyMissingCheckout:
    """A single punch is a check-in with a missing check-out: the report
    assumes the employee worked to the shift's scheduled end time. Hours run
    from the punch to that end, and lateness is read from the punch normally.
    No 'incomplete' flag/category exists."""

    def test_single_punch_assumes_checkout_at_shift_end(
        self, monthly_client, monthly_session, seed_device, seeded_shifts
    ):
        _make_employee(monthly_session, "IC1", "OnePunch", role="reception", location="HF")
        _assign(monthly_session, "IC1", date_type(2026, 5, 1), seeded_shifts["NORMAL"])
        # ONE punch at 08:45 — check-in; check-out assumed at 17:00 (NORMAL end).
        _add_punch(monthly_session, "IC1", seed_device.id,
                   datetime(2026, 5, 1, 8, 45, tzinfo=BANGKOK_TZ))

        body = monthly_client.get(_path(2026, 5)).json()
        emp = _emp(body, "IC1")
        day = emp["days"][0]
        assert day["status"] == "present"
        assert day["first_in"] == "08:45"
        assert day["last_out"] == "17:00"      # assumed shift end
        assert day["check_in_assumed"] is False   # real punch
        assert day["check_out_assumed"] is True    # assumed from schedule
        assert day["hours_worked"] == 8.25     # 08:45 -> 17:00
        assert day["late_minutes"] == 45
        assert day["late_tier"] == 3
        assert "incomplete" not in day

        t = emp["totals"]
        assert t["worked_days"] == 1
        assert t["late_count"] == 1
        assert t["severe_count"] == 1
        assert t["hours_total"] == 8.25
        assert "incomplete_days" not in t

    def test_single_punch_overnight_assumes_next_morning_end(
        self, monthly_client, monthly_session, seed_device, seeded_shifts
    ):
        """NIGHT 22:00–07:00: a lone 22:30 punch assumes a 07:00-next-day
        check-out (the overnight end), so hours span midnight correctly."""
        _make_employee(monthly_session, "IC2", "NightOne", role="reception", location="HF")
        _assign(monthly_session, "IC2", date_type(2026, 5, 1), seeded_shifts["NIGHT"])
        _add_punch(monthly_session, "IC2", seed_device.id,
                   datetime(2026, 5, 1, 22, 30, tzinfo=BANGKOK_TZ))

        body = monthly_client.get(_path(2026, 5)).json()
        day = _emp(body, "IC2")["days"][0]
        assert day["status"] == "present"
        assert day["last_out"] == "07:00"      # next-morning shift end
        assert day["hours_worked"] == 8.5      # 22:30 -> 07:00 (+1 day)
        assert day["late_minutes"] == 30

    def test_lone_checkout_explicit_type_assumes_checkin_at_start(
        self, monthly_client, monthly_session, seed_device, seeded_shifts
    ):
        """MORNING 07:00–16:00, one punch at 16:01 explicitly typed as a
        check-out (punch_type=1): check-in assumed at the shift start, NOT
        read as a ~9h-late arrival."""
        _make_employee(monthly_session, "CO1", "CheckoutOnly", role="reception", location="HF")
        _assign(monthly_session, "CO1", date_type(2026, 5, 1), seeded_shifts["MORNING"])
        _add_punch(monthly_session, "CO1", seed_device.id,
                   datetime(2026, 5, 1, 16, 1, tzinfo=BANGKOK_TZ), punch_type=1)

        day = _emp(monthly_client.get(_path(2026, 5)).json(), "CO1")["days"][0]
        assert day["status"] == "present"
        assert day["first_in"] == "07:00"      # assumed shift start
        assert day["last_out"] == "16:01"
        assert day["check_in_assumed"] is True     # assumed from schedule
        assert day["check_out_assumed"] is False   # real punch
        assert day["hours_worked"] == 9.02     # 07:00 -> 16:01
        assert day["late_minutes"] == 0
        assert day["late_tier"] == 0

    def test_lone_checkout_inferred_by_position(
        self, monthly_client, monthly_session, seed_device, seeded_shifts
    ):
        """NIGHT 22:00–07:00, one UNSPECIFIED punch (type 255) at 07:07 the
        next morning is inferred as a check-out by position (second half of
        the shift) → check-in assumed at 22:00, not a 547-min-late arrival."""
        _make_employee(monthly_session, "CO2", "NightCheckout", role="reception", location="HF")
        _assign(monthly_session, "CO2", date_type(2026, 5, 1), seeded_shifts["NIGHT"])
        _add_punch(monthly_session, "CO2", seed_device.id,
                   datetime(2026, 5, 2, 7, 7, tzinfo=BANGKOK_TZ), punch_type=255)

        day = _emp(monthly_client.get(_path(2026, 5)).json(), "CO2")["days"][0]
        assert day["status"] == "present"
        assert day["first_in"] == "22:00"      # assumed shift start
        assert day["last_out"] == "07:07"
        assert day["hours_worked"] == 9.12     # 22:00 -> 07:07 (+1 day)
        assert day["late_minutes"] == 0

    def test_multiple_checkout_logs_use_latest(
        self, monthly_client, monthly_session, seed_device, seeded_shifts
    ):
        """Several check-out punches and no check-in: take the latest as the
        check-out, assume the check-in at the shift start."""
        _make_employee(monthly_session, "CO3", "ManyOut", role="reception", location="HF")
        _assign(monthly_session, "CO3", date_type(2026, 5, 1), seeded_shifts["MORNING"])
        for h, m in [(16, 1), (16, 5)]:
            _add_punch(monthly_session, "CO3", seed_device.id,
                       datetime(2026, 5, 1, h, m, tzinfo=BANGKOK_TZ), punch_type=1)

        day = _emp(monthly_client.get(_path(2026, 5)).json(), "CO3")["days"][0]
        assert day["first_in"] == "07:00"
        assert day["last_out"] == "16:05"      # latest check-out
        assert day["hours_worked"] == 9.08     # 07:00 -> 16:05
        assert day["late_minutes"] == 0

    def test_punch_type_breaks_tie_near_midshift(
        self, monthly_client, monthly_session, seed_device, seeded_shifts
    ):
        """Near the shift midpoint (ambiguous), an explicit punch_type wins:
        an 08:00 check-in + a 12:15 punch typed check-out (within ±60 min of
        the 12:30 midpoint) is an early check-out, not assumed-to-end."""
        _make_employee(monthly_session, "MT1", "MidTie", role="reception", location="HF")
        _assign(monthly_session, "MT1", date_type(2026, 5, 1), seeded_shifts["NORMAL"])
        _add_punch(monthly_session, "MT1", seed_device.id,
                   datetime(2026, 5, 1, 8, 0, tzinfo=BANGKOK_TZ), punch_type=0)
        _add_punch(monthly_session, "MT1", seed_device.id,
                   datetime(2026, 5, 1, 12, 15, tzinfo=BANGKOK_TZ), punch_type=1)

        day = _emp(monthly_client.get(_path(2026, 5)).json(), "MT1")["days"][0]
        assert day["first_in"] == "08:00"
        assert day["last_out"] == "12:15"      # explicit early check-out honored
        assert day["check_in_assumed"] is False    # both punches are real
        assert day["check_out_assumed"] is False
        assert day["hours_worked"] == 4.25
        assert day["late_minutes"] == 0


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

    def test_holiday_does_not_apply_to_reception(self, monthly_client, monthly_session,
                                                 seed_device, seeded_shifts):
        """Hotels run on holidays — a company-wide public holiday marks
        non-reception staff off, but reception follows its roster."""
        monthly_session.add(PublicHoliday(date=date_type(2026, 5, 5), name="วันหยุด"))
        monthly_session.commit()
        # reception assigned + punched on the holiday → present (works it)
        _make_employee(monthly_session, "RH1", "RecepWorks", role="reception", location="HF")
        _assign(monthly_session, "RH1", date_type(2026, 5, 5), seeded_shifts["NORMAL"])
        _add_punch(monthly_session, "RH1", seed_device.id,
                   datetime(2026, 5, 5, 8, 0, tzinfo=BANGKOK_TZ))
        # reception with no roster assignment → off (normal off, not holiday)
        _make_employee(monthly_session, "RH2", "RecepOff", role="reception", location="HF")
        # non-reception → off for the public holiday
        _make_employee(monthly_session, "TH1", "TechHoliday", role="technician")

        body = monthly_client.get(_path(2026, 5)).json()
        rh1 = _emp(body, "RH1")["days"][4]
        assert rh1["status"] == "present"
        assert rh1["leave_type"] is None
        rh2 = _emp(body, "RH2")["days"][4]
        assert rh2["status"] == "off"
        assert rh2["leave_type"] is None          # scheduled off, not a holiday
        th1 = _emp(body, "TH1")["days"][4]
        assert th1["status"] == "off"
        assert th1["leave_type"] == "public_holiday"


class TestMonthlyFutureDays:
    """Upcoming days (after today) carry no attendance result — status
    'future', blank, and excluded from totals."""

    def test_future_days_blank_in_current_month(
        self, monthly_client, monthly_session, seed_device, seeded_shifts
    ):
        today = datetime.now(BANGKOK_TZ).date()
        _make_employee(monthly_session, "FU1", "FutureGuy", role="technician")
        # Tracked every calendar day (legacy role default), no punches → past
        # days are 'absent', future days must be 'future' (blank).
        body = monthly_client.get(_path(today.year, today.month)).json()
        emp = _emp(body, "FU1")
        for d in emp["days"]:
            dd = date_type.fromisoformat(d["date"])
            if dd > today:
                assert d["status"] == "future", d
                assert d["first_in"] is None and d["hours_worked"] is None
            else:
                assert d["status"] != "future", d
        # Past no-punch days are 'absent'; today may be 'pending' (shift not
        # started yet) rather than 'absent'. Totals match the per-day statuses,
        # and no future day ever counts as absent.
        absent_in_days = sum(1 for d in emp["days"] if d["status"] == "absent")
        assert emp["totals"]["absent_days"] == absent_in_days
        assert all(
            d["status"] != "absent"
            for d in emp["days"]
            if date_type.fromisoformat(d["date"]) > today
        )
        today_row = next(
            d for d in emp["days"] if date_type.fromisoformat(d["date"]) == today
        )
        assert today_row["status"] in ("absent", "pending")


class TestMonthlyPending:
    """A scheduled shift on TODAY whose start time hasn't arrived yet is
    'pending' (รอเริ่มงาน), not 'absent'. Driven directly on _build_month_day
    with a controlled `now_bkk` so the assertions don't depend on wall-clock."""

    @staticmethod
    def _eff(shift):
        return EffectiveShift(shift=shift, is_off=False, source="role_default", role="reception")

    @staticmethod
    def _row(shift, day, today, now):
        return _build_month_day(
            None, day, TestMonthlyPending._eff(shift), [],
            today=today, now_bkk=now, holiday=None, leave=None,
        )

    def test_today_before_shift_start_is_pending(self, seeded_shifts):
        day = date_type(2026, 6, 15)
        row = self._row(seeded_shifts["NORMAL"], day, day,  # 08:00–17:00
                        datetime(2026, 6, 15, 6, 30, tzinfo=BANGKOK_TZ))
        assert row["status"] == "pending"
        assert row["first_in"] is None and row["last_out"] is None
        assert row["hours_worked"] is None

    def test_today_after_shift_start_no_punch_is_absent(self, seeded_shifts):
        day = date_type(2026, 6, 15)
        row = self._row(seeded_shifts["NORMAL"], day, day,
                        datetime(2026, 6, 15, 9, 0, tzinfo=BANGKOK_TZ))
        assert row["status"] == "absent"

    def test_past_day_is_absent_regardless_of_clock(self, seeded_shifts):
        # A past day is never pending, even when the wall-clock time-of-day is
        # earlier than the shift start.
        row = self._row(seeded_shifts["NORMAL"], date_type(2026, 6, 14),
                        date_type(2026, 6, 15),
                        datetime(2026, 6, 15, 6, 30, tzinfo=BANGKOK_TZ))
        assert row["status"] == "absent"

    def test_overnight_shift_before_start_is_pending(self, seeded_shifts):
        day = date_type(2026, 6, 15)
        row = self._row(seeded_shifts["NIGHT"], day, day,  # 22:00–07:00+1
                        datetime(2026, 6, 15, 14, 0, tzinfo=BANGKOK_TZ))
        assert row["status"] == "pending"


class TestMonthlyInProgressCheckout:
    """Checked in but the shift hasn't ended yet: don't fabricate a check-out
    at the scheduled end — leave it blank (unknown) until the shift is over.
    Driven directly on _build_month_day with a controlled `now_bkk`."""

    @staticmethod
    def _row(shift, day, now, punch_bkk):
        eff = EffectiveShift(shift=shift, is_off=False, source="role_default", role="reception")
        punches = [(_bangkok_to_utc_naive(punch_bkk), 0)]
        return _build_month_day(
            None, day, eff, punches,
            today=day, now_bkk=now, holiday=None, leave=None,
        )

    def test_in_progress_leaves_checkout_blank(self, seeded_shifts):
        day = date_type(2026, 6, 15)
        row = self._row(
            seeded_shifts["MORNING"], day,                      # 07:00–16:00
            datetime(2026, 6, 15, 14, 0, tzinfo=BANGKOK_TZ),    # now: before 16:00
            datetime(2026, 6, 15, 6, 50, tzinfo=BANGKOK_TZ),    # checked in early
        )
        assert row["status"] == "present"
        assert row["first_in"] == "06:50"
        assert row["last_out"] is None              # NOT assumed — still on shift
        assert row["check_out_assumed"] is False
        assert row["hours_worked"] is None

    def test_after_shift_end_assumes_checkout(self, seeded_shifts):
        day = date_type(2026, 6, 15)
        row = self._row(
            seeded_shifts["MORNING"], day,
            datetime(2026, 6, 15, 18, 0, tzinfo=BANGKOK_TZ),    # now: after 16:00
            datetime(2026, 6, 15, 6, 50, tzinfo=BANGKOK_TZ),
        )
        assert row["status"] == "present"
        assert row["last_out"] == "16:00"           # assumed scheduled end
        assert row["check_out_assumed"] is True
        assert row["hours_worked"] is not None


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
