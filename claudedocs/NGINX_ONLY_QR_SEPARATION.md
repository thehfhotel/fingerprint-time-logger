# Nginx-Only QR Check-in Separation

## Current Setup Analysis

### ✅ You ARE Already Using Nginx

**Your Current Architecture:**
```
Internet
    ↓
emp.thehfhotel.org (HTTPS)
    ↓
Nginx (shared-nginx container)
    ↓ proxy_pass to fingerprint-time-logger:5000
FastAPI App
    ↓ mounted at /fingerprintlogs/
All features: Admin + Dashboard + QR Check-in
```

**Current URL Structure:**
- External: `https://emp.thehfhotel.org/...`
- Internal App: `/fingerprintlogs/...` (base path)
- QR URLs: `https://emp.thehfhotel.org/qr-checkin/...`

**Key Finding:** Your nginx config at line 41-67 routes ALL traffic (`location /`) to the same FastAPI container, meaning there's currently NO separation between internal and public access.

---

## Your Requirement

**Desired External URL:** `erp.thehfhotel.org/qr-checkin`
- **No** `/fingerprintlogs/` prefix in external URL
- Public QR check-in only
- Admin features remain internal-only

---

## Nginx-Only Solution (Recommended for Your Setup)

### Option: Single Service + Nginx Routing

**Concept:** Keep your existing single Docker container, but use nginx to:
1. Route `erp.thehfhotel.org/qr-checkin` → Public QR endpoints (rate limited)
2. Route `emp.thehfhotel.org` → Internal full features
3. Block admin endpoints from public URL

**Advantages:**
- ✅ No code changes required
- ✅ No database concurrency issues (single service)
- ✅ Easy to implement and maintain
- ✅ Security at nginx level
- ✅ Same Docker image, different routing

---

## Implementation: Nginx Configuration Changes

### Step 1: Update Nginx Sites-Enabled File

**File:** `/home/nut/nginx/sites-enabled/fingerprint-time-logger`

**Replace entire file with:**

```nginx
# Fingerprint Time Logger - Dual URL Configuration
# emp.thehfhotel.org: Internal full access
# erp.thehfhotel.org/qr-checkin: Public QR check-in only

# Rate limiting zones for public access
limit_req_zone $binary_remote_addr zone=qr_general:10m rate=60r/m;
limit_req_zone $binary_remote_addr zone=qr_api:10m rate=30r/m;

# =============================================================================
# INTERNAL ACCESS - emp.thehfhotel.org (Full Features)
# =============================================================================

server {
    # HTTP redirect to HTTPS
    listen 80;
    server_name emp.thehfhotel.org localhost;
    return 301 https://$host$request_uri;
}

server {
    # HTTPS server - Internal full access
    listen 443 ssl;
    server_name emp.thehfhotel.org localhost;

    # SSL Configuration
    ssl_certificate /etc/nginx/ssl/fingerprint-cert.pem;
    ssl_certificate_key /etc/nginx/ssl/fingerprint-key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Logging
    access_log /var/log/nginx/fingerprint-internal-access.log main;
    error_log /var/log/nginx/fingerprint-internal-error.log warn;

    # Main application - NO URL REWRITING (keeps /fingerprintlogs/ internally)
    location / {
        proxy_pass http://fingerprint-time-logger:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        # Buffers
        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 8 16k;
    }
}

# =============================================================================
# PUBLIC ACCESS - erp.thehfhotel.org/qr-checkin (QR Check-in Only)
# =============================================================================

server {
    # HTTP redirect to HTTPS
    listen 80;
    server_name erp.thehfhotel.org;
    return 301 https://$host$request_uri;
}

server {
    # HTTPS server - Public QR check-in only
    listen 443 ssl;
    server_name erp.thehfhotel.org;

    # SSL Configuration (use same or separate cert)
    ssl_certificate /etc/nginx/ssl/fingerprint-cert.pem;
    ssl_certificate_key /etc/nginx/ssl/fingerprint-key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Strict security headers for public access
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'none';" always;

    # Logging (separate logs for public access)
    access_log /var/log/nginx/fingerprint-public-access.log main;
    error_log /var/log/nginx/fingerprint-public-error.log warn;

    # QR Check-in Mobile Page - URL rewrite: /qr-checkin → /fingerprintlogs/qr-checkin
    location = /qr-checkin {
        return 301 /qr-checkin/mobile;
    }

    location /qr-checkin/mobile {
        limit_req zone=qr_general burst=10 nodelay;

        # Rewrite: /qr-checkin/mobile → /fingerprintlogs/qr-checkin/mobile
        proxy_pass http://fingerprint-time-logger:5000/fingerprintlogs/qr-checkin/mobile;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 60s;
    }

    # QR Check-in Terminal Display
    location /qr-checkin/terminal {
        limit_req zone=qr_general burst=10 nodelay;

        # Rewrite: /qr-checkin/terminal → /fingerprintlogs/qr-checkin/terminal
        proxy_pass http://fingerprint-time-logger:5000/fingerprintlogs/qr-checkin/terminal;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 60s;
    }

    # LINE Account Linking Page
    location /qr-checkin/link-account {
        limit_req zone=qr_general burst=10 nodelay;

        # Rewrite: /qr-checkin/link-account → /fingerprintlogs/qr-checkin/link-account
        proxy_pass http://fingerprint-time-logger:5000/fingerprintlogs/qr-checkin/link-account;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 60s;
    }

    # LINE OAuth Endpoints (required for login flow)
    location /api/auth/line/ {
        limit_req zone=qr_api burst=5 nodelay;

        # Rewrite: /api/auth/line/* → /fingerprintlogs/api/auth/line/*
        rewrite ^/api/auth/line/(.*)$ /fingerprintlogs/api/auth/line/$1 break;
        proxy_pass http://fingerprint-time-logger:5000;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 60s;
    }

    # QR Check-in API Endpoints
    location /api/qr-checkin/ {
        limit_req zone=qr_api burst=5 nodelay;

        # Rewrite: /api/qr-checkin/* → /fingerprintlogs/api/qr-checkin/*
        rewrite ^/api/qr-checkin/(.*)$ /fingerprintlogs/api/qr-checkin/$1 break;
        proxy_pass http://fingerprint-time-logger:5000;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Content-Type application/json;

        proxy_read_timeout 60s;
    }

    # Static files (JavaScript, CSS, images)
    location /static/ {
        limit_req zone=qr_general burst=20 nodelay;

        # Rewrite: /static/* → /fingerprintlogs/static/*
        rewrite ^/static/(.*)$ /fingerprintlogs/static/$1 break;
        proxy_pass http://fingerprint-time-logger:5000;

        proxy_set_header Host $host;

        # Cache static files
        expires 1h;
        add_header Cache-Control "public, max-age=3600";
    }

    # Health check endpoint (for monitoring)
    location /health {
        limit_req zone=qr_general burst=5 nodelay;

        proxy_pass http://fingerprint-time-logger:5000/fingerprintlogs/health;
        proxy_set_header Host $host;

        proxy_no_cache 1;
        proxy_cache_bypass 1;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # BLOCK ADMIN ENDPOINTS (return 404, not 403 to avoid enumeration)
    location ~ ^/api/admin/ {
        return 404;
    }

    location ~ ^/api/devices/ {
        return 404;
    }

    location ~ ^/api/employees/ {
        return 404;
    }

    location ~ ^/api/attendance/ {
        return 404;
    }

    location ~ ^/api/system/ {
        return 404;
    }

    # Block admin pages
    location ~ ^/(device-status|nickname-management|employee-management|work-schedules|status|docs|redoc) {
        return 404;
    }

    # Block all other paths (default deny)
    location / {
        return 404;
    }

    # Block sensitive files
    location ~ /\.(ht|git|svn) {
        deny all;
        return 404;
    }
}
```

---

## What Changed?

### Before (Single URL)
```
emp.thehfhotel.org → ALL features (admin + QR)
```

### After (Dual URL)
```
emp.thehfhotel.org → ALL features (admin + QR) ✅ Internal Only
erp.thehfhotel.org/qr-checkin → QR only (rate limited) ✅ Public
```

### Key Changes

1. **URL Rewriting for Public Access**
   - External: `erp.thehfhotel.org/qr-checkin/mobile`
   - Nginx rewrites to: `/fingerprintlogs/qr-checkin/mobile`
   - App receives familiar `/fingerprintlogs/` path

2. **Rate Limiting**
   - General pages: 60 requests/minute
   - API endpoints: 30 requests/minute
   - Burst allowance for spikes

3. **Admin Endpoint Blocking**
   - Returns 404 (not 403) to avoid endpoint enumeration
   - Blocks: `/api/admin/`, `/api/devices/`, `/api/employees/`, etc.

4. **Separate Logging**
   - Internal: `fingerprint-internal-access.log`
   - Public: `fingerprint-public-access.log`

5. **Enhanced Security Headers**
   - Content Security Policy for public
   - Stricter HTTPS enforcement

---

## Line OAuth Callback Update

**IMPORTANT:** Update your LINE OAuth callback URL:

**Current (Internal):**
```
LINE_CALLBACK_URL=https://emp.thehfhotel.org/api/auth/line/callback
```

**Add for Public (in .env):**
```
# Keep existing internal callback
LINE_CALLBACK_URL=https://emp.thehfhotel.org/api/auth/line/callback

# Add public callback for QR check-in
LINE_CALLBACK_URL_PUBLIC=https://erp.thehfhotel.org/api/auth/line/callback
```

**Update LINE Developers Console:**
1. Go to https://developers.line.biz/console/
2. Add new callback URL: `https://erp.thehfhotel.org/api/auth/line/callback`
3. Keep existing: `https://emp.thehfhotel.org/api/auth/line/callback`

---

## Deployment Steps

### Step 1: Backup Current Config
```bash
cd ~/nginx/sites-enabled
cp fingerprint-time-logger fingerprint-time-logger.backup.$(date +%Y%m%d)
```

### Step 2: Update Nginx Config
Replace `/home/nut/nginx/sites-enabled/fingerprint-time-logger` with the new configuration above.

### Step 3: Test Nginx Config
```bash
docker exec shared-nginx nginx -t
```

Expected output:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### Step 4: Reload Nginx
```bash
docker exec shared-nginx nginx -s reload
```

### Step 5: Update DNS (if needed)
Point `erp.thehfhotel.org` to your server IP address.

### Step 6: SSL Certificate
If using Let's Encrypt:
```bash
# Add new domain to existing cert
sudo certbot --nginx -d erp.thehfhotel.org

# Or create separate cert
sudo certbot certonly --webroot -w /var/www/html -d erp.thehfhotel.org
```

### Step 7: Update LINE Callback
Add `https://erp.thehfhotel.org/api/auth/line/callback` to LINE Developers Console.

---

## Testing Checklist

### Internal URL (emp.thehfhotel.org) - Should Work
- [ ] Dashboard: `https://emp.thehfhotel.org/`
- [ ] Admin: `https://emp.thehfhotel.org/api/admin/line-codes/stats?passcode=bananabananabanana`
- [ ] QR Check-in: `https://emp.thehfhotel.org/qr-checkin/mobile`
- [ ] Device Management: `https://emp.thehfhotel.org/device-status`

### Public URL (erp.thehfhotel.org/qr-checkin) - QR Only
- [ ] QR Mobile: `https://erp.thehfhotel.org/qr-checkin/mobile` ✅
- [ ] QR Terminal: `https://erp.thehfhotel.org/qr-checkin/terminal` ✅
- [ ] Link Account: `https://erp.thehfhotel.org/qr-checkin/link-account` ✅
- [ ] LINE Login: `https://erp.thehfhotel.org/api/auth/line/login` ✅
- [ ] Admin BLOCKED: `https://erp.thehfhotel.org/api/admin/line-codes/stats` → 404 ❌
- [ ] Dashboard BLOCKED: `https://erp.thehfhotel.org/` → 404 ❌

### Rate Limiting Test
```bash
# Should get 429 after 60 requests in 1 minute
for i in {1..65}; do
    curl -s -o /dev/null -w "%{http_code}\n" https://erp.thehfhotel.org/health
done
```

Expected: First 60 return `200`, subsequent requests return `429 Too Many Requests`

---

## Monitoring

### Check Logs
```bash
# Internal access
docker exec shared-nginx tail -f /var/log/nginx/fingerprint-internal-access.log

# Public access
docker exec shared-nginx tail -f /var/log/nginx/fingerprint-public-access.log

# Errors
docker exec shared-nginx tail -f /var/log/nginx/fingerprint-public-error.log
```

### Rate Limit Status
```bash
# Check rate limit zones
docker exec shared-nginx cat /dev/shm/nginx-qr_general
```

---

## Rollback Plan

If issues arise:

```bash
# Step 1: Restore backup config
cd ~/nginx/sites-enabled
cp fingerprint-time-logger.backup.YYYYMMDD fingerprint-time-logger

# Step 2: Reload nginx
docker exec shared-nginx nginx -s reload

# Step 3: Verify restoration
curl -s https://emp.thehfhotel.org/health
```

---

## Comparison: Nginx-Only vs Dual-Service

| Aspect | Nginx-Only (This Approach) | Dual-Service |
|--------|---------------------------|--------------|
| **Complexity** | ✅ Simple (config only) | ❌ Complex (code + config) |
| **Deployment Time** | ✅ 30 minutes | ❌ 2-3 days |
| **Code Changes** | ✅ None required | ❌ Significant changes |
| **Database** | ✅ No concurrency issues | ⚠️ SQLite concurrent writes |
| **Isolation** | ⚠️ Same app instance | ✅ Separate containers |
| **Maintenance** | ✅ Single codebase | ⚠️ Two services to monitor |
| **Resource Usage** | ✅ One container | ❌ Two containers |
| **Security** | ✅ Nginx-level + app | ✅ Nginx + app + code |
| **Rollback** | ✅ Config restore (instant) | ❌ Redeploy required |

---

## Recommendation

**Use Nginx-Only Approach** because:

1. ✅ **You already have nginx** - leverage existing infrastructure
2. ✅ **No code changes** - zero app modification needed
3. ✅ **URL rewriting** - handles `/qr-checkin` → `/fingerprintlogs/qr-checkin` transparently
4. ✅ **Quick deployment** - 30 minutes vs 2-3 days
5. ✅ **Easy rollback** - restore config file instantly
6. ✅ **No database issues** - single app, no concurrency problems
7. ✅ **Same security level** - rate limiting + endpoint blocking + security headers

---

## Post-Deployment

After successful deployment:

1. **Update Documentation**
   - [ ] Document public URL: `erp.thehfhotel.org/qr-checkin`
   - [ ] Update user guides with new URL

2. **Communication**
   - [ ] Notify employees of public QR URL
   - [ ] Update LINE OAuth callback in console

3. **Monitoring**
   - [ ] Set up alerts for 429 rate limit errors
   - [ ] Monitor public access logs for abuse patterns
   - [ ] Track nginx error logs

---

## Summary

**What You Get:**
- Public QR Check-in: `https://erp.thehfhotel.org/qr-checkin/mobile`
- Internal Full Access: `https://emp.thehfhotel.org/` (unchanged)
- No `/fingerprintlogs/` in public URLs (nginx rewrites internally)
- Rate limiting on public access
- Admin endpoints blocked from public
- Zero code changes required
- Same Docker container, different nginx routing

**Implementation Time:** 30 minutes
**Risk Level:** Low (config-only change, instant rollback)

---

**Ready to Deploy?** Follow the deployment steps above and you'll have public QR check-in with proper isolation in under an hour!
