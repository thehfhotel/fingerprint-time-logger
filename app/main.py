from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.core.database import engine, Base
from app.api import attendance, devices, employees, sync, thai_names, diagnostics, control, work_schedules, employee_schedules, unlimited_sync, roles, time_check, calendar_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Fingerprint Time Logger",
    description="API for ZKTeco fingerprint attendance tracking",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(attendance.router, prefix="/api/attendance", tags=["attendance"])
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(employees.router, prefix="/api/employees", tags=["employees"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(thai_names.router, tags=["thai-names"])
app.include_router(diagnostics.router, prefix="/api/diagnostics", tags=["diagnostics"])
app.include_router(control.router, prefix="/api/control", tags=["control"])
app.include_router(work_schedules.router, prefix="/api/work-schedules", tags=["work-schedules"])
app.include_router(employee_schedules.router, prefix="/api/employee-schedules", tags=["employee-schedules"])
app.include_router(unlimited_sync.router, prefix="/api/unlimited-sync", tags=["unlimited-sync"])
app.include_router(roles.router, tags=["roles"])
app.include_router(time_check.router, tags=["time-check"])
app.include_router(calendar_api.router, prefix="/api", tags=["calendar-api"])


@app.get("/")
async def root():
    return {"message": "Fingerprint Time Logger API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Direct calendar endpoints for testing
@app.get("/api/attendance/calendar/config")
async def get_calendar_config_direct():
    """Direct calendar config endpoint"""
    return {
        "status": "working",
        "message": "Direct calendar config endpoint",
        "violation_threshold_minutes": 15,
        "status_colors": {
            "perfect": "#22c55e",
            "minor_issue": "#eab308", 
            "violation": "#ef4444",
            "absent": "#9ca3af",
            "non_working": "#3b82f6"
        }
    }


@app.get("/api/attendance/calendar/{year}/{month}")
async def get_calendar_data_direct(year: int, month: int):
    """Direct calendar data endpoint"""
    return {
        "status": "working",
        "message": "Direct calendar data endpoint",
        "year": year,
        "month": month,
        "employees": [],
        "holidays": [],
        "weekends": []
    }