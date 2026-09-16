# HF ภายใน: employee leave requests

## Employee experience

Open the existing internal staff OA in a **one-to-one chat** and send `แจ้งลา`
(or `ขอลา`). No email, LIFF app, new channel, or rich-menu replacement is required.
Choose sick/personal/vacation leave and its first date in LINE's native date
picker, choose the last date (or one day), then explicitly confirm.
Only that final confirmation writes a pending request. The OA replies with text
and a deterministic Thai/English PNG that the employee can manually forward to a
group. Names come from the linked employee registry, not chat display names.

`ใบลาล่าสุด` returns the most recently submitted request with its current status
and a newly signed image URL. `ยกเลิกใบลา` asks for confirmation to cancel the
most recent pending request. Already approved requests cannot be employee-cancelled.
Group commands only explain how to open a private chat; no group filing occurs.

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

## Scope and date semantics

Version one supports **full-day** `sick`, `personal`, `vacation` only, matching
existing roster types. The inclusive range is expressed as calendar days, NOT a
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

## Testing record

Local isolated tests exercise SQLAlchemy transactions, API dependency boundaries,
LINE payload construction and real PNG rendering with test data; LINE HTTP calls
and manager-identity resolution are stubbed. Local harnesses mirror the verified
Employee/EmployeeLeave table contracts and are NOT committed. This is not a
production end-to-end test. The committed tests run against the repository's real
models in CI, with the same Loma font package installed in CI and Docker.
