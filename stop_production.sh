#!/bin/bash
# Stop production servers script

echo "=== Stopping Fingerprint Time Logger Production Servers ==="

# Read PID files if they exist
if [ -f "logs/api.pid" ]; then
    API_PID=$(cat logs/api.pid)
    echo "🛑 Stopping API Server (PID: $API_PID)..."
    kill $API_PID 2>/dev/null || echo "   API server was not running"
    rm -f logs/api.pid
fi

if [ -f "logs/dashboard.pid" ]; then
    DASHBOARD_PID=$(cat logs/dashboard.pid)
    echo "🛑 Stopping Dashboard Server (PID: $DASHBOARD_PID)..."
    kill $DASHBOARD_PID 2>/dev/null || echo "   Dashboard server was not running"
    rm -f logs/dashboard.pid
fi

# Kill any remaining processes
echo "🧹 Cleaning up any remaining processes..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "gunicorn.*dashboard_app:app" 2>/dev/null || true

echo "✅ All servers stopped successfully!"