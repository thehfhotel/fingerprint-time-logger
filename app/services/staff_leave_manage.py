"""Employee-side leave maintenance for HF ภายใน.

Employees choose a leave by readable type/date details. Internal request UUIDs
remain signed inside LINE postbacks and are never presented as something a staff
member must read, remember, or type.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session

from app.models.models import EmployeeLeave
from app.models.staff_leave import StaffLeaveDay, StaffLeaveRequest
from app.services import staff_leave
from app.services import staff_leave_roster

PORTION_LABELS = {"full": "เต็มวัน", "am": "ครึ่งวันเช้า", "pm": "ครึ่งวันบ่าย"}
MAX_CHOICES = 10
_EDIT_VERB_RE = re.compile(
    r"^edit_(from|to|review|half_am|half_pm|submit_full|submit_am|submit_pm)_v(\d+)$"
)
_PICK_VERB_RE = re.compile(r"^pick_(edit|cancel)_v(\d+)$")
_CANCEL_VERB_RE = re.compile(r"^cancel_v(\d+)$")
_INSTALLED = False


def _editable_rows(db, badge: str, mode: str = "edit",
                   limit: int = MAX_CHOICES) -> list[StaffLeaveRequest]:
    """Rows offered for edit/cancel selection.

    "edit" stays pending-only — editing an already-recorded leave is out of
    scope; cancel-and-refile instead. "cancel" also offers a request that was
    auto-recorded on confirmation and never reviewed by a manager (see
    ``staff_leave.AUTO_REVIEWER``, read from the service module at call time
    so a test's monkeypatch or a live env change is honored). A
    manager-approved row (``reviewed_by`` anything else) is never offered.
    Once recorded, offering to cancel additionally requires the roster's
    EFFECTIVE state to still be pending/recorded/partial — see
    ``_is_cancellable`` — so a request the roster already ended (every one
    of its roster rows removed on shifts-admin) drops out of the picker too.
    """
    query = db.query(StaffLeaveRequest).filter(
        StaffLeaveRequest.employee_badge_number == badge,
    )
    if mode == "cancel":
        query = query.filter(or_(
            StaffLeaveRequest.status == "pending",
            and_(
                StaffLeaveRequest.status == "approved",
                StaffLeaveRequest.reviewed_by == staff_leave.AUTO_REVIEWER,
            ),
        ))
    else:
        query = query.filter(StaffLeaveRequest.status == "pending")
    rows = query.order_by(
        StaffLeaveRequest.created_at.desc(), StaffLeaveRequest.id.desc()
    ).limit(limit).all()
    if mode == "cancel":
        rows = [r for r in rows if _is_cancellable(db, r, r.version)]
    return rows


def _latest_editable(db, badge: str) -> StaffLeaveRequest | None:
    rows = _editable_rows(db, badge, "edit", 1)
    return rows[0] if rows else None


def _is_cancellable(db, row: StaffLeaveRequest | None, expected_version: int) -> bool:
    """Cancellable = still pending, or auto-recorded (never reviewed by a
    manager) AND the roster's effective state for it is still
    pending/recorded/partial — never once the roster itself has ended it
    (``effective_state`` status "cancelled"/"cancelled_roster") or a manager
    actually approved it."""
    if row is None or row.version != expected_version:
        return False
    if row.status == "pending":
        return True
    if row.status != "approved" or row.reviewed_by != staff_leave.AUTO_REVIEWER:
        return False
    effective = staff_leave_roster.effective_state(db, row)
    return effective.status in ("recorded", "partial")


def _portion(row: StaffLeaveRequest) -> str:
    return PORTION_LABELS.get(getattr(row, "leave_portion", "full"), "เต็มวัน")


def _date_range(service, row: StaffLeaveRequest) -> str:
    if row.date_from == row.date_to:
        return service.thai_date(row.date_from)
    return f"{service.thai_date(row.date_from)} – {service.thai_date(row.date_to)}"


def _row_detail(service, row: StaffLeaveRequest) -> str:
    return f"{service.TYPES[row.leave_type]} • {_portion(row)}\n{_date_range(service, row)} (พ.ศ.)"


def _selection_message(service, rows: list[StaffLeaveRequest], mode: str) -> dict:
    if mode not in ("edit", "cancel"):
        raise ValueError("unsupported leave selection mode")
    title = "เลือกใบลาที่ต้องการแก้ไข" if mode == "edit" else "เลือกใบลาที่ต้องการยกเลิก"
    action_word = "แก้ใบที่" if mode == "edit" else "ยกเลิกใบที่"
    lines = [title, ""]
    actions = []
    for index, row in enumerate(rows, start=1):
        lines.append(
            f"{index}. {service.TYPES[row.leave_type]} • {_portion(row)}\n"
            f"   {_date_range(service, row)}"
        )
        actions.append(service._postback(
            f"{action_word} {index}",
            service.action_data(
                f"pick_{mode}_v{row.version}", row.employee_badge_number, row.id,
            ),
        ))
    lines.extend(("", "แตะปุ่มด้านล่างได้เลย ไม่ต้องพิมพ์เลขรายการ"))
    return service._text("\n".join(lines), actions)


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
    return service._text(
        f"กำลังแก้ไขใบลา\n{_row_detail(service, row)}\n\n"
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


def _cancel_confirm_message(service, row: StaffLeaveRequest) -> dict:
    return service._text(
        f"ยืนยันยกเลิกใบลานี้?\n{_row_detail(service, row)}", [
            service._postback(
                "ยืนยันยกเลิก",
                service.action_data(
                    f"cancel_v{row.version}", row.employee_badge_number, row.id,
                ),
            ),
            {"type": "message", "label": "ไม่ยกเลิก", "text": "ใบลาล่าสุด"},
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
        f"ตรวจสอบการแก้ไขใบลา\n"
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
    if row.status == "pending" and row.version == expected_version + 1 and current == target:
        return row
    if row.status != "pending" or row.version != expected_version:
        raise service.LeaveError("ใบลานี้ถูกตรวจหรือเปลี่ยนแปลงแล้ว กรุณาเลือกใบลาใหม่")
    if current == target:
        return row

    if db.query(EmployeeLeave).filter(
        EmployeeLeave.employee_badge_number == employee.badge_number,
        EmployeeLeave.date >= start,
        EmployeeLeave.date <= end,
    ).first():
        raise service.LeaveError("ช่วงวันที่ใหม่มีวันลาในตารางงานแล้ว กรุณาตรวจสอบกับผู้ดูแล")

    try:
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
    original_cancel = service.cancel

    def _heading(row: StaffLeaveRequest) -> str:
        if row.status == "pending":
            return "ส่งใบลาแล้ว"
        db = object_session(row)
        if db is None:
            return service.STATUSES.get(row.status, row.status)
        return staff_leave_roster.effective_state(db, row).label

    def receipt(row: StaffLeaveRequest) -> list[dict]:
        url = service.image_url(row)
        heading = _heading(row)
        return [
            service._text(
                f"{heading}\n{_row_detail(service, row)}\n"
                "กดรูปแล้วเลือกส่งต่อไปยังกลุ่มได้ "
                "พิมพ์ ใบลาล่าสุด เพื่อขอรูปฉบับล่าสุด"
            ),
            {"type": "image", "originalContentUrl": url, "previewImageUrl": url},
        ]

    def after_submit(row: StaffLeaveRequest) -> list[dict]:
        if service.medical_certificate_required(row) and not row.medical_certificate:
            return [service._text(
                f"บันทึกใบลาในระบบพนักงานแล้ว\n{_row_detail(service, row)}\n"
                f"ลาป่วย {service.calendar_days(row):g} วัน ต้องแนบรูปใบรับรองแพทย์ก่อนอนุมัติ\n"
                "กรุณาส่งรูปใบรับรองแพทย์เป็นข้อความถัดไปในแชตนี้"
            )]
        messages = receipt(row)
        if row.leave_type == "sick" and not row.medical_certificate:
            messages.append(service._text(
                "ลาป่วยไม่เกิน 3 วันไม่บังคับใบรับรองแพทย์ "
                "หากมีสามารถส่งรูปในแชตนี้เพื่อแนบกับใบลาได้"
            ))
        return messages

    def messages(event, db, employee):
        badge = employee.badge_number
        if event.get("type") == "message":
            text = ((event.get("message") or {}).get("text") or "").strip()
            if text in ("แก้ไขใบลา", "ยกเลิกใบลา"):
                mode = "edit" if text == "แก้ไขใบลา" else "cancel"
                rows = _editable_rows(db, badge, mode)
                if not rows:
                    label = "แก้ไข" if text == "แก้ไขใบลา" else "ยกเลิก"
                    return [service._text(f"ไม่มีใบลาที่{label}ได้")]
                return [_selection_message(service, rows, mode)]

        if event.get("type") == "postback":
            data = ((event.get("postback") or {}).get("data") or "")
            if isinstance(data, str) and data.startswith(service.PREFIX):
                verb, request_id, kind, start_s, end_s, expires = service._parse_action(data, badge)
                row = db.get(StaffLeaveRequest, request_id)

                pick = _PICK_VERB_RE.fullmatch(verb)
                if pick:
                    mode, version_s = pick.groups()
                    expected_version = int(version_s)
                    if row is None or row.employee_badge_number != badge:
                        raise service.LeaveError("ไม่พบใบลาของคุณ")
                    if mode == "edit":
                        offerable = row.status == "pending" and row.version == expected_version
                    else:
                        offerable = _is_cancellable(db, row, expected_version)
                    if not offerable:
                        raise service.LeaveError("ใบลานี้เปลี่ยนแปลงแล้ว กรุณาเลือกใบลาใหม่")
                    return [
                        _edit_start_message(service, row)
                        if mode == "edit" else _cancel_confirm_message(service, row)
                    ]

                cancel_match = _CANCEL_VERB_RE.fullmatch(verb)
                if cancel_match:
                    expected_version = int(cancel_match.group(1))
                    if row is None or row.employee_badge_number != badge:
                        raise service.LeaveError("ไม่พบใบลาของคุณ")
                    if row.status == "cancelled" and row.version == expected_version + 1:
                        return receipt(row)
                    if not _is_cancellable(db, row, expected_version):
                        raise service.LeaveError("ใบลานี้เปลี่ยนแปลงแล้ว กรุณาเลือกใบลาใหม่")
                    try:
                        return receipt(original_cancel(db, badge, request_id))
                    except service.LeaveError as exc:
                        raise service.LeaveError(_sanitize_text(str(exc))) from exc

                matched = _EDIT_VERB_RE.fullmatch(verb)
                if matched:
                    action, version_s = matched.groups()
                    expected_version = int(version_s)
                    if row is None or row.employee_badge_number != badge:
                        raise service.LeaveError("ไม่พบใบลาของคุณ")
                    submit_actions = {"submit_full", "submit_am", "submit_pm"}
                    if (action not in submit_actions
                            and (row.status != "pending" or row.version != expected_version)):
                        raise service.LeaveError("ใบลานี้เปลี่ยนแปลงแล้ว กรุณาเลือกใบลาใหม่")
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
                        # A no-op unless the edited request is still pending
                        # and now clears every precondition (e.g. a shortened
                        # sick leave that no longer needs a certificate).
                        updated = service._maybe_auto_approve(db, updated)
                        return service._after_submit(updated)

        try:
            return _sanitize_messages(original_messages(event, db, employee))
        except service.LeaveError as exc:
            raise service.LeaveError(_sanitize_text(str(exc))) from exc

    service._receipt = receipt
    service._after_submit = after_submit
    service._messages = messages
