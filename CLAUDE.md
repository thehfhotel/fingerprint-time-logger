# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Simple internal fingerprint time logger** for single super-user management of employee attendance via ZKTeco biometric devices.

### Core Features (Simplified Scope)
1. **Fingerprint Log Retrieval** - Get check-in/check-out time logs from ZK device
2. **Schedule Comparison** - Compare logs to employee work schedules to identify late arrivals and no-shows
3. **Device Time Management** - Check and adjust ZK device time when needed

**Target User**: Single internal super-user (no multi-user authentication needed)

## Quick Start

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Run the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run the dashboard (separate terminal)
python dashboard_app.py
```

### Database Management
```bash
# Initialize database migrations (if not done)
alembic init migrations

# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Downgrade migrations
alembic downgrade -1
```

### Testing
```bash
# Run tests
pytest

# Run tests with async support
pytest -v --asyncio-mode=auto

# Run specific test file
pytest tests/test_filename.py

# Test device connectivity
python scripts/test_device_connection.py <IP_ADDRESS>

# Check attendance data
python scripts/display_attendance.py <IP_ADDRESS>
```

## Documentation Structure

### Primary Documentation
- **`docs/DOCUMENTATION.md`** - Main comprehensive user and developer guide
- **`docs/TECHNICAL_REFERENCE.md`** - System architecture and implementation details
- **`docs/TROUBLESHOOTING.md`** - Problem resolution and maintenance guide
- **`docs/README.md`** - Documentation index and navigation
- **`POC_RESULTS.md`** - ZKTeco device integration proof of concept results

### Scripts and Utilities
- **`scripts/`** - Development, testing, and operational scripts
- **`scripts/README.md`** - Script usage documentation

## Architecture Summary

### Core Components (Simplified)
- **FastAPI API (Port 8000)**: Basic endpoints for attendance data and device management
- **Flask Dashboard (Port 5000)**: Simple monitoring interface for attendance review
- **SQLite Database**: Local file-based storage (sufficient for single-user)
- **ZKTeco Integration**: Device communication via `pyzk` library
- **Schedule Management**: Employee work schedule tracking and comparison

### Database Models (Core Only)
Key models in `app/models/models.py`:
- **Device**: ZKTeco device configuration (IP, port, connection settings)
- **Employee**: Staff records with unique employee IDs and work schedules
- **AttendanceRecord**: Time punch records with employee, device, timestamp
- **WorkSchedule**: Employee work schedules for attendance comparison
- **SyncLog**: Basic device synchronization logging

### Configuration (Simplified)
Settings in `app/core/config.py`:
- SQLite database connection (local file storage)
- ZKTeco device parameters (IP, port, timeout, password)
- Basic API server settings
- Work schedule comparison settings (late threshold, etc.)

## Current Status & Known Issues

### Working Features
✅ Device connectivity and data retrieval  
✅ Basic REST API for attendance data  
✅ Simple dashboard with real-time updates  
✅ Database storage with SQLite  
✅ Device time synchronization  

### Missing Core Features (Priority)
🔄 **Work schedule management** - Employee schedule tracking  
🔄 **Schedule comparison logic** - Identify late arrivals and no-shows  
🔄 **Attendance reporting** - Late/absent employee reports  
🔄 **Bulk schedule import** - CSV import for employee schedules  

### Nice-to-Have (Low Priority)
⚠️ Basic error handling improvements  
⚠️ Simple data export features  
⚠️ Dashboard UI improvements

## Development Guidelines (Simplified)

### Code Quality (Keep Simple)
- Basic type hints for main functions
- Simple validation with Pydantic
- SQLAlchemy for database operations
- Clear naming conventions
- Basic error handling

### Simplified Requirements
- Keep secrets in environment variables
- Basic input validation
- Simple error logging
- Focus on functionality over optimization
- No Redis, Celery, or PostgreSQL needed for single-user deployment

### Performance (Adequate for Single User)
- SQLite is sufficient for internal use
- Basic device connection handling
- Simple synchronous operations are acceptable
- Focus on reliability over speed

## Deployment Notes (Internal Use)

### Single-User Deployment
- SQLite database (single file - sufficient)
- Single machine deployment
- Both API and dashboard on same server
- No scaling or load balancing needed
- Simple backup strategy (copy database file)

## Priority Implementation Plan

### Phase 1: Core Schedule Management (Week 1)
1. **Add WorkSchedule model** - Employee work schedules
2. **Schedule API endpoints** - CRUD for schedules
3. **CSV import functionality** - Bulk schedule import

### Phase 2: Attendance Analysis (Week 2)  
1. **Schedule comparison logic** - Late arrival detection
2. **No-show identification** - Missing attendance detection
3. **Basic reporting endpoints** - Late/absent employee lists

### Phase 3: Dashboard Enhancement (Week 3)
1. **Schedule management UI** - Add/edit schedules in dashboard
2. **Attendance reports UI** - Display late/absent employees
3. **Export functionality** - CSV export of reports

## Requirements and Dependencies

### Core Dependencies (requirements.txt)
- **FastAPI & Uvicorn** - API server and ASGI server
- **Flask & Flask-SocketIO** - Dashboard web interface
- **SQLAlchemy & Alembic** - Database ORM and migrations
- **pyzk** - ZKTeco device communication library
- **Pydantic** - Data validation and settings
- **httpx** - HTTP client for API calls
- **pytest** - Testing framework

### Removed Dependencies (Not Needed for Single-User)
- ~~PostgreSQL (psycopg2-binary)~~ - SQLite sufficient
- ~~Redis~~ - No caching needed
- ~~Celery~~ - No background tasks needed
- ~~WebSockets~~ - Basic SocketIO sufficient

### Environment Variables
```env
# Database
DATABASE_URL=sqlite:///./attendance.db

# ZKTeco Device
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
ZKTECO_PASSWORD=0

# API Settings
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=True
```

**Focus**: Core business logic over complex architecture patterns. Keep it simple and functional for single-user internal use.