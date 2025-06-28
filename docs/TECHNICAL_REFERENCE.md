# Technical Reference

## System Architecture

### Overview
The Fingerprint Time Logger is a **simple internal tool** for single super-user management of employee attendance via ZKTeco fingerprint devices. Focus is on core business functionality rather than complex architecture.

### Core Business Requirements
1. **Fingerprint Log Retrieval** - Get check-in/check-out time logs from ZK device
2. **Schedule Comparison** - Compare logs to employee work schedules to identify late arrivals and no-shows  
3. **Device Time Management** - Check and adjust ZK device time when needed

**Target User**: Single internal super-user (no multi-user authentication needed)

### Simplified Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Simple Dashboard                     │
│               Flask (Port 5000)                         │
├─────────────────────────────────────────────────────────┤
│                    Basic API                            │
│               FastAPI (Port 8000)                       │
│  ┌──────────┬──────────┬──────────┬──────────┐        │
│  │Attendance│ Devices  │Schedules │ Reports  │        │
│  │   API    │   API    │   API    │   API    │        │
│  └──────────┴──────────┴──────────┴──────────┘        │
├─────────────────────────────────────────────────────────┤
│                 Business Logic                          │
│  ┌──────────┬──────────┬──────────┬──────────┐        │
│  │ Device   │Schedule  │Attendance│ Report   │        │
│  │ Service  │Comparison│ Analysis │Generator │        │
│  └──────────┴──────────┴──────────┴──────────┘        │
├─────────────────────────────────────────────────────────┤
│                 Data Layer                              │
│               SQLite Database                           │
│  ┌──────────┬──────────┬──────────┬──────────┐        │
│  │Employees │ Devices  │Attendance│WorkSchedule      │
│  │          │          │ Records  │          │        │
│  └──────────┴──────────┴──────────┴──────────┘        │
├─────────────────────────────────────────────────────────┤
│                Hardware Integration                     │
│               ZKTeco Device                             │
│               (pyzk library)                            │
└─────────────────────────────────────────────────────────┘
```

**Keep Current**: FastAPI + Flask Dashboard + SQLite + pyzk library
**Remove Complexity**: No Redis, Celery, PostgreSQL, authentication, or scaling concerns

### Component Details

#### 1. Dashboard Layer (Flask - Port 5000)
- **Purpose**: Simple monitoring interface for attendance review
- **Technology**: Flask with SocketIO for real-time updates
- **Key Features**:
  - Real-time attendance monitoring
  - Device status display
  - Basic attendance reports
  - Manual record management

#### 2. API Layer (FastAPI - Port 8000)
- **Purpose**: REST API for data access and device management
- **Technology**: FastAPI with automatic OpenAPI documentation
- **Key Endpoints**:
  - `/api/attendance/` - Attendance record management
  - `/api/employees/` - Employee information
  - `/api/devices/` - Device configuration
  - `/api/sync/` - Device synchronization

#### 3. Business Logic Layer
- **Device Service**: ZKTeco device communication and synchronization
- **Schedule Comparison**: Compare actual vs scheduled attendance
- **Attendance Analysis**: Identify late arrivals and no-shows
- **Report Generator**: Create attendance reports and exports

#### 4. Data Layer (SQLite)
- **Database**: Single SQLite file (sufficient for single-user)
- **Models**:
  - `Employee`: Staff records with IDs and basic info
  - `Device`: ZKTeco device configuration
  - `AttendanceRecord`: Time punch records
  - `WorkSchedule`: Employee work schedules
  - `SyncLog`: Device synchronization tracking

#### 5. Hardware Integration
- **Technology**: pyzk library for ZKTeco communication
- **Protocol**: TCP/IP communication on port 4370
- **Features**:
  - Real-time attendance data retrieval
  - Device time synchronization
  - User management (future)

## Database Schema

### Core Tables

```sql
-- Employee information
CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    employee_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    department VARCHAR(100),
    position VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ZKTeco device configuration  
CREATE TABLE devices (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    ip_address VARCHAR(15) NOT NULL,
    port INTEGER DEFAULT 4370,
    password INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    last_sync TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Attendance punch records
CREATE TABLE attendance_records (
    id INTEGER PRIMARY KEY,
    employee_id VARCHAR(50) NOT NULL,
    device_id INTEGER NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    punch_type INTEGER NOT NULL,
    status INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
    FOREIGN KEY (device_id) REFERENCES devices(id)
);

-- Work schedules (to be implemented)
CREATE TABLE work_schedules (
    id INTEGER PRIMARY KEY,
    employee_id VARCHAR(50) NOT NULL,
    day_of_week INTEGER NOT NULL,  -- 0=Monday, 6=Sunday
    start_time TIME NOT NULL,      -- Expected start time
    end_time TIME NOT NULL,        -- Expected end time
    is_workday BOOLEAN DEFAULT TRUE,
    late_threshold_minutes INTEGER DEFAULT 15,
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
);

-- Synchronization logs
CREATE TABLE sync_logs (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL,
    sync_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    records_synced INTEGER,
    error_message TEXT,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    FOREIGN KEY (device_id) REFERENCES devices(id)
);
```

### Indexes for Performance

```sql
-- Attendance record indexes
CREATE INDEX idx_attendance_employee ON attendance_records(employee_id);
CREATE INDEX idx_attendance_device ON attendance_records(device_id);
CREATE INDEX idx_attendance_timestamp ON attendance_records(timestamp);
CREATE INDEX idx_attendance_date ON attendance_records(date(timestamp));

-- Schedule indexes
CREATE INDEX idx_schedule_employee ON work_schedules(employee_id);
CREATE INDEX idx_schedule_day ON work_schedules(day_of_week);

-- Sync log indexes
CREATE INDEX idx_sync_device ON sync_logs(device_id);
CREATE INDEX idx_sync_status ON sync_logs(status);
CREATE INDEX idx_sync_started ON sync_logs(started_at);
```

## Development Environment

### Prerequisites
- **Python**: 3.8+ (tested with 3.12)
- **Operating System**: Linux/macOS/Windows
- **Memory**: 512MB RAM minimum
- **Storage**: 1GB free space
- **Network**: Access to ZKTeco device IP

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

# API Settings
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=True

# Dashboard Settings
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=5000
```

## Performance Considerations

### Single-User Design
- **SQLite**: Adequate for single-user concurrent access
- **No Connection Pooling**: Simple database connections
- **Synchronous Operations**: Acceptable for internal use
- **Basic Caching**: In-memory only, no Redis needed

### Resource Usage
- **Memory**: ~50MB typical usage
- **CPU**: Low usage except during device sync
- **Disk**: SQLite database grows ~1MB per 10K records
- **Network**: Minimal except during device communication

### Scalability Limits
- **Concurrent Users**: Designed for single user
- **Devices**: Tested with 1-2 devices
- **Records**: Suitable for thousands of records
- **Reports**: Daily/weekly reports only

## Deployment

### Single-Machine Deployment
```bash
# Start API server
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Start dashboard (separate terminal)
python dashboard_app.py
```

### Simple Backup Strategy
```bash
# Backup database (daily recommended)
cp attendance.db backups/attendance_$(date +%Y%m%d).db

# Backup logs
tar -czf logs_$(date +%Y%m%d).tar.gz *.log
```

### Security Considerations
- **Internal Use Only**: No public internet exposure
- **No Authentication**: Single trusted user
- **Local Network**: ZKTeco device on private network
- **File Permissions**: Restrict database file access

---

**Focus**: Keep architecture simple and functional for single-user internal use. Avoid over-engineering for this use case.