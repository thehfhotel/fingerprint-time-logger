# API Reference - Offline-First Extensions

**Fingerprint Time Logger - Enhanced API Documentation**

![API Status](https://img.shields.io/badge/API-Operational-brightgreen)
![Endpoints](https://img.shields.io/badge/Endpoints-15%20New-blue)
![Version](https://img.shields.io/badge/Version-2.0-orange)

## 📋 Overview

This document provides detailed API reference for the offline-first extensions to the Fingerprint Time Logger application. All endpoints support graceful degradation and work with cached data when devices are offline.

**Base URL**: `http://localhost:8000`  
**API Version**: 2.0  
**Authentication**: None (Internal Use)

## 🔄 Enhanced Attendance APIs

### GET /api/attendance/
Enhanced attendance retrieval with offline support.

**Query Parameters:**
- `include_offline` (boolean): Include offline data in response
- `max_age_hours` (integer): Maximum age of cached data to accept
- `device_id` (integer): Filter by specific device
- `limit` (integer): Maximum records to return

**Response:**
```json
{
  "records": [
    {
      "id": 123,
      "employee_id": "EMP001",
      "device_id": 1,
      "timestamp": "2025-06-29T10:30:00",
      "punch_type": 0,
      "sync_status": "synced",
      "created_locally": false
    }
  ],
  "data_freshness": {
    "last_sync": "2025-06-29T10:25:00",
    "cache_age_minutes": 5,
    "is_fresh": true
  },
  "sync_status": {
    "pending_count": 0,
    "failed_count": 0,
    "last_successful_sync": "2025-06-29T10:25:00"
  },
  "total_records": 1,
  "cached_data": false
}
```

### POST /api/attendance/manual
Create manual attendance record for offline scenarios.

**Query Parameters:**
- `employee_id` (string, required): Employee identifier
- `device_id` (integer, required): Device ID
- `punch_type` (integer, required): 0=Check In, 1=Check Out
- `timestamp` (string, optional): ISO format timestamp

**Response:**
```json
{
  "success": true,
  "local_id": "550e8400-e29b-41d4-a716-446655440000",
  "sync_queued": true,
  "operation_id": "op_12345",
  "message": "Manual attendance record created and queued for sync"
}
```

### GET /api/attendance/sync-status
Get synchronization status for attendance data.

**Query Parameters:**
- `device_id` (integer, optional): Filter by device

**Response:**
```json
{
  "sync_status": {
    "overall": "healthy",
    "pending_operations": 2,
    "failed_operations": 0,
    "last_sync": "2025-06-29T10:25:00"
  },
  "cache_status": {
    "entries": 150,
    "size_mb": 2.5,
    "freshness": "recent"
  },
  "device_statuses": [
    {
      "device_id": 1,
      "status": "online",
      "last_sync": "2025-06-29T10:25:00",
      "pending_count": 0
    }
  ]
}
```

### GET /api/attendance/pending-sync
Get attendance records pending synchronization.

**Response:**
```json
{
  "pending_records": [
    {
      "local_id": "550e8400-e29b-41d4-a716-446655440000",
      "employee_id": "EMP001",
      "device_id": 1,
      "created_at": "2025-06-29T10:30:00",
      "retry_count": 0
    }
  ],
  "queue_status": {
    "total_pending": 1,
    "oldest_pending": "2025-06-29T10:30:00",
    "estimated_sync_time": "2025-06-29T10:32:00"
  }
}
```

### POST /api/attendance/force-sync/{device_id}
Force immediate synchronization for a device.

**Path Parameters:**
- `device_id` (integer, required): Device to sync

**Query Parameters:**
- `sync_type` (string): "incremental" or "full" (default: incremental)

**Response:**
```json
{
  "sync_initiated": true,
  "operation_id": "op_67890",
  "device_id": 1,
  "sync_type": "incremental",
  "estimated_completion": "2025-06-29T10:32:00",
  "message": "Incremental sync queued for device 1"
}
```

### GET /api/attendance/offline-data/{device_id}
Get cached attendance data for offline use.

**Path Parameters:**
- `device_id` (integer, required): Device ID

**Response:**
```json
{
  "device_id": 1,
  "offline_data_available": true,
  "cached_records": 45,
  "cache_age_hours": 2,
  "last_updated": "2025-06-29T08:30:00",
  "data": [
    {
      "employee_id": "EMP001",
      "timestamp": "2025-06-29T08:30:00",
      "punch_type": 0,
      "cached": true
    }
  ]
}
```

## 🔍 Sync Monitoring APIs

### GET /api/sync/health
Get overall synchronization system health.

**Response:**
```json
{
  "overall_health": "healthy",
  "timestamp": "2025-06-29T10:30:00",
  "sync_service": {
    "status": "running",
    "uptime_seconds": 3600,
    "operations_processed": 150,
    "success_rate_percent": 98.5
  },
  "queue_status": {
    "pending_count": 2,
    "processing_count": 1,
    "completed_count": 147,
    "failed_count": 0
  },
  "cache_status": {
    "active_entries": 45,
    "size_estimate_mb": 2.5,
    "expired_entries": 0
  }
}
```

### GET /api/sync/devices/{device_id}/health
Get comprehensive device health status.

**Path Parameters:**
- `device_id` (integer, required): Device ID

**Query Parameters:**
- `include_history` (boolean): Include recent health history

**Response:**
```json
{
  "device_id": 1,
  "device_name": "Main Entrance",
  "ip_address": "192.168.100.209",
  "current_health": {
    "healthy": true,
    "response_time_ms": 125,
    "last_check": "2025-06-29T10:30:00"
  },
  "last_sync": "2025-06-29T10:25:00",
  "recent_operations": {
    "total": 10,
    "successful": 10,
    "failed": 0,
    "pending": 0
  },
  "reliability_metrics": {
    "uptime_percentage": 99.5,
    "operation_success_rate": 100.0
  }
}
```

### GET /api/sync/queue
Get sync queue status and operations.

**Query Parameters:**
- `device_id` (integer, optional): Filter by device
- `status_filter` (string): "pending", "processing", "completed", "failed"
- `limit` (integer): Maximum operations to return

**Response:**
```json
{
  "queue_statistics": {
    "pending_count": 2,
    "processing_count": 1,
    "completed_count": 147,
    "failed_count": 0
  },
  "operations": [
    {
      "id": 12345,
      "operation_type": "attendance_sync",
      "device_id": 1,
      "status": "pending",
      "priority": 5,
      "created_at": "2025-06-29T10:30:00",
      "retry_count": 0
    }
  ],
  "filters_applied": {
    "device_id": null,
    "status": "pending",
    "limit": 50
  }
}
```

### GET /api/sync/cache/status
Get cache system status and statistics.

**Response:**
```json
{
  "cache_status": {
    "total_cache_entries": 45,
    "active_entries": 43,
    "expired_entries": 2,
    "estimated_size_bytes": 2621440
  },
  "storage_usage": {
    "size_mb": 2.5,
    "entries": 45,
    "active_entries": 43,
    "expired_entries": 2
  },
  "timestamp": "2025-06-29T10:30:00"
}
```

### POST /api/sync/cache/refresh
Refresh cache entries and trigger sync.

**Query Parameters:**
- `device_id` (integer, optional): Refresh specific device cache

**Response:**
```json
{
  "success": true,
  "cache_entries_refreshed": 1,
  "sync_triggered": true,
  "operation_id": "op_refresh_12345",
  "message": "Cache refreshed and sync triggered for device 1"
}
```

## 🔬 Diagnostic APIs

### GET /api/diagnostics/system
Get comprehensive system diagnostics.

**Query Parameters:**
- `include_performance` (boolean): Include performance metrics
- `include_detailed_stats` (boolean): Include detailed statistics

**Response:**
```json
{
  "timestamp": "2025-06-29T10:30:00",
  "system_status": {
    "database_connected": true,
    "background_service": {
      "state": "running",
      "uptime_seconds": 3600
    },
    "queue_health": {
      "pending_count": 2,
      "failed_count": 0
    },
    "cache_health": {
      "active_entries": 45,
      "expired_entries": 0
    }
  },
  "device_summary": {
    "total_devices": 1,
    "active_devices": 1,
    "devices_with_recent_sync": 1,
    "devices_with_errors": 0
  },
  "data_statistics": {
    "total_attendance_records": 1250,
    "records_today": 25,
    "pending_sync_records": 2,
    "failed_sync_records": 0
  },
  "recommendations": [
    "System operating normally"
  ]
}
```

### GET /api/diagnostics/devices/{device_id}
Get detailed diagnostics for a specific device.

**Path Parameters:**
- `device_id` (integer, required): Device ID

**Query Parameters:**
- `hours_back` (integer): Hours of history to include (1-168)

**Response:**
```json
{
  "device_info": {
    "device_id": 1,
    "device_name": "Main Entrance",
    "ip_address": "192.168.100.209",
    "is_active": true,
    "last_sync": "2025-06-29T10:25:00"
  },
  "health_check": {
    "healthy": true,
    "response_time_ms": 125,
    "last_check": "2025-06-29T10:30:00"
  },
  "reliability_metrics": {
    "uptime_percentage": 99.5,
    "operation_success_rate": 100.0,
    "total_operations": 10,
    "successful_operations": 10,
    "failed_operations": 0
  },
  "attendance_statistics": {
    "total_records": 1250,
    "records_last_24h": 25,
    "pending_sync": 0,
    "failed_sync": 0
  },
  "recommendations": [
    "Device operating normally"
  ]
}
```

### GET /api/diagnostics/performance
Get detailed performance metrics for the system.

**Query Parameters:**
- `time_window_hours` (integer): Time window for analysis (1-168)
- `include_trends` (boolean): Include trend analysis

**Response:**
```json
{
  "measurement_period_hours": 24,
  "timestamp": "2025-06-29T10:30:00",
  "service_performance": {
    "uptime_hours": 24.0,
    "operations_processed": 150,
    "operations_per_hour": 6.25,
    "success_rate_percent": 98.5,
    "avg_operation_time_ms": 250
  },
  "queue_performance": {
    "current_backlog": 2,
    "processing_rate": 6.25,
    "failure_rate_percent": 1.5,
    "retry_success_rate": 75.0
  },
  "database_performance": {
    "total_queries_estimated": 150,
    "avg_response_time_ms": 25,
    "cache_hit_ratio": 85.0
  },
  "trends": {
    "operations_trend": "stable",
    "success_rate_trend": "improving",
    "queue_size_trend": "decreasing",
    "cache_usage_trend": "stable"
  }
}
```

### GET /api/diagnostics/alerts
Get system alerts and warnings.

**Query Parameters:**
- `severity` (string): "low", "medium", "high", "critical"
- `device_id` (integer, optional): Filter by device
- `limit` (integer): Maximum alerts to return

**Response:**
```json
{
  "alerts": [
    {
      "id": "device_offline_1_1719662200",
      "severity": "medium",
      "type": "device_offline",
      "message": "Device 'Main Entrance' offline for 2.5 hours",
      "timestamp": "2025-06-29T10:30:00",
      "device_id": 1,
      "recommended_action": "Check device network connectivity and power status"
    }
  ],
  "total_count": 1,
  "summary": {
    "critical": 0,
    "high": 0,
    "medium": 1,
    "low": 0
  },
  "filters_applied": {
    "severity": null,
    "device_id": null,
    "limit": 50
  }
}
```

### GET /api/diagnostics/health-check
Comprehensive system health check.

**Response:**
```json
{
  "timestamp": "2025-06-29T10:30:00",
  "overall_status": "healthy",
  "components": {
    "database": {
      "status": "healthy",
      "message": "Database connection OK"
    },
    "sync_service": {
      "status": "healthy",
      "message": "Background sync service running"
    },
    "sync_queue": {
      "status": "healthy",
      "message": "Sync queue operating normally"
    },
    "cache": {
      "status": "healthy",
      "message": "Cache system operational"
    }
  },
  "issues": [],
  "recommendations": [
    "All systems healthy"
  ]
}
```

## ⚙️ Control APIs

### GET /api/control/service/status
Get background sync service status and metrics.

**Response:**
```json
{
  "service_status": "running",
  "worker_active": true,
  "configuration": {
    "worker_interval_seconds": 30,
    "max_concurrent_operations": 3,
    "device_health_check_interval": 300
  },
  "performance_metrics": {
    "operations_processed": 150,
    "operations_succeeded": 148,
    "operations_failed": 2,
    "total_sync_time": 3750,
    "avg_operation_time": 25,
    "last_activity": "2025-06-29T10:29:00",
    "uptime_seconds": 3600,
    "devices_synced": [1]
  }
}
```

### POST /api/control/service/start
Start the background sync service.

**Response:**
```json
{
  "success": true,
  "message": "Background sync service started successfully",
  "timestamp": "2025-06-29T10:30:00",
  "service_state": "starting"
}
```

### POST /api/control/devices/{device_id}/force-sync
Force immediate synchronization for a specific device.

**Path Parameters:**
- `device_id` (integer, required): Device to sync

**Query Parameters:**
- `sync_type` (string): "incremental" or "full"
- `high_priority` (boolean): Use high priority for sync operation

**Response:**
```json
{
  "sync_initiated": true,
  "operation_id": "op_force_67890",
  "device_id": 1,
  "device_name": "Main Entrance",
  "sync_type": "incremental",
  "high_priority": false,
  "message": "Incremental sync queued for device 'Main Entrance'"
}
```

### POST /api/control/devices/{device_id}/reset-circuit
Reset circuit breaker for a specific device.

**Path Parameters:**
- `device_id` (integer, required): Device ID

**Response:**
```json
{
  "success": true,
  "device_id": 1,
  "device_name": "Main Entrance",
  "message": "Circuit breaker reset for device 'Main Entrance'"
}
```

### POST /api/control/devices/sync-all
Initiate sync for all devices.

**Query Parameters:**
- `sync_type` (string): "incremental" or "full"
- `only_active` (boolean): Only sync active devices

**Response:**
```json
{
  "sync_initiated": true,
  "total_devices": 1,
  "successfully_queued": 1,
  "failed_to_queue": 0,
  "sync_type": "incremental",
  "queued_operations": [
    {
      "device_id": 1,
      "device_name": "Main Entrance",
      "operation_id": "op_sync_all_12345"
    }
  ],
  "failed_operations": [],
  "message": "Queued incremental sync for 1 devices"
}
```

### POST /api/control/queue/retry-all-failed
Retry all failed sync operations.

**Query Parameters:**
- `device_id` (integer, optional): Retry failures for specific device
- `operation_type` (string, optional): Retry specific operation type

**Response:**
```json
{
  "success": true,
  "operations_retried": 2,
  "filters": {
    "device_id": null,
    "operation_type": null
  },
  "message": "Retried 2 failed operations",
  "timestamp": "2025-06-29T10:30:00"
}
```

### GET /api/control/maintenance/status
Get system maintenance status and recommendations.

**Response:**
```json
{
  "maintenance_status": "not_needed",
  "recommended_tasks": [],
  "system_metrics": {
    "cache_entries": 45,
    "expired_cache": 0,
    "queue_size": 3,
    "failed_operations": 0
  },
  "last_maintenance": "Not tracked",
  "timestamp": "2025-06-29T10:30:00"
}
```

### POST /api/control/maintenance/full-cleanup
Perform comprehensive system cleanup.

**Query Parameters:**
- `confirm` (boolean, required): Confirmation for destructive operation

**Response:**
```json
{
  "timestamp": "2025-06-29T10:30:00",
  "success": true,
  "total_items_cleaned": 25,
  "operations_performed": [
    {
      "operation": "cleanup_completed_operations",
      "count": 20,
      "success": true
    },
    {
      "operation": "clear_expired_cache",
      "count": 3,
      "success": true
    },
    {
      "operation": "cleanup_inactive_connections",
      "count": 2,
      "success": true
    }
  ],
  "message": "Full system cleanup completed - 25 items cleaned"
}
```

## 🔒 Error Responses

### Standard Error Format
```json
{
  "detail": "Error description",
  "status_code": 400,
  "timestamp": "2025-06-29T10:30:00",
  "path": "/api/attendance/manual",
  "method": "POST"
}
```

### Common HTTP Status Codes
- **200**: Success
- **201**: Created
- **400**: Bad Request
- **404**: Not Found
- **422**: Validation Error
- **500**: Internal Server Error

### Offline-Specific Responses
When operating in offline mode, APIs may return:
```json
{
  "offline_mode": true,
  "cached_data": true,
  "last_sync": "2025-06-29T08:30:00",
  "data_age_hours": 2,
  "message": "Displaying cached data - device offline"
}
```

## 📊 Rate Limiting & Performance

### Rate Limits
- **Health Checks**: 60 requests/minute
- **Sync Operations**: 10 requests/minute
- **Manual Operations**: 5 requests/minute
- **Diagnostics**: 30 requests/minute

### Response Times
- **Cached Data**: < 50ms
- **Database Queries**: < 200ms
- **Device Operations**: < 5000ms
- **Background Operations**: Async

### Pagination
Large datasets support pagination:
```
GET /api/attendance/?limit=50&offset=100
```

### Caching Headers
Responses include cache control headers:
```
Cache-Control: max-age=300
ETag: "version-123"
Last-Modified: Fri, 29 Jun 2025 10:30:00 GMT
```

## 🧪 Testing Examples

### cURL Examples

#### Check System Health
```bash
curl -X GET "http://localhost:8000/api/diagnostics/health-check" \
  -H "Accept: application/json"
```

#### Force Device Sync
```bash
curl -X POST "http://localhost:8000/api/control/devices/1/force-sync?sync_type=full" \
  -H "Content-Type: application/json"
```

#### Create Manual Attendance
```bash
curl -X POST "http://localhost:8000/api/attendance/manual?employee_id=EMP001&device_id=1&punch_type=0" \
  -H "Content-Type: application/json"
```

#### Get Sync Status
```bash
curl -X GET "http://localhost:8000/api/sync/health" \
  -H "Accept: application/json"
```

### Python Examples

```python
import requests

# Health check
response = requests.get("http://localhost:8000/api/diagnostics/health-check")
health = response.json()

# Manual attendance
response = requests.post(
    "http://localhost:8000/api/attendance/manual",
    params={"employee_id": "EMP001", "device_id": 1, "punch_type": 0}
)

# Force sync
response = requests.post(
    "http://localhost:8000/api/control/devices/1/force-sync",
    params={"sync_type": "incremental"}
)
```

## 📝 Changelog

### Version 2.0.0 (2025-06-29)
- ✅ Added 15 new offline-first API endpoints
- ✅ Implemented comprehensive health monitoring
- ✅ Added sync queue management
- ✅ Enhanced error handling and recovery
- ✅ Added cache management APIs
- ✅ Implemented diagnostic endpoints
- ✅ Added manual sync controls

### Version 1.0.0 (Previous)
- Basic attendance tracking
- Simple device connectivity
- Limited error handling

---

**API Reference Version**: 2.0  
**Last Updated**: 2025-06-29  
**Implementation Status**: Complete ✅

*This API reference covers all offline-first extensions to the Fingerprint Time Logger application. All endpoints are designed to work seamlessly whether devices are online or offline.*