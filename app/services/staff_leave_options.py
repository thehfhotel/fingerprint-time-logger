"""Incremental leave options for HF ภายใน: day-off + half-day periods.

This module installs on top of the signed staff_leave flow so existing full-day
requests remain byte-compatible. Half-day approvals are persisted in the
employee leave table with a compact note marker; attendance APIs keep computing
attendance instead of treating that date as a full-day absence.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy.exc import IntegrityError

from app.models.models import Employee, EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest

PORTION_LABELS = {"full": "เต็มวัน", "am": "ครึ่งวันเช้า", "pm": "ครึ่งวันบ่าย"}
_HALF_RE = re.compile(
    r"^(?:แจ้งลา|ขอลา)\s+"
    r"(?P<kind>ลาพักร้อน|พักร้อน|ลาป่วย|ป่วย|ลากิจ|กิจ|ใช้วันหยุด|วันหยุด)\s+"
    r"(?P<portion>ครึ่งวันเช้า|ครึ่งวันบ่าย)\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*$"
)
_INSTALLED = False


def _half_note(reference: str, portion: str) -> str:
    return f"{reference}|half={portion}"


def portion_from_leave_note(note: str | None) -> str:
    if not note:
        return "full"
    match = re.search(r"\|half=(am|pm)$", note)
    return match.group(1) if match else "full"


def _parse_half(service, text: str):
    normalized = re.sub(r"\s+", " ", text.strip())
    match = _HALF_RE.fullmatch(normalized)
    if not match:
        return None
    kind = service.TYPE_WORDS[match.group("kind")]
    single = service.SINGLE_DATE_RE.fullmatch(match.group("date"))
    if not single:
        return None
    on_date = service._make_date(*single.groups())
    service.validate_dates(on_date, on_date)
    portion = "am" if match.group("portion") == "ครึ่งวันเช้า" else "pm"
    return kind, on_date, portion


def _review_half(service, employee: Employee, request_id: str, kind: str,
                 on_date: date, portion: str, expires: int | None = None) -> dict:
    return service._text(
        f"ตรวจสอบก่อนส่งใบลา\n{employee.thai_name or employee.display_name}\n"
        f"{service.TYPES[kind]} • {PORTION_LABELS[portion]}\n"
        f"{service.thai_date(on_date)} (พ.ศ.)\n0.5 วัน\n"
        "หลังส่งจะบันทึกในระบบพนักงานเป็นสถานะ รออนุมัติ", [
            service._postback(
                "ยืนยันส่งใบลา",
                service.action_data(
                    f"submit_{portion}", employee.badge_number, request_id, kind,
                    on_date.isoformat(), on_date.isoformat(), expires,
                ),
            ),
            {"type": "message", "label": "เริ่มใหม่", "text": "แจ้งลา"},
        ],
    )


def _submit_half(service, db, employee: Employee, request_id: str, kind: str,
                 on_date: date, portion: str) -> StaffLeaveRequest:
    existing = db.get(StaffLeaveRequest, request_id)
    if existing is not None:
        if getattr(existing, "leave_portion", "full") != portion:
            raise service.LeaveError("เลขรายการนี้ถูกใช้แล้ว กรุณาพิมพ์ แจ้งลา เพื่อเริ่มใหม่")
        return existing
    row = service.submit(db, employee, request_id, kind, on_date, on_date)
    row.leave_portion = portion
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def _decide_half(service, db, row: StaffLeaveRequest, decision: str,
                 version: int, reviewer: str) -> StaffLeaveRequest:
    if decision not in ("approved", "rejected") or not reviewer:
        raise service.LeaveError("คำสั่งอนุมัติไม่ถูกต้อง")
    employee = db.query(Employee).filter(
        Employee.badge_number == row.employee_badge_number,
        Employee.is_active.is_(True), Employee.pending_approval.is_(False),
    ).first()
    if decision == "approved" and employee is None:
        raise service.LeaveError("พนักงานไม่มีสถานะใช้งาน ไม่สามารถอนุมัติได้")

    now = datetime.utcnow()
    changed = db.query(StaffLeaveRequest).filter(
        StaffLeaveRequest.id == row.id,
        StaffLeaveRequest.status == "pending",
        StaffLeaveRequest.version == version,
    ).update({
        "status": decision,
        "version": StaffLeaveRequest.version + 1,
        "reviewed_by": reviewer,
        "reviewed_at": now,
        "updated_at": now,
    }, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise service.LeaveError("สถานะเปลี่ยนแล้ว กรุณาโหลดรายการใหม่")

    try:
        if decision == "approved":
            if db.query(EmployeeLeave).filter(
                EmployeeLeave.employee_badge_number == row.employee_badge_number,
                EmployeeLeave.date == row.date_from,
            ).first():
                raise service.LeaveError("มีวันลาในตารางงานทับซ้อน ระบบไม่เขียนทับ กรุณาตรวจสอบก่อน")
            db.add(EmployeeLeave(
                employee_badge_number=row.employee_badge_number,
                date=row.date_from,
                leave_type=row.leave_type,
                note=_half_note(service.reference(row), row.leave_portion),
            ))
        else:
            db.query(StaffLeaveDay).filter(StaffLeaveDay.request_id == row.id).delete()
        db.commit()
    except (IntegrityError, service.LeaveError) as exc:
        db.rollback()
        if isinstance(exc, service.LeaveError):
            raise
        raise service.LeaveError(
            "ตารางงานเปลี่ยนระหว่างอนุมัติ กรุณาโหลดใหม่ ไม่มีการเขียนทับข้อมูล"
        ) from exc
    db.expire_all()
    return db.get(StaffLeaveRequest, row.id)


def install(service) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Fourth employee leave type. `day_off` means using an employee's own
    # accrued/rest day; it is deliberately distinct from company public holidays.
    service.TYPES["day_off"] = "ใช้วันหยุด"
    service.TYPE_WORDS.update({"ใช้วันหยุด": "day_off", "วันหยุด": "day_off"})
    service.DIRECT_RE = re.compile(
        r"^(?:แจ้งลา|ขอลา)\s+"
        r"(?P<kind>ลาพักร้อน|พักร้อน|ลาป่วย|ป่วย|ลากิจ|กิจ|ใช้วันหยุด|วันหยุด)\s+"
        r"(?P<dates>\S+)\s*$"
    )

    original_calendar_days = service.calendar_days
    original_messages = service._messages
    original_decide = service.decide

    def calendar_days(row):
        if getattr(row, "leave_portion", "full") in ("am", "pm"):
            return 0.5
        return original_calendar_days(row)

    def messages(event, db, employee):
        badge = employee.badge_number
        if event.get("type") == "message":
            text = ((event.get("message") or {}).get("text") or "").strip()
            half = _parse_half(service, text)
            if half:
                kind, on_date, portion = half
                from uuid import uuid4
                return [_review_half(service, employee, uuid4().hex, kind, on_date, portion)]

        if event.get("type") == "postback":
            data = ((event.get("postback") or {}).get("data") or "")
            if isinstance(data, str) and data.startswith(service.PREFIX):
                verb, request_id, kind, start_s, end_s, expires = service._parse_action(data, badge)
                params = (event.get("postback") or {}).get("params") or {}
                if verb == "from":
                    result = original_messages(event, db, employee)
                    on_date = date.fromisoformat(params["date"])
                    actions = result[0].get("quickReply", {}).get("items", [])
                    for portion in ("am", "pm"):
                        actions.append({"type": "action", "action": service._postback(
                            PORTION_LABELS[portion],
                            service.action_data(
                                f"half_{portion}", badge, request_id, kind,
                                on_date.isoformat(), on_date.isoformat(), expires,
                            ),
                        )})
                    return result
                if verb in ("half_am", "half_pm"):
                    portion = verb.removeprefix("half_")
                    on_date = date.fromisoformat(start_s)
                    return [_review_half(
                        service, employee, request_id, kind, on_date, portion, expires
                    )]
                if verb in ("submit_am", "submit_pm"):
                    portion = verb.removeprefix("submit_")
                    on_date = date.fromisoformat(start_s)
                    row = _submit_half(
                        service, db, employee, request_id, kind, on_date, portion
                    )
                    return service._after_submit(row)
        return original_messages(event, db, employee)

    def decide(db, request_id: str, decision: str, version: int, reviewer: str):
        row = db.get(StaffLeaveRequest, request_id)
        if row is not None and getattr(row, "leave_portion", "full") in ("am", "pm"):
            return _decide_half(service, db, row, decision, version, reviewer)
        return original_decide(db, request_id, decision, version, reviewer)

    service.calendar_days = calendar_days
    service._messages = messages
    service.decide = decide

    # Existing manager DTO/UI gets a human-readable half-day suffix without a
    # second public endpoint or any change to medical-document privacy.
    try:
        from app.api import staff_leave as leave_api
        original_dto = leave_api._dto

        def dto(row):
            data = original_dto(row)
            portion = getattr(row, "leave_portion", "full")
            data["leave_portion"] = portion
            data["leave_portion_label"] = PORTION_LABELS[portion]
            if portion != "full":
                data["leave_label"] = f"{data['leave_label']} • {PORTION_LABELS[portion]}"
            return data

        leave_api._dto = dto
    except Exception:
        pass

    try:
        from app.api import leaves as leaves_api
        if "day_off" not in leaves_api._ALLOWED_LEAVE_TYPES:
            leaves_api._ALLOWED_LEAVE_TYPES = (*leaves_api._ALLOWED_LEAVE_TYPES, "day_off")
    except Exception:
        pass

    # A half-day EmployeeLeave is still a roster annotation, but must not make
    # attendance APIs classify the whole day as off. Keep attendance computation
    # intact and attach leave metadata to the returned row instead.
    try:
        from app.api import consolidated_attendance as attendance_api
        original_shift_row = attendance_api._build_shift_row
        original_month_day = attendance_api._build_month_day

        def build_shift_row(db, employee, target_day, eff, *, holiday=None, leave=None):
            portion = portion_from_leave_note(getattr(leave, "note", None)) if leave else "full"
            if leave is None or portion == "full":
                return original_shift_row(
                    db, employee, target_day, eff, holiday=holiday, leave=leave
                )
            row = original_shift_row(
                db, employee, target_day, eff, holiday=holiday, leave=None
            )
            row["leave_type"] = leave.leave_type
            row["leave_note"] = leave.note
            row["leave_portion"] = portion
            return row

        def build_month_day(employee, day, eff, punches, *, today, now_bkk,
                            holiday, leave):
            portion = portion_from_leave_note(getattr(leave, "note", None)) if leave else "full"
            if leave is None or portion == "full":
                return original_month_day(
                    employee, day, eff, punches, today=today, now_bkk=now_bkk,
                    holiday=holiday, leave=leave,
                )
            row = original_month_day(
                employee, day, eff, punches, today=today, now_bkk=now_bkk,
                holiday=holiday, leave=None,
            )
            row["leave_type"] = leave.leave_type
            row["leave_note"] = leave.note
            row["leave_portion"] = portion
            return row

        attendance_api._build_shift_row = build_shift_row
        attendance_api._build_month_day = build_month_day
    except Exception:
        pass
