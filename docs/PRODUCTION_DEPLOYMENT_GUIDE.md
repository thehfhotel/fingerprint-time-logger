# Production Deployment Guide

## Nginx Reverse Proxy Setup

### Benefits
- ✅ **Eliminates HTTPS mixed content issues permanently**
- ✅ **Better performance** - static file serving, compression, caching
- ✅ **Security** - HTTPS termination, security headers
- ✅ **Scalability** - Load balancing, connection pooling
- ✅ **Simplified application** - No protocol handling in JavaScript

### Quick Setup

1. **Copy SSL certificates to server:**
```bash
sudo mkdir -p /etc/ssl/certs /etc/ssl/private
sudo cp your-cert.pem /etc/ssl/certs/
sudo cp your-key.pem /etc/ssl/private/
sudo chmod 600 /etc/ssl/private/your-key.pem
```

2. **Deploy with production compose:**
```bash
docker-compose -f docker-compose.production.yml up -d
```

3. **Simplify JavaScript (one-time change):**
```javascript
// Replace complex getApiUrl() with simple relative URLs
getApiUrl(endpoint = '') {
    return `/fingerprintlogs/api/${endpoint}`;
}
```

### Alternative: Cloudflare + Simple Relative URLs

If you prefer to keep using Cloudflare Tunnel:

1. **Add security headers to FastAPI:**
```python
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "upgrade-insecure-requests"
    return response
```

2. **Use only relative URLs in JavaScript:**
```javascript
// Simplified config.js - no protocol detection needed
class ConfigManager {
    getApiUrl(endpoint = '') {
        const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
        return `/fingerprintlogs/api/${cleanEndpoint}`;
    }
}
```

### Server-Side URL Generation (Alternative)

Add API endpoint to provide correct URLs:

```python
# In FastAPI
@app.get("/api/config/urls")
async def get_api_urls(request: Request):
    base_url = str(request.base_url).replace('http://', 'https://')
    return {
        "api_base": f"{base_url}api/",
        "websocket_url": f"{base_url.replace('https://', 'wss://')}ws"
    }
```

```javascript
// In frontend
async function loadConfig() {
    const response = await fetch('/fingerprintlogs/api/config/urls');
    const config = await response.json();
    this.apiBase = config.api_base;
}
```

## Deployment Options Summary

| Solution | Complexity | Reliability | Performance | Recommended |
|----------|------------|-------------|-------------|-------------|
| **Nginx Reverse Proxy** | Medium | Very High | Excellent | ✅ **Production** |
| **Relative URLs + CSP** | Low | High | Good | ✅ **Quick Fix** |
| **Server-side URLs** | Low | High | Good | ✅ **Alternative** |
| **Current JS Detection** | High | Low | Poor | ❌ **Problematic** |

## Migration Plan

### Phase 1: Immediate Fix (Today)
- Switch to relative URLs
- Add CSP headers
- Test in production

### Phase 2: Production Setup (This Week)
- Setup nginx reverse proxy
- Configure SSL certificates
- Deploy with production compose file
- Remove complex JavaScript URL logic

### Phase 3: Optimization (Future)
- Add monitoring and metrics
- Setup automated SSL renewal
- Implement proper logging
- Add backup automation