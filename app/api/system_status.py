"""
System Status API - Comprehensive system health and operational logs
Replaces floating connection status with dedicated status endpoint
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text
import os
import logging

from app.core.database import get_db
from app.models.models import Employee, AttendanceRecord, Device, ApplicationLog
from app.services.device_service import device_service
from app.services.logging_service import app_logger

router = APIRouter()

# Configure logging for status tracking
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@router.get("/health")
async def get_system_health(db: Session = Depends(get_db)):
    """
    Get comprehensive system health status
    """
    try:
        # Device Health with caching
        from app.services.device_service_cached import cached_device_service
        device_health = cached_device_service.get_device_status()
        
        # Database Health
        db_health = await get_database_health(db)
        
        # System Resources
        system_resources = get_system_resources()
        
        # Application Statistics
        app_stats = await get_application_statistics(db)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "healthy" if device_health.get("connected") and db_health["accessible"] else "degraded",
            "device_health": device_health,
            "database_health": db_health,
            "system_resources": system_resources,
            "application_stats": app_stats
        }
        
    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_status": "error",
            "error": str(e)
        }


@router.get("/logs")
async def get_system_logs(
    level: Optional[str] = Query(None, description="Filter by log level: INFO, WARNING, ERROR, DEBUG"),
    category: Optional[str] = Query(None, description="Filter by category: sync, connection, api, system, employee, error"),
    limit: int = Query(100, ge=1, le=1000),
    hours_back: int = Query(24, ge=1, le=168),  # Max 1 week
    search: Optional[str] = Query(None, description="Search in messages"),
    success_only: Optional[bool] = Query(None, description="Filter by success status")
):
    """
    Get comprehensive application logs with advanced filtering
    """
    try:
        # Get logs from database using new logging service
        logs = app_logger.get_logs(
            level=level,
            category=category,
            hours_back=hours_back,
            limit=limit,
            search=search,
            success_only=success_only
        )

        # Get summary statistics
        summary = app_logger.get_log_summary(hours_back=hours_back)

        return {
            "logs": logs,
            "total_returned": len(logs),
            "summary": summary,
            "filters": {
                "level": level,
                "category": category,
                "hours_back": hours_back,
                "search": search,
                "success_only": success_only
            },
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error retrieving logs: {e}")
        return {"error": str(e), "logs": [], "summary": {}}


@router.get("/logs/summary")
async def get_log_summary(
    hours_back: int = Query(24, ge=1, le=168)
):
    """
    Get log summary and statistics
    """
    try:
        summary = app_logger.get_log_summary(hours_back=hours_back)
        return summary
    except Exception as e:
        logger.error(f"Error getting log summary: {e}")
        return {"error": str(e)}


@router.post("/logs/cleanup")
async def cleanup_old_logs(
    days_to_keep: int = Query(30, ge=7, le=365, description="Number of days to keep logs")
):
    """
    Clean up old application logs
    """
    try:
        deleted_count = app_logger.cleanup_old_logs(days_to_keep=days_to_keep)
        return {
            "success": True,
            "deleted_count": deleted_count,
            "days_kept": days_to_keep,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error cleaning up logs: {e}")
        return {"error": str(e), "success": False}


@router.get("/metrics")
async def get_performance_metrics(db: Session = Depends(get_db)):
    """
    Get application performance metrics
    """
    try:
        # Database performance
        db_metrics = await get_database_metrics(db)
        
        # API performance (basic timing)
        api_start = datetime.now()
        test_query = db.execute(text("SELECT 1")).scalar()
        api_response_time = (datetime.now() - api_start).total_seconds() * 1000
        
        # Recent activity metrics
        activity_metrics = await get_activity_metrics(db)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "database_metrics": db_metrics,
            "api_performance": {
                "db_query_time_ms": round(api_response_time, 2),
                "status": "healthy" if api_response_time < 100 else "slow"
            },
            "activity_metrics": activity_metrics
        }
        
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        return {"error": str(e)}


async def get_database_health(db: Session) -> Dict[str, Any]:
    """Check database connectivity and basic health"""
    try:
        # Test basic connectivity
        result = db.execute(text("SELECT 1")).scalar()
        
        # Get table counts
        employee_count = db.query(Employee).count()
        attendance_count = db.query(AttendanceRecord).count()
        device_count = db.query(Device).count()
        
        return {
            "accessible": True,
            "total_employees": employee_count,
            "total_attendance_records": attendance_count,
            "total_devices": device_count,
            "last_checked": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {
            "accessible": False,
            "error": str(e),
            "last_checked": datetime.now().isoformat()
        }


def get_system_resources() -> Dict[str, Any]:
    """Get basic system information without psutil dependency"""
    try:
        # Basic system info using os module
        import shutil
        
        # Get disk usage
        disk_usage = shutil.disk_usage('/')
        disk_total = disk_usage.total
        disk_free = disk_usage.free
        disk_used = disk_total - disk_free
        disk_percent = (disk_used / disk_total) * 100
        
        return {
            "disk_usage_percent": round(disk_percent, 1),
            "disk_free_gb": round(disk_free / (1024**3), 2),
            "disk_total_gb": round(disk_total / (1024**3), 2),
            "timestamp": datetime.now().isoformat(),
            "note": "Basic system monitoring (install psutil for advanced metrics)"
        }
        
    except Exception as e:
        logger.warning(f"Could not get system resources: {e}")
        return {"error": "System resource monitoring unavailable"}


async def get_application_statistics(db: Session) -> Dict[str, Any]:
    """Get application-specific statistics"""
    try:
        # Employee statistics
        active_employees = db.query(Employee).filter(Employee.is_active == True).count()
        total_employees = db.query(Employee).count()
        
        # Recent attendance activity
        today = datetime.now().date()
        today_records = db.query(AttendanceRecord).filter(
            func.date(AttendanceRecord.timestamp) == today
        ).count()
        
        # Last sync info
        last_attendance = db.query(AttendanceRecord).order_by(
            desc(AttendanceRecord.timestamp)
        ).first()
        
        return {
            "employees": {
                "total": total_employees,
                "active": active_employees,
                "inactive": total_employees - active_employees
            },
            "attendance": {
                "today_records": today_records,
                "last_record_time": last_attendance.timestamp.isoformat() if last_attendance else None
            },
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting app statistics: {e}")
        return {"error": str(e)}


async def get_database_metrics(db: Session) -> Dict[str, Any]:
    """Get database performance metrics"""
    try:
        # Table sizes and basic metrics
        employee_count = db.query(Employee).count()
        attendance_count = db.query(AttendanceRecord).count()
        
        # Recent activity
        last_hour = datetime.now() - timedelta(hours=1)
        recent_attendance = db.query(AttendanceRecord).filter(
            AttendanceRecord.timestamp >= last_hour
        ).count()
        
        return {
            "table_sizes": {
                "employees": employee_count,
                "attendance_records": attendance_count
            },
            "recent_activity": {
                "attendance_last_hour": recent_attendance
            }
        }
        
    except Exception as e:
        return {"error": str(e)}


async def get_activity_metrics(db: Session) -> Dict[str, Any]:
    """Get recent system activity metrics"""
    try:
        # Activity in last 24 hours
        last_24h = datetime.now() - timedelta(hours=24)
        
        recent_attendance = db.query(AttendanceRecord).filter(
            AttendanceRecord.timestamp >= last_24h
        ).count()
        
        # Employee management activity (rough estimate)
        recent_employee_updates = db.query(Employee).filter(
            Employee.updated_at >= last_24h
        ).count() if hasattr(Employee, 'updated_at') else 0
        
        return {
            "last_24_hours": {
                "attendance_records": recent_attendance,
                "employee_updates": recent_employee_updates
            },
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {"error": str(e)}


def parse_log_line(line: str, log_type: Optional[str], time_cutoff: datetime) -> Optional[Dict[str, Any]]:
    """Parse a log line and extract relevant information"""
    try:
        if not line.strip():
            return None
            
        # Basic log parsing - can be enhanced based on log format
        parts = line.split(' - ', 2)
        if len(parts) < 2:
            return None
            
        # Extract log level and message
        log_level = "INFO"
        if "ERROR" in line:
            log_level = "ERROR"
        elif "WARNING" in line:
            log_level = "WARNING"
        elif "DEBUG" in line:
            log_level = "DEBUG"
            
        # Categorize log types
        category = "general"
        if "device_service" in line or "Connected to device" in line:
            category = "connection"
        elif "sync" in line.lower() or "import" in line.lower():
            category = "sync"
        elif "ERROR" in line or "Failed" in line:
            category = "error"
        elif "GET" in line or "POST" in line or "PUT" in line:
            category = "api"
            
        # Filter by log type if specified
        if log_type and log_type != "all" and category != log_type:
            return None
            
        return {
            "timestamp": datetime.now().isoformat(),  # Simplified - could parse actual timestamp
            "level": log_level,
            "category": category,
            "message": line.strip(),
            "source": "unified_server"
        }
        
    except Exception:
        return None