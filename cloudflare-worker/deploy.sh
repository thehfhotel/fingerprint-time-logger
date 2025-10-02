#!/bin/bash
# Cloudflare Worker Deployment Script
# Automates deployment of QR Check-in proxy worker

set -e  # Exit on error

echo "🚀 Cloudflare Worker Deployment"
echo "================================"
echo ""

# Change to worker directory
cd "$(dirname "$0")"

# Check if wrangler is installed
if ! command -v npx &> /dev/null; then
    echo "❌ Error: npx not found. Please install Node.js 18+"
    exit 1
fi

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
    echo "✅ Dependencies installed"
    echo ""
fi

# Prompt for environment
echo "Select deployment environment:"
echo "  1) Development (qr-checkin-proxy-dev)"
echo "  2) Production (qr-checkin-proxy)"
echo ""
read -p "Enter choice [1-2]: " env_choice

case $env_choice in
    1)
        ENV="development"
        echo "📍 Deploying to DEVELOPMENT environment..."
        ;;
    2)
        ENV="production"
        echo "📍 Deploying to PRODUCTION environment..."
        ;;
    *)
        echo "❌ Invalid choice. Exiting."
        exit 1
        ;;
esac

echo ""

# Deploy
echo "☁️ Deploying to Cloudflare Workers..."
if [ "$ENV" = "development" ]; then
    npm run deploy:dev
else
    npm run deploy:prod
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "🔗 Test URLs:"
if [ "$ENV" = "development" ]; then
    echo "   Development: https://qr-checkin-proxy-dev.your-subdomain.workers.dev"
else
    echo "   Production: https://erp.thehfhotel.org/qr-checkin/mobile"
fi
echo ""
echo "📊 View logs:"
echo "   npm run tail"
echo ""
echo "🌐 Dashboard:"
echo "   https://dash.cloudflare.com"
