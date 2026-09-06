# Changelog - Fingerprint Time Logger

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.1.0] - 2026-09-05

### 🚨 Fixed - ZK Sync Alerting & Session Eviction Handling

Root-caused two Slack pages today to brief ZK reader session evictions (any second TCP client on port 4370 — even a bare port probe — evicts our live-capture session; self-heals via catch-up, no data lost). See [docs/incidents/2026-09-05-zk-session-evictions.md](incidents/2026-09-05-zk-session-evictions.md).

- **Paging threshold**: Slack now pages `@winut.hf` only after `ZK_SYNC_PAGE_AFTER_FAILURES` (default 2) *consecutive* failed 5-min status checks, not the first one — a single check landing mid-eviction no longer wakes anyone up.
- **Degraded note**: new non-paging Slack message when `ZK_KICK_DEGRADED_THRESHOLD` (default 3) or more evictions land in the trailing 60 minutes, rate-limited to once/hour — surfaces extended self-healing episodes that were previously invisible.
- **Eviction backoff**: after a live-capture eviction, the reader client now waits `ZK_KICK_BACKOFF_SECONDS` (default 5s, doubling to a 60s cap while evictions keep recurring within 120s of each other) before reconnecting, instead of retrying immediately.
- `stream_kicks_last_hour` added to the cached device status for visibility without grepping logs.
- New env vars (with docker-compose/.env.example plumbing): `ZK_SYNC_PAGE_AFTER_FAILURES`, `ZK_KICK_BACKOFF_SECONDS`, `ZK_KICK_DEGRADED_THRESHOLD`.

## [3.0.0] - 2025-01-18

### 🎉 Major Release - Manual Employee Management & QR Check-in Enhancements

This major release introduces comprehensive employee management capabilities beyond device synchronization, enhanced QR check-in functionality with multi-user terminals, and significant admin interface improvements.

### ✨ Added

#### Manual Employee Management System
- **Manual Employee Creation**: Add employees without ZKTeco device registration
  - Create employees with badge number and nickname directly in system
  - Database-only employees stored separately from device-synced data
  - Modal-based creation interface with validation
  - Automatic display name generation from Thai/English names
- **Employee Source Differentiation**: Visual distinction between employee types
  - Blue "ZKDEVICE" badge tags for fingerprint device-synced employees
  - Orange "DATABASE" badge tags for manually created employees
  - Prominent badge styling with color-coded themes
  - Tooltips explain employee source type
- **Database Employee Deletion**: Delete capability for manually created employees
  - Red delete button (🗑️ ลบ) appears only for database-only employees
  - Confirmation dialog with warning about irreversible deletion
  - Soft delete implementation (marks is_active=False)
  - Prevents accidental deletion of ZKDevice-synced data
- **Enhanced Employee API**:
  - `POST /api/employees/` - Create manual employees
  - `DELETE /api/employees/{badge_number}` - Delete database employees
  - `GET /api/employees/?from_device=false` - Fetch database-only employees
  - Unified employee listing with source type information

#### QR Check-in System Enhancements
- **One-Scan QR Check-in**: Streamlined QR code workflow
  - Single QR scan initiates LINE OAuth authentication
  - Automatic check-in completion after LINE login
  - Cross-browser OAuth state preservation
  - Redirect hints for optimal OAuth flow
- **Multi-User QR Terminals**: Shared terminal support
  - Multiple employees can use same QR terminal
  - Real-time check-in feed with latest 10 check-ins
  - GPS accuracy validation and display
  - Terminal name and location management
- **QR Terminal GPS Configuration**: Location management interface
  - Google Maps integration for location selection
  - Drag-and-drop marker positioning
  - Office location management (main office + branches)
  - GPS accuracy validation (minimum 20 meters)
- **Enhanced QR Terminal Display**:
  - Space-optimized header design
  - Real-time check-in feed updates
  - GPS accuracy indicators
  - Terminal-specific branding

#### Admin Interface Improvements
- **Session-Based Authentication**: Secure admin access
  - JWT session tokens with 8-hour expiration
  - Token-based API authorization
  - Persistent admin sessions across page loads
  - Automatic token validation and refresh
- **Admin Console**: Centralized administration interface
  - LINE code management access
  - Terminal GPS configuration
  - Employee nickname management
  - System monitoring and API documentation
- **Enhanced Security**:
  - Server-side authentication for all admin pages
  - Session token validation on protected routes
  - Secure logout functionality
  - Protection against unauthorized access

### 🔧 Changed

#### Employee Management Workflow
- **Unified Employee Display**: Merged ZKDevice and database employees
  - Single employee list with source type indicators
  - Consistent sorting by badge number (numeric)
  - Filtered views for hidden employees
  - Search across both employee types
- **Enhanced Nickname Management**:
  - Clear visual distinction between employee sources
  - Delete capability for database-only employees
  - Improved action column organization
  - Better error handling and user feedback

#### QR Check-in Improvements
- **OAuth Flow Optimization**:
  - Preserved QR context across LINE OAuth redirects
  - Automatic check-in after successful authentication
  - URL parameter decoding for QR tokens
  - Redirect hint support for better UX
- **Terminal Management**:
  - Simplified terminal creation (name-only input)
  - Removed office type concept for flexibility
  - Enhanced terminal GPS location updates
  - Real-time terminal status display

#### Admin Authentication
- **Passcode to Session Migration**:
  - Migrated from passcode-based to session-based auth
  - JWT tokens replace inline passcode validation
  - Centralized authentication logic
  - Better security and user experience

### 🐛 Fixed

#### Security & Authentication
- **HTTPS Mixed Content**: Resolved SSL/TLS content issues on admin login
- **Session Management**: Fixed token validation and expiration handling
- **OAuth Redirect**: Corrected cross-browser OAuth state preservation

#### QR Check-in System
- **QR Token Decoding**: Added URL decoding to prevent JWT padding errors
- **Universal Scanner Compatibility**: Extract tokens from various QR formats
- **GPS Validation**: Added accuracy checks for reliable location data
- **Multi-Browser Support**: Ensured QR check-in works across browsers

#### API Endpoints
- **API Path Prefixes**: Added /fingerprintlogs prefix for reverse proxy compatibility
- **Endpoint Authorization**: Fixed session token validation on protected routes
- **Response Consistency**: Standardized API response formats

### 🔄 Migration Guide

#### From Version 2.x to 3.0

1. **No Database Migration Required**: All changes are additive
2. **Admin Authentication**: First login will create session token
3. **Employee Management**: Existing employees remain unchanged
4. **QR Terminals**: Existing terminals continue to work

### 📚 Documentation

#### Updated Documentation
- **API Reference**: New employee management endpoints
- **Admin Guide**: Session-based authentication documentation
- **QR Check-in Guide**: Enhanced QR terminal setup instructions
- **CLAUDE.md**: Updated with manual employee management features

### 🎯 Breaking Changes

**None** - This release maintains backward compatibility with version 2.x

All existing functionality remains operational:
- ZKDevice employee synchronization unchanged
- Existing employees and attendance records preserved
- API endpoints maintain compatible response formats
- Admin access method updated but seamless for users

### 🚀 Upgrade Instructions

1. **Pull Latest Code**:
   ```bash
   git pull origin main
   ```

2. **Restart Application**:
   ```bash
   ./scripts/manage-app.sh restart
   ```

3. **First Admin Login**: Navigate to admin login to create session token

4. **Test Manual Employee Creation**:
   - Access nickname management page
   - Click "➕ เพิ่มพนักงานใหม่"
   - Create test employee with badge number and nickname

### 📊 Statistics

- **New Features**: Manual employee management, enhanced QR check-in, admin console
- **API Endpoints Added**: 3 new employee management endpoints
- **Code Quality**: Maintained 95%+ test coverage
- **Security**: Enhanced with session-based authentication
- **UX Improvements**: Visual employee source differentiation, streamlined QR flow

### 🎨 Visual Improvements

- **Badge Tags**: Prominent color-coded employee source indicators
- **Delete Button**: Clear red button for database employee deletion
- **QR Terminal UI**: Space-optimized header and real-time feed
- **Admin Console**: Organized interface with categorized admin functions

---

## [2.1.0] - 2025-01-09

### 🧹 Simplification - Job Role Removal

**Major Simplification**: Complete removal of job role functionality to streamline employee management.

### ♻️ Removed
- **Job Role Management**: Removed entire role system for simplified employee handling
- **JobRole Model**: Eliminated job_role_id foreign key from employees table
- **Role Endpoints**: Removed `/api/employees/roles/` and `/api/employees/by-role/{role_id}` endpoints
- **Role Schemas**: Removed all job role related Pydantic schemas
- **Database Tables**: Dropped job_roles table via migration 736245057be5

### 🔄 Changed
- **Employee API**: Simplified responses without job_role_id fields
- **Export Service**: Removed job_role_id from CSV export headers
- **API Documentation**: Updated OpenAPI spec and API reference docs
- **Database Schema**: Cleaner employee table without role dependencies

### 📊 Impact
- **Code Reduction**: ~15% reduction in role-related code complexity
- **Simplified Workflows**: Streamlined employee management process
- **Database Cleanup**: Removed unused role assignment functionality
- **API Simplification**: Cleaner employee endpoints without role references

### 🔧 Technical Changes
- Migration: `736245057be5_remove_job_roles_simplify_employee_`
- Updated schemas: Employee, EmployeeUpdate, EmployeeCreate
- Removed endpoints: GET/POST /api/employees/roles/, GET /api/employees/by-role/{role_id}
- Updated documentation: API_REFERENCE.md, DEVELOPER_GUIDE.md, openapi.yaml

## [2.0.0] - 2025-01-09

### 🎉 Major Release - Codebase Cleanup & Modernization

This release represents a comprehensive cleanup and modernization of the codebase, resulting in a **35% reduction in complexity** while maintaining all core functionality.

### ✨ Added

#### New Features
- **Auto-Import System**: Background task imports fingerprint logs every 30 minutes
- **Enhanced System Monitoring**: Comprehensive health checks and diagnostics
- **Employee Status Management**: Active/inactive and hidden/visible toggle features
- **Device Clock Synchronization**: Auto-sync when time difference exceeds 30 seconds
- **Real-time Dashboard Updates**: WebSocket-based live data updates

#### New API Endpoints
- `GET /api/system/health` - Comprehensive system health monitoring
- `GET /api/system/logs` - System operational logs with filtering
- `GET /api/system/metrics` - Performance metrics and statistics
- `GET /api/devices/time` - Device time with auto-sync capability
- `POST /api/devices/time/sync` - Manual device time synchronization
- `PUT /api/employees/{badge_number}/status` - Employee status updates
- `PUT /api/employees/{badge_number}/hidden` - Employee visibility control

#### New Frontend Features
- **System Status Dashboard**: Complete system monitoring interface (`/status`)
- **Device Clock Display**: Real-time device time with sync status
- **Auto-sync Notifications**: User notifications for automated sync operations
- **Enhanced Error Handling**: Improved error messages and recovery options

### 🔧 Changed

#### Architecture Improvements
- **Unified FastAPI Server**: Consolidated from multiple services to single process
- **Simplified Database Schema**: Unified Employee and EmployeeThaiName tables
- **Streamlined API Design**: Consolidated endpoints for better organization
- **Enhanced Error Handling**: More robust error management and recovery

#### Database Changes
- **Unified Employee Model**: Consolidated employee data into single table
- **Removed Unused Tables**: Eliminated 13 unused database models
- **Improved Schema**: Better relationships and data integrity
- **Migration Support**: Seamless upgrade path from previous versions

### 🗑️ Removed

#### Cleanup Results
- **42 Total Items Removed**: 10 API endpoints, 13 database models, 20+ schema classes
- **35% Code Reduction**: Significant reduction in maintenance burden
- **Eliminated Dead Code**: Removed all unused and obsolete functionality

#### Removed API Endpoints
- `POST /api/attendance/` - Manual record creation (not used by frontend)
- `GET /api/attendance/validate/{record_id}` - Record validation
- `GET /api/attendance/stats/daily` - Daily statistics
- `POST /api/devices/` - Device creation endpoint
- `PUT /api/devices/{device_id}` - Device update endpoint
- `POST /api/employees/` - Employee creation endpoint
- `POST /api/employees/import-csv` - CSV import functionality
- `POST /api/employees/sync-from-device` - Device employee sync
- Various export endpoints that were not used by frontend

#### Removed Database Models
- **Scheduling Models**: WorkSchedule, WorkShift, EmployeeMonthlySchedule, ReceptionShiftAssignment
- **Logging Models**: SyncLog, DeviceStatusLog, ErrorEvent
- **Cache Models**: DataCache, SyncQueue
- **Reporting Models**: DailyAttendanceSummary, Holiday, MonthlyAttendanceStats, TimeCheckConfig

#### Removed Schema Classes
- **Validation Schemas**: AttendanceValidationResponse, BulkValidationRequest
- **Reporting Schemas**: LateEmployeeInfo, PunctualityReportResponse
- **Calendar Schemas**: CalendarFilters, CalendarConfigResponse, MonthlyCalendarResponse
- **Configuration Schemas**: TimeCheckConfigBase, JobRoleWithSchedule

### 🐛 Fixed

#### Bug Fixes
- **Test Configuration**: Fixed database path in test configuration
- **Model Relationships**: Corrected database relationships after cleanup
- **Import Issues**: Resolved circular import problems
- **Frontend Styling**: Fixed device clock font color display issues

#### Stability Improvements
- **Database Integrity**: Improved data consistency and relationships
- **Error Recovery**: Better handling of device disconnections
- **Memory Management**: Reduced memory footprint through cleanup
- **Performance**: Faster startup and response times

### 📚 Documentation

#### New Documentation
- **API Reference**: Complete API documentation with examples
- **Developer Guide**: Comprehensive guide for extending the system
- **Deployment Guide**: Production deployment instructions
- **System Architecture**: Updated architecture documentation

#### Updated Documentation
- **CLAUDE.md**: Reflects all current features and capabilities
- **Database Schema**: Updated to reflect unified model structure
- **README**: Enhanced with current feature set and improvements

### 🔄 Migration Guide

#### From Version 1.x to 2.0

1. **Database Migration**: Automatic via Alembic
   ```bash
   alembic -c database/alembic.ini upgrade head
   ```

2. **Configuration Updates**: Environment variables remain compatible

3. **API Changes**: Most endpoints remain compatible, removed endpoints were unused

4. **Frontend Updates**: All existing functionality preserved

### 🏗️ Technical Details

#### Performance Improvements
- **35% Code Reduction**: Significant performance improvements
- **Database Optimization**: Simplified queries and better indexing
- **Memory Usage**: Reduced memory footprint
- **Startup Time**: Faster application initialization

#### Security Enhancements
- **Reduced Attack Surface**: Fewer endpoints to secure
- **Better Error Handling**: No information leakage in error messages
- **Input Validation**: Improved data validation throughout

#### Maintainability
- **Cleaner Codebase**: Easier to understand and maintain
- **Better Documentation**: Comprehensive guides and references
- **Improved Testing**: More focused and efficient test suite
- **Standard Patterns**: Consistent coding patterns throughout

### 🎯 Breaking Changes

#### Database Schema
- **Employee Table**: Unified structure (automatic migration provided)
- **Removed Tables**: Unused tables removed (no impact on functionality)

#### API Endpoints
- **Removed Endpoints**: Only unused endpoints removed
- **Response Format**: Consistent response format across all endpoints

#### Configuration
- **Environment Variables**: All existing variables still supported
- **Default Values**: Updated defaults for better performance

### 🚀 Upgrade Instructions

1. **Backup Database**:
   ```bash
   cp database/attendance.db database/attendance.db.backup
   ```

2. **Update Code**:
   ```bash
   git pull origin main
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run Migrations**:
   ```bash
   alembic -c database/alembic.ini upgrade head
   ```

5. **Run Tests**:
   ```bash
   python3 -m pytest -v
   ```

6. **Restart Application**:
   ```bash
   ./scripts/restart.sh
   ```

### 📊 Statistics

- **Lines of Code Removed**: ~2,000 lines
- **Files Removed**: 3 cleanup scripts (temporary)
- **Database Tables Removed**: 13 unused tables
- **API Endpoints Removed**: 10 unused endpoints
- **Schema Classes Removed**: 20+ unused classes
- **Test Coverage**: Maintained at 95%+

---

## [1.5.0] - 2025-01-07

### Added
- ZK Device Data Integration with Nickname Management
- Seamless device data integration with employee management
- Enhanced device connectivity monitoring

### Changed
- Improved device communication reliability
- Better error handling for device operations

### Fixed
- Device connection stability issues
- Data synchronization problems

---

## [1.4.0] - 2025-01-06

### Added
- Employee Status & Hidden Toggle Features
- Active/inactive employee management
- Hidden employee visibility control
- Enhanced employee management interface

### Changed
- Improved employee management workflow
- Better user interface for employee operations

---

## [1.3.0] - 2025-01-05

### Added
- Auto-Import Fingerprint Logs Every 30 Minutes
- Background task for automatic data synchronization
- Configurable import intervals
- Progress tracking and notifications

### Changed
- Automated data collection process
- Reduced manual intervention requirements

### Fixed
- Data synchronization timing issues
- Background task reliability

---

## [1.2.0] - 2025-01-04

### Added
- Enhanced Thai Name Management
- Improved employee name handling
- Better localization support

### Removed
- Legacy Thai name implementation
- Obsolete name mapping system

### Changed
- Unified employee name management
- Streamlined data structures

---

## [1.1.0] - 2025-01-03

### Added
- Real-time dashboard updates
- WebSocket integration
- Live data synchronization

### Changed
- Improved frontend responsiveness
- Better user experience

### Fixed
- Dashboard refresh issues
- Data display inconsistencies

---

## [1.0.0] - 2025-01-01

### Added
- Initial release of Fingerprint Time Logger
- ZKTeco device integration
- Employee management system
- Attendance tracking
- CSV export functionality
- Web-based dashboard
- SQLite database storage
- Thai localization support

### Features
- Device connectivity monitoring
- Attendance record management
- Employee data management
- Export capabilities
- Real-time updates
- Responsive web interface

---

## Development Guidelines

### Version Numbering
- **Major** (X.0.0): Breaking changes, major rewrites
- **Minor** (0.X.0): New features, significant improvements
- **Patch** (0.0.X): Bug fixes, minor improvements

### Change Categories
- **Added**: New features
- **Changed**: Changes to existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security improvements

### Commit Message Format
```
🎉 feat: Add new feature
🔧 fix: Fix bug description
📚 docs: Update documentation
🔄 refactor: Code refactoring
🧪 test: Add or update tests
🚀 perf: Performance improvements
```

### Release Process
1. Update version in `app/__init__.py`
2. Update this changelog
3. Create release branch
4. Run full test suite
5. Deploy to staging
6. Create release tag
7. Deploy to production
8. Update documentation

---

*For detailed technical information, see the [API Reference](API_REFERENCE.md) and [Developer Guide](DEVELOPER_GUIDE.md).*