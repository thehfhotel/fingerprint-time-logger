from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
        
        # Perform sync
        result = device_service.sync_attendance_data()
        last_auto_import_time = datetime.now()
        
        if result["success"]:
            logger.info(f"Initial auto-import successful: {result.get('synced', 0)} records synced")
            
            # Broadcast update to WebSocket clients
            from app.services.attendance_service import attendance_service
            try:
                attendance_data = attendance_service.get_attendance_summary()
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
            
            # Perform sync
            result = device_service.sync_attendance_data()
            last_auto_import_time = datetime.now()
            
            if result["success"]:
                logger.info(f"Auto-import successful: {result.get('synced', 0)} records synced")
                
                # Broadcast update to WebSocket clients
                from app.services.attendance_service import attendance_service
                try:
                    attendance_data = attendance_service.get_attendance_summary()
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

# Create the main application
fingerprint_app = FastAPI(
    title="Fingerprint Time Logger - Unified",
    description="Unified API and Dashboard for ZKTeco fingerprint attendance tracking",
    version="2.0.0"
)

# Create root app to handle both direct access and tunneled access
app = FastAPI(title="Fingerprint Logger Root", lifespan=lifespan)

# CORS configuration for fingerprint_app
fingerprint_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# Include Consolidated API routers - Phase 4 Simplification
fingerprint_app.include_router(consolidated_attendance.router, prefix="/api/attendance", tags=["attendance"])
fingerprint_app.include_router(consolidated_devices.router, prefix="/api/devices", tags=["devices"])
fingerprint_app.include_router(consolidated_employees.router, prefix="/api/employees", tags=["employees"])

# System Status API - New comprehensive status monitoring
from app.api import system_status
fingerprint_app.include_router(system_status.router, prefix="/api/system", tags=["system-status"])

# Admin Line Codes API - QR Check-in Feature Phase 1
fingerprint_app.include_router(admin_line_codes.router, prefix="/api/admin/line-codes", tags=["admin-line-codes"])

# LINE Authentication API - QR Check-in Feature Phase 2
fingerprint_app.include_router(line_auth.router, prefix="/api/auth/line", tags=["line-auth"])

# QR Check-In API - QR Check-in Feature Phase 3
fingerprint_app.include_router(qr_checkin.router, prefix="/api/qr-checkin", tags=["qr-checkin"])


# WebSocket endpoint for real-time updates
@fingerprint_app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and handle incoming messages
            data = await websocket.receive_text()
            
            # Handle different message types
            message = json.loads(data)
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "refresh":
                # Trigger manual refresh using simplified services
                from app.services.device_service import device_service
                from app.services.attendance_service import attendance_service
                
                sync_result = device_service.sync_attendance_data()
                if sync_result["success"]:
                    attendance_data = attendance_service.get_attendance_summary()
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

@fingerprint_app.get("/device-status")
async def serve_device_status():
    return serve_html_with_cache_control("static/device-status.html")

@fingerprint_app.get("/export")
async def serve_export():
    return serve_html_with_cache_control("static/export.html")

@fingerprint_app.get("/nickname-management")
async def serve_nickname_management():
    return serve_html_with_cache_control("static/nickname-management.html")

@fingerprint_app.get("/individual-attendance")
async def serve_individual_attendance():
    return serve_html_with_cache_control("static/individual-attendance.html")

@fingerprint_app.get("/status")
async def serve_status():
    return serve_html_with_cache_control("static/status.html")

@fingerprint_app.get("/docs")
async def serve_api_docs():
    return serve_html_with_cache_control("static/swagger.html")

@fingerprint_app.get("/docs/openapi.yaml")
async def serve_openapi_spec():
    return FileResponse("docs/openapi.yaml")

@fingerprint_app.get("/health")
async def health_check():
    return {"status": "healthy", "server": "unified"}

@fingerprint_app.get("/api/auto-import/status")
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

@fingerprint_app.post("/api/auto-import/trigger")
async def trigger_manual_import():
    """Manually trigger fingerprint log import"""
    try:
        from app.services.device_service import device_service
        
        logger.info("Manual import triggered via API")
        result = device_service.sync_attendance_data()
        
        if result["success"]:
            # Broadcast update to WebSocket clients
            try:
                from app.services.attendance_service import attendance_service
                attendance_data = attendance_service.get_attendance_summary()
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
from fastapi.responses import RedirectResponse

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

# Legacy API endpoint for manual refresh (from dashboard)
@fingerprint_app.post("/api/refresh")
async def manual_refresh():
    """Manual refresh endpoint for backward compatibility"""
    try:
        # Use simplified device service for sync
        from app.services.device_service import device_service
        result = device_service.sync_attendance_data()
        
        if result["success"]:
            # Broadcast update to WebSocket clients
            from app.services.attendance_service import attendance_service
            attendance_data = attendance_service.get_attendance_summary()
            
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

# Add a root redirect for direct access
@app.get("/")
async def root_redirect():
    return {"message": "ระบบบันทึกเวลาด้วยลายนิ้วมือ", "dashboard": "/fingerprintlogs/"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)