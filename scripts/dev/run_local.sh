#!/usr/bin/env bash
# Run fingerprint-time-logger locally on a spare port, against a seeded
# throwaway SQLite database, with no ZKTeco device or Cloudflare Access
# required. Lets a UI agent load/screenshot any page and see real-looking
# data without deploying.
#
# One-liner:
#   ./scripts/dev/run_local.sh
#
# Then browse (or screenshot, see scripts/dev/shot.mjs):
#   http://localhost:5055/fingerprintlogs/v2/
#
# Stop with Ctrl-C (foreground) or `kill` the PID this script prints.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv-local"
if [ ! -x "$VENV/bin/python" ]; then
  echo "Missing venv at $VENV — create it first:" >&2
  echo "  python3.12 -m venv .venv-local && .venv-local/bin/pip install -r requirements.txt" >&2
  exit 1
fi

PORT="${PORT:-5055}"
DB_PATH="$REPO_ROOT/database/local_dev.db"

# --- Strict prod-config validation (app/services/{qr,line_auth}_service.py,
# app/services/admin_auth_service.py) needs SOMETHING here at import time.
# Setting ENV=test puts those modules in their "dev environment" branch, so
# JWT_SECRET / ADMIN_PASSCODE_HASH are DELIBERATELY LEFT UNSET below rather
# than filled with CI's throwaway values — that makes each module generate
# a real, USABLE dev default instead of a value nobody knows:
#   JWT_SECRET      -> "dev-jwt-secret-CHANGE-ME"
#   ADMIN_PASSCODE_HASH -> bcrypt hash of "dev-passcode-CHANGE-ME"
#     (only matters if you want to log into /fingerprintlogs/admin-login;
#     the v2 pages' JSON APIs are NOT gated by this locally — see README).
export ENV=test
export TESTING=true

# CORS + WebSocket origin allowlist must include the port we're serving on,
# or fingerprint_app's /ws handshake self-closes (code 1008) on the Origin
# check in app/main_unified.py — the page still loads, but the "live" pill
# on /v2/live will read disconnected forever.
export CORS_ALLOWED_ORIGINS="http://localhost:${PORT},http://127.0.0.1:${PORT}"

# NOTE: the app's pydantic Settings (app/core/config.py) uses
# env_prefix="FINGERPRINT_" for every field including database_url — a
# plain DATABASE_URL is silently IGNORED (Settings just falls back to its
# hardcoded default sqlite:///./database/attendance.db). Learned the hard
# way: seeding once wrote into database/attendance.db instead of our
# throwaway file because of this. Must be FINGERPRINT_DATABASE_URL.
export FINGERPRINT_DATABASE_URL="sqlite:///${DB_PATH}"
export BEHIND_PROXY=false

# Point at a deliberately unreachable-but-fails-fast ZK device instead of
# the real LAN IP (192.168.100.209, unreachable from a laptop off that
# LAN) — the background scheduler retries this every 5 min forever either
# way, but a refused localhost connection fails in milliseconds instead of
# hanging for the full zkteco_timeout on every attempt.
export ZKTECO_HOST="${ZKTECO_HOST:-127.0.0.1}"
export ZKTECO_PORT="${ZKTECO_PORT:-4370}"

mkdir -p "$REPO_ROOT/database"

if [ ! -f "$DB_PATH" ]; then
  echo "No local DB at $DB_PATH — seeding fake data..."
  "$VENV/bin/python" scripts/dev/seed_local_db.py
else
  echo "Reusing existing local DB at $DB_PATH (delete it, or run"
  echo "  scripts/dev/seed_local_db.py --reset"
  echo "to get fresh data)."
fi

echo "Starting uvicorn on http://localhost:${PORT}/fingerprintlogs/v2/ (ENV=test, no CF Access)"
exec "$VENV/bin/python" -m uvicorn app.main_unified:app --host 127.0.0.1 --port "$PORT"
