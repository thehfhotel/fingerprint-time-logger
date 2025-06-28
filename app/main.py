from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.core.config import settings
from app.core.database import engine, Base
from app.api import attendance, devices, employees, sync

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


@app.get("/")
async def root():
    return {"message": "Fingerprint Time Logger API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}