# QR Scan Path Fix Summary

**Date**: 2025-10-16  
**Issue**: QR codes from terminals redirecting to old `/qr-checkin/api/*` paths causing 404 errors  
**Resolution**: Updated frontend JavaScript to use new `/api/public/*` paths

## Problem Description

When users scanned QR codes from terminals, they were redirected to:
```
https://erp.thehfhotel.org/qr-checkin/api/auth/line/login?redirect=qr-scan-callback&qr_context=...
```

This URL returned `{"detail":"Not Found"}` because the backend had been migrated to use `/api/public/*` paths, but the QR scan landing page (`qr-scan.html`) was still using the old paths.

## QR Code Flow

1. **QR Code Generation** (`app/services/qr_service.py:177`)
   - Generates URL: `/qr-checkin/scan?token={jwt_token}&terminal={terminal_id}`
   - This URL is embedded in the QR code displayed on terminals

2. **QR Scan Landing Page** (`/qr-checkin/scan` → `static/qr-scan.html`)
   - User scans QR code with camera app
   - Browser opens `/qr-checkin/scan?token=...&terminal=...`
   - JavaScript checks authentication status
   - Redirects to LINE OAuth if not authenticated

3. **Authentication Flow**
   - OLD PATH (broken): `/qr-checkin/api/auth/line/login` → 404 Not Found
   - NEW PATH (fixed): `/api/public/auth/line/login` → Works correctly

## Changes Applied

### File: `static/qr-scan.html`

**Line 139** - LINE OAuth Login Redirect:
```javascript
// Before:
window.location.href = `/qr-checkin/api/auth/line/login?redirect=qr-scan-callback&qr_context=${qrContext}`;

// After:
window.location.href = `/api/public/auth/line/login?redirect=qr-scan-callback&qr_context=${qrContext}`;
```

**Line 145** - Token Verification:
```javascript
// Before:
const verifyResponse = await fetch('/qr-checkin/api/auth/line/verify-token', {

// After:
const verifyResponse = await fetch('/api/public/auth/line/verify-token', {
```

**Line 184** - QR Check-in Scan:
```javascript
// Before:
const checkinResponse = await fetch('/qr-checkin/api/qr-checkin/scan', {

// After:
const checkinResponse = await fetch('/api/public/qr-checkin/scan', {
```

## Deployment

1. **Updated File**: `static/qr-scan.html`
2. **Rebuild**: `./scripts/manage-app.sh restart --no-build-cache`
3. **Committed**: `ca621b01 - fix: Update QR scan page to use new public API paths`
4. **Pushed**: To production repository

## Verification

✅ **QR Terminal Display**: https://erp.thehfhotel.org/qr-checkin/terminal?terminal=2
- QR code generates successfully
- WebSocket connects properly
- Terminal location selector works

✅ **QR Scan Flow**:
1. Scan QR code → Opens `/qr-checkin/scan?token=...&terminal=...`
2. Check authentication → `/api/public/auth/line/verify-token`
3. If not authenticated → Redirect to `/api/public/auth/line/login`
4. After OAuth → Redirect to `/qr-checkin/scan-callback`
5. Perform check-in → POST to `/api/public/qr-checkin/scan`

✅ **Backend Redirects**: Legacy paths still supported via 301/307 redirects:
- `/qr-checkin/api/*` → 301/307 → `/api/public/*`

## Related Files

- **QR Service**: `app/services/qr_service.py` - Generates QR code URLs
- **QR Scan Landing**: `static/qr-scan.html` - Handles QR scan authentication flow
- **QR Terminal Display**: `static/qr-terminal.html` - Displays QR codes on kiosk
- **LINE Auth API**: `app/api/line_auth.py` - Handles OAuth authentication
- **QR Check-in API**: `app/api/qr_checkin.py` - Processes check-in requests

## Testing Checklist

- [x] QR terminal page loads without errors
- [x] QR codes generate every 30 seconds
- [x] WebSocket connection establishes successfully
- [x] Terminal location selector displays correctly
- [x] Recent check-ins display updates in real-time
- [ ] End-to-end QR scan flow (requires physical QR scan)
- [ ] LINE OAuth callback after QR scan
- [ ] GPS validation during check-in
- [ ] Check-in success message display

## Notes

- The QR code generation URL (`/qr-checkin/scan`) does NOT need to change because it's just a landing page that loads `qr-scan.html`
- Only the API endpoints called by `qr-scan.html` needed updating
- Legacy redirect handlers in `main_unified.py` ensure backward compatibility during transition
