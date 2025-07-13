from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import logging
import asyncio
import os
from typing import List
import json
from datetime import datetime

from app.core.database import engine, Base
from app.api import (
    consolidated_attendance, consolidated_devices, consolidated_employees, 
    consolidated_export
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
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

# Background task control
background_task = None

async def auto_import_fingerprint_logs():
    """Background task to automatically import fingerprint logs every 30 minutes"""
    auto_import_interval = int(os.getenv('AUTO_IMPORT_INTERVAL_MINUTES', '30')) * 60  # Convert to seconds
    
    logger.info(f"Starting auto-import background task (interval: {auto_import_interval/60} minutes)")
    
    while True:
        try:
            await asyncio.sleep(auto_import_interval)
            
            logger.info("Auto-importing fingerprint logs...")
            
            # Import device service here to avoid circular imports
            from app.services.device_service import device_service
            
            # Perform sync
            result = device_service.sync_attendance_data()
            
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
                        "message": f"Auto-imported {result.get('synced', 0)} records"
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
    version="2.0.0",
    lifespan=lifespan
)

# Create root app to handle both direct access and tunneled access
app = FastAPI(title="Fingerprint Logger Root")

# CORS configuration for fingerprint_app
fingerprint_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
fingerprint_app.mount("/static", StaticFiles(directory="static"), name="static")

# Include Consolidated API routers - Phase 4 Simplification
fingerprint_app.include_router(consolidated_attendance.router, prefix="/api/attendance", tags=["attendance"])
fingerprint_app.include_router(consolidated_devices.router, prefix="/api/devices", tags=["devices"])
fingerprint_app.include_router(consolidated_employees.router, prefix="/api/employees", tags=["employees"])
fingerprint_app.include_router(consolidated_export.router, prefix="/api/export", tags=["export"])

# System Status API - New comprehensive status monitoring
from app.api import system_status
fingerprint_app.include_router(system_status.router, prefix="/api/system", tags=["system-status"])


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

# Serve HTML pages
@fingerprint_app.get("/")
async def serve_dashboard():
    return FileResponse("static/dashboard.html")

@fingerprint_app.get("/device-status")
async def serve_device_status():
    return FileResponse("static/device-status.html")

@fingerprint_app.get("/export")
async def serve_export():
    return FileResponse("static/export.html")

@fingerprint_app.get("/nickname-management")
async def serve_nickname_management():
    return FileResponse("static/nickname-management.html")

@fingerprint_app.get("/status")
async def serve_status():
    return FileResponse("static/status.html")

@fingerprint_app.get("/docs")
async def serve_api_docs():
    return FileResponse("static/swagger.html")

@fingerprint_app.get("/docs/openapi.yaml")
async def serve_openapi_spec():
    return FileResponse("docs/openapi.yaml")

@fingerprint_app.get("/health")
async def health_check():
    return {"status": "healthy", "server": "unified"}

@fingerprint_app.get("/api/auto-import/status")
async def get_auto_import_status():
    """Get auto-import background task status"""
    global background_task
    
    auto_import_interval = int(os.getenv('AUTO_IMPORT_INTERVAL_MINUTES', '30'))
    
    return {
        "enabled": background_task is not None and not background_task.done(),
        "interval_minutes": auto_import_interval,
        "task_status": "running" if background_task and not background_task.done() else "stopped",
        "next_import_estimate": f"Within {auto_import_interval} minutes"
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
                    "message": f"Manual import: {result.get('synced', 0)} records synced"
                })
            except Exception as broadcast_error:
                logger.warning(f"Failed to broadcast manual import update: {broadcast_error}")
        
        return result
    except Exception as e:
        logger.error(f"Manual import failed: {e}")
        return {
            "success": False,
            "message": f"Manual import failed: {str(e)}"
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
            "message": f"Refresh failed: {str(e)}"
        }

# Mount the fingerprint app for tunnel support
app.mount("/fingerprintlogs", fingerprint_app, name="fingerprint_tunnel")

# Add a root redirect for direct access
@app.get("/")
async def root_redirect():
    return {"message": "Fingerprint Time Logger", "dashboard": "/fingerprintlogs/"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)