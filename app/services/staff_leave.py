"""HF ภายใน leave flow. Verified webhook only; no push, LLM, or group filing.

Date-picker/postback state is HMAC-bound to the active employee and expires
in one hour. A form UUID is also the durable submission idempotency key.
Receipt images are separately scoped, expiring bearer URLs. Medical
certificates are private database attachments and never appear in public PNGs.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from datetime import date, datetime, timedelta
from io import BytesIO
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from PIL import Image
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import Employee, EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest
from app.services import staff_oa_service

BKK = ZoneInfo("Asia/Bangkok")
TYPES = {"sick": "ลาป่วย", "personal": "ลากิจ", "vacation": "ลาพักร้อน"}
TYPE_WORDS = {
    "ป่วย": "sick", "ลาป่วย": "sick",
    "กิจ": "personal", "ลากิจ": "personal",
    "พักร้อน": "vacation", "ลาพักร้อน": "vacation",
}
# "approved" covers both a manager's decision and an auto-recorded LINE
# confirmation (see AUTO_REVIEWER) — the employee never sees who/what
# reviewed it, so one shared label must read correctly for both.
STATUSES = {"pending": "รออนุมัติ", "approved": "บันทึกการลาแล้ว",
            "rejected": "ไม่อนุมัติ", "cancelled": "ยกเลิกแล้ว"}
COMMANDS = {"แจ้งลา", "ขอลา", "ใบลาล่าสุด", "ยกเลิกใบลา"}
# Reviewer marker for a request auto-recorded on the employee's final LINE
# confirmation (see auto_approve_enabled/_maybe_auto_approve) instead of a
# human manager decision. Never a LINE id or employee name.
AUTO_REVIEWER = "auto:staff-oa"
_AUTO_APPROVE_TRUTHY = {"1", "true", "yes", "on"}
PREFIX = "hfleave:"
ORIGIN = "https://erp.thehfhotel.org"
IMAGE_TTL = 86400
FORM_TTL = 3600
MAX_DAYS = 92
MAX_MEDICAL_DOWNLOAD = 12 * 1024 * 1024
MAX_MEDICAL_STORED = 8 * 1024 * 1024
ID_RE = re.compile(r"^[0-9a-f]{32}$")
DIRECT_RE = re.compile(
    r"^(?:แจ้งลา|ขอลา)\s+(?P<kind>ลาพักร้อน|พักร้อน|ลาป่วย|ป่วย|ลากิจ|กิจ)\s+"
    r"(?P<dates>\S+)\s*$"
)
SINGLE_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
SHORT_RANGE_RE = re.compile(r"^(\d{1,2})-(\d{1,2})/(\d{1,2})/(\d{4})$")
FULL_RANGE_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})-(\d{1,2})/(\d{1,2})/(\d{4})$"
)


class LeaveError(ValueError):
    """A safe Thai message for the employee or reviewer."""


def today() -> date:
    return datetime.now(BKK).date()


def auto_approve_enabled() -> bool:
    """Read live (never cached) so ops can flip the switch without a deploy.

    The hotel has no manager-approval step today: a LINE-confirmed leave
    request is recorded immediately. Default TRUE when unset; the pending/
    review machinery stays available behind this switch for the future.
    """
    return os.getenv("STAFF_LEAVE_AUTO_APPROVE", "true").strip().lower() in _AUTO_APPROVE_TRUTHY


def thai_date(value: date) -> str:
    return f"{value.day:02d}/{value.month:02d}/{value.year + 543}"


def reference(row: StaffLeaveRequest) -> str:
    return f"HF-LV-{row.id.upper()}"


def calendar_days(row: StaffLeaveRequest) -> int:
    return (row.date_to - row.date_from).days + 1


def medical_certificate_required(row: StaffLeaveRequest) -> bool:
    return row.leave_type == "sick" and calendar_days(row) > 3


def validate_dates(start: date, end: date) -> None:
    if end < start or (end - start).days + 1 > MAX_DAYS:
        raise LeaveError(f"กรุณาเลือกวันสิ้นสุดไม่ก่อนวันเริ่ม และไม่เกิน {MAX_DAYS} วันต่อรายการ")
    if start < today() - timedelta(days=31) or end > today() + timedelta(days=366):
        raise LeaveError("วันที่ต้องอยู่ระหว่างย้อนหลัง 31 วันและล่วงหน้า 366 วัน กรุณาติดต่อผู้ดูแลสำหรับช่วงอื่น")


def _year(value: int) -> int:
    if 2400 <= value <= 2700:
        return value - 543
    if 2000 <= value <= 2200:
        return value
    raise LeaveError("ปีไม่ถูกต้อง กรุณาใช้ พ.ศ. 4 หลัก เช่น 2569")


def _make_date(day: str, month: str, year: str) -> date:
    try:
        return date(_year(int(year)), int(month), int(day))
    except (ValueError, TypeError) as exc:
        if isinstance(exc, LeaveError):
            raise
        raise LeaveError("วันที่ไม่ถูกต้อง ตัวอย่าง 17/9/2569") from exc


def parse_direct_request(text: str) -> tuple[str, date, date] | None:
    """Parse `แจ้งลา พักร้อน 17-20/9/2569` and full-date variants."""
    normalized = re.sub(r"\s+", " ", text.strip().replace("–", "-").replace("—", "-"))
    match = DIRECT_RE.fullmatch(normalized)
    if not match:
        return None
    kind = TYPE_WORDS[match.group("kind")]
    raw = match.group("dates")
    single = SINGLE_DATE_RE.fullmatch(raw)
    if single:
        start = end = _make_date(*single.groups())
    else:
        short = SHORT_RANGE_RE.fullmatch(raw)
        if short:
            d1, d2, month, year = short.groups()
            start = _make_date(d1, month, year)
            end = _make_date(d2, month, year)
        else:
            full = FULL_RANGE_RE.fullmatch(raw)
            if not full:
                raise LeaveError(
                    "รูปแบบวันที่ไม่ถูกต้อง ตัวอย่าง: แจ้งลา พักร้อน 17-20/9/2569 "
                    "หรือ แจ้งลา ลาป่วย 18/9/2569"
                )
            d1, m1, y1, d2, m2, y2 = full.groups()
            start = _make_date(d1, m1, y1)
            end = _make_date(d2, m2, y2)
    validate_dates(start, end)
    return kind, start, end


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
        existing = db.get(StaffLeaveRequest, request_id)
        if existing and (existing.employee_badge_number, existing.leave_type,
                         existing.date_from, existing.date_to) == (
                employee.badge_number, kind, start, end):
            return existing
        raise LeaveError("มีใบลาทับซ้อนในช่วงวันที่นี้แล้ว พิมพ์ ใบลาล่าสุด เพื่อตรวจสอบ") from exc
    db.refresh(row)
    return row


def cancel(db: Session, badge: str, request_id: str) -> StaffLeaveRequest:
    """Employee-initiated cancel.

    A still-pending request can always be cancelled. A request the employee
    never had reviewed — auto-recorded on confirmation via AUTO_REVIEWER —
    may also be cancelled, since no manager acted on it either; a request a
    human manager approved (reviewed_by != AUTO_REVIEWER) stays final, as
    today.
    """
    row = db.get(StaffLeaveRequest, request_id)
    if row is None or row.employee_badge_number != badge:
        raise LeaveError("ไม่พบใบลาของคุณ")
    if row.status == "cancelled":
        return row
    auto_recorded = row.status == "approved" and row.reviewed_by == AUTO_REVIEWER
    changed = db.query(StaffLeaveRequest).filter(
        StaffLeaveRequest.id == request_id,
        StaffLeaveRequest.employee_badge_number == badge,
        or_(
            StaffLeaveRequest.status == "pending",
            and_(StaffLeaveRequest.status == "approved",
                 StaffLeaveRequest.reviewed_by == AUTO_REVIEWER),
        ),
    ).update({
        "status": "cancelled", "version": StaffLeaveRequest.version + 1,
        "medical_certificate": None, "medical_certificate_content_type": None,
        "medical_certificate_sha256": None, "medical_certificate_uploaded_at": None,
        "updated_at": datetime.utcnow(),
    }, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise LeaveError("ยกเลิกได้เฉพาะใบลาที่ยังรออนุมัติ กรุณาติดต่อผู้อนุมัติ")
    db.query(StaffLeaveDay).filter(StaffLeaveDay.request_id == request_id).delete()
    if auto_recorded:
        # Auto-recording wrote EmployeeLeave rows directly (see decide());
        # remove ONLY the rows this request created — never a pre-existing
        # unrelated roster entry on another date.
        ref = reference(row)
        db.query(EmployeeLeave).filter(
            EmployeeLeave.employee_badge_number == badge,
            EmployeeLeave.date >= row.date_from, EmployeeLeave.date <= row.date_to,
            or_(EmployeeLeave.note == ref, EmployeeLeave.note.like(f"{ref}|%")),
        ).delete(synchronize_session=False)
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
    if decision == "approved" and medical_certificate_required(row) and not row.medical_certificate:
        raise LeaveError("ลาป่วยมากกว่า 3 วันต้องแนบรูปใบรับรองแพทย์ก่อนอนุมัติ")
    employee = db.query(Employee).filter(
        Employee.badge_number == row.employee_badge_number,
        Employee.is_active.is_(True), Employee.pending_approval.is_(False),
    ).first()
    if decision == "approved" and employee is None:
        raise LeaveError("พนักงานไม่มีสถานะใช้งาน ไม่สามารถอนุมัติได้")
    now = datetime.utcnow()
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


def _maybe_auto_approve(db: Session, row: StaffLeaveRequest) -> StaffLeaveRequest:
    """Auto-record a just-confirmed request the same way a manager approval
    would — the SAME installed ``decide`` (so staff_leave_options' half-day
    override still applies), reviewer AUTO_REVIEWER.

    Call this right after the step that creates/finalizes the pending
    request (full-day submit, or a half-day submit once its portion is
    set) — never from inside ``submit`` itself, which half-day submission
    also uses before its portion is applied.

    Any precondition ``decide`` enforces (a roster conflict, a still-missing
    required medical certificate) leaves the request pending exactly like
    today; a failed auto-decide never loses the submitted request.
    """
    if row.status != "pending" or not auto_approve_enabled():
        return row
    try:
        return decide(db, row.id, "approved", row.version, AUTO_REVIEWER)
    except LeaveError:
        db.rollback()
        db.expire_all()
        return db.get(StaffLeaveRequest, row.id)


def _medical_target(db: Session, employee: Employee) -> StaffLeaveRequest | None:
    return db.query(StaffLeaveRequest).filter(
        StaffLeaveRequest.employee_badge_number == employee.badge_number,
        StaffLeaveRequest.status == "pending",
        StaffLeaveRequest.leave_type == "sick",
        StaffLeaveRequest.medical_certificate.is_(None),
    ).order_by(StaffLeaveRequest.created_at.desc(), StaffLeaveRequest.id.desc()).first()


def _employee_for_event(db: Session, event: dict) -> Employee | None:
    source = event.get("source") or {}
    if not isinstance(source, dict) or source.get("type") != "user" or not source.get("userId"):
        return None
    return db.query(Employee).filter(
        Employee.line_user_id == source["userId"],
        Employee.is_active.is_(True), Employee.pending_approval.is_(False),
    ).first()


def is_leave_event(event: object, db: Session | None = None) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("type") == "postback":
        postback = event.get("postback")
        return (isinstance(postback, dict) and isinstance(postback.get("data"), str)
                and postback["data"].startswith(PREFIX))
    message = event.get("message")
    if event.get("type") != "message" or not isinstance(message, dict):
        return False
    if message.get("type") == "text" and isinstance(message.get("text"), str):
        text = message["text"].strip()
        return text in COMMANDS or text.startswith("แจ้งลา ") or text.startswith("ขอลา ")
    if message.get("type") == "image" and db is not None:
        employee = _employee_for_event(db, event)
        return employee is not None and _medical_target(db, employee) is not None
    return False


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
        raise RuntimeError(f"Leave reply failed: HTTP {response.status_code}")


def _receipt(row: StaffLeaveRequest) -> list[dict]:
    url = image_url(row)
    return [
        _text(f"{STATUSES[row.status]}\nเลขอ้างอิง {reference(row)}\n"
              "กดรูปแล้วเลือกส่งต่อไปยังกลุ่มได้ รูปเป็นสถานะ ณ เวลาที่สร้าง "
              "พิมพ์ ใบลาล่าสุด เพื่อขอรูปสถานะปัจจุบัน"),
        {"type": "image", "originalContentUrl": url, "previewImageUrl": url},
    ]


def _after_submit(row: StaffLeaveRequest) -> list[dict]:
    if medical_certificate_required(row) and not row.medical_certificate:
        return [_text(
            f"บันทึกใบลาในระบบพนักงานแล้ว เลขอ้างอิง {reference(row)}\n"
            f"ลาป่วย {calendar_days(row)} วัน ต้องแนบรูปใบรับรองแพทย์ก่อนอนุมัติ\n"
            "กรุณาส่งรูปใบรับรองแพทย์เป็นข้อความถัดไปในแชตนี้"
        )]
    messages = _receipt(row)
    if row.leave_type == "sick" and not row.medical_certificate:
        messages.append(_text(
            "ลาป่วยไม่เกิน 3 วันไม่บังคับใบรับรองแพทย์ หากมีสามารถส่งรูปในแชตนี้เพื่อแนบกับใบลาได้"
        ))
    return messages


def _review_message(employee: Employee, badge: str, request_id: str, kind: str,
                    start: date, end: date, expires: int | None = None) -> dict:
    required = kind == "sick" and (end - start).days + 1 > 3
    medical_line = (
        "\nลาป่วยมากกว่า 3 วัน: ต้องส่งรูปใบรับรองแพทย์หลังยืนยัน"
        if required else
        ("\nลาป่วยไม่เกิน 3 วัน: แนบใบรับรองแพทย์ได้ แต่ไม่บังคับ" if kind == "sick" else "")
    )
    return _text(
        f"ตรวจสอบก่อนส่งใบลา\n{employee.thai_name or employee.display_name}\n"
        f"{TYPES[kind]}\n{thai_date(start)} – {thai_date(end)} (พ.ศ.)\n"
        f"{(end - start).days + 1} วันตามปฏิทิน (ไม่ใช่ยอดสิทธิวันลา)"
        f"{medical_line}\n"
        "หลังส่งจะบันทึกในระบบพนักงานเป็นสถานะ รออนุมัติ", [
            _postback("ยืนยันส่งใบลา", action_data("submit", badge, request_id, kind,
                      start.isoformat(), end.isoformat(), expires)),
            {"type": "message", "label": "เริ่มใหม่", "text": "แจ้งลา"},
        ])


def _download_medical_certificate(message_id: str) -> tuple[bytes, str, str]:
    if not message_id:
        raise LeaveError("ไม่พบรูป กรุณาส่งรูปใบรับรองแพทย์ใหม่")
    response = requests.get(
        f"{staff_oa_service.LINE_DATA_API_BASE}/v2/bot/message/{message_id}/content",
        headers={"Authorization": f"Bearer {staff_oa_service.get_channel_access_token()}"},
        timeout=20,
    )
    if response.status_code // 100 != 2:
        raise LeaveError("ดาวน์โหลดรูปจาก LINE ไม่สำเร็จ กรุณาส่งรูปใหม่")
    raw = response.content
    if not raw or len(raw) > MAX_MEDICAL_DOWNLOAD:
        raise LeaveError("รูปใบรับรองแพทย์ใหญ่เกินไป กรุณาส่งรูปที่เล็กกว่า 12 MB")
    try:
        image = Image.open(BytesIO(raw))
        image.load()
        if image.width < 100 or image.height < 100:
            raise ValueError("too small")
        image.thumbnail((3200, 3200), Image.Resampling.LANCZOS)
        if image.mode not in ("RGB", "L"):
            background = Image.new("RGB", image.size, "white")
            if "A" in image.getbands():
                background.paste(image, mask=image.getchannel("A"))
            else:
                background.paste(image.convert("RGB"))
            image = background
        elif image.mode == "L":
            image = image.convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        normalized = output.getvalue()
    except Exception as exc:
        raise LeaveError("ไฟล์ที่ส่งไม่ใช่รูปภาพที่ระบบรองรับ กรุณาส่งเป็นรูปจาก LINE") from exc
    if len(normalized) > MAX_MEDICAL_STORED:
        raise LeaveError("รูปใบรับรองแพทย์ยังใหญ่เกินไป กรุณาถ่ายใหม่ให้เห็นเอกสารชัดเจน")
    digest = hashlib.sha256(normalized).hexdigest()
    return normalized, "image/jpeg", digest


def attach_medical_certificate(db: Session, row: StaffLeaveRequest,
                               content: bytes, content_type: str, digest: str) -> StaffLeaveRequest:
    if row.status != "pending" or row.leave_type != "sick":
        raise LeaveError("แนบใบรับรองแพทย์ได้เฉพาะใบลาป่วยที่รออนุมัติ")
    changed = db.query(StaffLeaveRequest).filter(
        StaffLeaveRequest.id == row.id,
        StaffLeaveRequest.status == "pending",
        StaffLeaveRequest.medical_certificate.is_(None),
    ).update({
        "medical_certificate": content,
        "medical_certificate_content_type": content_type,
        "medical_certificate_sha256": digest,
        "medical_certificate_uploaded_at": datetime.utcnow(),
        "version": StaffLeaveRequest.version + 1,
        "updated_at": datetime.utcnow(),
    }, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise LeaveError("ใบลานี้มีเอกสารแนบแล้วหรือสถานะเปลี่ยน กรุณาพิมพ์ ใบลาล่าสุด")
    db.commit()
    db.expire_all()
    return db.get(StaffLeaveRequest, row.id)


def handle_event(event: dict, db: Session) -> None:
    """Called ONLY after staff_oa verified the signature and claimed the event."""
    if event.get("mode") == "standby":
        return
    token = event.get("replyToken", "")
    source = event.get("source") or {}
    if not isinstance(source, dict) or source.get("type") != "user":
        _reply(token, [_text("กรุณาเปิดแชตส่วนตัวกับ HF ภายใน แล้วพิมพ์ แจ้งลา เพื่อรักษาข้อมูลส่วนตัว")])
        return
    employee = _employee_for_event(db, event)
    if employee is None:
        _reply(token, [_text("กรุณาผูก LINE กับบัญชีพนักงานและให้ผู้ดูแลอนุมัติก่อนแจ้งลา")])
        return
    try:
        message = event.get("message") or {}
        if event.get("type") == "message" and message.get("type") == "image":
            row = _medical_target(db, employee)
            if row is None:
                raise LeaveError("ไม่พบใบลาป่วยที่รอแนบใบรับรองแพทย์")
            content, content_type, digest = _download_medical_certificate(str(message.get("id") or ""))
            row = attach_medical_certificate(db, row, content, content_type, digest)
            # A certificate can be exactly what a sick leave over the
            # threshold was waiting on; re-run the same auto-decide path a
            # manager approval uses (through the installed `decide`, so a
            # half-day override still applies) so it gets recorded right
            # away instead of staying pending until someone reopens it.
            row = _maybe_auto_approve(db, row)
            messages = [_text(
                f"แนบใบรับรองแพทย์กับ {reference(row)} แล้ว และบันทึกไว้ในระบบพนักงาน"
            ), *_receipt(row)]
        else:
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
        direct = parse_direct_request(command) if command.startswith(("แจ้งลา ", "ขอลา ")) else None
        if direct:
            kind, start, end = direct
            return [_review_message(employee, badge, uuid4().hex, kind, start, end)]
        if command.startswith(("แจ้งลา ", "ขอลา ")):
            raise LeaveError(
                "พิมพ์ได้เช่น แจ้งลา พักร้อน 17-20/9/2569 หรือ แจ้งลา ลาป่วย 18/9/2569"
            )
        if command in ("แจ้งลา", "ขอลา"):
            request_id = uuid4().hex
            return [_text("แจ้งลา • เลือกประเภทลาและวันเริ่มลา\n"
                          "หรือพิมพ์ เช่น แจ้งลา พักร้อน 17-20/9/2569\n"
                          "ระบบรองรับลาเต็มวัน และจะบันทึกเมื่อกด ยืนยันส่งใบลา", [
                _picker(label, action_data("from", badge, request_id, kind), today(),
                        today() - timedelta(days=31), today() + timedelta(days=366))
                for kind, label in TYPES.items()
            ])]
        query = db.query(StaffLeaveRequest).filter(
            StaffLeaveRequest.employee_badge_number == badge)
        if command == "ยกเลิกใบลา":
            # Cancellable = still pending, or auto-recorded (never reviewed
            # by a manager) — see cancel().
            query = query.filter(or_(
                StaffLeaveRequest.status == "pending",
                and_(StaffLeaveRequest.status == "approved",
                     StaffLeaveRequest.reviewed_by == AUTO_REVIEWER),
            ))
        row = query.order_by(StaffLeaveRequest.created_at.desc(), StaffLeaveRequest.id.desc()).first()
        if row is None:
            return [_text("ไม่พบใบลา" + ("ที่ยกเลิกได้" if command == "ยกเลิกใบลา" else "ของคุณ"))]
        if command == "ยกเลิกใบลา":
            return [_text(f"ยกเลิกใบลา {thai_date(row.date_from)} – {thai_date(row.date_to)}?", [
                _postback("ยืนยันยกเลิกใบลา", action_data("cancel", badge, row.id))])]
        return _after_submit(row)

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
        if maximum > start:
            actions.append(_picker("ลาถึงวันที่", action_data("to", badge, request_id, kind,
                           start.isoformat(), expires=expires), start, start, maximum))
        actions.append(_postback("ลา 1 วัน", action_data("review", badge, request_id, kind,
                       start.isoformat(), start.isoformat(), expires)))
        return [_text(f"{TYPES[kind]} เริ่ม {thai_date(start)} (พ.ศ.)\nลาถึงวันที่ หรือเลือก ลา 1 วัน", actions)]
    start = date.fromisoformat(start_s)
    end = date.fromisoformat(params["date"] if verb == "to" else end_s)
    if verb == "submit":
        row = submit(db, employee, request_id, kind, start, end)
        return _after_submit(_maybe_auto_approve(db, row))
    if verb not in ("to", "review"):
        raise LeaveError("คำสั่งไม่ถูกต้อง กรุณาเริ่มใหม่")
    validate_dates(start, end)
    return [_review_message(employee, badge, request_id, kind, start, end, expires)]
