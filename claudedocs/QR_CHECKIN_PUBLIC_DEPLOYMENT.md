# QR Check-in Public Service Deployment Guide

Complete guide for deploying QR Check-in as a separate internet-accessible service using Cloudflare Workers and dual Docker services.

---

## Architecture Overview

### Current Production Architecture

```
Internet → Cloudflare (CDN/Proxy) → Docker Containers (Direct)
                                            ↓
                                      Port 5000 (Internal)
                                      FastAPI App @ /fingerprintlogs/
```

**Key Discovery**: Cloudflare proxies **directly** to Docker containers on port 5000, bypassing local nginx for external traffic.

- **External URL**: `https://emp.thehfhotel.org/fingerprintlogs/*`
- **Cloudflare Proxy**: `→ http://192.168.100.228:5000`
- **Local Nginx**: Used for internal network access only (ports 80/443)

### Target Architecture: Dual Services

```
┌─────────────────────────────────────────────────────────────────┐
│                      Internet Traffic                            │
└────────────┬───────────────────────────────┬────────────────────┘
             │                               │
    ┌────────▼─────────┐          ┌─────────▼──────────┐
    │ emp.thehfhotel   │          │ erp.thehfhotel     │
    │ .org/fingerprint │          │ .org/qr-checkin/*  │
    │ logs/*           │          │                    │
    └────────┬─────────┘          └─────────┬──────────┘
             │                               │
    ┌────────▼─────────┐          ┌─────────▼──────────┐
    │ Cloudflare       │          │ Cloudflare Worker  │
    │ Direct Proxy     │          │ (URL Rewriting)    │
    └────────┬─────────┘          └─────────┬──────────┘
             │                               │
             │                               │ Rewrites:
             │                               │ /qr-checkin/* →
             │                               │ /fingerprintlogs/qr-checkin/*
             │                               │
    ┌────────▼─────────┐          ┌─────────▼──────────┐
    │ :5000 Internal   │          │ :5001 Public       │
    │ Full Features    │          │ QR Only            │
    │ ✅ Admin         │          │ ❌ Admin           │
    │ ✅ Dashboard     │          │ ❌ Dashboard       │
    │ ✅ Devices       │          │ ❌ Devices         │
    │ ✅ QR Check-in   │          │ ✅ QR Check-in     │
    └────────┬─────────┘          └─────────┬──────────┘
             │                               │
             └──────── Shared Database ──────┘
                   (SQLite WAL Mode)
```

---

## Implementation Guide

### Part 1: Docker Compose Dual Services

#### Step 1.1: Enable SQLite WAL Mode

Before running dual services, enable Write-Ahead Logging for concurrent database access:

```bash
sqlite3 database/attendance.db "PRAGMA journal_mode=WAL;"
sqlite3 database/attendance.db "PRAGMA synchronous=NORMAL;"
```

Verify:
```bash
sqlite3 database/attendance.db "PRAGMA journal_mode;"
# Should return: wal
```

#### Step 1.2: Update docker-compose.yml

Add second service to existing `docker-compose.yml`:

```yaml
services:
  # Internal Service - Port 5000 (existing)
  app-internal:
    image: fingerprint-time-logger:latest
    build:
      context: .
      target: fingerprint-logger
    container_name: fingerprint-logger-internal
    ports:
      - "5000:5000"
    volumes:
      - ./database:/app/database
      - ./logs/internal:/app/logs
      - ./pids/internal:/app/pids
    environment:
      - SERVICE_MODE=internal
      - SERVICE_NAME=fingerprint-logger-internal
      - DATABASE_URL=sqlite:///./database/attendance.db
      - ZKTECO_HOST=${ZKTECO_HOST:-192.168.100.209}
      - ZKTECO_PORT=${ZKTECO_PORT:-4370}
      - TZ=Asia/Bangkok
      - LINE_CHANNEL_ID=${LINE_CHANNEL_ID}
      - LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET}
      - LINE_CALLBACK_URL=${LINE_CALLBACK_URL}
      - JWT_SECRET=${JWT_SECRET}
      - ENABLE_ADMIN=true
      - ENABLE_DEVICE_SYNC=true
      - ENABLE_DASHBOARD=true
    restart: unless-stopped
    networks:
      - app-network

  # Public Service - Port 5001 (new)
  app-public:
    image: fingerprint-time-logger:latest
    build:
      context: .
      target: fingerprint-logger
    container_name: fingerprint-logger-public
    ports:
      - "5001:5000"  # Host 5001 → Container 5000
    volumes:
      - ./database:/app/database  # Shared database
      - ./logs/public:/app/logs
      - ./pids/public:/app/pids
    environment:
      - SERVICE_MODE=public
      - SERVICE_NAME=fingerprint-logger-public
      - DATABASE_URL=sqlite:///./database/attendance.db
      - TZ=Asia/Bangkok
      - LINE_CHANNEL_ID=${LINE_CHANNEL_ID}
      - LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET}
      - LINE_CALLBACK_URL_PUBLIC=${LINE_CALLBACK_URL_PUBLIC}
      - JWT_SECRET=${JWT_SECRET}
      - ENABLE_ADMIN=false
      - ENABLE_DEVICE_SYNC=false
      - ENABLE_DASHBOARD=false
      - ENABLE_RATE_LIMITING=true
      - RATE_LIMIT_PER_MINUTE=60
      - RATE_LIMIT_PER_HOUR=500
    restart: unless-stopped
    networks:
      - app-network

networks:
  app-network:
    driver: bridge
```

#### Step 1.3: Update .env

Add new environment variables:

```bash
# Existing internal callback
LINE_CALLBACK_URL=https://emp.thehfhotel.org/fingerprintlogs/api/auth/line/callback

# New public callback (will be set up in Cloudflare section)
LINE_CALLBACK_URL_PUBLIC=https://erp.thehfhotel.org/qr-checkin/api/auth/line/callback

# Rate limiting
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_PER_HOUR=500
```

---

### Part 2: Application Code Changes

#### Step 2.1: Create Service Configuration

Create `app/core/service_config.py`:

```python
"""
Service configuration based on deployment mode
Supports internal (full features) and public (QR check-in only) modes
"""

import os
from typing import Literal

ServiceMode = Literal["internal", "public"]

class ServiceConfig:
    """Service configuration based on SERVICE_MODE environment variable"""

    def __init__(self):
        self.mode: ServiceMode = os.getenv("SERVICE_MODE", "internal")
        self.name = os.getenv("SERVICE_NAME", "fingerprint-logger")

        # Feature flags
        self.enable_admin = os.getenv("ENABLE_ADMIN", "true").lower() == "true"
        self.enable_device_sync = os.getenv("ENABLE_DEVICE_SYNC", "true").lower() == "true"
        self.enable_dashboard = os.getenv("ENABLE_DASHBOARD", "true").lower() == "true"
        self.enable_rate_limiting = os.getenv("ENABLE_RATE_LIMITING", "false").lower() == "true"

        # Rate limiting configuration
        self.rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        self.rate_limit_per_hour = int(os.getenv("RATE_LIMIT_PER_HOUR", "500"))

    @property
    def is_public(self) -> bool:
        """Check if running in public mode"""
        return self.mode == "public"

    @property
    def is_internal(self) -> bool:
        """Check if running in internal mode"""
        return self.mode == "internal"

# Global service configuration
service_config = ServiceConfig()
```

#### Step 2.2: Update main_unified.py

Add conditional route registration:

```python
from app.core.service_config import service_config

# ... existing imports ...

# Always include QR check-in and LINE auth
fingerprint_app.include_router(line_auth.router, prefix="/api/auth/line", tags=["line-auth"])
fingerprint_app.include_router(qr_checkin.router, prefix="/api/qr-checkin", tags=["qr-checkin"])

# Conditional routers based on service mode
if service_config.enable_admin:
    fingerprint_app.include_router(admin_line_codes.router, prefix="/api/admin/line-codes", tags=["admin-line-codes"])
    fingerprint_app.include_router(system_status.router, prefix="/api/system", tags=["system-status"])

if service_config.is_internal:
    fingerprint_app.include_router(consolidated_attendance.router, prefix="/api/attendance", tags=["attendance"])
    fingerprint_app.include_router(consolidated_devices.router, prefix="/api/devices", tags=["devices"])
    fingerprint_app.include_router(consolidated_employees.router, prefix="/api/employees", tags=["employees"])

# Service info endpoint
@fingerprint_app.get("/api/service-info")
async def get_service_info():
    return {
        "service_name": service_config.name,
        "service_mode": service_config.mode,
        "features": {
            "admin": service_config.enable_admin,
            "device_sync": service_config.enable_device_sync,
            "dashboard": service_config.enable_dashboard,
            "rate_limiting": service_config.enable_rate_limiting
        }
    }

# Startup logging
@fingerprint_app.on_event("startup")
async def startup_event():
    print(f"🚀 Starting {service_config.name} in {service_config.mode} mode")
    print(f"   Admin: {service_config.enable_admin}")
    print(f"   Device Sync: {service_config.enable_device_sync}")
    print(f"   Dashboard: {service_config.enable_dashboard}")
    print(f"   Rate Limiting: {service_config.enable_rate_limiting}")
```

#### Step 2.3: Add Rate Limiting

Add `slowapi==0.1.9` to `requirements.txt`

Create `app/middleware/rate_limit.py`:

```python
"""Rate limiting middleware for public-facing API"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.service_config import service_config

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[
        f"{service_config.rate_limit_per_minute}/minute",
        f"{service_config.rate_limit_per_hour}/hour"
    ],
    enabled=service_config.enable_rate_limiting
)

def setup_rate_limiting(app):
    if service_config.enable_rate_limiting:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        print(f"✅ Rate limiting enabled: {service_config.rate_limit_per_minute}/min")
```

Update `main_unified.py`:
```python
from app.middleware.rate_limit import setup_rate_limiting
setup_rate_limiting(fingerprint_app)
```

#### Step 2.4: Update Database Connection

Add to `app/core/database.py`:

```python
from sqlalchemy import event

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable WAL mode and optimize SQLite for concurrent access"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")  # 5 second timeout
    cursor.close()
```

---

### Part 3: Cloudflare Worker Infrastructure-as-Code

#### Step 3.1: Worker Files Already Created

The following files have been created in `cloudflare-worker/`:

- ✅ `wrangler.toml` - Worker configuration
- ✅ `src/worker.js` - URL rewriting logic
- ✅ `package.json` - Dependencies and scripts
- ✅ `deploy.sh` - Deployment automation
- ✅ `README.md` - Complete documentation
- ✅ `.github/workflows/deploy-worker.yml` - CI/CD pipeline

#### Step 3.2: Install and Authenticate

```bash
cd cloudflare-worker
npm install
npx wrangler login
```

Or use API token:
```bash
# Get token from: https://dash.cloudflare.com/profile/api-tokens
echo "CLOUDFLARE_API_TOKEN=your_token_here" > .dev.vars
```

#### Step 3.3: Configure Zone

Find your zone ID:
1. Go to https://dash.cloudflare.com
2. Select domain: `thehfhotel.org`
3. Overview → Zone ID (right sidebar)

Update `wrangler.toml` line 10:
```toml
routes = [
    { pattern = "erp.thehfhotel.org/qr-checkin/*", zone_id = "YOUR_ZONE_ID" }
]
```

Or use zone name (auto-fetch):
```toml
routes = [
    { pattern = "erp.thehfhotel.org/qr-checkin/*", zone_name = "thehfhotel.org" }
]
```

#### Step 3.4: Deploy Worker

```bash
cd cloudflare-worker
npm run deploy:prod
```

Or interactive:
```bash
./deploy.sh
```

---

## Deployment Procedure

### Pre-Deployment Checklist

- [ ] SQLite WAL mode enabled and verified
- [ ] Log directories created: `mkdir -p logs/{internal,public} pids/{internal,public}`
- [ ] `.env` updated with public service variables
- [ ] LINE Developers Console updated with new callback URL
- [ ] Cloudflare account access verified
- [ ] Backup created: `cp database/attendance.db database/attendance.db.backup.$(date +%Y%m%d_%H%M%S)`

### Step 1: Deploy Docker Services

```bash
# Stop existing service
docker compose down

# Build and start dual services
docker compose build --no-cache
docker compose up -d

# Verify both running
docker ps | grep fingerprint-logger

# Check logs
docker logs fingerprint-logger-internal
docker logs fingerprint-logger-public
```

### Step 2: Test Local Services

```bash
# Test internal service
curl http://localhost:5000/fingerprintlogs/health
curl http://localhost:5000/fingerprintlogs/api/service-info | jq

# Test public service
curl http://localhost:5001/fingerprintlogs/qr-checkin/health
curl http://localhost:5001/fingerprintlogs/api/service-info | jq

# Verify admin blocked on public
curl -I http://localhost:5001/fingerprintlogs/api/admin/line-codes/stats?passcode=test
# Should return 404
```

### Step 3: Deploy Cloudflare Worker

```bash
cd cloudflare-worker
npm run deploy:prod
```

Verify deployment:
```bash
npx wrangler deployments list
```

### Step 4: Configure Cloudflare DNS

1. Go to Cloudflare Dashboard → DNS → Records
2. Add A record: `erp` → `192.168.100.228`
3. Enable proxy (orange cloud) ☁️
4. SSL/TLS → Full (or Full Strict with backend SSL)

### Step 5: Update LINE OAuth

Add new callback URL in LINE Developers Console:
- `https://erp.thehfhotel.org/qr-checkin/api/auth/line/callback`

### Step 6: Test Production URLs

```bash
# Internal service (existing)
curl -v https://emp.thehfhotel.org/fingerprintlogs/qr-checkin/mobile

# Public service (new)
curl -v https://erp.thehfhotel.org/qr-checkin/mobile
```

---

## Testing & Validation

### Internal Service Tests

- [ ] Dashboard: `https://emp.thehfhotel.org/fingerprintlogs/`
- [ ] Admin: `https://emp.thehfhotel.org/fingerprintlogs/api/admin/line-codes/stats?passcode=...`
- [ ] QR Mobile: `https://emp.thehfhotel.org/fingerprintlogs/qr-checkin/mobile`
- [ ] Device Status: `https://emp.thehfhotel.org/fingerprintlogs/device-status`

### Public Service Tests

- [ ] QR Mobile: `https://erp.thehfhotel.org/qr-checkin/mobile`
- [ ] QR Terminal: `https://erp.thehfhotel.org/qr-checkin/terminal`
- [ ] Link Account: `https://erp.thehfhotel.org/qr-checkin/link-account`
- [ ] LINE Login flow works correctly
- [ ] Admin endpoints return 404
- [ ] Dashboard returns 404
- [ ] Rate limiting triggers (test with 65+ requests)

### Database Concurrent Access Tests

```bash
# Both services should handle simultaneous operations
# Watch for "database is locked" errors in logs
docker logs fingerprint-logger-internal --tail 50 -f &
docker logs fingerprint-logger-public --tail 50 -f &

# Trigger simultaneous writes from both services
# (use QR check-in on public + admin operation on internal)
```

### Cloudflare Worker Tests

```bash
# Test URL rewriting
curl -v https://erp.thehfhotel.org/qr-checkin/mobile

# Verify backend receives correct path
docker logs fingerprint-logger-public --tail 10 | grep "GET /fingerprintlogs/qr-checkin/mobile"
```

---

## Monitoring & Maintenance

### Real-Time Logs

```bash
# Cloudflare Worker logs
cd cloudflare-worker
npm run tail

# Docker service logs
docker logs fingerprint-logger-internal -f
docker logs fingerprint-logger-public -f
```

### Health Monitoring

Create `scripts/monitor-dual-service.sh`:

```bash
#!/bin/bash
echo "📊 Dual Service Health Check"
echo "Generated: $(date)"
echo ""

# Service status
docker ps --filter "name=fingerprint-logger" --format "table {{.Names}}\t{{.Status}}"

# Health checks
echo ""
echo "Health Status:"
curl -s http://localhost:5000/fingerprintlogs/health | jq -r '.status // "ERROR"' | xargs echo "  Internal:"
curl -s http://localhost:5001/fingerprintlogs/qr-checkin/health | jq -r '.status // "ERROR"' | xargs echo "  Public:"

# Database
echo ""
echo "Database:"
du -h database/attendance.db | cut -f1 | xargs echo "  DB Size:"
du -h database/attendance.db-wal 2>/dev/null | cut -f1 | xargs echo "  WAL Size:" || echo "  WAL Size: N/A"

# Resource usage
echo ""
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
    fingerprint-logger-internal fingerprint-logger-public
```

Run hourly:
```bash
chmod +x scripts/monitor-dual-service.sh
0 * * * * /home/nut/fingerprint-time-logger/scripts/monitor-dual-service.sh >> logs/monitoring.log 2>&1
```

### Cloudflare Dashboard Metrics

1. https://dash.cloudflare.com
2. Workers & Pages → `qr-checkin-proxy`
3. Metrics:
   - Requests/second
   - Error rate
   - CPU time
   - Success rate

---

## Troubleshooting

### Worker Not Receiving Requests

**Check DNS:**
```bash
dig erp.thehfhotel.org
# Should show Cloudflare IPs, not 192.168.100.228 directly
```

**Verify Route:**
```bash
cd cloudflare-worker
npx wrangler routes list
# Should show: erp.thehfhotel.org/qr-checkin/*
```

### Backend Connection Failed (502)

**Test backend directly:**
```bash
curl http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile
```

**Check container:**
```bash
docker ps | grep fingerprint-logger-public
docker logs fingerprint-logger-public
```

**Check firewall:**
```bash
# Ensure port 5001 accessible from Cloudflare IPs
# Cloudflare IP ranges: https://www.cloudflare.com/ips/
sudo ufw allow from 173.245.48.0/20 to any port 5001
```

### Database Locked Errors

**Verify WAL mode:**
```bash
sqlite3 database/attendance.db "PRAGMA journal_mode;"
# Should return: wal
```

**Check WAL files exist:**
```bash
ls -lh database/attendance.db*
# Should see: attendance.db, attendance.db-wal, attendance.db-shm
```

**Increase busy timeout:**
```python
# In app/core/database.py
cursor.execute("PRAGMA busy_timeout=10000")  # Increase to 10 seconds
```

### Rate Limiting Not Working

**Check configuration:**
```bash
curl http://localhost:5001/fingerprintlogs/api/service-info | jq '.features.rate_limiting'
# Should return: true
```

**Test rate limit:**
```bash
for i in {1..65}; do curl -s http://localhost:5001/fingerprintlogs/qr-checkin/health > /dev/null; done
curl -w "%{http_code}" http://localhost:5001/fingerprintlogs/qr-checkin/health
# Should return: 429
```

---

## Rollback Procedure

### Emergency Rollback (< 5 minutes)

```bash
# Step 1: Disable Cloudflare Worker
# Go to Cloudflare Dashboard → Workers & Pages → qr-checkin-proxy → Disable route

# Step 2: Stop public service
docker stop fingerprint-logger-public

# Step 3: Verify internal service still working
curl https://emp.thehfhotel.org/fingerprintlogs/health
```

### Full Rollback to Single Service

```bash
# Stop dual services
docker compose down

# Restore backup configuration
git checkout docker-compose.yml
git checkout .env

# Restart single service
docker compose up -d

# Verify
docker ps | grep fingerprint-logger
curl http://localhost:5000/fingerprintlogs/health
```

---

## Cost Analysis

### Cloudflare Workers Pricing

| Tier | Requests/Day | Cost |
|------|-------------|------|
| Free | 100,000 | $0 |
| Paid | 10,000,000 | $5/month |

### Typical QR Check-in Usage

- ~1,000 requests/day
- ~30,000 requests/month
- **Estimated Cost: $0/month** (well within free tier)

### Infrastructure Costs

- Additional Docker container: Minimal (shared resources)
- Database: Same SQLite file (WAL mode)
- SSL: Free with Cloudflare
- DNS: Free with Cloudflare

**Total Additional Cost: $0**

---

## URL Flow Reference

### Internal Service Flow

```
User → https://emp.thehfhotel.org/fingerprintlogs/qr-checkin/mobile
    ↓
Cloudflare (direct proxy, no rewriting)
    ↓ http://192.168.100.228:5000/fingerprintlogs/qr-checkin/mobile
Docker Container (fingerprint-logger-internal)
    ↓
FastAPI App (/fingerprintlogs/qr-checkin/mobile)
    ↓
Response (QR Mobile Page HTML)
```

### Public Service Flow

```
User → https://erp.thehfhotel.org/qr-checkin/mobile
    ↓
Cloudflare Worker (URL rewriting)
    ↓ http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile
    ↑ Rewrite: /qr-checkin/* → /fingerprintlogs/qr-checkin/*
Docker Container (fingerprint-logger-public)
    ↓
FastAPI App (/fingerprintlogs/qr-checkin/mobile)
    ↓
Response (QR Mobile Page HTML)
```

---

## Security Considerations

### Built-in Security

- ✅ Cloudflare DDoS protection
- ✅ SSL/TLS encryption
- ✅ Security headers injection
- ✅ Rate limiting (Cloudflare + application layer)

### Application Security

- ✅ Admin endpoints disabled in public service code
- ✅ Feature flags prevent unauthorized access
- ✅ Rate limiting per IP (60/min, 500/hour)
- ✅ CORS restricted to allowed origins

### Infrastructure Security

- ✅ Firewall rules for Cloudflare IPs only
- ✅ Separate containers for isolation
- ✅ Environment-based configuration
- ✅ No sensitive data in worker code

---

## Next Steps

1. ✅ **Infrastructure-as-Code Created** - Cloudflare Worker files ready
2. ⏭️ **Install Dependencies** - `cd cloudflare-worker && npm install`
3. ⏭️ **Authenticate** - `npx wrangler login`
4. ⏭️ **Configure Zone** - Update `wrangler.toml` with zone ID/name
5. ⏭️ **Deploy Docker Services** - Update `docker-compose.yml`, deploy
6. ⏭️ **Deploy Worker** - `npm run deploy:prod`
7. ⏭️ **Configure DNS** - Add `erp` A record in Cloudflare
8. ⏭️ **Test** - Verify both services and URL flows
9. ⏭️ **Update LINE OAuth** - Add public callback URL
10. ⏭️ **Monitor** - Set up health checks and logging

---

## Resources

- **Wrangler Docs**: https://developers.cloudflare.com/workers/wrangler/
- **Workers Examples**: https://developers.cloudflare.com/workers/examples/
- **Cloudflare Dashboard**: https://dash.cloudflare.com
- **Cloudflare IP Ranges**: https://www.cloudflare.com/ips/
- **LINE Developers**: https://developers.line.biz/

---

## Implementation Timeline

| Phase | Duration | Tasks |
|-------|----------|-------|
| Preparation | 1 hour | Enable SQLite WAL, backup, update configs |
| Code Changes | 3 hours | ServiceConfig, conditional routes, rate limiting |
| Docker Deployment | 2 hours | Build, deploy, test dual services |
| Cloudflare Worker | 1 hour | Install, configure, deploy worker |
| DNS & SSL | 30 min | Configure DNS, verify SSL |
| Testing | 2 hours | Full integration testing |
| **Total** | **9.5 hours** | **~2 working days** |

---

**Summary**: This deployment creates a secure, scalable public QR check-in service using Cloudflare Workers for URL rewriting and dual Docker services for feature isolation. No application code duplication, shared database with WAL mode, Infrastructure-as-Code for reproducibility.

**Architecture**: Cloudflare → Worker (rewrite) → Docker (public service) → SQLite (shared)

**Total Cost**: $0/month (within Cloudflare free tier)

**Rollback Time**: < 5 minutes

---

**Document Version:** 2.0
**Last Updated:** 2025-10-02
**Consolidates:** CLOUDFLARE_DUAL_SERVICE_ARCHITECTURE.md, CLOUDFLARE_WORKER_SETUP.md, QR_CHECKIN_DUAL_SERVICE_WORKFLOW.md
**Architecture Verified:** Cloudflare direct proxy (bypasses local nginx)
