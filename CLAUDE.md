# CLAUDE.md

Modern fingerprint time logger for ZKTeco biometric devices with Thai localization support.

## Quick Start

```bash
# Application Management (consolidated script)
./scripts/manage-app.sh start      # Start the application
./scripts/manage-app.sh stop       # Stop the application
./scripts/manage-app.sh restart    # Restart the application
./scripts/manage-app.sh status     # Check comprehensive status
./scripts/manage-app.sh health     # Quick health check
./scripts/manage-app.sh logs       # Show application logs
./scripts/manage-app.sh deploy     # Deploy with fresh build
./scripts/manage-app.sh backup     # Backup database

# Application URLs (after starting):
# Dashboard: http://localhost:5000
# API Docs:  http://localhost:5000/docs
# Status:    http://localhost:5000/status
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Database migrations
alembic -c database/alembic.ini upgrade head

# Run tests
python3 -m pytest -v

# Run E2E tests
./scripts/run_e2e_tests.sh
```

## Architecture

- **Docker Container**: Containerized deployment with Docker Compose
- **Unified FastAPI Server (5000)**: All functionality in single process
- **Static Dashboard**: HTML/CSS/JS served by FastAPI with WebSocket updates
- **SQLite Database**: Local storage with Alembic migrations (volume mounted)
- **ZKTeco Integration**: pyzk library for device communication
- **Background Tasks**: Auto-import fingerprint logs every 30 minutes

## Key Models

- **Device**: ZKTeco device config (IP, port, password, sync status)
- **Employee**: Unified staff records (badge, English/Thai names, status, visibility)
- **AttendanceRecord**: Time punches with validation and sync status
- **JobRole**: Employee role definitions with schedule support

## Working Features

✅ **Device connectivity** - ZKTeco fingerprint device integration  
✅ **Attendance tracking** - Real-time punch data collection  
✅ **Employee management** - Unified employee records with Thai/English names  
✅ **Nickname management** - Easy display name updates  
✅ **Status management** - Employee active/inactive and hidden/visible toggles  
✅ **CSV export** - Comprehensive data export capabilities  
✅ **Dashboard UI** - Real-time web dashboard with WebSocket updates  
✅ **Calendar view** - Monthly attendance visualization  
✅ **Auto-import** - Background fingerprint log synchronization  
✅ **System monitoring** - Health checks and diagnostics  

## API Endpoints

### Core APIs
- **Attendance**: `/api/attendance/` - Records, summaries, calendar data, CSV export
- **Devices**: `/api/devices/` - Status, connection, time sync, diagnostics
- **Employees**: `/api/employees/` - Management, Thai names, roles, statistics
- **Export**: `/api/export/` - CSV exports, reports, quick exports
- **System**: `/api/system/` - Health monitoring, logs, metrics

### Frontend Pages
- **Dashboard**: `/` - Real-time attendance display
- **Status**: `/status` - System health and monitoring
- **Device Status**: `/device-status` - Device connectivity
- **Nickname Management**: `/nickname-management` - Employee names
- **Export**: `/export` - Data export interface
- **API Documentation**: `/docs` - Interactive Swagger UI

## Development Commands

```bash
# Docker development
docker-compose up -d --build
docker logs fingerprint-time-logger
docker exec -it fingerprint-time-logger bash

# Direct development (without Docker)
uvicorn app.main_unified:app --reload --port 5000

# Database (inside container or locally)
alembic -c database/alembic.ini revision --autogenerate -m "description"
alembic -c database/alembic.ini upgrade head

# Tests
python3 -m pytest -v
```

## Environment

```env
DATABASE_URL=sqlite:///./database/attendance.db
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
```

## Recent Improvements

### Codebase Cleanup (Jan 2025)
- **35% reduction** in backend code complexity
- **Removed unused code**: 42 unused API endpoints, models, and schemas
- **Unified Employee Model**: Consolidated Employee and EmployeeThaiName tables
- **Simplified Architecture**: Eliminated enterprise complexity for focused functionality

### Key Features Added
- **Auto-Import System**: 30-minute background sync of fingerprint logs
- **ZK Device Integration**: Seamless device data integration with employee management
- **Employee Status Features**: Active/inactive and hidden/visible toggles
- **Enhanced Monitoring**: Comprehensive system health checks and diagnostics

## E2E Testing Framework

### Framework Components
- **Page Objects**: Dashboard, Employee Management, System Status
- **Workflows**: Employee lifecycle, attendance tracking, real-time updates
- **Browser Support**: Chromium, Firefox, WebKit with mobile viewports
- **Thai Localization**: Unicode validation, Bangkok timezone
- **WebSocket Testing**: Real-time functionality validation

### Test Execution
```bash
# Consolidated testing script
./scripts/test-verify.sh all            # All tests and quality checks
./scripts/test-verify.sh e2e            # E2E tests only

# E2E-specific (legacy, still available)
./scripts/run_e2e_tests.sh smoke       # Quick smoke tests
./scripts/run_e2e_tests.sh workflows   # Complete workflow testing
./scripts/run_e2e_tests.sh performance # Performance and load testing
./scripts/run_e2e_tests.sh --browser firefox # Cross-browser testing
```

## Documentation

- **API Reference**: `docs/API_REFERENCE.md` - Complete API documentation
- **Database Schema**: `database/database_schema.md` - ERD and table documentation
- **System Architecture**: `docs/SYSTEM_ARCHITECTURE.md` - Technical architecture
- **Developer Guide**: `docs/DEVELOPER_GUIDE.md` - Setup and development guide

## Testing

### Comprehensive Test Suite
- **323 Unit Tests**: Complete unit test coverage with zero failures
- **E2E Testing Framework**: Playwright-based browser automation
- **Integration Tests**: Full workflow testing including Thai localization
- **Performance Testing**: Load testing and performance validation

### Running Tests
```bash
# Testing and Verification (consolidated script)
./scripts/test-verify.sh all            # Complete test suite
./scripts/test-verify.sh unit           # Unit tests only
./scripts/test-verify.sh integration    # Integration tests
./scripts/test-verify.sh e2e            # E2E tests (requires app running)
./scripts/test-verify.sh security       # Security tests
./scripts/test-verify.sh quality        # Code quality checks
./scripts/test-verify.sh performance    # Performance tests
./scripts/test-verify.sh report         # Generate test report

# Test options
./scripts/test-verify.sh all --coverage 85 --browser firefox --parallel

# Legacy command still works:
python3 -m pytest -v
```

### Test Categories
- **Smoke Tests**: Critical path validation
- **Workflow Tests**: Complete user journeys (employee lifecycle, attendance tracking)
- **Integration Tests**: Device connectivity, WebSocket real-time, Thai Unicode
- **Performance Tests**: Page load times, sync operations, large datasets

## Development Workflow

**Commit Strategy**: Follow `COMMIT_STRATEGY.md` for granular commits at every development step.

**Testing**: Always run tests before commits:
1. `./scripts/test-verify.sh unit` (unit tests)
2. `./scripts/test-verify.sh e2e` (critical E2E paths)
3. `./scripts/test-verify.sh all` (comprehensive testing - recommended)

**Focus**: Simple, functional single-user system optimized for reliability and ease of use.