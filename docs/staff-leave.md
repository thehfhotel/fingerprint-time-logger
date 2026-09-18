# HF ภายใน: employee leave requests

## Employee experience

Open the existing internal staff OA in a **one-to-one chat** and send `แจ้งลา`
(or `ขอลา`). No email, LIFF app, new channel, or rich-menu replacement is required.
Choose sick/personal/vacation leave and its first date in LINE's native date
picker, choose the last date (or one day), then explicitly confirm.
Only that final confirmation writes a request. The OA replies with text
and a deterministic Thai/English PNG that the employee can manually forward to a
group. Names come from the linked employee registry, not chat display names.

`ใบลาล่าสุด` returns the most recently submitted request with its current status
and a newly signed image URL. `แก้ไขใบลา` lists still-pending requests (a
request already recorded — auto or by a manager — is out of scope for editing;
cancel it and file a fresh one instead) and lets the employee change type,
dates or portion before it is decided. `ยกเลิกใบลา` asks for confirmation to
cancel the most recent cancellable request — still pending, or auto-recorded
and never reviewed by a manager (see "Auto-record mode" below). A request a
manager has actually approved cannot be employee-cancelled, and never appears
in either picker.
Group commands only explain how to open a private chat; no group filing occurs.

## Auto-record mode (default)

The hotel has no manager-approval step: by default, the employee's final LINE
confirmation records the leave into the roster (`EmployeeLeave`) immediately,
the same way a manager approval always has — same half-day override, same
family-group report hook, same one-transaction roster write. The reply and
receipt PNG show `บันทึกการลาแล้ว` ("recorded"), never a pending/approval
wording, and never say who or what reviewed it. Internally the request row is
marked `status=approved`, `reviewed_by="auto:staff-oa"` (`AUTO_REVIEWER` in
`app/services/staff_leave.py`) — an audit marker only, never shown to the
employee and never a LINE id or a name.

If the roster already has a leave entry on any date in the request (the same
overlap check a manager approval uses), the auto-record aborts and the request
stays **pending** with the ordinary "ส่งใบลาแล้ว" / waiting-for-review reply —
nothing partial is written. The same happens if approval has an unmet
precondition, such as a sick leave over 3 days still missing its medical
certificate: that request stays pending until the certificate photo arrives,
at which point attaching it immediately re-runs the same auto-record check
and, once it clears, records the leave right there (reply and receipt flip to
`บันทึกการลาแล้ว`) instead of waiting for a manager to reopen it. These
pending requests are exactly what still shows up in the manager review UI.

The `STAFF_LEAVE_AUTO_APPROVE` env var is the switch (`auto_approve_enabled()`
in `app/services/staff_leave.py`, read live on every confirmation — no
restart/redeploy needed to flip): unset or any of `1/true/yes/on` (case
insensitive) means auto-record; anything else restores the original
pending-until-a-manager-decides flow for every new confirmation. Turning it
off does not touch already-recorded requests. The review UI at `.../manage`
and the pending/reject/decide machinery are unchanged and stay fully usable —
they are just dormant in the common case, with real work only when the switch
is off or an auto-record hit one of the aborts above.

Because an auto-recorded request was never reviewed by a manager, its owner
may cancel it the same way a pending request is cancelled (latest cancellable
request, explicit confirmation). Cancelling deletes only the roster rows that
specific request created and releases its date reservation; it never touches
another request's rows. A request a manager actually decided
(`reviewed_by` is a manager email, not `auto:staff-oa`) remains final and
non-cancellable, as before.

## Review

Managers open `https://erp.thehfhotel.org/api/private/leaves/requests/manage`.
The existing Cloudflare Access gate still applies, with an additional verified
manager-allowlist check in the application. Employee/kiosk identities cannot
list or decide requests. This is intentionally not the legacy staff-wide
leave CRUD's authorization level. The new UI uses same-origin requests, a custom
mutation header, origin checking, textContent for untrusted display values, and
an expected record version to prevent stale decisions.

Approval and creation of the existing EmployeeLeave rows happen in one database
transaction. Pending/rejected/cancelled requests never mark the employee off.
Existing roster leave entries are NEVER overwritten by this flow: conflicts
abort the entire approval. Reviewer identity/time are recorded; no signature is
invented. There is no automatic approval notification/push; the employee can
request `ใบลาล่าสุด`. No manager queue notification is sent in this version.

This review path is unchanged and always usable, but in auto-record mode
(the default — see above) it mostly sits idle: only requests the switch left
pending, or that an auto-record aborted (roster conflict, unmet
precondition), appear here needing an actual manager decision.

## Scope and date semantics

Four leave types are filable through LINE: `sick`, `personal`, `vacation`, and
`public_holiday` (an employee using their own rest/holiday day — the LINE
label is `ใช้วันหยุดนักขัตฤกษ์`, typed via `ใช้วันหยุด` / `วันหยุด` /
`นักขัตฤกษ์` / `วันหยุดนักขัตฤกษ์` / `ใช้วันหยุดนักขัตฤกษ์`, or picked from the
type buttons). `public_holiday` supports the same full/half-day (am/pm)
options as the others. Admin surfaces (leave-type legend, leave board, roster
cell picker, monthly report) show it as `วันหยุดนักขัตฤกษ์`, matching the
existing company-wide `PublicHoliday` calendar type it shares a code with as
of the 2026-09-18 merge (migration
`20260918_000000_merge_day_off_into_public_holiday`; before that, LINE's
version was tracked separately as `day_off`). The inclusive range is
expressed as calendar days, NOT a
calculated entitlement or payroll deduction. Managers must check shifts,
scheduled days off, policy and entitlement before approving a range. Each date
in an approved range becomes a roster leave entry, matching the existing admin
bulk-entry model. Split ranges when not every date should be marked as leave.
Half-day/hourly leave, other leave types, remaining-balance calculations,
attachments, approval delegation and approved-request revocation are not included.

System validation bounds are 92 inclusive days per request, a first date no
more than 31 days in the past, and an end no more than 366 days ahead. These
are input bounds, not statements of legal entitlement. Other cases are referred
to the manager. UI dates use Buddhist years; database dates use ISO calendar
dates; timestamps are UTC and rendered in Asia/Bangkok.

## Privacy, replay and images

Only verified LINE webhook events can file a request. The LINE user must resolve
to an active, approved employee. One-hour HMAC postback payloads are bound to
the employee badge; forwarding a confirmation button cannot submit as someone
else. A form UUID is a durable idempotency key. Composite-primary-key date
reservations enforce pending/approved overlap protection across requests and
restarts. Cancellation and rejection release reservations. Conditional versioned
updates serialize approval against cancellation and other reviewers.

No free-text reasons or medical attachments are collected by this feature.
Images contain the necessary employee name, department/property, leave type,
dates, status, reference and timestamps; no LINE identifiers or reviewer email.
Images are generated from database records with Pillow, not an image-generation
model. Runtime installs `fonts-tlwg-loma-otf` explicitly; Loma supports Thai AND
Latin/digits. Tests fail rather than silently producing missing-glyph boxes.

LINE fetches PNGs from `/api/public/staff-oa/leave-images/{id}.png` with a
purpose-separated HMAC, version and 24-hour expiry. This is a bearer URL: anyone
holding a valid URL can view that minimal receipt until it expires. Do not log
query strings, publish URLs, or allow CDN caching on this route. Responses set
private/no-store, noindex and no-referrer headers. State changes invalidate
older version URLs, but **cannot recall a PNG LINE has already cached or an
employee has already forwarded**. Each image explicitly states its snapshot time
and the command for current status. Nothing auto-posts to a LINE group.

The webhook runs the synchronous leave/reply operation in a worker thread, so
LINE fetching the PNG cannot deadlock the event loop. Other bot events retain
the existing routing and follow behavior. A failed reply never undoes an already
committed leave; `ใบลาล่าสุด` recovers it. Errors log only exception classes.

## Deployment and acceptance

Existing STAFF_OA_CHANNEL_SECRET/ACCESS_TOKEN are reused. No new secrets, LINE
channel settings or public hostnames are introduced. Merge follows the existing
main-branch GitHub Actions build/deploy workflow; do not deploy manually.
Migration `20260916_000000` follows `20260905_000000`, adds only two new tables,
and does not rewrite existing employee/attendance data. Back up the database
before production deployment using the established process.

Before declaring the feature live, verify all of these against the deployed SHA:

- CI unit/integration suites and new leave tests pass on pinned Python dependencies.
- Existing health route and ordinary staff bot commands still work.
- A linked test employee completes the native LINE flow and actually receives a
  readable image. Check Thai, Latin, date digits and forwarding from iOS/Android.
- LINE can fetch the signed image through the public nginx/Cloudflare path
  without an Access login, while missing/bad/expired/version-stale signatures
  fail closed. Check edge cache behavior, not only origin headers.
- A real manager can open the review UI; employee/kiosk/anonymous cannot decide.
  Confirm pending leaves do not alter the roster and approval does exactly once.
- Cancel/reject, repeated confirmation and a conflicting existing roster entry
  behave as tested; request a fresh image with `ใบลาล่าสุด` after a decision.

Rollback: roll application code back through CI; retain the new tables and audit
records. A schema downgrade drops request history and is not routine rollback.
Existing approved roster rows are retained; never silently undo granted leave.

## ตารางงานคือแหล่งข้อมูลหลัก / the roster is the source of truth

Every LINE leave surface — `ใบลาล่าสุด`, the receipt PNG, the after-submit
reply heading, `ยกเลิกใบลา`'s picker, and HF Family's slot digest — reads its
current state from the **roster** (`EmployeeLeave`), never from
`StaffLeaveRequest.status` alone. Whatever an admin does on
`/v2/shifts-admin`'s วันลา · วันหยุด board is what LINE shows, immediately,
with no separate sync job. `app/services/staff_leave_roster.py` is the only
place that reconciles the two; see `docs/LEAVE_SYNC_SURFACES.md` for the
exact contract.

Concretely: an approved (or auto-recorded) request's roster rows all carry
its reference (`HF-LV-<ID>`, optionally `|half=am`/`|half=pm`) in
`EmployeeLeave.note`. If an admin deletes or overwrites one of those rows on
shifts-admin, `app/api/leaves.py` calls
`staff_leave_roster.on_roster_leave_removed` with the row's old note, in the
same transaction, before committing:

- The request's day reservation (`StaffLeaveDay`) for that date is released,
  so the employee can re-file it through LINE afterward.
- If that was the request's **last** remaining roster row, the roster itself
  is what ended the leave: the request is marked `status="cancelled"`,
  `reviewed_by="admin:shifts-admin"` (`ROSTER_ADMIN_REVIEWER` — an audit
  marker only, never shown to the employee and never a LINE id or a name),
  and any leftover `StaffLeaveDay`/medical-certificate data is cleared.
- If some roster rows remain, the request stays `approved` but LINE reads it
  as **"partial"** (`บันทึกการลาแล้ว (ปรับจากตารางงาน)`) — the remaining
  dates only, not the originally filed range. `ยกเลิกใบลา` still offers it
  (cancelling removes only the rows still there); once the roster has ended
  it entirely (`"cancelled_roster"`), it drops out of that picker too.

An admin can also add roster rows directly with no LINE request behind them
at all. `ใบลาล่าสุด` still reports the most recent one (whichever is newer:
the latest LINE-filed request, or the latest contiguous admin-added run) —
as a short text summary ("วันลาล่าสุดในตารางงาน: ... (บันทึกโดยแอดมิน)")
with **no** receipt image, since nothing was ever filed through LINE for it.

## Testing record

Local isolated tests exercise SQLAlchemy transactions, API dependency boundaries,
LINE payload construction and real PNG rendering with test data; LINE HTTP calls
and manager-identity resolution are stubbed. Local harnesses mirror the verified
Employee/EmployeeLeave table contracts and are NOT committed. This is not a
production end-to-end test. The committed tests run against the repository's real
models in CI, with the same Loma font package installed in CI and Docker.
