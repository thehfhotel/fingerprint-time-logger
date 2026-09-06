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
launcher. **Every button is behind a grant** — there are no base buttons:

| Button | URL | Needs grant |
|---|---|---|
| แม่บ้าน (cleaning board) | https://hotel.thehfhotel.org/hk | `housekeeping` |
| แจ้งซ่อม (breakage report) | https://housekeeping.thehfhotel.org/staff/report | `housekeeping` |
| สต๊อกของ (stock count / purchase request) | https://housekeeping.thehfhotel.org/staff/stock | `housekeeping` |
| รับของมาส่ง (receive a delivery) | https://housekeeping.thehfhotel.org/staff/receive | `housekeeping` |
| สถานะห้อง (room status, read-only) | https://hotel.thehfhotel.org/hk | `reception` |
| รายงานแม่บ้าน (daily room report) | https://hotel.thehfhotel.org/hk/report | `housekeeping` **or** `reception` |

Four variants exist: `base` (**0 buttons**), `base+reception` (2),
`base+housekeeping` (5) and `base+housekeeping+reception` (6). LINE caps a
rich menu at 6 buttons, so as of 2026-09-02 the maximal variant sits exactly
ON the cap — **there is no headroom left.** A seventh tool cannot be a seventh
tile: it needs one removed, or two merged behind one tile. Adding a row to
`MENU_BUTTONS` anyway does not fail loudly at deploy time — the over-cap
guards in `scripts/staff_oa_sync.py` and `app/services/staff_oa_provision.py`
would UNLINK everyone holding both grants (the owner included) and log a
warning.

**รายงานแม่บ้าน is a SHARED tile** — one row in `MENU_BUTTONS` revealed by
either grant (`MenuButton.also_grant_app_ids`), because a room report is
two-sided: the maid files it (status code, equipment exceptions, 1–4 photos)
and reception verifies it with 1–4 photos of their own, or returns it with a
canned reason. Both halves are the same screen. An employee holding both
grants sees it **once**, not twice — that is what the one-row model
guarantees, and what two rows would have got wrong.

**สถานะห้อง and แม่บ้าน open the same board.** That is deliberate: `reception`
is a READ-ONLY viewer on `/hk`. new-hotel's `hk_access` middleware admits
either grant, but the write verbs (`POST .../cleaning`,
`POST .../linen-shortage`) require `housekeeping` and answer a reception-only
identity with a 403; `GET /api/hk/me` returns `canReport: false` so the UI
hides the reporting controls. The UI hiding is UX — **the server is the
enforcement.** An employee holding both grants is full-access and simply sees
six tiles, two of which point at the same board.

The same argument covers รายงานแม่บ้าน, which both grants open: new-hotel
enforces the roles server-side per verb — submitting a report is maid-only
(the `canReport: true` side), verify and return are reception-only, and a maid
who also holds `reception` still cannot verify her own work. The tile is a
launcher, never an authorization.

### `base` is deliberately empty — no-menu semantics

An employee holding NEITHER `housekeeping` nor `reception` gets **no rich
menu at all**. That is the intended meaning of a grant-only Hub, and the sync
handles it explicitly rather than by accident:

- no `base` rich menu is created;
- the **channel default is cleared** (`clear_default_rich_menu`), so it
  never dangles at a menu that stale-deletion is about to remove;
- employees on the `base` variant are **unlinked**
  (`bulk_unlink_rich_menu`), not left pointing at a doomed menu;
- the follow webhook still replies to an unknown follower with the
  onboarding pointer even though it links no menu — that reply is the only
  onboarding route a new follower gets.

Ordering matters: clearing the default happens **before** stale-menu
deletion. Reversing it opens a window where the channel default names a
deleted menu.

The `>6-button` guard in `staff_oa_sync.py` is unrelated to this and stays.
It is insurance: nothing a real employee can hold overflows LINE's 6-button
cap today (max variant is 2 buttons), but any future button can put us back
there.

**Consequence when applying:** issuing `housekeeping` grants and running
`staff_oa_sync.py --apply` should happen in ONE operation. Applying the
sync first leaves every linked employee with no menu until the grants land.

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
`upload_rich_menu_image`), then links them to it. No buttons (the empty
`base` case, i.e. no `housekeeping` grant) ⇒ it **unlinks** instead, so a
revocation is as automatic as a grant.

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


The OA answers questions in the all-staff LINE group and in 1:1 chats.
Design authority: hf-erp ADR *"The staff bot answers only with reply tokens;
LINE meters pushes per recipient"*. Code: `app/services/staff_bot.py`
(router, palette, digest, requests, debounce),
`app/services/housekeeping_client.py` (the แจ้งซ่อม read) and
`app/services/guest_feedback_client.py` (the guest-feedback read/confirm).

### Summoning it

| Where | What to type | What comes back |
|---|---|---|
| Staff group | `น้องคะ` / `น้องค่ะ` / `น้องครับ` / `น้องคับ` (a space after น้อง is fine), or @-mention the OA | the palette bubble |
| Staff group | the same summon followed by `งานค้าง` (also `งานซ่อมค้าง`, `แจ้งซ่อมค้าง`) | the digest |
| Staff group | the same summon (or a bare command word) followed by `คำขอ` / `คำขอลูกค้า` / `guest requests` / `ความคิดเห็น` / `ฟีดแบค` / `feedback` | the pending guest feedback |
| Staff group | any ordinary message, no summon at all, **while guest feedback is pending** | the pending guest feedback (see below) |
| Staff group | **bare** `แจ้งซ่อม <ห้อง/พื้นที่> <อาการ>`, **no summon** (owner decision 2026-09-06) — unless it STARTS WITH a digest word (`แจ้งซ่อมค้าง`, prefix match — reviewer finding, so "แจ้งซ่อมค้าง 204 ยังไม่มาเลย" stays chat too, not only the bare word alone), the remainder contains a completion phrase (`เสร็จแล้ว`/`เสร็จ`/`แล้วนะ`/`แล้วค่ะ`/`แล้วครับ`/`เรียบร้อย`/`ซ่อมแล้ว`/`แก้แล้ว`/`ทำแล้ว`), or the remainder has no room/area — any of those three stays ordinary chat, silently | the same แจ้งซ่อม ticket flow as the summoned form (see below) |
| 1:1 chat | `งานค้าง` on its own | the digest |
| 1:1 chat | `คำขอ` / `คำขอลูกค้า` / `guest requests` / `ความคิดเห็น` / `ฟีดแบค` / `feedback` on its own | a **preview** of the pending guest feedback |
| 1:1 chat | anything else | the palette bubble |
| anywhere | tapping the palette's **งานค้าง แจ้งซ่อม** button (`cmd=digest`) | the digest |
| anywhere | tapping the palette's **ความคิดเห็นลูกค้า** button (`cmd=requests`) | the pending guest feedback |

`น้อง` without one of the four particles is ordinary chat — "น้องเอาข้าวไหม"
never wakes the bot. In a 1:1 chat the sender must resolve to an **active**
employee via `line_user_id`; an unknown account gets the same Q-badge
onboarding reply a stranger's `follow` gets, and nothing else.

### Zero metered messages

Every reply rides the webhook's **reply token**, which LINE does not count at
any chat size. A *push* into the staff group would be metered **per member**
(one send to 17 people = 17 messages) against an allowance of ~300/month — see
"Mind the push cap" below. No push, multicast, broadcast or narrowcast exists
anywhere in this feature, and none may be added to it.

### Commands answer at once; scheduled digests wait for quiet

A summon, a command word or a palette tap is answered **immediately**
(`COMMAND_QUIET_SECONDS = 0`). The owner's rule (2026-09-05): "15 seconds of
quiet is for scheduled reports, not for the command reply."

The wait-for-quiet machinery (`ReplyDebouncer`) exists for the **phase 2 slot
digest**, which piggybacks on reception's hourly report and must never land in
the middle of that burst: it waits for **15 s of quiet** (`SLOT_QUIET_SECONDS`)
in the chat, every later message hands it a fresher reply token and restarts
the timer, and it fires at the latest **45 s** after the first trigger — reply
tokens are short lived, so that cap is not optional. Commands filed in the same
instant for one chat still coalesce into a single reply.

### The slot digest (phase 2)

Four Bangkok windows a day, in **groups only** (rooms and 1:1 chats never have
one), each carrying the same งานค้าง digest **once**, under one extra line:
`สรุปงานซ่อมค้างประจำรอบ<เช้า|เที่ยง|บ่าย|ค่ำ>`.

| Slot | Window (Bangkok, start inclusive / end exclusive) | Label |
|---|---|---|
| `morning` | 06:00 – 10:00 | เช้า |
| `noon` | 12:00 – 14:00 | เที่ยง |
| `afternoon` | 14:30 – 16:30 | บ่าย |
| `night` | 19:30 – 21:30 | ค่ำ |

The window is decided by the **event's own timestamp** (LINE's epoch-ms
`timestamp`, converted to Bangkok), not by the server clock at send time.

**What opens a window.** Any ordinary (non-command) message in the group, of any kind (text, sticker, photo, video, location; owner rule 2026-09-06: stickers count):

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
message re-triggers: the send failed, housekeeping was dark (a scheduled post
must never spam `ระบบงานซ่อมยังไม่เชื่อมต่อ` into the group four times a day;
it says nothing at all instead), or a `pending` older than 120 s was left
behind by a process that died mid-debounce.

**Interaction with commands.** A command typed while a slot digest is waiting
wins on timing (quiet 0) and the reply carries the slot-labelled digest with
it, one digest per reply, never two. And a plain `งานค้าง` answered inside an
unmarked window marks that slot `sent` too, so no near-duplicate follows a few
minutes later.

Logs, ids only, INFO: `staff-bot slot filed: group=... date=... slot=...
trigger=reception|late`, `staff-bot slot sent: ...`, `staff-bot slot dropped:
... reason=send_failed|housekeeping_dark|stale`.

No new environment variables: the behaviour is live for every group the OA is
in as soon as this deploys.

### Privacy rule

The webhook sees every message in the staff group. Non-command chat is
discarded **before any logging** — no text, no photo, no sender. A recognised
command logs exactly three fields: event type, source type, chat id. The first
`join` logs the group id once (`staff-bot joined group C...`), which is how
the rollout learns it. Nothing else about a message is ever written down.

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

### แจ้งซ่อม from chat (phase 3)

A linked employee raises a ticket without leaving LINE: `แจ้งซ่อม <ห้อง/พื้นที่>
<อาการ>` after the summon in the group, bare in a 1:1, or — since 2026-09-06 —
**bare in the group too**, gated by two safeguards so ordinary chat never
files a junk ticket: (1) the remainder after `แจ้งซ่อม` must not contain a
completion/status phrase (`BARE_REPORT_SKIP_PHRASES` — `เสร็จแล้ว`, `เสร็จ`,
`แล้วนะ`, `แล้วค่ะ`, `แล้วครับ`, `เรียบร้อย`, `ซ่อมแล้ว`, `แก้แล้ว`, `ทำแล้ว`, checked
as a substring anywhere in the remainder), and (2) it must parse to a room or
area (`parse_report`) — a bare message that fails either check is left as
ordinary chat, **silently** (no PARSE_ERROR reply, unlike the summoned form).
A digest word as a PREFIX of the message (`แจ้งซ่อมค้าง`, not only an exact
match — reviewer finding, so a digest word followed by more text is caught
too) is excluded up front and keeps needing a summon, exactly as before. A
bare report that clears both checks is routed as
the identical `COMMAND_REPORT` the summoned form produces — same identity
gate, ticket creation, photo claiming/attach window, confirmation bubble and
logging — and, being a command, it never counts as slot-trigger chatter
(`_maybe_file_slot_digest` is not reached for it, same as any other command).
No new environment variable; live for every group as soon as this deploys.
Code: `app/services/staff_bot.py` (parser, palette buttons, postback handlers),
`app/services/housekeeping_client.py` (create/patch/cancel/get/list work
orders + the photo upload), `app/services/staff_oa_service.fetch_message_content`
(the one place `api-data.line.me/v2/bot/message/{id}/content` is ever called).

**Identity.** The sender must resolve to an **active** employee via
`line_user_id`, in the group and in 1:1 alike; a stranger gets one fixed line
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
- **In-window acks** (rule A): a photo that arrives WHILE an order's attach
  window is open (the "silent attach" case — เพิ่มรูป, or more photos after
  the ticket already exists) still attaches with no reply of its own at the
  moment it arrives, but once its upload resolves, the bot now answers on
  that photo event's own reply token: `แนบรูปเข้า #N แล้ว k รูป (รวม total รูป)`
  on success (the parenthesis is omitted when the upload's response did not
  carry a photo count), `แนบรูปไม่สำเร็จ f รูป ลองส่งใหม่อีกครั้งค่ะ (#N)` on
  failure, or both as two lines when some of a burst succeeded and some
  failed. Several images sent together arrive as separate events a couple of
  seconds apart, so this coalesces like any other reply —
  `PHOTO_ACK_QUIET_SECONDS` (3 s) of quiet, the same 45 s cap as everything
  else — and a command typed into the same chat during that quiet window
  wins the impatient race (0 s) and carries the ack along in its own
  immediate reply. Photos with no ticket to attach to (no attach window
  open) are never fetched and never acknowledged — they only ever join the
  90-second buffer.

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

## Guest feedback (ความคิดเห็นลูกค้า)

Since guest-feedback `docs/CONTRACTS.md` §15 rev 3 ("the Employee Hub bot is
the ONLY responder"), the staff bot is the sole sender for guest feedback
raised on the public feedback site. Earlier revisions had guest-feedback hold
its own LINE token, then (PR #28/#30) had this webhook relay LINE events to
it fire-and-forget — both are retired. The bot now reads and confirms guest
feedback from guest-feedback itself, server-to-server, and answers only with
its own reply tokens, exactly like the housekeeping digest above. Rev 3.1
(2026-09-06) widened the queue from requests-only to **every** guest
submission — praise, issue and request alike — and every one of them is
relayed to the staff group on the bot's next free reply token, same as
before.

| | |
|---|---|
| Code | `app/services/guest_feedback_client.py` (`fetch_pending`, `confirm_delivered`); command handling in `app/services/staff_bot.py` |
| Read | `GET {GUEST_FEEDBACK_BASE_URL}/api/internal/line/pending` — `X-Reader-Secret: <GUEST_FEEDBACK_READER_SECRET>`, 2 s timeout |
| Confirm | `POST {GUEST_FEEDBACK_BASE_URL}/api/internal/line/delivered` — `{"ids": [...], "method": "reply"}` |
| Contract of record | guest-feedback `docs/CONTRACTS.md` §15 rev 3, widened by rev 3.1 |

**The command.** `คำขอ` / `คำขอลูกค้า` / `guest requests` / `ความคิดเห็น` /
`ฟีดแบค` / `feedback` (with or without a summon in a group; on its own in a
1:1) and the palette's **ความคิดเห็นลูกค้า** button (`cmd=requests`) all
render guest-feedback's own pre-formatted `text` as-is when `count > 0`,
`"ยังไม่มีความคิดเห็นใหม่ค่ะ"` when the read succeeds with nothing pending, and
`"ยังอ่านความคิดเห็นลูกค้าไม่ได้ค่ะ ลองใหม่อีกครั้ง"` on any failure (either env
unset, timeout, non-2xx, malformed body) — the bot never shows a status code
and never goes silent. Items carry `kind` (`praise`/`issue`/`request`) and
`urgent`, but the bot relays guest-feedback's pre-formatted `text` unchanged
and does not branch on either field — the gate/confirm logic is kind-agnostic.

**Group auto-offer.** Unlike the digest, a **plain group message with no
summon at all** also triggers this command — but only when guest-feedback
reports something pending. Every non-summon group message checks (through
`staff_bot.PendingRequestsGate`, cached **10 s per chat** so ordinary chatter
cannot hammer the endpoint); if pending feedback exists, that message becomes
a `COMMAND_REQUESTS` reply under the same immediate-answer rule as any other
command (`COMMAND_QUIET_SECONDS = 0`). A summon is unaffected either way — it
already produces a command before this check ever runs.

**1:1 is a preview, never a confirm.** In a 1:1 chat `คำขอ` renders the exact
same list, but the reply **never confirms delivery** — it is someone checking
privately, not the group being told. Confirmation only follows a reply that
went to a **group or room**.

**Delivery confirm.** Once LINE has **accepted** a group/room reply that
included the guest-feedback text, the bot calls `confirm_delivered` with the
feedback ids from the same fetch that rendered the text — marking those rows
delivered on guest-feedback's side so they are not offered again. A reply
LINE rejects, or a 1:1 reply, never confirms anything.

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

2500x843 (≤3 buttons) or 2500x1686 (4–6 buttons), PNG, well under LINE's
1MB cap. Thai labels use the bundled **Prompt** font
(`assets/fonts/`, SIL OFL 1.1 — license alongside). Preview without
credentials:

```bash
python scripts/staff_oa_render_menus.py --out /tmp/staffhub-previews
```

Bump `IMAGE_STYLE_VERSION` in `staff_oa_menu.py` after changing the
artwork so the sync re-creates menus whose buttons are otherwise unchanged.

## Mind the push cap

The LINE free tier caps **proactive push** messages (~300/mo). Rich-menu
taps and webhook replies are free — keep notifications riding replies or
the existing channels until a paid tier is decided.
