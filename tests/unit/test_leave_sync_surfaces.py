from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import leaves as leaves_api
from app.core.database import Base
from app.models.models import Employee, EmployeeLeave
from app.services.staff_leave_options import recount_monthly_day_totals


def make_db():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Employee(
        badge_number="SYNC-1",
        display_name="พนักงานซิงก์",
        thai_name="พนักงานซิงก์",
        location="HF",
        is_active=True,
        pending_approval=False,
    ))
    db.commit()
    return engine, db


def test_admin_leave_api_round_trips_day_off_half_day_without_marker_leak():
    engine, db = make_db()
    try:
        body = leaves_api.EmployeeLeaveIn(
            employee_badge_number="SYNC-1",
            leave_type="day_off",
            leave_portion="am",
            date=date(2026, 9, 18),
        )
        out = leaves_api.create_employee_leaves(body, db)
        assert len(out) == 1
        assert out[0].leave_type == "day_off"
        assert out[0].leave_portion == "am"
        assert out[0].note is None

        raw = db.query(EmployeeLeave).one()
        assert raw.note == "|half=am"

        listed = leaves_api.list_employee_leaves(
            date(2026, 9, 1), date(2026, 9, 30), None, db
        )
        assert listed[0].leave_portion == "am"
        assert listed[0].note is None
    finally:
        db.close()
        engine.dispose()


def test_admin_leave_api_rejects_half_day_range():
    engine, db = make_db()
    try:
        body = leaves_api.EmployeeLeaveIn(
            employee_badge_number="SYNC-1",
            leave_type="personal",
            leave_portion="pm",
            date_from=date(2026, 9, 18),
            date_to=date(2026, 9, 19),
        )
        with pytest.raises(HTTPException) as exc:
            leaves_api.create_employee_leaves(body, db)
        assert exc.value.status_code == 400
        assert "Half-day" in exc.value.detail
        assert db.query(EmployeeLeave).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_full_day_rewrite_removes_old_half_day_marker():
    engine, db = make_db()
    try:
        half = leaves_api.EmployeeLeaveIn(
            employee_badge_number="SYNC-1",
            leave_type="personal",
            leave_portion="am",
            date=date(2026, 9, 18),
        )
        leaves_api.create_employee_leaves(half, db)
        full = leaves_api.EmployeeLeaveIn(
            employee_badge_number="SYNC-1",
            leave_type="vacation",
            leave_portion="full",
            date=date(2026, 9, 18),
            note="หมายเหตุทั่วไป",
        )
        out = leaves_api.create_employee_leaves(full, db)
        assert out[0].leave_portion == "full"
        assert out[0].note == "หมายเหตุทั่วไป"
        assert db.query(EmployeeLeave).one().note == "หมายเหตุทั่วไป"
    finally:
        db.close()
        engine.dispose()


def test_monthly_totals_split_half_day_between_leave_and_attendance_status():
    payload = {
        "employees": [{
            "totals": {
                "worked_days": 99,
                "absent_days": 99,
                "off_days": 99,
                "leave_days": 99,
                "late_count": 2,
                "late_minutes_total": 21,
                "severe_count": 1,
                "hours_total": 12.5,
            },
            "days": [
                {"status": "present", "leave_portion": "am"},
                {"status": "absent", "leave_portion": "pm"},
                {"status": "leave", "leave_portion": "full"},
                {"status": "off", "leave_portion": "full"},
                {"status": "future"},
                {"status": "pending"},
            ],
        }],
    }

    out = recount_monthly_day_totals(payload)
    totals = out["employees"][0]["totals"]
    assert totals["worked_days"] == 0.5
    assert totals["absent_days"] == 0.5
    assert totals["off_days"] == 1.0
    assert totals["leave_days"] == 2.0
    # Punch-derived payroll facts are authoritative and must not be rewritten.
    assert totals["hours_total"] == 12.5
    assert totals["late_count"] == 2
    assert totals["late_minutes_total"] == 21
    assert totals["severe_count"] == 1


def test_shared_leave_ui_covers_both_pages_and_hides_internal_reference_vocabulary():
    source = Path("static/v2/leave-sync-ui.js").read_text(encoding="utf-8")
    nav = Path("static/v2/nav.js").read_text(encoding="utf-8")

    for phrase in (
        'page !== "leaves" && page !== "monthly"',
        'code: "day_off"',
        'leave_portion',
        'ครึ่งวันเช้า',
        'ครึ่งวันบ่าย',
        'id = "leaveSyncBoard"',
        'id = "monthlyLeaveSync"',
        '/api/private/leaves/employee',
    ):
        assert phrase in source
    assert "HF-LV-" not in source
    assert 'script.src = STATIC_BASE + "leave-sync-ui.js"' in nav


def test_day_off_is_native_admin_leave_type_not_runtime_only():
    assert "day_off" in leaves_api._ALLOWED_LEAVE_TYPES
