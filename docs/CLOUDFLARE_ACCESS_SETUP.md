# Cloudflare Access Setup for Protected Admin APIs

**Date**: 2025-10-16
**Purpose**: Configure Cloudflare Access to protect `/api/private/*` endpoints

## Overview

Cloudflare Access provides authentication for protected admin APIs, ensuring only authorized users can access sensitive management endpoints.

### Architecture

```
User Browser
    ↓
Cloudflare Access (Authentication Layer)
    ↓
Nginx Reverse Proxy (HTTPS Termination)
    ↓
FastAPI Application (Protected APIs)
```

## Protected API Endpoints

All admin management endpoints now use the `/api/private/*` pattern:

### Attendance Management
- `GET/POST /api/private/attendance/` - Attendance records
- `GET /api/private/attendance/summary` - Attendance summary
- `GET /api/private/attendance/export/csv` - CSV export

### Device Management
- `GET /api/private/devices/` - Device list and status
- `PUT /api/private/devices/{id}` - Update device configuration
- `POST /api/private/devices/` - Create new device
- `GET /api/private/devices/app-config` - Application configuration
- `POST /api/private/devices/time/sync` - Sync device time

### Employee Management
- `GET /api/private/employees/` - Employee list
- `PUT /api/private/employees/{badge}/nickname` - Update nickname
- `PUT /api/private/employees/{badge}/status` - Update status
- `PUT /api/private/employees/{badge}/hidden` - Update visibility
- `DELETE /api/private/employees/{badge}` - Delete employee

### System Management
- `GET /api/private/system/health` - Health check
- `GET /api/private/system/metrics` - System metrics
- `GET /api/private/system/logs` - System logs

### Admin Authentication
- `POST /api/private/admin/auth/login` - Admin login
- `POST /api/private/admin/auth/validate` - Token validation
- `POST /api/private/admin/auth/logout` - Admin logout

### Admin LINE Codes
- `POST /api/private/admin/line-codes/generate` - Generate linking code
- `POST /api/private/admin/line-codes/regenerate` - Regenerate code
- `POST /api/private/admin/line-codes/unlink` - Unlink account

### Auto-Import System
- `GET /api/private/auto-import/status` - Import status
- `POST /api/private/auto-import/trigger` - Trigger manual import
- `POST /api/private/refresh` - Manual refresh

## Cloudflare Access Configuration Steps

### Step 1: Create Access Application

1. **Login to Cloudflare Dashboard**
   - Navigate to: https://dash.cloudflare.com
   - Select your domain: `thehfhotel.org`

2. **Navigate to Zero Trust Dashboard**
   - Go to: **Zero Trust** → **Access** → **Applications**
   - Click: **Add an application**

3. **Select Application Type**
   - Choose: **Self-hosted**

4. **Configure Application Details**
   ```yaml
   Application name: Fingerprint Logger Admin APIs
   Session Duration: 24 hours
   Application domain: erp.thehfhotel.org
   Path: /api/private/*
   ```

5. **Add Additional Paths (if needed)**
   - `/admin/terminal-gps` - Admin GPS configuration page
   - `/nickname-management` - Employee management page
   - `/status` - System status page
   - `/export` - Data export page

### Step 2: Configure Access Policies

#### Policy 1: Admin Team Access
```yaml
Policy name: Admin Team
Action: Allow
Include:
  - Email domain: @thehfhotel.org
  - Email addresses:
    - admin@thehfhotel.org
    - manager@thehfhotel.org
Session duration: 24 hours
```

#### Policy 2: IP Whitelist (Optional)
```yaml
Policy name: Office IP Whitelist
Action: Allow
Include:
  - IP ranges: [Your office IP ranges]
```

### Step 3: Configure JWT Validation (Optional)

If your FastAPI application needs to validate Cloudflare Access tokens:

1. **Get Cloudflare Team Domain**
   - Found in: **Zero Trust** → **Settings** → **Custom Pages**
   - Example: `thehfhotel.cloudflareaccess.com`

2. **Add JWT Validation to FastAPI** (future enhancement)
   ```python
   # app/middleware/cloudflare_access.py
   from fastapi import Header, HTTPException
   import jwt

   CLOUDFLARE_TEAM_DOMAIN = "thehfhotel.cloudflareaccess.com"

   async def verify_cloudflare_jwt(
       cf_access_jwt_assertion: str = Header(None)
   ):
       if not cf_access_jwt_assertion:
           raise HTTPException(401, "No Cloudflare Access token")

       # Verify JWT signature with Cloudflare public keys
       # Implementation details in official docs
   ```

### Step 4: Test Configuration

#### Test 1: Protected API Access
```bash
# Without authentication (should redirect to Cloudflare login)
curl https://erp.thehfhotel.org/api/private/devices/

# With valid Cloudflare session (should work)
# Access from authenticated browser session
```

#### Test 2: Public API Access
```bash
# Public QR check-in APIs should work without authentication
curl https://erp.thehfhotel.org/api/public/qr-checkin/terminals

# LINE OAuth endpoints should work without authentication
curl https://erp.thehfhotel.org/api/public/auth/line/callback
```

#### Test 3: Dashboard Pages
1. Navigate to: https://erp.thehfhotel.org/
2. Should redirect to Cloudflare Access login page
3. After authentication, dashboard should load successfully
4. Browser console should show no 404 errors for `/api/private/*` calls

## Nginx Configuration (Already Applied)

The nginx configuration has been updated to forward Cloudflare Access JWT headers:

```nginx
# Protected Admin APIs (Cloudflare Access: /api/private/*)
location /api/private/ {
    proxy_pass http://fingerprint-time-logger:5000;

    # Pass Cloudflare Access JWT headers
    proxy_set_header Cf-Access-Jwt-Assertion $http_cf_access_jwt_assertion;
    proxy_set_header Cf-Access-Authenticated-User-Email $http_cf_access_authenticated_user_email;

    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Disable caching for admin APIs
    proxy_no_cache 1;
    proxy_cache_bypass 1;
    add_header Cache-Control "no-cache, no-store, must-revalidate";
}
```

## Deployment Steps

### 1. Apply Nginx Configuration

```bash
# On production server
cd /home/nut/nginx

# Verify nginx configuration syntax
docker exec nginx nginx -t

# Reload nginx to apply changes (zero-downtime)
docker exec nginx nginx -s reload

# Verify nginx is running
docker ps | grep nginx
```

### 2. Configure Cloudflare Access

Follow steps in **Cloudflare Access Configuration Steps** section above.

### 3. Verify Frontend Updates

All protected JavaScript files have been updated to use `/api/private/*`:
- ✅ `config.js` - ConfigManager generates `/api/private/*` URLs
- ✅ `config-simple.js` - ConfigManager generates `/api/private/*` URLs
- ✅ `terminal-gps-admin.js` - Direct fetch() calls updated
- ✅ `qr-terminal-gps.js` - Direct fetch() calls updated

Public QR check-in files correctly use `/api/public/*`:
- ✅ `qr-terminal.js`
- ✅ `qr-scan.html`
- ✅ `mobile-checkin.html`

### 4. Restart Application (if needed)

```bash
# On production server
cd /home/nut/fingerprint-time-logger

# Restart application container
docker compose restart app

# Verify application is running
docker logs fingerprint-time-logger --tail 50
```

## Testing Checklist

### ✅ Backend Verification
- [ ] All protected APIs accessible at `/api/private/*`
- [ ] Router endpoints work with trailing slash
- [ ] Standalone endpoints work without trailing slash

### ✅ Nginx Verification
- [ ] Nginx configuration syntax valid (`nginx -t`)
- [ ] Nginx reloaded successfully
- [ ] Cloudflare JWT headers forwarded correctly

### ✅ Cloudflare Access Verification
- [ ] Access application created for `/api/private/*`
- [ ] Access policies configured correctly
- [ ] Authentication redirects work
- [ ] Authenticated users can access protected APIs

### ✅ Frontend Verification
- [ ] Dashboard loads successfully
- [ ] No 404 errors in browser console
- [ ] API calls use `/api/private/*` pattern
- [ ] ConfigManager generates correct URLs

### ✅ Public API Verification
- [ ] QR check-in APIs work without authentication
- [ ] LINE OAuth flow works without authentication
- [ ] Public pages accessible without Cloudflare login

### ✅ End-to-End Verification
- [ ] Login to dashboard through Cloudflare Access
- [ ] View employee list
- [ ] View attendance records
- [ ] Export CSV data
- [ ] Update device configuration
- [ ] Trigger manual import
- [ ] Check system status

## Troubleshooting

### Issue: 404 on /api/private/* endpoints

**Cause**: Application not serving routes on root app

**Solution**:
```bash
# Verify backend routes are registered
docker logs fingerprint-time-logger | grep "CREATING ROOT APP"

# Should see protected router registrations
docker logs fingerprint-time-logger | grep "api/private"
```

### Issue: Cloudflare Access not protecting endpoints

**Cause**: Access application path pattern incorrect

**Solution**:
- Verify path is `/api/private/*` (with trailing `/*`)
- Check that application is enabled
- Clear browser cache and test in incognito mode

### Issue: CORS errors on /api/private/* calls

**Cause**: CORS middleware not applied to root app

**Solution**:
```python
# Verify CORS middleware in app/main_unified.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Issue: 401 Unauthorized after Cloudflare login

**Cause**: JWT headers not forwarded or application rejecting tokens

**Solution**:
- Verify nginx forwards `Cf-Access-Jwt-Assertion` header
- Check FastAPI application accepts requests (no middleware rejecting)
- Review Cloudflare Access logs in dashboard

## Security Considerations

### Protected Endpoints
- All `/api/private/*` endpoints require Cloudflare Access authentication
- Session duration: 24 hours (configurable)
- JWT tokens validated by Cloudflare

### Public Endpoints
- `/api/public/*` - Public QR check-in system (no auth required)
- `/docs`, `/redoc` - API documentation (optional: protect with Access)
- `/health` - Health check endpoint (optional: protect with Access)

### Best Practices
- Use short session durations for sensitive operations
- Enable IP whitelisting for additional security
- Monitor Cloudflare Access logs regularly
- Review access policies quarterly
- Use email domain restrictions when possible

## References

- **Cloudflare Access Documentation**: https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-apps/
- **JWT Validation Guide**: https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/
- **Nginx Proxy Headers**: https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/
- **FastAPI Security**: https://fastapi.tiangolo.com/tutorial/security/

## Migration Status

**Current Status**: 80% Complete

- ✅ **Backend**: 100% - All protected APIs migrated to `/api/private/*`
- ✅ **Frontend**: 100% - All JavaScript files updated
- ✅ **Nginx**: 100% - Configuration updated with Cloudflare JWT forwarding
- ⏸️ **Cloudflare Access**: 0% - Awaiting configuration in dashboard
- ⏸️ **Testing**: 0% - Awaiting production deployment

**Next Steps**:
1. Configure Cloudflare Access application and policies (15 minutes)
2. Reload nginx on production server (1 minute)
3. Test protected and public API access (10 minutes)
4. Verify end-to-end workflows (15 minutes)

**Estimated Completion**: 30-60 minutes
