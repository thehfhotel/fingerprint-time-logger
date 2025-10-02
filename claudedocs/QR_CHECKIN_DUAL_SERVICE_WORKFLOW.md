# QR Check-in Dual Service Implementation Workflow

## Executive Summary

Create two separate Docker Compose services from the existing unified application:
- **Internal Service**: Full-featured admin + QR check-in (existing functionality)
- **Public Service**: QR check-in only, internet-exposed, admin disabled

**Timeline**: 2-3 days for full implementation and testing
**Risk Level**: Medium (SQLite concurrent access, security hardening required)

---

## Architecture Overview

### Current State
```
┌─────────────────────────────────────┐
│  fingerprint-time-logger (port 5000)│
│  ├── Admin Panel                    │
│  ├── Dashboard                      │
│  ├── QR Check-in (LINE OAuth)       │
│  ├── Device Management              │
│  └── Employee Management            │
└─────────────────────────────────────┘
         ↓ (nginx proxy)
    Internal Network Only
```

### Target State
```
┌────────────────────────────────────┐     ┌──────────────────────────────┐
│ Internal Service (port 5000)       │     │ Public Service (port 5001)   │
│ ├── Admin Panel          ✅        │     │ ├── Admin Panel       ❌     │
│ ├── Dashboard            ✅        │     │ ├── Dashboard         ❌     │
│ ├── QR Check-in          ✅        │     │ ├── QR Check-in       ✅     │
│ ├── Device Management    ✅        │     │ ├── Device Management ❌     │
│ └── Employee Management  ✅        │     │ └── Rate Limited      ✅     │
└────────────────────────────────────┘     └──────────────────────────────┘
         ↓                                           ↓
   Internal Network                          Internet Exposed
         │                                           │
         └───────────── Shared Database ────────────┘
              (SQLite WAL mode for concurrent access)
```

---

## Implementation Workflow

### Phase 1: Docker Compose Configuration (Day 1 - 4 hours)

#### Step 1.1: Backup Current Configuration
```bash
cp docker-compose.yml docker-compose.yml.backup
cp .env .env.backup
```

#### Step 1.2: Update docker-compose.yml

**Replace existing service with two services:**

```yaml
# Production Docker Compose - Dual Service Configuration
# Internal Service: Full features, internal network only
# Public Service: QR Check-in only, internet exposed

services:
  # Internal Service - Full Features
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
      - BEHIND_PROXY=${BEHIND_PROXY:-true}
      - LINE_CHANNEL_ID=${LINE_CHANNEL_ID}
      - LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET}
      - LINE_CALLBACK_URL=${LINE_CALLBACK_URL}
      - JWT_SECRET=${JWT_SECRET}
      # Internal service settings
      - ENABLE_ADMIN=true
      - ENABLE_DEVICE_SYNC=true
      - ENABLE_DASHBOARD=true
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/fingerprintlogs/health"]
      interval: 600s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - app-network
      - shared-nginx

  # Public Service - QR Check-in Only
  app-public:
    image: fingerprint-time-logger:latest
    build:
      context: .
      target: fingerprint-logger
    container_name: fingerprint-logger-public
    ports:
      - "5001:5000"  # External 5001 → Internal 5000
    volumes:
      - ./database:/app/database  # Shared database (read-write)
      - ./logs/public:/app/logs
      - ./pids/public:/app/pids
    environment:
      - SERVICE_MODE=public
      - SERVICE_NAME=fingerprint-logger-public
      - DATABASE_URL=sqlite:///./database/attendance.db
      - TZ=Asia/Bangkok
      - BEHIND_PROXY=${BEHIND_PROXY:-true}
      - LINE_CHANNEL_ID=${LINE_CHANNEL_ID}
      - LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET}
      - LINE_CALLBACK_URL_PUBLIC=${LINE_CALLBACK_URL_PUBLIC}  # Different callback for public
      - JWT_SECRET=${JWT_SECRET}
      # Public service security settings
      - ENABLE_ADMIN=false
      - ENABLE_DEVICE_SYNC=false
      - ENABLE_DASHBOARD=false
      - ENABLE_RATE_LIMITING=true
      - RATE_LIMIT_PER_MINUTE=60
      - RATE_LIMIT_PER_HOUR=500
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/fingerprintlogs/qr-checkin/health"]
      interval: 300s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - app-network
      - shared-nginx

networks:
  app-network:
    driver: bridge

  shared-nginx:
    external: true
    name: shared-nginx
```

#### Step 1.3: Update .env file

Add new environment variables:
```bash
# Public Service Configuration
LINE_CALLBACK_URL_PUBLIC=https://qr.thehfhotel.org/fingerprintlogs/api/auth/line/callback
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_PER_HOUR=500
```

**Checklist:**
- [ ] Backup created
- [ ] docker-compose.yml updated with dual services
- [ ] .env updated with public service variables
- [ ] Log directories created (`mkdir -p logs/{internal,public} pids/{internal,public}`)

---

### Phase 2: Application Code Changes (Day 1-2 - 6 hours)

#### Step 2.1: Add Service Mode Configuration

**Create new file: `app/core/service_config.py`**

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

    def __repr__(self):
        return f"ServiceConfig(mode={self.mode}, name={self.name})"

# Global service configuration
service_config = ServiceConfig()
```

#### Step 2.2: Update main_unified.py for Conditional Routes

**Modify `app/main_unified.py`:**

```python
# Add at top of file
from app.core.service_config import service_config

# ... existing imports ...

# Conditional router registration (around line 220)

# Always include QR check-in and LINE auth
fingerprint_app.include_router(line_auth.router, prefix="/api/auth/line", tags=["line-auth"])
fingerprint_app.include_router(qr_checkin.router, prefix="/api/qr-checkin", tags=["qr-checkin"])

# Conditional routers based on service mode
if service_config.enable_admin:
    # Admin-only routes
    fingerprint_app.include_router(admin_line_codes.router, prefix="/api/admin/line-codes", tags=["admin-line-codes"])
    fingerprint_app.include_router(system_status.router, prefix="/api/system", tags=["system-status"])

if service_config.is_internal:
    # Internal-only features
    fingerprint_app.include_router(consolidated_attendance.router, prefix="/api/attendance", tags=["attendance"])
    fingerprint_app.include_router(consolidated_devices.router, prefix="/api/devices", tags=["devices"])
    fingerprint_app.include_router(consolidated_employees.router, prefix="/api/employees", tags=["employees"])

# Add service info endpoint
@fingerprint_app.get("/api/service-info")
async def get_service_info():
    """Get service configuration info"""
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

# Logging on startup
@fingerprint_app.on_event("startup")
async def startup_event():
    print(f"🚀 Starting {service_config.name} in {service_config.mode} mode")
    print(f"   Admin: {service_config.enable_admin}")
    print(f"   Device Sync: {service_config.enable_device_sync}")
    print(f"   Dashboard: {service_config.enable_dashboard}")
    print(f"   Rate Limiting: {service_config.enable_rate_limiting}")
```

#### Step 2.3: Add Rate Limiting Middleware

**Install dependency (add to requirements.txt):**
```
slowapi==0.1.9
```

**Create new file: `app/middleware/rate_limit.py`**

```python
"""
Rate limiting middleware for public-facing API
Uses slowapi for token bucket rate limiting
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
from app.core.service_config import service_config

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[
        f"{service_config.rate_limit_per_minute}/minute",
        f"{service_config.rate_limit_per_hour}/hour"
    ],
    enabled=service_config.enable_rate_limiting
)

def setup_rate_limiting(app):
    """Setup rate limiting for the application"""
    if service_config.enable_rate_limiting:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        print(f"✅ Rate limiting enabled: {service_config.rate_limit_per_minute}/min, {service_config.rate_limit_per_hour}/hour")
    else:
        print("ℹ️  Rate limiting disabled")
```

**Update main_unified.py to use rate limiting:**

```python
from app.middleware.rate_limit import setup_rate_limiting

# After creating fingerprint_app
setup_rate_limiting(fingerprint_app)
```

#### Step 2.4: Add Public Service Health Check

**Update QR check-in router:**

```python
# In app/api/qr_checkin.py

@router.get("/health")
async def qr_health_check():
    """Health check endpoint for public service"""
    return {
        "status": "healthy",
        "service": "qr-checkin",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
```

**Checklist:**
- [ ] ServiceConfig class created
- [ ] main_unified.py updated with conditional routes
- [ ] Rate limiting middleware added
- [ ] slowapi added to requirements.txt
- [ ] QR health check endpoint added

---

### Phase 3: Security Hardening (Day 2 - 4 hours)

#### Step 3.1: Add Security Headers Middleware

**Create `app/middleware/security_headers.py`:**

```python
"""
Security headers middleware for public-facing service
Adds recommended security headers to all responses
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.service_config import service_config

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to responses"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if service_config.is_public:
            # Security headers for public service
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

            # Strict Transport Security (if using HTTPS)
            if request.url.scheme == "https":
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response
```

**Add to main_unified.py:**

```python
from app.middleware.security_headers import SecurityHeadersMiddleware

fingerprint_app.add_middleware(SecurityHeadersMiddleware)
```

#### Step 3.2: Review and Update CORS Configuration

**In main_unified.py, update CORS for public service:**

```python
from app.core.service_config import service_config

# CORS configuration based on service mode
if service_config.is_public:
    # Strict CORS for public service
    allowed_origins = [
        "https://qr.thehfhotel.org",
        "https://emp.thehfhotel.org"
    ]
else:
    # More permissive for internal
    allowed_origins = ["*"]

fingerprint_app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

#### Step 3.3: SQLite WAL Mode for Concurrent Access

**Verify SQLite WAL mode is enabled:**

```bash
# Check if WAL mode is enabled
sqlite3 database/attendance.db "PRAGMA journal_mode;"
# Should return: wal

# If not enabled, enable it:
sqlite3 database/attendance.db "PRAGMA journal_mode=WAL;"
```

**Add to database initialization in `app/core/database.py`:**

```python
# After engine creation
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

**Checklist:**
- [ ] Security headers middleware added
- [ ] CORS configuration updated for service modes
- [ ] SQLite WAL mode enabled and verified
- [ ] Database connection settings optimized

---

### Phase 4: Static File Serving Configuration (Day 2 - 2 hours)

#### Step 4.1: Conditional Static File Serving

**Update main_unified.py:**

```python
if service_config.is_internal:
    # Serve all static pages for internal service
    @app.get("/")
    async def redirect_to_dashboard():
        return RedirectResponse(url="/fingerprintlogs/")

    app.mount("/fingerprintlogs/static", StaticFiles(directory="static"), name="static")

    # All HTML pages
    templates = Jinja2Templates(directory="static")

    @app.get("/fingerprintlogs/")
    async def serve_dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})

    # ... other pages ...

elif service_config.is_public:
    # Only serve QR check-in related pages
    app.mount("/fingerprintlogs/static", StaticFiles(directory="static"), name="static")
    templates = Jinja2Templates(directory="static")

    @app.get("/fingerprintlogs/qr-checkin/mobile")
    async def serve_qr_mobile(request: Request):
        return templates.TemplateResponse("qr-mobile.html", {"request": request})

    @app.get("/fingerprintlogs/qr-checkin/terminal")
    async def serve_qr_terminal(request: Request):
        return templates.TemplateResponse("qr-terminal.html", {"request": request})

    @app.get("/fingerprintlogs/qr-checkin/link-account")
    async def serve_link_account(request: Request):
        return templates.TemplateResponse("link-line.html", {"request": request})

    # Redirect root to mobile check-in for public service
    @app.get("/")
    async def redirect_to_qr():
        return RedirectResponse(url="/fingerprintlogs/qr-checkin/mobile")
```

**Checklist:**
- [ ] Conditional static file serving implemented
- [ ] Public service only serves QR-related pages
- [ ] Root redirect configured for each service mode

---

### Phase 5: Testing & Validation (Day 2-3 - 6 hours)

#### Step 5.1: Local Testing

**Test script: `test_dual_service.sh`**

```bash
#!/bin/bash
# Test dual service deployment

echo "🧪 Testing Dual Service Deployment"
echo "=================================="

# Build and start services
echo "1. Building and starting services..."
docker-compose build
docker-compose up -d

# Wait for services to be healthy
echo "2. Waiting for services to start..."
sleep 10

# Test internal service
echo "3. Testing internal service (port 5000)..."
INTERNAL_HEALTH=$(curl -s http://localhost:5000/fingerprintlogs/health | jq -r '.status')
INTERNAL_MODE=$(curl -s http://localhost:5000/fingerprintlogs/api/service-info | jq -r '.service_mode')
INTERNAL_ADMIN=$(curl -s http://localhost:5000/fingerprintlogs/api/service-info | jq -r '.features.admin')

echo "   Status: $INTERNAL_HEALTH"
echo "   Mode: $INTERNAL_MODE"
echo "   Admin Enabled: $INTERNAL_ADMIN"

# Test admin endpoint (should work on internal)
ADMIN_TEST=$(curl -s -w "%{http_code}" http://localhost:5000/fingerprintlogs/api/admin/line-codes/stats?passcode=bananabananabanana -o /dev/null)
echo "   Admin endpoint: $ADMIN_TEST (expected: 200)"

# Test public service
echo "4. Testing public service (port 5001)..."
PUBLIC_HEALTH=$(curl -s http://localhost:5001/fingerprintlogs/qr-checkin/health | jq -r '.status')
PUBLIC_MODE=$(curl -s http://localhost:5001/fingerprintlogs/api/service-info | jq -r '.service_mode')
PUBLIC_ADMIN=$(curl -s http://localhost:5001/fingerprintlogs/api/service-info | jq -r '.features.admin')

echo "   Status: $PUBLIC_HEALTH"
echo "   Mode: $PUBLIC_MODE"
echo "   Admin Enabled: $PUBLIC_ADMIN"

# Test admin endpoint (should fail on public)
ADMIN_PUBLIC_TEST=$(curl -s -w "%{http_code}" http://localhost:5001/fingerprintlogs/api/admin/line-codes/stats?passcode=bananabananabanana -o /dev/null)
echo "   Admin endpoint: $ADMIN_PUBLIC_TEST (expected: 404)"

# Test rate limiting on public service
echo "5. Testing rate limiting on public service..."
for i in {1..65}; do
    curl -s http://localhost:5001/fingerprintlogs/qr-checkin/health > /dev/null
done
RATE_LIMIT_TEST=$(curl -s -w "%{http_code}" http://localhost:5001/fingerprintlogs/qr-checkin/health -o /dev/null)
echo "   After 65 requests: $RATE_LIMIT_TEST (expected: 429 if rate limiting works)"

# Database concurrent access test
echo "6. Testing database concurrent access..."
# Both services should be able to read/write simultaneously
echo "   Skipping automated test - manual verification needed"

echo ""
echo "✅ Testing complete!"
echo "   Review results above for any failures"
```

#### Step 5.2: Integration Testing Checklist

**Internal Service Tests:**
- [ ] Dashboard accessible at http://localhost:5000/fingerprintlogs/
- [ ] Admin endpoints work (/api/admin/line-codes/*)
- [ ] Device management accessible
- [ ] Employee management accessible
- [ ] QR check-in accessible
- [ ] LINE OAuth flow works

**Public Service Tests:**
- [ ] QR mobile page accessible at http://localhost:5001/fingerprintlogs/qr-checkin/mobile
- [ ] QR terminal page accessible
- [ ] Link account page accessible
- [ ] LINE OAuth flow works with public callback
- [ ] Admin endpoints return 404
- [ ] Dashboard returns 404
- [ ] Rate limiting triggers after threshold
- [ ] Security headers present in responses

**Database Tests:**
- [ ] Both services can read employee data
- [ ] Both services can write attendance records
- [ ] No database corruption after concurrent writes
- [ ] WAL files created (attendance.db-wal, attendance.db-shm)

**Security Tests:**
- [ ] CORS headers correct for each service
- [ ] Security headers present on public service
- [ ] Admin passcode doesn't work on public endpoints
- [ ] Rate limiting prevents abuse

---

### Phase 6: Nginx Configuration (Day 3 - 3 hours)

#### Step 6.1: Update Nginx Upstream Configuration

**In `~/nginx/conf.d/fingerprint.conf`:**

```nginx
# Internal service upstream (existing)
upstream fingerprint_internal {
    server fingerprint-logger-internal:5000;
}

# Public service upstream (new)
upstream fingerprint_public {
    server fingerprint-logger-public:5000;
}

# Internal access (existing domain)
server {
    listen 80;
    server_name emp.thehfhotel.org;

    location /fingerprintlogs/ {
        proxy_pass http://fingerprint_internal;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Public QR check-in access (new domain)
server {
    listen 80;
    server_name qr.thehfhotel.org;

    # Only allow QR check-in paths
    location /fingerprintlogs/qr-checkin/ {
        proxy_pass http://fingerprint_public;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Additional security headers at nginx level
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header X-XSS-Protection "1; mode=block" always;
    }

    location /fingerprintlogs/api/auth/line/ {
        proxy_pass http://fingerprint_public;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /fingerprintlogs/static/ {
        proxy_pass http://fingerprint_public;
        proxy_set_header Host $host;

        # Cache static files
        proxy_cache_valid 200 1h;
        add_header Cache-Control "public, max-age=3600";
    }

    # Block everything else
    location / {
        return 404;
    }
}
```

#### Step 6.2: SSL/TLS Configuration

**Add SSL certificates for new domain:**

```bash
# Request SSL certificate for qr.thehfhotel.org
sudo certbot --nginx -d qr.thehfhotel.org

# Nginx will auto-update config with SSL
```

**Update SSL configuration in nginx config:**

```nginx
# Public QR check-in access with SSL
server {
    listen 443 ssl http2;
    server_name qr.thehfhotel.org;

    ssl_certificate /etc/letsencrypt/live/qr.thehfhotel.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/qr.thehfhotel.org/privkey.pem;

    # ... rest of location blocks from step 6.1 ...
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name qr.thehfhotel.org;
    return 301 https://$server_name$request_uri;
}
```

**Checklist:**
- [ ] Nginx upstream configurations added
- [ ] Internal service nginx config verified
- [ ] Public service nginx config created
- [ ] SSL certificate obtained for public domain
- [ ] SSL configuration tested
- [ ] Nginx reloaded (`nginx -s reload`)

---

### Phase 7: Deployment & Monitoring (Day 3 - 2 hours)

#### Step 7.1: Production Deployment

**Deployment checklist:**

```bash
# 1. Stop existing service
docker-compose down

# 2. Backup database
cp database/attendance.db database/attendance.db.backup.$(date +%Y%m%d_%H%M%S)

# 3. Pull latest code
git pull origin main

# 4. Build new images
docker-compose build --no-cache

# 5. Start dual services
docker-compose up -d

# 6. Verify both services running
docker ps | grep fingerprint-logger

# 7. Check logs
docker logs fingerprint-logger-internal
docker logs fingerprint-logger-public

# 8. Test health endpoints
curl http://localhost:5000/fingerprintlogs/health
curl http://localhost:5001/fingerprintlogs/qr-checkin/health

# 9. Reload nginx
docker exec nginx-proxy nginx -s reload
```

#### Step 7.2: Monitoring Setup

**Create monitoring script: `scripts/monitor-dual-service.sh`**

```bash
#!/bin/bash
# Monitor dual service health and performance

echo "📊 Dual Service Monitoring Report"
echo "=================================="
echo "Generated: $(date)"
echo ""

# Service status
echo "🔧 Service Status:"
docker ps --filter "name=fingerprint-logger" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

# Health checks
echo "💚 Health Checks:"
INTERNAL_HEALTH=$(curl -s http://localhost:5000/fingerprintlogs/health | jq -r '.status // "ERROR"')
PUBLIC_HEALTH=$(curl -s http://localhost:5001/fingerprintlogs/qr-checkin/health | jq -r '.status // "ERROR"')
echo "   Internal: $INTERNAL_HEALTH"
echo "   Public: $PUBLIC_HEALTH"
echo ""

# Database status
echo "💾 Database Status:"
DB_SIZE=$(du -h database/attendance.db | cut -f1)
WAL_SIZE=$(du -h database/attendance.db-wal 2>/dev/null | cut -f1 || echo "N/A")
echo "   DB Size: $DB_SIZE"
echo "   WAL Size: $WAL_SIZE"
echo ""

# Log file sizes
echo "📝 Log Files:"
INTERNAL_LOGS=$(du -sh logs/internal 2>/dev/null | cut -f1 || echo "0")
PUBLIC_LOGS=$(du -sh logs/public 2>/dev/null | cut -f1 || echo "0")
echo "   Internal: $INTERNAL_LOGS"
echo "   Public: $PUBLIC_LOGS"
echo ""

# Container resource usage
echo "⚡ Resource Usage:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
    fingerprint-logger-internal fingerprint-logger-public
```

**Add to crontab for hourly monitoring:**

```bash
0 * * * * /home/nut/fingerprint-time-logger/scripts/monitor-dual-service.sh >> /home/nut/fingerprint-time-logger/logs/monitoring.log 2>&1
```

**Checklist:**
- [ ] Production deployment completed
- [ ] Both services running and healthy
- [ ] Nginx routing verified
- [ ] Monitoring script created and scheduled
- [ ] Backup procedures documented

---

## Risk Mitigation & Rollback Plan

### Risk 1: SQLite Concurrent Access Issues

**Symptoms:**
- Database locked errors
- Corrupted database file
- Slow write operations

**Mitigation:**
1. WAL mode enabled (implemented)
2. Busy timeout set to 5 seconds
3. Monitor for lock errors in logs

**Rollback:**
```bash
# Restore single service
git checkout docker-compose.yml.backup
docker-compose down
docker-compose up -d
```

### Risk 2: Public Service Security Breach

**Symptoms:**
- Unauthorized access to admin features
- Excessive API calls
- Unusual access patterns

**Mitigation:**
1. Rate limiting enabled
2. Admin endpoints disabled in code
3. Security headers enforced
4. Nginx-level path restrictions

**Emergency Response:**
```bash
# Immediately stop public service
docker stop fingerprint-logger-public

# Review logs for suspicious activity
docker logs fingerprint-logger-public | grep -i "admin\|error\|401\|403"

# Re-enable after investigation
```

### Risk 3: Service Configuration Mismatch

**Symptoms:**
- Wrong features enabled/disabled
- Environment variables not loaded
- Service mode incorrect

**Mitigation:**
1. Service info endpoint for verification
2. Startup logging of configuration
3. Health check endpoints per service

**Verification:**
```bash
# Check internal service config
curl http://localhost:5000/fingerprintlogs/api/service-info | jq

# Check public service config
curl http://localhost:5001/fingerprintlogs/api/service-info | jq
```

---

## Alternative Approach: Nginx-Only Separation

If the dual-service approach proves too complex or risky, here's a simpler alternative:

### Option B: Single Service + Nginx Routing

**Concept:** Keep single Docker service, use nginx to create public/internal access patterns

**Nginx configuration:**

```nginx
# Internal access - all features
server {
    listen 80;
    server_name emp.thehfhotel.org;

    location /fingerprintlogs/ {
        proxy_pass http://fingerprint-time-logger:5000;
    }
}

# Public access - QR only, rate limited
server {
    listen 80;
    server_name qr.thehfhotel.org;

    # Rate limiting at nginx level
    limit_req_zone $binary_remote_addr zone=qr_limit:10m rate=60r/m;

    location /fingerprintlogs/qr-checkin/ {
        limit_req zone=qr_limit burst=10;
        proxy_pass http://fingerprint-time-logger:5000;
    }

    location /fingerprintlogs/api/auth/line/ {
        limit_req zone=qr_limit burst=10;
        proxy_pass http://fingerprint-time-logger:5000;
    }

    location /fingerprintlogs/static/ {
        proxy_pass http://fingerprint-time-logger:5000;
    }

    # Block admin endpoints
    location ~ ^/fingerprintlogs/api/admin/ {
        return 404;
    }

    location / {
        return 404;
    }
}
```

**Pros:**
- No code changes required
- No SQLite concurrent access issues
- Simpler to maintain
- Same Docker image

**Cons:**
- Less isolation between public/internal
- Security boundary at nginx only
- No application-level feature flags

---

## Success Criteria

### Functional Requirements
- [ ] Internal service provides full admin functionality
- [ ] Public service provides QR check-in functionality only
- [ ] LINE OAuth works on both services
- [ ] Both services can read/write to database without corruption
- [ ] Admin endpoints return 404 on public service

### Non-Functional Requirements
- [ ] Public service rate limiting prevents abuse (429 after threshold)
- [ ] Security headers present on all public responses
- [ ] Both services achieve 99%+ uptime
- [ ] Database operations complete within 100ms 95th percentile
- [ ] No database corruption after 1 week of concurrent access

### Operational Requirements
- [ ] Monitoring script runs hourly
- [ ] Health checks respond within 1 second
- [ ] Logs separated by service
- [ ] Rollback procedure tested and documented
- [ ] Team trained on dual-service architecture

---

## Post-Implementation Tasks

1. **Documentation Updates**
   - [ ] Update CLAUDE.md with dual-service architecture
   - [ ] Update README with deployment instructions
   - [ ] Create runbook for operations team

2. **Performance Baseline**
   - [ ] Measure response times for both services
   - [ ] Monitor database file size growth
   - [ ] Track memory/CPU usage per service

3. **Security Audit**
   - [ ] Penetration testing of public service
   - [ ] Review logs for suspicious patterns
   - [ ] Verify admin endpoints truly inaccessible

4. **User Communication**
   - [ ] Notify employees of new QR check-in URL
   - [ ] Update LINE OAuth callback configuration
   - [ ] Provide training on new public service

---

## Timeline Summary

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| 1. Docker Config | 4 hours | Updated docker-compose.yml, .env |
| 2. Code Changes | 6 hours | ServiceConfig, conditional routes, rate limiting |
| 3. Security | 4 hours | Security headers, CORS, SQLite WAL |
| 4. Static Files | 2 hours | Conditional page serving |
| 5. Testing | 6 hours | Integration tests, security validation |
| 6. Nginx | 3 hours | Upstream config, SSL setup |
| 7. Deployment | 2 hours | Production rollout, monitoring |
| **Total** | **27 hours** | **2-3 days** |

---

## Conclusion

This workflow provides a comprehensive path to duplicate the QR Check-in service for internet exposure while maintaining internal admin functionality. The dual-service approach offers strong isolation and security, with clear rollback options if issues arise.

**Recommendation:** Implement Option A (dual services) for maximum security isolation, with Option B (nginx-only) as a fallback if SQLite concurrent access becomes problematic.

**Next Steps:**
1. Review this workflow with stakeholders
2. Obtain approval for production deployment
3. Schedule implementation during low-traffic window
4. Begin Phase 1 implementation

---

**Document Version:** 1.0
**Last Updated:** 2025-10-01
**Author:** Claude Code (via /sc:workflow)
