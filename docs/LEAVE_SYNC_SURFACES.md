# Leave data surfaces

HF ภายใน, `/fingerprintlogs/v2/shifts-admin`, and `/fingerprintlogs/v2/monthly`
share `EmployeeLeave` as the authoritative approved-leave record.

## Data contract

- `leave_type`: `vacation`, `personal`, `sick`, `day_off`, `public_holiday`
- `leave_portion`: API field `full`, `am`, `pm`
- Half-day compatibility is stored in `EmployeeLeave.note` as `|half=am` or
  `|half=pm`; the admin API removes that marker from the public `note` field and
  exposes `leave_portion` explicitly.
- No second leave table or sync job is required. An approval in HF ภายใน writes
  `EmployeeLeave`, and both ERP pages read that same row.

## UI behavior

- shifts-admin > วันลา · วันหยุด shows five leave types and full/morning/afternoon
  portions. Admin-created leave writes through the same `/api/private/leaves/employee`
  endpoint.
- monthly shows a leave/holiday panel sourced from the same API.
- Monthly day totals split half-day leave as 0.5 leave plus 0.5 of the actual
  attendance state (worked/absent/off). Punch-derived hours and lateness are not
  rewritten.
- Internal HF leave references are not rendered by these UI surfaces.
