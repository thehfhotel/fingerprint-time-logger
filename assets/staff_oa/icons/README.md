# HF Internal approved Rich Menu icons

These seven PNGs are pixel-exact crops of the owner-approved **HF Internal**
icon sheet, supplied **2026-09-17 22:23**
(`assets/staff_oa/source/hf_internal_icon_sheet_2026-09-17.png`, 1536x1024
RGB, sha256 `f6f8b61e1554b5e981f6f12136ad74774da438795d2f5d8bd8b2e7150ffbb93e`
— pinned in `crops.json` and re-verified by `test_staff_oa_icon_sheet.py`
on every run). An earlier sheet supplied 18:36 the same day was superseded
before it ever shipped; only the 22:23 sheet is committed.

## Extraction

```bash
python scripts/split_staff_oa_icon_sheet.py
```

`scripts/split_staff_oa_icon_sheet.py` is a manifest-driven cropper, not an
icon generator: for each entry in `crops.json` it does
`sheet.convert("RGBA").crop(box)` against the pinned source file, then adds
a rounded-corner alpha channel (`corner_radius`, computed arithmetically —
see `rounded_mask()`) so each pastel tile keeps its sheet shape once pasted
onto a menu card. RGB pixels are never touched — no redraw, no recolour, no
filter, no resize beyond the crop itself. `crops.json`
(`format: "hf-staff-oa-icon-crops-v2"`) pins the source file's sha256 and
size and refuses to crop anything else, and records each crop's `box`
(left, top, right, bottom — PIL semantics, right/bottom exclusive),
`corner_radius` and the sheet's own Thai `sheet_label` for that tile.

## Canonical assets

| key | file | sheet label |
| --- | --- | --- |
| `leave` | `leave_calendar.png` | แจ้งลา |
| `time` | `time_clock.png` | ลงเวลา |
| `announcement` | `announcement_megaphone.png` | ประกาศ |
| `handbook` | `handbook_document.png` | คู่มือพนักงาน |
| `maintenance` | `maintenance_tools.png` | แจ้งซ่อม |
| `contacts` | `team_contacts.png` | ติดต่อทีมงาน |
| `suggestions` | `suggestions_chat.png` | ข้อเสนอแนะ |

There is no `staff_meal` asset any more — the 22:23 sheet has seven tiles,
not eight, and `meal` is gone from both `ICON_ASSETS` and
`GLYPH_ASSET_KEYS` in `app/services/staff_oa_images.py`.

## Current MenuButton glyph -> asset table

`app/services/staff_oa_menu.py`'s `MENU_BUTTONS` was built against the old
programmatic glyph set and hasn't been redesigned around these seven
tiles, so several buttons wear an approved asset that is only an
approximate match for their Thai label. Every mapping below is
owner-confirmed 2026-09-17 — revisit if the tiles themselves are ever
redesigned.

| button (Thai label) | glyph | asset (key) | fit |
| --- | --- | --- | --- |
| แจ้งซ่อม / จัดการงานซ่อม | `wrench` | แจ้งซ่อม tools (`maintenance`) | exact |
| งานซ่อมค้าง | `wrench_list` | แจ้งซ่อม tools (`maintenance`) | reasonable — tools appears twice, on the reception and housekeeping menus |
| แม่บ้าน | `broom` | ติดต่อทีมงาน team (`contacts`) | reasonable |
| สถานะห้อง | `clipboard` | คู่มือพนักงาน document (`handbook`) | reasonable |
| สต๊อกของ | `box` | คู่มือพนักงาน document (`handbook`) | weak |
| รับของมาส่ง | `tray` | ลงเวลา check-in clock (`time`) | weak |
| รายงานแม่บ้าน | `photo_sheet` | ข้อเสนอแนะ chat (`suggestions`) | weak |

Any glyph not in this table (the retired `clock`/`receipt`/`baht`/`bell`/
`meal` glyphs, or anything unrecognised) fails closed with
`ApprovedAssetError` rather than falling back to a blank tile.

## Rules

- Never redraw, synthesize, recolour, filter or sharpen approved artwork in
  code. The renderer may only scale an approved PNG (LANCZOS) and
  alpha-paste it.
- Do not modify the seven `*.png` files or `crops.json` here, or the
  source sheet, by hand — regenerate them from the sheet with
  `scripts/split_staff_oa_icon_sheet.py` if the manifest ever changes.
- Renderer changes go through PR + CI/CD; production LINE synchronization
  is performed by the post-deploy release job.
- The renderer fails closed (`ApprovedAssetError`) on an unknown glyph or a
  missing/unreadable/non-PNG asset — never a silent blank tile or a
  legacy drawn-glyph fallback.
