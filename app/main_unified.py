from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import logging
import asyncio
from typing import List
import json
from datetime import datetime

from app.core.config import settings
from app.core.database import engine, Base
from app.api import (
    consolidated_attendance, consolidated_devices, consolidated_employees, 
    consolidated_export
)
# Legacy APIs for backward compatibility 
from app.api import (
    attendance, devices, employees, sync, diagnostics, 
    control, unlimited_sync, 
    roles, time_check, employees_unified
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up unified server...")
    Base.metadata.create_all(bind=engine)
    
    # Start background sync service
    asyncio.create_task(background_sync_loop())
    
    yield
    
    logger.info("Shutting down unified server...")

async def background_sync_loop():
    """Background loop for device synchronization"""
    while True:
        try:
            # For now, just sleep - we'll implement device sync later
            # This prevents the server from doing real device operations during testing
            await asyncio.sleep(120)  # 2 minutes
            
        except Exception as e:
            logger.error(f"Background sync error: {e}")
            await asyncio.sleep(60)  # Retry after 1 minute on error

app = FastAPI(
    title="Fingerprint Time Logger - Unified",
    description="Unified API and Dashboard for ZKTeco fingerprint attendance tracking",
    version="2.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include Consolidated API routers - Phase 4 Simplification
app.include_router(consolidated_attendance.router, prefix="/api/attendance", tags=["attendance"])
app.include_router(consolidated_devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(consolidated_employees.router, prefix="/api/employees", tags=["employees"])
app.include_router(consolidated_export.router, prefix="/api/export", tags=["export"])

# System Status API - New comprehensive status monitoring
from app.api import system_status
app.include_router(system_status.router, prefix="/api/system", tags=["system-status"])

# Legacy API routers for backward compatibility (Phase 4 cleanup will remove these)
app.include_router(attendance.router, prefix="/api/legacy/attendance", tags=["legacy-attendance"])
app.include_router(devices.router, prefix="/api/legacy/devices", tags=["legacy-devices"])
app.include_router(employees_unified.router, prefix="/api/legacy/employees-unified", tags=["legacy-employees-unified"])
app.include_router(employees.router, prefix="/api/legacy/employees", tags=["legacy-employees"])
app.include_router(sync.router, prefix="/api/legacy/sync", tags=["legacy-sync"])
app.include_router(diagnostics.router, prefix="/api/legacy/diagnostics", tags=["legacy-diagnostics"])
app.include_router(control.router, prefix="/api/legacy/control", tags=["legacy-control"])
app.include_router(unlimited_sync.router, prefix="/api/legacy/unlimited-sync", tags=["legacy-unlimited-sync"])
app.include_router(roles.router, prefix="/api/legacy/roles", tags=["legacy-roles"])
app.include_router(time_check.router, prefix="/api/legacy/time-check", tags=["legacy-time-check"])

# WebSocket endpoint for real-time updates
@app.websocket("/ws")
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
@app.get("/")
async def serve_dashboard():
    return FileResponse("static/dashboard.html")



@app.get("/device-status")
async def serve_device_status():
    return FileResponse("static/device-status.html")

@app.get("/export")
async def serve_export():
    return FileResponse("static/export.html")

@app.get("/status")
async def serve_status():
    return FileResponse("static/status.html")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "server": "unified"}

# Legacy API endpoint for manual refresh (from dashboard)
@app.post("/api/refresh")
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)