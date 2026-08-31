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

Four variants exist: `base` (**0 buttons**), `base+housekeeping` (4),
`base+reception` (1) and `base+housekeeping+reception` (5). LINE caps a rich
menu at 6 buttons, so the maximal variant has one tile of headroom left.

**สถานะห้อง and แม่บ้าน open the same board.** That is deliberate: `reception`
is a READ-ONLY viewer on `/hk`. new-hotel's `hk_access` middleware admits
either grant, but the write verbs (`POST .../cleaning`,
`POST .../linen-shortage`) require `housekeeping` and answer a reception-only
identity with a 403; `GET /api/hk/me` returns `canReport: false` so the UI
hides the reporting controls. The UI hiding is UX — **the server is the
enforcement.** An employee holding both grants is full-access and simply sees
five tiles, the first and last pointing at the same page.

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

Other events are ignored. Per-event failures are logged but never fail the
delivery (LINE would retry the whole batch).

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
