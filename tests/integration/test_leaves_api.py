"""
Integration tests for /api/private/leaves/* (public holidays + employee leaves)
and /api/private/shifts/{code}/color.

Same isolated-engine fixture pattern as test_shifts_api.py.
"""
from datetime import date as date_type, time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main_unified import app
from app.models.models import Employee, EmployeeLeave, LeaveType, PublicHoliday, Shift
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest
from app.services import staff_leave, staff_leave_roster


LEAVES_ROOT = "/api/private/leaves"
SHIFTS_ROOT = "/api/private/shifts"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def leaves_engine():
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
def leaves_session(leaves_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=leaves_engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def leaves_client(leaves_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=leaves_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def seeded_shifts(leaves_session):
    """Same 5 shifts as elsewhere, with colors set per code."""
    rows = [
        Shift(code="NORMAL",    letter=None, name_th="ปกติ",  start_time=time(8, 0),  end_time=time(17, 0), color="#e5e7eb"),
        Shift(code="MORNING",   letter="A",  name_th="เช้า",  start_time=time(7, 0),  end_time=time(16, 0), color="#86efac"),
        Shift(code="MID",       letter="C",  name_th="สาย",   start_time=time(11, 0), end_time=time(20, 0), color="#fde68a"),
        Shift(code="AFTERNOON", letter="B",  name_th="บ่าย", start_time=time(13, 0), end_time=time(22, 0), color="#93c5fd"),
        Shift(code="NIGHT",     letter="D",  name_th="ดึก",  start_time=time(22, 0), end_time=time(7, 0),  color="#c4b5fd"),
    ]
    for r in rows:
        leaves_session.add(r)
    leaves_session.commit()
    for r in rows:
        leaves_session.refresh(r)
    return {r.code: r for r in rows}


@pytest.fixture
def seeded_leave_types(leaves_session):
    """Seed the 4 leave-type rows the way migration 20260516_020000 does."""
    rows = [
        LeaveType(code="vacation",       name_th="ลาพักร้อน",        color="#bbf7d0"),
        LeaveType(code="personal",       name_th="ลากิจ",            color="#fdba74"),
        LeaveType(code="sick",           name_th="ลาป่วย",           color="#fbcfe8"),
        LeaveType(code="public_holiday", name_th="วันหยุดนักขัตฤกษ์", color="#fca5a5"),
    ]
    for r in rows:
        leaves_session.add(r)
    leaves_session.commit()
    for r in rows:
        leaves_session.refresh(r)
    return {r.code: r for r in rows}


@pytest.fixture
def seeded_off_shift(leaves_session):
    """OFF pseudo-shift row used by the cell color picker."""
    from datetime import time as _time
    off = Shift(code="OFF", letter="OFF", name_th="หยุด",
                start_time=_time(0, 0), end_time=_time(0, 0),
                color="#e5e7eb")
    leaves_session.add(off)
    leaves_session.commit()
    leaves_session.refresh(off)
    return off


@pytest.fixture
def seeded_employee(leaves_session):
    e = Employee(
        badge_number="EMP01",
        display_name="Test Employee",
        is_active=True,
        is_hidden=False,
    )
    leaves_session.add(e)
    leaves_session.commit()
    leaves_session.refresh(e)
    return e


# ---------------------------------------------------------------------------
# Shift color
# ---------------------------------------------------------------------------


class TestShiftColor:
    def test_color_appears_on_list(self, leaves_client, seeded_shifts):
        resp = leaves_client.get(SHIFTS_ROOT + "/")
        by_code = {r["code"]: r for r in resp.json()}
        assert by_code["MORNING"]["color"] == "#86efac"
        assert by_code["NIGHT"]["color"] == "#c4b5fd"

    def test_patch_updates_color(self, leaves_client, seeded_shifts, leaves_session):
        resp = leaves_client.patch(
            f"{SHIFTS_ROOT}/MORNING/color",
            json={"color": "#ff0000"},
        )
        assert resp.status_code == 200
        assert resp.json()["color"] == "#ff0000"

        leaves_session.expire_all()
        s = leaves_session.query(Shift).filter_by(code="MORNING").first()
        assert s.color == "#ff0000"

    def test_patch_can_clear_color(self, leaves_client, seeded_shifts):
        resp = leaves_client.patch(
            f"{SHIFTS_ROOT}/MORNING/color",
            json={"color": None},
        )
        assert resp.status_code == 200
        assert resp.json()["color"] is None

    def test_patch_rejects_invalid_hex(self, leaves_client, seeded_shifts):
        resp = leaves_client.patch(
            f"{SHIFTS_ROOT}/MORNING/color",
            json={"color": "red"},
        )
        assert resp.status_code == 400

    def test_patch_404_for_unknown_code(self, leaves_client, seeded_shifts):
        resp = leaves_client.patch(
            f"{SHIFTS_ROOT}/UNKNOWN/color",
            json={"color": "#000000"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Public holidays
# ---------------------------------------------------------------------------


class TestPublicHolidays:
    def test_create_and_list_holiday(self, leaves_client):
        resp = leaves_client.post(
            f"{LEAVES_ROOT}/holidays",
            json={"date": "2026-12-05", "name": "วันคล้ายวันเฉลิม"},
        )
        assert resp.status_code == 200
        assert resp.json()["date"] == "2026-12-05"

        listed = leaves_client.get(
            f"{LEAVES_ROOT}/holidays",
            params={"from": "2026-12-01", "to": "2026-12-31"},
        ).json()
        assert len(listed) == 1
        assert listed[0]["name"] == "วันคล้ายวันเฉลิม"

    def test_create_is_idempotent(self, leaves_client, leaves_session):
        leaves_client.post(
            f"{LEAVES_ROOT}/holidays",
            json={"date": "2026-12-05", "name": "Original"},
        )
        leaves_client.post(
            f"{LEAVES_ROOT}/holidays",
            json={"date": "2026-12-05", "name": "Updated"},
        )
        rows = leaves_session.query(PublicHoliday).all()
        assert len(rows) == 1
        assert rows[0].name == "Updated"

    def test_delete_holiday(self, leaves_client, leaves_session):
        leaves_client.post(
            f"{LEAVES_ROOT}/holidays",
            json={"date": "2026-12-05", "name": "Test"},
        )
        resp = leaves_client.delete(f"{LEAVES_ROOT}/holidays/2026-12-05")
        assert resp.status_code == 204
        assert leaves_session.query(PublicHoliday).count() == 0

    def test_delete_is_idempotent(self, leaves_client):
        resp = leaves_client.delete(f"{LEAVES_ROOT}/holidays/2099-01-01")
        assert resp.status_code == 204

    def test_list_400_on_bad_range(self, leaves_client):
        resp = leaves_client.get(
            f"{LEAVES_ROOT}/holidays",
            params={"from": "2026-12-31", "to": "2026-12-01"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Employee leaves
# ---------------------------------------------------------------------------


class TestEmployeeLeaves:
    def test_create_single_date_leave(
        self, leaves_client, seeded_employee, leaves_session
    ):
        resp = leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "vacation",
                "date": "2026-06-15",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["leave_type"] == "vacation"
        assert body[0]["date"] == "2026-06-15"

    def test_create_date_range_expands_to_rows(
        self, leaves_client, seeded_employee, leaves_session
    ):
        resp = leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "vacation",
                "date_from": "2026-06-15",
                "date_to": "2026-06-17",
            },
        )
        assert resp.status_code == 200
        # 3 days inclusive → 3 rows
        assert len(resp.json()) == 3
        dates = sorted(r["date"] for r in resp.json())
        assert dates == ["2026-06-15", "2026-06-16", "2026-06-17"]

    def test_create_is_idempotent_per_day(
        self, leaves_client, seeded_employee, leaves_session
    ):
        leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "vacation",
                "date": "2026-06-15",
            },
        )
        leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "sick",  # different type — overwrite
                "date": "2026-06-15",
            },
        )
        rows = leaves_session.query(EmployeeLeave).all()
        assert len(rows) == 1
        assert rows[0].leave_type == "sick"

    def test_create_rejects_invalid_leave_type(
        self, leaves_client, seeded_employee
    ):
        resp = leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "sabbatical",
                "date": "2026-06-15",
            },
        )
        assert resp.status_code == 400

    def test_create_accepts_public_holiday_as_leave_type(
        self, leaves_client, seeded_employee, leaves_session
    ):
        """As of 2026-05, public_holiday is a valid per-employee leave
        type too (in addition to the company-wide public_holidays
        table). Lets admins mark one employee as off-for-holiday
        without applying it to everyone."""
        resp = leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "public_holiday",
                "date": "2026-12-31",
            },
        )
        assert resp.status_code == 200
        assert resp.json()[0]["leave_type"] == "public_holiday"

    def test_create_404_unknown_employee(self, leaves_client):
        resp = leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "NOSUCH",
                "leave_type": "vacation",
                "date": "2026-06-15",
            },
        )
        assert resp.status_code == 404

    def test_create_rejects_both_date_and_range(
        self, leaves_client, seeded_employee
    ):
        resp = leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "vacation",
                "date": "2026-06-15",
                "date_from": "2026-06-15",
                "date_to": "2026-06-17",
            },
        )
        assert resp.status_code == 400

    def test_list_filters_by_employee(
        self, leaves_client, seeded_employee, leaves_session
    ):
        # Add a second employee + leaves for both
        e2 = Employee(badge_number="EMP02", display_name="Two", is_active=True, is_hidden=False)
        leaves_session.add(e2)
        leaves_session.commit()
        for badge in ("EMP01", "EMP02"):
            leaves_client.post(
                f"{LEAVES_ROOT}/employee",
                json={
                    "employee_badge_number": badge,
                    "leave_type": "vacation",
                    "date": "2026-06-15",
                },
            )

        resp = leaves_client.get(
            f"{LEAVES_ROOT}/employee",
            params={"from": "2026-06-01", "to": "2026-06-30", "badge": "EMP02"},
        )
        assert resp.status_code == 200
        badges = {r["employee_badge_number"] for r in resp.json()}
        assert badges == {"EMP02"}

    def test_delete_leave(
        self, leaves_client, seeded_employee, leaves_session
    ):
        leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "vacation",
                "date": "2026-06-15",
            },
        )
        resp = leaves_client.delete(f"{LEAVES_ROOT}/employee/EMP01/2026-06-15")
        assert resp.status_code == 204
        assert leaves_session.query(EmployeeLeave).count() == 0

    def test_delete_is_idempotent(self, leaves_client, seeded_employee):
        resp = leaves_client.delete(f"{LEAVES_ROOT}/employee/EMP01/2099-01-01")
        assert resp.status_code == 204


class TestLeaveTypeColors:
    """The /leaves/types CRUD: list + PATCH color. Mirrors the shape of
    /shifts color picking so the same debounced UI handler works for
    both."""

    def test_list_returns_seeded_types_with_colors(
        self, leaves_client, seeded_leave_types
    ):
        resp = leaves_client.get(f"{LEAVES_ROOT}/types")
        assert resp.status_code == 200
        body = {r["code"]: r for r in resp.json()}
        assert set(body.keys()) == {"vacation", "personal", "sick", "public_holiday"}
        assert body["vacation"]["color"] == "#bbf7d0"
        assert body["sick"]["name_th"] == "ลาป่วย"

    def test_patch_updates_color(
        self, leaves_client, seeded_leave_types, leaves_session
    ):
        resp = leaves_client.patch(
            f"{LEAVES_ROOT}/types/vacation/color",
            json={"color": "#123456"},
        )
        assert resp.status_code == 200
        assert resp.json()["color"] == "#123456"

        leaves_session.expire_all()
        lt = leaves_session.query(LeaveType).filter_by(code="vacation").first()
        assert lt.color == "#123456"

    def test_patch_can_clear_color(
        self, leaves_client, seeded_leave_types
    ):
        resp = leaves_client.patch(
            f"{LEAVES_ROOT}/types/sick/color",
            json={"color": None},
        )
        assert resp.status_code == 200
        assert resp.json()["color"] is None

    def test_patch_rejects_invalid_hex(
        self, leaves_client, seeded_leave_types
    ):
        resp = leaves_client.patch(
            f"{LEAVES_ROOT}/types/sick/color",
            json={"color": "blue"},
        )
        assert resp.status_code == 400

    def test_patch_404_for_unknown_code(self, leaves_client, seeded_leave_types):
        resp = leaves_client.patch(
            f"{LEAVES_ROOT}/types/sabbatical/color",
            json={"color": "#000000"},
        )
        assert resp.status_code == 404


class TestOffShiftNotAssignable:
    """OFF is a UI pseudo-shift used for color display. Admins should
    use shift_code=null to mark a day off; OFF as a real shift code in
    /assignments PUT is rejected."""

    def test_assignment_rejects_off_code(
        self, leaves_client, seeded_shifts, seeded_off_shift, seeded_employee
    ):
        resp = leaves_client.put(
            "/api/private/shifts/assignments/EMP01/2026-06-15",
            json={"shift_code": "OFF"},
        )
        assert resp.status_code == 400
        assert "OFF" in resp.json()["detail"]

    def test_off_shift_color_can_be_patched(
        self, leaves_client, seeded_shifts, seeded_off_shift
    ):
        """Even though OFF isn't assignable, its color IS editable via
        the existing /shifts/{code}/color endpoint — that's how the
        admin recolors OFF cells on the roster."""
        resp = leaves_client.patch(
            "/api/private/shifts/OFF/color",
            json={"color": "#000000"},
        )
        assert resp.status_code == 200
        assert resp.json()["color"] == "#000000"


# ---------------------------------------------------------------------------
# The roster is the single source of truth for LINE leave surfaces
# (docs/LEAVE_SYNC_SURFACES.md) — deleting/overwriting a roster row here
# feeds back into the linked LINE-filed request in the same transaction.
# ---------------------------------------------------------------------------


class TestRosterIsSourceOfTruthForLineRequests:
    def test_deleting_roster_days_updates_linked_request_and_effective_state(
        self, leaves_client, leaves_session, seeded_employee, monkeypatch,
    ):
        monkeypatch.setattr(staff_leave, "today", lambda: date_type(2026, 6, 20))
        badge = "EMP01"
        start, mid, end = date_type(2026, 6, 15), date_type(2026, 6, 16), date_type(2026, 6, 17)
        request_id = uuid4().hex
        row = StaffLeaveRequest(
            id=request_id, employee_badge_number=badge, employee_name="Test Employee",
            leave_type="vacation", date_from=start, date_to=end,
            status="approved", version=1, reviewed_by=staff_leave.AUTO_REVIEWER,
        )
        leaves_session.add(row)
        leaves_session.commit()
        ref = staff_leave.reference(row)
        for d in (start, mid, end):
            leaves_session.add(EmployeeLeave(
                employee_badge_number=badge, date=d, leave_type="vacation", note=ref,
            ))
            leaves_session.add(StaffLeaveDay(
                employee_badge_number=badge, date=d, request_id=request_id,
            ))
        leaves_session.commit()

        # Remove the middle day: the request is still "approved", but its
        # effective state is now "partial" and re-filing that one date works.
        resp = leaves_client.delete(f"{LEAVES_ROOT}/employee/{badge}/2026-06-16")
        assert resp.status_code == 204

        leaves_session.expire_all()
        refreshed = leaves_session.get(StaffLeaveRequest, request_id)
        assert refreshed.status == "approved"
        assert leaves_session.query(StaffLeaveDay).filter_by(
            request_id=request_id, date=mid
        ).count() == 0
        assert leaves_session.query(StaffLeaveDay).filter_by(request_id=request_id).count() == 2

        effective = staff_leave_roster.effective_state(leaves_session, refreshed)
        assert effective.status == "partial"
        assert effective.dates == (start, end)

        # Remove the two remaining days: the roster itself ends the request.
        leaves_client.delete(f"{LEAVES_ROOT}/employee/{badge}/2026-06-15")
        leaves_client.delete(f"{LEAVES_ROOT}/employee/{badge}/2026-06-17")

        leaves_session.expire_all()
        final = leaves_session.get(StaffLeaveRequest, request_id)
        assert final.status == "cancelled"
        assert final.reviewed_by == staff_leave_roster.ROSTER_ADMIN_REVIEWER
        assert leaves_session.query(StaffLeaveDay).filter_by(request_id=request_id).count() == 0

        # Freed dates: the employee can re-file the exact same range.
        employee = leaves_session.query(Employee).filter_by(badge_number=badge).one()
        refiled = staff_leave.submit(leaves_session, employee, uuid4().hex, "vacation", start, end)
        assert refiled.status == "pending"

    def test_upsert_without_note_preserves_line_reference(
        self, leaves_client, leaves_session, seeded_employee,
    ):
        request_id = uuid4().hex
        ref = f"HF-LV-{request_id.upper()}"
        on_date = date_type(2026, 6, 15)
        leaves_session.add(EmployeeLeave(
            employee_badge_number="EMP01", date=on_date, leave_type="vacation", note=ref,
        ))
        leaves_session.commit()

        resp = leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "vacation",
                "date": on_date.isoformat(),
            },
        )
        assert resp.status_code == 200

        leaves_session.expire_all()
        stored = leaves_session.query(EmployeeLeave).filter_by(
            employee_badge_number="EMP01", date=on_date,
        ).one()
        assert stored.note == ref

    def test_upsert_with_explicit_note_replaces_reference(
        self, leaves_client, leaves_session, seeded_employee,
    ):
        request_id = uuid4().hex
        ref = f"HF-LV-{request_id.upper()}"
        on_date = date_type(2026, 6, 15)
        leaves_session.add(EmployeeLeave(
            employee_badge_number="EMP01", date=on_date, leave_type="vacation", note=ref,
        ))
        leaves_session.commit()

        resp = leaves_client.post(
            f"{LEAVES_ROOT}/employee",
            json={
                "employee_badge_number": "EMP01",
                "leave_type": "vacation",
                "date": on_date.isoformat(),
                "note": "แก้ไขโดยแอดมิน",
            },
        )
        assert resp.status_code == 200

        leaves_session.expire_all()
        stored = leaves_session.query(EmployeeLeave).filter_by(
            employee_badge_number="EMP01", date=on_date,
        ).one()
        assert stored.note == "แก้ไขโดยแอดมิน"
