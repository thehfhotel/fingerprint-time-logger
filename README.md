# Fingerprint Time Logger

FastAPI-based biometric attendance tracking system that integrates with ZKTeco fingerprint devices.

## Features

- **ZKTeco Device Integration** - Connect to biometric devices via TCP/IP
- **REST API** - Complete CRUD operations for attendance management
- **Real-time Dashboard** - Live attendance monitoring with WebSocket updates
- **Multi-device Support** - Manage multiple fingerprint devices
- **Background Sync** - Automatic synchronization with device data
- **Database Migrations** - Alembic for schema management

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the API Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Run the Dashboard (Optional)
```bash
python dashboard_app.py
```

Access the dashboard at: http://localhost:5000

### 4. Test Device Connection
```bash
python scripts/test_device_connection.py 192.168.100.209
```

## API Documentation

Interactive API docs available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

For detailed API reference, see [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)

## Architecture

The system follows a layered architecture:

```
Frontend (Dashboard) → API Layer → Service Layer → Database
                    ↓
              ZKTeco Devices
```

For complete architecture documentation, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Database Setup

### SQLite (Default)
No setup required - database file created automatically.

### PostgreSQL (Production)
```bash
# Set database URL in environment
export DATABASE_URL="postgresql://user:password@localhost/attendance_db"

# Run migrations
alembic upgrade head
```

## Configuration

### Environment Variables
Create `.env` file:
```env
DATABASE_URL=sqlite:///./attendance.db
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here
```

### Device Configuration
Add devices via API:
```bash
curl -X POST http://localhost:8000/api/devices/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Main Entrance",
    "ip_address": "192.168.100.209",
    "port": 4370,
    "password": 0
  }'
```

## Development

### Project Structure
```
app/
├── api/          # FastAPI route handlers
├── core/         # Configuration and database
├── models/       # SQLAlchemy models
├── schemas/      # Pydantic schemas
└── services/     # Business logic

docs/             # Documentation
scripts/          # Utility scripts
tests/            # Test files
```

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Test specific device
python scripts/test_device_connection.py <IP_ADDRESS>
```

### Code Quality
```bash
# Format code
black app/ tests/

# Sort imports
isort app/ tests/

# Type checking
mypy app/
```

## Deployment

### Development
- SQLite database
- Single process
- Direct device connections

### Production
- PostgreSQL with connection pooling
- Redis for caching
- Celery for background tasks
- Load balancer for scaling

See [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) for detailed deployment guide.

## Troubleshooting

### Common Issues

**Device Connection Failed**
- Check IP address and port (default: 4370)
- Verify network connectivity
- Ensure device is powered on

**Database Locked (SQLite)**
- Stop all running processes
- Check for leftover connections
- Consider upgrading to PostgreSQL

**Dashboard Not Updating**
- Check WebSocket connection
- Verify device synchronization status
- Review logs in `dashboard.log`

### Logs
- **API Logs**: `app.log`
- **Dashboard Logs**: `dashboard.log`
- **Device Scripts**: Console output

### Performance Scripts
```bash
# Check system status
./scripts/check_status.sh

# Performance summary
./scripts/performance_summary.sh

# Manual data refresh
curl -X POST http://localhost:8000/api/refresh
```

## Contributing

1. Follow existing code style and conventions
2. Add type hints to all functions
3. Write tests for new features
4. Update documentation for API changes
5. See [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) for improvement roadmap

## Security

⚠️ **Current Status**: Development setup - not production ready
- No authentication required
- CORS allows all origins
- Secrets in configuration files

See Phase 1 of [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) for security hardening steps.

## License

[Add your license here]

## Support

For issues and questions:
1. Check the documentation in `docs/`
2. Review logs for error messages
3. Test device connectivity with scripts
4. Check existing issues or create new ones