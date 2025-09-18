# Employee State Persistence Issue Analysis

**Date**: September 18, 2025
**Issue**: Employee hidden status not persisting when cycling through "Show Hidden" button
**Status**: Partially Fixed - Database persistence needs investigation

## Problem Description

Employee hidden status is not persisting when cycling through the "Show Hidden" button. Specifically, when you hide employee 3, then toggle "Show Hidden", the employee appears as visible again instead of maintaining its hidden status.

## Root Cause Analysis

The issue was identified in the backend API merging logic in `/home/nut/fingerprint-time-logger/app/api/consolidated_employees.py`:

### Primary Issues
1. **Database Query Filtering**: Lines 237-243 were pre-filtering database employees based on `include_hidden` status BEFORE merging with ZK device data
2. **Lost Database Records**: When `include_hidden=false`, hidden employees were excluded from the `db_employees` lookup dictionary
3. **Fallback to ZK Data**: Employees like #3 get treated as "ZK device only" and get hardcoded `is_hidden: false` (line 284)

### Flow Breakdown
```
1. User clicks "Hide" on employee 3 → API creates database record with is_hidden: true
2. User clicks "Show Hidden" button → loadEmployees() called with from_device=true
3. Backend merges ZK device data with database, but employee 3 wasn't in database query results
4. Employee 3 gets treated as "ZK device only" → gets is_hidden: false hardcoded
```

## Fixes Applied

### Backend Fix
**File**: `/home/nut/fingerprint-time-logger/app/api/consolidated_employees.py`
**Lines**: 235-240

```python
# OLD (BROKEN):
db_employees = {}
query = db.query(Employee)
if not include_hidden:
    query = query.filter(Employee.is_hidden == False)  # ❌ Pre-filtering
if not include_inactive:
    query = query.filter(Employee.is_active == True)

# NEW (FIXED):
# Load ALL employees first, apply filtering after merging to preserve hidden state
db_employees = {}
query = db.query(Employee)
# Filtering now happens after merging, not before
```

### Frontend Fix
**File**: `/home/nut/fingerprint-time-logger/static/nickname-management.html`
**Lines**: 428-442

```javascript
// OLD (BROKEN):
function getFilteredEmployees() {
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    return employees.filter(employee => {
        const badgeMatch = employee.badge_number.toLowerCase().includes(searchTerm);
        const nameMatch = (employee.display_name || '').toLowerCase().includes(searchTerm);
        return badgeMatch || nameMatch;  // ❌ No hidden status filtering
    });
}

// NEW (FIXED):
function getFilteredEmployees() {
    const searchTerm = document.getElementById('searchInput').value.toLowerCase();
    return employees.filter(employee => {
        // Filter by search term
        const badgeMatch = employee.badge_number.toLowerCase().includes(searchTerm);
        const nameMatch = (employee.display_name || '').toLowerCase().includes(searchTerm);
        const searchMatch = badgeMatch || nameMatch;

        // Filter by hidden status ✅
        const hiddenMatch = showHidden || !employee.is_hidden;

        return searchMatch && hiddenMatch;
    });
}
```

## Testing Results

### ✅ Successful Tests
- **Backend Logic**: Database employee loading fixed to prevent pre-filtering
- **Frontend Logic**: Client-side filtering now respects hidden status
- **API Endpoints**: Hide/show API endpoints work correctly (verified with employee 99999)
- **Basic Filtering**: `include_hidden=false` properly filters out hidden employees

### ❌ Outstanding Issues
- **Database Persistence**: Employee 3 records not persisting correctly in SQLite
- **Merge Logic**: Some edge cases with ZK device + database merging still need investigation
- **Full Flow Verification**: Complete hide → show hidden → hide hidden cycle needs end-to-end testing

## Current Status

### Working
- ✅ Backend prevents pre-filtering of database employees
- ✅ Frontend properly filters by hidden status
- ✅ API endpoints create/update hidden status correctly
- ✅ Basic hide/show functionality works for database employees

### Needs Investigation
- ❌ SQLite database persistence for specific employees (employee #3 case)
- ❌ ZK device + database merge edge cases
- ❌ Container restart database volume persistence verification

## Next Steps

1. **Debug Database Persistence**
   - Investigate why employee 3 records aren't being saved to SQLite
   - Check database volume mounting and transaction commit issues
   - Verify hidden API endpoint database operations

2. **End-to-End Testing**
   - Test complete hide → show hidden → hide hidden cycle
   - Verify with both database-only and ZK device employees
   - Test edge cases with employees that exist in only one source

3. **Production Validation**
   - Test on actual production environment with real users
   - Monitor for any additional edge cases or persistence issues
   - Validate fix works across browser cache refresh cycles

## Technical Context

### API Endpoints
- `PUT /api/employees/{badge_number}/hidden` - Update employee hidden status
- `GET /api/employees/?from_device=true&include_hidden={bool}` - Get merged employee list

### Key Files
- `/home/nut/fingerprint-time-logger/app/api/consolidated_employees.py` - Backend merging logic
- `/home/nut/fingerprint-time-logger/static/nickname-management.html` - Frontend management UI
- `/home/nut/fingerprint-time-logger/static/js/config.js` - API configuration and URL generation

### Database Schema
- `employees` table with `badge_number`, `is_hidden`, `is_active` columns
- SQLite database mounted as volume: `./database:/app/database`

## Related Issues

This fix also resolves similar issues that could occur with:
- Employee active/inactive status persistence
- Any other employee attributes that need to persist across ZK device refreshes
- General data merging between ZK device and database sources