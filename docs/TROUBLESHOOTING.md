# Troubleshooting Guide

## Quick Diagnosis

### System Health Check
```bash
# Check if services are running
./scripts/check_status.sh

# Test device connectivity
python scripts/test_device_connection.py 192.168.100.209

# View system status
./scripts/performance_summary.sh
```

### Log Files
- **API Logs**: `app.log`
- **Dashboard Logs**: `dashboard.log`
- **System Logs**: Console output during startup

## Common Issues

### 🔌 Device Connection Problems

#### "Connection refused" or "Timeout"

**Symptoms:**
- Cannot connect to ZKTeco device
- Error: "Failed to connect to device"
- Dashboard shows "Device disconnected"

**Causes & Solutions:**

1. **Network Connectivity**
   ```bash
   # Test basic network connection
   ping 192.168.100.209
   
   # Test TCP port connectivity
   telnet 192.168.100.209 4370
   ```
   
   **Solutions:**
   - Verify device IP address
   - Check network cable connections
   - Ensure device and server are on same network
   - Check firewall settings

2. **Device Configuration**
   ```bash
   # Verify device settings in app
   curl http://localhost:8000/api/devices/
   ```
   
   **Solutions:**
   - Confirm IP address in device configuration
   - Verify port number (default: 4370)
   - Check device password setting
   - Ensure device TCP/IP is enabled

3. **Device Busy**
   **Solutions:**
   - Wait for current operation to complete
   - Restart device if necessary
   - Check if other software is connected to device

#### "Device time drift detected"

**Symptoms:**
- Warning messages about device time
- Incorrect timestamps in attendance records

**Solutions:**
```bash
# Manual time sync test
python scripts/display_attendance.py 192.168.100.209
```

- System will automatically sync time if drift > 60 seconds
- Manually set device time through device interface
- Ensure device has stable power supply
- Check device RTC battery if time keeps drifting

### 💾 Database Issues

#### "Database is locked" (SQLite)

**Symptoms:**
- API returns 500 errors
- "Database is locked" error messages
- Operations hang or timeout

**Causes & Solutions:**

1. **Multiple Connections**
   ```bash
   # Check for running processes
   ps aux | grep python
   ps aux | grep uvicorn
   
   # Kill hanging processes
   pkill -f "uvicorn app.main:app"
   pkill -f "dashboard_app.py"
   ```

2. **Database Corruption**
   ```bash
   # Check database integrity
   sqlite3 attendance.db "PRAGMA integrity_check;"
   
   # Backup and repair if needed
   cp attendance.db attendance_backup.db
   sqlite3 attendance.db ".dump" | sqlite3 attendance_repaired.db
   ```

3. **Long-running Transactions**
   - Restart API server
   - Check for infinite loops in code
   - Review recent database operations

#### "No such table" errors

**Symptoms:**
- API returns table not found errors
- Fresh installation issues

**Solutions:**
```bash
# Apply database migrations
alembic upgrade head

# If migrations don't exist, create them
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head

# Check current database schema
sqlite3 attendance.db ".schema"
```

### 🌐 API Server Issues

#### API Server Won't Start

**Symptoms:**
- "Address already in use" error
- uvicorn startup fails
- Port 8000 not accessible

**Solutions:**

1. **Port Already in Use**
   ```bash
   # Find process using port 8000
   lsof -i :8000
   netstat -tulpn | grep 8000
   
   # Kill process
   kill -9 <PID>
   
   # Or use different port
   uvicorn app.main:app --port 8001
   ```

2. **Import Errors**
   ```bash
   # Check virtual environment
   which python
   pip list | grep fastapi
   
   # Reinstall dependencies
   pip install -r requirements.txt
   ```

3. **Configuration Issues**
   ```bash
   # Check environment variables
   env | grep DATABASE_URL
   
   # Test configuration
   python -c "from app.core.config import settings; print(settings.database_url)"
   ```

#### "404 Not Found" for API endpoints

**Symptoms:**
- API endpoints return 404
- Swagger UI shows no endpoints

**Solutions:**
- Check if API server is running on correct port
- Verify router inclusion in main.py
- Check endpoint URLs in browser/curl
- Review FastAPI app configuration

### 🖥️ Dashboard Issues

#### Dashboard Not Loading

**Symptoms:**
- Browser shows connection refused
- Dashboard page doesn't load
- Port 5000 not accessible

**Solutions:**

1. **Flask Server Not Running**
   ```bash
   # Start dashboard manually
   python dashboard_app.py
   
   # Check if port is available
   lsof -i :5000
   ```

2. **Template Issues**
   ```bash
   # Check template file exists
   ls templates/dashboard.html
   
   # Check Flask template directory configuration
   ```

#### Dashboard Shows No Data

**Symptoms:**
- Dashboard loads but shows empty data
- "No employees found" messages
- Missing attendance records

**Solutions:**

1. **Device Sync Issues**
   ```bash
   # Manual data refresh
   curl -X POST http://localhost:8000/api/refresh
   
   # Check sync status
   curl http://localhost:8000/api/sync/status
   ```

2. **Employee Data Missing**
   ```bash
   # Check if employees exist
   curl http://localhost:8000/api/employees/
   
   # Add test employee
   curl -X POST http://localhost:8000/api/employees/ \
     -H "Content-Type: application/json" \
     -d '{"employee_id": "999", "name": "Test User"}'
   ```

3. **Date Range Issues**
   - Check if attendance data is within displayed date range
   - Verify device time is accurate
   - Check filter settings in dashboard

### 📊 Data Sync Issues

#### No Attendance Records Retrieved

**Symptoms:**
- Sync completes but no records added
- Device has data but database is empty
- Sync logs show 0 records processed

**Causes & Solutions:**

1. **Employee ID Mismatch**
   ```bash
   # Check device users vs database employees
   python scripts/display_attendance.py 192.168.100.209
   curl http://localhost:8000/api/employees/
   ```
   
   **Solutions:**
   - Ensure employee IDs in database match device user IDs
   - Add missing employees to database
   - Check employee ID format (string vs number)

2. **Date Filtering**
   - Device records may be outside expected date range
   - Check device time accuracy
   - Review sync date filters

3. **Record Duplicates**
   - System skips existing records to prevent duplicates
   - Check if records already exist in database
   - Review sync logic for duplicate detection

#### Sync Fails with Errors

**Symptoms:**
- Sync status shows "failed"
- Error messages in sync logs
- Partial data synchronization

**Solutions:**

1. **Check Sync Logs**
   ```bash
   # View recent sync logs
   curl http://localhost:8000/api/sync/logs?limit=10
   
   # Check specific failed sync
   curl http://localhost:8000/api/sync/logs/123
   ```

2. **Device Operation Issues**
   ```bash
   # Test device operations manually
   python scripts/test_device_connection.py 192.168.100.209
   python scripts/display_attendance.py 192.168.100.209 -d 1
   ```

3. **Memory or Timeout Issues**
   - Reduce sync batch size
   - Increase timeout values
   - Clear device data after successful sync

### 🔧 Performance Issues

#### Slow API Responses

**Symptoms:**
- API calls take several seconds
- Dashboard loading slowly
- Database queries timeout

**Solutions:**

1. **Database Optimization**
   ```bash
   # Check database size
   ls -lh attendance.db
   
   # Analyze query performance
   # Enable SQL logging in development
   ```

2. **Large Dataset Issues**
   ```bash
   # Check record counts
   sqlite3 attendance.db "SELECT COUNT(*) FROM attendance_records;"
   
   # Clean up old data
   curl -X DELETE "http://localhost:8000/api/sync/logs/old?days=30"
   ```

3. **Device Sync Blocking**
   - Device operations are synchronous and may block API
   - Schedule syncs during low-usage periods
   - Consider manual sync instead of automatic

#### High Memory Usage

**Symptoms:**
- System becomes slow
- Out of memory errors
- Process crashes

**Solutions:**

1. **Dashboard Memory Usage**
   ```bash
   # Check process memory
   ps aux | grep python
   top -p <PID>
   ```
   
   - Restart dashboard periodically
   - Reduce data refresh frequency
   - Limit displayed data range

2. **Database Growth**
   ```bash
   # Database cleanup
   sqlite3 attendance.db "DELETE FROM sync_logs WHERE completed_at < date('now', '-30 days');"
   sqlite3 attendance.db "VACUUM;"
   ```

## Error Messages Reference

### Device Errors

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Connection timeout" | Network/device issue | Check network, restart device |
| "Invalid device response" | Device firmware issue | Update device firmware |
| "Device busy" | Another connection active | Wait or restart device |
| "Authentication failed" | Wrong device password | Check password setting |

### Database Errors

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "Database is locked" | Multiple connections | Restart services |
| "No such table" | Missing migrations | Run `alembic upgrade head` |
| "Integrity constraint" | Duplicate/invalid data | Check data constraints |
| "Disk I/O error" | Storage issue | Check disk space |

### API Errors

| Error Message | Cause | Solution |
|---------------|-------|----------|
| "404 Not Found" | Wrong endpoint URL | Check API documentation |
| "422 Validation Error" | Invalid request data | Check request format |
| "500 Internal Server Error" | Server-side issue | Check server logs |
| "Connection refused" | Server not running | Start API server |

## Recovery Procedures

### Complete System Reset

1. **Stop All Services**
   ```bash
   pkill -f uvicorn
   pkill -f dashboard_app
   ```

2. **Backup Data**
   ```bash
   cp attendance.db backup/attendance_$(date +%Y%m%d).db
   ```

3. **Reset Database** (if needed)
   ```bash
   rm attendance.db
   alembic upgrade head
   ```

4. **Restart Services**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
   python dashboard_app.py &
   ```

### Database Recovery

1. **Backup Current Database**
   ```bash
   cp attendance.db attendance_corrupted.db
   ```

2. **Export Data**
   ```bash
   sqlite3 attendance.db ".dump" > attendance_dump.sql
   ```

3. **Create New Database**
   ```bash
   rm attendance.db
   alembic upgrade head
   ```

4. **Import Data**
   ```bash
   sqlite3 attendance.db < attendance_dump.sql
   ```

### Device Re-registration

1. **Clear Device Configuration**
   ```bash
   curl -X DELETE http://localhost:8000/api/devices/1
   ```

2. **Add Device Again**
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

3. **Test Connection**
   ```bash
   python scripts/test_device_connection.py 192.168.100.209
   ```

## Prevention Tips

### Regular Maintenance

1. **Daily Checks**
   - Verify device connectivity
   - Check sync status
   - Review error logs

2. **Weekly Tasks**
   - Backup database
   - Clean up old sync logs
   - Export attendance reports

3. **Monthly Tasks**
   - Review system performance
   - Update employee information
   - Check device firmware

### Monitoring Setup

```bash
# Create monitoring script
cat > monitor.sh << 'EOF'
#!/bin/bash
# Check API health
curl -f http://localhost:8000/health || echo "API DOWN"

# Check device connectivity
python scripts/test_device_connection.py 192.168.100.209 || echo "DEVICE DOWN"

# Check database size
SIZE=$(stat -f%z attendance.db 2>/dev/null || stat -c%s attendance.db)
if [ $SIZE -gt 100000000 ]; then
    echo "DATABASE SIZE WARNING: $SIZE bytes"
fi
EOF

chmod +x monitor.sh

# Run daily via cron
echo "0 9 * * * /path/to/monitor.sh" | crontab -
```

### Backup Strategy

```bash
# Create backup script
cat > backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p backups

# Database backup
cp attendance.db backups/attendance_${DATE}.db

# Export CSV reports
curl "http://localhost:8000/api/reports/export/daily/$(date +%Y-%m-%d)" > backups/daily_${DATE}.csv

# Clean old backups (keep 30 days)
find backups/ -name "*.db" -mtime +30 -delete
find backups/ -name "*.csv" -mtime +30 -delete
EOF

chmod +x backup.sh

# Schedule backup
echo "0 18 * * * /path/to/backup.sh" | crontab -
```

## Getting Help

### Log Analysis
```bash
# Recent API errors
grep ERROR app.log | tail -20

# Dashboard issues
grep ERROR dashboard.log | tail -20

# System resource usage
top -b -n1 | head -20
```

### System Information
```bash
# System details for support
echo "OS: $(uname -a)"
echo "Python: $(python --version)"
echo "Database size: $(ls -lh attendance.db)"
echo "Services: $(ps aux | grep -E '(uvicorn|dashboard)' | grep -v grep)"
```

### Support Checklist
When requesting help, provide:
- [ ] Error messages from logs
- [ ] System information (OS, Python version)
- [ ] Device model and firmware version
- [ ] Network configuration details
- [ ] Steps to reproduce the issue
- [ ] Recent changes to system or configuration

---

*For additional support, review the system logs and error messages for specific diagnostic information.*