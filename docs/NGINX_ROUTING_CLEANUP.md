# Nginx Routing Cleanup - QR Check-in URL Consolidation

**Date**: 2025-10-16
**Issue**: Duplicate QR check-in URLs causing confusion
**Resolution**: Block legacy `/fingerprintlogs/qr-checkin/*` pattern via nginx

## Problem Description

Both QR check-in URL patterns were accessible, creating duplicate canonical URLs:

```
✅ Correct:  https://erp.thehfhotel.org/qr-checkin/terminal
❌ Legacy:   https://erp.thehfhotel.org/fingerprintlogs/qr-checkin/terminal
```

This caused:
- SEO confusion with duplicate content
- User confusion about which URL to use
- Unnecessary maintenance of multiple URL patterns
- Potential issues with URL sharing and bookmarks

## Root Cause

Nginx configuration had multiple location blocks handling the same endpoint:

1. **Line 38-60**: `/qr-checkin/` - Correct rewrite pattern
2. **Line 128-139**: `/fingerprintlogs/` - General catch-all that also handled `/fingerprintlogs/qr-checkin/`

The general `/fingerprintlogs/` location block was proxying **all** fingerprintlogs requests, including the legacy QR check-in path.

## Solution Implementation

### Changes Made

**File**: `/home/nut/nginx/sites-enabled/erp-thehfhotel-org`

Added explicit 404 block for legacy QR check-in pattern (lines 66-69):

```nginx
# Block direct access to /fingerprintlogs/qr-checkin/* (must come before general /fingerprintlogs/)
location /fingerprintlogs/qr-checkin/ {
    return 404;
}
```

**Location Block Order** (critical for nginx routing):
1. Line 21-34: `/qr-checkin/ws` - WebSocket (most specific)
2. Line 38-60: `/qr-checkin/` - QR check-in rewrite (specific)
3. Line 66-69: `/fingerprintlogs/qr-checkin/` - Block legacy (specific) ✅ NEW
4. Line 71-76: `/fingerprintlogs/api/auth/line/` - LINE OAuth (specific)
5. Line 78-81: `/static/` - Static files (specific)
6. Line 84-89: `/fingerprintlogs/static/` - Legacy static (specific)
7. Line 93-107: `/api/public/` - Public APIs (specific)
8. Line 114-125: `/api/private/` - Private APIs (specific)
9. Line 128-139: `/fingerprintlogs/` - General catch-all (least specific)

### Why This Works

Nginx processes location blocks in this order:
1. **Exact matches** (`location = /path`)
2. **Longest prefix matches** (`location ^~ /path`)
3. **Regular expression matches** (`location ~ pattern`)
4. **Prefix matches** (`location /path`)

By placing the **specific blocking rule** for `/fingerprintlogs/qr-checkin/` BEFORE the general `/fingerprintlogs/` catch-all, nginx matches the more specific pattern first and returns 404.

## Deployment

```bash
# Applied nginx configuration
docker exec shared-nginx nginx -s reload

# Verified configuration loaded
docker exec shared-nginx nginx -T 2>&1 | grep -A 3 "location /fingerprintlogs/qr-checkin"
# Output:
# location /fingerprintlogs/qr-checkin/ {
#     return 404;
# }
```

## URL Behavior After Fix

### Correct URL (works)
```bash
curl https://erp.thehfhotel.org/qr-checkin/terminal?terminal=2
# Returns: 200 OK (QR terminal page)
```

### Legacy URL (blocked)
```bash
curl https://erp.thehfhotel.org/fingerprintlogs/qr-checkin/terminal?terminal=2
# Returns: 404 Not Found
```

### Internal Routing (still works)
The rewrite rule in `/qr-checkin/` location block still works:
```
External:  /qr-checkin/terminal
           ↓ (nginx rewrite)
Internal:  /fingerprintlogs/qr-checkin/terminal
           ↓ (FastAPI routing)
Backend:   app/api/qr_checkin.py
```

## Verification Steps

### 1. Check Nginx Configuration
```bash
docker exec shared-nginx nginx -T | grep -A 5 "location /fingerprintlogs/qr-checkin"
```

### 2. Test Correct URL
```bash
curl -I https://erp.thehfhotel.org/qr-checkin/terminal?terminal=2
# Expected: HTTP/1.1 200 OK
```

### 3. Test Legacy URL (should be blocked)
```bash
curl -I https://erp.thehfhotel.org/fingerprintlogs/qr-checkin/terminal?terminal=2
# Expected: HTTP/1.1 404 Not Found
```

### 4. Monitor Access Logs
```bash
docker exec shared-nginx tail -f /var/log/nginx/erp-access.log
# Look for 404 responses to /fingerprintlogs/qr-checkin/* requests
```

## URL Patterns Summary

### ✅ Accessible Public URLs
```
# QR Check-in (canonical)
https://erp.thehfhotel.org/qr-checkin/terminal
https://erp.thehfhotel.org/qr-checkin/mobile
https://erp.thehfhotel.org/qr-checkin/scan

# Authentication
https://erp.thehfhotel.org/api/public/auth/line/login
https://erp.thehfhotel.org/api/public/auth/line/callback

# Public APIs
https://erp.thehfhotel.org/api/public/qr-checkin/scan
https://erp.thehfhotel.org/api/public/qr-checkin/terminals
https://erp.thehfhotel.org/api/public/qr-checkin/kiosk/{id}
```

### ❌ Blocked Legacy URLs
```
# Legacy QR check-in pattern (now returns 404)
https://erp.thehfhotel.org/fingerprintlogs/qr-checkin/terminal
https://erp.thehfhotel.org/fingerprintlogs/qr-checkin/mobile
https://erp.thehfhotel.org/fingerprintlogs/qr-checkin/scan
```

### 🔒 Protected Admin URLs (Cloudflare Access)
```
# These remain accessible but require Cloudflare Access authentication
https://erp.thehfhotel.org/fingerprintlogs/
https://erp.thehfhotel.org/fingerprintlogs/device-status
https://erp.thehfhotel.org/api/private/*
```

## Expected User Impact

### Immediate
- **Existing bookmarks** to legacy URLs will return 404
- **Browser history** with legacy URLs will fail
- **Direct URL typing** of legacy pattern will fail

### Positive Long-term
- Single canonical URL pattern (better SEO)
- Clearer documentation and user guidance
- Reduced confusion about which URL to use
- Easier maintenance with single URL pattern

## Documentation Updates

Updated the following documentation to reflect canonical URL pattern:

- ✅ `/home/nut/fingerprint-time-logger/docs/NGINX_DEPLOYMENT.md`
- ✅ `/home/nut/fingerprint-time-logger/docs/GPS_LOCATION_SETUP.md`
- ✅ `/home/nut/fingerprint-time-logger/CLAUDE.md`

## Troubleshooting

### Issue: Legacy URL still works
**Cause**: Nginx configuration not reloaded
**Solution**: `docker exec shared-nginx nginx -s reload`

### Issue: Correct URL returns 404
**Cause**: Blocking rule placed incorrectly or too broad
**Solution**: Verify location block order, ensure blocking rule is specific

### Issue: 301 redirect loop
**Cause**: HTTP to HTTPS redirect interfering
**Solution**: This is expected behavior from Cloudflare, not an issue

### Issue: WebSocket connections failing
**Cause**: `/qr-checkin/ws` location block order
**Solution**: WebSocket block MUST come before general `/qr-checkin/` block

## Related Changes

- **v3.1.0**: QR code timing improvements (60s validity, 15s grace period)
- **Commit `58612b14`**: Button text clarity improvements
- **Commit `de3789fa`**: Dynamic QR refresh scheduling

## Success Criteria

- [x] Nginx configuration updated with blocking rule
- [x] Nginx reloaded successfully
- [x] Configuration verified in nginx -T output
- [x] Legacy URL pattern blocked (returns 404)
- [x] Correct URL pattern works (returns 200)
- [x] Documentation updated

## Rollback Plan

If issues occur, remove the blocking rule:

```bash
# Edit nginx config
vim /home/nut/nginx/sites-enabled/erp-thehfhotel-org

# Remove lines 66-69:
# location /fingerprintlogs/qr-checkin/ {
#     return 404;
# }

# Reload nginx
docker exec shared-nginx nginx -s reload
```

This will restore access to legacy URLs while you investigate the issue.
