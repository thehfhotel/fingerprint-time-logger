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

Everyone gets the base buttons; grants in `employee_app_grants`
(Employee Management) reveal extras:

| Button | URL | Needs grant |
|---|---|---|
| สแกนเข้างาน (QR clock-in) | https://erp.thehfhotel.org/qr-checkin | — |
| เบิกค่าใช้จ่าย (Reimbursement) | https://reimbursement.thehfhotel.org | —\* |
| เงินเดือน (Payroll) | https://payroll.thehfhotel.org | `payroll` |
| OTA Desk | https://ota.thehfhotel.org | `ota` |
| แม่บ้าน (Housekeeping) | https://hotel.thehfhotel.org/hk | `housekeeping` |

\* The menu button itself is unchanged (base button, no grant needed to see
it). But since reimbursement retired its own LINE login (2026-07),
`reimbursement.thehfhotel.org` is now gated by Cloudflare Access checking
the `apps` claim for the `reimbursement` grant — default-granted at
onboarding, so most employees never notice, but an ungranted employee who
taps through hits Cloudflare's block page.

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
5. Re-run `--apply` whenever grants change (or call
   `staff_oa_service.link_role_menu_for_line_user()` for one user).
   Employees who follow the OA are linked automatically by the webhook.

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
