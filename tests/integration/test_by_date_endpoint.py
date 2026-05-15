"""
Integration tests for GET /api/private/attendance/by-date.

Endpoint contract (post 2026-05 shift-aware rewrite):
  - Path: /api/private/attendance/by-date
  - Query: date=YYYY-MM-DD (Bangkok-local, defaults to today)
  - Response: { date, rows: [...] }
  - One row per ACTIVE, TRACKED employee. "Tracked" = has an effective
    shift for the requested date (per-day override > employee default >
    role default). Employees with no role and no default shift are
    omitted entirely.
  - status enum:
      "late"    — first punch inside the shift window is after shift_start
      "on_time" — first punch at/before shift_start
      "absent"  — effective shift exists, no punches in the window
      "off"     — employee is scheduled off today (explicit override
                  with shift_id=NULL, or reception with no assignment)

These tests hit the ROOT app (where /api/private/* is mounted) using a
fresh TestClient + dependency override pattern.
"""

from datetime import datetime, date as date_type, time, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main_unified import app
from app.models.models import AttendanceRecord, Device, Employee, Shift, ShiftAssignment
from app.utils.timezone import BANGKOK_TZ


BY_DATE_PATH = "/api/private/attendance/by-date"


# ---------------------------------------------------------------------------
# Fixtures
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
    """TestClient for the ROOT app with a get_db override.

    Skipping the lifespan (no ``with`` block) keeps the APScheduler /
    zk_session daemons from booting and leaking event loops between tests.
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


@pytest.fixture
def seeded_shifts(by_date_session):
    """Insert the 5 standard shifts in the test DB."""
    rows = [
        Shift(code="NORMAL",    letter=None, name_th="ปกติ", start_time=time(8, 0),  end_time=time(17, 0)),
        Shift(code="MORNING",   letter="A", name_th="เช้า", start_time=time(7, 0),  end_time=time(16, 0)),
        Shift(code="MID",       letter="C", name_th="สาย", start_time=time(11, 0), end_time=time(20, 0)),
        Shift(code="AFTERNOON", letter="B", name_th="บ่าย", start_time=time(13, 0), end_time=time(22, 0)),
        Shift(code="NIGHT",     letter="D", name_th="ดึก", start_time=time(22, 0), end_time=time(7, 0)),
    ]
    for r in rows:
        by_date_session.add(r)
    by_date_session.commit()
    for r in rows:
        by_date_session.refresh(r)
    return {r.code: r for r in rows}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_employee(
    session,
    badge,
    display_name,
    *,
    is_active=True,
    role=None,
    default_shift=None,
    location=None,
):
    """Create an Employee with optional role + default_shift + location."""
    e = Employee(
        badge_number=badge,
        english_name=None,
        thai_name=None,
        display_name=display_name,
        is_active=is_active,
        is_hidden=False,
        role=role,
        default_shift_id=default_shift.id if default_shift else None,
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


def _assign(session, badge, on_date, shift=None):
    """Create a ShiftAssignment row. shift=None means scheduled off."""
    a = ShiftAssignment(
        employee_badge_number=badge,
        date=on_date,
        shift_id=shift.id if shift else None,
    )
    session.add(a)
    session.commit()
    return a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestByDateUntrackedEmployees:
    """Employees with no role and no default shift never surface."""

    def test_employee_with_no_role_and_no_default_is_omitted(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """role=NULL + default_shift_id=NULL → row not emitted, even if
        the employee has punches that day. Pins the "untracked" contract
        so accidentally enabling tracking is a visible diff."""
        _make_employee(by_date_session, "U001", "Untracked")
        target = date_type(2026, 5, 14)
        _add_punch(
            by_date_session, "U001", seed_device.id,
            datetime(2026, 5, 14, 8, 0, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        assert resp.status_code == 200
        assert resp.json()["rows"] == []

    def test_empty_db_returns_zero_rows(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["date"] == "2026-05-14"
        assert body["rows"] == []


class TestByDateDayShiftStatuses:
    """on_time / late / absent for a regular dayshift employee."""

    def test_on_time_when_first_punch_before_shift_start(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """Technician's role default is NORMAL (08:00). Punch at 08:52
        is still inside the [06:00, 19:00] window — wait, 08:52 > 08:00
        so this should be LATE actually. Let me use 07:55 for on_time.
        """
        _make_employee(
            by_date_session, "T001", "TechOnTime", role="technician",
        )
        target = date_type(2026, 5, 14)
        _add_punch(
            by_date_session, "T001", seed_device.id,
            datetime(2026, 5, 14, 7, 55, tzinfo=BANGKOK_TZ),  # 5 min early
        )
        _add_punch(
            by_date_session, "T001", seed_device.id,
            datetime(2026, 5, 14, 17, 10, tzinfo=BANGKOK_TZ),  # 10 min after end
        )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        assert resp.status_code == 200
        row = resp.json()["rows"][0]
        assert row["status"] == "on_time"
        assert row["first_in"] == "07:55"
        assert row["last_out"] == "17:10"
        assert row["role"] == "technician"
        assert row["shift"]["code"] == "NORMAL"

    def test_late_when_first_punch_after_shift_start(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        _make_employee(by_date_session, "T002", "TechLate", role="technician")
        target = date_type(2026, 5, 14)
        _add_punch(
            by_date_session, "T002", seed_device.id,
            datetime(2026, 5, 14, 9, 15, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        row = resp.json()["rows"][0]
        assert row["status"] == "late"
        assert row["first_in"] == "09:15"

    def test_absent_when_no_punches_in_window(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """Tracked employee, no punches → absent (with role assigned).

        Was the dropped pre-2026-05 behavior; restored alongside shifts.
        """
        _make_employee(by_date_session, "T003", "TechMissing", role="technician")
        target = date_type(2026, 5, 14)

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        rows = resp.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["status"] == "absent"
        assert rows[0]["first_in"] is None

    def test_housekeeping_uses_morning_shift(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """แม่บ้าน work hours are 07:00–16:00 — 06:55 punch is on_time."""
        _make_employee(by_date_session, "H001", "Cleaner", role="housekeeping")
        target = date_type(2026, 5, 14)
        _add_punch(
            by_date_session, "H001", seed_device.id,
            datetime(2026, 5, 14, 6, 55, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        row = resp.json()["rows"][0]
        assert row["shift"]["code"] == "MORNING"
        assert row["status"] == "on_time"


class TestByDateReception:
    """Reception requires per-day assignment; no override = off, not absent."""

    def test_reception_without_assignment_is_off(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        _make_employee(by_date_session, "R001", "Receptionist", role="reception")
        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        rows = resp.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["status"] == "off"
        assert rows[0]["shift"] is None
        assert rows[0]["first_in"] is None

    def test_reception_with_mid_shift_override(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        _make_employee(by_date_session, "R002", "MidShiftReception", role="reception")
        target = date_type(2026, 5, 14)
        _assign(by_date_session, "R002", target, seeded_shifts["MID"])
        # 11:00 shift, punches at 11:00 sharp
        _add_punch(
            by_date_session, "R002", seed_device.id,
            datetime(2026, 5, 14, 11, 0, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        row = resp.json()["rows"][0]
        assert row["shift"]["code"] == "MID"
        assert row["status"] == "on_time"

    def test_explicit_off_override_for_non_reception(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """Even a housekeeper can have a day off via shift_id=NULL override."""
        _make_employee(by_date_session, "H002", "TodayOff", role="housekeeping")
        target = date_type(2026, 5, 14)
        _assign(by_date_session, "H002", target, shift=None)  # explicit off

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        rows = resp.json()["rows"]
        assert rows[0]["status"] == "off"


class TestByDateOvernightShift:
    """NIGHT 22:00–07:00 crosses midnight. Pin the window math end-to-end."""

    def test_night_worker_on_time(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """Reception assigned NIGHT on May 14. Punch in 21:55 on May 14
        and out 07:30 on May 15 → on_time for May 14, both punches
        attributed to the same shift."""
        _make_employee(by_date_session, "N001", "NightOwl", role="reception")
        _assign(by_date_session, "N001", date_type(2026, 5, 14), seeded_shifts["NIGHT"])

        _add_punch(
            by_date_session, "N001", seed_device.id,
            datetime(2026, 5, 14, 21, 55, tzinfo=BANGKOK_TZ),
        )
        _add_punch(
            by_date_session, "N001", seed_device.id,
            datetime(2026, 5, 15, 7, 30, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        rows = resp.json()["rows"]
        assert len(rows) == 1
        row = rows[0]
        assert row["shift"]["code"] == "NIGHT"
        assert row["shift"]["crosses_midnight"] is True
        assert row["status"] == "on_time"
        assert row["first_in"] == "21:55"
        assert row["last_out"] == "07:30"

    def test_night_worker_late(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        _make_employee(by_date_session, "N002", "NightLate", role="reception")
        _assign(by_date_session, "N002", date_type(2026, 5, 14), seeded_shifts["NIGHT"])
        _add_punch(
            by_date_session, "N002", seed_device.id,
            datetime(2026, 5, 14, 22, 30, tzinfo=BANGKOK_TZ),  # 30 min after 22:00
        )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        row = resp.json()["rows"][0]
        assert row["status"] == "late"

    def test_night_worker_absent(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """NIGHT assigned but no punches in [20:00 May14, 09:00 May15] → absent."""
        _make_employee(by_date_session, "N003", "NightMissing", role="reception")
        _assign(by_date_session, "N003", date_type(2026, 5, 14), seeded_shifts["NIGHT"])

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        rows = resp.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["status"] == "absent"

    def test_night_worker_next_day_punch_not_attributed_to_next_day(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """The 07:00-on-May-15 punch from May-14 NIGHT shift must not
        surface on the May-15 /by-date page unless the employee is
        also tracked on May 15. Reception without a May-15 assignment
        is OFF on May 15, so they shouldn't be flagged absent there."""
        _make_employee(by_date_session, "N004", "NightNoNext", role="reception")
        _assign(by_date_session, "N004", date_type(2026, 5, 14), seeded_shifts["NIGHT"])
        # No May-15 assignment → off on May 15
        _add_punch(
            by_date_session, "N004", seed_device.id,
            datetime(2026, 5, 14, 22, 0, tzinfo=BANGKOK_TZ),
        )
        _add_punch(
            by_date_session, "N004", seed_device.id,
            datetime(2026, 5, 15, 7, 0, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        # May 14: on_time with the night shift
        r14 = client.get(BY_DATE_PATH, params={"date": "2026-05-14"}).json()["rows"]
        assert r14[0]["status"] == "on_time"

        # May 15: off, not absent (reception with no assignment).
        # The 07:00 punch belongs to May-14's shift, NOT May-15.
        r15 = client.get(BY_DATE_PATH, params={"date": "2026-05-15"}).json()["rows"]
        assert r15[0]["status"] == "off"


class TestByDateMisc:
    """Miscellaneous contract checks."""

    def test_inactive_employees_excluded(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        _make_employee(by_date_session, "A001", "Alice", role="technician")
        _make_employee(
            by_date_session, "A002", "Bob",
            role="technician", is_active=False,
        )
        for badge in ("A001", "A002"):
            _add_punch(
                by_date_session, badge, seed_device.id,
                datetime(2026, 5, 14, 8, 0, tzinfo=BANGKOK_TZ),
            )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        badges = [r["badge_number"] for r in resp.json()["rows"]]
        assert badges == ["A001"]

    def test_invalid_date_format_returns_400(self, by_date_client):
        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "not-a-date"})
        assert resp.status_code == 400
        assert "YYYY-MM-DD" in resp.json()["detail"]

    def test_date_defaults_to_today_bangkok(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        _make_employee(by_date_session, "D001", "Today", role="technician")
        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH)
        today = datetime.now(BANGKOK_TZ).date().isoformat()
        assert resp.json()["date"] == today

    def test_sort_order(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """late > absent > on_time > off, then alphabetic within."""
        target = date_type(2026, 5, 14)

        # late
        _make_employee(by_date_session, "S1", "Bravo", role="technician")
        _add_punch(
            by_date_session, "S1", seed_device.id,
            datetime(2026, 5, 14, 10, 0, tzinfo=BANGKOK_TZ),
        )

        # absent (tracked but no punches)
        _make_employee(by_date_session, "S2", "Delta", role="technician")

        # on_time
        _make_employee(by_date_session, "S3", "Alpha", role="technician")
        _add_punch(
            by_date_session, "S3", seed_device.id,
            datetime(2026, 5, 14, 7, 45, tzinfo=BANGKOK_TZ),
        )

        # off (explicit override)
        _make_employee(by_date_session, "S4", "Charlie", role="technician")
        _assign(by_date_session, "S4", target, shift=None)

        # second on_time for alphabetic tie-break
        _make_employee(by_date_session, "S5", "Echo", role="technician")
        _add_punch(
            by_date_session, "S5", seed_device.id,
            datetime(2026, 5, 14, 7, 50, tzinfo=BANGKOK_TZ),
        )

        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": target.isoformat()})
        rows = resp.json()["rows"]
        statuses = [r["status"] for r in rows]
        names = [r["display_name"] for r in rows]

        assert statuses == ["late", "absent", "on_time", "on_time", "off"]
        # Within on_time: Alpha < Echo
        assert names[2:4] == ["Alpha", "Echo"]

    def test_single_punch_yields_null_hours_worked(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        _make_employee(by_date_session, "P001", "OnlyOnce", role="technician")
        _add_punch(
            by_date_session, "P001", seed_device.id,
            datetime(2026, 5, 14, 8, 0, tzinfo=BANGKOK_TZ),
        )
        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        row = resp.json()["rows"][0]
        assert row["first_in"] == "08:00"
        assert row["last_out"] == "08:00"
        assert row["hours_worked"] is None

    def test_previous_day_punch_excluded(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        """A May 13 23:55 punch belongs to May-13's NORMAL shift window
        ([06:00, 19:00 May-13]) — it's outside, so it doesn't show anywhere.
        A May 14 08:45 punch is the first_in for May 14."""
        _make_employee(by_date_session, "B001", "Boundary", role="technician")
        _add_punch(
            by_date_session, "B001", seed_device.id,
            datetime(2026, 5, 13, 23, 55, tzinfo=BANGKOK_TZ),
        )
        _add_punch(
            by_date_session, "B001", seed_device.id,
            datetime(2026, 5, 14, 8, 45, tzinfo=BANGKOK_TZ),
        )
        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        row = resp.json()["rows"][0]
        assert row["first_in"] == "08:45"


class TestByDateLocationFilter:
    """?location=HF|HF_VILLE restricts rows to that branch's employees.

    Employees with location=NULL are only included when the caller
    omits the filter — once HF or HF_VILLE is specified, only matching
    employees come back. Each row also carries `location` so the UI can
    show the branch label.
    """

    def _seed_two_branches(self, session, seed_device):
        _make_employee(
            session, "HF1", "HFTech",
            role="technician", location="HF",
        )
        _make_employee(
            session, "HV1", "HFVilleTech",
            role="technician", location="HF_VILLE",
        )
        _make_employee(
            session, "NX1", "NoLocation",
            role="technician",  # location stays NULL
        )
        for badge in ("HF1", "HV1", "NX1"):
            _add_punch(
                session, badge, seed_device.id,
                datetime(2026, 5, 14, 8, 0, tzinfo=BANGKOK_TZ),
            )

    def test_no_filter_returns_all_locations(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        self._seed_two_branches(by_date_session, seed_device)
        client, _ = by_date_client
        resp = client.get(BY_DATE_PATH, params={"date": "2026-05-14"})
        badges = {r["badge_number"] for r in resp.json()["rows"]}
        assert badges == {"HF1", "HV1", "NX1"}

    def test_filter_hf_returns_only_hf(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        self._seed_two_branches(by_date_session, seed_device)
        client, _ = by_date_client
        resp = client.get(
            BY_DATE_PATH, params={"date": "2026-05-14", "location": "HF"}
        )
        rows = resp.json()["rows"]
        assert [r["badge_number"] for r in rows] == ["HF1"]
        assert rows[0]["location"] == "HF"

    def test_filter_hf_ville_returns_only_villa(
        self, by_date_client, by_date_session, seed_device, seeded_shifts
    ):
        self._seed_two_branches(by_date_session, seed_device)
        client, _ = by_date_client
        resp = client.get(
            BY_DATE_PATH, params={"date": "2026-05-14", "location": "HF_VILLE"}
        )
        badges = [r["badge_number"] for r in resp.json()["rows"]]
        assert badges == ["HV1"]

    def test_invalid_location_returns_400(self, by_date_client):
        client, _ = by_date_client
        resp = client.get(
            BY_DATE_PATH,
            params={"date": "2026-05-14", "location": "MARS"},
        )
        assert resp.status_code == 400
        assert "location" in resp.json()["detail"]
