# HTTPS Mixed Content Troubleshooting Guide

## Overview
This guide documents the resolution of HTTPS mixed content errors in production environments, specifically when using Cloudflare Tunnel with proxy setups.

## Problem Description
**Issue**: JavaScript debug logs show HTTPS URLs being generated, but browser console reports HTTP URLs being requested, causing mixed content security violations.

**Symptoms**:
- Debug logs: `🌐 FINAL URL RETURNED: https://domain.com/api/endpoint`
- Browser error: `Mixed Content: requested an insecure resource 'http://domain.com/api/endpoint'`
- Fetch requests fail with `TypeError: Failed to fetch`

## Root Causes Identified

### 1. Variable Scoping in URL Generation
**Problem**: HTTPS protocol fix applied after debug logging, potentially not affecting returned value.

**Original Code**:
```javascript
// Debug logging first
console.log('🌐 FINAL URL RETURNED:', absoluteUrl);

// HTTPS fix after logging (too late)
if (window.location.protocol === 'https:' && absoluteUrl.startsWith('http:')) {
    absoluteUrl = absoluteUrl.replace('http:', 'https:');
}
```

**Fix**: Move HTTPS correction before debug logging:
```javascript
// HTTPS fix BEFORE debug logging
if (window.location.protocol === 'https:' && absoluteUrl.startsWith('http:')) {
    absoluteUrl = absoluteUrl.replace('http:', 'https:');
    console.log('🔒 FORCED HTTPS URL:', absoluteUrl);
}

// Debug logging after fix
console.log('🌐 FINAL URL RETURNED:', absoluteUrl);
```

### 2. Browser Caching Issues
**Problem**: Browser cache retains old JavaScript files despite server-side updates.

**Symptoms**:
- Server logs show new code deployed
- Browser continues using cached versions
- Mixed content errors persist despite fixes

**Solution**: Aggressive cache busting with multiple parameters:
```javascript
const timestamp = Date.now();
const randomId = Math.random().toString(36).substring(7);
const buildNumber = '2025011700'; // Build timestamp
const version = `v2.5-debug-${buildNumber}`;
const cacheBuster = `${timestamp}.${randomId}&build=${buildNumber}`;
document.write(`<script src="static/js/config.js?v=${cacheBuster}&version=${version}&force=${Date.now()}"><\/script>`);
```

### 3. Async Configuration Loading
**Problem**: API calls made before configuration is loaded, causing fallback to incorrect protocol.

**Solution**: Always await configuration loading:
```javascript
async function toggleStatus(badgeNumber, newStatus) {
    try {
        // Ensure config is loaded first
        await appConfig.loadConfig();

        const response = await fetch(appConfig.getApiUrl(`employees/${badgeNumber}/status`), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: newStatus })
        });
    } catch (error) {
        console.error('Error updating status:', error);
    }
}
```

## Debugging Steps

### 1. Verify URL Generation
Check browser console for debug logs:
```javascript
console.log('getApiUrl debug:', {
    windowProtocol: window.location.protocol,
    isHttpsPage: window.location.protocol === 'https:',
    absoluteUrl: absoluteUrl,
    finalUrl: /* returned value */
});
```

### 2. Test Direct API Access
Verify backend endpoints work correctly:
```bash
curl -X PUT -H "Content-Type: application/json" \
     -d '{"is_active": false}' \
     "https://domain.com/api/employees/1/status"
```

### 3. Check Browser Cache
- Open DevTools → Network tab
- Check "Disable cache" option
- Hard refresh (Ctrl+Shift+R)
- Compare timestamps in resource URLs

### 4. Verify Configuration Loading
Add debug logging to configuration manager:
```javascript
async loadConfig() {
    if (this.loaded) {
        console.log('Config already loaded:', this.config);
        return this.config;
    }

    try {
        const response = await fetch(`${this.basePath}/api/devices/app-config`);
        if (response.ok) {
            this.config = await response.json();
            this.loaded = true;
            console.log('Configuration loaded successfully:', this.config);
            return this.config;
        }
    } catch (error) {
        console.warn('Failed to load configuration:', error);
        this.config = this.getDefaultConfig();
        this.loaded = true;
        return this.config;
    }
}
```

## Prevention Strategies

### 1. Bulletproof HTTPS Detection
```javascript
getApiUrl(endpoint = '') {
    // Multiple protocol detection methods
    const isHttpsPage = window.location.protocol === 'https:' ||
                       window.location.href.startsWith('https://') ||
                       window.location.host.includes('cloudflare') ||
                       window.location.host.includes('.org');

    const protocol = isHttpsPage ? 'https:' : window.location.protocol;
    let absoluteUrl = `${protocol}//${window.location.host}${this.basePath}/api/${endpoint}`;

    // Force HTTPS if page is HTTPS (apply BEFORE any logging)
    if (window.location.protocol === 'https:' && absoluteUrl.startsWith('http:')) {
        absoluteUrl = absoluteUrl.replace('http:', 'https:');
    }

    return absoluteUrl;
}
```

### 2. Consistent Cache Busting
Apply to ALL HTML pages loading JavaScript:
```javascript
const timestamp = Date.now();
const randomId = Math.random().toString(36).substring(7);
const buildNumber = '2025011700';
const version = `v2.5-debug-${buildNumber}`;
const cacheBuster = `${timestamp}.${randomId}&build=${buildNumber}`;
document.write(`<script src="static/js/config.js?v=${cacheBuster}&version=${version}&force=${Date.now()}"><\/script>`);
```

### 3. Configuration Loading Pattern
Always follow this pattern for API calls:
```javascript
async function apiFunction() {
    try {
        // 1. Ensure config loaded
        await appConfig.loadConfig();

        // 2. Generate URL
        const url = appConfig.getApiUrl('endpoint');

        // 3. Make request
        const response = await fetch(url, { /* options */ });

        // 4. Handle response
        if (!response.ok) throw new Error(`Request failed: ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('API error:', error);
        throw error;
    }
}
```

## Testing Checklist

### Local Testing
- [ ] HTTPS works on localhost with self-signed certificates
- [ ] HTTP fallback works for development
- [ ] Configuration loads before API calls
- [ ] Cache busting prevents stale JavaScript

### Production Testing
- [ ] Cloudflare Tunnel HTTPS enforcement works
- [ ] Mixed content errors eliminated
- [ ] API endpoints respond with correct protocol
- [ ] Browser cache invalidation effective

### Cross-Environment Testing
- [ ] Same code works in both HTTP and HTTPS environments
- [ ] Protocol detection adapts to environment
- [ ] No hardcoded protocol assumptions
- [ ] Graceful fallback for configuration failures

## Deployment Notes

1. **Always restart application** after JavaScript changes to ensure file updates
2. **Test in production environment** - caching behavior differs from development
3. **Monitor browser console** for mixed content warnings
4. **Verify cache busting** by checking resource URLs include fresh timestamps
5. **Document protocol handling** for future maintenance

## Related Files
- `static/js/config.js` - Main configuration and URL generation
- `static/nickname-management.html` - Employee management interface
- `static/export.html` - Data export interface
- `static/individual-attendance.html` - Reference implementation (working example)

## Success Criteria
✅ No mixed content errors in browser console
✅ All API calls use HTTPS in production
✅ Cache busting prevents stale JavaScript
✅ Configuration loads before API requests
✅ Same code works in both HTTP and HTTPS environments