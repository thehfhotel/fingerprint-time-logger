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
| Event forward to guest-feedback (group relay + 1:1 preview) | `app/services/staff_oa_service.py` → `forward_group_events*` |
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
`message`, `postback` and `join`, and **forwards** group events — plus 1:1
`message` events, ids only — to guest-feedback (further below). Everything
else is ignored. Per-event failures
are logged but never fail the delivery (LINE would retry the whole batch), and
a delivery marked `deliveryContext.isRedelivery` is dropped by the bot so a
LINE retry cannot double-post.

## The staff bot (HF ภายใน)

**Reply-token arbitration.** A LINE reply token is single-use, and this
webhook has two consumers: the staff bot (debounced replies) and the
guest-feedback relay (`GUEST_FEEDBACK_LINE_*`, dark until configured). The
bot files intent first; any event whose token it has claimed — a command, or
ordinary chat in a chat where a reply is already pending (the bot moves to the
newer token) — is still relayed to guest-feedback, but with `replyToken:
null`, meaning "no reply window on this one, wait for the next message". One
consumer per token, decided in the webhook, never by a race between two
senders. See `staff_bot.handle_event_detail` and
`staff_oa_service.group_event_forward_payload(withhold_reply_token=...)`.


The OA answers questions in the all-staff LINE group and in 1:1 chats.
Design authority: hf-erp ADR *"The staff bot answers only with reply tokens;
LINE meters pushes per recipient"*. Code: `app/services/staff_bot.py`
(router, palette, digest, debounce) and `app/services/housekeeping_client.py`
(the one outbound read).

### Summoning it

| Where | What to type | What comes back |
|---|---|---|
| Staff group | `น้องคะ` / `น้องค่ะ` / `น้องครับ` / `น้องคับ` (a space after น้อง is fine), or @-mention the OA | the palette bubble |
| Staff group | the same summon followed by `งานค้าง` (also `งานซ่อมค้าง`, `แจ้งซ่อมค้าง`) | the digest |
| 1:1 chat | `งานค้าง` on its own | the digest |
| 1:1 chat | anything else | the palette bubble |
| anywhere | tapping the palette's **งานค้าง แจ้งซ่อม** button (`cmd=digest`) | the digest |

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

### It waits for quiet (debounce)

People type in bursts, so the bot never answers the message it was summoned
by. A command opens a pending reply; every later message in that chat hands it
a fresher reply token and restarts the timer. It answers after **15 s of quiet
in a group** (2 s in a 1:1) and at the latest **45 s** after the first
trigger — reply tokens are short lived, so that cap is not optional. Two
commands in one burst coalesce into a single reply carrying both messages.

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

## Events forwarded to guest-feedback

LINE allows exactly **one Official Account per group chat**. The staff LINE
group hosts the staff OA above, so the guest-feedback app
(`feedback.thehfhotel.org`, repo `guest-feedback`) cannot be invited into the
same group and cannot receive its webhook. This webhook relays the events it
does not handle itself, and guest-feedback replies into the group using the
**staff OA's** channel access token. Contract of record: guest-feedback
`docs/CONTRACTS.md` §15.4 (the group relay) and §15.5 (the 1:1 preview).

| | |
|---|---|
| Sender | `app/api/staff_oa.py` → `app/services/staff_oa_service.py` (`forward_group_events*`) |
| Receiver | `POST http://feedback:4080/api/internal/line/event` over the shared-nginx Docker network |
| Auth | `X-Reader-Secret: <GUEST_FEEDBACK_LINE_SECRET>` (constant-time compare on the far side; 401 on mismatch) |
| Forwarded | `source.type == "group"` **and** type in `message`, `join`, `memberJoined`, `leave`; `source.type == "user"` **and** type `message` |
| Group payload | `{"type", "replyToken", "timestamp", "groupId", "channel": "staff-oa"}` |
| 1:1 payload | `{"type", "replyToken", "timestamp", "userId", "groupId": null, "channel": "staff-oa"}` |

Deliberate properties, each covered by a test:

- **No message text, ever.** For a GROUP event no `userId` crosses either —
  staff chatter and who said it never leave this app; only the group id and
  the reply token do.
- **1:1 `message` events cross as ids only** (see below). A multi-person
  `room` still forwards nothing, and `follow`/`unfollow` are never forwarded:
  they are the Employee Hub's own events, handled by the follow path above
  and unchanged by any of this.
- **Fire-and-forget on a daemon thread**, 2 s timeout, every failure logged
  and swallowed. It cannot delay or fail the webhook's `200` — a delivery
  LINE counts as failed is retried, and a wedged staff channel would cost far
  more than a missed guest request. (A FastAPI `BackgroundTasks` would NOT do:
  Starlette runs those inside the same ASGI call, so a slow peer would still
  hold the response.)
- **Follow handling is untouched**, and forwarding is a separate darkness
  switch from the OA credentials.

### 1:1 messages: a private preview for an allowlisted manager

Since 2026-09-05 a `message` event from a **1:1 chat** (`source.type ==
"user"`) is forwarded too, reduced to `{"type": "message", "replyToken",
"timestamp", "userId", "groupId": null, "channel": "staff-oa"}` — the ids and
the reply window, never the text. The point is a private preview: a manager
whose LINE user id guest-feedback has allowlisted (`LINE_PREVIEW_USER_IDS`,
its env, not ours) can message the OA directly and get the pending guest
requests back in that chat, instead of testing the relay by posting into the
staff group. `groupId: null` is what tells guest-feedback to answer the
person rather than the group; the allowlist decision, and the ignoring of
anyone not on it, happen entirely on the far side — this app forwards every
1:1 message id-only and knows nothing about who may preview. Contract of
record: guest-feedback `docs/CONTRACTS.md` §15.5.

> **Known limitation — the reply token.** A LINE reply token is single-use,
> so an event whose token the staff bot (`app/services/staff_bot.py`) has
> claimed crosses with `replyToken: null`. In a group that is rare; in a 1:1
> the bot answers **every** text message it is sent, so nearly every 1:1
> event will reach guest-feedback without a reply window and its preview
> reply will be skipped. Whichever way that is resolved — the bot yielding
> 1:1 tokens, or guest-feedback pushing instead of replying — is a decision
> for the owner and a separate change; what ships here is the relay, and the
> rule that exactly one sender ever holds a token.

### Env

```
GUEST_FEEDBACK_LINE_URL=http://feedback:4080/api/internal/line/event
GUEST_FEEDBACK_LINE_SECRET=<shared with guest-feedback's LINE_FORWARD_SECRET>
```

**Empty/unset URL ⇒ dark**: no reduction, no thread, no request. The URL is
not a secret (container-to-container, no Cloudflare Access in the path) and
rides the deploy as the GitHub **variable** `GUEST_FEEDBACK_LINE_URL`; the
secret is the GitHub **secret** `GUEST_FEEDBACK_LINE_SECRET`. Both are in the
`env_payload` of `.github/workflows/build.yml` and in `docker-compose.yml` —
do not hand-edit the host `.env`, every deploy rewrites it. The secret is
**not** `READER_SECRET`, despite sharing the header name.

### Console prerequisites for the group

The group side is console configuration, not code — the forward stays silent
until all of this is true:

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
5. **A human invites the OA into the staff group.** There is no API for this.
   guest-feedback learns the group id from the `join`/`memberJoined` event this
   forwarder relays; nothing needs to be configured with the group id by hand.

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
