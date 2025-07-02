# CLAUDE.md

Fingerprint time logger for ZKTeco biometric devices.

## Quick Start

```bash
# Start application
./scripts/start.sh

# Use application
# Dashboard: http://localhost:5000
# API: http://localhost:8000

# Stop application  
./scripts/stop.sh
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Database migrations
alembic upgrade head

# Run tests
python3 -m pytest
```

## Architecture

- **FastAPI API (8000)**: Attendance data, device management
- **Flask Dashboard (5000)**: Web interface
- **SQLite Database**: Local storage
- **ZKTeco Integration**: pyzk library

## Key Models

- **Device**: ZKTeco device config
- **Employee**: Staff records  
- **AttendanceRecord**: Time punches
- **EmployeeThaiName**: Name mappings
- **WorkSchedule**: Employee schedules

## Working Features

✅ Device connectivity  
✅ Attendance tracking  
✅ Thai name management  
✅ CSV export  
✅ Dashboard UI  
✅ Calendar view  

## Development Commands

```bash
# API server
uvicorn app.main:app --reload --port 8000

# Dashboard
python dashboard_app.py

# Database
alembic revision --autogenerate -m "description"
alembic upgrade head

# Tests
pytest -v
```

## Environment

```env
DATABASE_URL=sqlite:///./attendance.db
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
```

**Focus**: Simple, functional single-user system.

## Development Workflow

**Commit Strategy**: Follow `COMMIT_STRATEGY.md` for granular commits at every development step.

**Database Schema**: See `database_schema.md` for complete ERD and table documentation.