# Scripts

Management scripts for fingerprint time logger.

## Usage

```bash
./scripts/start.sh     # Start unified server
./scripts/stop.sh      # Stop server  
./scripts/restart.sh   # Restart server
./scripts/status.sh    # Check status
./scripts/health.sh    # Quick health check
```

## Scripts

| Script | Purpose |
|--------|---------|
| `start.sh` | Start unified FastAPI server on port 5000 |
| `stop.sh` | Stop unified server |
| `restart.sh` | Restart server with health checks |
| `status.sh` | Full system diagnostics |
| `health.sh` | Quick health check (exit codes) |

## Simple Scripts

For quick, no-frills management:

| Script | Purpose |
|--------|---------|
| `start_simple.sh` | Basic server startup |
| `stop_simple.sh` | Basic server shutdown |
| `status_simple.sh` | Simple status check |

## Health Check Exit Codes

- `0` = Healthy
- `1` = Partial/Warning  
- `2` = Down/Critical

## Access

- Dashboard: http://localhost:5000
- API Health: http://localhost:5000/api/devices/health
- API Docs: http://localhost:5000/docs

## Files

- PID: `pids/unified_server.pid`
- Log: `logs/unified_server.log`
- DB: `database/attendance.db`

## Python Scripts

| Script | Purpose |
|--------|---------|
| `test_device_connection.py` | Test ZKTeco device connectivity |
| `display_attendance.py` | Show attendance records from device |
| `debug_data.py` | Debug attendance data |
| `migrate_thai_names.py` | Migrate Thai names to database |

## Troubleshooting

```bash
# Check logs
tail -f logs/unified_server.log

# Force restart
./scripts/stop.sh && ./scripts/start.sh

# Port conflicts
ss -tlnp | grep :5000

# Test device connection
python3 scripts/test_device_connection.py 192.168.100.209
```