"""
Integration: HF ภายใน LINE leave auto-record -> attendance report.

Files a leave through the actual service entry points (service.submit +
service._maybe_auto_approve, the same call staff_leave.py's postback dispatch
and staff_leave_options' half-day submit make on the employee's final LINE
confirmation) with auto-record ON (the default), then reads it back through
the REAL report endpoints — GET /api/private/attendance/by-date and
GET /api/private/attendance/monthly/{year}/{month} (app/api/consolidated_attendance.py)
— to confirm an auto-recorded EmployeeLeave row is indistinguishable from a
manager-approved one to those reports, and that cancelling it removes it.

No LINE HTTP calls anywhere: this only exercises the SQLAlchemy service layer
and the FastAPI report endpoints, both stubbed-network per the file's own
docstring conventions (staff_leave.submit/decide never call LINE).

Reuses the DB/session/client fixtures and the ``_make_employee`` helper from
tests/integration/test_monthly_endpoint.py (same engine/session for both the
leave write and the report read, same seeded shift codes).
"""
from datetime import date
from uuid import uuid4

from app.models.staff_leave import StaffLeaveRequest
from app.services import staff_leave, staff_leave_manage, staff_leave_options, staff_leave_roster
from tests.integration.test_monthly_endpoint import (  # noqa: F401 (fixtures)
    _make_employee, monthly_client, monthly_engine, monthly_session,
    seed_device, seeded_shifts,
)

LEAVES_EMPLOYEE_PATH = "/api/private/leaves/employee"

BY_DATE_PATH = "/api/private/attendance/by-date"
MONTHLY_PATH = "/api/private/attendance/monthly/2026/5"
# Well inside service.validate_dates' bounds relative to the frozen "today"
# below, and safely in the past relative to the real wall clock so the report
# endpoints never see a "future"/"pending" day for these dates.
FROZEN_TODAY = date(2026, 5, 1)


def _by_date_row(client, on_date, badge):
    body = client.get(BY_DATE_PATH, params={"date": on_date.isoformat()}).json()
    return next(r for r in body["rows"] if r["badge_number"] == badge)


def _month_day(client, badge, day_index):
    body = client.get(MONTHLY_PATH).json()
    emp = next(e for e in body["employees"] if e["badge_number"] == badge)
    return emp, emp["days"][day_index - 1]


def test_full_day_auto_recorded_leave_appears_then_cancel_removes_it(
    monkeypatch, monthly_session, monthly_client, seed_device, seeded_shifts,
):
    monkeypatch.setattr(staff_leave, "today", lambda: FROZEN_TODAY)
    employee = _make_employee(
        monthly_session, "LV1", "Vacationer", role="technician", location="HF",
    )

    row = staff_leave.submit(
        monthly_session, employee, uuid4().hex, "vacation",
        date(2026, 5, 10), date(2026, 5, 12),
    )
    row = staff_leave._maybe_auto_approve(monthly_session, row)
    assert row.status == "approved" and row.reviewed_by == staff_leave.AUTO_REVIEWER

    by_date = _by_date_row(monthly_client, date(2026, 5, 11), "LV1")
    assert by_date["status"] == "off"
    assert by_date["leave_type"] == "vacation"

    emp, day11 = _month_day(monthly_client, "LV1", 11)
    assert day11["status"] == "leave"
    assert day11["leave_type"] == "vacation"
    assert day11.get("leave_portion") == "full"
    assert emp["totals"]["leave_days"] == 3.0

    cancelled = staff_leave.cancel(monthly_session, "LV1", row.id)
    assert cancelled.status == "cancelled"

    by_date_after = _by_date_row(monthly_client, date(2026, 5, 11), "LV1")
    assert by_date_after["leave_type"] is None
    assert by_date_after["status"] == "absent"  # NORMAL shift, no punch, no leave

    emp_after, day11_after = _month_day(monthly_client, "LV1", 11)
    assert day11_after["leave_type"] is None
    assert day11_after["status"] == "absent"
    assert emp_after["totals"]["leave_days"] == 0.0


def test_half_day_auto_recorded_leave_shows_fractional_totals_then_cancels(
    monkeypatch, monthly_session, monthly_client, seed_device, seeded_shifts,
):
    monkeypatch.setattr(staff_leave, "today", lambda: FROZEN_TODAY)
    staff_leave_options.install(staff_leave)
    employee = _make_employee(
        monthly_session, "LV2", "HalfDayer", role="technician", location="HF",
    )

    # The half-day submit entry point itself, same one staff_leave_options'
    # postback dispatch calls, exercising the installed `decide` override
    # (routes to _decide_half because leave_portion is "am"/"pm").
    row = staff_leave_options._submit_half(
        staff_leave, monthly_session, employee, uuid4().hex,
        "personal", date(2026, 5, 15), "am",
    )
    assert row.status == "approved" and row.reviewed_by == staff_leave.AUTO_REVIEWER
    assert row.leave_portion == "am"

    by_date = _by_date_row(monthly_client, date(2026, 5, 15), "LV2")
    # Half-day leave tags the day but does NOT hide real attendance: no punch
    # on an assigned NORMAL day is still "absent", per staff_leave_options'
    # own docstring ("attendance APIs keep computing instead of treating
    # that date as a full-day absence").
    assert by_date["status"] == "absent"
    assert by_date["leave_type"] == "personal"
    assert by_date["leave_portion"] == "am"

    emp, day15 = _month_day(monthly_client, "LV2", 15)
    assert day15["status"] == "absent"
    assert day15["leave_type"] == "personal"
    assert day15["leave_portion"] == "am"
    # recount_monthly_day_totals: a half-day splits 0.5 leave + 0.5 of the
    # real attendance state (absent here) instead of one full leave day.
    assert emp["totals"]["leave_days"] == 0.5

    cancelled = staff_leave.cancel(monthly_session, "LV2", row.id)
    assert cancelled.status == "cancelled"

    by_date_after = _by_date_row(monthly_client, date(2026, 5, 15), "LV2")
    assert by_date_after["leave_type"] is None
    assert by_date_after["status"] == "absent"

    emp_after, _ = _month_day(monthly_client, "LV2", 15)
    assert emp_after["totals"]["leave_days"] == 0.0


def test_webhook_submit_postback_auto_records_and_shows_in_report(
    monkeypatch, monthly_session, monthly_client, seed_device, seeded_shifts,
):
    """End-to-end proof through the REAL webhook entry point: install
    staff_leave_options + staff_leave_manage exactly like app/api/staff_oa.py
    does, then drive staff_leave.handle_event with a signed "submit" postback
    for a 2-day personal leave (no LINE HTTP calls — reply is stubbed)."""
    staff_leave_options.install(staff_leave)
    staff_leave_manage.install(staff_leave)
    monkeypatch.setattr(staff_leave, "today", lambda: FROZEN_TODAY)
    monkeypatch.setattr(
        staff_leave.staff_oa_service, "get_channel_secret", lambda: "test-secret"
    )
    employee = _make_employee(
        monthly_session, "WH1", "WebhookFiler", role="technician", location="HF",
    )
    employee.line_user_id = "Uwebhook1"
    employee.pending_approval = False
    monthly_session.commit()

    replies = []
    monkeypatch.setattr(
        staff_leave, "_reply", lambda token, messages: replies.append(messages)
    )

    request_id = uuid4().hex
    start, end = date(2026, 5, 20), date(2026, 5, 21)
    data = staff_leave.action_data(
        "submit", "WH1", request_id, "personal", start.isoformat(), end.isoformat(),
    )
    event = {
        "replyToken": "rt-webhook",
        "type": "postback",
        "source": {"type": "user", "userId": "Uwebhook1"},
        "postback": {"data": data},
    }
    staff_leave.handle_event(event, monthly_session)

    monthly_session.expire_all()
    row = monthly_session.get(StaffLeaveRequest, request_id)
    assert row.status == "approved"
    assert row.reviewed_by == staff_leave.AUTO_REVIEWER
    assert replies and "บันทึกการลาแล้ว" in replies[-1][0]["text"]

    for on_date, day_index in ((date(2026, 5, 20), 20), (date(2026, 5, 21), 21)):
        by_date = _by_date_row(monthly_client, on_date, "WH1")
        assert by_date["status"] == "off"
        assert by_date["leave_type"] == "personal"

        emp, day_row = _month_day(monthly_client, "WH1", day_index)
        assert day_row["status"] == "leave"
        assert day_row["leave_type"] == "personal"
        assert day_row.get("leave_portion") == "full"
    assert emp["totals"]["leave_days"] == 2.0


def test_admin_deleting_one_roster_day_updates_reports_and_latest_leave(
    monkeypatch, monthly_session, monthly_client, seed_device, seeded_shifts,
):
    """The roster is the single source of truth for every LINE leave
    surface (docs/LEAVE_SYNC_SURFACES.md): deleting one day of an
    auto-recorded leave on shifts-admin (here, via the same
    /api/private/leaves/employee endpoint shifts-admin uses) removes that
    day from the by-date/monthly reports while the other days remain, and
    ``ใบลาล่าสุด`` (staff_leave_roster.latest_effective_leave) agrees it is
    now only "partial"."""
    monkeypatch.setattr(staff_leave, "today", lambda: FROZEN_TODAY)
    employee = _make_employee(
        monthly_session, "LV3", "PartialDay", role="technician", location="HF",
    )

    row = staff_leave.submit(
        monthly_session, employee, uuid4().hex, "vacation",
        date(2026, 5, 10), date(2026, 5, 12),
    )
    row = staff_leave._maybe_auto_approve(monthly_session, row)
    assert row.status == "approved"

    resp = monthly_client.delete(f"{LEAVES_EMPLOYEE_PATH}/LV3/2026-05-11")
    assert resp.status_code == 204

    # The removed middle day no longer shows as leave in either report...
    by_date_11 = _by_date_row(monthly_client, date(2026, 5, 11), "LV3")
    assert by_date_11["leave_type"] is None
    assert by_date_11["status"] == "absent"
    _, day11 = _month_day(monthly_client, "LV3", 11)
    assert day11["leave_type"] is None
    assert day11["status"] == "absent"

    # ...while the other two days are untouched.
    for on_date, day_index in ((date(2026, 5, 10), 10), (date(2026, 5, 12), 12)):
        by_date = _by_date_row(monthly_client, on_date, "LV3")
        assert by_date["status"] == "off"
        assert by_date["leave_type"] == "vacation"
        emp, day_row = _month_day(monthly_client, "LV3", day_index)
        assert day_row["status"] == "leave"
        assert day_row["leave_type"] == "vacation"
    assert emp["totals"]["leave_days"] == 2.0

    monthly_session.expire_all()
    refreshed = monthly_session.get(StaffLeaveRequest, row.id)
    assert refreshed.status == "approved"
    latest = staff_leave_roster.latest_effective_leave(monthly_session, "LV3")
    assert latest.status == "partial"
    assert latest.dates == (date(2026, 5, 10), date(2026, 5, 12))
