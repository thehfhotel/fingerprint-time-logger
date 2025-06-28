# Fingerprint Time Logger Documentation

## Project Overview

**Simple internal fingerprint time logger** for single super-user management of employee attendance via ZKTeco biometric devices.

### Core Features
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

# Test device connectivity
python scripts/test_device_connection.py <IP_ADDRESS>

# Check attendance data
python scripts/display_attendance.py <IP_ADDRESS>
```

## Architecture

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

## API Reference

### Base Information
- **Base URL**: `http://localhost:8000`
- **Documentation**: http://localhost:8000/docs (Swagger UI)
- **Alternative Docs**: http://localhost:8000/redoc
- **Authentication**: None required (internal single-user app)

### Core API Endpoints

#### 🕐 Attendance Management
**GET /api/attendance/** - Retrieve attendance records with filtering options
- Query Parameters: `skip`, `limit`, `employee_id`, `device_id`, `start_date`, `end_date`, `punch_type`
- Example: `curl "http://localhost:8000/api/attendance/?employee_id=105"`

**GET /api/attendance/{record_id}** - Get specific attendance record
**POST /api/attendance/** - Create new attendance record
**PUT /api/attendance/{record_id}** - Update attendance record
**DELETE /api/attendance/{record_id}** - Delete attendance record
**GET /api/attendance/employee/{employee_id}** - Get all records for employee
**GET /api/attendance/today/** - Get today's attendance records

#### 👥 Employee Management
**GET /api/employees/** - List all employees
**GET /api/employees/{employee_id}** - Get specific employee
**POST /api/employees/** - Create new employee
**PUT /api/employees/{employee_id}** - Update employee information
**DELETE /api/employees/{employee_id}** - Delete employee

#### 🏢 Device Management
**GET /api/devices/** - List all devices
**GET /api/devices/{device_id}** - Get specific device
**POST /api/devices/** - Add new device
**PUT /api/devices/{device_id}** - Update device configuration
**DELETE /api/devices/{device_id}** - Remove device

#### 🔄 Synchronization
**POST /api/sync/start** - Start device synchronization
**POST /api/sync/all** - Sync all active devices
**GET /api/sync/logs** - Get synchronization logs
**GET /api/sync/status** - Get sync status for all devices
**DELETE /api/sync/logs/old** - Delete old sync logs

#### 📅 Schedule Management *(To Be Implemented)*
**GET /api/schedules/** - List all work schedules
**POST /api/schedules/** - Create work schedule
**GET /api/schedules/employee/{employee_id}** - Get employee's weekly schedule
**POST /api/schedules/import-csv** - Bulk import schedules from CSV

#### 📊 Reports and Analysis *(To Be Implemented)*
**GET /api/reports/daily/{date}** - Generate daily attendance report
**GET /api/reports/late-arrivals** - Get late arrivals for date range
**GET /api/reports/no-shows** - Get no-shows for date range
**GET /api/reports/export/daily/{date}** - Export daily report as CSV

### Data Types

#### Punch Types
- `0` - Check-in
- `1` - Check-out
- `2` - Break-out
- `3` - Break-in
- `4` - Overtime-in
- `5` - Overtime-out

#### Status Types
- `0` - Normal
- `1` - Late
- `2` - Early

#### Sync Types
- `employees` - Sync employee data only
- `attendance` - Sync attendance records only
- `full` - Sync both employees and attendance

#### Sync Status
- `started` - Sync in progress
- `success` - Completed successfully
- `failed` - Failed with error
- `partial` - Partially completed

## Implementation Plan

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

## Development Guidelines

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

## User Guide

### Getting Started

#### Start the System
```bash
# Terminal 1: Start API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Start dashboard
python dashboard_app.py
```

#### Access Points
- **Dashboard**: http://localhost:5000 (main interface)
- **API Documentation**: http://localhost:8000/docs (technical reference)

### Device Configuration

#### Add Your ZKTeco Device
1. Open dashboard at http://localhost:5000
2. Navigate to device management section
3. Add device with:
   - **Name**: "Main Entrance" (or your preference)
   - **IP Address**: Your device IP (e.g., 192.168.100.209)
   - **Port**: 4370 (standard ZKTeco port)
   - **Password**: 0 (if no password set)

#### Test Device Connection
```bash
python scripts/test_device_connection.py 192.168.100.209
```

### Daily Workflow

1. **Morning Sync** - Sync devices to get overnight data
2. **Check Reports** - Review late arrivals and no-shows
3. **Manual Corrections** - Add missing records if needed
4. **Export Data** - Generate reports for management

## Developer Setup

### Prerequisites
- **Python**: 3.8+ (tested with 3.12)
- **Network**: Access to ZKTeco device IP
- **Storage**: 1GB free space

### Installation
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
```

### Environment Configuration
```env
# Database
DATABASE_URL=sqlite:///./attendance.db

# ZKTeco Device
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
ZKTECO_PASSWORD=0
```

## Troubleshooting

### Common Issues

#### Device Connection Problems
1. **Check network connectivity** - Ping device IP
2. **Verify device settings** - Ensure correct IP, port, password
3. **Test with script** - Use `scripts/test_device_connection.py`

#### Database Issues
1. **Migration problems** - Check alembic logs
2. **Connection errors** - Verify database file permissions
3. **Data corruption** - Restore from backup

#### API Problems
1. **Server won't start** - Check port 8000 availability
2. **Sync failures** - Check device connectivity and logs
3. **Missing data** - Verify sync completion

### Log Files
- **API logs**: `app.log`
- **Dashboard logs**: `dashboard.log`
- **Sync logs**: Check `/api/sync/logs` endpoint

### Performance Issues
- **Slow queries** - Add database indexes
- **Dashboard timeout** - Reduce polling frequency
- **Memory usage** - Check for connection leaks

---

## File Structure\n\n```\nfingerprint-time-logger/\n├── app/                    # FastAPI application\n│   ├── api/               # API endpoints\n│   ├── core/              # Configuration and database\n│   ├── models/            # Database models\n│   ├── schemas/           # Pydantic schemas\n│   └── services/          # Business logic\n├── docs/                  # Documentation\n│   ├── DOCUMENTATION.md   # Main documentation (this file)\n│   ├── TECHNICAL_REFERENCE.md  # Architecture and technical details\n│   └── TROUBLESHOOTING.md # Detailed troubleshooting guide\n├── scripts/               # Utility scripts\n├── tests/                 # Test files\n├── dashboard_app.py       # Flask dashboard\n├── requirements.txt       # Python dependencies\n└── CLAUDE.md             # Development instructions\n```\n\n## Scripts Reference\n\n### Available Scripts\n- `test_device_connection.py` - Test ZKTeco device connectivity\n- `display_attendance.py` - Show attendance data from device\n- `check_status.sh` - Check service status\n- `performance_summary.sh` - System performance overview\n- `start_dashboard.sh` - Start dashboard service\n- `restart_dashboard.sh` - Restart dashboard service\n- `stop_dashboard.sh` - Stop dashboard service\n\n### Usage Examples\n```bash\n# Test device connection\npython scripts/test_device_connection.py 192.168.100.209\n\n# Check attendance data\npython scripts/display_attendance.py 192.168.100.209\n\n# Check system status\n./scripts/check_status.sh\n```\n\n**Focus**: Core business logic over complex architecture patterns. Keep it simple and functional for single-user internal use.