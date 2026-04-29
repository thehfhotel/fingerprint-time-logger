# PLAN.md — Fingerprint Time Logger Feature Contract

This document is the contract for what the system MUST do. Anything listed here must
continue to exist and behave as described after any automated polish/refactor pass.
Auditors compare code against this list to detect gaps and regressions; the fixer
agent must skip any change that would remove, disable, or alter behavior described here.

> **Maintenance**: Edit this file by hand when intent changes. Automated tools (`/polish`,
> `/sweep`) read from it but never write to it.

---

## 1. Application Architecture

- **Two-tier FastAPI app**: a root `app` and a mounted sub-app `fingerprint_app` at
  `/fingerprintlogs`. Mount order is "register root routes first, then mount sub-app".
- **Single port (5000)** serving everything: APIs, dashboard, WebSocket, QR check-in.
- **SQLite database** at `database/attendance.db`, managed by Alembic migrations.
- **Background scheduler** (APScheduler) runs in the lifespan context.
- **WebSocket manager** broadcasts real-time updates to connected dashboard clients.
- **`BEHIND_PROXY`** env flag enables `ProxyHeadersMiddleware` for HTTPS preservation
  behind nginx/Cloudflare.

### Cross-cutting constraints (must never be silently changed)

- **Bangkok timezone (UTC+7)** for all human-facing timestamps. Storage is UTC; date
  filters interpret inputs as Bangkok dates and convert to UTC ranges for queries.
- **FastAPI router trailing slashes** — protected routers are mounted with trailing
  slashes (`/api/private/attendance/`). Removing the slash causes 307 redirects.
- **Cache control headers**: HTML pages and JS files use `no-cache, no-store,
  must-revalidate, max-age=0` plus ETag/timestamp cache-busting on JS.
- **Browser localStorage persistence** for: LINE JWT, GPS terminal location, QR camera
  permission state. Removing this regresses UX.
- **Future-date filter**: records with year > current_year + 5 are filtered as data
  corruption (clock-skew protection). Must remain.

---

## 2. Protected Admin APIs (`/api/private/*`, behind Cloudflare Access)

### 2.1 Admin Auth (`/api/private/admin/auth`)
- `POST /login` — bcrypt-verify passcode, return session token.
- `GET /validate` — validate token + expiry.
- `POST /logout` — invalidate token.
- `GET /session-info` — return session metadata.

### 2.2 Admin LINE linking codes (`/api/private/admin/line-codes`)
- `POST /generate`, `POST /regenerate`, `GET /list`, `GET /linked`, `POST /unlink`,
  `GET /stats`.
- 6-digit numeric codes, **24-hour expiry**, one code per employee, regeneratable.

### 2.3 Attendance (`/api/private/attendance/`)
- `GET /` — records with date/badge filtering.
- `GET /summary` — dashboard summary (cache-first, 5-minute TTL).
- `GET /employee/{id}` and `GET /employee/badge/{badge}` — per-employee records.
- `GET /calendar/config` and `GET /calendar/{year}/{month}` — calendar data.
- `GET /today` — today's summary.
- `POST /sync` — manual force sync; `GET /sync/status` — sync state.
- `GET /export/csv` — CSV export.
- `GET /health`.

### 2.4 Devices (`/api/private/devices/`)
- CRUD: `GET /`, `POST /`, `GET /{id}`, `PUT /{id}`, `DELETE /{id}`, `GET /default`.
- Status: `GET /health`, `GET /status`, `GET /diagnostics`, `GET /config`, `GET /app-config`.
- Operations: `POST /test-connection`, `POST /sync-time`, `POST /sync/attendance`,
  `GET /time`, `POST /time/sync`.
- **QR-terminal devices have no IP/port** — connection logic must skip them silently.

### 2.5 Employees (`/api/private/employees/`)
- CRUD: `GET /`, `POST /`, `GET /{badge}`, `PUT /{badge}`, `DELETE /{badge}`.
- Display controls: `PUT /{badge}/nickname`, `PUT /{badge}/status` (active/inactive),
  `PUT /{badge}/hidden` (dashboard visibility).
- Thai names: `GET /thai-names/`, `PUT /thai-names/{badge}`.
- Stats/export: `GET /stats/summary`, `GET /export/csv`, `GET /health`.

### 2.6 System (`/api/private/system/`)
- `GET /health` — comprehensive health (device, db, resources, stats).
- `GET /logs`, `GET /logs/summary`, `POST /logs/cleanup`.
- `GET /metrics`.

### 2.7 Auto-import & refresh
- `GET /api/private/auto-import/status` — task status, next scheduled time.
- `POST /api/private/auto-import/trigger/` — manual trigger; broadcasts via WebSocket.
- `POST /api/private/refresh` — manual refresh with WebSocket broadcast.

---

## 3. Public APIs (`/api/public/*`, no Cloudflare Access)

### 3.1 QR check-in (`/api/public/qr-checkin/`)
- `POST /scan` — process scan with GPS validation + create attendance record.
- `GET /terminals` — list active QR terminals.
- `GET /kiosk/{terminal_id}` — generate QR (60-second expiry, 15-second grace).
- `POST /refresh/{terminal_id}` — regenerate QR.
- `GET /validate-location` — GPS-radius validation (Haversine).
- `GET /attendance/employee/badge/{badge}` — individual records.

### 3.2 LINE OAuth (`/api/public/auth/line/`)
- `GET /login` — initiate OAuth with mobile-Safari-compatible redirect hint.
- `GET /callback` — handle OAuth, smart-redirect for linked vs unlinked accounts.
- `POST /link-account` — link with 6-digit code; returns JWT.
- `POST /unlink-account` — unlink; returns logout JWT.
- `POST /verify-token` — JWT validity + remaining time.

### 3.3 Direct/tunnel access aliases
- `GET /qr-checkin/terminal`, `GET /qr-checkin/mobile`,
  `GET /qr-checkin/link-account` — serve static HTML directly so the Cloudflare
  worker can proxy by path.
- `GET /api/private/test` — routing verification.

---

## 4. Frontend Pages (under `/fingerprintlogs/*` unless noted)

### 4.1 Public dashboard / attendance
- `/` (and `/fingerprintlogs/`) — **main dashboard**: real-time attendance, last
  import time, device clock, manual import button, navigation.
- `/individual-attendance` — per-employee punch history + calendar.
- `/export` — CSV export with date-range filtering.
- `/docs` — Swagger UI.
- `/health` — basic health.

### 4.2 Admin (require admin session cookie)
- `/admin-login` — passcode entry.
- `/admin-console` — admin nav hub.
- `/nickname-management` — employee table with name + LINE-code generation.
- `/admin/terminal-gps` — Google Maps GPS-pin/radius editor for terminals.
- `/status` — system health page.

### 4.3 QR check-in (publicly reachable)
- `/qr-checkin/terminal` — kiosk display: live QR with 60s refresh, countdown,
  recent check-ins feed (real-time).
- `/qr-checkin/mobile` — LINE login + camera scanner + GPS + feedback.
- `/qr-checkin/link-account` — 6-digit code entry.
- `/qr-checkin/scan` — scan landing with auto-redirect.
- `/qr-checkin/scan-callback` — OAuth callback redirect.

### 4.4 Legacy redirects (must keep returning 301)
- `/employee-management` → `/`
- `/work-schedules` → `/`
- `/attendance-calendar` → `/`

---

## 5. Frontend JS Modules (in `static/js/`)

Each file below implements a feature; do not delete:

- `config.js`, `config-simple.js` — global config, API endpoint routing, cache-bust version.
- `websocket-adapter.js` — WebSocket connection manager.
- `real-time-manager.js` — real-time data sync / broadcast handling.
- `qr-terminal.js` — QR display, auto-refresh, countdown, recent check-ins feed.
- `qr-terminal-gps.js` — multi-office terminal location selector.
- `mobile-checkin.js` — camera QR scanner (jsQR), GPS permission, check-in submit.
- `terminal-gps-admin.js` — Google Maps pin/radius editor.
- `link-line.js` — LINE linking 6-digit code flow.
- `individual-attendance.js` — per-employee attendance display + filtering.

---

## 6. Database Models

### Device
- Identity: `id`, `name`, `device_type` (`fingerprint` | `qr_terminal`).
- Connection: `ip_address`, `port` (default 4370), `password` (nullable for QR terminals).
- State: `is_active`, `last_sync`, `created_at`, `updated_at`.
- `device_metadata` (JSON) — GPS coordinates, display settings, radius.
- 1-to-many → `attendance_records`.

### Employee
- Identity: `id`, `badge_number` (unique, immutable primary identifier).
- Names: `english_name`, `thai_name`, `display_name` (computed: Thai or
  `"พนักงาน {badge}"` fallback).
- Org: `department`, `position`.
- UI flags: `is_active`, `is_hidden`.
- LINE: `line_user_id` (unique), `line_display_name`, `line_picture_url`,
  `line_linking_code` (unique), `line_linking_code_generated_at`.
- Audit: `created_at`, `updated_at`.

### AttendanceRecord
- Keys: `id`, `employee_badge_number` (FK), `device_id` (FK).
- Punch: `timestamp` (UTC, indexed), `punch_type` (0 in / 1 out / 2 break-out /
  3 break-in / 4 OT-in / 5 OT-out), `status` (0 normal / 1 late / 2 early).
- Sync: `sync_status` (`synced` | `pending` | `failed`), `local_id` (UUID),
  `created_locally` (bool).
- Validation: `validation_status` (`on_time` | `warning` | `late` | `early` |
  `unvalidated`), `lateness_minutes`, `early_minutes`, `expected_time`,
  `schedule_type` (`STANDARD` | `SHIFT`), `validation_message`, `validated_at`.
- Audit: `created_at`.

### ApplicationLog
- `id`, `timestamp` (indexed), `level` (indexed), `category` (indexed), `action`,
  `message`, `details` (JSON), `user_agent`, `success`.

### JobRole
- Listed in CLAUDE.md as a working model — must remain. Schedule-aware role definitions.

---

## 7. Services Layer (in `app/services/`)

Each service below provides a business capability that other code depends on:

- **`device_service.py` / SimpleDeviceService** — ZKTeco connect, sync, status, time
  read/write, user list. Auto-skip QR terminals.
- **`device_service_cached.py` / CachedDeviceService** — cached read paths for
  status / time / attendance summary.
- **`device_cache_service.py`** — TTL cache primitives (get/set/invalidate/auto-expire).
- **`attendance_service.py` / SimpleAttendanceService** — record retrieval (TZ-aware),
  summary, employee list, monthly stats, future-date sanitizer.
- **`line_auth_service.py`** — OAuth URL gen, code exchange, profile fetch, JWT
  create/verify (24h), CSRF state cleanup (10-min TTL).
- **`qr_service.py`** — QR-token JWT (60s, 15s grace), PNG image gen.
- **`location_service.py`** — Haversine distance, terminal-location fetch, radius validate.
- **`admin_auth_service.py`** — passcode bcrypt verify, 1-hour session create/validate/invalidate.
- **`export_service.py`** — attendance CSV, employee CSV, filtered exports.
- **`logging_service.py`** — structured app log writes / queries / cleanup.
- **`background_scheduler.py`** — APScheduler with the four jobs in §8.

---

## 8. Background Tasks

- **Auto-import fingerprint logs** (lifespan task in `main_unified.py`): runs at
  startup and every `AUTO_IMPORT_INTERVAL_MINUTES` (default 30). Calls
  `sync_attendance_data()`, broadcasts `auto_import_update` over WebSocket with a
  Thai message, retries on failure with 60s delay. Records
  `auto_import_start_time` and `last_auto_import_time`.
- **5-minute refresh jobs** (BackgroundSchedulerService):
  - device metadata refresh
  - device time refresh
  - attendance summary cache refresh
- **30-minute fingerprint sync job** (configurable).

---

## 9. WebSocket (`/ws` on `fingerprint_app`)

- Manages connection list; broadcasts JSON to all clients.
- Server-to-client message types: `auto_import_update`, `manual_import_update`,
  `attendance_update`, `pong`.
- Client-to-server: `{"type": "ping"}` → server replies `pong`;
  `{"type": "refresh"}` → server triggers manual sync and emits `attendance_update`.

---

## 10. External Integrations

- **ZKTeco devices (pyzk)** — TCP+UDP fallback, configurable retries/timeout,
  password auth, time read/write, attendance pull.
- **LINE OAuth 2.0** — channel id/secret from env, configurable callback URL,
  `profile` scope, CSRF state, smart linked/unlinked redirect.
- **Google Maps** — terminal GPS admin page; default Bangkok center
  (13.7563, 100.5018); pin + radius circle; data persisted in `Device.device_metadata`.
- **Cloudflare Access** — header-based auth on `/api/private/*`; no-op locally.
- **Slack notifications** — used by `zk-time-sync` subproject and the new
  `zk-time-sync` error notifier with @mention support (recent commit). Webhook from env.

---

## 11. Authentication & Authorization

- **Admin sessions** — bcrypt passcode → 32-byte random session token →
  HttpOnly+Secure+SameSite=Strict cookie → 1-hour expiry → server-side redirect on
  expiry. No automatic renewal on activity.
- **LINE JWT (mobile)** — HS256, payload `{line_user_id, expires_at, iat, exp}`,
  24-hour expiry, stored in browser localStorage (persistent across reloads).
- **QR-code token** — HS256 JWT, payload `{terminal_id, timestamp, nonce, iat, exp}`,
  60s expiry, 15s grace, no nonce-replay protection (intentional — many users may
  scan the same QR).
- **Cloudflare Access headers** — `CF-Access-Authenticated-User-Email` or
  `X-Forwarded-Email` on `/api/private/*`. Local dev works without them.

---

## 12. Configuration / Environment Variables

Keep all of these recognized:

- **DB**: `DATABASE_URL` (default `sqlite:///./database/attendance.db`).
- **Device**: `ZKTECO_HOST`, `ZKTECO_PORT` (4370), `ZKTECO_PASSWORD` (0),
  `DEVICE_NAME`, `DEVICE_MAX_RETRIES` (3), `DEVICE_TIMEOUT` (5).
- **Scheduler**: `AUTO_IMPORT_INTERVAL_MINUTES` (30).
- **Admin**: `ADMIN_PASSCODE_HASH` (bcrypt; required in production).
- **LINE**: `LINE_CHANNEL_ID`, `LINE_CHANNEL_SECRET`, `LINE_CALLBACK_URL`,
  `JWT_SECRET`.
- **Proxy**: `BEHIND_PROXY` (false) — toggles ProxyHeadersMiddleware.

---

## 13. CLI Scripts (user-invokable)

- `./scripts/manage-app.sh` — interactive menu + direct: `start`, `stop`, `restart`,
  `status`, `health`, `logs`, `deploy`, `backup`. Supports `--build-method bake`,
  `--no-build-cache`, `--build-target`.
- `./scripts/test-suite-console.sh` — `all | unit | integration | e2e | security |
  quality | setup`; flags `--browser`, `--parallel`, `--coverage`.
- `./scripts/run-complete-test-suite.sh` — full suite + timestamped report; flags
  `--parallel`, `--verbose`.
- `./scripts/run-integration-e2e-tests.sh` — integration + E2E only; same flags.
- `./scripts/build-with-bake.sh` — Bake build; `--dev` / `--prod`.
- `./scripts/build-comparison.sh` — Bake-vs-Compose perf comparison.

---

## 14. zk-time-sync Subproject (`zk-time-sync/`)

- Standalone Python service (NOT mounted in main app).
- Syncs ZKTeco device clock to Bangkok timezone.
- JSON config + env defaults, log files in `logs/sync.log` and `logs/errors.log`.
- Configurable interval and device list.
- Slack error notifier with @mention support (recent feature).

---

## 15. Cloudflare Worker (`cloudflare-worker/`)

- Path-rewriting proxy for public QR check-in:
  external `erp.thehfhotel.org/qr-checkin/*` →
  internal `http://{BACKEND_HOST}:{BACKEND_PORT}/{PATH_PREFIX}/qr-checkin/*`.
- Forwards method/headers/body unchanged.
- Adds security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options`,
  `X-XSS-Protection`, `Referrer-Policy`.
- Returns 404 for non-`/qr-checkin` paths, 502 on backend failure.
- Env vars in `wrangler.toml`: `PATH_PREFIX`, `BACKEND_HOST`, `BACKEND_PORT`.

---

## 16. Critical Behaviors That Must Be Preserved

These are easy to "fix" away by accident — they are intentional:

- **QR-terminal devices skip ZK connection** entirely (no IP, no port).
- **Future-date attendance records are filtered** at read time as clock-skew protection.
- **Cache-first reads** on `/attendance/summary`, device status, device time —
  cache miss falls back to DB/device.
- **Trailing slashes** on protected routers (mounted with `/`-suffixed prefixes).
- **Mobile-Safari OAuth redirect hint** in `/api/public/auth/line/login`.
- **Smart OAuth callback** redirect: linked accounts → mobile check-in; unlinked →
  link-account page.
- **Persistent LINE JWT** in browser localStorage across sessions.
- **GPS-localStorage caching** for instant terminal-location availability.
- **No nonce-replay protection on QR tokens** is intentional, not a bug.
- **5-minute device-status cache TTL** matches frontend health check interval.
- **HS256 JWT** with shared `JWT_SECRET` for all JWTs (LINE + QR).
- **Bangkok timezone everywhere user-facing**; UTC at storage layer.

---

## 17. Test Suite (must continue to be runnable)

- Unit, integration, and E2E (Playwright) suites under `tests/`.
- Runnable via `pytest`, the suite-console script, and the complete-test-suite script.
- Test reports written to `test-reports/` directory.
