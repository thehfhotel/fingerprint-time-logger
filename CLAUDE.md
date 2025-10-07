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

# Complete Test Suite Runner (RECOMMENDED)
./scripts/run-complete-test-suite.sh              # Run all tests with detailed report
./scripts/run-complete-test-suite.sh --parallel   # Run with parallel execution
./scripts/run-complete-test-suite.sh --verbose    # Run with detailed output

# View latest test report
cat test-reports/test-report-*.txt | tail -100   # View recent report summary
ls -lt test-reports/                              # List all test reports

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

### Core Attendance System
✅ **Device connectivity** - ZKTeco fingerprint device integration
✅ **Attendance tracking** - Real-time punch data collection
✅ **Auto-import** - Background fingerprint log synchronization (30-minute intervals)
✅ **Dashboard UI** - Real-time web dashboard with WebSocket updates
✅ **Calendar view** - Monthly attendance visualization

### Employee Management
✅ **Employee management** - Unified employee records with Thai/English names
✅ **Nickname management** - Easy display name updates
✅ **Status management** - Active/inactive and hidden/visible toggles

### QR Check-in System
✅ **LINE authentication** - OAuth integration with persistent login
✅ **Smart OAuth callback** - Auto-redirect for linked accounts
✅ **QR terminal GPS** - Google Maps integration for location management
✅ **Multi-office support** - Main office and branch office GPS configuration
✅ **GPS persistence** - Browser localStorage caching for instant availability

### Data Management
✅ **CSV export** - Comprehensive data export capabilities
✅ **System monitoring** - Health checks and diagnostics
✅ **Bangkok timezone** - Consistent UTC+7 handling across all features  

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

# Complete Test Suite with Reporting (PRIMARY METHOD)
./scripts/run-complete-test-suite.sh              # All tests + detailed report
./scripts/run-complete-test-suite.sh --parallel   # Parallel execution
./scripts/run-complete-test-suite.sh --verbose    # Detailed output

# After running, examine the report:
cat test-reports/test-report-*.txt | tail -200   # View full summary
ls -lt test-reports/ | head -5                    # List recent reports

# Interactive testing console
./scripts/test-suite-console.sh all                    # Complete test suite
./scripts/test-suite-console.sh unit                   # Unit tests only
./scripts/test-suite-console.sh integration            # Integration tests (parallel)
./scripts/test-suite-console.sh e2e                    # E2E tests (parallelized)
./scripts/test-suite-console.sh e2e --browser firefox  # E2E with specific browser

# Direct pytest commands
python3 -m pytest -v                              # Standard execution
python3 -m pytest -n auto                         # Parallel execution
```

## Environment

```env
DATABASE_URL=sqlite:///./database/attendance.db
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
```

## Recent Improvements (October 2025)

### LINE Authentication & QR Check-in
- **Persistent Login**: JWT tokens remain in localStorage after successful linking
- **Smart OAuth Callback**: Auto-redirect based on account link status
- **GPS Persistence**: Browser localStorage caching for instant location availability
- **Timezone Consistency**: Fixed Bangkok UTC+7 handling across individual attendance and QR check-in

### Testing & Performance
- **323 Unit Tests**: Complete unit test coverage with zero failures
- **70% faster execution**: Parallel testing with pytest-xdist (Sequential 2m19s → Parallel 41s)
- **E2E Framework**: Playwright-based browser automation for critical workflows
- **Test Consolidation**: Enhanced test-suite-console.sh for comprehensive testing

### Architecture & Build
- **Docker Bake Build**: 30-50% faster builds with advanced caching
- **Codebase Cleanup**: 35% reduction in backend complexity
- **Unified Employee Model**: Consolidated Employee and EmployeeThaiName tables
- **Simplified Architecture**: Eliminated enterprise complexity for focused functionality

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

### Core Documentation
- **API Reference**: `docs/API_REFERENCE.md` - Complete API documentation
- **System Architecture**: `docs/SYSTEM_ARCHITECTURE.md` - Technical architecture
- **Developer Guide**: `docs/DEVELOPER_GUIDE.md` - Setup and development guide
- **Database Schema**: `database/database_schema.md` - ERD and table documentation

### Deployment & Operations
- **Deployment Guide**: `docs/DEPLOYMENT_GUIDE.md` - Production deployment procedures
- **Nginx Deployment**: `docs/NGINX_DEPLOYMENT.md` - Reverse proxy setup
- **GPS Location Setup**: `docs/GPS_LOCATION_SETUP.md` - QR terminal GPS configuration
- **Troubleshooting**: `docs/TROUBLESHOOTING.md` - Common issues and solutions

### Development
- **Commit Strategy**: `COMMIT_STRATEGY.md` - Git commit guidelines
- **Test Plan**: `tests/TEST_PLAN_PERSISTENT_LOGIN.md` - LINE persistent login testing
- **Changelog**: `docs/CHANGELOG.md` - Version history and updates

## Testing

### Comprehensive Test Suite (507+ Tests)
- **253 Unit Tests**: Complete unit test coverage
- **133 Integration Tests**: Full workflow and API testing
- **121 E2E Tests**: Playwright-based browser automation
- **Thai Localization**: Unicode validation across all tests
- **Performance Testing**: Load testing and performance validation

### Primary Test Execution Method

**🎯 Complete Test Suite Runner (RECOMMENDED)**
```bash
# Run complete test suite with detailed reporting
./scripts/run-complete-test-suite.sh

# Options:
./scripts/run-complete-test-suite.sh --parallel   # Parallel execution (faster)
./scripts/run-complete-test-suite.sh --verbose    # Detailed output

# Features:
# ✓ Runs ALL tests: Unit, Integration, E2E
# ✓ Continues on errors (captures all results)
# ✓ Categorizes results by test type
# ✓ Generates timestamped reports: test-reports/test-report-YYYYMMDD_HHMMSS.txt
# ✓ Provides pass/fail statistics
# ✓ Includes AI-ready analysis recommendations
```

**📊 Examine Test Reports**
```bash
# View latest report summary
cat test-reports/test-report-*.txt | tail -200

# List all reports
ls -lt test-reports/ | head -10

# View specific report
cat test-reports/test-report-20250107_143022.txt

# Find recent failures
grep -A 3 "FAILED" test-reports/test-report-*.txt | tail -50
```

**Report Structure:**
- **Execution Summary**: Overall statistics and timing
- **Phase 1**: Unit Tests (categorized by module)
- **Phase 2**: Integration Tests (categorized by feature)
- **Phase 3**: E2E Tests (browser automation)
- **Final Summary**: Pass/fail counts, pass rate, recommendations
- **AI Analysis Section**: Structured for Claude AI review

### Alternative Test Methods

**Interactive Console** (for development)
```bash
./scripts/test-suite-console.sh all            # Complete test suite
./scripts/test-suite-console.sh unit           # Unit tests only
./scripts/test-suite-console.sh integration    # Integration tests
./scripts/test-suite-console.sh e2e            # E2E tests (requires app running)
./scripts/test-suite-console.sh security       # Security tests
./scripts/test-suite-console.sh quality        # Code quality checks
```

**Direct pytest** (for specific tests)
```bash
python3 -m pytest -v                                    # All tests
python3 -m pytest tests/unit/test_line_auth_security.py # Specific file
python3 -m pytest -k "test_jwt" -v                      # By pattern
python3 -m pytest -n auto                               # Parallel
```

### Test Categories

**Phase 1: Unit Tests (253 tests)**
- LINE Authentication Security (18 tests)
- Timezone Handling (10 tests)
- Location Service (GPS validation)
- QR Service (token generation/validation)
- Configuration & Cache Busting
- Admin LINE Codes

**Phase 2: Integration Tests (133 tests)**
- Auto-Import Scheduler (9 tests)
- Multi-Office GPS (6 tests)
- QR Check-in API (30+ tests)
- QR Terminal Display (79 tests)
- LINE Auth API Integration
- Export Service Integration

**Phase 3: E2E Tests (121 tests)**
- GPS Persistence (8 tests) - Requires app running
- LINE Persistent Login (9 tests) - Requires app running
- LINE OAuth Flow (11 tests) - Requires app running
- QR Terminal Real-time (12 tests) - Requires app running
- Additional E2E workflows

### Test Report Analysis for Claude AI

When asked to analyze test results:
1. Run: `./scripts/run-complete-test-suite.sh`
2. Read: Latest report from `test-reports/`
3. Analyze: Review "FINAL SUMMARY" and "RECOMMENDATIONS" sections
4. Focus on: Failed categories and root causes
5. Note: E2E failures may indicate app not running (expected)

## Development Workflow

**Commit Strategy**: Follow `COMMIT_STRATEGY.md` for granular commits at every development step.

**Testing**: Always run tests before commits:
1. `./scripts/test-suite-console.sh unit` (unit tests)
2. `./scripts/test-suite-console.sh e2e` (critical E2E paths)
3. `./scripts/test-suite-console.sh all` (comprehensive testing - recommended)

**Focus**: Simple, functional single-user system optimized for reliability and ease of use.