"""Employee-side leave maintenance for HF ภายใน.

The database keeps ``pending`` as an internal concurrency/review state, but the
employee-facing LINE flow deliberately does not present it as a status. Employees
may edit or cancel only the latest request that has not been reviewed yet.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.models.models import EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest

PORTION_LABELS = {"full": "เต็มวัน", "am": "ครึ่งวันเช้า", "pm": "ครึ่งวันบ่าย"}
_EDIT_VERB_RE = re.compile(
    r"^edit_(from|to|review|half_am|half_pm|submit_full|submit_am|submit_pm)_v(\d+)$"
)
_INSTALLED = False


def _latest_editable(db, badge: str) -> StaffLeaveRequest | None:
    return db.query(StaffLeaveRequest).filter(
        StaffLeaveRequest.employee_badge_number == badge,
        StaffLeaveRequest.status == "pending",
    ).order_by(StaffLeaveRequest.created_at.desc(), StaffLeaveRequest.id.desc()).first()


def _sanitize_text(text: str) -> str:
    replacements = (
        ("หลังส่งจะบันทึกในระบบพนักงานเป็นสถานะ รออนุมัติ",
         "หลังส่งจะบันทึกใบลาในระบบพนักงานทันที"),
        ("ยกเลิกได้เฉพาะใบลาที่ยังรออนุมัติ กรุณาติดต่อผู้อนุมัติ",
         "ใบลานี้ถูกตรวจแล้ว กรุณาติดต่อผู้จัดการหากต้องการเปลี่ยนแปลง"),
        ("แนบใบรับรองแพทย์ได้เฉพาะใบลาป่วยที่รออนุมัติ",
         "แนบใบรับรองแพทย์ได้เฉพาะใบลาป่วยที่ยังแก้ไขได้"),
        ("ที่รออนุมัติ", "ที่ยังแก้ไขได้"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    for message in messages:
        if isinstance(message, dict) and message.get("type") == "text":
            text = message.get("text")
            if isinstance(text, str):
                message["text"] = _sanitize_text(text)
    return messages


def _edit_start_message(service, row: StaffLeaveRequest) -> dict:
    badge = row.employee_badge_number
    current_portion = PORTION_LABELS.get(getattr(row, "leave_portion", "full"), "เต็มวัน")
    return service._text(
        f"แก้ไขใบลา {service.reference(row)}\n"
        f"ปัจจุบัน: {service.TYPES[row.leave_type]} • {current_portion}\n"
        f"{service.thai_date(row.date_from)} – {service.thai_date(row.date_to)}\n"
        "เลือกประเภทลาและวันเริ่มใหม่", [
            service._picker(
                label,
                service.action_data(
                    f"edit_from_v{row.version}", badge, row.id, kind,
                ),
                service.today(),
                service.today() - timedelta(days=31),
                service.today() + timedelta(days=366),
            )
            for kind, label in service.TYPES.items()
        ],
    )


def _edit_review(service, row: StaffLeaveRequest, kind: str, start: date, end: date,
                 portion: str, expected_version: int, expires: int | None = None) -> dict:
    days = 0.5 if portion in ("am", "pm") else (end - start).days + 1
    medical_line = ""
    if kind == "sick":
        medical_line = (
            "\nลาป่วยมากกว่า 3 วัน: ต้องส่งรูปใบรับรองแพทย์ใหม่หลังแก้ไข"
            if portion == "full" and days > 3
            else "\nลาป่วยไม่เกิน 3 วัน: แนบใบรับรองแพทย์ได้ แต่ไม่บังคับ"
        )
    return service._text(
        f"ตรวจสอบการแก้ไขใบลา\n{service.reference(row)}\n"
        f"{service.TYPES[kind]} • {PORTION_LABELS[portion]}\n"
        f"{service.thai_date(start)} – {service.thai_date(end)} (พ.ศ.)\n"
        f"{days:g} วัน{medical_line}", [
            service._postback(
                "ยืนยันแก้ไขใบลา",
                service.action_data(
                    f"edit_submit_{portion}_v{expected_version}",
                    row.employee_badge_number, row.id, kind,
                    start.isoformat(), end.isoformat(), expires,
                ),
            ),
            {"type": "message", "label": "ยกเลิกการแก้ไข", "text": "ใบลาล่าสุด"},
        ],
    )


def _edit_request(service, db, employee, request_id: str, expected_version: int,
                  kind: str, start: date, end: date, portion: str) -> StaffLeaveRequest:
    if kind not in service.TYPES or portion not in PORTION_LABELS:
        raise service.LeaveError("ข้อมูลใบลาไม่ถูกต้อง กรุณาเริ่มใหม่")
    if portion != "full" and start != end:
        raise service.LeaveError("ลาครึ่งวันต้องเป็นวันเดียว")
    service.validate_dates(start, end)

    row = db.get(StaffLeaveRequest, request_id)
    if row is None or row.employee_badge_number != employee.badge_number:
        raise service.LeaveError("ไม่พบใบลาของคุณ")

    target = (kind, start, end, portion)
    current = (
        row.leave_type, row.date_from, row.date_to,
        getattr(row, "leave_portion", "full"),
    )
    # LINE may redeliver a confirmation. The first successful edit increments
    # version once; a byte-identical replay is therefore safe and idempotent.
    if row.status == "pending" and row.version == expected_version + 1 and current == target:
        return row
    if row.status != "pending" or row.version != expected_version:
        raise service.LeaveError("ใบลานี้ถูกตรวจหรือเปลี่ยนแปลงแล้ว กรุณาพิมพ์ ใบลาล่าสุด")
    if current == target:
        return row

    if db.query(EmployeeLeave).filter(
        EmployeeLeave.employee_badge_number == employee.badge_number,
        EmployeeLeave.date >= start,
        EmployeeLeave.date <= end,
    ).first():
        raise service.LeaveError("ช่วงวันที่ใหม่มีวันลาในตารางงานแล้ว กรุณาตรวจสอบกับผู้ดูแล")

    try:
        # Remove this request's reservations inside the same transaction. Any
        # conflict while inserting the new dates rolls the whole edit back,
        # restoring both the old request values and old reservations.
        db.query(StaffLeaveDay).filter(
            StaffLeaveDay.request_id == row.id
        ).delete(synchronize_session=False)
        db.flush()

        row.leave_type = kind
        row.date_from = start
        row.date_to = end
        row.leave_portion = portion
        row.version += 1
        row.medical_certificate = None
        row.medical_certificate_content_type = None
        row.medical_certificate_sha256 = None
        row.medical_certificate_uploaded_at = None
        row.updated_at = datetime.utcnow()
        db.add_all([
            StaffLeaveDay(
                employee_badge_number=employee.badge_number,
                date=day,
                request_id=row.id,
            )
            for day in service._span(start, end)
        ])
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise service.LeaveError(
            "ช่วงวันที่ใหม่ทับซ้อนกับใบลาอื่น การแก้ไขถูกยกเลิกและข้อมูลเดิมยังอยู่"
        ) from exc
    db.refresh(row)
    return row


def install(service) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    service.COMMANDS.add("แก้ไขใบลา")
    original_messages = service._messages
    original_receipt = service._receipt
    original_cancel = service.cancel

    def receipt(row: StaffLeaveRequest) -> list[dict]:
        if row.status != "pending":
            return original_receipt(row)
        url = service.image_url(row)
        return [
            service._text(
                f"ส่งใบลาแล้ว\nเลขอ้างอิง {service.reference(row)}\n"
                "กดรูปแล้วเลือกส่งต่อไปยังกลุ่มได้ "
                "พิมพ์ ใบลาล่าสุด เพื่อขอรูปฉบับล่าสุด"
            ),
            {"type": "image", "originalContentUrl": url, "previewImageUrl": url},
        ]

    def messages(event, db, employee):
        badge = employee.badge_number
        if event.get("type") == "message":
            text = ((event.get("message") or {}).get("text") or "").strip()
            if text == "แก้ไขใบลา":
                row = _latest_editable(db, badge)
                if row is None:
                    return [service._text("ไม่มีใบลาที่แก้ไขได้")]
                return [_edit_start_message(service, row)]
            if text == "ยกเลิกใบลา":
                row = _latest_editable(db, badge)
                if row is None:
                    return [service._text("ไม่มีใบลาที่ยกเลิกได้")]
                portion = PORTION_LABELS.get(getattr(row, "leave_portion", "full"), "เต็มวัน")
                return [service._text(
                    f"ยกเลิกใบลา {service.reference(row)}?\n"
                    f"{service.TYPES[row.leave_type]} • {portion}\n"
                    f"{service.thai_date(row.date_from)} – {service.thai_date(row.date_to)}", [
                        service._postback(
                            "ยืนยันยกเลิกใบลา",
                            service.action_data("cancel", badge, row.id),
                        )
                    ],
                )]

        if event.get("type") == "postback":
            data = ((event.get("postback") or {}).get("data") or "")
            if isinstance(data, str) and data.startswith(service.PREFIX):
                verb, request_id, kind, start_s, end_s, expires = service._parse_action(data, badge)
                if verb == "cancel":
                    try:
                        return service._receipt(original_cancel(db, badge, request_id))
                    except service.LeaveError as exc:
                        raise service.LeaveError(_sanitize_text(str(exc))) from exc

                matched = _EDIT_VERB_RE.fullmatch(verb)
                if matched:
                    action, version_s = matched.groups()
                    expected_version = int(version_s)
                    row = db.get(StaffLeaveRequest, request_id)
                    if row is None or row.employee_badge_number != badge:
                        raise service.LeaveError("ไม่พบใบลาของคุณ")
                    submit_actions = {"submit_full", "submit_am", "submit_pm"}
                    if (action not in submit_actions
                            and (row.status != "pending" or row.version != expected_version)):
                        raise service.LeaveError(
                            "ใบลานี้ถูกตรวจหรือเปลี่ยนแปลงแล้ว กรุณาพิมพ์ ใบลาล่าสุด"
                        )
                    params = (event.get("postback") or {}).get("params") or {}
                    if action == "from":
                        start = date.fromisoformat(params["date"])
                        service.validate_dates(start, start)
                        maximum = min(
                            start + timedelta(days=service.MAX_DAYS - 1),
                            service.today() + timedelta(days=366),
                        )
                        actions = []
                        if maximum > start:
                            actions.append(service._picker(
                                "ลาถึงวันที่",
                                service.action_data(
                                    f"edit_to_v{expected_version}", badge, request_id, kind,
                                    start.isoformat(), expires=expires,
                                ),
                                start, start, maximum,
                            ))
                        actions.append(service._postback(
                            "ลา 1 วัน",
                            service.action_data(
                                f"edit_review_v{expected_version}", badge, request_id, kind,
                                start.isoformat(), start.isoformat(), expires,
                            ),
                        ))
                        for portion in ("am", "pm"):
                            actions.append(service._postback(
                                PORTION_LABELS[portion],
                                service.action_data(
                                    f"edit_half_{portion}_v{expected_version}",
                                    badge, request_id, kind,
                                    start.isoformat(), start.isoformat(), expires,
                                ),
                            ))
                        return [service._text(
                            f"{service.TYPES[kind]} เริ่ม {service.thai_date(start)} (พ.ศ.)\n"
                            "ลาถึงวันที่ หรือเลือกช่วงเวลา", actions,
                        )]

                    if kind not in service.TYPES:
                        raise service.LeaveError("ประเภทลาไม่ถูกต้อง")
                    start = date.fromisoformat(start_s)
                    if action == "to":
                        end = date.fromisoformat(params["date"])
                        portion = "full"
                    else:
                        end = date.fromisoformat(end_s)
                        portion = (
                            action.removeprefix("half_") if action.startswith("half_")
                            else action.removeprefix("submit_") if action.startswith("submit_")
                            else "full"
                        )
                    service.validate_dates(start, end)
                    if action in ("to", "review", "half_am", "half_pm"):
                        return [_edit_review(
                            service, row, kind, start, end, portion,
                            expected_version, expires,
                        )]
                    if action in submit_actions:
                        updated = _edit_request(
                            service, db, employee, request_id, expected_version,
                            kind, start, end, portion,
                        )
                        return service._after_submit(updated)

        try:
            return _sanitize_messages(original_messages(event, db, employee))
        except service.LeaveError as exc:
            raise service.LeaveError(_sanitize_text(str(exc))) from exc

    service._receipt = receipt
    service._messages = messages
