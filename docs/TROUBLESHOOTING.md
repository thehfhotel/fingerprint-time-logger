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

### 🐳 Docker Build Issues

#### Docker BuildX Cache Problems (Cache Not Clearing)

**Symptoms:**
- File changes not reflected in built container
- `docker buildx bake --no-cache` still uses cached layers
- Container serves old versions of updated files
- Build appears successful but changes are missing

**Root Cause:**
Docker BuildX uses BuildKit's internal cache system, which is separate from regular Docker cache. The `--no-cache` flag for `docker buildx bake` doesn't clear BuildKit's internal cache, causing file changes to be ignored.

**Solutions:**

1. **Clear BuildKit Cache (Immediate Fix)**
   ```bash
   # Clear all BuildKit cache
   docker buildx prune -f

   # Then rebuild
   docker buildx bake --load fingerprint-logger

   # Or use the manage-app.sh script
   ./scripts/manage-app.sh deploy --fresh-build
   ```

2. **Automatic Cache Management (Enhanced Script)**
   ```bash
   # Use the enhanced cache management features
   ./scripts/manage-app.sh cache-status     # Check cache state
   ./scripts/manage-app.sh cache-clear      # Clear all build caches
   ./scripts/manage-app.sh deploy --fresh-build  # Force fresh build
   ```

3. **Cache State Detection**
   The system can detect stale cache by monitoring:
   - Dockerfile modifications
   - requirements.txt changes
   - Source code updates (app/*)
   - Configuration file changes

   **Cache staleness indicators:**
   ```bash
   # Check what files have changed since last build
   find . -name "Dockerfile" -newer .docker-cache-state
   find . -name "requirements*.txt" -newer .docker-cache-state
   find app/ -name "*.py" -newer .docker-cache-state
   ```

**Prevention:**

1. **Use Enhanced Build Script**
   ```bash
   # The manage-app.sh script now includes intelligent cache management
   export CACHE_STRATEGY=auto  # Automatically detect stale cache
   ./scripts/manage-app.sh start
   ```

2. **Regular Cache Maintenance**
   ```bash
   # Add to crontab for weekly cache cleanup
   0 2 * * 0 docker buildx prune -f
   ```

3. **Environment Variables for Cache Control**
   ```bash
   # Set cache strategy
   export CACHE_STRATEGY=auto          # auto|fresh|preserve
   export CACHE_STALENESS_HOURS=24     # Hours before cache considered stale
   export CACHE_DEBUG=true             # Enable verbose cache logging
   ```

#### Container Shows Old Files After Build

**Symptoms:**
- Recent code changes not visible in running container
- JavaScript/CSS files show old versions
- Configuration changes ignored

**Diagnostic Steps:**
1. **Check if files exist in container:**
   ```bash
   docker exec fingerprint-time-logger ls -la /app/static/js/config.js
   docker exec fingerprint-time-logger head -10 /app/static/js/config.js
   ```

2. **Verify file timestamps:**
   ```bash
   # Compare host vs container file times
   ls -la static/js/config.js
   docker exec fingerprint-time-logger ls -la /app/static/js/config.js
   ```

3. **Check Docker layer caching:**
   ```bash
   # Review build output for CACHED vs copied layers
   docker buildx bake --progress=plain fingerprint-logger 2>&1 | grep -E "(COPY|CACHED)"
   ```

**Solutions:**
1. **Force fresh build with cache clear:**
   ```bash
   ./scripts/manage-app.sh deploy --fresh-build
   ```

2. **Manual cache clearing:**
   ```bash
   docker buildx prune -f
   docker system prune -f  # If using docker-compose
   docker buildx bake --load fingerprint-logger
   docker-compose restart
   ```

#### Build Cache Size Issues

**Symptoms:**
- Docker taking up excessive disk space
- Build cache consuming GBs of storage
- System running out of disk space

**Solutions:**

1. **Check cache size:**
   ```bash
   docker system df         # Show Docker space usage
   docker buildx du         # Show buildx cache size
   ```

2. **Selective cache cleaning:**
   ```bash
   # Clear only build cache
   docker buildx prune -f

   # Clear all unused Docker objects
   docker system prune -a -f

   # Clear everything including volumes (DANGEROUS)
   docker system prune -a --volumes -f
   ```

3. **Automated cache management:**
   ```bash
   # Set up automated cache cleanup
   cat > /etc/cron.weekly/docker-cleanup << 'EOF'
   #!/bin/bash
   # Clean up Docker build cache weekly
   docker buildx prune -f --filter until=168h
   docker system prune -f --filter until=168h
   EOF
   chmod +x /etc/cron.weekly/docker-cleanup
   ```

#### Docker Compose vs Docker Bake Cache Issues

**Symptoms:**
- Different behavior between build methods
- Cache issues vary by build tool used

**Understanding the Difference:**

- **Docker Compose**: Uses regular Docker builder
  - Cache cleared with: `docker-compose build --no-cache`
  - System cache: `docker system prune -f`

- **Docker Bake**: Uses BuildKit builder
  - Cache cleared with: `docker buildx prune -f`
  - More advanced caching but can be stickier

**Solutions:**

1. **For Docker Compose builds:**
   ```bash
   docker-compose down
   docker system prune -f
   docker-compose build --no-cache
   docker-compose up -d
   ```

2. **For Docker Bake builds:**
   ```bash
   docker buildx prune -f
   docker buildx bake --load fingerprint-logger
   docker-compose restart
   ```

3. **Universal cache clearing (all methods):**
   ```bash
   # Clear everything
   docker buildx prune -f
   docker system prune -a -f

   # Rebuild with preferred method
   ./scripts/manage-app.sh deploy --fresh-build
   ```

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

### ZK reader: "TCP packet invalid" bursts / "unpack requires a buffer of 8 bytes"

**Symptoms:**
- A paging Slack message in `#zk-time-sync`, e.g. `🚨 ZK Sync FAILED 2 consecutive checks since 20:21 - Main Fingerprint Device: TCP packet invalid`
- In the container journal (`docker logs fingerprint-time-logger` / `journalctl CONTAINER_NAME=fingerprint-time-logger`), a burst of:
  ```
  WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): error('unpack requires a buffer of 8 bytes')
  WARNING:app.services.zk_session:[zk_session.stream] disconnect error: TCP packet invalid
  WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
  ```

**What it means:**

The ZKTeco reader allows exactly one TCP session on port 4370. Any *other* TCP client that connects to the device — even a bare port probe with no ZK protocol traffic — evicts our live-capture session. `unpack requires a buffer of 8 bytes` is the live-capture socket read hitting the truncated/garbage reply from the eviction; `TCP packet invalid` is every reconnect attempt landing while the device is still in its post-eviction confused state. This is not our code failing and not the device being down.

The client self-heals: it reconnects with a backoff (`ZK_KICK_BACKOFF_SECONDS`, doubling up to a cap while evictions keep recurring, resetting after a quiet gap — see `app/services/zk_session.py`), then does a full catch-up read of the device's attendance buffer. Live punches during the eviction window are not lost — they are recovered by that catch-up (`new=0` in the log once the buffer matches what we already have; a nonzero `new=` means it just backfilled real punches). Typical full cycle is well under a minute per eviction.

**How to confirm:**
```bash
# Signature lines for a given window (primary confirmation)
journalctl CONTAINER_NAME=fingerprint-time-logger --since "16:00" --until "16:30" \
  | grep -E "unpack requires a buffer of 8 bytes|TCP packet invalid"

# Eviction rate the app itself is tracking, read directly from the cache
# inside the container — do NOT curl /api/private/devices/status for this:
# that route is mounted behind `Depends(require_cf_access)` in
# app/main_unified.py, which enforces a Cloudflare Access JWT for EVERY
# caller including localhost/in-container, so a plain curl 401s and
# `jq .data.stream_kicks_last_hour` prints `null` — indistinguishable from
# "zero kicks" during a real incident.
docker exec fingerprint-time-logger python -c "from app.services.device_cache_service import device_cache_service; s = device_cache_service.get_raw('device_status') or {}; print('stream_kicks_last_hour =', s.get('stream_kicks_last_hour'))"
```
`stream_kicks_last_hour` is populated by the 5-minute status/time job (`app/services/background_scheduler.py`) from `zk_session.stream_kicks_in()`. The HTTP route (`/api/private/devices/status`) also carries this field in its JSON, but only for a caller that can pass Cloudflare Access — use the `docker exec` command above for a direct, CF-Access-free read.

**When to act:**
- A **non-paging "degraded" Slack note** ("⚠️ ZK reader session evicted N× in the last 60 min") means ≥`ZK_KICK_DEGRADED_THRESHOLD` (default 3) evictions in the trailing hour — informational, rate-limited to once/hour. No action needed unless it keeps repeating for hours.
- A **paging alert** means ≥`ZK_SYNC_PAGE_AFTER_FAILURES` (default 2) *consecutive* 5-minute status checks actually failed — i.e. the device was unreachable across two full poll cycles, not just caught mid-eviction once. That's worth investigating as a real outage (device power/network, not just a session kick).
- If either keeps firing for hours rather than clearing within a few minutes, escalate — see the root fix below and the incident writeup.

**Root fix (not yet applied):** restrict inbound TCP/4370 on `192.168.100.209` to the evergreen host (`192.168.100.228`) only, via switch/AP ACL or a firewall rule on the device's segment — this is the only way to stop a second client from evicting our session in the first place. Full details, timeline, and evidence: [docs/incidents/2026-09-05-zk-session-evictions.md](incidents/2026-09-05-zk-session-evictions.md).

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