"""
Thailand public-holiday presets for the holiday-config UI.

2026 (B.E. 2569) is the official Cabinet/BOT calendar including the
observed/substitution days. For any year without a curated entry we return
only the FIXED-date national holidays — the lunar Buddhist days (Makha /
Visakha / Asarnha Bucha) shift every year and are NOT computed here, so
those must be added manually for other years.
"""
from __future__ import annotations


# Curated, accurate per-year lists: (MM-DD, Thai name).
_CURATED: dict[int, list[tuple[str, str]]] = {
    2026: [
        ("01-01", "วันขึ้นปีใหม่"),
        ("01-02", "วันหยุดพิเศษ"),
        ("03-03", "วันมาฆบูชา"),
        ("04-06", "วันจักรี"),
        ("04-13", "วันสงกรานต์"),
        ("04-14", "วันสงกรานต์"),
        ("04-15", "วันสงกรานต์"),
        ("05-01", "วันแรงงานแห่งชาติ"),
        ("05-04", "วันฉัตรมงคล"),
        ("05-31", "วันวิสาขบูชา"),
        ("06-01", "ชดเชยวันวิสาขบูชา"),
        ("06-03", "วันเฉลิมพระชนมพรรษาสมเด็จพระนางเจ้าฯ พระบรมราชินี"),
        ("07-28", "วันเฉลิมพระชนมพรรษาพระบาทสมเด็จพระเจ้าอยู่หัว"),
        ("07-29", "วันอาสาฬหบูชา"),
        ("08-12", "วันแม่แห่งชาติ"),
        ("10-13", "วันคล้ายวันสวรรคต ร.9"),
        ("10-23", "วันปิยมหาราช"),
        ("12-05", "วันพ่อแห่งชาติ"),
        ("12-07", "ชดเชยวันพ่อแห่งชาติ"),
        ("12-10", "วันรัฐธรรมนูญ"),
        ("12-31", "วันสิ้นปี"),
    ],
}

# Fixed-date national holidays (MM-DD, name) — same calendar date every year.
_FIXED: list[tuple[str, str]] = [
    ("01-01", "วันขึ้นปีใหม่"),
    ("04-06", "วันจักรี"),
    ("04-13", "วันสงกรานต์"),
    ("04-14", "วันสงกรานต์"),
    ("04-15", "วันสงกรานต์"),
    ("05-01", "วันแรงงานแห่งชาติ"),
    ("05-04", "วันฉัตรมงคล"),
    ("06-03", "วันเฉลิมพระชนมพรรษาสมเด็จพระนางเจ้าฯ พระบรมราชินี"),
    ("07-28", "วันเฉลิมพระชนมพรรษาพระบาทสมเด็จพระเจ้าอยู่หัว"),
    ("08-12", "วันแม่แห่งชาติ"),
    ("10-13", "วันคล้ายวันสวรรคต ร.9"),
    ("10-23", "วันปิยมหาราช"),
    ("12-05", "วันพ่อแห่งชาติ"),
    ("12-10", "วันรัฐธรรมนูญ"),
    ("12-31", "วันสิ้นปี"),
]


def thai_holidays_for_year(year: int) -> list[dict]:
    """Preset Thai public holidays for ``year`` as [{date, name}], sorted.

    Uses the curated list when available, else the fixed-date holidays only.
    """
    entries = _CURATED.get(year, _FIXED)
    out = [{"date": f"{year:04d}-{md}", "name": name} for md, name in entries]
    out.sort(key=lambda h: h["date"])
    return out
