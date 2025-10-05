# Fingerprint Time Logger

Modern attendance tracking system for ZKTeco biometric devices with Thai localization, QR check-in, and LINE authentication.

## Quick Start

```bash
# Start application with interactive menu
./scripts/manage-app.sh

# Direct start (recommended)
./scripts/manage-app.sh start

# Application URLs
# Dashboard: http://localhost:5000
# API Docs:  http://localhost:5000/docs
# Status:    http://localhost:5000/status
```

## Features

### Core Attendance System
- ✅ ZKTeco fingerprint device integration
- ✅ Real-time attendance tracking with WebSocket updates
- ✅ Auto-import background sync (30-minute intervals)
- ✅ Monthly calendar view with Bangkok timezone
- ✅ Comprehensive CSV export

### QR Check-in System
- ✅ LINE OAuth authentication with persistent login
- ✅ Smart callback routing (auto-redirect for linked accounts)
- ✅ GPS location management with Google Maps
- ✅ Multi-office support (main office + branches)
- ✅ Browser localStorage GPS persistence

### Employee Management
- ✅ Thai/English name support
- ✅ Nickname management
- ✅ Active/inactive status toggles
- ✅ Hidden/visible employee filtering

### Data & Monitoring
- ✅ Health checks and system diagnostics
- ✅ Device status monitoring
- ✅ Attendance summaries and reports
- ✅ WebSocket real-time updates

## Architecture

- **Single FastAPI Server (port 5000)**: Unified backend with static file serving
- **SQLite Database**: Local storage with Alembic migrations
- **Docker Container**: Containerized deployment with Docker Compose/Bake
- **WebSocket**: Real-time dashboard updates
- **pyzk**: ZKTeco device integration library

## Development

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Git

### Setup

```bash
# Clone repository
git clone https://github.com/jwinut/fingerprint-time-logger.git
cd fingerprint-time-logger

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic -c database/alembic.ini upgrade head

# Start application
./scripts/manage-app.sh start
```

### Testing

```bash
# Interactive testing console
./scripts/test-suite-console.sh

# Quick test commands
./scripts/test-suite-console.sh all       # Complete test suite
./scripts/test-suite-console.sh unit      # Unit tests only (parallel)
./scripts/test-suite-console.sh e2e       # E2E tests (Playwright)

# Direct pytest (legacy)
python3 -m pytest -v                      # Standard execution
python3 -m pytest -n auto                 # Parallel execution (70% faster)
```

### Docker Build

```bash
# Optimized Docker Bake build
./scripts/build-with-bake.sh              # Production build
./scripts/build-with-bake.sh --dev        # Development build
./scripts/build-comparison.sh             # Performance comparison

# Standard Docker Compose
docker compose build                      # Standard build
docker compose up -d                      # Start containers
```

## Configuration

### Environment Variables

```env
# Database
DATABASE_URL=sqlite:///./database/attendance.db

# ZKTeco Device
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370

# Application
LOG_LEVEL=INFO
```

### Device Configuration

1. Navigate to Device Status: http://localhost:5000/device-status
2. Configure ZKTeco device IP and port
3. Test connection and sync time
4. Enable auto-import for background sync

## Documentation

### Getting Started
- **[CLAUDE.md](CLAUDE.md)** - Developer quick reference and feature overview
- **[Developer Guide](docs/DEVELOPER_GUIDE.md)** - Comprehensive development setup
- **[API Reference](docs/API_REFERENCE.md)** - Complete API documentation

### Deployment
- **[Deployment Guide](docs/DEPLOYMENT_GUIDE.md)** - Production deployment procedures
- **[Nginx Deployment](docs/NGINX_DEPLOYMENT.md)** - Reverse proxy configuration
- **[GPS Location Setup](docs/GPS_LOCATION_SETUP.md)** - QR terminal GPS configuration

### Technical Reference
- **[System Architecture](docs/SYSTEM_ARCHITECTURE.md)** - Architecture overview
- **[Database Schema](database/database_schema.md)** - ERD and table documentation
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions
- **[Changelog](docs/CHANGELOG.md)** - Version history

## Project Structure

```
fingerprint-time-logger/
├── app/                      # FastAPI application
│   ├── api/                  # API endpoints
│   ├── core/                 # Core configuration
│   ├── models/               # Database models
│   ├── schemas/              # Pydantic schemas
│   └── services/             # Business logic
├── database/                 # Database and migrations
│   ├── migrations/           # Alembic migrations
│   └── database_schema.md    # Schema documentation
├── static/                   # Frontend assets
│   ├── css/                  # Stylesheets
│   ├── js/                   # JavaScript
│   └── *.html                # HTML pages
├── scripts/                  # Management scripts
│   ├── manage-app.sh         # Application management
│   └── test-suite-console.sh # Testing console
├── tests/                    # Test suite
│   ├── unit/                 # Unit tests (323 tests)
│   ├── integration/          # Integration tests
│   └── e2e/                  # E2E tests (Playwright)
└── docs/                     # Documentation
```

## Key Technologies

- **Backend**: FastAPI, SQLAlchemy, Alembic, pyzk
- **Frontend**: Vanilla JavaScript, WebSocket, Leaflet (GPS maps)
- **Database**: SQLite with UTC storage, Bangkok timezone display
- **Testing**: pytest, pytest-xdist (parallel), Playwright (E2E)
- **Deployment**: Docker, Docker Compose, Docker Bake
- **Authentication**: LINE OAuth, JWT tokens

## Performance Metrics

- **Test Execution**: 70% faster with parallel execution (2m19s → 41s)
- **Docker Build**: 30-50% faster with Docker Bake caching
- **Code Coverage**: 323 unit tests with zero failures
- **Codebase**: 35% reduction in backend complexity

## Contributing

See [COMMIT_STRATEGY.md](COMMIT_STRATEGY.md) for git commit guidelines.

## License

Proprietary - All rights reserved

## Support

For issues and questions:
- Check [Troubleshooting Guide](docs/TROUBLESHOOTING.md)
- Review [API Reference](docs/API_REFERENCE.md)
- See [Developer Guide](docs/DEVELOPER_GUIDE.md)
