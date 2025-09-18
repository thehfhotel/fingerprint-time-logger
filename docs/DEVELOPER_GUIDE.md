# Developer Guide - Fingerprint Time Logger

**Version**: 1.0  
**Last Updated**: January 2025

## Overview

This guide provides comprehensive instructions for developers working with the Fingerprint Time Logger system, including setup, development workflows, architecture understanding, and extending the system for other projects.

## Table of Contents

1. [Quick Setup](#quick-setup)
2. [Development Environment](#development-environment)
3. [Project Structure](#project-structure)
4. [Architecture Overview](#architecture-overview)
5. [Database Management](#database-management)
6. [API Development](#api-development)
7. [Frontend Development](#frontend-development)
8. [Testing](#testing)
9. [Deployment](#deployment)
10. [Extending for Other Projects](#extending-for-other-projects)
11. [Troubleshooting](#troubleshooting)

## Quick Setup

### Prerequisites

- Python 3.8+ (recommended: 3.12)
- SQLite 3
- ZKTeco fingerprint device (for production use)
- Git

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd fingerprint-time-logger

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup database
alembic -c database/alembic.ini upgrade head

# Start development server
./scripts/start.sh
```

### Verify Installation

```bash
# Check application is running
curl http://localhost:5000/health

# Run tests
python3 -m pytest -v

# Check database
sqlite3 database/attendance.db ".tables"
```

## Development Environment

### Required Tools

- **Python 3.8+**: Main runtime
- **SQLite Browser**: Database inspection
- **Postman/Insomnia**: API testing
- **VS Code/PyCharm**: IDE with Python support

### Environment Variables

Create a `.env` file in the project root:

```env
# Database Configuration
DATABASE_URL=sqlite:///./database/attendance.db

# ZKTeco Device Configuration
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
ZKTECO_PASSWORD=0

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=5000
DEBUG=True
LOG_LEVEL=INFO

# Auto-Import Configuration
AUTO_IMPORT_ENABLED=True
AUTO_IMPORT_INTERVAL_MINUTES=30
```

### Development Commands

```bash
# Start development server with auto-reload
uvicorn app.main_unified:app --reload --port 5000

# Run in debug mode
python3 -m uvicorn app.main_unified:app --reload --port 5000 --log-level debug

# Run tests with coverage
python3 -m pytest --cov=app --cov-report=html

# Database migration
alembic -c database/alembic.ini revision --autogenerate -m "description"
alembic -c database/alembic.ini upgrade head

# Code formatting
black app/ tests/
isort app/ tests/

# Linting
flake8 app/ tests/
```

## Project Structure

```
fingerprint-time-logger/
├── app/                          # Main application
│   ├── __init__.py
│   ├── main_unified.py          # FastAPI application entry point
│   ├── api/                     # API endpoints
│   │   ├── consolidated_attendance.py
│   │   ├── consolidated_devices.py
│   │   ├── consolidated_employees.py
│   │   └── system_status.py
│   ├── core/                    # Core functionality
│   │   ├── config.py           # Configuration management
│   │   └── database.py         # Database connection
│   ├── models/                  # Database models
│   │   └── models.py
│   ├── schemas/                 # Pydantic schemas
│   │   └── schemas.py
│   └── services/                # Business logic
│       ├── attendance_service.py
│       ├── device_service.py
│       └── export_service.py
├── database/                    # Database files
│   ├── alembic.ini             # Alembic configuration
│   ├── attendance.db           # SQLite database
│   ├── database_schema.md      # Database documentation
│   └── migrations/             # Database migrations
├── docs/                       # Documentation
├── static/                     # Frontend files
│   ├── css/
│   ├── js/
│   └── *.html
├── tests/                      # Test files
├── scripts/                    # Management scripts
└── requirements.txt            # Dependencies
```

## Architecture Overview

### Core Components

1. **FastAPI Application**: Unified server handling both API and static files
2. **SQLAlchemy ORM**: Database abstraction layer
3. **Pydantic**: Data validation and serialization
4. **pyzk**: ZKTeco device communication
5. **Alembic**: Database migration management
6. **WebSocket**: Real-time frontend updates

### Data Flow

```
ZKTeco Device ↔ Device Service ↔ Database ↔ API ↔ Frontend
                      ↓
                Background Tasks
                      ↓
                 Auto-Import Service
```

### Key Design Patterns

- **Repository Pattern**: Data access abstraction
- **Service Layer**: Business logic separation
- **Dependency Injection**: FastAPI's built-in DI
- **Factory Pattern**: Configuration management
- **Observer Pattern**: WebSocket updates

## Database Management

### Schema Overview

#### Core Tables

```sql
-- Devices table
CREATE TABLE devices (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    ip_address VARCHAR(15) NOT NULL,
    port INTEGER DEFAULT 4370,
    password INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    last_sync DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Employees table (unified)
CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    badge_number VARCHAR(50) UNIQUE NOT NULL,
    english_name VARCHAR(100),
    thai_name VARCHAR(100),
    display_name VARCHAR(100) NOT NULL,
    department VARCHAR(100),
    position VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    is_hidden BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Attendance records table
CREATE TABLE attendance_records (
    id INTEGER PRIMARY KEY,
    employee_badge_number VARCHAR(50) NOT NULL,
    device_id INTEGER NOT NULL,
    timestamp DATETIME NOT NULL,
    punch_type INTEGER NOT NULL,
    status INTEGER DEFAULT 0,
    sync_status VARCHAR(20) DEFAULT 'synced',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Job roles table removed - simplifying employee management
```

### Migration Management

```bash
# Create new migration
alembic -c database/alembic.ini revision --autogenerate -m "Add new feature"

# Apply migrations
alembic -c database/alembic.ini upgrade head

# Rollback migration
alembic -c database/alembic.ini downgrade -1

# Check migration status
alembic -c database/alembic.ini current

# Show migration history
alembic -c database/alembic.ini history
```

### Database Utilities

```python
# app/core/database.py
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

## API Development

### Creating New Endpoints

1. **Define Schema** (`app/schemas/schemas.py`):
```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class NewFeatureBase(BaseModel):
    name: str
    description: Optional[str] = None

class NewFeatureCreate(NewFeatureBase):
    pass

class NewFeature(NewFeatureBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True
```

2. **Create Model** (`app/models/models.py`):
```python
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base

class NewFeature(Base):
    __tablename__ = "new_features"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

3. **Create Service** (`app/services/new_feature_service.py`):
```python
from sqlalchemy.orm import Session
from app.models.models import NewFeature
from app.schemas.schemas import NewFeatureCreate

class NewFeatureService:
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, feature_data: NewFeatureCreate) -> NewFeature:
        db_feature = NewFeature(**feature_data.dict())
        self.db.add(db_feature)
        self.db.commit()
        self.db.refresh(db_feature)
        return db_feature
    
    def get_all(self) -> List[NewFeature]:
        return self.db.query(NewFeature).all()
```

4. **Create API Endpoint** (`app/api/new_feature.py`):
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.new_feature_service import NewFeatureService
from app.schemas.schemas import NewFeature, NewFeatureCreate

router = APIRouter(prefix="/api/new-feature", tags=["new-feature"])

@router.post("/", response_model=NewFeature)
async def create_feature(
    feature: NewFeatureCreate,
    db: Session = Depends(get_db)
):
    service = NewFeatureService(db)
    return service.create(feature)

@router.get("/", response_model=List[NewFeature])
async def get_features(db: Session = Depends(get_db)):
    service = NewFeatureService(db)
    return service.get_all()
```

5. **Register Router** (`app/main_unified.py`):
```python
from app.api import new_feature

app.include_router(new_feature.router)
```

### API Best Practices

- Use consistent response formats
- Implement proper error handling
- Add input validation with Pydantic
- Include comprehensive documentation
- Use dependency injection for services
- Implement logging for debugging

## Frontend Development

### Structure

```
static/
├── css/
│   ├── base.css           # Common styles
│   ├── dashboard.css      # Dashboard specific
│   └── modal.css          # Modal components
├── js/
│   ├── config.js          # Configuration
│   ├── real-time-manager.js # WebSocket handling
│   └── websocket-adapter.js # WebSocket adapter
└── *.html                 # Page templates
```

### Adding New Pages

1. **Create HTML Template** (`static/new-page.html`):
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Page - Fingerprint Time Logger</title>
    <link rel="stylesheet" href="/static/css/base.css">
    <link rel="stylesheet" href="/static/css/new-page.css">
</head>
<body>
    <div class="header">
        <div class="header-row-1">
            <h1>New Page</h1>
        </div>
        <div class="header-row-2">
            <div class="header-actions">
                <a href="/" class="action-btn">📊 Dashboard</a>
                <a href="/new-page" class="action-btn">🆕 New Page</a>
            </div>
        </div>
    </div>
    
    <div class="container">
        <div id="content">
            <!-- Page content here -->
        </div>
    </div>
    
    <script src="/static/js/config.js"></script>
    <script src="/static/js/new-page.js"></script>
</body>
</html>
```

2. **Add Route** (`app/main_unified.py`):
```python
@app.get("/new-page")
async def new_page():
    return FileResponse('static/new-page.html')
```

3. **Create JavaScript** (`static/js/new-page.js`):
```javascript
class NewPage {
    constructor() {
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.loadData();
    }
    
    setupEventListeners() {
        // Event handlers
    }
    
    async loadData() {
        try {
            const response = await fetch('/api/new-feature/');
            const data = await response.json();
            this.renderData(data);
        } catch (error) {
            console.error('Error loading data:', error);
        }
    }
    
    renderData(data) {
        // Render logic
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new NewPage();
});
```

### WebSocket Integration

```javascript
class RealTimeManager {
    constructor() {
        this.ws = null;
        this.reconnectInterval = 5000;
        this.maxReconnectAttempts = 5;
        this.reconnectAttempts = 0;
        this.connect();
    }
    
    connect() {
        this.ws = new WebSocket(`ws://${window.location.host}/ws`);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.reconnectAttempts = 0;
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.reconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }
    
    handleMessage(data) {
        // Handle real-time updates
        if (data.type === 'attendance_update') {
            this.updateAttendanceDisplay(data.data);
        }
    }
    
    reconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            setTimeout(() => this.connect(), this.reconnectInterval);
        }
    }
}
```

## Testing

### Test Structure

```
tests/
├── __init__.py
├── test_api.py          # API endpoint tests
├── test_config.py       # Configuration tests
├── test_models.py       # Database model tests
└── test_services.py     # Service layer tests
```

### Writing Tests

```python
# tests/test_new_feature.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main_unified import app
from app.core.database import get_db, Base

# Test database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

def test_create_new_feature():
    response = client.post(
        "/api/new-feature/",
        json={"name": "Test Feature", "description": "Test description"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Feature"
    assert "id" in data

def test_get_new_features():
    response = client.get("/api/new-feature/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
```

### Running Tests

```bash
# Run all tests
python3 -m pytest

# Run with coverage
python3 -m pytest --cov=app --cov-report=html

# Run specific test file
python3 -m pytest tests/test_api.py

# Run with verbose output
python3 -m pytest -v

# Run tests matching pattern
python3 -m pytest -k "test_employee"
```

## Deployment

### Production Setup

1. **Environment Configuration**:
```env
# Production settings
DEBUG=False
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///./database/attendance.db
ZKTECO_HOST=<production-device-ip>
```

2. **Service Configuration** (`/etc/systemd/system/fingerprint-logger.service`):
```ini
[Unit]
Description=Fingerprint Time Logger
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/fingerprint-time-logger
Environment=PATH=/opt/fingerprint-time-logger/venv/bin
ExecStart=/opt/fingerprint-time-logger/venv/bin/uvicorn app.main_unified:app --host 0.0.0.0 --port 5000
Restart=always

[Install]
WantedBy=multi-user.target
```

3. **Deployment Script** (`deploy.sh`):
```bash
#!/bin/bash
set -e

# Update code
git pull origin main

# Install dependencies
source venv/bin/activate
pip install -r requirements.txt

# Run migrations
alembic -c database/alembic.ini upgrade head

# Run tests
python3 -m pytest

# Restart service
sudo systemctl restart fingerprint-logger
sudo systemctl status fingerprint-logger
```

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["uvicorn", "app.main_unified:app", "--host", "0.0.0.0", "--port", "5000"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./database:/app/database
      - ./logs:/app/logs
    environment:
      - DATABASE_URL=sqlite:///./database/attendance.db
      - ZKTECO_HOST=192.168.100.209
    restart: unless-stopped
```

## Extending for Other Projects

### Adapting for Different Devices

1. **Create Device Adapter** (`app/services/adapters/`):
```python
from abc import ABC, abstractmethod

class DeviceAdapter(ABC):
    @abstractmethod
    def connect(self) -> bool:
        pass
    
    @abstractmethod
    def get_attendance_records(self) -> List[AttendanceRecord]:
        pass
    
    @abstractmethod
    def get_users(self) -> List[User]:
        pass

class ZKTecoAdapter(DeviceAdapter):
    # ZKTeco implementation
    pass

class NewDeviceAdapter(DeviceAdapter):
    # New device implementation
    pass
```

2. **Configuration** (`app/core/config.py`):
```python
class Settings(BaseSettings):
    device_type: str = "zkteco"  # or "new_device"
    
    @property
    def device_adapter(self):
        if self.device_type == "zkteco":
            return ZKTecoAdapter
        elif self.device_type == "new_device":
            return NewDeviceAdapter
        else:
            raise ValueError(f"Unsupported device type: {self.device_type}")
```

### Multi-Tenant Support

1. **Database Schema Updates**:
```python
class Organization(Base):
    __tablename__ = "organizations"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    subdomain = Column(String(50), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)

# Add organization_id to existing tables
class Employee(Base):
    __tablename__ = "employees"
    
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    # ... other fields
```

2. **Middleware for Tenant Resolution**:
```python
from fastapi import Request
from fastapi.middleware.base import BaseHTTPMiddleware

class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Extract tenant from subdomain or header
        tenant = self.get_tenant_from_request(request)
        request.state.tenant = tenant
        response = await call_next(request)
        return response
```

### API Versioning

```python
from fastapi import APIRouter

# Version 1
v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(attendance.router)

# Version 2
v2_router = APIRouter(prefix="/api/v2")
v2_router.include_router(attendance_v2.router)

app.include_router(v1_router)
app.include_router(v2_router)
```

### Microservices Architecture

1. **Service Decomposition**:
```
User Service:     /api/users/
Device Service:   /api/devices/
Attendance Service: /api/attendance/
Export Service:   /api/export/
```

2. **Service Communication**:
```python
import httpx

class UserServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
    
    async def get_user(self, user_id: int):
        response = await self.client.get(f"{self.base_url}/users/{user_id}")
        return response.json()
```

## Troubleshooting

### Common Issues

1. **Database Connection Issues**:
```bash
# Check database file permissions
ls -la database/attendance.db

# Test database connection
python3 -c "from app.core.database import engine; print(engine.execute('SELECT 1').scalar())"
```

2. **Device Connection Issues**:
```bash
# Test network connectivity
ping 192.168.100.209

# Check device port
telnet 192.168.100.209 4370
```

3. **Import Issues**:
```bash
# Check Python path
python3 -c "import sys; print(sys.path)"

# Test imports
python3 -c "from app.main_unified import app; print('Import successful')"
```

### Debug Mode

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Add debug prints
print(f"Database URL: {settings.database_url}")
print(f"Device Config: {settings.zkteco_host}:{settings.zkteco_port}")
```

### Performance Monitoring

```python
import time
from functools import wraps

def monitor_performance(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        duration = time.time() - start_time
        print(f"{func.__name__} took {duration:.2f}s")
        return result
    return wrapper

@monitor_performance
async def slow_endpoint():
    # Endpoint implementation
    pass
```

## Best Practices

### Code Organization

- Follow PEP 8 style guidelines
- Use type hints consistently
- Implement proper error handling
- Write comprehensive tests
- Document complex logic
- Use dependency injection

### Security

- Validate all input data
- Use parameterized queries
- Implement proper logging
- Don't expose sensitive information
- Use environment variables for secrets

### Performance

- Use database indexes appropriately
- Implement connection pooling
- Cache frequently accessed data
- Use async/await for I/O operations
- Monitor database query performance

## Resources

- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **SQLAlchemy Documentation**: https://docs.sqlalchemy.org/
- **Pydantic Documentation**: https://pydantic-docs.helpmanual.io/
- **pyzk Documentation**: https://github.com/fananimi/pyzk
- **Alembic Documentation**: https://alembic.sqlalchemy.org/

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

For questions or support, please refer to the project documentation or contact the development team.