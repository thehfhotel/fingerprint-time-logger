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
    attendance, devices, employees, sync, thai_names, diagnostics, 
    control, work_schedules, employee_schedules, unlimited_sync, 
    roles, time_check, calendar_api, employees_unified
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

# Include API routers
app.include_router(attendance.router, prefix="/api/attendance", tags=["attendance"])
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(employees_unified.router, prefix="/api/employees-unified", tags=["employees-unified"])
app.include_router(employees.router, prefix="/api/employees-legacy", tags=["employees-legacy"])
app.include_router(thai_names.router, prefix="/api/thai-names", tags=["thai-names"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(diagnostics.router, prefix="/api/diagnostics", tags=["diagnostics"])
app.include_router(control.router, prefix="/api/control", tags=["control"])
app.include_router(work_schedules.router, prefix="/api/work-schedules", tags=["work-schedules"])
app.include_router(employee_schedules.router, prefix="/api/employee-schedules", tags=["employee-schedules"])
app.include_router(unlimited_sync.router, prefix="/api/unlimited-sync", tags=["unlimited-sync"])
app.include_router(roles.router, prefix="/api/roles", tags=["roles"])
app.include_router(time_check.router, prefix="/api/time-check", tags=["time-check"])
app.include_router(calendar_api.router, prefix="/api/calendar", tags=["calendar"])

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

@app.get("/thai-names")
async def serve_thai_names():
    return FileResponse("static/thai_names.html")

@app.get("/work-schedules")
async def serve_work_schedules():
    return FileResponse("static/work_schedules.html")

@app.get("/attendance-calendar")
async def serve_attendance_calendar():
    return FileResponse("static/attendance_calendar.html")

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