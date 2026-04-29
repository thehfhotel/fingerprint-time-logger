# Polish Audit

## Skip List

Items the user has decided to ignore. Persists across runs.

| # | Type | Pattern | Reason | Added |
|---|------|---------|--------|-------|

_(skip list is empty)_

---

## Iteration 1

37 findings, all fixed. Dispatched across 5 parallel fixers (main_unified, admin auth, LINE/QR auth, backend bugs, frontend).

| # | Severity | Category | File:Line | Issue | Fix Applied | Status |
|---|----------|----------|-----------|-------|-------------|--------|
| 1 | critical | crypto | line_auth_service.py:36, qr_service.py:24 | `JWT_SECRET` silent default | Refuse to start in prod when env unset/placeholder; dev fallback with logger.warning | fixed |
| 2 | critical | headers | main_unified.py:184-190, 442-448 | `allow_origins=["*"]` + `allow_credentials=True` | Replaced with `CORS_ALLOWED_ORIGINS` env (default erp/emp.thehfhotel.org) on both apps | fixed |
| 3 | high | bug+auth | line_auth.py:500-507 | unlink-account ImportError + insecure | Replaced admin-passcode with LINE JWT self-unlink | fixed |
| 4 | high | bug | consolidated_devices.py:251 | NameError on cache miss | Removed redundant `device_time` line in response.update | fixed |
| 5 | high | bug | consolidated_attendance.py:133-134 | `punch_type == "IN"` vs int | Int comparison (0/1) | fixed |
| 6 | high | bug | consolidated_attendance.py:219-223 | Calendar end_date = first of NEXT month | `calendar.monthrange` for inclusive end_date | fixed |
| 7 | high | bug | export_service.py:75-76,236-237; consolidated_attendance.py:236,245 | UTC timestamps used for Bangkok-day output | BANGKOK_TZ helper applied at all formatting sites | fixed |
| 8 | high | bug | system_status.py:236-239 | UTC vs Bangkok day boundary | Bangkok-day computed as UTC range filter | fixed |
| 9 | high | error-handling | main_unified.py:69-147,245,559,623,763 | Sync ZK calls block event loop | `asyncio.to_thread` on 9 sync call sites | fixed |
| 10 | high | auth | admin_auth.py:127-134 | `secure=False` + `samesite="lax"` | `secure=BEHIND_PROXY`, `samesite="strict"` | fixed |
| 11 | high | auth | main_unified.py:228-258,745-776 | WS endpoints accept refresh, no auth | Origin allowlist on both; admin session on /fingerprintlogs/ws; per-conn 1/min refresh rate-limit | fixed |
| 12 | high | injection | individual-attendance.js, qr-terminal.js, mobile-checkin.js | innerHTML XSS sinks | escapeHtml helper added + applied to 3 files | fixed |
| 13 | high | rate-limit | line_auth.py:372-476 | Brute-force on 6-digit linking code | Per-(IP, line_user_id) sliding window 5/min, lockout 20→5min, code invalidate after 5 fails | fixed |
| 14 | high | broken | individual-attendance.js:98-104 | Missing `>` in nickname-item div tag | Tag closed; safer attribute interpolation | fixed |
| 15 | high | broken | nickname-management.html:241 | Stray `</main>` | Removed | fixed |
| 16 | high | a11y | dashboard.html, export.html, status.html, nickname-management.html | `lang="en"` on Thai pages | Changed to `lang="th"` (swagger.html intentionally kept "en" for English UI) | fixed |
| 17a | medium | concurrency | admin_auth_service.py | `_sessions` dict mutated without locks | `threading.RLock` on all _sessions read/write/iterate | fixed |
| 17b | medium | concurrency | line_auth_service.py | `_state_storage` mutated without locks | `threading.Lock` on all state ops | fixed |
| 18 | medium | bug | admin_line_codes.py:73,148-160,226-235 | `random.choices` + non-atomic uniqueness | `secrets.choice` + IntegrityError retry helper used by /generate and /regenerate | fixed |
| 19 | medium | bug | cache_busting.py:33-45 | URL memoized forever — defeats cache-bust | Removed `_cache`; `clear_cache` kept as no-op | fixed |
| 20 | medium | bug | consolidated_employees.py:82 | display_name fallback `""` | `f"พนักงาน {badge}"` fallback in both create+update branches | fixed |
| 21 | medium | error-handling | qr_service.py:122,126 | Bare `print()` | `logger.info`/`logger.warning` | fixed |
| 22 | medium | rate-limit | admin_auth.py:94-145 | No login throttle | Per-IP 5/15min lockout, honors X-Forwarded-For when BEHIND_PROXY | fixed |
| 23 | medium | secrets | admin_auth_service.py:24-30 | Hardcoded passcode in source | Refuse to start in prod; literal removed; dev override via ADMIN_PASSCODE_DEV_DEFAULT | fixed |
| 24 | medium | auth | admin-login.html:294-295 | Token to localStorage nullifies HttpOnly | localStorage write removed; admin-console switched to cookie auth | fixed |
| 25 | medium | headers | main_unified.py | Missing security headers | `_add_security_headers` middleware on both apps (nosniff, X-Frame: DENY, Referrer, HSTS when proxied) | fixed |
| 26 | medium | error-state | qr-scan.html:246-258,263-269 | Server data into innerHTML | Static skeleton + textContent on data spans | fixed |
| 27 | medium | broken | mobile-checkin.js:149, link-line.js:122 | Missing default-avatar.png | Inline data-URI SVG fallback + onerror handler | fixed |
| 28 | medium | realtime | real-time-manager.js:175-179 | Toast every 60s polling | `isUserTriggered` flag; 60s polling silent; offline→online one-time toast | fixed |
| 29 | medium | realtime | qr-terminal.html:48 | Hardcoded "30" countdown (real validity 60s) | Initial text "--" | fixed |
| 30 | medium | a11y | mobile-checkin.html:54, admin-console.html:28 | Icon-only logout no aria-label | aria-label + type="button" on relevant buttons | fixed |
| 31 | medium | error-state | mobile-checkin.js:273, individual-attendance.js:154, link-line.js:168 | alert/confirm for errors | alert() replaced with showResult/inline UI in 3 files; one confirm() kept (no in-page confirm UI) | fixed |
| 32 | low | quality | qr_checkin.py:152-154, location_service.py:188-192 | location_name not sanitized at write | `safe_location_name` helper applied at read sites | fixed |
| 33 | low | auth | main_unified.py:469-472 | `/api/private/test` info-leak | Now requires `Depends(require_admin_auth)` | fixed |
| 34 | low | redirect | line_auth.py:292-303 | LINE values not URL-encoded | `urllib.parse.quote` on line_user_id, display_name, picture_url, redirect | fixed |
| 35 | low | loading | qr-terminal.js:312-322 | WS reconnect no backoff cap | Exponential backoff capped at 60s + attempt counter in status badge | fixed |
| 36 | low | forms | link-line.html:33-43 | Missing autocomplete="one-time-code" | Added | fixed |
| 37 | low | cache | dashboard.html:11-26, export.html:17-23 | document.write warning post-parser | Wrapped in IIFE guarded by `readyState !== 'loading'` | fixed |
