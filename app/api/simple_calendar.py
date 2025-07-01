"""
Simple Calendar API endpoints - Basic version for testing
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter(prefix="/attendance/calendar", tags=["Simple Calendar"])


@router.get("/health")
async def calendar_health_check():
    """Health check for calendar service"""
    return {
        "status": "healthy",
        "service": "simple_calendar",
        "message": "Calendar API is working"
    }


@router.get("/{year}/{month}")
async def get_simple_calendar(
    year: int,
    month: int,
    db: Session = Depends(get_db)
):
    """Get basic calendar data"""
    return {
        "year": year,
        "month": month,
        "message": "Calendar endpoint is working",
        "status": "basic_implementation"
    }