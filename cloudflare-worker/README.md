# Cloudflare Worker: QR Check-in Proxy

Infrastructure-as-Code deployment of Cloudflare Worker for QR check-in URL rewriting.

## Purpose

Rewrites public QR check-in URLs to internal application structure:

- **External**: `erp.thehfhotel.org/qr-checkin/mobile`
- **Internal**: `http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile`

## Architecture

```
User Request
    ↓
Cloudflare Edge (Worker executes)
    ↓ Rewrites: /qr-checkin/* → /fingerprintlogs/qr-checkin/*
Backend Server (192.168.100.228:5001)
    ↓
Public QR Service (Docker container)
```

## Prerequisites

1. **Cloudflare Account** with domain `thehfhotel.org`
2. **Cloudflare API Token** with Workers permissions
3. **Node.js** 18+ and npm installed

## Setup

### Step 1: Install Wrangler CLI

```bash
cd cloudflare-worker
npm install
```

### Step 2: Authenticate with Cloudflare

```bash
npx wrangler login
```

This opens a browser for OAuth authentication.

**Alternative: Use API Token**

Create `.dev.vars` file:
```bash
CLOUDFLARE_API_TOKEN=your_api_token_here
```

Get API token from: https://dash.cloudflare.com/profile/api-tokens

Required permissions:
- Account Settings: Read
- Workers Scripts: Edit
- Zone: Read

### Step 3: Configure Zone ID

Update `wrangler.toml` with your zone ID:

```toml
# Find your zone ID at: Cloudflare Dashboard → Domain → Overview (right sidebar)
routes = [
    { pattern = "erp.thehfhotel.org/qr-checkin/*", zone_id = "YOUR_ZONE_ID_HERE" }
]
```

Or use zone_name (Wrangler will auto-fetch zone ID):
```toml
routes = [
    { pattern = "erp.thehfhotel.org/qr-checkin/*", zone_name = "thehfhotel.org" }
]
```

## Development

### Local Development

```bash
npm run dev
```

This starts a local development server at `http://localhost:8787`

Test locally:
```bash
curl http://localhost:8787/qr-checkin/mobile
```

### Test Against Staging

Update `wrangler.toml` for development environment:
```bash
npm run deploy:dev
```

## Deployment

### Deploy to Production

```bash
npm run deploy:prod
```

**Output:**
```
✔ Deployed qr-checkin-proxy
  https://qr-checkin-proxy.your-subdomain.workers.dev
  Route: erp.thehfhotel.org/qr-checkin/*
```

### Verify Deployment

```bash
# Check worker status
npx wrangler deployments list

# View live logs
npm run tail
```

### Test Production

```bash
curl -v https://erp.thehfhotel.org/qr-checkin/mobile
```

Expected:
- Status: 200 OK
- Response: QR mobile check-in page HTML

## Configuration

### Environment Variables

Defined in `wrangler.toml`:

```toml
[vars]
BACKEND_HOST = "192.168.100.228"
BACKEND_PORT = "5001"
PATH_PREFIX = "/fingerprintlogs"
```

### Update Backend Configuration

To change backend server:

```toml
[env.production.vars]
BACKEND_HOST = "new-server-ip"
BACKEND_PORT = "5001"
```

Then redeploy:
```bash
npm run deploy:prod
```

## Monitoring

### View Real-Time Logs

```bash
npm run tail
```

### Cloudflare Dashboard

1. Go to: https://dash.cloudflare.com
2. Select your account → Workers & Pages
3. Click on `qr-checkin-proxy`
4. View metrics, logs, and settings

### Analytics

Cloudflare provides:
- Request count
- Error rate
- CPU time
- Response times

Free tier: Last 24 hours
Paid tier: Extended analytics

## Troubleshooting

### Worker Not Receiving Requests

**Check DNS:**
```bash
dig erp.thehfhotel.org
```

Should resolve to Cloudflare IPs (not your server IP directly).

**Verify Route:**
```bash
npx wrangler routes list
```

Should show: `erp.thehfhotel.org/qr-checkin/*`

### Backend Connection Failed (502)

**Test backend directly:**
```bash
curl http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile
```

**Check firewall:**
- Ensure port 5001 accessible from Cloudflare IPs
- Cloudflare IP ranges: https://www.cloudflare.com/ips/

**Check container:**
```bash
docker ps | grep fingerprint-logger-public
docker logs fingerprint-logger-public
```

### Path Rewriting Not Working

**Check worker logs:**
```bash
npm run tail
```

**Verify rewrite logic:**

Worker should log:
```
Incoming: /qr-checkin/mobile
Rewritten: /fingerprintlogs/qr-checkin/mobile
Backend: http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile
```

## CI/CD Integration

### GitHub Actions

Create `.github/workflows/deploy-worker.yml`:

```yaml
name: Deploy Cloudflare Worker

on:
  push:
    branches:
      - main
    paths:
      - 'cloudflare-worker/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'

      - name: Install dependencies
        working-directory: cloudflare-worker
        run: npm ci

      - name: Deploy to Cloudflare
        working-directory: cloudflare-worker
        run: npm run deploy:prod
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
```

Add secret:
1. GitHub repo → Settings → Secrets → New secret
2. Name: `CLOUDFLARE_API_TOKEN`
3. Value: Your Cloudflare API token

### Manual Deployment Script

Create `deploy.sh`:

```bash
#!/bin/bash
set -e

echo "🚀 Deploying Cloudflare Worker..."

cd cloudflare-worker

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

# Deploy to production
echo "☁️ Deploying to Cloudflare..."
npm run deploy:prod

echo "✅ Deployment complete!"
echo "🔗 Test: https://erp.thehfhotel.org/qr-checkin/mobile"
```

Make executable:
```bash
chmod +x cloudflare-worker/deploy.sh
```

Run:
```bash
./cloudflare-worker/deploy.sh
```

## Rollback

### Rollback to Previous Version

```bash
# List deployments
npx wrangler deployments list

# Rollback to specific deployment
npx wrangler rollback [deployment-id]
```

### Delete Worker

```bash
npx wrangler delete qr-checkin-proxy
```

### Remove Route

```bash
npx wrangler route delete [route-id]
```

## Cost

**Cloudflare Workers Free Tier:**
- 100,000 requests/day
- 10ms CPU time per request
- Unlimited scripts

**Typical QR Check-in Usage:**
- ~1,000 requests/day
- <1ms CPU time per request
- **Cost: $0/month**

**If exceeding free tier:**
- Workers Paid: $5/month for 10M requests

## Security

**Security Headers Added:**
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`

**Cloudflare DDoS Protection:**
- Automatic DDoS mitigation
- Rate limiting available (separate configuration)

## Next Steps

1. Deploy worker: `npm run deploy:prod`
2. Configure DNS: Point `erp.thehfhotel.org` to Cloudflare
3. Test public access: `curl https://erp.thehfhotel.org/qr-checkin/mobile`
4. Monitor logs: `npm run tail`
5. Update LINE OAuth callback URL

## Resources

- [Wrangler Documentation](https://developers.cloudflare.com/workers/wrangler/)
- [Workers Runtime API](https://developers.cloudflare.com/workers/runtime-apis/)
- [Cloudflare Dashboard](https://dash.cloudflare.com)
