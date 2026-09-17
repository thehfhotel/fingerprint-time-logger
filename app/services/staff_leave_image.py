"""Deterministic Thai PNG. Deliberately excludes reasons, medical data and internal IDs."""
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import unicodedata

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import object_session

from app.models.staff_leave import StaffLeaveRequest
from app.services.staff_leave import BKK, TYPES, thai_date

FONT_DIR = Path("/usr/share/fonts/opentype/tlwg")
PORTION_LABELS = {"full": "เต็มวัน", "am": "ครึ่งวันเช้า", "pm": "ครึ่งวันบ่าย"}
_STATUS_COLORS = {
    "recorded": "accent", "partial": "accent",
    "rejected": "danger", "cancelled": "muted", "cancelled_roster": "muted",
}


@lru_cache(maxsize=16)
def _font(size: int, bold: bool = False):
    name = "Loma-Bold.otf" if bold else "Loma.otf"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _wrap(draw, text: str, font, width: int) -> list[str]:
    clusters: list[str] = []
    for char in text.replace("\n", " "):
        if unicodedata.category(char).startswith("M") and clusters:
            clusters[-1] += char
        elif not unicodedata.category(char).startswith("C"):
            clusters.append(char)
    lines, line = [], ""
    for cluster in clusters:
        if line and draw.textlength(line + cluster, font=font) > width:
            lines.append(line)
            line = cluster
        else:
            line += cluster
    return lines + [line or "—"]


def _date_range(start, end) -> tuple:
    from datetime import timedelta
    return tuple(start + timedelta(days=n) for n in range((end - start).days + 1))


def _effective_for_row(row: StaffLeaveRequest):
    """The roster is the source of truth for what a leave receipt shows
    (see ``app.services.staff_leave_roster``). When ``row`` is attached to a
    live session, compute its real effective state; a detached/transient row
    (no session — e.g. a plain object built in a test) falls back to a
    best-effort approximation from the row's own fields only."""
    from app.services import staff_leave_roster

    db = object_session(row)
    if db is not None:
        return staff_leave_roster.effective_state(db, row)
    if row.status == "cancelled":
        status = ("cancelled_roster" if row.reviewed_by == staff_leave_roster.ROSTER_ADMIN_REVIEWER
                  else "cancelled")
        dates: tuple = ()
    elif row.status in ("pending", "rejected"):
        status = row.status
        dates = _date_range(row.date_from, row.date_to)
    else:  # "approved", no session to check the roster with
        status = "recorded"
        dates = _date_range(row.date_from, row.date_to)
    return staff_leave_roster.EffectiveLeave(
        status=status, dates=dates,
        date_from=dates[0] if dates else None, date_to=dates[-1] if dates else None,
        leave_type=row.leave_type, portion=getattr(row, "leave_portion", "full"),
        source="line", request=row,
    )


def _dates_text(effective) -> str:
    if effective.status == "cancelled_roster":
        return "ไม่มีวันลาคงเหลือในตารางงาน"
    dates = effective.dates
    if not dates and effective.request is not None:
        dates = (effective.request.date_from, effective.request.date_to)
    if not dates:
        return "—"
    if effective.status == "partial":
        return ", ".join(thai_date(d) for d in dates)
    if dates[0] == dates[-1]:
        return thai_date(dates[0])
    return f"{thai_date(dates[0])} – {thai_date(dates[-1])}"


def _duration_text(effective) -> str:
    if effective.status == "cancelled_roster":
        return "ไม่มีวันลาคงเหลือในตารางงาน"
    if effective.portion in ("am", "pm"):
        return f"0.5 วัน • {PORTION_LABELS.get(effective.portion, effective.portion)}"
    days = len(effective.dates) if effective.dates else (
        (effective.request.date_to - effective.request.date_from).days + 1
        if effective.request else 0
    )
    unit = "วันตามปฏิทิน" if effective.status != "partial" else "วันคงเหลือในตารางงาน"
    return f"{days} {unit} • เต็มวัน"


def render_png(row: StaffLeaveRequest, rendered_at: datetime | None = None) -> bytes:
    """Legacy row-only entry point. Kept working by computing the roster's
    effective state internally (see ``_effective_for_row``)."""
    return render_effective_png(_effective_for_row(row), rendered_at)


def render_effective_png(effective, rendered_at: datetime | None = None) -> bytes:
    row = effective.request
    image = Image.new("RGB", (1080, 2400), "white")
    draw = ImageDraw.Draw(image)
    ink, muted, accent = "#17352F", "#52655F", "#17694F"
    draw.rectangle((0, 0, 1080, 214), fill=ink)
    draw.text((70, 34), "HF ภายใน", font=_font(54, True), fill="white")
    draw.text((70, 112), "ใบแจ้งลา / LEAVE REQUEST", font=_font(36), fill="white")
    y = 260

    # ``pending`` remains an internal review/concurrency state only. Employees
    # should not see it as a status on the shareable leave image. Final states
    # still appear because they materially change the meaning of a
    # previously shared receipt — including a roster edit changing it after
    # the fact (see EFFECTIVE_LABELS' "_roster"-suffixed variants).
    if effective.status != "pending":
        color_key = _STATUS_COLORS.get(effective.status, "muted")
        fill = {"accent": accent, "danger": "#A13030", "muted": muted}[color_key]
        draw.rounded_rectangle((70, y, 1010, y + 100), radius=16, fill=fill)
        draw.text((100, y + 12), effective.label, font=_font(48, True), fill="white")
        y += 132

    def block(label: str, value: str):
        nonlocal y
        draw.text((70, y), label, font=_font(29), fill=muted)
        y += 45
        for line in _wrap(draw, value, _font(43, True), 940):
            draw.text((70, y), line, font=_font(43, True), fill=ink)
            y += 61
        y += 22

    block("ชื่อพนักงาน", row.employee_name)
    property_name = {"HF": "The Harbour Front Hotel", "HF_VILLE": "HF Ville"}.get(
        row.location, row.location or "ไม่ระบุสาขา")
    block("แผนก / สาขา", " • ".join(filter(None, (row.department, property_name))))
    block("ประเภทการลา", TYPES.get(effective.leave_type, effective.leave_type))
    block("ช่วงวันที่ลา (พ.ศ.)", _dates_text(effective))
    block("ระยะเวลาการลา", _duration_text(effective))
    draw.line((70, y, 1010, y), fill="#D8E4DD", width=2)
    y += 28

    stamped = rendered_at or datetime.now(timezone.utc)
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    stamped = stamped.astimezone(BKK)
    draw.text(
        (70, y),
        f"สร้างจาก HF ภายใน • {thai_date(stamped.date())} {stamped:%H:%M} น.",
        font=_font(26), fill=muted,
    )
    y += 40

    if y + 60 > image.height:
        raise ValueError("Leave image exceeds layout height")
    output = BytesIO()
    image.crop((0, 0, 1080, y + 60)).save(output, format="PNG", optimize=True)
    png = output.getvalue()
    if len(png) > 1_000_000:
        raise ValueError("Leave image exceeds LINE preview budget")
    return png
