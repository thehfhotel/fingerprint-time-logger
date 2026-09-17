# Employee Hub — staff LINE OA setup & operations

The Employee Hub is the rich menu on a **dedicated staff LINE Official
Account** (decision of record: HF-erp
`docs/adr/0001-employee-hub-is-line-rich-menu.md`). Employees launch their
tools from grant-driven **Role Menus**; this repo hosts the machinery:

| Piece | Where |
|---|---|
| Menu model (buttons, variants, layout, signatures) | `app/services/staff_oa_menu.py` |
| Menu image renderer (PIL, HF One palette, bundled Thai font) | `app/services/staff_oa_images.py` |
| Credentials, webhook signature, LINE API client, relink helper | `app/services/staff_oa_service.py` |
| Follow-event webhook | `app/api/staff_oa.py` → `POST /api/public/staff-oa/webhook` |
| Staff bot (HF ภายใน): digest, guest feedback, palette, debounce | `app/services/staff_bot.py` |
| Guest-feedback read/confirm (guest-feedback docs/CONTRACTS.md §15 rev 3, widened by rev 3.1) | `app/services/guest_feedback_client.py` |
| **Automatic per-employee provisioning (create menu + link/unlink)** | `app/services/staff_oa_provision.py` |
| Idempotent menu/link sync (dry-run by default) | `scripts/staff_oa_sync.py` |
| Offline image preview | `scripts/staff_oa_render_menus.py` |

## Fail closed

The whole feature is **dark** until BOTH env vars are set (see the registry
block in `app/core/config.py`):

- `STAFF_OA_CHANNEL_ACCESS_TOKEN` — Messaging API long-lived channel access token
- `STAFF_OA_CHANNEL_SECRET` — channel secret (webhook signature verification)

Unset ⇒ the webhook answers `503` and the sync script exits 2 without
touching anything. These are a **different channel** from `LINE_CHANNEL_*`
(the LINE Login channel behind QR check-in OAuth).

## Role Menus

**The Hub is a MAID tool** plus, since 2026-09-01, the reception half of the
same sentence (owner directive 2026-08-14: "for maid to notify reception of
cleaning progress and maid inventory"). It is still not a general employee
launcher, with one exception: **แจ้งลา (file a leave request) is a BASE
tile** (owner decision, 2026-09-18) — every linked employee sees it
regardless of grants. Every OTHER button stays behind a grant:

| Button | URL / action | Needs grant |
|---|---|---|
| แจ้งลา (file a leave request) | message action `แจ้งลา` → the LINE leave flow (`app/services/staff_leave.py`) | **none — every linked employee** |
| แม่บ้าน (cleaning board) | https://hotel.thehfhotel.org/hk | `housekeeping` |
| แจ้งซ่อม (breakage report) | https://housekeeping.thehfhotel.org/staff/report | `housekeeping` |
| สต๊อกของ (stock count / purchase request) | https://housekeeping.thehfhotel.org/staff/stock | `housekeeping` |
| รับของมาส่ง (receive a delivery) | https://housekeeping.thehfhotel.org/staff/receive | `housekeeping` |
| สถานะห้อง (room status, read-only) | https://hotel.thehfhotel.org/hk — **hidden when `housekeeping` is also held** | `reception` |
| รายงานแม่บ้าน (daily room report) | https://hotel.thehfhotel.org/hk/report | `housekeeping` **or** `reception` |
| งานซ่อมค้าง (outstanding maintenance, chat report) | message action `งานค้าง` → staff bot report (no web page) — **hidden when `housekeeping` is also held** | `reception` |
| จัดการงานซ่อม (outstanding maintenance, queue page) | https://housekeeping.thehfhotel.org/staff/queue | `housekeeping` **or** `reception` |

Four variants exist: `base` (**1 tile** — แจ้งลา alone; a real, renderable
menu, not an empty placeholder), `base+reception` (**5**: แจ้งลา, สถานะห้อง,
รายงานแม่บ้าน, งานซ่อมค้าง, จัดการงานซ่อม), `base+housekeeping` (**7**: แจ้งลา,
แม่บ้าน, แจ้งซ่อม, สต๊อกของ, รับของมาส่ง, รายงานแม่บ้าน, จัดการงานซ่อม) and
`base+housekeeping+reception` (**7** — the same seven tiles as
`base+housekeeping`; สถานะห้อง and งานซ่อมค้าง stay hidden). `MAX_BUTTONS = 8`
is the Hub's own layout ceiling (2026-09-18) — a 4x2-cell grid at most; LINE
itself allows up to 20 rich-menu areas, so this was never LINE's limit, only
ours. The maximal real variant sits one tile under that ceiling today, so
there is exactly one tile of headroom left before a tenth tool forces
something to be removed or merged. Adding a row to `MENU_BUTTONS` past the
ceiling does not fail loudly at deploy time — the over-cap guards in
`scripts/staff_oa_sync.py` and `app/services/staff_oa_provision.py` fall
back to the base menu (แจ้งลา alone) for everyone over the cap, or unlink
them if even base has no buttons, and log a warning.

**How งานซ่อมค้าง and จัดการงานซ่อม fit onto a menu already at the cap
(2026-09-06):** neither added a row that had to render on the both-grants
canvas — each took over a slot that a hide rule freed up.
`MenuButton.hidden_by_grant_app_ids` on สถานะห้อง (`{"housekeeping"}`) means
that tile is dropped for anyone who ALSO holds `housekeeping`, because
แม่บ้าน already opens the identical `/hk` board for them with full write
access — the read-only duplicate was a wasted slot on a full canvas.
งานซ่อมค้าง took that freed slot first, that same morning, also carrying its
own `hidden_by_grant_app_ids={"housekeeping"}` from the start — a
housekeeping+reception holder never needed the read-only chat report either,
since แม่บ้าน already gave them full write access to the same board. Then the
owner decided to launch a SECOND tool the same day — จัดการงานซ่อม, a `uri`
tile opening the actual queue page. It first carried the identical hide, but
the owner widened it hours later ("let maid mark fix done too"): the queue
page itself was updated to admit the `housekeeping` grant as well as
`reception`, so maids now need this launcher too, and it became a SHARED
tile (`also_grant_app_ids={"housekeeping"}`) rather than a hidden one. So the
both-grants variant still renders exactly six tiles: the four maid tools,
รายงานแม่บ้าน, and จัดการงานซ่อม, with both สถานะห้อง and งานซ่อมค้าง hidden —
that employee reaches the queue page directly instead of the read-only chat
report. A `reception`-only employee is unaffected by either hide (no
`housekeeping` grant to trigger them) and keeps all four tiles: สถานะห้อง,
รายงานแม่บ้าน, งานซ่อมค้าง, and จัดการงานซ่อม — the Hub's first real use of
the 2+2 layout. A `housekeeping`-only maid, previously capped at five tiles,
now also gets จัดการงานซ่อม as her sixth, reaching the Hub's then-6-tile
layout ceiling the same way the both-grants variant does — never LINE's own
limit, only the Hub's own choice at the time (see "Four variants exist"
above for where that ceiling sits today).

งานซ่อมค้าง itself is a `message` rich-menu action rather than `uri` —
reception's web board is Google-IdP-gated and cannot open inside LINE's
in-app browser at all (the same dead end Reimbursement and payroll hit, see
below), so the tile instead sends the text `งานค้าง` into the 1:1 chat,
which the staff bot (`app/services/staff_bot.py`, already live) answers with
the outstanding-maintenance report. A message action is also free of LINE's
proactive-push quota — see "Mind the push cap" below — since tapping it is
the user initiating the exchange, not the bot pushing to them. จัดการงานซ่อม
is a plain `uri` tile: `housekeeping.thehfhotel.org/staff/queue` is on this
app's own Cloudflare Access setup and does not hit the same in-app-browser
dead end works.thehfhotel.org does, so it opens directly — it is where the
work actually gets claimed and closed, not merely read. It reuses the
existing `wrench` glyph (the "go act" mark แจ้งซ่อม already wears) rather
than minting a new one, since the two maintenance tiles now sitting side by
side needed their glyphs to read as "report" (`wrench_list`, still) vs. "go
do the work" (`wrench`).

**รายงานแม่บ้าน and จัดการงานซ่อม are SHARED tiles** — one row each in
`MENU_BUTTONS`, revealed by either grant (`MenuButton.also_grant_app_ids`).
รายงานแม่บ้าน is shared because a room report is two-sided: the maid files it
(status code, equipment exceptions, 1–4 photos) and reception verifies it
with 1–4 photos of their own, or returns it with a canned reason. Both halves
are the same screen. จัดการงานซ่อม is shared for the same shape of reason,
widened onto it 2026-09-06 ("let maid mark fix done too"): housekeeping's own
`/staff/queue` page now admits the `housekeeping` grant as well as
`reception`, so a maid claims and closes a repair from the same page
reception uses to manage the queue. An employee holding both grants sees
either tile **once**, not twice — that is what the one-row model guarantees,
and what two rows would have got wrong.

**สถานะห้อง and แม่บ้าน open the same board.** That is deliberate: `reception`
is a READ-ONLY viewer on `/hk`. new-hotel's `hk_access` middleware admits
either grant, but the write verbs (`POST .../cleaning`,
`POST .../linen-shortage`) require `housekeeping` and answer a reception-only
identity with a 403; `GET /api/hk/me` returns `canReport: false` so the UI
hides the reporting controls. The UI hiding is UX — **the server is the
enforcement.**

An employee holding both grants does NOT see both tiles, though — since
2026-09-06 สถานะห้อง is hidden the moment `housekeeping` is also held
(`hidden_by_grant_app_ids={"housekeeping"}`), because แม่บ้าน already opens
that same board with full write access and a second, read-only tile pointing
at it would be a wasted slot. A `reception`-only
employee still gets สถานะห้อง; a `housekeeping`-holder never needed it in
the first place. งานซ่อมค้าง carries the identical hide, for the identical
reason on a different tool: once จัดการงานซ่อม is shared (above) a
housekeeping+reception employee reaches the same queue page with full write
access, so the read-only chat report is dropped in favor of it — a
`reception`-only employee still gets both tiles side by side.

The same argument covers รายงานแม่บ้าน and จัดการงานซ่อม, which both grants
now open: new-hotel enforces the roles server-side per verb — submitting a
report is maid-only (the `canReport: true` side), verify and return are
reception-only, and a maid who also holds `reception` still cannot verify her
own work; housekeeping.thehfhotel.org/staff/queue admits either grant on the
server side the same way. The tile is a launcher, never an authorization.

### `base` carries แจ้งลา — every linked employee gets a menu

Owner decision (2026-09-18): an employee holding NEITHER `housekeeping` nor
`reception` still gets a real, one-tile Employee Hub — แจ้งลา, so every
linked employee can file a leave request regardless of what else they hold.
This replaces the old "grant-only Hub, no menu at all for base" contract:

- the `base` rich menu (แจ้งลา alone) is **created like any other variant**;
- the **channel default rich menu is `base`** — the first menu an unlinked
  follower or a freshly-linked employee with no other grant would see;
- employees on the `base` variant are **linked to it**, not unlinked — the
  old `bulk_unlink_rich_menu` path for an empty base is gone; unlinking now
  only happens when even `base` has no buttons (i.e. someone deletes the
  แจ้งลา row too, which would be its own regression);
- the follow webhook still replies to an unknown follower with the
  onboarding pointer (a stranger is never linked to any menu); a
  known-but-ungranted follower is linked to `base` instead.

**Over-cap disposition (`staff_oa_provision.py` /
`scripts/staff_oa_sync.py`):** when a variant needs more buttons than
`menu_size` accepts (more than `MAX_BUTTONS = 8`), both paths **fall back to
linking the employee to the `base` menu** — since base now always has a
button (แจ้งลา), there is always somewhere to fall back to. Unlinking only
happens in the case base itself is empty (the pre-2026-09-18 contract, kept
as a defensive fallback rather than a live path). This mirrors what
`scripts/staff_oa_sync.py` already did at its own over-cap branch before
`staff_oa_provision.py` was brought in line with it.

**Consequence when applying:** issuing `housekeeping` grants and running
`staff_oa_sync.py --apply` should happen in ONE operation. Applying the
sync first leaves every linked employee on `base` (แจ้งลา only) until the
grants land — no longer with no menu at all, but still not the menu they
are about to be entitled to.

### If a clock-in button ever comes back

`สแกนเข้างาน` was on the Hub until 2026-08-14. If it or any
`erp.thehfhotel.org/qr-checkin` link returns on any surface, it **must**
carry a path suffix — `/qr-checkin/mobile` for a phone. The bare
`/qr-checkin` has no route: it 301s to `http://` (protocol downgrade) and
then 404s. It shipped that way from the menu's first commit (`a816c86b`,
2026-07-09) until 2026-08-14 — five weeks in which every linked employee
had a dead clock-in tile and nobody reported it. Registered pages are
`/qr-checkin/{terminal,mobile,link-account,onboard}`.

### Deliberately absent

**แม่บ้าน / cleaning progress (`hotel.thehfhotel.org/hk`) is DEFERRED**
(owner, 2026-08-14), not deleted. It is the only cleaning-progress surface
in the estate and its Access app is HF ID (LINE) only, so it is safe to put
back — but two things should land first:

1. **Nothing notifies reception of anything.** There is no LINE push, no
   Slack, no toast on any reception screen. `ht_hk_cleaning_events` is read
   by nothing outside `routes/hk.rs`, so `started` has zero reception
   visibility; only `done` reaches reception, as a silent `room_clean` flip
   picked up by a 30-second poll.
2. **`hkFetch` never sends `?branch=`**, so the backend defaults to
   `Branch::Hfhotel` — a HF Ville maid would see and *mutate* HF Hotel
   rooms.

Also wanted before re-adding (owner): a **mark dirty** verb alongside mark
clean. Mark clean already writes through to both PMS and iHOTEL; mark dirty
does not exist — `/hk` has only `started` and `done`, pinned by a DB CHECK
constraint.

**เงินเดือน (Payroll) and OTA Desk were removed 2026-08-14** for scope, not
breakage: neither is a maid tool. Both are also dual-IdP with a Cloudflare
picker, so they render a Google button inside LINE — the same shape that
dead-ended Reimbursement. It bites less there because both are grant-gated
to HF ID (LINE) employees who pick HF ID and get through; it is a footgun,
not an outage. Removing the tiles removed only the launcher — the grants
still open both from a real browser, where they work better.

**Reimbursement is deliberately NOT on the menu** (owner directive
2026-08-14, removed same day it went live). The button opened
`reimbursement.thehfhotel.org` inside LINE's in-app browser, where Google
refuses OAuth (`disallowed_useragent`) — managers reaching the Cloudflare
Access picker were dead-ended, which read as "reimbursement regressed to
LINE-only". Reimbursement is a web app reached from real browsers (desktop
included); its Access app still checks the `apps` claim for the
`reimbursement` grant (default-granted at onboarding) alongside the
managers' Google allowlist. Don't re-add the button without solving the
external-browser handoff.

The sync script creates only the variants **actually held** by linked
employees (plus `base`, the channel default). Rich-menu names embed a
content signature (`staffhub:<variant>:<sig>`) — that is the idempotency
key: re-running the sync reuses unchanged menus, re-creates changed ones,
and deletes stale `staffhub:*` menus. It never touches menus it didn't
create.

## Go-live checklist (after creating the staff OA)

1. In the [LINE Developers console](https://developers.line.biz/): create a
   **Messaging API channel** for the staff OA. Issue a long-lived **channel
   access token**; note the **channel secret**.
2. Set the **webhook URL** to
   `https://erp.thehfhotel.org/api/public/staff-oa/webhook`, enable
   *Use webhook*, and disable auto-reply/greeting messages
   (the webhook handles the one onboarding reply itself).
3. Deliver both values as **GitHub repo secrets** (`gh secret set
   STAFF_OA_CHANNEL_ACCESS_TOKEN` / `STAFF_OA_CHANNEL_SECRET` on
   `thehfhotel/fingerprint-time-logger`) and re-run the deploy workflow —
   they ride the deploy payload into the host `.env` like `HFID_*`.
   Do NOT hand-edit the host `.env`: the deploy script rewrites it on
   every deploy, so hand-set values are silently wiped (this bit
   new-hotel's card-login on 2026-07-09). The host compose `environment:`
   block must also list both vars (host-owned; already done alongside the
   `READER_*` entries).
4. Deploy the menus and links:
   ```bash
   docker exec fingerprint-time-logger python scripts/staff_oa_sync.py           # plan
   docker exec fingerprint-time-logger python scripts/staff_oa_sync.py --apply   # execute
   ```
5. That is the last time anyone needs to run it for a grant change — see
   **Automatic provisioning** below. Re-run `--apply` only for the
   channel-wide operations that stay manual (channel default, deleting
   stale menus, a bulk relink after an artwork change).

## Automatic provisioning (no commands)

Owner directive, 2026-08-14: *"make it auto when housekeeping or new menu
is granted then maids or users see new LINE OA menu. should be seamless
from admin perspective. no need to run commands."*

`app/services/staff_oa_provision.py` — `provision_for_badge(badge)` — does
for ONE employee what the sync script does for the channel: computes their
variant from `employee_app_grants`, **creates the rich menu if that variant
is not deployed yet** (render PNG → `create_rich_menu` →
`upload_rich_menu_image`), then links them to it. No app grants at all
(neither `housekeeping` nor `reception`) resolves to the `base` variant
(แจ้งลา alone, since 2026-09-18) rather than to no menu — so a full
revocation now **links the employee to `base`** instead of unlinking them,
and a revocation is still as automatic as a grant.

It fires from three places, always via FastAPI `BackgroundTasks` (after the
response, in a threadpool — the blocking LINE/PIL work never touches the
event loop):

| Trigger | Where |
|---|---|
| Admin saves app grants | `PUT /api/private/admin/employees/{badge}/grants` |
| Employee links LINE with a 6-digit code | `POST /api/public/auth/line/link-account` |
| Admin approves a self-onboarding | `POST /api/private/admin/onboarding/approve` |

The last two matter because **grant-then-link** is a real onboarding order:
the grant fires while `line_user_id` is still `NULL` and returns early, so
the link is what completes it.

A safety net runs **hourly** in the background scheduler
(`reconcile_staff_oa_menus`, interval overridable with
`STAFF_OA_RECONCILE_INTERVAL_MINUTES`): every active, LINE-linked employee
goes through the same path, converging anything the events missed (LINE
down at grant time, a grant written straight into the DB, a menu deleted by
hand in the LINE console).

Both paths are **strictly additive and per-user**: they never delete a rich
menu and never touch the channel default. Those are destructive
cross-employee operations and stay in `scripts/staff_oa_sync.py`.
Provisioning also **never raises** — a LINE outage must never fail or roll
back the admin's save (the grant is committed before the task is scheduled;
the hourly reconcile is what retries). Everything no-ops while the feature
is dark.

Employees who follow the OA are still linked by the webhook as well.

## Webhook behavior

`follow` event → LINE userId looked up in `employees.line_user_id`:

- **known + active** → link that employee's Role Menu variant.
- **unknown/inactive** → link the base menu and reply once (free, no push
  quota) with a short Thai pointer to the Q-badge onboarding flow
  (`/qr-checkin/onboard`) that links LINE accounts.

Since 2026-09-05 the webhook also drives the **staff bot** (below) on
`message`, `postback` and `join`. Everything else is ignored. Per-event
failures are logged but never fail the delivery (LINE would retry the whole
batch), and a delivery marked `deliveryContext.isRedelivery` is dropped by
the bot so a LINE retry cannot double-post.

## The staff bot (HF ภายใน)


**HF Family (or any group/room) is REPORT-ONLY, with ONE command carve-out**
(owner policy, 2026-09-06: *"command through chat is considered spam in HF
Family group... feedback should be consolidated and report in reporting style
not chat style"*; owner, 2026-09-06 evening: *"HF Family should be able to
get mention and act to create new maintenance ticket still"*). A group never
answers an ordinary command, of any kind, from anybody — its only voices are
the four daily **slot reports** (below) and this one @mention ticket
exception. Every other command, ticket edit and preview lives in a **1:1
chat**. Design authority: hf-erp ADR *"The staff bot answers only with reply
tokens; LINE meters pushes per recipient"*. Code: `app/services/staff_bot.py`
(router, palette, digest, requests, debounce), `app/services/housekeeping_client.py`
(the แจ้งซ่อม read/write) and `app/services/guest_feedback_client.py` (the
guest-feedback read/confirm).

### What to type, and where

| Where | What to type | What comes back |
|---|---|---|
| HF Family (any group/room) | `@HF ภายใน แจ้งซ่อม <ห้อง> <อาการ>` (an explicit @mention of the bot whose text after the mention starts with แจ้งซ่อม) + photos/video | the ticket flow (see "แจ้งซ่อม from chat" below), replied as a **compact text line**, not the 1:1 Flex bubble — see "Group is report-only" below |
| HF Family (any group/room) | anything else — unmentioned text, a mention with other words, a tap on an old bubble's button, a photo, a video | **nothing.** The message is only a candidate for the scheduled slot report's heartbeat (see "The slot report" below); it is never parsed as a command, never acknowledged (a linked sender's photo/video IS still buffered — ids only — in case a mention-report follows it). |
| 1:1 chat | `งานค้าง` (also `งานซ่อมค้าง`, `แจ้งซ่อมค้าง`) on its own | the digest |
| 1:1 chat | `คำขอ` / `คำขอลูกค้า` / `guest requests` / `ความคิดเห็น` / `ฟีดแบค` / `feedback` on its own | a **preview** of the pending guest feedback, report-style (see "Guest feedback" below) |
| 1:1 chat | `แจ้งซ่อม <ห้อง/พื้นที่> <อาการ>` | the ticket flow (see "แจ้งซ่อม from chat" below) |
| 1:1 chat | `เพิ่มรูป <id>` / `เพิ่มรูป #<id>` (reply-to-media, 2026-09-06) | attach a photo/video, gated like `cmd=addphoto` (see "Reply-to-media" below) |
| 1:1 chat | anything else | the palette bubble |
| 1:1 chat | tapping the palette's **งานค้าง แจ้งซ่อม** button (`cmd=digest`) | the digest |
| 1:1 chat | tapping the palette's **ความคิดเห็นลูกค้า** button (`cmd=requests`) | the pending guest feedback preview |

The sender must resolve to an **active** employee via `line_user_id`; an
unknown account gets the same Q-badge onboarding reply a stranger's `follow`
gets, and nothing else (a stranger's mention-report gets `NOT_LINKED_TEXT`
instead — see "Group is report-only" below). There is no summon *word*
grammar any more — a 1:1 never needed one, and a group only ever reacts to
LINE's own @-mention, never a typed word.

### Zero metered messages

Every reply rides the webhook's **reply token**, which LINE does not count at
any chat size. A *push* into the staff group would be metered **per member**
(one send to 17 people = 17 messages) against an allowance of ~300/month — see
"Mind the push cap" below. No push, multicast, broadcast or narrowcast exists
anywhere in this feature, and none may be added to it.

### Commands answer at once; scheduled reports wait for quiet

A 1:1 command word or a palette tap is answered **immediately**
(`COMMAND_QUIET_SECONDS = 0`). The owner's rule (2026-09-05): "15 seconds of
quiet is for scheduled reports, not for the command reply."

The wait-for-quiet machinery (`ReplyDebouncer`) exists for the **phase 2 slot
report**, which piggybacks on reception's hourly report and must never land in
the middle of that burst: it waits for **15 s of quiet** (`SLOT_QUIET_SECONDS`)
in the chat, every later message hands it a fresher reply token and restarts
the timer, and it fires at the latest **45 s** after the first trigger — reply
tokens are short lived, so that cap is not optional. Commands filed in the same
instant for one chat still coalesce into a single reply.

### The slot report (phase 2, consolidated 2026-09-06)

Four Bangkok windows a day, in **groups only** (rooms and 1:1 chats never have
one) — the ONLY thing a group ever hears from this bot. Each window posts
**once**, as a REPORT with up to two sections:

- **(a) the maintenance digest** — unchanged text, under one extra line:
  `สรุปงานซ่อมค้างประจำรอบ<เช้า|เที่ยง|บ่าย|ค่ำ>` — present whenever housekeeping
  answers at all (even "ไม่มีงานซ่อมค้าง").
- a blank line, then **(b) ความคิดเห็นลูกค้า** — pending guest feedback,
  consolidated in 2026-09-06 (owner: *"feedback should be consolidated and
  report in reporting style not chat style"*), present whenever guest-feedback
  has something pending. See "Guest feedback" below for the line format.

Either section is simply **omitted** when its own source has nothing to say
(housekeeping dark, or guest-feedback dark/zero pending) — the report still
goes out with just the other section. The window posts **nothing at all**
only when BOTH are empty (a scheduled message must never spam an error line
into HF Family, but a scheduled post that DOES have real content — feedback
pending even while housekeeping is dark — must not be dropped either).
`render_slot_digest` / `render_feedback_section` in `staff_bot.py` are the
two functions this splits across; the combined text is still capped at
LINE's 5000-char message limit (`_fit`), same as the maintenance section
always was on its own.

| Slot | Window (Bangkok, start inclusive / end exclusive) | Label |
|---|---|---|
| `morning` | 06:00 – 10:00 | เช้า |
| `noon` | 12:00 – 14:00 | เที่ยง |
| `afternoon` | 14:30 – 16:30 | บ่าย |
| `night` | 19:30 – 21:30 | ค่ำ |

The window is decided by the **event's own timestamp** (LINE's epoch-ms
`timestamp`, converted to Bangkok), not by the server clock at send time.

**What opens a window.** Any message in the group, of any kind (text,
sticker, photo, video, location; owner rule 2026-09-06: stickers count) —
never read, kept or logged, since a group message can no longer be a command
of any kind either:

1. from someone whose LINE account maps to an **active employee holding the
   `reception` grant**, riding the report burst this digest is meant to piggyback
   on; or
2. from **anyone**, including a sender LINE gives us no `userId` for (LINE for
   PC), in the window's **last 30 minutes**.

Nothing else. A window in which the group never speaks is **skipped**; that
is by design, not a failure. There is no group allowlist.

**Once per slot, across restarts.** The mark is a row in
`staff_bot_slot_marks` (UNIQUE `group_id, bkk_date, slot`), written `pending`
the moment the slot is filed and promoted to `sent` when the LINE reply
succeeds. Every other outcome **deletes** the row so the next qualifying
message re-triggers: the send failed, both sources had nothing to say (a
scheduled post must never spam `ระบบงานซ่อมยังไม่เชื่อมต่อ` into the group four
times a day; it says nothing at all instead), or a `pending` older than 120 s
was left behind by a process that died mid-debounce.

**Delivery confirm.** Once LINE has **accepted** a slot report that carried
section (b), the bot calls `guest_feedback_client.confirm_delivered` with
that fetch's feedback ids — the group posting the report IS the delivery,
exactly as a 1:1 preview (below) never triggers it.

Logs, ids only, INFO: `staff-bot slot filed: group=... date=... slot=...
trigger=reception|late`, `staff-bot slot sent: ...`, `staff-bot slot dropped:
... reason=send_failed|housekeeping_dark|stale`.

No new environment variables: the behaviour is live for every group the OA is
in as soon as this deploys.

### Privacy rule

The webhook sees every message in the staff group. A group/room message of
any kind is discarded **before any logging** (DEBUG-only, never INFO: `staff-bot
group ignored: type=message|postback chat=...`) — no text, no photo, no
sender. A recognised 1:1 command logs exactly three fields: event type,
source type, chat id. The first `join` logs the group id once (`staff-bot
joined group C...`), which is how the rollout learns it. Nothing else about a
message is ever written down.

### Where the งานซ่อม rows come from

`GET {HOUSEKEEPING_INTERNAL_URL}/internal/staff-bot/digest` with
`Authorization: Bearer {HOUSEKEEPING_STAFF_BOT_TOKEN}`, 5 s timeout,
container-to-container over the shared-nginx network (no Cloudflare Access in
the path). Housekeeping returns both properties, Thai-labelled, urgent first
then oldest, 20 rows each plus a `truncated` count.

```
HOUSEKEEPING_INTERNAL_URL=http://housekeeping:4070   # default; not a secret
HOUSEKEEPING_STAFF_BOT_TOKEN=<= housekeeping's STAFF_BOT_INGRESS_TOKEN>
```

**Empty token ⇒ dark**: nothing is dialed and every digest request answers
`ระบบงานซ่อมยังไม่เชื่อมต่อ ลองใหม่อีกครั้งภายหลัง` — the same line a timeout,
a 401 or a 503 produces. Staff never see a status code, and never silence.
Both variables ride the deploy (`env_payload` in
`.github/workflows/build.yml`, passthrough in `docker-compose.yml`); do not
hand-edit the host `.env`, every deploy rewrites it.

### แจ้งซ่อม from chat (phase 3, 1:1 only since 2026-09-06; group/room reopened
that evening via @mention — phase 5)

A linked employee raises a ticket without leaving LINE: `แจ้งซ่อม <ห้อง/พื้นที่>
<อาการ>`, bare, in a 1:1 chat — or `@HF ภายใน แจ้งซ่อม <ห้อง/พื้นที่> <อาการ>`,
an explicit @mention of the bot, in a group/room. Every OTHER ticket command —
addphoto, fixcat, setcat, toggleurgent, cancel, switchprop, mine, status — is
still 1:1 only; a group/room event never reaches any of those (see "Group is
report-only" below for the report exception's own rules: identity gate, parse
error, photo buffer/attach window and the compact confirmation reply). Code:
`app/services/staff_bot.py` (parser, palette
buttons, postback handlers), `app/services/housekeeping_client.py`
(create/patch/cancel/get/list work orders + the photo upload),
`app/services/staff_oa_service.fetch_message_content` (the one place
`api-data.line.me/v2/bot/message/{id}/content` is ever called).

**Identity.** The sender must resolve to an **active** employee via
`line_user_id`; a stranger gets one fixed line
(`ยังไม่รู้จักบัญชีนี้ค่ะ กรุณาเชื่อมบัญชี LINE กับ HF ID ก่อนแจ้งซ่อม`) and
nothing is created. The employee's `location` picks the property (`HF` →
`hf`, `HF_VILLE` → `hfville`, unset → `hf`, correctable afterwards with the
confirmation bubble's **สลับสาขา** button).

**Parsing.** Room: the first 3–4 digit token, alone or after `ห้อง` (`204`,
`ห้อง 204`, `1204`). No room number → an area keyword (`ล็อบบี้`/`lobby` →
lobby, `ทางเดิน`/`โถง` → corridor, `สระ` → pool, `ครัว` → kitchen,
`ซักรีด`/`ซักผ้า` → laundry, `ด้านนอก`/`ข้างนอก`/`ลานจอด`/`ที่จอดรถ`/`สวน` →
outside). Neither → one fixed line asking for the room number; nothing is
created. Category by keyword priority (aircon, tv, plumbing, electric,
furniture, else other — see `_CATEGORY_KEYWORDS` for the exact word lists).
`ด่วน` anywhere in the text sets urgent. The detail text is everything except
the room token, pictographs stripped, capped at 200 characters.

**Photos — never downloaded unless tied to a ticket.** Every image from a
linked sender is recorded as a bare **message id**, nothing else (no bytes,
no log line), for 90 seconds (`PHOTO_BUFFER_TTL_SECONDS`), keyed per
(chat, sender). Creating a ticket claims up to 6 of that sender's fresh
buffered ids in that chat and opens a 2-minute **attach window**
(`ATTACH_WINDOW_SECONDS`) for (chat, sender) → order id — every photo that
window lets through refreshes it, but it can never live past a 5-minute hard
cap (`ATTACH_WINDOW_HARD_CAP_SECONDS`). The **เพิ่มรูป** button (or postback
`cmd=addphoto&id=N`) reopens the window on an existing ticket. Only once a
photo is claimed or arrives inside an open window does the bot fetch its
bytes (`fetch_message_content`) and upload them
(`housekeeping_client.upload_photo`) — off the request path either way, but
see "Photo acknowledgements" below for how each of the two cases (claimed at
creation vs. arriving inside an open window) now differs.

**The confirmation bubble**, replied once its claimed photos' uploads have
resolved or timed out (see below): `รับเรื่องแล้ว #N`, branch, location,
category, urgency, detail, reporter, photo count, and five postback
buttons — **แก้หมวด** (a quick-reply of all six categories),
**ด่วน/ไม่ด่วน** (toggles), **เพิ่มรูป**, **ยกเลิก**, **สลับสาขา**. Every
button's tap is checked against the ticket's `reporterBadge` OR the tapper
holding the `reception` grant; anyone else gets
`แก้ได้เฉพาะผู้แจ้งค่ะ` and the housekeeping call is never made. `ยกเลิก`
additionally enforces (server-side, relayed verbatim) that only the reporter
may cancel, only while the ticket is still `new`, and only within 10 minutes
of creation. The palette's **แจ้งซ่อมใหม่** button (`cmd=report_help`) answers
a one-line how-to instead of opening anything.

**Photo acknowledgements** (owner request 2026-09-06: "add ack to photos
sent and received"). Two related but separate behaviors, both free-reply-
token only — every ack rides a reply to a photo event or an existing pending
reply, never a push:

- **Photos-first** (rule B): when photos are sent BEFORE `แจ้งซ่อม` and get
  claimed at ticket creation, the confirmation bubble now WAITS for their
  uploads — bounded by `CLAIMED_UPLOAD_WAIT_SECONDS` (10 s) — before it is
  replied, so the bubble's photo row reflects the real outcome instead of
  just "claimed": `รูป N รูป` for however many finished in time, plus
  `กำลังแนบอีก M รูป` for however many were still running at the 10 s mark,
  plus `แนบไม่สำเร็จ F รูป` for any failures, or `ยังไม่มีรูป` when nothing was
  claimed. The still-running ones are NOT cancelled — they keep uploading in
  the background exactly as before; when they finish, they produce no ack of
  their own, because a buffered photo never had a reply token of its own to
  answer with (silent, by design).
- **In-window acks** (rule A): a photo or video that arrives WHILE an order's
  attach window is open (the "silent attach" case — เพิ่มรูป, or more media
  after the ticket already exists) still attaches with no reply of its own at
  the moment it arrives, but once its upload resolves, the bot now answers on
  that event's own reply token: `แนบรูปเข้า #N แล้ว k รูป` and/or
  `แนบวิดีโอเข้า #N แล้ว v คลิป` — photos and videos are counted (and worded)
  SEPARATELY everywhere, see "Video support" below — followed by
  `(รวม t ไฟล์)` where `t` is the upload's own `photoCount + videoCount`
  (omitted when that total is not known), `แนบรูปไม่สำเร็จ f รูป
  ลองส่งใหม่อีกครั้งค่ะ (#N)` and/or `แนบวิดีโอไม่สำเร็จ f คลิป
  ลองส่งใหม่อีกครั้งค่ะ (#N)` on failure, or a mix of these as separate lines
  when a burst had more than one outcome. Several media sent together arrive
  as separate events a couple of seconds apart, so this coalesces like any
  other reply — `PHOTO_ACK_QUIET_SECONDS` (3 s) of quiet, the same 45 s cap as
  everything else — and a command typed into the same chat during that quiet
  window wins the impatient race (0 s) and carries the ack along in its own
  immediate reply. Photos/videos with no ticket to attach to (no attach
  window open) are never fetched and never acknowledged — they only ever join
  the 90-second buffer.

Housekeeping unreachable at any step: the one fixed line
`ระบบแจ้งซ่อมยังไม่เชื่อมต่อ ลองใหม่อีกครั้งภายหลัง` — buffered photos are left
untouched (they simply age out after 90 s) and nothing is half-created.

Logs, ids only, INFO: `staff-bot ticket created: chat=... order=... photos=N`,
`staff-bot ticket edited: order=... field=...`, `staff-bot ticket cancelled:
order=...`, `staff-bot photo attached: order=...`, `staff-bot photo failed:
order=... reason=download|upload`. No message text, no photo byte and no LINE
message id is ever written to a log line.

No new environment variables — this rides the same `HOUSEKEEPING_INTERNAL_URL`
/ `HOUSEKEEPING_STAFF_BOT_TOKEN` pair as the digest above, against the same
internal door's additional routes.

### งานของฉัน / สถานะ (phase 4)

The palette's **งานของฉัน** button (`cmd=mine`) and the bare word งานของฉัน
answer a Flex carousel of the tapper's own active tickets, newest first, at
most 10 bubbles (`housekeeping_client.list_work_orders(badge, active=True,
limit=10)`) — same identity gate as แจ้งซ่อม (`NOT_LINKED_TEXT` for a
stranger). Each bubble is `#id · <location>`, หมวด, สถานะ, อายุ (วันนี้ / n
วัน) and รูป n, with the same เพิ่มรูป/ยกเลิก postback buttons phase 3's
confirmation bubble uses. Nothing outstanding answers with one plain line
(`ไม่มีงานแจ้งซ่อมที่ค้างอยู่ค่ะ`); housekeeping dark answers the same fixed
"not connected" line as every other write/read here.

`สถานะ <id>` / `งาน <id>` (a strict "word, one space, digits" match — not a
prefix, so ordinary chat starting with งาน is never mistaken for it) answers
the same ticket as a single bubble, gated exactly like the edit postbacks:
the reporter or a `reception`-grant holder gets the bubble
(`ดูได้เฉพาะงานของตัวเองค่ะ` otherwise), an unknown id answers
`ไม่พบงาน #N ค่ะ`. This is a READ — no button or command in this chat ever
changes a ticket's status; that stays on the reception board in every phase.

### Reply-to-media (2026-09-06)

LINE marks a text message as a reply with `message.quotedMessageId`. Two
commands read it (`RoutedCommand.quoted_message_id`, parsed in `route_event`,
threaded onto the RoutedCommand for both — never logged, only the message id
is ever carried):

- **แจ้งซ่อม, as a reply** (1:1 only): the quoted photo/video — whoever
  originally sent it — is attached to the new ticket alongside anything
  already buffered, exactly like a claimed buffered photo (rule B's bounded
  `CLAIMED_UPLOAD_WAIT_SECONDS` wait; the confirmation bubble's photo row
  reflects the outcome once it resolves).
- **เพิ่มรูป #N** (text command, `^เพิ่มรูป\s*#?(\d{1,10})$` — bare in 1:1):
  same authorization as the `cmd=addphoto` postback (reporter or a
  `reception`-grant holder). **As a reply to a message**, the quoted media is
  fetched and attached right away (bounded wait, then the ack line replaces
  the placeholder). **Without a quote**, it behaves exactly as before: opens
  the attach window and replies `ส่งรูปหรือวิดีโอมาได้เลยค่ะ (ภายใน 2 นาที) #N`.

A quoted message whose content is neither `image/*` nor `video/*` (a quoted
TEXT message, say — LINE's content endpoint answers with something else, or
refuses outright) counts as one failed attach, the same line an ordinary
failed upload gets. The quoted item's kind is not known ahead of the fetch —
unlike a photo/video sent directly (see below), a quote is fetched once,
capped at `VIDEO_BYTES_MAX` (never unbounded — cleanup, 2026-09-06 review;
an oversize quote raises `ContentTooLarge` and is bucketed as a video
failure the same as an oversize declared video), and its kind decided from
the response's Content-Type; this means a quoted VIDEO skips the
transcoding wait (LINE's transcoding status is only meaningful for a
message LINE itself flagged as needing it) — if LINE has not finished
processing a just-sent, just-quoted video yet, the fetch fails and it counts
as a generic failed attach rather than the specific "still processing" line.

### Video support (2026-09-06)

`message.type == "video"` is buffered, claimed and attached exactly like an
image (the photo buffer's entries carry `kind`: `image` | `video`), with one
extra step: LINE transcodes a video server-side before its bytes are
downloadable at all.

- **Pipeline**: `staff_oa_service.wait_for_transcoding(message_id,
  VIDEO_TRANSCODE_WAIT_SECONDS)` polls `GET
  {DATA API}/v2/bot/message/{id}/content/transcoding` every 3 s
  (`{"status": "processing"|"succeeded"|"failed"}`) until it succeeds
  (`True`), or fails/times out (`False`, indistinguishable at this layer —
  both render the same line) → `fetch_message_content(message_id,
  VIDEO_BYTES_MAX)` (streamed, aborts past **60 MB** — raises
  `staff_oa_service.ContentTooLarge`, caught and rendered as its own line) →
  `housekeeping_client.upload_photo(..., mime)` with the mime LINE reported
  (`video/mp4` or `video/quicktime`; defaults to `video/mp4` for anything
  else) — a `video/*` mime gets `VIDEO_UPLOAD_TIMEOUT_SECONDS` (60 s) on
  that upload call rather than the plain `PHOTO_UPLOAD_TIMEOUT_SECONDS`
  (15 s): a video is both larger and slower to push through (cleanup,
  2026-09-06 review).
- **Failure lines** (rule A's own-token ack; rule B's bounded-wait bubble
  shows only the aggregate counts, not the specific reason): transcode
  failed/timed out → `วิดีโอประมวลผลไม่สำเร็จ ลองส่งใหม่อีกครั้งค่ะ (#N)`;
  oversize → `วิดีโอใหญ่เกินไป (สูงสุด 60 MB) (#N)`; any other upload failure →
  `แนบวิดีโอไม่สำเร็จ f คลิป ลองส่งใหม่อีกครั้งค่ะ (#N)` (the video-worded
  parallel of the existing photo failure line, since counts are separated
  everywhere now).
- **VIDEO_ACK_DEADLINE_SECONDS (40 s)**: a video's transcode can outlive an
  IN-WINDOW event's LINE reply token (LINE's tokens are short-lived; a
  transcode can take up to `VIDEO_TRANSCODE_WAIT_SECONDS` = 90 s). Past 40 s
  without an outcome, the bot files `วิดีโอกำลังประมวลผล จะแนบให้เมื่อพร้อมค่ะ
  (#N)` on that about-to-expire token and lets the upload keep going in the
  background — its eventual real outcome is **silent** (no second ack; the
  token was already spent). Finishing within 40 s answers the normal ack
  instead. A claimed/quoted video inside rule B's 10-second bounded wait is
  simpler: it almost always shows as still-running (`กำลังแนบอีก m ไฟล์`) at
  that mark, and its later completion is silent the same way a still-running
  photo's always was — it never had a reply token of its own to answer with.
- **Counts, everywhere**: photos and videos are counted and worded
  separately — the confirmation bubble's row says `รูป k รูป · วิดีโอ v คลิป`
  (a zero part omitted; `ยังไม่มีรูป` when both are zero), and so do the
  งานของฉัน/สถานะ bubbles. A claimed-but-not-yet-uploaded batch says
  `กำลังแนบ 2 รูป 1 คลิป` (per-kind, space-joined). A still-running count that
  is purely photos keeps saying `...N รูป` (unchanged from before video
  support); any video in the mix says `...N ไฟล์`.
- **Row label** (cleanup, 2026-09-06 review): the confirmation bubble's and
  the งานของฉัน/สถานะ bubble's media row is labelled **ไฟล์** whenever the
  order carries any video at all, else the original **รูป** —
  `_media_row_label` in `staff_bot.py`; the confirmation bubble's label is
  re-derived once the claimed batch settles, so a quoted attachment that
  turns out to be a video still ends up under ไฟล์ even though the
  claiming-time render (kind unknown yet) guessed รูป.
- **Works board**: `src/server/worksFeed.ts` in the housekeeping repo serves
  media bytes by id with the stored mime already — a video shows as a broken
  thumbnail there until it is updated to read the mime and render
  accordingly (noted, not fixed, in that repo's own README).

No new environment variables for either of the above — same
`HOUSEKEEPING_INTERNAL_URL` / `HOUSEKEEPING_STAFF_BOT_TOKEN` /
`STAFF_OA_CHANNEL_*` pairs as everything else in this section.

### Group is report-only, except one @mention command (owner policy,
2026-09-06, amended that evening)

Superseding phase 3's narrower "group silence" rule (which only suppressed
two specific ticket-nag replies), the owner's 2026-09-06 decision was
absolute: *"command through chat is considered spam in HF Family group —
10 people send commands in 1 chat room is bad."* That evening the owner
narrowly reopened one command: *"HF Family should be able to get mention and
act to create new maintenance ticket still."* In HF Family (or any
group/room) the bot's only voices are the scheduled slot report and this one
@mention ticket flow — every OTHER command, of any kind, from anybody,
summoned or bare, recognised word or not, text or media, from a stranger or a
linked employee alike, is still silently ignored. This is enforced
structurally in `route_event`: a group/room **postback** event always routes
to `None` (buttons stay dead there, see below), and a group/room **message**
event becomes a `RoutedCommand` (`COMMAND_REPORT`) ONLY when it carries an
explicit self-mention (`message.mention.mentionees[]` with `isSelf: true`)
whose remainder — the mention span stripped using LINE's own UTF-16
code-unit offsets, not Python string indices (`_strip_utf16_span`) — is
แจ้งซ่อม, bare or with a room/symptom; every other message, mentioned or not,
still becomes a plain `RoutedMessage`.

**The mention-report flow, rule by rule:**

- **Same parser, same ticket.** The text after แจ้งซ่อม is parsed exactly like
  the 1:1 form (room/area, category, urgent, detail) and creates the same
  housekeeping work order.
- **Same identity gate.** An unlinked sender's mention-report gets
  `NOT_LINKED_TEXT` once, exactly like a 1:1 stranger. A mention with no
  room/area gets `PARSE_ERROR_NO_ROOM_TEXT` once, exactly like a 1:1 parse
  error.
- **Photos are buffered again for a group sender** (ids only, 90 s TTL, never
  downloaded) so a mention-report can claim media the same sender sent just
  before it; a ticket created from the mention opens the same 2-minute attach
  window as 1:1 for media sent right after, and reply-to-media (a quoted
  message) attaches too. Media from an unlinked sender, or never tied to any
  ticket, stays unfetched — never buffered, never downloaded.
- **The confirmation reply is deliberately lean — a compact TEXT, not the
  1:1 Flex bubble.** Group postbacks stay ignored, so the fixcat/toggleurgent/
  addphoto/cancel/switchprop buttons on the 1:1 bubble would be dead weight in
  a group; `build_group_confirmation_text` instead replies one line —
  `รับเรื่องแล้ว #N · <สาขา> · <ที่> · <หมวด> · <ด่วน|ปกติ> · <รูป/วิดีโอ นับ>` —
  plus `แก้ไขหรือดูสถานะได้ในแชทส่วนตัวกับ HF ภายใน` pointing the reporter back
  to their 1:1 chat for anything else (edit, cancel, more photos, status). The
  same photos-first bounded wait (`CLAIMED_UPLOAD_WAIT_SECONDS`, 10 s) as the
  1:1 bubble applies first, so the counts shown are real, not a
  claimed-but-unconfirmed guess. Photo/video acks for the attach window still
  use the existing coalesced ack lines, unchanged.
- **Still a command, never a heartbeat.** A mention-report never files or
  promotes a slot mark and never counts as the slot heartbeat — it is routed
  as a `RoutedCommand` from the start, so it never reaches
  `_maybe_file_slot_digest` at all (same structural rule that keeps every
  other command out of the slot machinery).

**Unaffected in 1:1** — a stranger or a parse error there still gets the
fixed line, exactly as always, via the ordinary (non-mention) `แจ้งซ่อม`
path. The webhook logs a group/room drop at
**DEBUG only** (never INFO — a group is told nothing and the log stays
quiet by default too): `staff-bot group ignored: type=message|postback
chat=<chat id>` — never the message text, never the sender.

## Guest feedback (ความคิดเห็นลูกค้า)

Since guest-feedback `docs/CONTRACTS.md` §15 rev 3 ("the Employee Hub bot is
the ONLY responder"), the staff bot is the sole sender for guest feedback
raised on the public feedback site. Earlier revisions had guest-feedback hold
its own LINE token, then (PR #28/#30) had this webhook relay LINE events to
it fire-and-forget — both are retired. The bot now reads and confirms guest
feedback from guest-feedback itself, server-to-server, and answers only with
its own reply tokens, exactly like the housekeeping digest above. Rev 3.1
(2026-09-06) widened the queue from requests-only to **every** guest
submission — praise, issue and request alike.

**Consolidated into the slot report (2026-09-06)**, superseding the
chatter-triggered group auto-offer phase 3 shipped: the ONLY place a group
ever sees pending guest feedback is section (b) of its own scheduled slot
report (see "The slot report" above) — never from ordinary chat, pending or
not, summoned or bare. A 1:1 `คำขอ` still renders the identical report-style
text as a PREVIEW, and still never confirms delivery.

| | |
|---|---|
| Code | `app/services/guest_feedback_client.py` (`fetch_pending`, `confirm_delivered`); rendering (`render_feedback_section`, `render_requests`, `render_slot_digest`) and command handling in `app/services/staff_bot.py` |
| Read | `GET {GUEST_FEEDBACK_BASE_URL}/api/internal/line/pending` — `X-Reader-Secret: <GUEST_FEEDBACK_READER_SECRET>`, 2 s timeout |
| Confirm | `POST {GUEST_FEEDBACK_BASE_URL}/api/internal/line/delivered` — `{"ids": [...], "method": "reply"}` |
| Contract of record | guest-feedback `docs/CONTRACTS.md` §15 rev 3, widened by rev 3.1 |

**Rendering (2026-09-06 consolidation).** Both the slot report's section (b)
and the 1:1 preview render the SAME report-style text
(`render_feedback_section`) built from the pending JSON's `items[]` —
never guest-feedback's own chat-style `text` field any more:

```
ความคิดเห็นลูกค้า (3 รายการ)
ด่วน ปัญหา · HF ห้อง 412 · น้ำไม่ร้อน — "Sometimes scalding"
คำชม · HF ห้อง 310 · พนักงานเป็นมิตร, ทำเลดี — "พนักงานน่ารักมากค่ะ"
คำขอ · HF Ville ห้อง 112 · ขอทำความสะอาดห้อง
```

One line per item: `<ด่วน ><kind label> · <branch><location> · <short text>`
— kind labels `praise`→คำชม, `issue`→ปัญหา, `request`→คำขอ (any other kind
falls back to its raw value); branch label `hf`→HF, `hfville`→HF Ville
(matches guest-feedback's own `branchShort`); the short text is `tagsTh`
joined by `, ` plus an optional quoted `comment`, pictographs stripped and
capped at 80 characters. Capped at **15 lines**, then `และอีก m รายการ` for
the rest (`m` = the fetch's total `count` minus the 15 shown). The whole
combined text (both sections, in a slot report) is still capped at LINE's
5000-char message limit (`_fit`).

**1:1 `คำขอ` is a preview, never a confirm.** Same rendering, but the reply
**never confirms delivery** — it is someone checking privately, not the
group being told. `render_requests` maps a dark/unreachable read to
`"ยังอ่านความคิดเห็นลูกค้าไม่ได้ค่ะ ลองใหม่อีกครั้ง"` and a reachable read with
nothing pending to `"ยังไม่มีความคิดเห็นใหม่ค่ะ"`.

**Delivery confirm.** Once LINE has **accepted** a slot report or a group/room
reply that carried the feedback section, the bot calls `confirm_delivered`
with the feedback ids from the same fetch that rendered it — marking those
rows delivered on guest-feedback's side so they are not offered again. A
reply LINE rejects, or a 1:1 preview, never confirms anything.

### Env

```
GUEST_FEEDBACK_BASE_URL=http://feedback:4080
GUEST_FEEDBACK_READER_SECRET=<shared with guest-feedback's LINE_READER_SECRET>
```

**Either empty/unset ⇒ dark**: nothing is dialed, and every guest-feedback
read answers the fixed "ยังอ่านความคิดเห็นลูกค้าไม่ได้ค่ะ ..." line. The URL is not a
secret (container-to-container, no Cloudflare Access in the path) and has
**no built-in default** (unlike `HOUSEKEEPING_INTERNAL_URL`); it rides the
deploy as the GitHub **variable** `GUEST_FEEDBACK_BASE_URL`, the secret as the
GitHub **secret** `GUEST_FEEDBACK_READER_SECRET`. Both are in the
`env_payload` of `.github/workflows/build.yml` and in `docker-compose.yml` —
do not hand-edit the host `.env`, every deploy rewrites it. The secret is
**not** `READER_SECRET`, despite sharing the header name.

### Console prerequisite for the group

The staff bot only sees group chat at all once a human has invited the OA
into the staff LINE group — there is no API for this — and the console is
configured to allow it:

1. **LINE Developers console → the staff OA's Messaging API tab**: *Allow bot
   to join group chats* **ON**.
2. **LINE Official Account Manager → Settings**: *Allow account to join groups
   and multi-person chats* **ON** (the same permission, second switch — the OA
   Manager one wins, and it defaults OFF).
3. **Both webhook toggles ON**: *Use webhook* in the Developers console **and**
   *Webhooks* under OA Manager → Response settings. Either one off and no group
   event is delivered at all.
4. **Auto-reply and greeting messages OFF** (OA Manager → Response settings) —
   otherwise the OA answers every group message on its own and burns the reply.

## Images

2500x843 (≤3 buttons) or 2500x1686 (4–8 buttons, `MAX_BUTTONS` — the Hub's
own layout ceiling; LINE itself allows up to 20 rich-menu areas), PNG, well
under LINE's 1MB cap. Thai labels use the bundled **Prompt** font
(`assets/fonts/`, SIL OFL 1.1 — license alongside). Icons are pixel-exact
crops of owner-approved HF Internal artwork, never drawn or generated in
code — see `assets/staff_oa/icons/README.md` for provenance and the
glyph→asset fit table. Preview without credentials:

```bash
python scripts/staff_oa_render_menus.py --out /tmp/staffhub-previews
```

Bump `IMAGE_STYLE_VERSION` in `staff_oa_menu.py` after changing the
artwork so the sync re-creates menus whose buttons are otherwise unchanged.

## Mind the push cap

The LINE free tier caps **proactive push** messages (~300/mo). Rich-menu
taps and webhook replies are free — keep notifications riding replies or
the existing channels until a paid tier is decided.
