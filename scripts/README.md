# Scripts

Management scripts for fingerprint time logger.

## Usage

```bash
./scripts/start.sh     # Start services
./scripts/stop.sh      # Stop services  
./scripts/restart.sh   # Restart services
./scripts/status.sh    # Check status
./scripts/health.sh    # Quick health check
```

## Scripts

| Script | Purpose |
|--------|---------|
| `start.sh` | Start API (8000) + Dashboard (5000) |
| `stop.sh` | Stop all services |
| `restart.sh` | Restart with health checks |
| `status.sh` | Full system diagnostics |
| `health.sh` | Quick health check (exit codes) |

## Health Check Exit Codes

- `0` = Healthy
- `1` = Partial  
- `2` = Down

## Access

- Dashboard: http://localhost:5000
- API: http://localhost:8000
- Docs: http://localhost:8000/docs

## Files

- PIDs: `pids/api.pid`, `pids/dashboard.pid`
- Logs: `logs/api.log`, `logs/dashboard.log`
- DB: `attendance.db`

## Troubleshooting

```bash
# Check logs
tail -f logs/*.log

# Force restart
./scripts/stop.sh && ./scripts/start.sh

# Port conflicts
ss -tlnp | grep :8000
```