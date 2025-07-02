"""
Diagnostic and Monitoring API for Offline-First Architecture

This module provides comprehensive diagnostic endpoints for monitoring
the health and performance of the offline-first fingerprint time logger system.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.core.database import get_db
from app.models.models import Device, AttendanceRecord, SyncQueue, DeviceStatusLog, DataCache
from app.services.cache_service import CacheService
from app.services.sync_queue_manager import SyncQueueManager
from app.services.connection_manager import DeviceConnectionManager, CircuitBreakerConfig
from app.services.background_sync_service import get_sync_service

router = APIRouter()


@router.get("/system", response_model=Dict[str, Any])
async def get_system_diagnostics(
    include_performance: bool = Query(True, description="Include performance metrics"),
    include_detailed_stats: bool = Query(False, description="Include detailed statistics"),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive system diagnostics
    """
    cache_service = CacheService(db)
    sync_manager = SyncQueueManager(db)
    sync_service = get_sync_service()
    
    # Basic system info
    diagnostics = {
        "timestamp": datetime.now().isoformat(),
        "system_status": {
            "database_connected": True,  # If we're here, DB is connected
            "background_service": sync_service.get_status(),
            "queue_health": sync_manager.get_queue_statistics(),
            "cache_health": cache_service.get_cache_status()
        }
    }
    
    # Device status summary
    devices = db.query(Device).all()
    device_summary = {
        "total_devices": len(devices),
        "active_devices": len([d for d in devices if d.is_active]),
        "devices_with_recent_sync": 0,
        "devices_with_errors": 0
    }
    
    # Check recent sync status for each device
    for device in devices:
        if device.last_sync and device.last_sync > datetime.now() - timedelta(hours=24):
            device_summary["devices_with_recent_sync"] += 1
        
        # Check for recent errors
        recent_errors = db.query(DeviceStatusLog).filter(
            DeviceStatusLog.device_id == device.id,
            DeviceStatusLog.status.in_(["error", "offline"]),
            DeviceStatusLog.created_at > datetime.now() - timedelta(hours=24)
        ).count()
        
        if recent_errors > 0:
            device_summary["devices_with_errors"] += 1
    
    diagnostics["device_summary"] = device_summary
    
    # Data statistics
    data_stats = {
        "total_attendance_records": db.query(AttendanceRecord).count(),
        "records_today": db.query(AttendanceRecord).filter(
            AttendanceRecord.timestamp >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        ).count(),
        "pending_sync_records": db.query(AttendanceRecord).filter(
            AttendanceRecord.sync_status == "pending"
        ).count(),
        "failed_sync_records": db.query(AttendanceRecord).filter(
            AttendanceRecord.sync_status == "failed"
        ).count()
    }
    
    diagnostics["data_statistics"] = data_stats
    
    if include_performance:
        # Performance metrics
        performance = _calculate_performance_metrics(db, sync_service, sync_manager)
        diagnostics["performance_metrics"] = performance
    
    if include_detailed_stats:
        # Detailed statistics
        detailed = _get_detailed_statistics(db)
        diagnostics["detailed_statistics"] = detailed
    
    # Health recommendations
    diagnostics["recommendations"] = _generate_system_recommendations(diagnostics)
    
    return diagnostics


@router.get("/devices/{device_id}", response_model=Dict[str, Any])
async def get_device_diagnostics(
    device_id: int,
    hours_back: int = Query(24, ge=1, le=168, description="Hours of history to include"),
    db: Session = Depends(get_db)
):
    """
    Get detailed diagnostics for a specific device
    """
    # Verify device exists
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    connection_manager = DeviceConnectionManager(db, CircuitBreakerConfig())
    cache_service = CacheService(db)
    sync_manager = SyncQueueManager(db)
    
    cutoff_time = datetime.now() - timedelta(hours=hours_back)
    
    # Device basic info
    device_info = {
        "device_id": device_id,
        "device_name": device.name,
        "ip_address": device.ip_address,
        "port": device.port,
        "is_active": device.is_active,
        "last_sync": device.last_sync.isoformat() if device.last_sync else None
    }
    
    # Connection status and health
    try:
        health_data = await connection_manager.health_check(device_id)
        connection_status = connection_manager.get_connection_status(device_id)
    except Exception as e:
        health_data = {"healthy": False, "error": str(e)}
        connection_status = {"connected": False, "error": str(e)}
    
    # Sync operations history
    operations = sync_manager.get_operations_by_device(device_id, limit=50)
    recent_operations = [op for op in operations if op.get("created_at") and 
                        datetime.fromisoformat(op["created_at"]) > cutoff_time]
    
    # Device status logs
    status_logs = db.query(DeviceStatusLog).filter(
        DeviceStatusLog.device_id == device_id,
        DeviceStatusLog.created_at > cutoff_time
    ).order_by(desc(DeviceStatusLog.created_at)).limit(100).all()
    
    status_history = [
        {
            "status": log.status,
            "timestamp": log.created_at.isoformat(),
            "error_message": log.error_message,
            "last_successful_sync": log.last_successful_sync.isoformat() if log.last_successful_sync else None
        }
        for log in status_logs
    ]
    
    # Attendance data statistics
    attendance_stats = {
        "total_records": db.query(AttendanceRecord).filter(
            AttendanceRecord.device_id == device_id
        ).count(),
        "records_last_24h": db.query(AttendanceRecord).filter(
            AttendanceRecord.device_id == device_id,
            AttendanceRecord.timestamp > datetime.now() - timedelta(hours=24)
        ).count(),
        "pending_sync": db.query(AttendanceRecord).filter(
            AttendanceRecord.device_id == device_id,
            AttendanceRecord.sync_status == "pending"
        ).count(),
        "failed_sync": db.query(AttendanceRecord).filter(
            AttendanceRecord.device_id == device_id,
            AttendanceRecord.sync_status == "failed"
        ).count()
    }
    
    # Cache status for this device
    cached_data = cache_service.get_cached_attendance_data(device_id)
    cache_status = {
        "has_cached_data": cached_data is not None,
        "cached_record_count": cached_data.get("record_count", 0) if cached_data else 0,
        "cache_age_hours": 0
    }
    
    if cached_data:
        cached_time = datetime.fromisoformat(cached_data["cached_at"])
        cache_status["cache_age_hours"] = (datetime.now() - cached_time).total_seconds() / 3600
    
    # Calculate uptime and reliability
    online_logs = [log for log in status_logs if log.status in ["online", "connected"]]
    uptime_percentage = (len(online_logs) / max(len(status_logs), 1)) * 100
    
    operation_success_rate = 0
    if recent_operations:
        successful_ops = len([op for op in recent_operations if op.get("status") == "completed"])
        operation_success_rate = (successful_ops / len(recent_operations)) * 100
    
    return {
        "device_info": device_info,
        "health_check": health_data,
        "connection_status": connection_status,
        "reliability_metrics": {
            "uptime_percentage": round(uptime_percentage, 2),
            "operation_success_rate": round(operation_success_rate, 2),
            "total_operations": len(recent_operations),
            "successful_operations": len([op for op in recent_operations if op.get("status") == "completed"]),
            "failed_operations": len([op for op in recent_operations if op.get("status") == "failed"])
        },
        "attendance_statistics": attendance_stats,
        "cache_status": cache_status,
        "recent_operations": recent_operations,
        "status_history": status_history,
        "analysis_period_hours": hours_back,
        "recommendations": _generate_device_recommendations(
            health_data, connection_status, attendance_stats, operation_success_rate
        )
    }


@router.get("/performance", response_model=Dict[str, Any])
async def get_performance_metrics(
    time_window_hours: int = Query(24, ge=1, le=168),
    include_trends: bool = Query(True, description="Include trend analysis"),
    db: Session = Depends(get_db)
):
    """
    Get detailed performance metrics for the system
    """
    sync_service = get_sync_service()
    sync_manager = SyncQueueManager(db)
    cache_service = CacheService(db)
    
    cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
    
    # Service performance
    service_status = sync_service.get_status()
    service_metrics = service_status.get("metrics", {})
    
    # Queue performance
    queue_stats = sync_manager.get_queue_statistics()
    
    # Database performance (simplified)
    db_performance = {
        "total_queries_estimated": queue_stats.get("pending_count", 0) + queue_stats.get("completed_count", 0),
        "avg_response_time_ms": service_metrics.get("avg_operation_time", 0) * 1000,
        "cache_hit_ratio": _calculate_cache_hit_ratio(cache_service)
    }
    
    # Sync operation throughput
    completed_operations = queue_stats.get("completed_count", 0)
    uptime_hours = service_metrics.get("uptime_seconds", 1) / 3600
    throughput = completed_operations / max(uptime_hours, 0.01)  # operations per hour
    
    performance_summary = {
        "measurement_period_hours": time_window_hours,
        "timestamp": datetime.now().isoformat(),
        "service_performance": {
            "uptime_hours": round(uptime_hours, 2),
            "operations_processed": service_metrics.get("operations_processed", 0),
            "operations_per_hour": round(throughput, 2),
            "success_rate_percent": _calculate_success_rate(queue_stats),
            "avg_operation_time_ms": round(service_metrics.get("avg_operation_time", 0) * 1000, 2)
        },
        "queue_performance": {
            "current_backlog": queue_stats.get("pending_count", 0),
            "processing_rate": round(throughput, 2),
            "failure_rate_percent": _calculate_failure_rate(queue_stats),
            "retry_success_rate": _calculate_retry_success_rate(queue_stats)
        },
        "database_performance": db_performance,
        "cache_performance": {
            "cache_entries": cache_service.get_cache_status().get("active_entries", 0),
            "cache_size_mb": round(cache_service.get_cache_status().get("estimated_size_bytes", 0) / 1024 / 1024, 2),
            "hit_ratio_percent": db_performance["cache_hit_ratio"]
        }
    }
    
    if include_trends:
        # Simple trend analysis (would be more sophisticated in production)
        trends = _analyze_performance_trends(db, time_window_hours)
        performance_summary["trends"] = trends
    
    return performance_summary


@router.get("/alerts", response_model=Dict[str, Any])
async def get_system_alerts(
    severity: Optional[str] = Query(None, regex="^(low|medium|high|critical)$"),
    device_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """
    Get system alerts and warnings
    """
    alerts = []
    current_time = datetime.now()
    
    # Check for critical issues
    cache_service = CacheService(db)
    sync_manager = SyncQueueManager(db)
    
    # Failed operations alert
    queue_stats = sync_manager.get_queue_statistics()
    failed_count = queue_stats.get("failed_count", 0)
    if failed_count > 10:
        alerts.append({
            "id": f"failed_ops_{int(current_time.timestamp())}",
            "severity": "high" if failed_count > 20 else "medium",
            "type": "sync_failures",
            "message": f"{failed_count} sync operations have failed",
            "timestamp": current_time.isoformat(),
            "device_id": None,
            "recommended_action": "Check device connectivity and retry failed operations"
        })
    
    # Large queue backlog alert
    pending_count = queue_stats.get("pending_count", 0)
    if pending_count > 100:
        alerts.append({
            "id": f"queue_backlog_{int(current_time.timestamp())}",
            "severity": "medium" if pending_count < 200 else "high",
            "type": "queue_backlog",
            "message": f"{pending_count} operations pending in sync queue",
            "timestamp": current_time.isoformat(),
            "device_id": None,
            "recommended_action": "Consider increasing sync worker capacity"
        })
    
    # Check device-specific alerts
    devices = db.query(Device).filter(Device.is_active == True).all()
    for device in devices:
        if device_id and device.id != device_id:
            continue
        
        # Device offline alert
        if device.last_sync and device.last_sync < current_time - timedelta(hours=4):
            hours_offline = (current_time - device.last_sync).total_seconds() / 3600
            alerts.append({
                "id": f"device_offline_{device.id}_{int(current_time.timestamp())}",
                "severity": "high" if hours_offline > 12 else "medium",
                "type": "device_offline",
                "message": f"Device '{device.name}' offline for {hours_offline:.1f} hours",
                "timestamp": current_time.isoformat(),
                "device_id": device.id,
                "recommended_action": "Check device network connectivity and power status"
            })
        
        # High failure rate for device
        device_operations = sync_manager.get_operations_by_device(device.id, limit=20)
        if device_operations:
            failed_ops = len([op for op in device_operations if op.get("status") == "failed"])
            failure_rate = (failed_ops / len(device_operations)) * 100
            
            if failure_rate > 50:
                alerts.append({
                    "id": f"device_failures_{device.id}_{int(current_time.timestamp())}",
                    "severity": "high" if failure_rate > 80 else "medium",
                    "type": "device_failures",
                    "message": f"Device '{device.name}' has {failure_rate:.1f}% failure rate",
                    "timestamp": current_time.isoformat(),
                    "device_id": device.id,
                    "recommended_action": "Reset circuit breaker or check device configuration"
                })
    
    # Cache size alert
    cache_status = cache_service.get_cache_status()
    cache_size_mb = cache_status.get("estimated_size_bytes", 0) / 1024 / 1024
    if cache_size_mb > 100:  # Alert if cache > 100MB
        alerts.append({
            "id": f"cache_size_{int(current_time.timestamp())}",
            "severity": "low" if cache_size_mb < 500 else "medium",
            "type": "cache_size",
            "message": f"Cache size is {cache_size_mb:.1f}MB",
            "timestamp": current_time.isoformat(),
            "device_id": None,
            "recommended_action": "Consider running cache cleanup"
        })
    
    # Filter by severity if specified
    if severity:
        alerts = [alert for alert in alerts if alert["severity"] == severity]
    
    # Sort by severity and timestamp (most severe and recent first)
    severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    alerts.sort(key=lambda x: (severity_order.get(x["severity"], 0), x["timestamp"]), reverse=True)
    
    # Limit results
    alerts = alerts[:limit]
    
    return {
        "alerts": alerts,
        "total_count": len(alerts),
        "summary": {
            "critical": len([a for a in alerts if a["severity"] == "critical"]),
            "high": len([a for a in alerts if a["severity"] == "high"]),
            "medium": len([a for a in alerts if a["severity"] == "medium"]),
            "low": len([a for a in alerts if a["severity"] == "low"])
        },
        "filters_applied": {
            "severity": severity,
            "device_id": device_id,
            "limit": limit
        },
        "timestamp": current_time.isoformat()
    }


@router.get("/health-check", response_model=Dict[str, Any])
async def comprehensive_health_check(db: Session = Depends(get_db)):
    """
    Comprehensive system health check
    """
    health_status = {
        "timestamp": datetime.now().isoformat(),
        "overall_status": "healthy",
        "components": {}
    }
    
    issues = []
    
    try:
        # Database health
        db.execute("SELECT 1")
        health_status["components"]["database"] = {"status": "healthy", "message": "Database connection OK"}
    except Exception as e:
        health_status["components"]["database"] = {"status": "unhealthy", "message": f"Database error: {str(e)}"}
        issues.append("database")
    
    try:
        # Sync service health
        sync_service = get_sync_service()
        service_status = sync_service.get_status()
        
        if service_status["state"] == "running":
            health_status["components"]["sync_service"] = {"status": "healthy", "message": "Background sync service running"}
        else:
            health_status["components"]["sync_service"] = {"status": "unhealthy", "message": f"Sync service state: {service_status['state']}"}
            issues.append("sync_service")
    except Exception as e:
        health_status["components"]["sync_service"] = {"status": "unhealthy", "message": f"Sync service error: {str(e)}"}
        issues.append("sync_service")
    
    try:
        # Queue health
        sync_manager = SyncQueueManager(db)
        queue_stats = sync_manager.get_queue_statistics()
        
        failed_count = queue_stats.get("failed_count", 0)
        pending_count = queue_stats.get("pending_count", 0)
        
        if failed_count > 20:
            health_status["components"]["sync_queue"] = {"status": "degraded", "message": f"{failed_count} failed operations"}
            issues.append("sync_queue")
        elif pending_count > 200:
            health_status["components"]["sync_queue"] = {"status": "degraded", "message": f"{pending_count} pending operations"}
            issues.append("sync_queue")
        else:
            health_status["components"]["sync_queue"] = {"status": "healthy", "message": "Sync queue operating normally"}
    except Exception as e:
        health_status["components"]["sync_queue"] = {"status": "unhealthy", "message": f"Queue error: {str(e)}"}
        issues.append("sync_queue")
    
    try:
        # Cache health
        cache_service = CacheService(db)
        cache_status = cache_service.get_cache_status()
        
        if "error" in cache_status:
            health_status["components"]["cache"] = {"status": "unhealthy", "message": cache_status["error"]}
            issues.append("cache")
        else:
            health_status["components"]["cache"] = {"status": "healthy", "message": "Cache system operational"}
    except Exception as e:
        health_status["components"]["cache"] = {"status": "unhealthy", "message": f"Cache error: {str(e)}"}
        issues.append("cache")
    
    # Determine overall status
    if any(comp["status"] == "unhealthy" for comp in health_status["components"].values()):
        health_status["overall_status"] = "unhealthy"
    elif any(comp["status"] == "degraded" for comp in health_status["components"].values()):
        health_status["overall_status"] = "degraded"
    
    health_status["issues"] = issues
    health_status["recommendations"] = _generate_health_recommendations(issues)
    
    return health_status


# Helper functions

def _calculate_performance_metrics(db: Session, sync_service, sync_manager) -> Dict[str, Any]:
    """Calculate system performance metrics"""
    service_status = sync_service.get_status()
    queue_stats = sync_manager.get_queue_statistics()
    
    return {
        "avg_operation_time_ms": round(service_status["metrics"].get("avg_operation_time", 0) * 1000, 2),
        "operations_per_minute": round(service_status["metrics"].get("operations_processed", 0) / max(service_status["metrics"].get("uptime_seconds", 1) / 60, 1), 2),
        "success_rate_percent": _calculate_success_rate(queue_stats),
        "queue_utilization_percent": min(100, (queue_stats.get("pending_count", 0) / max(queue_stats.get("completed_count", 1), 1)) * 100)
    }


def _get_detailed_statistics(db: Session) -> Dict[str, Any]:
    """Get detailed system statistics"""
    return {
        "database_size_estimate": _estimate_database_size(db),
        "oldest_pending_operation": _get_oldest_pending_operation(db),
        "device_distribution": _get_device_statistics(db),
        "sync_patterns": _analyze_sync_patterns(db)
    }


def _calculate_cache_hit_ratio(cache_service: CacheService) -> float:
    """Calculate cache hit ratio (simplified)"""
    # Cache service is simplified, return 0 for actual implementation
    return 0.0


def _calculate_success_rate(queue_stats: Dict) -> float:
    """Calculate operation success rate"""
    completed = queue_stats.get("completed_count", 0)
    failed = queue_stats.get("failed_count", 0)
    total = completed + failed
    
    if total == 0:
        return 100.0
    
    return (completed / total) * 100


def _calculate_failure_rate(queue_stats: Dict) -> float:
    """Calculate operation failure rate"""
    return 100.0 - _calculate_success_rate(queue_stats)


def _calculate_retry_success_rate(queue_stats: Dict) -> float:
    """Calculate retry success rate (simplified)"""
    # Return 0 for simplified implementation without queue tracking
    return 0.0


def _analyze_performance_trends(db: Session, hours: int) -> Dict[str, str]:
    """Analyze performance trends (simplified)"""
    return {
        "operations_trend": "stable",
        "success_rate_trend": "improving",
        "queue_size_trend": "decreasing",
        "cache_usage_trend": "stable"
    }


def _estimate_database_size(db: Session) -> str:
    """Estimate database size"""
    # Simplified estimation
    record_count = db.query(AttendanceRecord).count()
    estimated_mb = (record_count * 0.5) / 1024  # Rough estimate
    return f"{estimated_mb:.1f} MB"


def _get_oldest_pending_operation(db: Session) -> Optional[str]:
    """Get oldest pending operation timestamp"""
    oldest = db.query(SyncQueue).filter(
        SyncQueue.status == "pending"
    ).order_by(SyncQueue.created_at).first()
    
    return oldest.created_at.isoformat() if oldest else None


def _get_device_statistics(db: Session) -> Dict[str, int]:
    """Get device distribution statistics"""
    return {
        "total": db.query(Device).count(),
        "active": db.query(Device).filter(Device.is_active == True).count(),
        "with_recent_sync": db.query(Device).filter(
            Device.last_sync > datetime.now() - timedelta(hours=24)
        ).count()
    }


def _analyze_sync_patterns(db: Session) -> Dict[str, Any]:
    """Analyze sync patterns"""
    # Return minimal data for simplified implementation
    return {}


def _generate_system_recommendations(diagnostics: Dict) -> List[str]:
    """Generate system-level recommendations"""
    recommendations = []
    
    queue_stats = diagnostics.get("system_status", {}).get("queue_health", {})
    if queue_stats.get("failed_count", 0) > 10:
        recommendations.append("High number of failed operations - check device connectivity")
    
    if queue_stats.get("pending_count", 0) > 50:
        recommendations.append("Large queue backlog - consider increasing worker capacity")
    
    device_summary = diagnostics.get("device_summary", {})
    if device_summary.get("devices_with_errors", 0) > 0:
        recommendations.append("Some devices have errors - review device diagnostics")
    
    if not recommendations:
        recommendations.append("System operating normally")
    
    return recommendations


def _generate_device_recommendations(health_data: Dict, connection_status: Dict, 
                                   attendance_stats: Dict, success_rate: float) -> List[str]:
    """Generate device-specific recommendations"""
    recommendations = []
    
    if not health_data.get("healthy", True):
        recommendations.append("Device health check failed - verify connectivity")
    
    if success_rate < 80:
        recommendations.append("Low operation success rate - reset circuit breaker")
    
    if attendance_stats.get("failed_sync", 0) > 5:
        recommendations.append("Multiple failed sync operations - check device status")
    
    if not recommendations:
        recommendations.append("Device operating normally")
    
    return recommendations


def _generate_health_recommendations(issues: List[str]) -> List[str]:
    """Generate health-based recommendations"""
    recommendations = []
    
    if "database" in issues:
        recommendations.append("Check database connectivity and disk space")
    
    if "sync_service" in issues:
        recommendations.append("Restart background sync service")
    
    if "sync_queue" in issues:
        recommendations.append("Clear failed operations and restart sync")
    
    if "cache" in issues:
        recommendations.append("Clear cache and restart cache service")
    
    if not recommendations:
        recommendations.append("All systems healthy")
    
    return recommendations