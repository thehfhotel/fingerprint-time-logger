# Polish Audit

## Skip List

Items the user has decided to ignore. Persists across runs.

| # | Type | Pattern | Reason | Added |
|---|------|---------|--------|-------|

_(skip list is empty)_

---

## Iteration 1

37 findings, all fixed and committed as `16b67b86`. Full table preserved below for the historical record.

| # | Severity | Category | File:Line | Issue | Fix Applied | Status |
|---|----------|----------|-----------|-------|-------------|--------|
| 1 | critical | crypto | line_auth_service.py:36, qr_service.py:24 | `JWT_SECRET` silent default | Refuse to start in prod when env unset/placeholder; dev fallback with logger.warning | fixed |
| 2 | critical | headers | main_unified.py:184-190, 442-448 | `allow_origins=["*"]` + `allow_credentials=True` | Replaced with `CORS_ALLOWED_ORIGINS` env (default erp/emp.thehfhotel.org) on both apps | fixed |
| 3 | high | bug+auth | line_auth.py:500-507 | unlink-account ImportError + insecure | Replaced admin-passcode with LINE JWT self-unlink | fixed |
| 4 | high | bug | consolidated_devices.py:251 | NameError on cache miss | Removed redundant `device_time` line in response.update | fixed |
| 5 | high | bug | consolidated_attendance.py:133-134 | `punch_type == "IN"` vs int | Int comparison (0/1) | fixed |
| 6 | high | bug | consolidated_attendance.py:219-223 | Calendar end_date = first of NEXT month | `calendar.monthrange` for inclusive end_date | fixed |
| 7 | high | bug | export_service.py, consolidated_attendance.py | UTC timestamps used for Bangkok-day output | BANGKOK_TZ helper applied at all formatting sites | fixed |
| 8 | high | bug | system_status.py:236-239 | UTC vs Bangkok day boundary | Bangkok-day computed as UTC range filter | fixed |
| 9 | high | error-handling | main_unified.py multiple sites | Sync ZK calls block event loop | `asyncio.to_thread` on 9 sync call sites | fixed |
| 10 | high | auth | admin_auth.py:127-134 | `secure=False` + `samesite="lax"` | `secure=BEHIND_PROXY`, `samesite="strict"` | fixed |
| 11 | high | auth | main_unified.py:228-258,745-776 | WS endpoints accept refresh, no auth | Origin allowlist on both; admin session on /fingerprintlogs/ws; per-conn 1/min refresh rate-limit | fixed |
| 12 | high | injection | individual-attendance.js, qr-terminal.js, mobile-checkin.js | innerHTML XSS sinks | escapeHtml helper added + applied to 3 files | fixed |
| 13 | high | rate-limit | line_auth.py:372-476 | Brute-force on 6-digit linking code | Per-(IP, line_user_id) sliding window 5/min, lockout 20→5min, code invalidate after 5 fails | fixed |
| 14 | high | broken | individual-attendance.js:98-104 | Missing `>` in nickname-item div tag | Tag closed; safer attribute interpolation | fixed |
| 15 | high | broken | nickname-management.html:241 | Stray `</main>` | Removed | fixed |
| 16 | high | a11y | dashboard.html, export.html, status.html, nickname-management.html | `lang="en"` on Thai pages | Changed to `lang="th"` | fixed |
| 17a | medium | concurrency | admin_auth_service.py | `_sessions` dict mutated without locks | `threading.RLock` on all _sessions read/write/iterate | fixed |
| 17b | medium | concurrency | line_auth_service.py | `_state_storage` mutated without locks | `threading.Lock` on all state ops | fixed |
| 18 | medium | bug | admin_line_codes.py | `random.choices` + non-atomic uniqueness | `secrets.choice` + IntegrityError retry helper | fixed |
| 19 | medium | bug | cache_busting.py:33-45 | URL memoized forever | Removed `_cache`; `clear_cache` kept as no-op | fixed |
| 20 | medium | bug | consolidated_employees.py:82 | display_name fallback `""` | `f"พนักงาน {badge}"` fallback | fixed |
| 21 | medium | error-handling | qr_service.py:122,126 | Bare `print()` | `logger.info`/`logger.warning` | fixed |
| 22 | medium | rate-limit | admin_auth.py:94-145 | No login throttle | Per-IP 5/15min lockout | fixed |
| 23 | medium | secrets | admin_auth_service.py:24-30 | Hardcoded passcode in source | Refuse to start in prod; literal removed | fixed |
| 24 | medium | auth | admin-login.html:294-295 | Token to localStorage | localStorage write removed; admin-console switched to cookie auth | fixed |
| 25 | medium | headers | main_unified.py | Missing security headers | `_add_security_headers` middleware on both apps | fixed |
| 26 | medium | error-state | qr-scan.html | Server data into innerHTML | Static skeleton + textContent on data spans | fixed |
| 27 | medium | broken | mobile-checkin.js, link-line.js | Missing default-avatar.png | Inline data-URI SVG fallback + onerror | fixed |
| 28 | medium | realtime | real-time-manager.js | Toast every 60s polling | `isUserTriggered` flag; 60s polling silent; offline→online one-time toast | fixed |
| 29 | medium | realtime | qr-terminal.html:48 | Hardcoded "30" countdown | Initial text "--" | fixed |
| 30 | medium | a11y | mobile-checkin.html, admin-console.html | Icon-only logout no aria-label | aria-label + type="button" added | fixed |
| 31 | medium | error-state | mobile-checkin.js, individual-attendance.js, link-line.js | alert/confirm for errors | alert() replaced with showResult/inline UI | fixed |
| 32 | low | quality | qr_checkin.py, location_service.py | location_name not sanitized | `safe_location_name` helper applied | fixed |
| 33 | low | auth | main_unified.py:469-472 | `/api/private/test` info-leak | Now requires `Depends(require_admin_auth)` | fixed |
| 34 | low | redirect | line_auth.py:292-303 | LINE values not URL-encoded | `urllib.parse.quote` on all values | fixed |
| 35 | low | loading | qr-terminal.js | WS reconnect no backoff cap | Exponential backoff capped at 60s + attempt counter | fixed |
| 36 | low | forms | link-line.html | Missing autocomplete="one-time-code" | Added | fixed |
| 37 | low | cache | dashboard.html, export.html | document.write warning | Wrapped in IIFE guarded by `readyState !== 'loading'` | fixed |

---

## Iteration 2

9 findings after de-duping (reviewer + security flagged the same missed ZK sites and the same rate-limit dict growth). Auto-fix mode.

| # | Severity | Category | File:Line | Issue | Suggested Fix | Status |
|---|----------|----------|-----------|-------|---------------|--------|
| 1 | high | regression | admin_auth_service.py, line_auth_service.py, qr_service.py | Strict-prod env check fires at module import time. `tests/conftest.py` sets `TESTING=true` only — auth services don't consult it, so `pytest --collect-only` breaks in CI when `ENV`/`JWT_SECRET`/`ADMIN_PASSCODE_HASH` are unset. | Treat `TESTING=true` as a dev-equivalent in the env-check OR set `ENV=test` at the top of `tests/conftest.py` before any imports. | fixed |
| 2 | high | regression | static/nickname-management.html:373-411 | iter 1 added `escapeHtml` to 3 JS files but missed this admin page. Server `display_name` (incl. LINE-imported) interpolated into `value="${...}"` attrs and JS-string literals inside `row.innerHTML` and `onclick="...('${...}')"` — stored XSS. | Add `escapeHtml` helper to the inline script, wrap every `${employee.display_name}`/`${employee.badge_number}` interpolation, JS-escape onclick params. | fixed |
| 3 | medium | regression | consolidated_attendance.py:310, consolidated_devices.py:307,349,358,518 | iter 1 #9 fix wrapped 9 sites in `main_unified.py` but missed 10+ identical blocking ZK calls in `async def` router endpoints (`/attendance/sync`, `/devices/test-connection`, `/devices/sync-time`, `/devices/sync/attendance`, etc). Same event-loop blocking. | Wrap each with `await asyncio.to_thread(device_service.*)` matching the lifespan-task pattern. | fixed |
| 4 | medium | rate-limit | line_auth.py:57-100 | The three rate-limit dicts (`_link_attempts`, `_link_lockouts`, `_link_code_failures`) only prune the same key on access. Inactive keys accumulate forever (memory DoS by attacker rotating LINE accounts and codes). `_enforce_link_rate_limit` writes empty-list keys on first call. | Add a global pruner that iterates all three dicts; only insert into `_link_attempts` when there are timestamps; TTL-age `_link_code_failures`. Add `max_length=6` on the Pydantic `linking_code` field. | fixed |
| 5 | medium | rate-limit | admin_auth.py:32-40, line_auth.py:65-72 | Both `_get_client_ip` helpers trust the FIRST entry of `X-Forwarded-For` when `BEHIND_PROXY=true` with no trusted-proxy allowlist. If proxy appends instead of overwrites, attacker can spoof XFF to bypass both lockouts. | Read `CF-Connecting-IP` (preferred — Cloudflare overwrites this) before XFF; fall back to `request.client.host` only when neither is set. Document the proxy contract. | fixed |
| 6 | medium | regression | static/status.html:714,727 | `issues.map(... ${issue} ...)` rendered via `innerHTML`. iter 1 patched the same XSS pattern in 3 sibling JS files but skipped this file. `deviceHealth.message` from API embedded in the array (line 694). | Add `escapeHtml` helper, wrap each issue: `issues.map(i => \`<div...>${escapeHtml(i)}</div>\`)`. | fixed |
| 7 | low | quality | consolidated_attendance.py:17-24, system_status.py:16, export_service.py:19-26 | iter 1 introduced 3 identical copies of `BANGKOK_TZ = timezone(timedelta(hours=7))` + `_to_bangkok` helper. Drift risk. | Move to shared `app/utils/timezone.py`; import. | fixed |
| 8 | low | bug | admin_auth.py:268, main_unified.py:356,385,444,479 | `set_cookie` uses `samesite="strict", secure=BEHIND_PROXY`; matching `delete_cookie` calls use Starlette defaults (`samesite="lax", secure=False`). Browsers may silently ignore the deletion under SameSite=Strict — invalidated cookie keeps being re-sent. | Pass matching `samesite="strict", secure=_is_behind_proxy()` to every `delete_cookie` call. | fixed |
| 9 | low | a11y | static/mobile-checkin.html:49, static/link-line.html:21 | `<img src="">` causes browser to request the page URL as an image until JS reassigns `src`. iter 1's SVG fallback only fires in JS. | Set initial `src` attribute to the same data-URI SVG so placeholder is immediate. | fixed |
