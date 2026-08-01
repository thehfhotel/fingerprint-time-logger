# Deployment Guide - Fingerprint Time Logger

**Version**: 1.0  
**Last Updated**: January 2025

## Overview

This guide provides comprehensive instructions for deploying the Fingerprint Time Logger system in production environments. The system is designed for single-user installations with focus on reliability and ease of maintenance.

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Pre-deployment Checklist](#pre-deployment-checklist)
3. [Installation Methods](#installation-methods)
4. [Configuration](#configuration)
5. [Service Management](#service-management)
6. [Monitoring & Maintenance](#monitoring--maintenance)
7. [Backup & Recovery](#backup--recovery)
8. [Troubleshooting](#troubleshooting)

## System Requirements

### Hardware Requirements

**Minimum:**
- CPU: 1 core, 1 GHz
- RAM: 512 MB
- Storage: 2 GB available space
- Network: 100 Mbps Ethernet

**Recommended:**
- CPU: 2 cores, 2.4 GHz
- RAM: 2 GB
- Storage: 10 GB available space (SSD preferred)
- Network: 1 Gbps Ethernet

### Software Requirements

**Operating System:**
- Ubuntu 20.04 LTS or later
- CentOS 8 or later
- Debian 11 or later
- Windows 10/11 (for development)

**Dependencies:**
- Python 3.8 or later (Python 3.12 recommended)
- SQLite 3.35 or later
- Git 2.25 or later

**Network Requirements:**
- Access to ZKTeco device (default: 192.168.100.209:4370)
- HTTP/HTTPS port access (default: 5000)
- WebSocket support

## Pre-deployment Checklist

### Environment Preparation

- [ ] Target server meets system requirements
- [ ] Python 3.8+ installed and configured
- [ ] Database directory permissions configured
- [ ] Network connectivity to ZKTeco device verified
- [ ] Firewall rules configured for port 5000
- [ ] SSL certificates prepared (if using HTTPS)
- [ ] Backup strategy planned
- [ ] Monitoring tools configured

### ZKTeco Device Setup

- [ ] Device IP address configured and accessible
- [ ] Device time synchronized with server
- [ ] Device password configured (if required)
- [ ] Network connectivity tested
- [ ] Device firmware version verified (compatible with pyzk)

### Security Checklist

- [ ] Server hardening completed
- [ ] User accounts configured with minimal privileges
- [ ] File permissions properly set
- [ ] Network security configured
- [ ] Backup encryption configured
- [ ] Log rotation configured

## Installation Methods

### Method 1: Standard Installation (Recommended)

```bash
# 1. Create application user
sudo useradd -r -s /bin/bash -d /opt/fingerprint-logger fingerprint-logger
sudo mkdir -p /opt/fingerprint-logger
sudo chown fingerprint-logger:fingerprint-logger /opt/fingerprint-logger

# 2. Switch to application user
sudo -u fingerprint-logger -i

# 3. Clone repository
cd /opt/fingerprint-logger
git clone <repository-url> .

# 4. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 5. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 6. Configure environment
cp .env.example .env
# Edit .env with your configuration

# 7. Setup database
alembic -c database/alembic.ini upgrade head

# 8. Run tests
python3 -m pytest

# 9. Create directories
mkdir -p logs pids
```

### Method 2: Docker Installation

```bash
# 1. Create project directory
mkdir -p /opt/fingerprint-logger
cd /opt/fingerprint-logger

# 2. Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
version: '3.8'
services:
  app:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./database:/app/database
      - ./logs:/app/logs
      - ./static:/app/static
    environment:
      - DATABASE_URL=sqlite:///./database/attendance.db
      - ZKTECO_HOST=192.168.100.209
      - ZKTECO_PORT=4370
      - LOG_LEVEL=INFO
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
EOF

# 3. Create Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -r -s /bin/bash app
RUN chown -R app:app /app
USER app

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:5000/health || exit 1

# Start application
CMD ["uvicorn", "app.main_unified:app", "--host", "0.0.0.0", "--port", "5000"]
EOF

# 4. Build and run
docker-compose up -d
```

### Method 3: Systemd Service Installation

```bash
# 1. Complete standard installation first
# 2. Create systemd service file
sudo tee /etc/systemd/system/fingerprint-logger.service > /dev/null << 'EOF'
[Unit]
Description=Fingerprint Time Logger
After=network.target

[Service]
Type=simple
User=fingerprint-logger
Group=fingerprint-logger
WorkingDirectory=/opt/fingerprint-logger
Environment=PATH=/opt/fingerprint-logger/venv/bin
ExecStart=/opt/fingerprint-logger/venv/bin/uvicorn app.main_unified:app --host 0.0.0.0 --port 5000 --workers 1
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/fingerprint-logger
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

# 3. Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable fingerprint-logger
sudo systemctl start fingerprint-logger
sudo systemctl status fingerprint-logger
```

## Configuration

### Environment Variables

Create `/opt/fingerprint-logger/.env`:

```env
# Database Configuration
DATABASE_URL=sqlite:///./database/attendance.db

# ZKTeco Device Configuration
ZKTECO_HOST=192.168.100.209
ZKTECO_PORT=4370
ZKTECO_PASSWORD=0
ZKTECO_TIMEOUT=30

# Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=5000
DEBUG=False
LOG_LEVEL=INFO

# Auto-Import Configuration
AUTO_IMPORT_ENABLED=True
AUTO_IMPORT_INTERVAL_MINUTES=30

# Security Configuration
SECRET_KEY=your-secret-key-here
CORS_ORIGINS=http://localhost:5000

# Logging Configuration
LOG_FILE=/opt/fingerprint-logger/logs/app.log
LOG_MAX_SIZE=10MB
LOG_BACKUP_COUNT=5
```

### Application Configuration

Edit `app/core/config.py` if needed:

```python
class Settings(BaseSettings):
    # Database
    database_url: str = "sqlite:///./database/attendance.db"
    
    # ZKTeco Device
    zkteco_host: str = "192.168.100.209"
    zkteco_port: int = 4370
    zkteco_password: int = 0
    zkteco_timeout: int = 30
    
    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 5000
    debug: bool = False
    log_level: str = "INFO"
    
    # Auto-Import
    auto_import_enabled: bool = True
    auto_import_interval_minutes: int = 30
    
    class Config:
        env_file = ".env"
```

### Database Configuration

```bash
# Initialize database
cd /opt/fingerprint-logger
source venv/bin/activate
alembic -c database/alembic.ini upgrade head

# Verify database setup
python3 -c "
from app.core.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text('SELECT count(*) FROM devices'))
    print(f'Database initialized. Tables created.')
"
```

### Web Server Configuration (Optional)

For production deployments with high traffic, consider using Nginx as a reverse proxy:

```nginx
# /etc/nginx/sites-available/fingerprint-logger
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    location /static/ {
        alias /opt/fingerprint-logger/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

## Service Management

### Management Scripts

The system includes several management scripts in the `scripts/` directory:

#### Start Service
```bash
./scripts/start.sh
```

#### Stop Service  
```bash
./scripts/stop.sh
```

#### Restart Service
```bash
./scripts/restart.sh
```

#### Check Status
```bash
./scripts/status.sh
```

#### Health Check
```bash
./scripts/health.sh
```

### Systemd Commands

```bash
# Start service
sudo systemctl start fingerprint-logger

# Stop service
sudo systemctl stop fingerprint-logger

# Restart service
sudo systemctl restart fingerprint-logger

# Check status
sudo systemctl status fingerprint-logger

# View logs
sudo journalctl -u fingerprint-logger -f

# Enable auto-start
sudo systemctl enable fingerprint-logger

# Disable auto-start
sudo systemctl disable fingerprint-logger
```

### Docker Commands

```bash
# Start containers
docker-compose up -d

# Stop containers
docker-compose down

# View logs
docker-compose logs -f

# Restart containers
docker-compose restart

# Check status
docker-compose ps

# Update containers
docker-compose pull
docker-compose up -d
```

## Monitoring & Maintenance

### Health Monitoring

The system provides several health check endpoints:

```bash
# Overall system health
curl http://localhost:5000/health

# API health
curl http://localhost:5000/api/system/health

# Device health
curl http://localhost:5000/api/devices/health

# Database health
curl http://localhost:5000/api/employees/health
```

### Log Monitoring

```bash
# Application logs
tail -f /opt/fingerprint-logger/logs/app.log

# System logs (systemd)
journalctl -u fingerprint-logger -f

# Access logs
tail -f /opt/fingerprint-logger/logs/access.log

# Error logs
tail -f /opt/fingerprint-logger/logs/error.log
```

### Performance Monitoring

```bash
# System metrics
curl http://localhost:5000/api/system/metrics

# Database performance
python3 -c "
from app.core.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text('PRAGMA table_info(attendance_records)'))
    print('Database schema OK')
"

# Disk usage
df -h /opt/fingerprint-logger/database/
```

### Automated Monitoring Script

Create `/opt/fingerprint-logger/scripts/monitor.sh`:

```bash
#!/bin/bash
# System health monitoring script

LOG_FILE="/opt/fingerprint-logger/logs/monitor.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

# Check service status
if systemctl is-active --quiet fingerprint-logger; then
    echo "[$DATE] Service: OK" >> $LOG_FILE
else
    echo "[$DATE] Service: FAILED" >> $LOG_FILE
    # Send alert (email, Slack, etc.)
fi

# Check API health
if curl -f -s http://localhost:5000/health > /dev/null; then
    echo "[$DATE] API: OK" >> $LOG_FILE
else
    echo "[$DATE] API: FAILED" >> $LOG_FILE
    # Send alert
fi

# Check database
if python3 -c "from app.core.database import engine; engine.connect()"; then
    echo "[$DATE] Database: OK" >> $LOG_FILE
else
    echo "[$DATE] Database: FAILED" >> $LOG_FILE
    # Send alert
fi

# Check disk space
DISK_USAGE=$(df -h /opt/fingerprint-logger | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "[$DATE] Disk: WARNING (${DISK_USAGE}% used)" >> $LOG_FILE
    # Send alert
fi
```

Add to crontab:
```bash
# Run every 5 minutes
*/5 * * * * /opt/fingerprint-logger/scripts/monitor.sh
```

## Backup & Recovery

### Database Backup

```bash
#!/bin/bash
# Database backup script

BACKUP_DIR="/opt/fingerprint-logger/backups"
DATE=$(date '+%Y%m%d_%H%M%S')
DB_FILE="/opt/fingerprint-logger/database/attendance.db"

# Create backup directory
mkdir -p $BACKUP_DIR

# Create database backup
sqlite3 $DB_FILE ".backup $BACKUP_DIR/attendance_backup_$DATE.db"

# Compress backup
gzip "$BACKUP_DIR/attendance_backup_$DATE.db"

# Remove old backups (keep last 30 days)
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete

echo "Backup completed: attendance_backup_$DATE.db.gz"
```

### Full System Backup

```bash
#!/bin/bash
# Full system backup script

BACKUP_DIR="/backups/fingerprint-logger"
DATE=$(date '+%Y%m%d_%H%M%S')
SOURCE_DIR="/opt/fingerprint-logger"

# Create backup directory
mkdir -p $BACKUP_DIR

# Stop service
sudo systemctl stop fingerprint-logger

# Create backup
tar -czf "$BACKUP_DIR/fingerprint-logger_$DATE.tar.gz" \
    -C $(dirname $SOURCE_DIR) \
    --exclude='venv' \
    --exclude='logs/*.log' \
    --exclude='__pycache__' \
    --exclude='.git' \
    $(basename $SOURCE_DIR)

# Start service
sudo systemctl start fingerprint-logger

# Remove old backups
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "Full backup completed: fingerprint-logger_$DATE.tar.gz"
```

### Recovery Procedures

#### Database Recovery

```bash
# Stop service
sudo systemctl stop fingerprint-logger

# Restore database from backup
cd /opt/fingerprint-logger
gunzip -c backups/attendance_backup_YYYYMMDD_HHMMSS.db.gz > database/attendance.db

# Set permissions
chown fingerprint-logger:fingerprint-logger database/attendance.db

# Start service
sudo systemctl start fingerprint-logger

# Verify recovery
curl http://localhost:5000/health
```

#### Full System Recovery

```bash
# Extract backup
cd /opt
tar -xzf /backups/fingerprint-logger/fingerprint-logger_YYYYMMDD_HHMMSS.tar.gz

# Set permissions
chown -R fingerprint-logger:fingerprint-logger /opt/fingerprint-logger

# Recreate virtual environment
cd /opt/fingerprint-logger
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start service
sudo systemctl start fingerprint-logger
```

## Troubleshooting

### Common Issues

#### Service Won't Start

```bash
# Check service status
sudo systemctl status fingerprint-logger

# Check logs
sudo journalctl -u fingerprint-logger -n 50

# Check port availability
netstat -tlnp | grep 5000

# Check file permissions
ls -la /opt/fingerprint-logger/
```

#### Database Connection Issues

```bash
# Check database file
ls -la /opt/fingerprint-logger/database/attendance.db

# Test database connection
python3 -c "
from app.core.database import engine
try:
    engine.connect()
    print('Database connection: OK')
except Exception as e:
    print(f'Database error: {e}')
"

# Check database integrity
sqlite3 /opt/fingerprint-logger/database/attendance.db "PRAGMA integrity_check;"
```

#### Device Connection Issues

```bash
# Test network connectivity
ping 192.168.100.209

# Test port connectivity
telnet 192.168.100.209 4370

# Check device configuration
python3 -c "
from app.services.zk_client import zk_client
try:
    status = zk_client.get_status()
    print(f'Device status: {status}')
except Exception as e:
    print(f'Device error: {e}')
"
```

#### Performance Issues

```bash
# Check CPU usage
top -p $(pgrep -f "fingerprint-logger")

# Check memory usage
ps aux | grep "fingerprint-logger"

# Check disk I/O
iotop -p $(pgrep -f "fingerprint-logger")

# Check database performance
sqlite3 /opt/fingerprint-logger/database/attendance.db "
SELECT COUNT(*) FROM attendance_records;
.timer on
SELECT * FROM attendance_records LIMIT 100;
"
```

### Debug Mode

Enable debug mode for troubleshooting:

```bash
# Edit .env file
DEBUG=True
LOG_LEVEL=DEBUG

# Restart service
sudo systemctl restart fingerprint-logger

# Monitor debug logs
tail -f /opt/fingerprint-logger/logs/app.log
```

### Log Analysis

```bash
# Error analysis
grep -i "error" /opt/fingerprint-logger/logs/app.log | tail -20

# Performance analysis
grep -i "slow" /opt/fingerprint-logger/logs/app.log | tail -10

# Device connection analysis
grep -i "device" /opt/fingerprint-logger/logs/app.log | tail -20
```

## Security Considerations

### Network Security

- Configure firewall to restrict access to port 5000
- Use VPN for remote access
- Enable HTTPS in production
- Regularly update system packages

### Application Security

- Change default passwords
- Implement proper user authentication if needed
- Regular security updates
- Monitor access logs

### Data Security

- Encrypt database backups
- Secure file permissions
- Regular security audits
- Compliance with data protection regulations

## Support

For additional support:

1. Check the logs for error messages
2. Review the troubleshooting section
3. Consult the API documentation
4. Contact system administrator

## Changelog

### Version 1.0 (January 2025)
- Initial deployment guide
- Systemd service configuration
- Docker deployment support
- Comprehensive monitoring setup
- Backup and recovery procedures