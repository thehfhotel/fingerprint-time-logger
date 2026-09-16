"""HF ภายใน leave flow. Verified webhook only; no push, LLM, or group filing.

Date-picker/postback state is HMAC-bound to the active employee and expires
in one hour. A form UUID is also the durable submission idempotency key.
Images are separately scoped, expiring bearer URLs with no private reasons.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import Employee, EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest
from app.services import staff_oa_service

BKK = ZoneInfo("Asia/Bangkok")
TYPES = {"sick": "ลาป่วย", "personal": "ลากิจ", "vacation": "ลาพักร้อน"}
STATUSES = {"pending": "รออนุมัติ", "approved": "อนุมัติแล้ว",
            "rejected": "ไม่อนุมัติ", "cancelled": "ยกเลิกแล้ว"}
COMMANDS = {"แจ้งลา", "ขอลา", "ใบลาล่าสุด", "ยกเลิกใบลา"}
PREFIX = "hfleave:"
ORIGIN = "https://erp.thehfhotel.org"
IMAGE_TTL = 86400
FORM_TTL = 3600
MAX_DAYS = 92
ID_RE = re.compile(r"^[0-9a-f]{32}$")


class LeaveError(ValueError):
    """A safe Thai message for the employee or reviewer."""


def today() -> date:
    return datetime.now(BKK).date()


def thai_date(value: date) -> str:
    return f"{value.day:02d}/{value.month:02d}/{value.year + 543}"


def reference(row: StaffLeaveRequest) -> str:
    return f"HF-LV-{row.id.upper()}"


def validate_dates(start: date, end: date) -> None:
    if end < start or (end - start).days + 1 > MAX_DAYS:
        raise LeaveError(f"กรุณาเลือกวันสิ้นสุดไม่ก่อนวันเริ่ม และไม่เกิน {MAX_DAYS} วันต่อรายการ")
    if start < today() - timedelta(days=31) or end > today() + timedelta(days=366):
        raise LeaveError("วันที่ต้องอยู่ระหว่างย้อนหลัง 31 วันและล่วงหน้า 366 วัน กรุณาติดต่อผู้ดูแลสำหรับช่วงอื่น")


def _mac(purpose: str, text: str) -> str:
    secret = staff_oa_service.get_channel_secret()
    if not secret:
        raise LeaveError("ระบบแจ้งลายังไม่พร้อมใช้งาน")
    return hmac.new(secret.encode(), f"{purpose}\n{text}".encode(), hashlib.sha256).hexdigest()


def action_data(verb: str, badge: str, request_id: str, kind: str = "-",
                start: str = "-", end: str = "-", expires: int | None = None) -> str:
    expires = expires if expires is not None else int(time.time()) + FORM_TTL
    body = ":".join((verb, request_id, kind, start, end, str(expires)))
    return PREFIX + body + ":" + _mac("staff-leave-form-v1", badge + ":" + body)


def _parse_action(data: str, badge: str) -> tuple[str, str, str, str, str, int]:
    parts = data[len(PREFIX):].split(":")
    if len(parts) != 7 or not ID_RE.fullmatch(parts[1]):
        raise LeaveError("ปุ่มไม่ถูกต้อง กรุณาพิมพ์ แจ้งลา เพื่อเริ่มใหม่")
    body = ":".join(parts[:-1])
    if not hmac.compare_digest(_mac("staff-leave-form-v1", badge + ":" + body), parts[-1]):
        raise LeaveError("ปุ่มนี้ไม่ใช่ของบัญชีคุณ กรุณาพิมพ์ แจ้งลา เพื่อเริ่มใหม่")
    try:
        expires = int(parts[5])
    except ValueError as exc:
        raise LeaveError("ปุ่มไม่ถูกต้อง กรุณาเริ่มใหม่") from exc
    if not int(time.time()) < expires <= int(time.time()) + FORM_TTL + 5:
        raise LeaveError("ปุ่มหมดอายุแล้ว พิมพ์ แจ้งลา เพื่อเริ่มใหม่ หรือ ใบลาล่าสุด เพื่อตรวจสอบรายการที่ส่งแล้ว")
    return (*parts[:5], expires)


def image_url(row: StaffLeaveRequest, expires: int | None = None) -> str:
    expires = expires if expires is not None else int(time.time()) + IMAGE_TTL
    body = f"{row.id}:{row.version}:{expires}"
    signature = _mac("staff-leave-image-v1", body)
    return (f"{ORIGIN}/api/public/staff-oa/leave-images/{row.id}.png"
            f"?version={row.version}&expires={expires}&signature={signature}")


def valid_image_token(request_id: str, version: int, expires: int, signature: str) -> bool:
    if (not ID_RE.fullmatch(request_id) or not re.fullmatch(r"[0-9a-f]{64}", signature)
            or not staff_oa_service.get_channel_secret()):
        return False
    now = int(time.time())
    if not now < expires <= now + IMAGE_TTL + 5:
        return False
    return hmac.compare_digest(
        _mac("staff-leave-image-v1", f"{request_id}:{version}:{expires}"), signature
    )


def _span(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def submit(db: Session, employee: Employee, request_id: str, kind: str,
           start: date, end: date) -> StaffLeaveRequest:
    if not ID_RE.fullmatch(request_id) or kind not in TYPES:
        raise LeaveError("ประเภทลาหรือเลขรายการไม่ถูกต้อง")
    if not employee.is_active or employee.pending_approval:
        raise LeaveError("บัญชีพนักงานยังไม่มีสิทธิ์แจ้งลา")
    existing = db.get(StaffLeaveRequest, request_id)
    if existing:
        if (existing.employee_badge_number, existing.leave_type, existing.date_from,
                existing.date_to) != (employee.badge_number, kind, start, end):
            raise LeaveError("เลขรายการนี้ถูกใช้แล้ว กรุณาพิมพ์ แจ้งลา เพื่อเริ่มใหม่")
        return existing
    validate_dates(start, end)
    if db.query(EmployeeLeave).filter(
        EmployeeLeave.employee_badge_number == employee.badge_number,
        EmployeeLeave.date >= start, EmployeeLeave.date <= end,
    ).first():
        raise LeaveError("ช่วงวันที่นี้มีวันลาในตารางงานแล้ว กรุณาตรวจสอบกับผู้ดูแล")
    row = StaffLeaveRequest(
        id=request_id, employee_badge_number=employee.badge_number,
        employee_name=employee.thai_name or employee.display_name,
        department=employee.department, location=employee.location,
        leave_type=kind, date_from=start, date_to=end,
        status="pending", version=1,
    )
    try:
        db.add(row)
        db.flush()
        db.add_all([StaffLeaveDay(employee_badge_number=employee.badge_number,
                                 date=day, request_id=request_id)
                    for day in _span(start, end)])
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A retried confirmation can race the original. Only return that
        # exact employee/date/type request; never create a second record.
        existing = db.get(StaffLeaveRequest, request_id)
        if existing and (existing.employee_badge_number, existing.leave_type,
                         existing.date_from, existing.date_to) == (
                employee.badge_number, kind, start, end):
            return existing
        raise LeaveError("มีใบลาทับซ้อนในช่วงวันที่นี้แล้ว พิมพ์ ใบลาล่าสุด เพื่อตรวจสอบ") from exc
    db.refresh(row)
    return row


def cancel(db: Session, badge: str, request_id: str) -> StaffLeaveRequest:
    row = db.get(StaffLeaveRequest, request_id)
    if row is None or row.employee_badge_number != badge:
        raise LeaveError("ไม่พบใบลาของคุณ")
    if row.status == "cancelled":
        return row
    changed = db.query(StaffLeaveRequest).filter(
        StaffLeaveRequest.id == request_id,
        StaffLeaveRequest.employee_badge_number == badge,
        StaffLeaveRequest.status == "pending",
    ).update({"status": "cancelled", "version": StaffLeaveRequest.version + 1,
              "updated_at": datetime.utcnow()}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise LeaveError("ยกเลิกได้เฉพาะใบลาที่ยังรออนุมัติ กรุณาติดต่อผู้อนุมัติ")
    db.query(StaffLeaveDay).filter(StaffLeaveDay.request_id == request_id).delete()
    db.commit()
    db.expire_all()
    return db.get(StaffLeaveRequest, request_id)


def decide(db: Session, request_id: str, decision: str, version: int,
           reviewer: str) -> StaffLeaveRequest:
    if decision not in ("approved", "rejected") or not reviewer:
        raise LeaveError("คำสั่งอนุมัติไม่ถูกต้อง")
    row = db.get(StaffLeaveRequest, request_id)
    if row is None:
        raise LeaveError("ไม่พบใบลา")
    employee = db.query(Employee).filter(
        Employee.badge_number == row.employee_badge_number,
        Employee.is_active.is_(True), Employee.pending_approval.is_(False),
    ).first()
    if decision == "approved" and employee is None:
        raise LeaveError("พนักงานไม่มีสถานะใช้งาน ไม่สามารถอนุมัติได้")
    now = datetime.utcnow()
    # Compare-and-set takes the SQLite write lock before checking/inserting
    # roster days. Cancellation or a second reviewer can never win as well.
    changed = db.query(StaffLeaveRequest).filter(
        StaffLeaveRequest.id == request_id, StaffLeaveRequest.status == "pending",
        StaffLeaveRequest.version == version,
    ).update({"status": decision, "version": StaffLeaveRequest.version + 1,
              "reviewed_by": reviewer, "reviewed_at": now, "updated_at": now},
             synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise LeaveError("สถานะเปลี่ยนแล้ว กรุณาโหลดรายการใหม่")
    try:
        if decision == "approved":
            if db.query(EmployeeLeave).filter(
                EmployeeLeave.employee_badge_number == row.employee_badge_number,
                EmployeeLeave.date >= row.date_from, EmployeeLeave.date <= row.date_to,
            ).first():
                raise LeaveError("มีวันลาในตารางงานทับซ้อน ระบบไม่เขียนทับ กรุณาตรวจสอบก่อน")
            db.add_all([EmployeeLeave(
                employee_badge_number=row.employee_badge_number, date=day,
                leave_type=row.leave_type, note=reference(row),
            ) for day in _span(row.date_from, row.date_to)])
        else:
            db.query(StaffLeaveDay).filter(StaffLeaveDay.request_id == request_id).delete()
        db.commit()
    except (IntegrityError, LeaveError) as exc:
        db.rollback()
        if isinstance(exc, LeaveError):
            raise
        raise LeaveError("ตารางงานเปลี่ยนระหว่างอนุมัติ กรุณาโหลดใหม่ ไม่มีการเขียนทับข้อมูล") from exc
    db.expire_all()
    return db.get(StaffLeaveRequest, request_id)


def is_leave_event(event: object) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("type") == "postback":
        postback = event.get("postback")
        return (isinstance(postback, dict) and isinstance(postback.get("data"), str)
                and postback["data"].startswith(PREFIX))
    message = event.get("message")
    return (event.get("type") == "message" and isinstance(message, dict)
            and message.get("type") == "text"
            and isinstance(message.get("text"), str)
            and message["text"].strip() in COMMANDS)


def _text(text: str, actions: list[dict] | None = None) -> dict:
    message = {"type": "text", "text": text}
    if actions:
        message["quickReply"] = {"items": [{"type": "action", "action": action}
                                           for action in actions]}
    return message


def _postback(label: str, data: str) -> dict:
    return {"type": "postback", "label": label, "data": data}


def _picker(label: str, data: str, initial: date, minimum: date, maximum: date) -> dict:
    return {"type": "datetimepicker", "label": label, "data": data, "mode": "date",
            "initial": initial.isoformat(), "min": minimum.isoformat(),
            "max": maximum.isoformat()}


def _reply(token: str, messages: list[dict]) -> None:
    if not token:
        return
    response = requests.post(
        f"{staff_oa_service.LINE_API_BASE}/v2/bot/message/reply",
        headers={"Authorization": f"Bearer {staff_oa_service.get_channel_access_token()}"},
        json={"replyToken": token, "messages": messages}, timeout=15,
    )
    if response.status_code // 100 != 2:
        # Do not include LINE's response body, token, or any employee data.
        raise RuntimeError(f"Leave reply failed: HTTP {response.status_code}")


def _receipt(row: StaffLeaveRequest) -> list[dict]:
    url = image_url(row)
    return [
        _text(f"{STATUSES[row.status]}\nเลขอ้างอิง {reference(row)}\n"
              "กดรูปแล้วเลือกส่งต่อไปยังกลุ่มได้ รูปเป็นสถานะ ณ เวลาที่สร้าง "
              "พิมพ์ ใบลาล่าสุด เพื่อขอรูปสถานะปัจจุบัน"),
        {"type": "image", "originalContentUrl": url, "previewImageUrl": url},
    ]


def handle_event(event: dict, db: Session) -> None:
    """Called ONLY after staff_oa verified the signature and claimed the event.

    The webhook runs this sync function in a worker thread; LINE's fetch of
    the image must not be blocked by our synchronous reply HTTP request.
    """
    if event.get("mode") == "standby":
        return
    token = event.get("replyToken", "")
    source = event.get("source") or {}
    if not isinstance(source, dict) or source.get("type") != "user":
        _reply(token, [_text("กรุณาเปิดแชตส่วนตัวกับ HF ภายใน แล้วพิมพ์ แจ้งลา เพื่อรักษาข้อมูลส่วนตัว")])
        return
    employee = db.query(Employee).filter(
        Employee.line_user_id == source.get("userId", ""),
        Employee.is_active.is_(True), Employee.pending_approval.is_(False),
    ).first()
    if employee is None or not source.get("userId"):
        _reply(token, [_text("กรุณาผูก LINE กับบัญชีพนักงานและให้ผู้ดูแลอนุมัติก่อนแจ้งลา")])
        return
    try:
        messages = _messages(event, db, employee)
    except (LeaveError, ValueError, TypeError, KeyError) as exc:
        db.rollback()
        text = str(exc) if isinstance(exc, LeaveError) else "ข้อมูลวันที่ไม่ถูกต้อง กรุณาพิมพ์ แจ้งลา เพื่อเริ่มใหม่"
        messages = [_text(text)]
    _reply(token, messages)


def _messages(event: dict, db: Session, employee: Employee) -> list[dict]:
    badge = employee.badge_number
    if event["type"] == "message":
        command = event["message"]["text"].strip()
        if command in ("แจ้งลา", "ขอลา"):
            request_id = uuid4().hex
            return [_text("แจ้งลา • เลือกประเภทลาและวันเริ่มลา\n"
                          "ระบบรองรับลาเต็มวัน รายละเอียดส่วนตัวแจ้งผู้อนุมัติโดยตรง "
                          "ยังไม่บันทึกจนกด ยืนยันส่งใบลา", [
                _picker(label, action_data("from", badge, request_id, kind), today(),
                        today() - timedelta(days=31), today() + timedelta(days=366))
                for kind, label in TYPES.items()
            ])]
        query = db.query(StaffLeaveRequest).filter(
            StaffLeaveRequest.employee_badge_number == badge)
        if command == "ยกเลิกใบลา":
            query = query.filter(StaffLeaveRequest.status == "pending")
        row = query.order_by(StaffLeaveRequest.created_at.desc(), StaffLeaveRequest.id.desc()).first()
        if row is None:
            return [_text("ไม่พบใบลา" + ("ที่รออนุมัติ" if command == "ยกเลิกใบลา" else "ของคุณ"))]
        if command == "ยกเลิกใบลา":
            return [_text(f"ยกเลิกใบลาที่รออนุมัติ {thai_date(row.date_from)} – {thai_date(row.date_to)}?", [
                _postback("ยืนยันยกเลิกใบลา", action_data("cancel", badge, row.id))])]
        return _receipt(row)

    verb, request_id, kind, start_s, end_s, expires = _parse_action(
        event["postback"]["data"], badge)
    if verb == "cancel":
        return _receipt(cancel(db, badge, request_id))
    if kind not in TYPES:
        raise LeaveError("ประเภทลาไม่ถูกต้อง")
    params = event["postback"].get("params") or {}
    if verb == "from":
        start = date.fromisoformat(params["date"])
        validate_dates(start, start)
        maximum = min(start + timedelta(days=MAX_DAYS - 1), today() + timedelta(days=366))
        actions = []
        # LINE requires min < max, not min <= max. At the upper boundary,
        # only a one-day request is valid; never send an invalid date picker.
        if maximum > start:
            actions.append(_picker("เลือกวันสุดท้าย", action_data("to", badge, request_id, kind,
                           start.isoformat(), expires=expires), start, start, maximum))
        actions.append(_postback("ลา 1 วัน", action_data("review", badge, request_id, kind,
                       start.isoformat(), start.isoformat(), expires)))
        return [_text(f"{TYPES[kind]} เริ่ม {thai_date(start)} (พ.ศ.)\nเลือกวันสุดท้าย หรือ ลา 1 วัน", actions)]
    start = date.fromisoformat(start_s)
    end = date.fromisoformat(params["date"] if verb == "to" else end_s)
    if verb == "submit":
        return _receipt(submit(db, employee, request_id, kind, start, end))
    if verb not in ("to", "review"):
        raise LeaveError("คำสั่งไม่ถูกต้อง กรุณาเริ่มใหม่")
    validate_dates(start, end)
    return [_text(
        f"ตรวจสอบก่อนส่งใบลา\n{employee.thai_name or employee.display_name}\n"
        f"{TYPES[kind]}\n{thai_date(start)} – {thai_date(end)} (พ.ศ.)\n"
        f"{(end - start).days + 1} วันตามปฏิทิน (ไม่ใช่ยอดสิทธิวันลา)\n"
        "หลังส่งจะอยู่ในสถานะ รออนุมัติ รูปสำหรับกลุ่มจะไม่มีเหตุผลส่วนตัว", [
            _postback("ยืนยันส่งใบลา", action_data("submit", badge, request_id, kind,
                      start.isoformat(), end.isoformat(), expires)),
            {"type": "message", "label": "เริ่มใหม่", "text": "แจ้งลา"},
        ])]
