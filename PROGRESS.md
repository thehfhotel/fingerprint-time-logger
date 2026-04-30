# Polish Progress

## Config
- **Branch**: main @ b15fa380 (baseline)
- **Stack**: Python (FastAPI) + JavaScript frontend + Docker + SQLite
- **Scope**: entire project
- **Auditors**: reviewer, security, ux
- **Intent**: (none)
- **Mode**: review (triage on iteration 1, auto-fix iterations 2+)
- **Max iterations**: 5

## Current Status
- **Iteration**: 3
- **Phase**: complete (converged with 0 findings)

## Iteration History

### Iteration 1
- **Found**: 37 (0 skipped)
- **Fixed**: 37
- **Files changed**: 23 source (15 .py, 5 HTML, 5 JS — plus admin-console.html as collateral for #24)
- **Commit**: 16b67b86

### Iteration 2
- **Found**: 9 (0 skipped) — regressions and missed issues from iter 1
- **Fixed**: 9
- **Files changed**: 14 + 1 new (10 .py incl. new app/utils/timezone.py, 4 HTML)
- **Commit**: 0784073d

### Iteration 3
- **Found**: 0 — converged
- **Fixed**: 0
- **Files changed**: docs only (PROGRESS.md, AUDIT.md)
- **Commit**: _(pending — doc-only)_

## Final Summary

- **Iterations**: 3
- **Total findings**: 46 (37 + 9 + 0)
- **Fixed**: 46
- **Skipped**: 0
- **Unfixable**: 0
- **PLAN.md gaps**: 0 — all planned features verified intact
- **Convergence**: yes (iteration 3 returned 0 findings from both auditors)

### Validation gap

I could not run the test suite locally — the project venv is Linux-built for Docker. All modified Python files pass `py_compile`/AST checks, and JS files pass `node --check`. **Before deploying, verify in Docker**:

```bash
docker compose down && docker compose build app && docker compose up -d
./scripts/run-complete-test-suite.sh
```

### New environment variables introduced

These should be set for production:
- `CORS_ALLOWED_ORIGINS` — comma-separated allowlist (default: `https://erp.thehfhotel.org,https://emp.thehfhotel.org`)
- `JWT_SECRET` — REQUIRED in production (no longer has a silent placeholder default)
- `ADMIN_PASSCODE_HASH` — REQUIRED in production (no longer has a hardcoded fallback)
- `ENV` / `ENVIRONMENT` — set to `production` or unset in prod (any of `dev`/`development`/`local`/`test` enables dev fallback with logger.warning)

Existing `BEHIND_PROXY=true` now also gates: cookie `Secure` flag, HSTS header, `X-Forwarded-For` / `CF-Connecting-IP` trust for rate limiting.

### Behavioral API changes

- `POST /api/public/auth/line/unlink-account` now requires `Authorization: Bearer <LINE-JWT>` instead of an `admin_passcode` body field. Mobile clients calling this need updating.
- `GET /api/private/test` now requires admin auth (was unauthenticated routing-verifier).
- WebSocket `/fingerprintlogs/ws` now requires the `admin_session_token` cookie + Origin allowlist.
- WebSocket `/qr-checkin/ws` requires Origin allowlist (no auth — kiosk display).
