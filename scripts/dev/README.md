# Local dev loop (screenshot-driven UI work)

Run the FastAPI app on a spare port against a seeded, throwaway SQLite
database — no ZKTeco device, no Cloudflare Access, no deploy — then
screenshot any page so a UI agent can self-inspect its work.

This is dev-only tooling. Nothing here is imported by the app; the
Dockerfile does not copy `scripts/dev/`.

## One-time setup

```bash
# Python venv (3.11 or 3.12 — .venv-local was built with 3.12)
python3.12 -m venv .venv-local
.venv-local/bin/pip install -r requirements.txt

# Node deps for the screenshot helper (reuses whatever Chromium build is
# already cached in ~/Library/Caches/ms-playwright — shouldn't re-download)
cd scripts/dev && npm install && npx playwright install chromium && cd ../..
```

## Run the app

```bash
./scripts/dev/run_local.sh
```

First run seeds `database/local_dev.db` (~920 attendance records across 12
employees, 60 days) via `scripts/dev/seed_local_db.py`, then starts
uvicorn on **http://localhost:5055**. Subsequent runs reuse the existing
DB file. To get fresh data:

```bash
rm database/local_dev.db && ./scripts/dev/run_local.sh
# or, with the app stopped:
.venv-local/bin/python scripts/dev/seed_local_db.py --reset
```

Stop the server with Ctrl-C (foreground) or `kill` its PID (find it with
`lsof -nP -iTCP:5055 -sTCP:LISTEN`).

## Take a screenshot

```bash
node scripts/dev/shot.mjs http://localhost:5055/fingerprintlogs/v2/ /tmp/v2-index.png
node scripts/dev/shot.mjs http://localhost:5055/fingerprintlogs/v2/monthly /tmp/monthly.png 1600 1000
```

Full-page PNG, default viewport 1440x900 (override with width/height
args). Prints the HTTP status and any browser console errors — useful
for catching a broken fetch() without opening dev tools.

## What the seeded data covers

12 employees (Thai + English names, `display_name` as the nickname,
spanning reception / housekeeping / technician / admin roles) and ~60
days of `AttendanceRecord` punches, including:

| Badge | What it demonstrates |
|---|---|
| R001-R004 | Reception roster: rotating shifts (`shift_assignments`), each with a different weekly day off |
| H001, H003 | Housekeeping, role-default MORNING shift, Sundays off |
| **H002** | Housekeeping, scheduled every work day, **zero punches ever** — permanent "absent" |
| T001 | Technician, normal day shift, plus one **missing punch-out** day and one **duplicate check-in** day (device double-scan) |
| **T002** | Technician with an explicit `default_shift_id` = NIGHT (22:00-07:00) — punches **cross midnight** into the next calendar day |
| A001 | Admin role, NORMAL shift |
| U001 | **Untracked** (no role, no default shift) — has punches, but `/by-date` and `/monthly` both skip it |
| I001 | Inactive + hidden — punches only in the first third of the window, then stops (simulates leaving) |

Also seeded: all 7 `shifts` rows (NORMAL/MORNING/MID/AFTERNOON/NIGHT plus
the OFF and HK_WORK pseudo-shifts, matching the Alembic migrations
exactly — see comments in `seed_local_db.py`), the 4 `leave_types`, one
`public_holiday`, and a couple of `employee_leaves` rows.

## Gotchas a UI agent must know

- **`DATABASE_URL` does nothing.** The app's pydantic `Settings`
  (`app/core/config.py`) uses `env_prefix="FINGERPRINT_"` on every field,
  so the real env var is `FINGERPRINT_DATABASE_URL`. Setting plain
  `DATABASE_URL` is silently ignored and the app falls back to its
  hardcoded default (`sqlite:///./database/attendance.db`) — this bit us
  once while building this script. `run_local.sh` sets the correct name.
- **JWT_SECRET / ADMIN_PASSCODE_HASH are deliberately left UNSET.**
  CI (`ci.yml`/`build.yml`) fills these with throwaway values just to get
  a clean import; we instead rely on `ENV=test` putting
  `app/services/{qr,line_auth,admin_auth}_service.py` in their "dev
  environment" branch, which generates a real, known dev default:
  `JWT_SECRET=dev-jwt-secret-CHANGE-ME`,
  `ADMIN_PASSCODE_HASH` = bcrypt hash of `dev-passcode-CHANGE-ME`. That
  passcode logs into `/fingerprintlogs/admin-login` if you ever need the
  legacy admin-console pages.
- **The v2 JSON APIs need NO login locally.** `/api/private/*` (attendance,
  employees, shifts, leaves, devices) has no `require_admin_auth`
  dependency in code — it's protected only by Cloudflare Access upstream
  in production (see the comment on `serve_v2_shifts_admin` in
  `app/main_unified.py`). Locally, with no CF Access in front, these
  endpoints are wide open. Only `admin_onboarding` / `admin_employees` /
  `admin_line_codes` actually enforce `require_admin_auth` in code.
- **The WebSocket (`/fingerprintlogs/ws`, used by `/v2/live`) DOES require
  auth**, and will 403/close (code 1008) on every connection attempt
  without a valid admin session or CF Access identity. `/v2/live`'s
  initial data load (a plain `fetch()`) still works fine and shows real
  punches — only the "live" real-time pill stays red/disconnected, and
  the browser console logs a WebSocket handshake failure. This is
  expected, not a bug to fix.
- **`CORS_ALLOWED_ORIGINS` must include the port you're serving on.**
  Even same-origin, the WS origin check in `main_unified.py` compares
  against this allowlist; the default value only has the production
  hostnames. `run_local.sh` sets it to `http://localhost:5055,
  http://127.0.0.1:5055`.
- **Tailwind + hf-bar need real network.** Every `static/v2/*.html` loads
  Tailwind from `https://cdn.tailwindcss.com` and the estate nav bar from
  `https://erp.thehfhotel.org/shell/hf-bar.js`. Offline, pages still
  return 200 and screenshot fine, just unstyled and without the top bar
  — don't mistake that for a broken page.
- **The background scheduler and ZK session thread start regardless** —
  they retry a device connection every 5 minutes forever. `run_local.sh`
  points `ZKTECO_HOST` at `127.0.0.1` (refused instantly) instead of the
  real LAN IP `192.168.100.209` (unreachable from off-LAN, would hang for
  the full `zkteco_timeout` on every attempt) — just log noise either
  way, never blocks startup or the API.
- **`.venv-local`'s Python is x86_64 running under Rosetta** on this
  Apple Silicon machine (`/usr/local/bin/python3.12` is an Intel build) —
  works fine, just somewhat slower than a native arm64 interpreter would
  be. Not worth rebuilding for this dev-loop use case.
- **The seed script is idempotent by default** — if `database/local_dev.db`
  already has employees, running `seed_local_db.py` again is a no-op.
  Pass `--reset` to wipe and reseed (drops all tables first).
