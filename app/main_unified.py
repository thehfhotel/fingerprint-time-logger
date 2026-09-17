from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from contextlib import asynccontextmanager
import logging
import asyncio
import os
from typing import List
import json
from datetime import datetime, timedelta
from app.utils.cache_busting import cache_manager
from app.utils.static_asset_version import asset_version, version_static_urls

from app.core.database import engine, Base
from app.api import (
    consolidated_attendance, consolidated_devices, consolidated_employees,
    admin_line_codes, line_auth, qr_checkin, shifts, leaves,
    admin_employees, admin_onboarding, public_onboarding, oidc, reader,
    staff_oa,
)
from app.services.cf_access_service import get_cf_access_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# CORS / WebSocket origin allowlist
# ----------------------------------------------------------------------------
DEFAULT_CORS_ALLOWED_ORIGINS = "https://erp.thehfhotel.org,https://emp.thehfhotel.org"

def _parse_allowed_origins() -> List[str]:
    """Parse CORS_ALLOWED_ORIGINS env var into a clean allowlist.

    Comma-separated; whitespace stripped; empty values dropped.
    """
    raw = os.getenv("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ALLOWED_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]

ALLOWED_ORIGINS = _parse_allowed_origins()
logger.info(f"CORS allowlist: {ALLOWED_ORIGINS}")


def _is_behind_proxy() -> bool:
    """Whether the app is running behind a TLS-terminating proxy."""
    return os.getenv("BEHIND_PROXY", "false").lower() == "true"


def _clear_admin_session_cookie(response) -> None:
    """
    Delete the admin session cookie with attributes matching the original
    ``set_cookie`` call in :mod:`app.api.admin_auth`.

    Browsers ignore ``delete_cookie`` calls whose attributes (path,
    SameSite, Secure) do not match the original cookie under SameSite=Strict.
    """
    response.delete_cookie(
        "admin_session_token",
        path="/",
        samesite="strict",
        secure=_is_behind_proxy(),
        httponly=True,
    )


# ----------------------------------------------------------------------------
# Security headers middleware (shared by both apps)
# ----------------------------------------------------------------------------
async def _add_security_headers(request: Request, call_next):
    """Add baseline security headers to every response.

    HSTS is only added when running behind a TLS-terminating proxy.
    CSP is intentionally omitted (requires per-page tuning).
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if os.getenv("BEHIND_PROXY", "false").lower() == "true":
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        connection_count = len(self.active_connections)
        logger.info(f"Broadcasting message to {connection_count} connected clients: {message.get('type', 'unknown')}")

        if connection_count == 0:
            logger.warning("No active WebSocket connections - broadcast skipped")
            return

        disconnected = []
        successful = 0
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
                successful += 1
            except Exception as e:
                logger.error(f"Failed to send message to WebSocket client: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

        logger.info(f"Broadcast complete: {successful} successful, {len(disconnected)} failed")

manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    logger.info("Starting up unified server...")
    Base.metadata.create_all(bind=engine)

    # All ZKTeco device I/O is owned by the ZkSession daemon thread —
    # live_capture streams punches in real time and one-shot ops queue
    # through it. The 30-min scheduler import is now a backstop.
    from app.services.zk_session import zk_session
    zk_session.start(_asyncio.get_running_loop(), manager.broadcast)
    logger.info("ZkSession started")

    from app.services.background_scheduler import background_scheduler
    background_scheduler.start(broadcast_callback=manager.broadcast)
    logger.info("Background scheduler started")

    yield

    from app.services.background_scheduler import background_scheduler
    background_scheduler.shutdown(wait=False)
    from app.services.zk_session import zk_session
    zk_session.shutdown(wait=False)
    logger.info("Shutting down unified server...")

# ============================================================================
# FINGERPRINT_APP CONFIGURATION
# ============================================================================

# Create the main application
fingerprint_app = FastAPI(
    title="Fingerprint Time Logger - Unified",
    description="Unified API and Dashboard for ZKTeco fingerprint attendance tracking",
    version="2.0.0"
)

# CORS configuration for fingerprint_app
fingerprint_app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers for fingerprint_app
fingerprint_app.middleware("http")(_add_security_headers)

# Proxy headers middleware for nginx reverse proxy
if os.getenv("BEHIND_PROXY", "false").lower() == "true":
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    fingerprint_app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    logger.info("Proxy headers middleware enabled for nginx reverse proxy")

# Custom StaticFiles with cache control headers
class CacheControlStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        # Add aggressive cache control headers
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        # Force fresh content for JavaScript files
        if full_path.endswith('.js'):
            response.headers["ETag"] = f'"v2.0-https-fix-{hash(full_path)}"'
        return response

# Mount static files with cache control
fingerprint_app.mount("/static", CacheControlStaticFiles(directory="static"), name="static")

# Cache busting endpoint
@fingerprint_app.get("/api/static-version/{file_path:path}")
async def get_static_version(file_path: str):
    """Get versioned URL for static file"""
    return {"url": cache_manager.get_versioned_url(file_path)}

# Note: Protected APIs have been moved to root app with /api/private/* prefix
# See lines after root app creation for the new routing structure


# WebSocket endpoint for real-time updates
@fingerprint_app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Origin check (browser clients only — None means same-origin/non-browser)
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return

    # Admin session required for the privileged dashboard WebSocket.
    # A verified Cloudflare Access identity satisfies this too (auto-login).
    if not get_cf_access_email(websocket):
        from app.services.admin_auth_service import admin_auth_service
        admin_token = websocket.cookies.get("admin_session_token")
        if not admin_token or not admin_auth_service.validate_session(admin_token):
            await websocket.close(code=1008)
            return

    await manager.connect(websocket)
    last_refresh_at = None
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()

            # Handle different message types
            message = json.loads(data)
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "refresh":
                # Per-connection rate limit: 1 refresh per 60 seconds
                now_ts = datetime.now()
                if last_refresh_at is not None and (now_ts - last_refresh_at).total_seconds() < 60:
                    await websocket.send_json({"type": "rate_limited"})
                    continue
                last_refresh_at = now_ts

                # Trigger manual refresh through the scheduler so the
                # device lock is honoured.
                from app.services.background_scheduler import background_scheduler
                from app.services.attendance_service import attendance_service

                sync_result = await background_scheduler.run_attendance_import_now()
                if sync_result["success"]:
                    attendance_data = await asyncio.to_thread(attendance_service.get_attendance_summary)
                    await websocket.send_json({
                        "type": "attendance_update",
                        "data": attendance_data,
                        "timestamp": datetime.now().isoformat()
                    })

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# Helper function to serve HTML with cache control headers
def serve_html_with_cache_control(file_path: str):
    # Stamp every /fingerprintlogs/static/** asset URL with this deploy's
    # version (see app/utils/static_asset_version.py) so the edge cache in
    # front of us — which ignores our no-store header and caches by URL —
    # gets a brand-new cache key for nav.js/theme.js/etc. on every deploy,
    # instead of serving up to 4 hours of the previous release's assets.
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()
    html = version_static_urls(html, asset_version())
    response = HTMLResponse(content=html)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


ADMIN_LOGIN_URL = "/fingerprintlogs/admin-login"


def serve_admin_page(request: Request, file_path: str):
    """Serve an admin-only HTML page, or redirect to the passcode login.

    THE single server-side admin page guard. Server-side (not client-side)
    so NO HTML/CSS/JS asset reaches the browser before authentication is
    confirmed — a 302 is all an unauthenticated caller ever sees.

    Resolution order (unchanged from the four inline copies this replaces —
    /employee-management, /status, /admin/terminal-gps, /admin-console):
      1. Verified Cloudflare Access identity for an admin-allowlisted email
         -> serve (auto-login, no passcode prompt).
      2. No ``admin_session_token`` cookie -> 302 to the login page.
      3. Cookie present but session invalid/expired -> clear the cookie
         (with matching attributes, see ``_clear_admin_session_cookie``)
         and 302 to the login page.
      4. Session valid -> serve.

    NOTE FOR WP5b (v1 retirement, deploy 2): when the owner signals the
    cutover, the v1 pages below (/employee-management, /status,
    /admin/terminal-gps, /admin-console) become 302s to their /v2/*
    replacements. THIS is where those redirects go — replace the v1 route
    bodies, leave this helper and the /v2/* routes that use it alone.
    Deploy 1 (this change) is purely additive: no v1 route behaviour changes.
    """
    # A verified Cloudflare Access identity is treated as authenticated
    # admin (auto-login), no passcode prompt needed.
    if get_cf_access_email(request):
        return serve_html_with_cache_control(file_path)

    # Check for session token in cookie
    admin_token = request.cookies.get('admin_session_token')

    # If no token, redirect to login page
    if not admin_token:
        return RedirectResponse(url=ADMIN_LOGIN_URL, status_code=302)

    # Validate session server-side
    from app.services.admin_auth_service import admin_auth_service

    if not admin_auth_service.validate_session(admin_token):
        # Session invalid or expired - clear cookie and redirect
        response = RedirectResponse(url=ADMIN_LOGIN_URL, status_code=302)
        _clear_admin_session_cookie(response)
        return response

    # Session valid - serve page
    return serve_html_with_cache_control(file_path)


# Serve HTML pages with cache control headers
@fingerprint_app.get("/")
async def serve_dashboard():
    return serve_html_with_cache_control("static/dashboard.html")

@fingerprint_app.get("/v2/")
async def serve_v2_hub():
    return serve_html_with_cache_control("static/v2/index.html")

@fingerprint_app.get("/v2/live")
async def serve_v2_live():
    return serve_html_with_cache_control("static/v2/live.html")

@fingerprint_app.get("/v2/by-date")
async def serve_v2_by_date():
    return serve_html_with_cache_control("static/v2/by-date.html")

@fingerprint_app.get("/v2/shifts-admin")
async def serve_v2_shifts_admin():
    """Shift admin page (role + default shift + reception roster).

    Linked from the v2 nav as 'จัดกะ'. Same Cloudflare Access posture
    as the rest of /fingerprintlogs/* — protected upstream, not at the
    FastAPI layer.
    """
    return serve_html_with_cache_control("static/v2/shifts-admin.html")

@fingerprint_app.get("/v2/leaves")
async def serve_v2_leaves():
    """วันลา · วันหยุด — per-employee leave/holiday Kanban, its own
    top-level page (moved off the จัดกะ tab strip).

    Linked from the v2 nav as 'วันลา · วันหยุด'. Same Cloudflare Access
    posture as the rest of /fingerprintlogs/* — protected upstream, not at
    the FastAPI layer (ungated here, same as shifts-admin/monthly above).
    """
    return serve_html_with_cache_control("static/v2/leaves.html")

@fingerprint_app.get("/v2/monthly")
async def serve_v2_monthly():
    """Monthly payroll/management report — per-employee timesheet + grid.

    Linked from the v2 nav as 'รายเดือน'. Same Cloudflare Access posture
    as the rest of /fingerprintlogs/* — protected upstream.
    """
    return serve_html_with_cache_control("static/v2/monthly.html")

# ----------------------------------------------------------------------------
# v2 admin pages (2026-08). The v2 replacements for the four legacy admin
# pages. ADDITIVE: the v1 pages below keep serving unchanged — the v1 -> v2
# retirement is a separate, owner-signalled deploy (see serve_admin_page).
#
# Unlike the ungated v2 pages above, these carry the same server-side admin
# guard as their v1 counterparts, so an unauthenticated caller gets a 302 and
# no page assets.
# ----------------------------------------------------------------------------

@fingerprint_app.get("/v2/employees")
async def serve_v2_employees(request: Request):
    """v2 employee registry (replaces /employee-management)."""
    return serve_admin_page(request, "static/v2/employees.html")

@fingerprint_app.get("/v2/system")
async def serve_v2_system(request: Request):
    """v2 system status + admin console (replaces /status + /admin-console)."""
    return serve_admin_page(request, "static/v2/system.html")

@fingerprint_app.get("/v2/terminals")
async def serve_v2_terminals(request: Request):
    """v2 QR terminal GPS admin (replaces /admin/terminal-gps)."""
    return serve_admin_page(request, "static/v2/terminals.html")

@fingerprint_app.get("/export")
async def serve_export():
    return serve_html_with_cache_control("static/export.html")

@fingerprint_app.get("/nickname-management")
async def redirect_nickname_management():
    """Old nickname-management page — replaced by the employee registry
    (employee-management.html). APIs are unchanged; only the admin page
    moved. Permanent redirect so bookmarks/links keep working.
    """
    return RedirectResponse(url="/fingerprintlogs/employee-management", status_code=301)


@fingerprint_app.get("/employee-management")
async def serve_employee_management(request: Request):
    """Serve the employee registry page (requires authentication).

    Replaces nickname-management.html: device+DB employee list, LINE
    linking codes, pending self-onboarding approvals, app grants, NFC
    card assignment, and the device-badge/Q-badge merge tool.

    Server-side authentication check to prevent unauthorized access.
    Recognizes a verified Cloudflare Access identity as well as the
    existing passcode session cookie.
    """
    return serve_admin_page(request, "static/employee-management.html")

@fingerprint_app.get("/individual-attendance")
async def serve_individual_attendance():
    return serve_html_with_cache_control("static/individual-attendance.html")

@fingerprint_app.get("/status")
async def serve_status(request: Request):
    """Serve system status page (requires authentication)

    Server-side authentication check to prevent unauthorized access.
    Recognizes a verified Cloudflare Access identity as well as the
    existing passcode session cookie.
    """
    return serve_admin_page(request, "static/status.html")

@fingerprint_app.get("/docs")
async def serve_api_docs():
    return serve_html_with_cache_control("static/swagger.html")

@fingerprint_app.get("/docs/openapi.yaml")
async def serve_openapi_spec():
    return FileResponse("docs/openapi.yaml")

# QR Check-in UI Pages - Phase 4
@fingerprint_app.get("/qr-checkin/link-account")
async def serve_link_account():
    """Serve LINE account linking page"""
    return serve_html_with_cache_control("static/link-line.html")

@fingerprint_app.get("/qr-checkin/onboard")
async def serve_onboard():
    """Serve the public self-service employee onboarding page.

    Public, chromeless (no hf-bar band), like link-line.html/mobile-checkin.html
    — this path is already Cloudflare-bypassed.
    """
    return serve_html_with_cache_control("static/onboard.html")

@fingerprint_app.get("/qr-checkin/mobile")
async def serve_mobile_checkin():
    """Serve mobile QR check-in page"""
    return serve_html_with_cache_control("static/mobile-checkin.html")

@fingerprint_app.get("/qr-checkin/terminal")
async def serve_qr_terminal():
    """Serve kiosk QR terminal display page"""
    return serve_html_with_cache_control("static/qr-terminal.html")

@fingerprint_app.get("/qr-checkin/scan")
async def serve_qr_scan_landing():
    """Serve QR scan landing page with auto-redirect logic"""
    return serve_html_with_cache_control("static/qr-scan.html")

@fingerprint_app.get("/qr-checkin/scan-callback")
async def serve_qr_scan_callback():
    """Serve QR scan OAuth callback page"""
    return serve_html_with_cache_control("static/qr-scan-callback.html")

@fingerprint_app.get("/admin/terminal-gps")
async def serve_terminal_gps_admin(request: Request):
    """Serve QR terminal GPS location admin page (requires authentication)

    Server-side authentication check to prevent unauthorized access.
    Recognizes a verified Cloudflare Access identity as well as the
    existing passcode session cookie.
    """
    return serve_admin_page(request, "static/terminal-gps-admin.html")

@fingerprint_app.get("/admin-login")
async def serve_admin_login():
    """Serve admin login page"""
    return serve_html_with_cache_control("static/admin-login.html")

@fingerprint_app.get("/admin-console")
async def serve_admin_console(request: Request):
    """Serve admin console configuration page (requires authentication)

    Server-side authentication check to prevent any client-side assets
    from loading before authentication is verified. This ensures NO HTML,
    CSS, JavaScript, or any other assets are sent to the browser before
    authentication is confirmed on the server side.

    Recognizes a verified Cloudflare Access identity as well as the
    existing passcode session cookie.
    """
    return serve_admin_page(request, "static/admin-console.html")

@fingerprint_app.get("/health")
async def health_check():
    return {"status": "healthy", "server": "unified"}

# ============================================================================
# ROOT APP CONFIGURATION
# ============================================================================

logger.info("========== CREATING ROOT APP ==========")

# Create root app to handle both direct access and tunneled access
app = FastAPI(title="Fingerprint Logger Root", lifespan=lifespan)

logger.info(f"========== ROOT APP CREATED: {app} ==========")

# CORS configuration for root app (for /api/private/* and /qr-checkin/api/* endpoints)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers for root app
app.middleware("http")(_add_security_headers)

# Proxy headers middleware for nginx reverse proxy - ROOT APP
# This ensures FastAPI generates correct HTTPS URLs in redirects when behind nginx
if os.getenv("BEHIND_PROXY", "false").lower() == "true":
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    logger.info("Proxy headers middleware enabled for root app (nginx reverse proxy)")

# ============================================================================
# PROTECTED APIs - Admin Management (Cloudflare Access: /api/private/*)
# ============================================================================

logger.info("========== REGISTERING PROTECTED API ROUTES ==========")

# Import system_status and admin_auth routers
from app.api import system_status, admin_auth
from app.api.admin_auth import require_admin_auth
from app.api.deps import require_cf_access
from fastapi import Depends

logger.info("========== IMPORTED system_status AND admin_auth ==========")

# Simple test endpoint to verify root app routing works (admin-auth required)
@app.get("/api/private/test")
async def test_endpoint(_: str = Depends(require_admin_auth)):
    """Simple test endpoint to verify routing (admin-auth required)."""
    return {"status": "success", "message": "Root app routing works!", "timestamp": datetime.now().isoformat()}

# Mount protected API routers
#
# dependencies=[Depends(require_cf_access)] on these six (attendance,
# devices, employees, system, shifts, leaves below): defense-in-depth
# against a future ungated hostname pointing at this same process — see
# app/api/deps.py's module docstring for the full rationale, and why this
# is require_cf_access (any verified staff-tier CF Access identity), NOT
# require_admin_auth (admin-allowlist only — would 401 the legitimate
# non-admin staff/kiosk sessions these routers already serve).
app.include_router(
    consolidated_attendance.router,
    prefix="/api/private/attendance",
    tags=["attendance-protected"],
    dependencies=[Depends(require_cf_access)],
)

app.include_router(
    consolidated_devices.router,
    prefix="/api/private/devices",
    tags=["devices-protected"],
    dependencies=[Depends(require_cf_access)],
)

app.include_router(
    consolidated_employees.router,
    prefix="/api/private/employees",
    tags=["employees-protected"],
    dependencies=[Depends(require_cf_access)],
)

app.include_router(
    system_status.router,
    prefix="/api/private/system",
    tags=["system-protected"],
    dependencies=[Depends(require_cf_access)],
)

app.include_router(
    admin_auth.router,
    prefix="/api/private/admin/auth",
    tags=["admin-auth-protected"]
)

app.include_router(
    admin_line_codes.router,
    prefix="/api/private/admin/line-codes",
    tags=["line-codes-protected"]
)

# Shift admin (2026-05). Defines work shifts and per-day overrides used
# by /by-date for late/absent detection.
app.include_router(
    shifts.router,
    prefix="/api/private/shifts",
    tags=["shifts-protected"],
    dependencies=[Depends(require_cf_access)],
)

# Leaves admin (2026-05). Public holidays + per-employee leaves; both
# consumed by the roster grid + /by-date.
app.include_router(
    leaves.router,
    prefix="/api/private/leaves",
    tags=["leaves-protected"],
    dependencies=[Depends(require_cf_access)],
)

# Employee registry admin (2026-07): app grants, NFC card slot, and the
# device-badge/Q-badge merge tool.
app.include_router(
    admin_employees.router,
    prefix="/api/private/admin/employees",
    tags=["admin-employees-protected"],
)

# Self-service onboarding approvals (2026-07).
app.include_router(
    admin_onboarding.router,
    prefix="/api/private/admin/onboarding",
    tags=["admin-onboarding-protected"],
)

# Card-reader identity resolution (2026-07): server-to-server NFC-card-UID ->
# employee lookup the new-hotel PMS calls. Authenticated by the shared
# X-Reader-Secret header (constant-time); dark/404 until READER_RESOLVE_SECRET
# is set. This is the central identity authority for staff NFC cards.
app.include_router(
    reader.router,
    prefix="/api/private/reader",
    tags=["reader-protected"],
)

# Protected endpoint: Auto-import status
#
# Same bare-router exposure class as the six above (this and the two
# endpoints below sit just outside the include_router block, but were an
# equally unauthenticated /api/private/* surface) — gated with the same
# require_cf_access for the same reason. system.html (the only caller,
# itself admin-page-gated) already carries a valid CF Access assertion,
# so this is strictly additive.
@app.get("/api/private/auto-import/status")
async def get_auto_import_status(_: str = Depends(require_cf_access)):
    """Get background scheduler status, including the next attendance import."""
    from app.services.background_scheduler import background_scheduler

    status = background_scheduler.get_job_status()
    import_job = next((j for j in status["jobs"] if j["id"] == "import_attendance"), None)

    auto_import_interval = int(os.getenv("AUTO_IMPORT_INTERVAL_MINUTES", "30"))
    next_run = import_job["next_run"] if import_job else None

    next_import_estimate = "Unknown"
    if next_run:
        try:
            next_dt = datetime.fromisoformat(next_run)
            minutes_until = (next_dt - datetime.now(next_dt.tzinfo)).total_seconds() / 60
            if minutes_until <= 0:
                next_import_estimate = "Overdue (running now)"
            elif minutes_until < 1:
                next_import_estimate = f"In {int(minutes_until * 60)} seconds"
            else:
                next_import_estimate = f"In {int(minutes_until)} minutes"
        except Exception:
            next_import_estimate = next_run

    return {
        "enabled": status["running"],
        "interval_minutes": auto_import_interval,
        "task_status": "running" if status["running"] else "stopped",
        "next_import_estimate": next_import_estimate,
        "jobs": status["jobs"],
    }


@app.post("/api/private/auto-import/trigger/")
async def trigger_manual_import(full: bool = False, _: str = Depends(require_cf_access)):
    """Manually trigger an attendance import via the scheduler."""
    try:
        from app.services.background_scheduler import background_scheduler

        logger.info("Manual import triggered via API (full=%s)", full)
        result = await background_scheduler.run_attendance_import_now(full=full)

        synced_count = result.get("synced", 0)
        if not isinstance(synced_count, int):
            try:
                synced_count = int(synced_count)
            except (ValueError, TypeError):
                synced_count = 0

        return {
            "success": bool(result.get("success", False)),
            "synced": synced_count,
            "message": f"นำเข้าเสร็จสมบูรณ์: ประมวลผลแล้ว {synced_count} บันทึก"
            if result.get("success")
            else result.get("message", "Import failed"),
        }
    except Exception as e:
        logger.error(f"Manual import failed: {e}")
        return {
            "success": False,
            "message": f"การนำเข้าด้วยตนเองล้มเหลว: {str(e)}",
        }

# Redirect old routes to new simplified interface
from fastapi import HTTPException

@fingerprint_app.get("/employee-management")
async def redirect_employee_management():
    return RedirectResponse(url="/", status_code=301)

@fingerprint_app.get("/work-schedules") 
async def redirect_work_schedules():
    return RedirectResponse(url="/", status_code=301)

@fingerprint_app.get("/attendance-calendar")
async def redirect_attendance_calendar():
    return RedirectResponse(url="/", status_code=301)

@fingerprint_app.get("/favicon.ico")
async def favicon():
    return {"status": "no favicon"}

# Manual refresh endpoint for dashboard. The docstring/comment here has
# long said "(protected)" but until this change nothing enforced that —
# same bare-/api/private/* exposure class as the six consolidated routers
# above; now closed with the same require_cf_access dependency.
@app.post("/api/private/refresh")
async def manual_refresh(_: str = Depends(require_cf_access)):
    """Manual refresh: trigger an attendance import through the scheduler."""
    try:
        from app.services.background_scheduler import background_scheduler
        return await background_scheduler.run_attendance_import_now()
    except Exception as e:
        logger.error(f"Manual refresh failed: {e}")
        return {
            "success": False,
            "message": f"การรีเฟรชล้มเหลว: {str(e)}",
        }

# Mount the fingerprint app for tunnel support
app.mount("/fingerprintlogs", fingerprint_app, name="fingerprint_tunnel")

# Mount static files at root level for direct IP access (without nginx)
app.mount("/static", CacheControlStaticFiles(directory="static"), name="static_direct")

# Add direct access routes for QR check-in (for local network access without nginx)
# These routes handle both nginx-proxied access and direct IP access
@app.get("/qr-checkin/terminal")
async def root_serve_qr_terminal():
    """Serve QR terminal for direct IP access (without nginx proxy)"""
    return serve_html_with_cache_control("static/qr-terminal.html")

@app.get("/qr-checkin/mobile")
async def root_serve_mobile_checkin():
    """Serve mobile check-in for direct IP access (without nginx proxy)"""
    return serve_html_with_cache_control("static/mobile-checkin.html")

@app.get("/qr-checkin/link-account")
async def root_serve_link_account():
    """Serve LINE account linking for direct IP access (without nginx proxy)"""
    return serve_html_with_cache_control("static/link-line.html")

@app.get("/qr-checkin/onboard")
async def root_serve_onboard():
    """Serve self-service employee onboarding for direct IP access (without nginx proxy)"""
    return serve_html_with_cache_control("static/onboard.html")

# ============================================================================
# PUBLIC APIs - QR Check-in & Authentication (No Authentication Required)
# ============================================================================

# Mount QR checkin API router for public access
# Pattern: /api/public/* (consistent with /api/private/*)
app.include_router(
    qr_checkin.router,
    prefix="/api/public/qr-checkin",
    tags=["qr-checkin-public"]
)

# Mount LINE auth router for public access
# Pattern: /api/public/* (consistent with /api/private/*)
app.include_router(
    line_auth.router,
    prefix="/api/public/auth/line",
    tags=["line-auth-public"]
)

# Mount self-service employee onboarding router for public access
# (LINE-JWT-gated, not admin-auth — see app/api/public_onboarding.py)
app.include_router(
    public_onboarding.router,
    prefix="/api/public/onboarding",
    tags=["onboarding-public"]
)

# Employee self-service card-login (2026-07): "tap your NFC staff card to log
# in" for an employee viewing their own attendance. Reader-secret-free (the
# browser is the employee's own terminal); resolves the tap IN-PROCESS from the
# reader module's pending-tap store and mints the same LINE-JWT self-service
# session the LINE-login path mints. Ships DARK (404) until READER_SECRET is set.
app.include_router(
    reader.public_router,
    prefix="/api/public/reader",
    tags=["reader-self-login-public"],
)

# HF ID — OIDC identity provider (LINE-brokered employee SSO for Cloudflare
# Access). Served at id.thehfhotel.org/oidc/*. Ships DARK: every endpoint
# 404s until HFID_SIGNING_KEY is configured (see app/services/oidc_service.py).
app.include_router(
    oidc.router,
    prefix="/oidc",
    tags=["hf-id-oidc"],
)

# Employee Hub — staff LINE OA webhook (2026-07): follow events link each
# employee's grant-driven Role Menu (rich menu). Ships DARK: answers 503
# until STAFF_OA_CHANNEL_ACCESS_TOKEN + STAFF_OA_CHANNEL_SECRET are set
# (see app/core/config.py + app/services/staff_oa_service.py).
app.include_router(
    staff_oa.router,
    prefix="/api/public/staff-oa",
    tags=["staff-oa-public"],
)

# ============================================================================
# LEGACY PUBLIC API ROUTES - Backward Compatibility (301 Redirects)
# ============================================================================
#
# DEPRECATION NOTICE (2025-10-16):
# These routes provide backward compatibility for QR terminals and mobile devices
# using the old /qr-checkin/api/* URL pattern. All new implementations should use
# the /api/public/* pattern for consistency with protected /api/private/* endpoints.
#
# Migration Path:
# - Phase 1 (Current): Both old and new URLs work (redirects active)
# - Phase 2 (Future): Monitor redirect usage, identify devices needing updates
# - Phase 3 (TBD): Deprecate redirects after all devices updated
#
# Redirect Behavior:
# - GET requests: 301 Permanent Redirect (browsers cache the redirect)
# - POST requests: 307 Temporary Redirect (preserves POST method and body)
# ============================================================================

from fastapi.responses import RedirectResponse

@app.get("/qr-checkin/api/qr-checkin/{path:path}")
async def legacy_qr_checkin_redirect(path: str):
    """
    DEPRECATED: Redirect legacy QR check-in API paths to new public API

    Use /api/public/qr-checkin/{path} instead
    """
    return RedirectResponse(url=f"/api/public/qr-checkin/{path}", status_code=301)

@app.post("/qr-checkin/api/qr-checkin/{path:path}")
async def legacy_qr_checkin_post_redirect(path: str):
    """
    DEPRECATED: Redirect legacy QR check-in POST requests to new public API

    Use /api/public/qr-checkin/{path} instead
    """
    return RedirectResponse(url=f"/api/public/qr-checkin/{path}", status_code=307)

@app.get("/qr-checkin/api/auth/line/{path:path}")
async def legacy_line_auth_redirect(path: str):
    """
    DEPRECATED: Redirect legacy LINE auth paths to new public API

    Use /api/public/auth/line/{path} instead
    """
    return RedirectResponse(url=f"/api/public/auth/line/{path}", status_code=301)

@app.post("/qr-checkin/api/auth/line/{path:path}")
async def legacy_line_auth_post_redirect(path: str):
    """
    DEPRECATED: Redirect legacy LINE auth POST requests to new public API

    Use /api/public/auth/line/{path} instead
    """
    return RedirectResponse(url=f"/api/public/auth/line/{path}", status_code=307)

# Mount WebSocket at root level for unprotected access
@app.websocket("/qr-checkin/ws")
async def root_websocket_endpoint(websocket: WebSocket):
    """Root-level WebSocket for unprotected QR terminal access.

    Public endpoint (kiosk display); no admin session required, but the Origin
    header is validated against the CORS allowlist when present.
    """
    # Origin check (browser clients only — None means same-origin/non-browser)
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)
    last_refresh_at = None
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()

            # Handle different message types
            message = json.loads(data)
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "refresh":
                # Per-connection rate limit: 1 refresh per 60 seconds
                now_ts = datetime.now()
                if last_refresh_at is not None and (now_ts - last_refresh_at).total_seconds() < 60:
                    await websocket.send_json({"type": "rate_limited"})
                    continue
                last_refresh_at = now_ts

                # Trigger manual refresh through the scheduler so the
                # device lock is honoured.
                from app.services.background_scheduler import background_scheduler
                from app.services.attendance_service import attendance_service

                sync_result = await background_scheduler.run_attendance_import_now()
                if sync_result["success"]:
                    attendance_data = await asyncio.to_thread(attendance_service.get_attendance_summary)
                    await websocket.send_json({
                        "type": "attendance_update",
                        "data": attendance_data,
                        "timestamp": datetime.now().isoformat()
                    })

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# Add a root redirect for direct access
@app.get("/")
async def root_redirect():
    return {"message": "ระบบบันทึกเวลาด้วยลายนิ้วมือ", "dashboard": "/fingerprintlogs/"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)  # nosec B104 — same rationale as config.py