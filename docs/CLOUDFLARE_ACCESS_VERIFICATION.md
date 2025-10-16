# Cloudflare Access Verification Checklist

**Date**: 2025-10-16
**Purpose**: Verify Cloudflare Access configuration for public API migration
**Related**: Public API migration from `/qr-checkin/api/*` to `/api/public/*`

## Overview

After migrating public APIs to `/api/public/*` pattern, Cloudflare Access must be configured to:
- ✅ **Protect** `/api/private/*` - Require authentication for admin APIs
- ✅ **Allow** `/api/public/*` - Public access for QR terminals and mobile devices
- ✅ **Allow** legacy `/api/*` - Backward compatibility (temporary)

## Configuration Requirements

### 1. Cloudflare Access Application Settings

Navigate to: **Zero Trust** → **Access** → **Applications**

**Application 1: Protected Admin APIs**
```yaml
Name: Fingerprint Logger Admin APIs
Domain: erp.thehfhotel.org
Path: /api/private/*
Session Duration: 24 hours
Action: Block (require authentication)
```

**Application 2: Public Bypass Rules** (IMPORTANT)
```yaml
Name: QR Check-in Public APIs
Domain: erp.thehfhotel.org
Paths to bypass (DO NOT require authentication):
  - /api/public/*
  - /qr-checkin/mobile
  - /qr-checkin/link-line
Action: Bypass (allow without authentication)
```

### 2. Access Policies

**Policy 1: Admin Team Access** (for `/api/private/*`)
```yaml
Name: Admin Team
Action: Allow
Include:
  - Email domain: @thehfhotel.org
  - Specific emails: admin@thehfhotel.org, manager@thehfhotel.org
```

**Policy 2: Public Bypass** (for `/api/public/*`)
```yaml
Name: Public API Bypass
Action: Bypass
Include:
  - Everyone
Paths:
  - /api/public/*
```

## Verification Tests

### Test 1: Protected API Requires Authentication
```bash
# Should redirect to Cloudflare Access login page
curl -I https://erp.thehfhotel.org/api/private/devices/

# Expected: 302 redirect to Cloudflare login
# Actual: [VERIFY IN PRODUCTION]
```

### Test 2: Public QR API Works Without Authentication
```bash
# Should return JSON response without authentication
curl https://erp.thehfhotel.org/api/public/qr-checkin/terminals

# Expected: [{"id":2,"name":"HF",...}]
# Actual: [VERIFY IN PRODUCTION]
```

### Test 3: LINE Auth Works Without Authentication
```bash
# Should return error response (not redirect to login)
curl -X POST https://erp.thehfhotel.org/api/public/auth/line/verify-token \
  -H "Content-Type: application/json" \
  -d '{"token":"test"}'

# Expected: {"detail":"Invalid token"}
# Actual: [VERIFY IN PRODUCTION]
```

### Test 4: QR Terminal Mobile Page Accessible
```bash
# Should load HTML page without authentication
curl https://erp.thehfhotel.org/qr-checkin/mobile

# Expected: HTML page with QR scanner
# Actual: [VERIFY IN PRODUCTION]
```

### Test 5: Legacy API Backward Compatibility
```bash
# Should redirect to /api/public/* and work
curl -L https://erp.thehfhotel.org/qr-checkin/api/qr-checkin/terminals

# Expected: [{"id":2,"name":"HF",...}]
# Actual: [VERIFY IN PRODUCTION]
```

## Common Issues and Solutions

### Issue 1: Public APIs Blocked by Cloudflare Access

**Symptoms**:
- QR terminals can't load terminal list
- Mobile check-in redirects to login page
- LINE OAuth callback fails

**Cause**: `/api/public/*` not configured as bypass rule

**Solution**:
1. Navigate to: **Zero Trust** → **Access** → **Applications**
2. Click: **Add an application** → **Self-hosted**
3. Configure:
   - Application name: `QR Check-in Public APIs`
   - Path: `/api/public/*`
   - Action: **Bypass** (not Service Auth)
4. Add policy: Include **Everyone**, Action **Bypass**

### Issue 2: Protected APIs Not Requiring Authentication

**Symptoms**:
- Anyone can access `/api/private/*` without login
- No Cloudflare Access prompt appears

**Cause**: Access application not configured or disabled

**Solution**:
1. Verify Access application exists for `/api/private/*`
2. Verify application is **Enabled** (not disabled)
3. Verify path pattern includes trailing `/*`
4. Clear browser cache and test in incognito mode

### Issue 3: Legacy Routes Redirect to Login

**Symptoms**:
- QR terminals using old `/qr-checkin/api/*` URLs fail
- Error: "Cloudflare Access requires authentication"

**Cause**: Legacy paths not included in bypass rules

**Solution**:
1. Add bypass rule for legacy pattern
2. Alternative: Update QR terminal firmware to use new URLs

## Production Deployment Checklist

### Before Deployment
- [ ] Verify nginx configuration includes `/api/public/*` location block
- [ ] Verify nginx configuration forwards Cloudflare JWT headers for `/api/private/*`
- [ ] Verify application container has updated code with new API paths
- [ ] Verify frontend JavaScript files use `/api/public/*` pattern

### During Deployment
- [ ] Reload nginx: `docker exec nginx nginx -s reload`
- [ ] Configure Cloudflare Access application for `/api/private/*`
- [ ] Configure Cloudflare bypass rule for `/api/public/*`
- [ ] Verify bypass rule includes all public paths

### After Deployment
- [ ] Test protected APIs require authentication (Test 1)
- [ ] Test public QR APIs work without authentication (Test 2)
- [ ] Test LINE OAuth works without authentication (Test 3)
- [ ] Test QR terminal mobile page loads (Test 4)
- [ ] Test legacy API backward compatibility (Test 5)
- [ ] Monitor Cloudflare Access logs for blocked requests
- [ ] Verify no 403 errors in application logs

## Local Development Notes

**Current Environment**: Local development (localhost:5000)

Since Cloudflare Access only applies to production domain (`erp.thehfhotel.org`), local testing shows:
- ✅ All APIs work without authentication
- ✅ No Cloudflare Access interception
- ✅ Nginx configuration prepared for production deployment

**Production Differences**:
- Production domain will have Cloudflare Access enabled
- `/api/private/*` will require authentication
- `/api/public/*` must be configured as bypass rule

## Next Steps

1. **Deploy to Production** (when ready)
   ```bash
   # On production server
   cd /home/nut/fingerprint-time-logger
   git pull origin main
   docker compose build --no-cache app
   docker compose up -d
   docker exec nginx nginx -s reload
   ```

2. **Configure Cloudflare Access** (15 minutes)
   - Follow steps in CLOUDFLARE_ACCESS_SETUP.md
   - Ensure `/api/public/*` bypass rule is created

3. **Verify Production** (10 minutes)
   - Run all verification tests
   - Monitor Cloudflare Access logs
   - Check application logs for errors

## References

- [CLOUDFLARE_ACCESS_SETUP.md](./CLOUDFLARE_ACCESS_SETUP.md) - Detailed setup instructions
- [Cloudflare Access Documentation](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-apps/)
- [Cloudflare Bypass Rules](https://developers.cloudflare.com/cloudflare-one/policies/access/#bypass)
