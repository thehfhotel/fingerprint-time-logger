# Cloudflare Dual-Service Architecture Analysis

## Critical Architecture Discovery

### ❌ My Initial Nginx Assumption Was WRONG

I incorrectly assumed nginx was handling external traffic. After analyzing your Cloudflare setup, here's the **actual architecture**:

```
Internet
    ↓
Cloudflare (SSL Termination + Proxy)
    ↓ Proxy: https://emp.thehfhotel.org/fingerprintlogs → http://192.168.100.228:5000
Host Machine (192.168.100.228)
    ↓ Port 5000 (bypasses nginx!)
fingerprint-time-logger container:5000 (FastAPI direct)
    ↓ Mounted at /fingerprintlogs/
```

**Local Nginx Container:**
- Runs on ports 80/443
- **NOT used by Cloudflare traffic**
- Probably for local network access or development only

### ✅ Correct Solution: Dual Docker Services

Your suggestion to use **two Cloudflare proxy rules** is the RIGHT approach:

```
Internal: emp.thehfhotel.org/fingerprintlogs → :5000 (full features)
Public:   erp.thehfhotel.org/qr-checkin   → :5001 (QR only)
```

**My original workflow (QR_CHECKIN_DUAL_SERVICE_WORKFLOW.md) was correct!** Just ignore the nginx parts and focus on the Docker Compose and code changes.

---

## Architecture Options

### Option A: Cloudflare URL Rewriting (Recommended - No Code Changes)

**Cloudflare Configuration:**

```
Proxy Rule 1 (Internal - Existing):
  Source: https://emp.thehfhotel.org/fingerprintlogs/*
  Target: http://192.168.100.228:5000/fingerprintlogs/*
  Status: Keep as-is ✅

Proxy Rule 2 (Public - New):
  Source: https://erp.thehfhotel.org/qr-checkin/*
  Target: http://192.168.100.228:5001/fingerprintlogs/qr-checkin/*
         ↑ Note: Adds /fingerprintlogs/ prefix!
```

**How This Works:**

1. User accesses: `https://erp.thehfhotel.org/qr-checkin/mobile`
2. Cloudflare rewrites to: `http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile`
3. Public service receives: `/fingerprintlogs/qr-checkin/mobile`
4. App handles it normally (same code as internal service)

**Advantages:**
- ✅ No application code changes
- ✅ Same Docker image for both services
- ✅ Only environment variables differ
- ✅ Simple to maintain

**Implementation:**

```yaml
# docker-compose.yml
services:
  app-internal:
    # ... existing config
    ports:
      - "5000:5000"
    environment:
      - SERVICE_MODE=internal
      - ENABLE_ADMIN=true

  app-public:
    # ... same image
    ports:
      - "5001:5000"  # Host 5001 → Container 5000
    environment:
      - SERVICE_MODE=public
      - ENABLE_ADMIN=false
      - ENABLE_RATE_LIMITING=true
```

**Cloudflare Setup Methods:**

1. **Cloudflare Workers (Recommended):**
   ```javascript
   // Cloudflare Worker for erp.thehfhotel.org
   addEventListener('fetch', event => {
     event.respondWith(handleRequest(event.request))
   })

   async function handleRequest(request) {
     const url = new URL(request.url)

     // Rewrite: /qr-checkin/* → /fingerprintlogs/qr-checkin/*
     if (url.pathname.startsWith('/qr-checkin/')) {
       const newPath = url.pathname.replace('/qr-checkin/', '/fingerprintlogs/qr-checkin/')
       const backendUrl = `http://192.168.100.228:5001${newPath}${url.search}`

       return fetch(backendUrl, {
         method: request.method,
         headers: request.headers,
         body: request.body
       })
     }

     return new Response('Not Found', { status: 404 })
   }
   ```

2. **Cloudflare Transform Rules (Business/Enterprise):**
   - Path rewrite: `/qr-checkin/` → `/fingerprintlogs/qr-checkin/`
   - Target: `192.168.100.228:5001`

3. **Cloudflare Tunnel with Ingress Rules:**
   ```yaml
   # config.yml
   ingress:
     - hostname: erp.thehfhotel.org
       path: /qr-checkin/*
       service: http://192.168.100.228:5001/fingerprintlogs/qr-checkin
   ```

---

### Option B: Dual Mount Strategy (Code Changes Required)

**If Cloudflare can't easily rewrite paths**, modify the app to support both mounting styles:

**Code Changes:**

```python
# app/main_unified.py

from app.core.service_config import service_config

# Create QR-specific sub-app
qr_app = FastAPI(title="QR Check-in")
qr_app.include_router(line_auth.router, prefix="/api/auth/line", tags=["line-auth"])
qr_app.include_router(qr_checkin.router, prefix="/api/qr-checkin", tags=["qr-checkin"])

# Mount static files for QR app
qr_app.mount("/static", StaticFiles(directory="static"), name="static")

# QR page routes
@qr_app.get("/mobile")
async def qr_mobile(request: Request):
    return templates.TemplateResponse("qr-mobile.html", {"request": request})

@qr_app.get("/terminal")
async def qr_terminal(request: Request):
    return templates.TemplateResponse("qr-terminal.html", {"request": request})

@qr_app.get("/link-account")
async def qr_link_account(request: Request):
    return templates.TemplateResponse("link-line.html", {"request": request})

# Conditional mounting based on service mode
if service_config.is_public:
    # Public service: mount at /qr-checkin (no /fingerprintlogs/)
    app.mount("/qr-checkin", qr_app)

    @app.get("/")
    async def root_redirect():
        return RedirectResponse(url="/qr-checkin/mobile")
else:
    # Internal service: keep traditional /fingerprintlogs/ mount
    app.mount("/fingerprintlogs", fingerprint_app)

    @app.get("/")
    async def root_redirect():
        return RedirectResponse(url="/fingerprintlogs/")
```

**Cloudflare Configuration:**

```
Proxy Rule 2 (Public - Simpler):
  Source: https://erp.thehfhotel.org/qr-checkin/*
  Target: http://192.168.100.228:5001/qr-checkin/*
         ↑ No path rewriting needed!
```

**Advantages:**
- ✅ Cleaner external URLs (no /fingerprintlogs/)
- ✅ No Cloudflare Workers needed
- ✅ More flexible for future changes

**Disadvantages:**
- ❌ More code changes
- ❌ Two different URL structures to maintain
- ❌ Static file paths need careful handling

---

## Feasibility Analysis: erp.thehfhotel.org/qr-checkin/mobile

### ✅ FEASIBLE - Both Options Work

**Option A (Cloudflare Rewriting):**
- **Feasibility: ✅ HIGH** - Cloudflare Workers free tier supports this
- **Effort: LOW** - JavaScript worker script ~20 lines
- **Maintenance: LOW** - No app code changes

**Option B (Dual Mount):**
- **Feasibility: ✅ HIGH** - Standard FastAPI functionality
- **Effort: MEDIUM** - App code changes + testing
- **Maintenance: MEDIUM** - Two URL structures to maintain

### Recommended: Option A (Cloudflare Workers)

**Why:**
1. No application code changes
2. URL rewriting at CDN edge (faster)
3. Same Docker image for both services
4. Easier rollback (just change Cloudflare config)
5. Free tier available

---

## Updated Deployment Plan

### Phase 1: Docker Services (No Code Changes Needed with Option A)

```yaml
# docker-compose.yml
services:
  # Internal Service - Port 5000
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

  # Public Service - Port 5001
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

### Phase 2: Cloudflare Configuration

**Step 1: Create Cloudflare Worker**

1. Go to Cloudflare Dashboard → Workers & Pages
2. Create Worker → Name: `qr-checkin-proxy`
3. Add route: `erp.thehfhotel.org/qr-checkin/*`
4. Deploy worker code:

```javascript
addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request))
})

async function handleRequest(request) {
  const url = new URL(request.url)

  // Only handle /qr-checkin/* paths
  if (!url.pathname.startsWith('/qr-checkin/')) {
    return new Response('Not Found', { status: 404 })
  }

  // Rewrite path: /qr-checkin/* → /fingerprintlogs/qr-checkin/*
  const newPath = url.pathname.replace('/qr-checkin/', '/fingerprintlogs/qr-checkin/')
  const backendUrl = `http://192.168.100.228:5001${newPath}${url.search}`

  // Forward request to backend
  const modifiedRequest = new Request(backendUrl, {
    method: request.method,
    headers: request.headers,
    body: request.body,
    redirect: 'follow'
  })

  const response = await fetch(modifiedRequest)

  // Return response
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers
  })
}
```

**Step 2: Configure DNS**

1. Add DNS record: `erp.thehfhotel.org` → `192.168.100.228`
2. Enable Cloudflare proxy (orange cloud)

**Step 3: Configure SSL**

1. SSL/TLS → Overview → Full (or Full Strict if you have SSL on backend)
2. Edge Certificates → Always Use HTTPS: ON

**Step 4: Update LINE OAuth Callback**

Update `.env`:
```bash
# Internal callback (existing)
LINE_CALLBACK_URL=https://emp.thehfhotel.org/api/auth/line/callback

# Public callback (new)
LINE_CALLBACK_URL_PUBLIC=https://erp.thehfhotel.org/qr-checkin/api/auth/line/callback
```

Update LINE Developers Console:
- Add: `https://erp.thehfhotel.org/qr-checkin/api/auth/line/callback`

---

## Testing Checklist

### Internal Service (emp.thehfhotel.org/fingerprintlogs)
- [ ] Dashboard: `https://emp.thehfhotel.org/fingerprintlogs/`
- [ ] Admin: `https://emp.thehfhotel.org/fingerprintlogs/api/admin/line-codes/stats?passcode=...`
- [ ] QR Mobile: `https://emp.thehfhotel.org/fingerprintlogs/qr-checkin/mobile`
- [ ] Device Status: `https://emp.thehfhotel.org/fingerprintlogs/device-status`

### Public Service (erp.thehfhotel.org/qr-checkin)
- [ ] QR Mobile: `https://erp.thehfhotel.org/qr-checkin/mobile` ✅
- [ ] QR Terminal: `https://erp.thehfhotel.org/qr-checkin/terminal` ✅
- [ ] Link Account: `https://erp.thehfhotel.org/qr-checkin/link-account` ✅
- [ ] LINE Login: Works and redirects correctly ✅
- [ ] Admin Blocked: Try `/fingerprintlogs/api/admin/...` → 404 ❌
- [ ] Static Files: `/static/js/...` loads correctly ✅

### Cloudflare Worker Testing
```bash
# Test path rewriting
curl -v https://erp.thehfhotel.org/qr-checkin/mobile

# Check backend receives /fingerprintlogs/qr-checkin/mobile
docker logs fingerprint-logger-public --tail 10
```

---

## Cost Analysis

### Cloudflare Costs
- **Workers Free Tier**: 100,000 requests/day - Sufficient for most use cases
- **DNS**: Free with Cloudflare
- **SSL**: Free with Cloudflare

### Infrastructure Costs
- **Additional Container**: Minimal (shared resources)
- **Database**: Same SQLite file (WAL mode for concurrent access)

**Total Additional Cost: $0** (assuming within Workers free tier)

---

## Migration Path

### Step 1: Enable SQLite WAL Mode
```bash
# Before running dual services
sqlite3 database/attendance.db "PRAGMA journal_mode=WAL;"
```

### Step 2: Deploy Dual Services
```bash
# Stop current service
docker-compose down

# Update docker-compose.yml with dual services
# (Use configuration above)

# Start both services
docker-compose up -d

# Verify both running
docker ps | grep fingerprint-logger
```

### Step 3: Configure Cloudflare Worker
1. Create worker with code above
2. Add route: `erp.thehfhotel.org/qr-checkin/*`
3. Deploy

### Step 4: Test Public Access
```bash
curl -v https://erp.thehfhotel.org/qr-checkin/mobile
```

### Step 5: Update LINE OAuth
Add new callback URL in LINE Developers Console

---

## Rollback Plan

**If Issues Arise:**

```bash
# Step 1: Stop dual services
docker-compose down

# Step 2: Restore single service config
git checkout docker-compose.yml

# Step 3: Restart single service
docker-compose up -d

# Step 4: Remove Cloudflare Worker
# Disable worker route in Cloudflare Dashboard
```

**Rollback Time: < 5 minutes**

---

## Summary

### ✅ What You Discovered
- Cloudflare proxies directly to Docker containers
- Local nginx is NOT in the external traffic path
- Dual services with Cloudflare routing is the correct approach

### ✅ Recommended Solution: Option A

**Cloudflare Worker + Dual Docker Services:**
- Public: `erp.thehfhotel.org/qr-checkin/mobile` → Port 5001
- Internal: `emp.thehfhotel.org/fingerprintlogs/...` → Port 5000
- Cloudflare Worker rewrites `/qr-checkin/*` → `/fingerprintlogs/qr-checkin/*`
- No application code changes needed
- Free tier Cloudflare Workers

### ✅ Implementation Timeline
- **Phase 1 (Docker)**: 1 hour - Update docker-compose.yml, deploy services
- **Phase 2 (Cloudflare)**: 30 minutes - Create worker, configure routes
- **Phase 3 (Testing)**: 1 hour - Verify both services work correctly
- **Total**: 2.5 hours

### ✅ Next Steps
1. Review this architecture plan
2. Confirm Cloudflare Workers approach
3. Implement dual services in docker-compose.yml
4. Create and deploy Cloudflare Worker
5. Test and validate

**This architecture is FEASIBLE and RECOMMENDED!** 🚀
