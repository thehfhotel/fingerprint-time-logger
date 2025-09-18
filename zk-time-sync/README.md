# ZK Device Time Sync Service

Minimal Docker container to synchronize ZK biometric device time to Bangkok timezone (GMT+7) with comprehensive logging.

## Overview

This standalone service extracts the time synchronization logic from the main fingerprint-time-logger application and runs it as a dedicated container. It continuously syncs ZK device time to Bangkok time (GMT+7) and maintains detailed logs of all sync operations.

## Features

- **Bangkok Time Sync**: Always syncs to Asia/Bangkok timezone (GMT+7)
- **Scheduled Synchronization**: Configurable interval (default: 30 minutes)
- **Slack Notifications**: Real-time notifications for sync completion and errors
- **Comprehensive Logging**: Detailed logs with timestamps and status
- **Health Monitoring**: Built-in health checks and status reporting
- **Minimal Dependencies**: Only requires pyzk and requests libraries
- **Docker Integration**: Shares network with main application
- **Error Recovery**: Continues operation after errors

## Quick Start

### 1. Build and Run
```bash
# Navigate to the service directory
cd zk-time-sync/

# Build the container
docker-compose build

# Start the service
docker-compose up -d

# Check status
docker-compose ps
```

### 2. View Logs
```bash
# Real-time logs
docker-compose logs -f

# Check sync logs
tail -f logs/sync.log

# Check error logs
tail -f logs/errors.log
```

### 3. Health Check
```bash
# Container health status
docker-compose ps

# Manual health check
docker-compose exec zk-time-sync python -c "from sync_service import ZKTimeSyncService; import json; print(json.dumps(ZKTimeSyncService().health_check(), indent=2))"
```

## Configuration

### Device Configuration (`config/devices.json`)
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

### Configuration Options
- **devices**: Array of ZK devices to sync
- **sync_interval_minutes**: How often to sync (default: 30 minutes)
- **bangkok_timezone**: Target timezone (always Asia/Bangkok)
- **log_level**: Logging level (DEBUG, INFO, WARNING, ERROR)
- **slack_notifications**: Slack webhook notification settings

### Adding More Devices
```json
{
  "devices": [
    {
      "id": 1,
      "host": "192.168.100.209",
      "port": 4370,
      "password": "",
      "name": "Main Office Device",
      "sync_enabled": true
    },
    {
      "id": 2,
      "host": "192.168.100.210",
      "port": 4370,
      "password": "admin123",
      "name": "Secondary Device",
      "sync_enabled": true
    }
  ]
}
```

### Slack Notifications Configuration
Enable real-time Slack notifications for sync operations:

```json
{
  "slack_notifications": {
    "enabled": true,
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    "notify_on_success": true,
    "notify_on_error": true,
    "channel": "#zk-time-sync",
    "username": "ZK Time Sync Bot"
  }
}
```

#### Slack Configuration Options
- **enabled**: Enable/disable Slack notifications (true/false)
- **webhook_url**: Your Slack webhook URL (required if enabled)
- **notify_on_success**: Send notifications for successful syncs (true/false)
- **notify_on_error**: Send notifications for sync errors (true/false)
- **channel**: Target Slack channel (e.g., "#zk-time-sync")
- **username**: Bot display name in Slack

#### Setting up Slack Webhook
1. Go to your Slack workspace settings
2. Create a new app or use existing app
3. Add "Incoming Webhooks" feature
4. Create webhook for your target channel
5. Copy webhook URL to configuration
6. Restart the service to apply changes

#### Notification Examples

**Success Notification:**
```
✅ ZK Sync 1/1 OK at 17:30 - Main Fingerprint Device:17:30(120.5s→0.8s)
```

**Error Notification:**
```
🚨 ZK Sync 1/2 OK at 17:30 - Device A:✅17:30(1.2s), Device B:❌
```

**Service Error:**
```
🚨 ZK Sync service error at 17:30: Connection refused - retrying in 1min
```

## Logging

### Log Files
- **`logs/sync.log`**: Main synchronization operations log
- **`logs/errors.log`**: Error and exception logging only

### Log Format
```
[2025-01-18 10:30:00] INFO  - Starting time sync for device Main Fingerprint Device (192.168.100.209:4370)
[2025-01-18 10:30:01] INFO  - Current device time: 2025-01-18 15:30:01
[2025-01-18 10:30:01] INFO  - Bangkok time (target): 2025-01-18 17:30:01
[2025-01-18 10:30:01] INFO  - Time difference before sync: 7200.0 seconds
[2025-01-18 10:30:02] INFO  - Time sync command sent to device
[2025-01-18 10:30:03] INFO  - New device time: 2025-01-18 17:30:03
[2025-01-18 10:30:03] INFO  - Time difference after sync: 0.2 seconds
[2025-01-18 10:30:03] INFO  - Time sync successful for Main Fingerprint Device
[2025-01-18 10:30:03] INFO  - Disconnected from device Main Fingerprint Device
```

### Log Monitoring Commands
```bash
# Real-time sync logs
tail -f logs/sync.log

# Filter successful syncs
grep "Time sync successful" logs/sync.log

# Filter errors only
tail -f logs/errors.log

# Check last sync for specific device
grep "Main Fingerprint Device" logs/sync.log | tail -5

# Monitor time differences
grep "Time difference" logs/sync.log | tail -10
```

## Monitoring & Health Checks

### Docker Health Check
The container includes automatic health checks every 5 minutes:
```bash
# Check container health status
docker-compose ps
# Shows: healthy, unhealthy, or starting

# View health check logs
docker inspect zk-time-sync --format='{{.State.Health.Log}}'
```

### Manual Monitoring
```bash
# Service status and configuration
docker-compose exec zk-time-sync python -c "
from sync_service import ZKTimeSyncService
import json
service = ZKTimeSyncService()
print(json.dumps(service.health_check(), indent=2))
"

# Force immediate sync (for testing)
docker-compose exec zk-time-sync python -c "
from sync_service import ZKTimeSyncService
service = ZKTimeSyncService()
results = service.sync_all_devices()
for result in results:
    print(f\"Device: {result['device']} - Success: {result['success']}\")
"
```

### Integration with Main Application
The service can be monitored by the main fingerprint-time-logger application:

```bash
# Check if sync service is running
docker ps | grep zk-time-sync

# Monitor from main application logs
docker-compose -f ../docker-compose.yml logs | grep -i "time.sync"
```

## Troubleshooting

### Common Issues

#### 1. Device Connection Failed
```bash
# Check device accessibility
ping 192.168.100.209

# Check port accessibility
nc -zv 192.168.100.209 4370

# Check device configuration
cat config/devices.json

# View connection errors
grep "Failed to connect" logs/errors.log
```

#### 2. Time Sync Not Working
```bash
# Check current device time manually
docker-compose exec zk-time-sync python -c "
from zk import ZK
zk = ZK('192.168.100.209', port=4370, timeout=10)
conn = zk.connect()
print(f'Device time: {conn.get_time()}')
conn.disconnect()
"

# Check Bangkok time
docker-compose exec zk-time-sync python -c "
from datetime import datetime
from zoneinfo import ZoneInfo
bangkok_time = datetime.now(ZoneInfo('Asia/Bangkok'))
print(f'Bangkok time: {bangkok_time}')
"
```

#### 3. High Time Differences
```bash
# Monitor time differences over time
grep "Time difference after sync" logs/sync.log | tail -10

# Check if device hardware clock is drifting
grep "Time difference before sync" logs/sync.log | tail -10
```

### Service Management
```bash
# Stop service
docker-compose stop

# Restart service
docker-compose restart

# Update configuration (restart required)
# 1. Edit config/devices.json
# 2. docker-compose restart

# View service resource usage
docker stats zk-time-sync

# Clean up logs (if getting too large)
> logs/sync.log
> logs/errors.log
```

## File Structure
```
zk-time-sync/
├── sync_service.py         # Main Python service
├── requirements.txt        # Python dependencies
├── Dockerfile             # Container definition
├── docker-compose.yml     # Service orchestration
├── README.md              # This documentation
├── config/
│   └── devices.json       # Device configurations
└── logs/                  # Persistent log files
    ├── sync.log          # Main sync operations
    └── errors.log        # Error logging
```

## Integration Notes

- **Network**: Uses shared-nginx network to communicate with main application
- **Timezone**: Always uses Asia/Bangkok (GMT+7) for consistency
- **Device**: Configured for existing ZK device at 192.168.100.209:4370
- **Logging**: Separate log files to avoid conflicts with main application
- **Resource Usage**: Minimal resource footprint (~50MB RAM, periodic CPU usage)

## Development

### Testing Changes
```bash
# Rebuild after code changes
docker-compose build --no-cache

# Test with one-time sync
docker-compose run --rm zk-time-sync python -c "
from sync_service import ZKTimeSyncService
service = ZKTimeSyncService()
results = service.sync_all_devices()
print(results)
"

# Test health check
docker-compose run --rm zk-time-sync python -c "
from sync_service import ZKTimeSyncService
health = ZKTimeSyncService().health_check()
print(health)
"
```

### Customization
- **Sync Interval**: Modify `sync_interval_minutes` in config/devices.json
- **Log Level**: Change `log_level` for more/less verbose logging
- **Additional Devices**: Add to `devices` array in configuration
- **Custom Logic**: Modify sync_service.py (rebuild container required)