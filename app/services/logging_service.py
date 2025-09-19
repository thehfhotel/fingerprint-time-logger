"""
Application Logging Service - Comprehensive activity and error tracking
Replaces basic logging with structured database logging for system monitoring
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, or_

from app.core.database import get_db
from app.models.models import ApplicationLog


class ApplicationLoggingService:
    """Comprehensive application logging service with database storage"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def log_action(self,
                   level: str,
                   category: str,
                   action: str,
                   message: str,
                   details: Optional[Dict[str, Any]] = None,
                   employee_badge: Optional[str] = None,
                   device_id: Optional[int] = None,
                   duration_ms: Optional[int] = None,
                   success: Optional[bool] = None,
                   user_agent: Optional[str] = None,
                   ip_address: Optional[str] = None) -> None:
        """Log an application action to database"""
        try:
            db = next(get_db())
            try:
                log_entry = ApplicationLog(
                    level=level.upper(),
                    category=category,
                    action=action,
                    message=message,
                    details=details,
                    employee_badge=employee_badge,
                    device_id=device_id,
                    duration_ms=duration_ms,
                    success=success,
                    user_agent=user_agent,
                    ip_address=ip_address
                )
                db.add(log_entry)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            # Fallback to standard logging if database logging fails
            self.logger.error(f"Failed to log to database: {e}")
            self.logger.log(getattr(logging, level.upper(), logging.INFO), f"{category}.{action}: {message}")

    def log_sync_start(self, device_id: int, sync_type: str = "partial") -> None:
        """Log sync operation start"""
        self.log_action(
            level="INFO",
            category="sync",
            action="sync_started",
            message=f"Started {sync_type} sync for device {device_id}",
            device_id=device_id,
            details={"sync_type": sync_type}
        )

    def log_sync_completed(self, device_id: int, synced_count: int, total_processed: int,
                          sync_type: str = "partial", duration_ms: Optional[int] = None) -> None:
        """Log successful sync completion"""
        self.log_action(
            level="INFO",
            category="sync",
            action="sync_completed",
            message=f"Sync completed: {synced_count} new records from {total_processed} processed ({sync_type})",
            device_id=device_id,
            duration_ms=duration_ms,
            success=True,
            details={
                "synced_count": synced_count,
                "total_processed": total_processed,
                "sync_type": sync_type
            }
        )

    def log_sync_failed(self, device_id: Optional[int], error: str, sync_type: str = "partial") -> None:
        """Log sync operation failure"""
        self.log_action(
            level="ERROR",
            category="sync",
            action="sync_failed",
            message=f"Sync failed: {error}",
            device_id=device_id,
            success=False,
            details={"error": error, "sync_type": sync_type}
        )

    def log_device_connection(self, device_id: int, device_name: str, ip_address: str, success: bool,
                             error: Optional[str] = None) -> None:
        """Log device connection attempt"""
        level = "INFO" if success else "WARNING"
        action = "device_connected" if success else "device_connection_failed"
        message = f"Device {device_name} ({ip_address}) {'connected' if success else 'connection failed'}"
        if error:
            message += f": {error}"

        self.log_action(
            level=level,
            category="connection",
            action=action,
            message=message,
            device_id=device_id,
            success=success,
            details={"device_name": device_name, "ip_address": ip_address, "error": error}
        )

    def log_api_request(self, method: str, endpoint: str, status_code: int, duration_ms: int,
                       user_agent: Optional[str] = None, ip_address: Optional[str] = None,
                       employee_badge: Optional[str] = None, error: Optional[str] = None) -> None:
        """Log API request"""
        level = "INFO" if status_code < 400 else "WARNING" if status_code < 500 else "ERROR"
        success = status_code < 400

        self.log_action(
            level=level,
            category="api",
            action=f"api_request_{method.lower()}",
            message=f"{method} {endpoint} - {status_code}",
            duration_ms=duration_ms,
            success=success,
            user_agent=user_agent,
            ip_address=ip_address,
            employee_badge=employee_badge,
            details={
                "method": method,
                "endpoint": endpoint,
                "status_code": status_code,
                "error": error
            }
        )

    def log_system_event(self, event: str, message: str, level: str = "INFO",
                        details: Optional[Dict[str, Any]] = None, success: Optional[bool] = None) -> None:
        """Log general system events"""
        self.log_action(
            level=level,
            category="system",
            action=event,
            message=message,
            details=details,
            success=success
        )

    def log_employee_action(self, action: str, employee_badge: str, message: str,
                           details: Optional[Dict[str, Any]] = None, success: bool = True) -> None:
        """Log employee-related actions"""
        self.log_action(
            level="INFO",
            category="employee",
            action=action,
            message=message,
            employee_badge=employee_badge,
            details=details,
            success=success
        )

    def get_logs(self,
                 level: Optional[str] = None,
                 category: Optional[str] = None,
                 hours_back: int = 24,
                 limit: int = 100,
                 search: Optional[str] = None,
                 success_only: Optional[bool] = None) -> List[Dict[str, Any]]:
        """Retrieve logs with filtering"""
        try:
            db = next(get_db())
            try:
                query = db.query(ApplicationLog)

                # Time filter
                if hours_back > 0:
                    time_cutoff = datetime.now() - timedelta(hours=hours_back)
                    query = query.filter(ApplicationLog.timestamp >= time_cutoff)

                # Level filter
                if level:
                    query = query.filter(ApplicationLog.level == level.upper())

                # Category filter
                if category:
                    query = query.filter(ApplicationLog.category == category)

                # Success filter
                if success_only is not None:
                    query = query.filter(ApplicationLog.success == success_only)

                # Search filter
                if search:
                    search_term = f"%{search}%"
                    query = query.filter(
                        or_(
                            ApplicationLog.message.ilike(search_term),
                            ApplicationLog.action.ilike(search_term)
                        )
                    )

                # Order by timestamp (newest first) and limit
                logs = query.order_by(desc(ApplicationLog.timestamp)).limit(limit).all()

                # Convert to dictionary format
                result = []
                for log in logs:
                    result.append({
                        "id": log.id,
                        "timestamp": log.timestamp.isoformat(),
                        "level": log.level,
                        "category": log.category,
                        "action": log.action,
                        "message": log.message,
                        "details": log.details,
                        "employee_badge": log.employee_badge,
                        "device_id": log.device_id,
                        "duration_ms": log.duration_ms,
                        "success": log.success,
                        "user_agent": log.user_agent,
                        "ip_address": log.ip_address
                    })

                return result

            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Failed to retrieve logs: {e}")
            return []

    def get_log_summary(self, hours_back: int = 24) -> Dict[str, Any]:
        """Get log statistics summary"""
        try:
            db = next(get_db())
            try:
                time_cutoff = datetime.now() - timedelta(hours=hours_back)

                # Count by level
                level_counts = {}
                for level in ["INFO", "WARNING", "ERROR", "DEBUG"]:
                    count = db.query(ApplicationLog).filter(
                        and_(
                            ApplicationLog.timestamp >= time_cutoff,
                            ApplicationLog.level == level
                        )
                    ).count()
                    level_counts[level.lower()] = count

                # Count by category
                category_counts = {}
                for category in ["sync", "connection", "api", "system", "employee", "error"]:
                    count = db.query(ApplicationLog).filter(
                        and_(
                            ApplicationLog.timestamp >= time_cutoff,
                            ApplicationLog.category == category
                        )
                    ).count()
                    category_counts[category] = count

                # Recent activity
                total_logs = sum(level_counts.values())
                recent_errors = level_counts.get("error", 0)
                recent_warnings = level_counts.get("warning", 0)

                return {
                    "total_logs": total_logs,
                    "hours_back": hours_back,
                    "level_counts": level_counts,
                    "category_counts": category_counts,
                    "recent_errors": recent_errors,
                    "recent_warnings": recent_warnings,
                    "health_status": "good" if recent_errors == 0 else "warning" if recent_errors < 5 else "critical"
                }

            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Failed to get log summary: {e}")
            return {"error": str(e)}

    def cleanup_old_logs(self, days_to_keep: int = 30) -> int:
        """Clean up old logs to prevent database bloat"""
        try:
            db = next(get_db())
            try:
                cutoff_date = datetime.now() - timedelta(days=days_to_keep)

                # Count logs to be deleted
                count = db.query(ApplicationLog).filter(
                    ApplicationLog.timestamp < cutoff_date
                ).count()

                # Delete old logs
                db.query(ApplicationLog).filter(
                    ApplicationLog.timestamp < cutoff_date
                ).delete()

                db.commit()

                if count > 0:
                    self.log_system_event(
                        "log_cleanup",
                        f"Cleaned up {count} old log entries (older than {days_to_keep} days)",
                        details={"deleted_count": count, "days_to_keep": days_to_keep}
                    )

                return count

            finally:
                db.close()

        except Exception as e:
            self.logger.error(f"Failed to cleanup old logs: {e}")
            return 0


# Global service instance
app_logger = ApplicationLoggingService()