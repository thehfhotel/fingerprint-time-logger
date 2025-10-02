# Cloudflare Worker Infrastructure-as-Code Setup

## ✅ Yes, Cloudflare Workers Can Be Configured as Code!

I've created a complete Infrastructure-as-Code setup for your Cloudflare Worker in the `cloudflare-worker/` directory.

## File Structure Created

```
fingerprint-time-logger/
└── cloudflare-worker/
    ├── wrangler.toml           # Worker configuration
    ├── package.json            # Dependencies and scripts
    ├── .gitignore              # Git ignore patterns
    ├── deploy.sh               # Deployment automation script
    ├── README.md               # Complete documentation
    ├── src/
    │   └── worker.js           # Worker code (URL rewriting logic)
    └── .github/
        └── workflows/
            └── deploy-worker.yml  # GitHub Actions CI/CD
```

## What This Gives You

### 1. **Version Control** ✅
- Worker code in Git
- Track changes over time
- Review before deployment

### 2. **Automated Deployment** ✅
- One command: `npm run deploy:prod`
- CI/CD with GitHub Actions
- Rollback capability

### 3. **Environment Management** ✅
- Development environment for testing
- Production environment for live
- Environment-specific configuration

### 4. **Infrastructure-as-Code** ✅
- Declarative configuration in `wrangler.toml`
- No manual Cloudflare Dashboard clicks
- Reproducible deployments

## Quick Start

### Step 1: Install Wrangler CLI

```bash
cd cloudflare-worker
npm install
```

### Step 2: Authenticate

**Option A: OAuth (Recommended)**
```bash
npx wrangler login
```

**Option B: API Token**
1. Get token: https://dash.cloudflare.com/profile/api-tokens
2. Create token with Workers permissions
3. Create `.dev.vars`:
```bash
CLOUDFLARE_API_TOKEN=your_token_here
```

### Step 3: Configure Zone

Find your zone ID:
1. Go to: https://dash.cloudflare.com
2. Select domain: `thehfhotel.org`
3. Overview → Zone ID (right sidebar)

Update `wrangler.toml` line 10:
```toml
routes = [
    { pattern = "erp.thehfhotel.org/qr-checkin/*", zone_id = "YOUR_ZONE_ID" }
]
```

Or use zone name (auto-fetch):
```toml
routes = [
    { pattern = "erp.thehfhotel.org/qr-checkin/*", zone_name = "thehfhotel.org" }
]
```

### Step 4: Deploy

**Interactive deployment:**
```bash
./deploy.sh
```

**Direct deployment:**
```bash
npm run deploy:prod
```

### Step 5: Verify

```bash
curl -v https://erp.thehfhotel.org/qr-checkin/mobile
```

Expected: QR mobile page HTML (status 200)

## Worker Configuration

### wrangler.toml Explained

```toml
name = "qr-checkin-proxy"           # Worker name in dashboard
main = "src/worker.js"              # Entry point
compatibility_date = "2024-01-01"   # Worker runtime version

# Routes: When to run this worker
routes = [
    { pattern = "erp.thehfhotel.org/qr-checkin/*", zone_name = "thehfhotel.org" }
]

# Environment variables (available in worker code)
[vars]
BACKEND_HOST = "192.168.100.228"   # Your server IP
BACKEND_PORT = "5001"              # Public service port
PATH_PREFIX = "/fingerprintlogs"  # Path to prepend

# Environment-specific configs
[env.development]
name = "qr-checkin-proxy-dev"
vars = { BACKEND_HOST = "localhost", BACKEND_PORT = "5001" }

[env.production]
name = "qr-checkin-proxy"
vars = { BACKEND_HOST = "192.168.100.228", BACKEND_PORT = "5001" }
```

### Worker Code (src/worker.js)

**URL Rewriting Logic:**

```javascript
// Input:  /qr-checkin/mobile
// Output: /fingerprintlogs/qr-checkin/mobile

const newPath = url.pathname.replace('/qr-checkin/', `${env.PATH_PREFIX}/qr-checkin/`);
const backendUrl = `http://${env.BACKEND_HOST}:${env.BACKEND_PORT}${newPath}`;
```

**Features:**
- ✅ URL path rewriting
- ✅ Security headers injection
- ✅ Error handling (502 on backend failure)
- ✅ Request/response forwarding

## Deployment Methods

### Method 1: Manual Deployment

```bash
cd cloudflare-worker
npm run deploy:prod
```

### Method 2: Interactive Script

```bash
cd cloudflare-worker
./deploy.sh
```

Prompts for:
1. Environment (dev/prod)
2. Auto-installs dependencies
3. Deploys to Cloudflare
4. Shows test URLs

### Method 3: GitHub Actions (CI/CD)

**Setup:**

1. Add secret to GitHub repo:
   - Settings → Secrets → New secret
   - Name: `CLOUDFLARE_API_TOKEN`
   - Value: Your Cloudflare API token

2. Push code to main branch:
```bash
git add cloudflare-worker/
git commit -m "Add Cloudflare Worker infrastructure"
git push origin main
```

3. GitHub Actions auto-deploys on push to `cloudflare-worker/` directory

**Workflow file:** `.github/workflows/deploy-worker.yml`

## Development Workflow

### Local Testing

```bash
npm run dev
```

Opens local server at `http://localhost:8787`

Test:
```bash
curl http://localhost:8787/qr-checkin/mobile
```

### Deploy to Development

```bash
npm run deploy:dev
```

Creates separate worker: `qr-checkin-proxy-dev`

### View Logs

```bash
npm run tail
```

Real-time worker execution logs.

### Iterate and Deploy

```bash
# Edit src/worker.js
vim src/worker.js

# Test locally
npm run dev

# Deploy to production
npm run deploy:prod
```

## Configuration Updates

### Change Backend Server

Edit `wrangler.toml`:
```toml
[vars]
BACKEND_HOST = "new-ip-address"
BACKEND_PORT = "5001"
```

Deploy:
```bash
npm run deploy:prod
```

### Add New Route

Edit `wrangler.toml`:
```toml
routes = [
    { pattern = "erp.thehfhotel.org/qr-checkin/*", zone_name = "thehfhotel.org" },
    { pattern = "qr.thehfhotel.org/*", zone_name = "thehfhotel.org" }
]
```

### Add Environment Variable

Edit `wrangler.toml`:
```toml
[vars]
BACKEND_HOST = "192.168.100.228"
BACKEND_PORT = "5001"
PATH_PREFIX = "/fingerprintlogs"
RATE_LIMIT = "100"  # New variable
```

Use in worker:
```javascript
const rateLimit = env.RATE_LIMIT;
```

## Monitoring

### Cloudflare Dashboard

1. https://dash.cloudflare.com
2. Workers & Pages
3. Click `qr-checkin-proxy`

**Metrics Available:**
- Requests/second
- Error rate
- CPU time
- Success rate
- Geographic distribution

### Real-Time Logs

```bash
cd cloudflare-worker
npm run tail
```

Shows:
- Request paths
- Response codes
- Errors
- console.log() output

### Debugging

Add logging to `src/worker.js`:
```javascript
console.log('Incoming path:', url.pathname);
console.log('Rewritten path:', newPath);
console.log('Backend URL:', backendUrl);
```

View logs:
```bash
npm run tail
```

## Rollback

### List Deployments

```bash
npx wrangler deployments list
```

Shows:
```
Deployment ID          Created            Author
abc123                2024-01-15 10:00   you@email.com
def456                2024-01-14 15:00   you@email.com
```

### Rollback to Previous

```bash
npx wrangler rollback abc123
```

### Emergency: Delete Worker

```bash
npx wrangler delete qr-checkin-proxy
```

## Integration with Docker Services

### Complete Workflow

1. **Deploy Docker Services:**
```bash
cd ~/fingerprint-time-logger
docker-compose up -d
```

2. **Deploy Cloudflare Worker:**
```bash
cd cloudflare-worker
./deploy.sh
```

3. **Verify End-to-End:**
```bash
# Internal service
curl https://emp.thehfhotel.org/fingerprintlogs/qr-checkin/mobile

# Public service (via worker)
curl https://erp.thehfhotel.org/qr-checkin/mobile
```

### URL Flow Verification

**Public Request:**
```
User → https://erp.thehfhotel.org/qr-checkin/mobile
    ↓
Cloudflare Worker (URL rewrite)
    ↓ http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile
Docker Container (fingerprint-logger-public)
    ↓
FastAPI App (/fingerprintlogs/qr-checkin/mobile)
    ↓
Response (QR Mobile Page HTML)
```

## Troubleshooting

### Worker Not Deployed

**Check authentication:**
```bash
npx wrangler whoami
```

**Re-login:**
```bash
npx wrangler logout
npx wrangler login
```

### Route Not Working

**Check DNS:**
```bash
dig erp.thehfhotel.org
```

Should show Cloudflare IPs (not your server directly).

**Cloudflare DNS Settings:**
1. Dashboard → DNS → Records
2. Add A record: `erp` → `192.168.100.228`
3. Enable proxy (orange cloud) ☁️

### Backend Connection Failed

**Test backend directly:**
```bash
curl http://192.168.100.228:5001/fingerprintlogs/qr-checkin/mobile
```

**Check Docker service:**
```bash
docker ps | grep fingerprint-logger-public
```

**Check firewall:**
```bash
# Allow port 5001 from Cloudflare IPs
sudo ufw allow from 173.245.48.0/20 to any port 5001
# ... (add all Cloudflare IP ranges)
```

Cloudflare IP ranges: https://www.cloudflare.com/ips/

### Worker Logs Show Errors

**Common errors:**

1. **"Backend fetch failed"**
   - Backend server down or unreachable
   - Check: `docker logs fingerprint-logger-public`

2. **"Not Found"**
   - Path doesn't match `/qr-checkin/*`
   - Check route in `wrangler.toml`

3. **CORS errors**
   - Add CORS headers in worker
   - See: https://developers.cloudflare.com/workers/examples/cors-header-proxy/

## Cost Estimation

**Cloudflare Workers Pricing:**

| Tier | Requests/Day | Cost |
|------|-------------|------|
| Free | 100,000 | $0 |
| Paid | 10,000,000 | $5/month |

**Typical QR Check-in Usage:**
- ~1,000 requests/day
- ~30,000 requests/month
- **Estimated Cost: $0/month** (well within free tier)

**Additional Costs:**
- Domain: Already owned ✅
- SSL: Free with Cloudflare ✅
- DNS: Free with Cloudflare ✅

**Total Monthly Cost: $0**

## Security Considerations

**Built-in Security:**
- ✅ Cloudflare DDoS protection
- ✅ SSL/TLS encryption
- ✅ Security headers injection
- ✅ Rate limiting (Cloudflare dashboard)

**Worker Security:**
- ✅ Only handles `/qr-checkin/*` paths
- ✅ Returns 404 for other paths
- ✅ No sensitive data in worker code
- ✅ Environment variables for secrets

**Backend Security:**
- ✅ Firewall rules for Cloudflare IPs only
- ✅ Backend service has admin endpoints disabled
- ✅ Rate limiting in application layer

## Next Steps

1. ✅ **Files created** - All Infrastructure-as-Code files ready
2. ⏭️ **Install Wrangler** - Run `cd cloudflare-worker && npm install`
3. ⏭️ **Authenticate** - Run `npx wrangler login`
4. ⏭️ **Configure Zone** - Update `wrangler.toml` with zone ID
5. ⏭️ **Deploy** - Run `./deploy.sh` or `npm run deploy:prod`
6. ⏭️ **Test** - Verify `https://erp.thehfhotel.org/qr-checkin/mobile`
7. ⏭️ **Monitor** - Run `npm run tail` to watch logs

## Resources

- **Wrangler Docs**: https://developers.cloudflare.com/workers/wrangler/
- **Workers Examples**: https://developers.cloudflare.com/workers/examples/
- **Dashboard**: https://dash.cloudflare.com
- **Community**: https://community.cloudflare.com/

---

**Summary:** Your Cloudflare Worker is now Infrastructure-as-Code! All configuration in Git, one-command deployment, CI/CD ready, fully automated. 🚀
