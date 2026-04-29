from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from contextlib import asynccontextmanager
import logging
import asyncio
import os
from typing import List
import json
from datetime import datetime, timedelta
from app.utils.cache_busting import cache_manager

from app.core.database import engine, Base
from app.api import (
    consolidated_attendance, consolidated_devices, consolidated_employees, admin_line_codes, line_auth, qr_checkin
)

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

# Background task control
background_task = None
auto_import_start_time = None
last_auto_import_time = None

async def auto_import_fingerprint_logs():
    """Background task to automatically import fingerprint logs every 30 minutes"""
    global auto_import_start_time, last_auto_import_time
    
    auto_import_interval = int(os.getenv('AUTO_IMPORT_INTERVAL_MINUTES', '30')) * 60  # Convert to seconds
    auto_import_start_time = datetime.now()
    
    logger.info(f"Starting auto-import background task (interval: {auto_import_interval/60} minutes)")
    
    # Do immediate import on startup
    try:
        logger.info("Performing initial auto-import on startup...")
        
        # Import device service here to avoid circular imports
        from app.services.device_service import device_service

        # Perform sync (offload blocking ZK I/O to a thread)
        result = await asyncio.to_thread(device_service.sync_attendance_data)
        last_auto_import_time = datetime.now()

        if result["success"]:
            logger.info(f"Initial auto-import successful: {result.get('synced', 0)} records synced")

            # Broadcast update to WebSocket clients
            from app.services.attendance_service import attendance_service
            try:
                attendance_data = await asyncio.to_thread(attendance_service.get_attendance_summary)
                await manager.broadcast({
                    "type": "auto_import_update",
                    "data": attendance_data,
                    "synced_records": result.get('synced', 0),
                    "timestamp": datetime.now().isoformat(),
                    "message": f"นำเข้าอัตโนมัติ {result.get('synced', 0)} บันทึก (เริ่มระบบ)"
                })
            except Exception as broadcast_error:
                logger.warning(f"Failed to broadcast initial auto-import update: {broadcast_error}")
        else:
            logger.warning(f"Initial auto-import failed: {result.get('message', 'Unknown error')}")
            
    except Exception as e:
        logger.error(f"Initial auto-import error: {e}")
    
    while True:
        try:
            logger.info(f"Auto-import: Sleeping for {auto_import_interval} seconds ({auto_import_interval/60} minutes)...")
            await asyncio.sleep(auto_import_interval)

            logger.info("Auto-import: Woke up from sleep, starting import...")
            
            # Import device service here to avoid circular imports
            from app.services.device_service import device_service

            # Perform sync (offload blocking ZK I/O to a thread)
            result = await asyncio.to_thread(device_service.sync_attendance_data)
            last_auto_import_time = datetime.now()

            if result["success"]:
                logger.info(f"Auto-import successful: {result.get('synced', 0)} records synced")

                # Broadcast update to WebSocket clients
                from app.services.attendance_service import attendance_service
                try:
                    attendance_data = await asyncio.to_thread(attendance_service.get_attendance_summary)
                    await manager.broadcast({
                        "type": "auto_import_update",
                        "data": attendance_data,
                        "synced_records": result.get('synced', 0),
                        "timestamp": datetime.now().isoformat(),
                        "message": f"นำเข้าอัตโนมัติ {result.get('synced', 0)} บันทึก"
                    })
                except Exception as broadcast_error:
                    logger.warning(f"Failed to broadcast auto-import update: {broadcast_error}")
            else:
                logger.warning(f"Auto-import failed: {result.get('message', 'Unknown error')}")
                
        except Exception as e:
            logger.error(f"Auto-import background task error: {e}")
            # Continue running despite errors
            await asyncio.sleep(60)  # Wait 1 minute before retrying on error

@asynccontextmanager
async def lifespan(app: FastAPI):
    global background_task
    
    logger.info("Starting up unified server...")
    Base.metadata.create_all(bind=engine)
    
    # Start the background auto-import task
    background_task = asyncio.create_task(auto_import_fingerprint_logs())
    logger.info("Auto-import background task started")
    
    yield
    
    # Clean up background task
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            logger.info("Auto-import background task cancelled")
    
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

    # Admin session required for the privileged dashboard WebSocket
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

                # Trigger manual refresh using simplified services
                from app.services.device_service import device_service
                from app.services.attendance_service import attendance_service

                sync_result = await asyncio.to_thread(device_service.sync_attendance_data)
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
    response = FileResponse(file_path)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Serve HTML pages with cache control headers
@fingerprint_app.get("/")
async def serve_dashboard():
    return serve_html_with_cache_control("static/dashboard.html")

@fingerprint_app.get("/export")
async def serve_export():
    return serve_html_with_cache_control("static/export.html")

@fingerprint_app.get("/nickname-management")
async def serve_nickname_management(request: Request):
    """Serve employee nickname management page (requires authentication)

    Server-side authentication check to prevent unauthorized access.
    """
    # Check for session token in cookie
    admin_token = request.cookies.get('admin_session_token')

    # If no token, redirect to login page
    if not admin_token:
        return RedirectResponse(url="/fingerprintlogs/admin-login", status_code=302)

    # Validate session server-side
    from app.services.admin_auth_service import admin_auth_service

    if not admin_auth_service.validate_session(admin_token):
        # Session expired - clear cookie and redirect
        response = RedirectResponse(url="/fingerprintlogs/admin-login", status_code=302)
        _clear_admin_session_cookie(response)
        return response

    # Session valid - serve page
    return serve_html_with_cache_control("static/nickname-management.html")

@fingerprint_app.get("/individual-attendance")
async def serve_individual_attendance():
    return serve_html_with_cache_control("static/individual-attendance.html")

@fingerprint_app.get("/status")
async def serve_status(request: Request):
    """Serve system status page (requires authentication)

    Server-side authentication check to prevent unauthorized access.
    """
    # Check for session token in cookie
    admin_token = request.cookies.get('admin_session_token')

    # If no token, redirect to login page
    if not admin_token:
        return RedirectResponse(url="/fingerprintlogs/admin-login", status_code=302)

    # Validate session server-side
    from app.services.admin_auth_service import admin_auth_service

    if not admin_auth_service.validate_session(admin_token):
        # Session expired - clear cookie and redirect
        response = RedirectResponse(url="/fingerprintlogs/admin-login", status_code=302)
        _clear_admin_session_cookie(response)
        return response

    # Session valid - serve page
    return serve_html_with_cache_control("static/status.html")

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
    """
    # Check for session token in cookie
    admin_token = request.cookies.get('admin_session_token')

    # If no token, redirect to login page
    if not admin_token:
        return RedirectResponse(url="/fingerprintlogs/admin-login", status_code=302)

    # Validate session server-side
    from app.services.admin_auth_service import admin_auth_service

    if not admin_auth_service.validate_session(admin_token):
        # Session expired - clear cookie and redirect
        response = RedirectResponse(url="/fingerprintlogs/admin-login", status_code=302)
        _clear_admin_session_cookie(response)
        return response

    # Session valid - serve page
    return serve_html_with_cache_control("static/terminal-gps-admin.html")

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
    """
    # Check for session token in cookie
    admin_token = request.cookies.get('admin_session_token')

    # If no token, redirect immediately to login page
    # No assets will be loaded - just an HTTP 302 redirect
    if not admin_token:
        return RedirectResponse(url="/fingerprintlogs/admin-login", status_code=302)

    # Validate token server-side before serving any content
    from app.services.admin_auth_service import admin_auth_service

    if not admin_auth_service.validate_session(admin_token):
        # Session invalid or expired - clear cookie and redirect
        # Still no assets loaded - just redirect with cookie cleanup
        response = RedirectResponse(url="/fingerprintlogs/admin-login", status_code=302)
        _clear_admin_session_cookie(response)
        return response

    # Session valid - NOW we serve admin console HTML
    # Only at this point will any assets be loaded by the browser
    return serve_html_with_cache_control("static/admin-console.html")

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
from fastapi import Depends

logger.info("========== IMPORTED system_status AND admin_auth ==========")

# Simple test endpoint to verify root app routing works (admin-auth required)
@app.get("/api/private/test")
async def test_endpoint(_: str = Depends(require_admin_auth)):
    """Simple test endpoint to verify routing (admin-auth required)."""
    return {"status": "success", "message": "Root app routing works!", "timestamp": datetime.now().isoformat()}

# Mount protected API routers
app.include_router(
    consolidated_attendance.router,
    prefix="/api/private/attendance",
    tags=["attendance-protected"]
)

app.include_router(
    consolidated_devices.router,
    prefix="/api/private/devices",
    tags=["devices-protected"]
)

app.include_router(
    consolidated_employees.router,
    prefix="/api/private/employees",
    tags=["employees-protected"]
)

app.include_router(
    system_status.router,
    prefix="/api/private/system",
    tags=["system-protected"]
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

# Protected endpoint: Auto-import status
@app.get("/api/private/auto-import/status")
async def get_auto_import_status():
    """Get auto-import background task status"""
    global background_task, auto_import_start_time, last_auto_import_time
    
    auto_import_interval = int(os.getenv('AUTO_IMPORT_INTERVAL_MINUTES', '30'))
    
    # Calculate exact next import time
    next_import_estimate = "Unknown"
    if auto_import_start_time and last_auto_import_time:
        # Next import is 30 minutes after last import
        next_import_time = last_auto_import_time + timedelta(minutes=auto_import_interval)
        minutes_until_next = (next_import_time - datetime.now()).total_seconds() / 60
        
        if minutes_until_next > 0:
            if minutes_until_next < 1:
                next_import_estimate = f"In {int(minutes_until_next * 60)} seconds"
            else:
                next_import_estimate = f"In {int(minutes_until_next)} minutes"
        else:
            next_import_estimate = "Overdue (running now)"
    elif auto_import_start_time:
        # First import hasn't happened yet, calculate from start time
        next_import_time = auto_import_start_time + timedelta(minutes=auto_import_interval)
        minutes_until_next = (next_import_time - datetime.now()).total_seconds() / 60
        
        if minutes_until_next > 0:
            next_import_estimate = f"In {int(minutes_until_next)} minutes (first import)"
        else:
            next_import_estimate = "Running first import now"
    
    return {
        "enabled": background_task is not None and not background_task.done(),
        "interval_minutes": auto_import_interval,
        "task_status": "running" if background_task and not background_task.done() else "stopped",
        "next_import_estimate": next_import_estimate,
        "last_auto_import": last_auto_import_time.strftime('%Y-%m-%d %H:%M:%S') if last_auto_import_time else None,
        "service_started": auto_import_start_time.strftime('%Y-%m-%d %H:%M:%S') if auto_import_start_time else None
    }

@app.post("/api/private/auto-import/trigger/")
async def trigger_manual_import():
    """Manually trigger fingerprint log import"""
    try:
        from app.services.device_service import device_service

        logger.info("Manual import triggered via API")
        result = await asyncio.to_thread(device_service.sync_attendance_data)

        if result["success"]:
            # Broadcast update to WebSocket clients
            try:
                from app.services.attendance_service import attendance_service
                attendance_data = await asyncio.to_thread(attendance_service.get_attendance_summary)
                await manager.broadcast({
                    "type": "manual_import_update",
                    "data": attendance_data,
                    "synced_records": result.get('synced', 0),
                    "timestamp": datetime.now().isoformat(),
                    "message": f"นำเข้าด้วยตนเอง: ซิงค์แล้ว {result.get('synced', 0)} บันทึก"
                })
            except Exception as broadcast_error:
                logger.warning(f"Failed to broadcast manual import update: {broadcast_error}")

        # Return sanitized response (don't expose raw device data)
        synced_count = result.get("synced", 0)
        # Ensure synced count is a safe integer
        if not isinstance(synced_count, int):
            try:
                synced_count = int(synced_count) if str(synced_count).isdigit() else 0
            except (ValueError, TypeError):
                synced_count = 0

        return {
            "success": result.get("success", False),
            "synced": synced_count,
            "message": f"นำเข้าเสร็จสมบูรณ์: ประมวลผลแล้ว {synced_count} บันทึก"
        }
    except Exception as e:
        logger.error(f"Manual import failed: {e}")
        return {
            "success": False,
            "message": f"การนำเข้าด้วยตนเองล้มเหลว: {str(e)}"
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

# Manual refresh endpoint for dashboard (protected)
@app.post("/api/private/refresh")
async def manual_refresh():
    """Manual refresh endpoint for protected dashboard access"""
    try:
        # Use simplified device service for sync
        from app.services.device_service import device_service
        result = await asyncio.to_thread(device_service.sync_attendance_data)

        if result["success"]:
            # Broadcast update to WebSocket clients
            from app.services.attendance_service import attendance_service
            attendance_data = await asyncio.to_thread(attendance_service.get_attendance_summary)

            await manager.broadcast({
                "type": "attendance_update",
                "data": attendance_data,
                "timestamp": datetime.now().isoformat()
            })
        
        return result
    except Exception as e:
        logger.error(f"Manual refresh failed: {e}")
        return {
            "success": False,
            "message": f"การรีเฟรชล้มเหลว: {str(e)}"
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

                # Trigger manual refresh using simplified services
                from app.services.device_service import device_service
                from app.services.attendance_service import attendance_service

                sync_result = await asyncio.to_thread(device_service.sync_attendance_data)
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
    uvicorn.run(app, host="0.0.0.0", port=5000)