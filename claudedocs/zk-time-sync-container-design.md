# ZK Device Time Sync Container - Design & Implementation

## Overview
Minimal Docker container to synchronize ZK biometric device time to Bangkok timezone (GMT+7) with comprehensive logging.

## Container Architecture

### Core Components
```
zk-time-sync/
├── Dockerfile              # Minimal Python container
├── requirements.txt         # pyzk + timezone libs
├── sync_service.py         # Main sync logic
├── config/
│   └── devices.json        # Device configurations
├── logs/                   # Time sync logs (volume mounted)
└── docker-compose.yml      # Container orchestration
```

### Service Design
- **Single Purpose**: ZK device time synchronization only
- **Bangkok Time**: Always sync to Asia/Bangkok timezone (GMT+7)
- **Scheduled Sync**: Configurable interval (default: every 30 minutes)
- **Slack Notifications**: Real-time notifications for sync completion and errors
- **Persistent Logs**: Volume-mounted log directory
- **Health Monitoring**: Basic health check endpoint
- **Configuration**: JSON-based device configuration

## Extracted Logic from device_service.py

### Key Functions to Extract
```python
# From app/services/device_service.py:45-89
def set_device_time(self, target_time: Optional[datetime] = None) -> Dict[str, Any]:
    """Set device time to Bangkok timezone"""

# From app/services/device_service.py:91-142
def sync_time_to_device(self, device_id: int) -> Dict[str, Any]:
    """Sync single device time"""

# From app/services/device_service.py:144-187
def check_device_time(self, device_id: int) -> Dict[str, Any]:
    """Check time difference"""
```

### Bangkok Timezone Configuration
```python
# From docker-compose.yml environment
TZ=Asia/Bangkok

# Python timezone handling
from zoneinfo import ZoneInfo
bangkok_tz = ZoneInfo("Asia/Bangkok")
target_time = datetime.now(bangkok_tz)
```

## Implementation Plan

### Phase 1: Core Service Creation
1. **Extract time sync logic** from existing device_service.py
2. **Create minimal Python service** with pyzk dependency
3. **Implement Bangkok timezone** handling
4. **Add comprehensive logging** for all sync operations

### Phase 2: Container Setup
1. **Create Dockerfile** with minimal Python base
2. **Configure device connections** via JSON config
3. **Set up log volume mounting** for persistence
4. **Add basic health checks**

### Phase 3: Orchestration & Monitoring
1. **Create docker-compose** configuration
2. **Implement scheduled sync** (cron-like intervals)
3. **Add monitoring endpoints** for sync status
4. **Test with existing ZK device** (192.168.100.209:4370)

## Logging Strategy

### Log Levels & Content
```
[2025-01-18 10:30:00] INFO  - Starting time sync for device 192.168.100.209:4370
[2025-01-18 10:30:01] INFO  - Device time: 2025-01-18 15:30:01 (UTC+5)
[2025-01-18 10:30:01] INFO  - Bangkok time: 2025-01-18 17:30:01 (UTC+7)
[2025-01-18 10:30:01] INFO  - Time difference: 2 hours
[2025-01-18 10:30:02] INFO  - Time sync successful - New device time: 2025-01-18 17:30:02
[2025-01-18 10:30:02] INFO  - Verification: Time difference now 0 seconds
```

### Log Files
- **sync.log**: Main sync operations log
- **errors.log**: Error and exception logging
- **health.log**: Health check and monitoring

## Configuration Structure

### devices.json
```json
{
  "devices": [
    {
      "id": 1,
      "host": "192.168.100.209",
      "port": 4370,
      "password": "",
      "name": "Main Fingerprint Device",
      "sync_enabled": true
    }
  ],
  "sync_interval_minutes": 30,
  "bangkok_timezone": "Asia/Bangkok",
  "log_level": "INFO"
}
```

## Docker Configuration

### Dockerfile Structure
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY sync_service.py .
COPY config/ ./config/
CMD ["python", "sync_service.py"]
```

### Volume Mounts
- **./logs:/app/logs** - Persistent logging
- **./config:/app/config** - Configuration files

## Benefits of Separation
1. **Isolation**: Time sync runs independently of main application
2. **Reliability**: Dedicated service for critical time synchronization
3. **Scalability**: Can sync multiple devices independently
4. **Monitoring**: Focused logging and health checks
5. **Maintenance**: Simpler deployment and updates

## Integration with Existing System
- **Network**: Shares docker network with main application
- **Device Access**: Direct connection to ZK device on LAN
- **Logging**: Separate log files for easy monitoring
- **Health**: Can be monitored by main application if needed

## Next Steps
1. Extract and adapt time sync logic from device_service.py
2. Create minimal Python service with scheduling
3. Build Docker container and test with existing device
4. Integrate with docker-compose network
5. Validate Bangkok timezone synchronization