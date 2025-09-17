# API Endpoint Validation Report

Generated: 2025-09-17

## Summary

This report analyzes all API endpoint references throughout the codebase to identify non-existent endpoints and potential issues.

## Official API Endpoints (Active)

Based on router registrations in `app/main_unified.py`:

### Attendance API (`/api/attendance/`)
- `GET /api/attendance/` - Get attendance records
- `GET /api/attendance/summary` - Get attendance summary
- `GET /api/attendance/employee/{employee_badge}` - Get employee attendance
- `GET /api/attendance/calendar/config` - Get calendar configuration
- `GET /api/attendance/calendar/{year}/{month}` - Get monthly calendar
- `GET /api/attendance/today` - Get today's attendance
- `POST /api/attendance/sync` - Sync attendance data
- `GET /api/attendance/sync/status` - Get sync status
- `GET /api/attendance/export/csv` - Export attendance to CSV
- `GET /api/attendance/health` - Health check
- `POST /api/attendance/records/{record_id}/mark-late` - Mark record as late
- `GET /api/attendance/records/{record_id}/adjustments` - Get record adjustments
- `DELETE /api/attendance/records/{record_id}/adjustments/{adjustment_id}` - Delete adjustment

### Devices API (`/api/devices/`)
- `GET /api/devices/` - List devices
- `GET /api/devices/default` - Get default device
- `GET /api/devices/status` - Get device status
- `POST /api/devices/test-connection` - Test device connection
- `POST /api/devices/sync-time` - Sync device time
- `POST /api/devices/sync/attendance` - Sync attendance from device
- `GET /api/devices/time` - Get device time
- `POST /api/devices/time/sync` - Sync device time
- `GET /api/devices/config` - Get device config
- `GET /api/devices/app-config` - Get app config
- `GET /api/devices/diagnostics` - Get device diagnostics
- `GET /api/devices/health` - Health check

### Employees API (`/api/employees/`)
- `PUT /api/employees/{badge_number}/nickname` - Update nickname
- `PUT /api/employees/{badge_number}/status` - Update status
- `PUT /api/employees/{badge_number}/hidden` - Update visibility
- `GET /api/employees/` - List employees
- `GET /api/employees/health` - Health check
- `GET /api/employees/{badge_number}` - Get employee details
- `PUT /api/employees/{badge_number}` - Update employee
- `DELETE /api/employees/{badge_number}` - Delete employee
- `GET /api/employees/thai-names/` - Get Thai names
- `PUT /api/employees/thai-names/{badge_number}` - Update Thai name
- `GET /api/employees/stats/summary` - Get employee statistics
- `GET /api/employees/export/csv` - Export employees to CSV

### System API (`/api/system/`)
- `GET /api/system/health` - System health check
- `GET /api/system/logs` - Get system logs
- `GET /api/system/metrics` - Get system metrics

### Auto-Import API (Direct in main_unified.py)
- `GET /api/auto-import/status` - Get auto-import status
- `POST /api/auto-import/trigger` - Trigger auto-import
- `POST /api/refresh` - Refresh data

## Non-Existent Endpoints Found

### 🚨 Critical Issues

1. **`/api/export/*` routes referenced but not registered**
   - Found in coverage report: `/api/export` router inclusion
   - **Files affected**: `reports/unit/coverage/d_5f5a17c013354698_main_unified_py.html:289`
   - **Issue**: Coverage report shows this route was included, but it's not in current main_unified.py
   - **Impact**: Historical test failures, outdated documentation

2. **Non-existent device endpoints**
   - `/api/devices/stats` - Referenced in `tests/test_device_endpoints.py:53`
   - `/api/devices/{id}/test-connection` - Referenced in `tests/test_device_endpoints.py:63`
   - `/api/devices/{id}/sync-time` - Referenced in `tests/test_device_endpoints.py:68`
   - `/api/devices/{id}/diagnostics` - Referenced in `tests/test_device_endpoints.py:73`

3. **Non-existent websocket config endpoint**
   - `/api/websocket/config` - Referenced in `tests/e2e/test_dashboard.py:139`

### ⚠️ Test-Only References (Intentional 404s)

These endpoints are intentionally non-existent for testing error handling:

1. **Security test endpoints** (Proper 404 testing):
   - `/api/nonexistent` - Multiple test files
   - `/api/attendance/invalid` - Security tests
   - `/api/employees/export/nonexistent-format/` - Security tests
   - `/api/admin/` - Security protected endpoint testing

2. **Invalid parameter testing**:
   - `/api/employees/NONEXISTENT` - Valid endpoint, invalid ID
   - `/api/devices/99999` - Valid endpoint, invalid ID

### 🔍 Potentially Valid but Suspicious

1. **Employee management endpoints** (May be missing POST for creation):
   - Tests reference `POST /api/employees/` but only PUT/GET/DELETE are defined
   - Found in multiple test files expecting 201 creation responses

2. **Device creation endpoints**:
   - Tests reference `POST /api/devices/` but only GET is defined
   - Found in security tests expecting device creation

## Recommendations

### Immediate Fixes Needed

1. **Remove obsolete `/api/export` references**
   - Clean up any remaining import statements
   - Update any documentation that mentions this endpoint

2. **Fix device test endpoints**
   - Update tests to use correct device endpoint paths:
     - `/api/devices/stats` → `/api/devices/status`
     - `/api/devices/{id}/*` → `/api/devices/*` (device ID not in path)

3. **Remove websocket config endpoint reference**
   - Update E2E test to remove `/api/websocket/config` check

### Design Decisions Needed

1. **Employee Creation API**
   - Decide if `POST /api/employees/` should be implemented
   - Multiple tests expect this functionality

2. **Device Creation API**
   - Decide if `POST /api/devices/` should be implemented
   - Security tests expect this functionality

### Files Requiring Updates

**High Priority:**
- `tests/test_device_endpoints.py` - Fix device endpoint paths
- `tests/e2e/test_dashboard.py` - Remove websocket config check

**Medium Priority:**
- Review all tests expecting `POST /api/employees/` and `POST /api/devices/`
- Clean up obsolete export route references

**Low Priority:**
- Update documentation to reflect current API structure

## Validation Commands

To verify fixes:
```bash
# Run security tests to check endpoint handling
./scripts/test-verify.sh security

# Run device endpoint tests
python3 -m pytest tests/test_device_endpoints.py -v

# Run E2E dashboard tests
python3 -m pytest tests/e2e/test_dashboard.py -v
```

---
*Report generated by comprehensive codebase analysis*