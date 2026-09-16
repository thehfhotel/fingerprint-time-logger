"""Deterministic Thai PNG. Deliberately excludes reasons, medical data and LINE IDs."""
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import unicodedata

from PIL import Image, ImageDraw, ImageFont

from app.models.staff_leave import StaffLeaveRequest
from app.services.staff_leave import BKK, STATUSES, TYPES, reference, thai_date

FONT_DIR = Path("/usr/share/fonts/opentype/tlwg")


@lru_cache(maxsize=16)
def _font(size: int, bold: bool = False):
    # Installed explicitly by Dockerfile. Do not silently emit tofu if missing.
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


def render_png(row: StaffLeaveRequest, rendered_at: datetime | None = None) -> bytes:
    image = Image.new("RGB", (1080, 2400), "white")
    draw = ImageDraw.Draw(image)
    ink, muted, accent = "#17352F", "#52655F", "#17694F"
    draw.rectangle((0, 0, 1080, 214), fill=ink)
    draw.text((70, 34), "HF ภายใน", font=_font(54, True), fill="white")
    draw.text((70, 112), "ใบแจ้งลา / LEAVE REQUEST", font=_font(36), fill="white")
    y = 260
    status_colors = {"pending": "#946900", "approved": accent,
                     "rejected": "#A13030", "cancelled": muted}
    draw.rounded_rectangle((70, y, 1010, y + 100), radius=16,
                           fill=status_colors[row.status])
    draw.text((100, y + 12), STATUSES[row.status], font=_font(48, True), fill="white")
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
    block("ประเภทการลา", TYPES[row.leave_type])
    block("ช่วงวันที่ลา (พ.ศ.)", f"{thai_date(row.date_from)} – {thai_date(row.date_to)}")
    block("ระยะเวลาตามช่วงวันที่", f"{(row.date_to - row.date_from).days + 1} วันตามปฏิทิน • เต็มวัน")
    draw.line((70, y, 1010, y), fill="#D8E4DD", width=2)
    y += 28
    stamped = rendered_at or datetime.now(timezone.utc)
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    created = row.created_at.replace(tzinfo=timezone.utc).astimezone(BKK)
    details = [reference(row),
               f"ส่งคำขอ {thai_date(created.date())} เวลา {created:%H:%M} น."]
    if row.reviewed_at:
        reviewed = row.reviewed_at.replace(tzinfo=timezone.utc).astimezone(BKK)
        details.append(f"พิจารณา {thai_date(reviewed.date())} เวลา {reviewed:%H:%M} น.")
    stamped = stamped.astimezone(BKK)
    details += [f"ภาพสถานะ ณ {thai_date(stamped.date())} เวลา {stamped:%H:%M} น.",
                "จำนวนวันข้างต้นไม่ใช่ยอดสิทธิวันลา", "รูปนี้ไม่แสดงเหตุผลส่วนตัวหรือเอกสารแพทย์",
                "ตรวจสอบสถานะปัจจุบัน: พิมพ์ ใบลาล่าสุด ใน HF ภายใน"]
    if row.status == "pending":
        details.append("ยังไม่ได้รับอนุมัติ • ไม่มีการสร้างลายเซ็นแทนผู้อนุมัติ")
    for text in details:
        for line in _wrap(draw, text, _font(26), 940):
            draw.text((70, y), line, font=_font(26), fill=muted)
            y += 40
    if y + 60 > image.height:
        raise ValueError("Leave image exceeds layout height")
    output = BytesIO()
    image.crop((0, 0, 1080, y + 60)).save(output, format="PNG", optimize=True)
    png = output.getvalue()
    if len(png) > 1_000_000:
        raise ValueError("Leave image exceeds LINE preview budget")
    return png
