# API Reference - Fingerprint Time Logger

**Version**: 1.0  
**Base URL**: `http://localhost:5000`  
**Last Updated**: January 2025

## Overview

The Fingerprint Time Logger API provides comprehensive endpoints for managing ZKTeco biometric devices, employee records, attendance tracking, and data export functionality. All endpoints return JSON responses and follow RESTful conventions.

## Authentication

Currently, the API does not require authentication. It's designed for single-user local installations.

## Response Format

All API responses follow a consistent format:

```json
{
  "success": true,
  "data": {...},
  "message": "Optional message"
}
```

Error responses:
```json
{
  "success": false,
  "error": "Error description",
  "detail": "Optional detailed error message"
}
```

## API Endpoints

### 1. Attendance API (`/api/attendance/`)

#### Get Attendance Records
```http
GET /api/attendance/
```

**Query Parameters:**
- `start_date` (optional): ISO datetime string
- `end_date` (optional): ISO datetime string  
- `employee_badge` (optional): Employee badge number
- `limit` (optional): Number of records (default: 100)
- `offset` (optional): Record offset for pagination

**Response:**
```json
{
  "records": [
    {
      "id": 1,
      "employee_badge_number": "001",
      "timestamp": "2025-01-09T08:30:00",
      "punch_type": 0,
      "status": 0,
      "device_id": 1,
      "sync_status": "synced"
    }
  ],
  "total": 100,
  "filters": {
    "start_date": null,
    "end_date": null,
    "employee_badge": null
  }
}
```

#### Get Attendance Summary
```http
GET /api/attendance/summary
```

**Response:**
```json
{
  "total_records": 1500,
  "today_records": 45,
  "last_sync": "2025-01-09T08:30:00",
  "employees_today": 23,
  "device_status": "connected"
}
```

#### Get Employee Attendance
```http
GET /api/attendance/employee/{employee_badge}
```

**Query Parameters:**
- `days` (optional): Number of days to retrieve (default: 30)

**Response:**
```json
{
  "employee": {
    "badge_number": "001",
    "display_name": "John Doe",
    "is_active": true
  },
  "records": [...],
  "summary": {
    "total_records": 60,
    "check_ins": 30,
    "check_outs": 30
  }
}
```

#### Get Calendar Configuration
```http
GET /api/attendance/calendar/config
```

**Response:**
```json
{
  "current_month": 1,
  "current_year": 2025,
  "total_employees": 50,
  "active_employees": 45,
  "available_months": [
    {"month": 1, "year": 2025, "record_count": 1200}
  ]
}
```

#### Get Calendar Data
```http
GET /api/attendance/calendar/{year}/{month}
```

**Response:**
```json
{
  "year": 2025,
  "month": 1,
  "employees": [
    {
      "badge_number": "001",
      "display_name": "John Doe",
      "attendance_data": {
        "1": [
          {
            "timestamp": "2025-01-01T08:30:00",
            "punch_type": 0,
            "status": 0
          }
        ]
      }
    }
  ]
}
```

#### Get Today's Records
```http
GET /api/attendance/today
```

**Response:**
```json
{
  "date": "2025-01-09",
  "records": [...],
  "summary": {
    "total_records": 45,
    "unique_employees": 23,
    "check_ins": 25,
    "check_outs": 20
  }
}
```

#### Sync Attendance Data
```http
POST /api/attendance/sync
```

**Response:**
```json
{
  "success": true,
  "message": "Attendance sync completed",
  "data": {
    "records_imported": 15,
    "employees_updated": 8,
    "sync_duration": "2.3s"
  }
}
```

#### Get Sync Status
```http
GET /api/attendance/sync/status
```

**Response:**
```json
{
  "last_sync": "2025-01-09T08:30:00",
  "sync_status": "completed",
  "next_sync": "2025-01-09T09:00:00",
  "auto_sync_enabled": true,
  "sync_interval_minutes": 30
}
```

#### Export Attendance CSV
```http
GET /api/attendance/export/csv
```

**Query Parameters:**
- `start_date` (optional): ISO datetime string
- `end_date` (optional): ISO datetime string
- `employee_badge` (optional): Employee badge number

**Response:** CSV file download

#### Health Check
```http
GET /api/attendance/health
```

**Response:**
```json
{
  "status": "healthy",
  "database_accessible": true,
  "last_record_time": "2025-01-09T08:30:00",
  "total_records": 1500
}
```

### 2. Device API (`/api/devices/`)

#### Get All Devices
```http
GET /api/devices/
```

**Response:**
```json
[
  {
    "id": 1,
    "name": "ZKTeco Device",
    "ip_address": "192.168.100.209",
    "port": 4370,
    "password": 0,
    "is_active": true,
    "last_sync": "2025-01-09T08:30:00",
    "created_at": "2025-01-01T00:00:00"
  }
]
```

#### Get Default Device
```http
GET /api/devices/default
```

**Response:**
```json
{
  "id": 1,
  "name": "ZKTeco Device",
  "ip_address": "192.168.100.209",
  "port": 4370,
  "is_active": true,
  "connection_status": "connected"
}
```

#### Get Device Status
```http
GET /api/devices/status
```

**Response:**
```json
{
  "device_id": 1,
  "connected": true,
  "ip_address": "192.168.100.209",
  "port": 4370,
  "firmware": "Ver 6.60 Apr 28 2017",
  "users_count": 50,
  "records_count": 1500,
  "last_connection": "2025-01-09T08:30:00",
  "response_time_ms": 120
}
```

#### Test Device Connection
```http
POST /api/devices/test-connection
```

**Request Body:**
```json
{
  "ip_address": "192.168.100.209",
  "port": 4370,
  "password": 0
}
```

**Response:**
```json
{
  "success": true,
  "connected": true,
  "message": "Device connected successfully",
  "device_info": {
    "firmware": "Ver 6.60 Apr 28 2017",
    "users_count": 50,
    "records_count": 1500
  }
}
```

#### Sync System Time to Device
```http
POST /api/devices/sync-time
```

**Response:**
```json
{
  "success": true,
  "message": "Device time synchronized",
  "old_time": "2025-01-09T08:29:45",
  "new_time": "2025-01-09T08:30:00",
  "time_difference_seconds": 15
}
```

#### Sync Attendance Data
```http
POST /api/devices/sync/attendance
```

**Response:**
```json
{
  "success": true,
  "message": "Attendance data synchronized",
  "records_imported": 15,
  "employees_updated": 8,
  "sync_duration": "2.3s"
}
```

#### Get Device Time
```http
GET /api/devices/time
```

**Response:**
```json
{
  "success": true,
  "device_time": "2025-01-09T08:30:00",
  "server_time": "2025-01-09T08:30:05",
  "synchronized": false,
  "time_difference_seconds": 5,
  "auto_synced": false,
  "message": "Device time is 5 seconds behind"
}
```

#### Sync Device Time
```http
POST /api/devices/time/sync
```

**Response:**
```json
{
  "success": true,
  "message": "Device time synchronized successfully",
  "old_time": "2025-01-09T08:29:45",
  "new_time": "2025-01-09T08:30:00",
  "time_difference_seconds": 15,
  "synchronized": true
}
```

#### Get Device Configuration
```http
GET /api/devices/config
```

**Response:**
```json
{
  "device_id": 1,
  "name": "ZKTeco Device",
  "ip_address": "192.168.100.209",
  "port": 4370,
  "timeout": 30,
  "max_retries": 3,
  "auto_sync_enabled": true,
  "sync_interval_minutes": 30
}
```

#### Get Application Configuration
```http
GET /api/devices/app-config
```

**Response:**
```json
{
  "auto_import_enabled": true,
  "auto_import_interval_minutes": 30,
  "database_url": "sqlite:///./database/attendance.db",
  "log_level": "INFO",
  "environment": "development"
}
```

#### Get Device Diagnostics
```http
GET /api/devices/diagnostics
```

**Response:**
```json
{
  "device_id": 1,
  "connection_test": {
    "success": true,
    "response_time_ms": 120,
    "last_test": "2025-01-09T08:30:00"
  },
  "firmware_info": {
    "version": "Ver 6.60 Apr 28 2017",
    "platform": "ZKTeco"
  },
  "capacity": {
    "max_users": 1000,
    "current_users": 50,
    "max_records": 100000,
    "current_records": 1500
  },
  "network": {
    "ip_address": "192.168.100.209",
    "port": 4370,
    "mac_address": "00:11:22:33:44:55"
  }
}
```

#### Health Check
```http
GET /api/devices/health
```

**Response:**
```json
{
  "status": "healthy",
  "device_connected": true,
  "last_sync": "2025-01-09T08:30:00",
  "response_time_ms": 120
}
```

### 3. Employee API (`/api/employees/`)

#### Get All Employees
```http
GET /api/employees/
```

**Query Parameters:**
- `include_inactive` (optional): Include inactive employees (default: false)
- `include_hidden` (optional): Include hidden employees (default: false)
- `role_id` (optional): Filter by job role ID

**Response:**
```json
{
  "employees": [
    {
      "id": 1,
      "badge_number": "001",
      "english_name": "John Doe",
      "thai_name": "จอห์น โด",
      "display_name": "จอห์น โด",
      "department": "IT",
      "position": "Developer",
      "job_role_id": 1,
      "is_active": true,
      "is_hidden": false,
      "created_at": "2025-01-01T00:00:00",
      "updated_at": "2025-01-09T08:30:00"
    }
  ],
  "total": 50,
  "active": 45,
  "hidden": 2
}
```

#### Get Specific Employee
```http
GET /api/employees/{badge_number}
```

**Response:**
```json
{
  "id": 1,
  "badge_number": "001",
  "english_name": "John Doe",
  "thai_name": "จอห์น โด",
  "display_name": "จอห์น โด",
  "department": "IT",
  "position": "Developer",
  "job_role_id": 1,
  "is_active": true,
  "is_hidden": false,
  "created_at": "2025-01-01T00:00:00",
  "updated_at": "2025-01-09T08:30:00"
}
```

#### Update Employee
```http
PUT /api/employees/{badge_number}
```

**Request Body:**
```json
{
  "english_name": "John Smith",
  "thai_name": "จอห์น สมิธ",
  "department": "HR",
  "position": "Manager",
  "job_role_id": 2,
  "is_active": true,
  "is_hidden": false
}
```

**Response:**
```json
{
  "success": true,
  "message": "Employee updated successfully",
  "employee": {...}
}
```

#### Delete Employee (Soft Delete)
```http
DELETE /api/employees/{badge_number}
```

**Response:**
```json
{
  "success": true,
  "message": "Employee deactivated successfully"
}
```

#### Update Employee Nickname
```http
PUT /api/employees/{badge_number}/nickname
```

**Request Body:**
```json
{
  "thai_name": "จอห์น สมิธ"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Employee nickname updated successfully",
  "employee": {...}
}
```

#### Update Employee Status
```http
PUT /api/employees/{badge_number}/status
```

**Request Body:**
```json
{
  "is_active": false
}
```

**Response:**
```json
{
  "success": true,
  "message": "Employee status updated successfully",
  "employee": {...}
}
```

#### Update Employee Visibility
```http
PUT /api/employees/{badge_number}/hidden
```

**Request Body:**
```json
{
  "is_hidden": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Employee visibility updated successfully",
  "employee": {...}
}
```

#### Get Thai Names
```http
GET /api/employees/thai-names/
```

**Response:**
```json
{
  "thai_names": [
    {
      "badge_number": "001",
      "english_name": "John Doe",
      "thai_name": "จอห์น โด",
      "display_name": "จอห์น โด"
    }
  ]
}
```

#### Update Thai Name
```http
PUT /api/employees/thai-names/{badge_number}
```

**Request Body:**
```json
{
  "thai_name": "จอห์น สมิธ"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Thai name updated successfully",
  "employee": {...}
}
```

#### Get Job Roles
```http
GET /api/employees/roles/
```

**Response:**
```json
{
  "roles": [
    {
      "id": 1,
      "role_name": "developer",
      "display_name": "Developer",
      "description": "Software development role",
      "has_shifts": false,
      "is_active": true,
      "employee_count": 10
    }
  ]
}
```

#### Create Job Role
```http
POST /api/employees/roles/
```

**Request Body:**
```json
{
  "role_name": "manager",
  "display_name": "Manager",
  "description": "Management role",
  "has_shifts": false,
  "is_active": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Job role created successfully",
  "role": {...}
}
```

#### Get Employees by Role
```http
GET /api/employees/by-role/{role_id}
```

**Response:**
```json
{
  "role": {
    "id": 1,
    "role_name": "developer",
    "display_name": "Developer"
  },
  "employees": [...]
}
```

#### Get Employee Statistics
```http
GET /api/employees/stats/summary
```

**Response:**
```json
{
  "total_employees": 50,
  "active_employees": 45,
  "inactive_employees": 5,
  "hidden_employees": 2,
  "employees_with_thai_names": 40,
  "employees_by_role": {
    "developer": 10,
    "manager": 5
  }
}
```

#### Health Check
```http
GET /api/employees/health
```

**Response:**
```json
{
  "status": "healthy",
  "total_employees": 50,
  "active_employees": 45,
  "database_accessible": true
}
```

### 4. Export API (`/api/export/`)

#### Export Attendance CSV
```http
GET /api/export/attendance/csv
```

**Query Parameters:**
- `start_date` (optional): ISO datetime string
- `end_date` (optional): ISO datetime string
- `employee_badge` (optional): Employee badge number

**Response:** CSV file download

#### Export Attendance Summary
```http
GET /api/export/attendance/summary
```

**Query Parameters:**
- `start_date` (optional): ISO datetime string
- `end_date` (optional): ISO datetime string

**Response:** CSV file download with summary data

#### Export Employee List
```http
GET /api/export/employees/csv
```

**Query Parameters:**
- `include_inactive` (optional): Include inactive employees
- `include_hidden` (optional): Include hidden employees

**Response:** CSV file download

#### Export Thai Names
```http
GET /api/export/employees/thai-names
```

**Response:** CSV file download with Thai name mappings

#### Export Device Configuration
```http
GET /api/export/devices/config
```

**Response:** JSON file download with device configuration

#### Export Device Status Report
```http
GET /api/export/devices/status-report
```

**Response:** CSV file download with device status information

#### Export Monthly Report
```http
GET /api/export/reports/monthly
```

**Query Parameters:**
- `year` (required): Year (e.g., 2025)
- `month` (required): Month (1-12)

**Response:** CSV file download with monthly attendance report

#### Export Employee Summary
```http
GET /api/export/reports/employee-summary
```

**Response:** CSV file download with employee summary statistics

#### Get Export Formats
```http
GET /api/export/formats
```

**Response:**
```json
{
  "supported_formats": [
    {
      "format": "csv",
      "description": "Comma-separated values",
      "mime_type": "text/csv"
    },
    {
      "format": "json",
      "description": "JSON format",
      "mime_type": "application/json"
    }
  ]
}
```

#### Quick Export Today's Attendance
```http
GET /api/export/quick/today-attendance
```

**Response:** CSV file download with today's attendance

#### Quick Export This Month
```http
GET /api/export/quick/this-month
```

**Response:** CSV file download with current month's data

#### Quick Export All Employees
```http
GET /api/export/quick/all-employees
```

**Response:** CSV file download with all employee data

#### Health Check
```http
GET /api/export/health
```

**Response:**
```json
{
  "status": "healthy",
  "export_functions_available": true,
  "last_export": "2025-01-09T08:30:00"
}
```

### 5. System API (`/api/system/`)

#### Get System Health
```http
GET /api/system/health
```

**Response:**
```json
{
  "overall_status": "healthy",
  "timestamp": "2025-01-09T08:30:00",
  "device_health": {
    "connected": true,
    "ip_address": "192.168.100.209",
    "firmware": "Ver 6.60 Apr 28 2017",
    "response_time_ms": 120
  },
  "database_health": {
    "accessible": true,
    "total_employees": 50,
    "total_attendance_records": 1500
  },
  "system_resources": {
    "disk_usage_percent": 45,
    "disk_free_gb": 25.5,
    "disk_total_gb": 50.0
  },
  "application_stats": {
    "employees": {
      "total": 50,
      "active": 45
    },
    "attendance": {
      "today_records": 45,
      "last_record_time": "2025-01-09T08:30:00"
    }
  }
}
```

#### Get System Logs
```http
GET /api/system/logs
```

**Query Parameters:**
- `log_type` (optional): Filter by log type (connection, sync, error, api, all)
- `limit` (optional): Number of log entries (default: 50)

**Response:**
```json
{
  "logs": [
    {
      "timestamp": "2025-01-09T08:30:00",
      "level": "INFO",
      "message": "Device connection established",
      "source": "device_service"
    }
  ],
  "total": 100,
  "log_type": "all"
}
```

#### Get Performance Metrics
```http
GET /api/system/metrics
```

**Response:**
```json
{
  "api_performance": {
    "db_query_time_ms": 15,
    "status": "healthy",
    "response_time_ms": 120
  },
  "activity_metrics": {
    "last_24_hours": {
      "attendance_records": 150,
      "api_requests": 500,
      "sync_operations": 48
    },
    "current_session": {
      "uptime_seconds": 3600,
      "requests_handled": 100
    }
  }
}
```

## Error Codes

Common HTTP status codes used by the API:

- `200 OK`: Request successful
- `201 Created`: Resource created successfully
- `400 Bad Request`: Invalid request parameters
- `404 Not Found`: Resource not found
- `422 Unprocessable Entity`: Validation errors
- `500 Internal Server Error`: Server error

## Rate Limiting

Currently, no rate limiting is implemented. The API is designed for single-user local installations.

## WebSocket Support

The system supports WebSocket connections for real-time updates:

```javascript
const ws = new WebSocket('ws://localhost:5000/ws');
ws.onmessage = function(event) {
  const data = JSON.parse(event.data);
  // Handle real-time updates
};
```

## Data Types

### Punch Types
- `0`: Check In
- `1`: Check Out  
- `2`: Break Out
- `3`: Break In
- `4`: Overtime In
- `5`: Overtime Out

### Status Types
- `0`: Normal
- `1`: Late
- `2`: Early

### Sync Status
- `synced`: Record synchronized with device
- `pending`: Awaiting synchronization
- `failed`: Synchronization failed

## Examples

### Complete Employee Management Workflow

```javascript
// 1. Get all employees
const employees = await fetch('/api/employees/').then(r => r.json());

// 2. Update employee Thai name
await fetch('/api/employees/001/nickname', {
  method: 'PUT',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({thai_name: 'จอห์น สมิธ'})
});

// 3. Get employee attendance
const attendance = await fetch('/api/attendance/employee/001').then(r => r.json());

// 4. Export employee data
window.location.href = '/api/export/employees/csv';
```

### Device Management

```javascript
// 1. Check device status
const status = await fetch('/api/devices/status').then(r => r.json());

// 2. Sync device time if needed
if (!status.synchronized) {
  await fetch('/api/devices/time/sync', {method: 'POST'});
}

// 3. Sync attendance data
await fetch('/api/devices/sync/attendance', {method: 'POST'});
```

## Support

For additional support or questions about the API, refer to:
- **System Architecture**: `docs/SYSTEM_ARCHITECTURE.md`
- **Developer Guide**: `docs/DEVELOPER_GUIDE.md`
- **Database Schema**: `database/database_schema.md`