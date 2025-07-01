# Fingerprint Time Logger

ZKTeco biometric device attendance tracking.

## Quick Start

```bash
./scripts/start.sh    # Start services
```

- Dashboard: http://localhost:5000
- API: http://localhost:8000

## Features

- ZKTeco device integration
- Attendance tracking
- Thai name management  
- Work schedule management
- CSV export
- Real-time dashboard

## Development

```bash
# Install
pip install -r requirements.txt

# Database
alembic upgrade head

# Manual start
uvicorn app.main:app --port 8000
python dashboard_app.py
```

## Files

- `scripts/` - Management scripts
- `app/` - FastAPI application
- `dashboard_app.py` - Flask dashboard
- `attendance.db` - SQLite database

## Documentation

- `QUICK_START.md` - Essential commands
- `scripts/README.md` - Script documentation
- `docs/` - Additional documentation