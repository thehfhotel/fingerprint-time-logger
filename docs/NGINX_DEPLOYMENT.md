# Nginx Deployment Guide

## Overview

This guide documents the nginx reverse proxy setup for the fingerprint time logger application with Cloudflare Tunnel integration.

## Architecture

```
User Browser
    ↓
Cloudflare Edge (HTTPS + DDoS Protection)
    ↓
Cloudflare Tunnel (Secure tunnel without open ports)
    ↓
Nginx Reverse Proxy (192.168.100.228:80)
    ├─ Path routing and URL rewriting
    ├─ Security controls (admin endpoint blocking)
    └─ Static file caching
    ↓
Docker Application (fingerprint-time-logger:5000)
```

## Domain Configuration

### Internal Domain: emp.thehfhotel.org
- **Purpose**: Full application access for internal staff
- **Path**: `/fingerprintlogs`
- **Access**: All features including admin dashboard
- **Cloudflare Tunnel**: `emp.thehfhotel.org → 192.168.100.228:80`

### Public Domain: erp.thehfhotel.org
- **Purpose**: Public QR check-in access only
- **Path**: `/qr-checkin` (rewrites to `/fingerprintlogs/qr-checkin`)
- **Access**: QR check-in and LINE authentication only
- **Security**: Admin endpoints blocked, internal pages hidden
- **Cloudflare Tunnel**: `erp.thehfhotel.org → 192.168.100.228:80`

## Nginx Configuration

### Location: `/home/nut/nginx`

```
nginx/
├── docker-compose.yml          # Nginx container definition
├── nginx.conf                  # Main nginx configuration
├── sites-available/
│   ├── fingerprint-time-logger # Internal domain config
│   └── erp-thehfhotel-org      # Public domain config
├── sites-enabled/              # Active configurations (symlinks or copies)
├── ssl/                        # SSL certificates
└── logs/                       # Access and error logs
```

### Docker Compose Setup

```yaml
services:
  nginx:
    image: nginx:alpine
    container_name: shared-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./sites-enabled:/etc/nginx/sites-enabled:ro
      - ./ssl:/etc/nginx/ssl:ro
      - ./logs:/var/log/nginx
    restart: unless-stopped
    networks:
      - shared-nginx-network

networks:
  shared-nginx-network:
    driver: bridge
    name: shared-nginx
```

### Public Domain Config (erp.thehfhotel.org)

**File**: `sites-enabled/erp-thehfhotel-org`

```nginx
server {
    listen 80;
    server_name erp.thehfhotel.org;

    # Security headers
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # QR Check-in root - Redirect to link account page
    location = /qr-checkin/ {
        return 301 https://$host/qr-checkin/link-account;
    }

    # QR Check-in paths - Rewrite and proxy
    location /qr-checkin/ {
        # Rewrite: /qr-checkin/* → /fingerprintlogs/qr-checkin/*
        rewrite ^/qr-checkin/(.*)$ /fingerprintlogs/qr-checkin/$1 break;

        proxy_pass http://fingerprint-time-logger:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Direct fingerprintlogs access (for LINE OAuth callback)
    location /fingerprintlogs/qr-checkin/ {
        proxy_pass http://fingerprint-time-logger:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # LINE OAuth callback
    location /fingerprintlogs/api/auth/line/ {
        proxy_pass http://fingerprint-time-logger:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static files for QR pages
    location /fingerprintlogs/static/ {
        proxy_pass http://fingerprint-time-logger:5000;
        proxy_set_header Host $host;
        expires 1h;
        add_header Cache-Control "public, immutable";
    }

    # SECURITY: Block admin endpoints
    location ~ ^/fingerprintlogs/api/admin/ {
        return 404;
    }

    # SECURITY: Block dashboard and device management
    location ~ ^/fingerprintlogs/(device-status|status|docs|redoc)$ {
        return 404;
    }

    # General fingerprintlogs access (after specific blocks)
    location /fingerprintlogs/ {
        proxy_pass http://fingerprint-time-logger:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Block everything else
    location / {
        return 404;
    }
}
```

## Cloudflare Tunnel Configuration

### Setup

1. **Access Cloudflare Zero Trust Dashboard**:
   - URL: https://one.dash.cloudflare.com/
   - Navigate to: **Networks** → **Tunnels**

2. **Configure Public Hostnames**:

   **Internal Access**:
   - Public hostname: `emp.thehfhotel.org`
   - Service: `http://192.168.100.228:80`
   - Path: (none - full access)

   **Public QR Check-in**:
   - Public hostname: `erp.thehfhotel.org`
   - Service: `http://192.168.100.228:80`
   - Path: (none - nginx handles path routing)

### Traffic Flow

**Public QR Check-in**:
```
https://erp.thehfhotel.org/qr-checkin/
    → Cloudflare Tunnel
    → nginx:80 (301 redirect)
    → /qr-checkin/link-account
    → nginx rewrite: /fingerprintlogs/qr-checkin/link-account
    → Docker app:5000
    → LINE Account Linking Page
```

**Internal Dashboard**:
```
https://emp.thehfhotel.org/fingerprintlogs/
    → Cloudflare Tunnel
    → nginx:80
    → Docker app:5000
    → Dashboard
```

## Docker Network Integration

### Connecting Application to Nginx

The application container must be on the same Docker network as nginx for hostname resolution.

**Option 1: Connect existing container**:
```bash
docker network connect shared-nginx fingerprint-time-logger
```

**Option 2: Add to docker-compose.yml**:
```yaml
services:
  app:
    # ... existing config ...
    networks:
      - default
      - shared-nginx

networks:
  shared-nginx:
    external: true
    name: shared-nginx
```

## Deployment Steps

### Initial Setup

1. **Create nginx directory structure**:
   ```bash
   mkdir -p ~/nginx/{sites-available,sites-enabled,ssl,logs}
   ```

2. **Copy configuration files**:
   ```bash
   cp nginx/docker-compose.yml ~/nginx/
   cp nginx/nginx.conf ~/nginx/
   cp nginx/sites-available/* ~/nginx/sites-available/
   ```

3. **Enable site configurations**:
   ```bash
   cd ~/nginx/sites-enabled
   cp ../sites-available/fingerprint-time-logger .
   cp ../sites-available/erp-thehfhotel-org .
   ```

4. **Start nginx**:
   ```bash
   cd ~/nginx
   docker compose up -d
   ```

5. **Connect application network**:
   ```bash
   docker network connect shared-nginx fingerprint-time-logger
   ```

6. **Test configuration**:
   ```bash
   docker exec shared-nginx nginx -t
   curl -I http://localhost:80/fingerprintlogs/
   ```

### Configuration Updates

1. **Edit configuration**:
   ```bash
   nano ~/nginx/sites-enabled/erp-thehfhotel-org
   ```

2. **Test changes**:
   ```bash
   docker exec shared-nginx nginx -t
   ```

3. **Apply changes**:
   ```bash
   cd ~/nginx
   docker compose restart nginx
   ```

### Troubleshooting

**Issue**: Nginx can't resolve `fingerprint-time-logger` hostname

**Solution**: Ensure containers are on the same network:
```bash
docker network ls
docker inspect fingerprint-time-logger | grep NetworkMode
docker inspect shared-nginx | grep NetworkMode
docker network connect shared-nginx fingerprint-time-logger
```

**Issue**: 404 errors on specific paths

**Solution**: Check nginx logs:
```bash
docker logs shared-nginx --tail 50
tail -f ~/nginx/logs/erp-error.log
```

**Issue**: Changes not taking effect

**Solution**: Verify config file is in container:
```bash
docker exec shared-nginx cat /etc/nginx/sites-enabled/erp-thehfhotel-org
docker compose restart nginx
```

## Security Considerations

### Public Domain (erp.thehfhotel.org)

**Blocked Endpoints**:
- `/fingerprintlogs/api/admin/*` - Admin operations
- `/fingerprintlogs/status` - System status
- `/fingerprintlogs/device-status` - Device management
- `/fingerprintlogs/docs` - API documentation
- All other paths return 404

**Allowed Endpoints**:
- `/qr-checkin/*` - QR check-in pages
- `/fingerprintlogs/qr-checkin/*` - Direct QR access
- `/fingerprintlogs/api/auth/line/*` - LINE authentication
- `/fingerprintlogs/static/*` - Static assets

### Testing Security

```bash
# Should work (200)
curl -I https://erp.thehfhotel.org/qr-checkin/link-account

# Should be blocked (404)
curl -I https://erp.thehfhotel.org/fingerprintlogs/api/admin/employees
curl -I https://erp.thehfhotel.org/fingerprintlogs/status

# Should work (200)
curl -I https://erp.thehfhotel.org/fingerprintlogs/static/css/link-line.css
```

## Monitoring

### Access Logs
```bash
tail -f ~/nginx/logs/erp-access.log
```

### Error Logs
```bash
tail -f ~/nginx/logs/erp-error.log
```

### Nginx Status
```bash
docker ps | grep nginx
docker logs shared-nginx --tail 50
```

### Test Endpoints
```bash
# Public QR check-in
curl -I https://erp.thehfhotel.org/qr-checkin/

# Internal dashboard
curl -I https://emp.thehfhotel.org/fingerprintlogs/
```

## Maintenance

### Restart Nginx
```bash
cd ~/nginx
docker compose restart nginx
```

### Reload Configuration (without downtime)
```bash
docker exec shared-nginx nginx -s reload
```

### View Logs
```bash
docker logs shared-nginx --tail 100 --follow
```

### Backup Configuration
```bash
tar -czf nginx-backup-$(date +%Y%m%d).tar.gz ~/nginx/
```

## References

- Nginx Documentation: https://nginx.org/en/docs/
- Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
- Docker Networking: https://docs.docker.com/network/
