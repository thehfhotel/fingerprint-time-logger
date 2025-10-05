# CLAUDE.md

Modern fingerprint time logger for ZKTeco biometric devices with Thai localization support.

## Quick Start

```bash
# Interactive Scripts (NEW) - Guided menus for easy operation
./scripts/manage-app.sh            # Interactive application management with Docker Bake
./scripts/test-suite-console.sh    # Enhanced testing console with comprehensive logging

# Direct Commands - For automation and CI/CD with Docker Bake Support
./scripts/manage-app.sh start                    # Start with auto-detected build method (Bake/Compose)
./scripts/manage-app.sh start --build-method bake # Start with Docker Bake build
./scripts/manage-app.sh stop                     # Stop the application
./scripts/manage-app.sh restart --no-build-cache # Restart with fresh build
./scripts/manage-app.sh status                   # Check comprehensive status
./scripts/manage-app.sh health                   # Quick health check
./scripts/manage-app.sh logs                     # Show application logs
./scripts/manage-app.sh deploy --build-target fingerprint-logger-prod # Deploy optimized build
./scripts/manage-app.sh backup                   # Backup database

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

# Docker Build (Enhanced with Bake)
./scripts/build-with-bake.sh              # Optimized Docker Bake build
./scripts/build-with-bake.sh --dev        # Development build with tools
./scripts/build-with-bake.sh --prod       # Production optimized build
./scripts/build-comparison.sh             # Compare build performance

# Standard Docker Commands
docker compose build                      # Standard build (supports Bake delegation)
docker compose up -d                      # Start with Docker Compose

# Run tests
python3 -m pytest -v                    # Standard test execution
python3 -m pytest -n auto               # Parallel test execution (70% faster)
python3 -m pytest -n 4                  # Parallel with 4 specific workers
python3 -m pytest tests/unit/ -n auto   # Parallel unit tests only

# Interactive Testing & Verification
./scripts/test-suite-console.sh    # Enhanced testing console with comprehensive logging

# Direct Testing Commands
./scripts/test-suite-console.sh setup     # Setup testing infrastructure
./scripts/test-suite-console.sh all       # Complete test suite
./scripts/test-suite-console.sh e2e       # E2E tests only
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
✅ **GPS location management** - Google Maps integration for QR terminal locations
✅ **Multi-office support** - Main office and branch office GPS configuration  

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
- **GPS Terminal Admin**: `/admin/terminal-gps` - QR terminal GPS location management with Google Maps
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

# Testing with integrated test-suite-console.sh
./scripts/test-suite-console.sh all                    # Complete test suite
./scripts/test-suite-console.sh unit                   # Unit tests only
./scripts/test-suite-console.sh integration            # Integration tests (parallel)
./scripts/test-suite-console.sh e2e                    # E2E tests (parallelized)
./scripts/test-suite-console.sh e2e --browser firefox  # E2E with specific browser

# Legacy testing
python3 -m pytest -v
```

## Environment

```env
DATABASE_URL=sqlite:///./database/attendance.db
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
```

## Recent Improvements

### Unit Test Parallelization (Jan 2025)
- **70% faster test execution**: Sequential 2m19s → Parallel 41s
- **8-worker auto-detection**: Optimal CPU utilization with `-n auto`
- **Perfect test isolation**: In-memory SQLite databases per test
- **Zero configuration conflicts**: Existing fixtures work seamlessly

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

## Docker Build Optimization

### Bake Build System (Jan 2025)
Enhanced Docker build system using Docker Bake for improved performance and advanced features:

- **Advanced Caching**: Registry-based build cache for faster subsequent builds
- **Multi-stage Optimization**: Separate base, development, and production stages
- **Parallel Builds**: Improved build parallelization compared to standard Compose
- **Build Targets**: Specialized development and production optimized images
- **Platform Support**: Multi-platform build capabilities (linux/amd64, linux/arm64)

### Build Commands
```bash
# Optimized Bake builds
./scripts/build-with-bake.sh              # Standard production build
./scripts/build-with-bake.sh --dev        # Development build with testing tools
./scripts/build-with-bake.sh --prod       # Production optimized build
./scripts/build-comparison.sh             # Performance comparison tool

# Standard builds (with Bake delegation when enabled)
docker compose build                      # Uses Bake when COMPOSE_BAKE=true
export COMPOSE_BAKE=true && docker compose build  # Enable Bake delegation

# Manual Bake commands
docker buildx bake fingerprint-logger     # Direct Bake build
docker buildx bake fingerprint-logger-dev # Development target
```

### Performance Improvements
- **Faster builds**: Enhanced caching and parallelization
- **Better layer reuse**: Multi-stage builds with optimized layer sharing
- **Registry caching**: Shared cache for team development
- **Build customization**: Environment-specific optimizations

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
./scripts/test-suite-console.sh all            # All tests and quality checks
./scripts/test-suite-console.sh e2e            # E2E tests only

# Enhanced testing options
./scripts/test-suite-console.sh setup --browser firefox    # Setup with custom browser
./scripts/test-suite-console.sh e2e --parallel             # Parallel E2E execution
./scripts/test-suite-console.sh all --coverage 90          # High coverage threshold
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
./scripts/test-suite-console.sh all            # Complete test suite
./scripts/test-suite-console.sh unit           # Unit tests only
./scripts/test-suite-console.sh integration    # Integration tests
./scripts/test-suite-console.sh e2e            # E2E tests (requires app running)
./scripts/test-suite-console.sh security       # Security tests
./scripts/test-suite-console.sh quality        # Code quality checks
./scripts/test-suite-console.sh performance    # Performance tests
./scripts/test-suite-console.sh report         # Generate test report

# Test options
./scripts/test-suite-console.sh all --coverage 85 --browser firefox --parallel

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
1. `./scripts/test-suite-console.sh unit` (unit tests)
2. `./scripts/test-suite-console.sh e2e` (critical E2E paths)
3. `./scripts/test-suite-console.sh all` (comprehensive testing - recommended)

**Focus**: Simple, functional single-user system optimized for reliability and ease of use.