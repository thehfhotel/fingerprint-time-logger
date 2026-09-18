# Leave data surfaces

HF ภายใน, `/fingerprintlogs/v2/shifts-admin`, and `/fingerprintlogs/v2/monthly`
share `EmployeeLeave` as the authoritative approved-leave record.

## Data contract

- `leave_type`: `vacation`, `personal`, `sick`, `public_holiday`
- `leave_portion`: API field `full`, `am`, `pm`
- Half-day compatibility is stored in `EmployeeLeave.note` as `|half=am` or
  `|half=pm`; the admin API removes that marker from the public `note` field and
  exposes `leave_portion` explicitly.
- `public_holiday` is filable both ways: from the admin's shared
  `PublicHoliday` (company-wide) table AND from HF ภายใน's `แจ้งลา` LINE
  flow, which used to track a separate `day_off` code. The two were merged
  2026-09-18 (migration `20260918_000000_merge_day_off_into_public_holiday`)
  because they meant the same thing — an employee using their own
  rest/holiday day. `staff_leave.TYPES["public_holiday"]` is the LINE label
  (`ใช้วันหยุดนักขัตฤกษ์`); admin surfaces (leave-type legend, leave board,
  roster cell picker, monthly report) show the shorter `วันหยุดนักขัตฤกษ์`.
  Typed keywords `ใช้วันหยุด` / `วันหยุด` / `นักขัตฤกษ์` /
  `วันหยุดนักขัตฤกษ์` / `ใช้วันหยุดนักขัตฤกษ์` all map to `public_holiday`.
- No second leave table or sync job is required. An approval in HF ภายใน writes
  `EmployeeLeave`, and both ERP pages read that same row.
- In auto-record mode (the default — see `docs/staff-leave.md`), a
  LINE-confirmed leave request writes its `EmployeeLeave` row(s) immediately on
  the employee's final confirmation, with no separate manager-approval step in
  between. The write path and one-transaction guarantee are identical to a
  manager approval; only the reviewer marker differs (`auto:staff-oa` instead
  of a manager's email — never shown to shifts-admin/monthly, which only ever
  read `EmployeeLeave`, not the request/reviewer table).

## The roster is the source of truth for LINE (two-way contract)

`app/services/staff_leave_roster.py` is the only module that reconciles a
`StaffLeaveRequest` against its roster rows. Every LINE leave surface reads
its **effective state** from there — never `StaffLeaveRequest.status` alone.

- **LINE -> roster, on confirmation.** Filing/auto-recording/manager-approval
  write `EmployeeLeave` rows exactly as before (unchanged) — one row per
  date, `note` carrying the request's reference (`HF-LV-<ID>`, or
  `HF-LV-<ID>|half=am`/`pm` for a half day).
- **Roster -> LINE, at read time.** `staff_leave_roster.effective_state(db,
  row)` recomputes what a LINE surface should show by looking at the roster
  rows that currently match that reference: all of the request's dates
  present -> "recorded"; some missing -> "partial" (remaining dates only);
  none left -> "cancelled_roster". `latest_effective_leave(db, badge)`
  additionally considers the newest **admin-added** roster run (no LINE
  reference at all) so `ใบลาล่าสุด` can report it too — as a short text
  summary with no receipt image, since nothing was filed through LINE for
  it.
- **Reservation release on removal.** `app/api/leaves.py`'s
  `delete_employee_leave` and the overwrite branch of
  `create_employee_leaves` call `staff_leave_roster.on_roster_leave_removed`
  with the row's OLD note, in the same transaction, before committing. If
  that note references an existing request, its `StaffLeaveDay` for that one
  date is released (so the employee can re-file it); if that was the
  request's last remaining roster row and it was still `approved`, the
  roster itself ends it — `status="cancelled"`,
  `reviewed_by="admin:shifts-admin"` (`ROSTER_ADMIN_REVIEWER`). Overwriting a
  linked row with no `note` in the request body preserves the existing
  reference instead of wiping it, so a plain re-add/edit keeps the LINE link.
- **Admin-added rows are visible to `ใบลาล่าสุด` without an image.** A roster
  row with no LINE reference at all is still reportable as "the roster's
  latest leave" when it is newer than any LINE-filed request — text only.

## UI behavior

- shifts-admin > วันลา · วันหยุด shows four leave types and full/morning/afternoon
  portions. Admin-created leave writes through the same `/api/private/leaves/employee`
  endpoint.
- monthly shows a leave/holiday panel sourced from the same API.
- Monthly day totals split half-day leave as 0.5 leave plus 0.5 of the actual
  attendance state (worked/absent/off). Punch-derived hours and lateness are not
  rewritten.
- Internal HF leave references are not rendered by these UI surfaces.
