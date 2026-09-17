# Leave data surfaces

HF ภายใน, `/fingerprintlogs/v2/shifts-admin`, and `/fingerprintlogs/v2/monthly`
share `EmployeeLeave` as the authoritative approved-leave record.

## Data contract

- `leave_type`: `vacation`, `personal`, `sick`, `day_off`, `public_holiday`
- `leave_portion`: API field `full`, `am`, `pm`
- Half-day compatibility is stored in `EmployeeLeave.note` as `|half=am` or
  `|half=pm`; the admin API removes that marker from the public `note` field and
  exposes `leave_portion` explicitly.
- `public_holiday` is admin/holiday-table only: it comes from the shared
  `PublicHoliday` table, never from a LINE-filed request. HF ภายใน's `แจ้งลา`
  flow cannot file `public_holiday`; `staff_leave.TYPES` never includes it.
- No second leave table or sync job is required. An approval in HF ภายใน writes
  `EmployeeLeave`, and both ERP pages read that same row.
- In auto-record mode (the default — see `docs/staff-leave.md`), a
  LINE-confirmed leave request writes its `EmployeeLeave` row(s) immediately on
  the employee's final confirmation, with no separate manager-approval step in
  between. The write path and one-transaction guarantee are identical to a
  manager approval; only the reviewer marker differs (`auto:staff-oa` instead
  of a manager's email — never shown to shifts-admin/monthly, which only ever
  read `EmployeeLeave`, not the request/reviewer table).

## UI behavior

- shifts-admin > วันลา · วันหยุด shows five leave types and full/morning/afternoon
  portions. Admin-created leave writes through the same `/api/private/leaves/employee`
  endpoint.
- monthly shows a leave/holiday panel sourced from the same API.
- Monthly day totals split half-day leave as 0.5 leave plus 0.5 of the actual
  attendance state (worked/absent/off). Punch-derived hours and lateness are not
  rewritten.
- Internal HF leave references are not rendered by these UI surfaces.
