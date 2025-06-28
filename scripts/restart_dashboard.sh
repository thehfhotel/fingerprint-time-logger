#!/bin/bash

echo "=== Dashboard Restart Script ==="
echo "Stopping existing dashboard processes..."

# Kill any existing dashboard processes
pkill -f dashboard_app.py 2>/dev/null
pkill -f flask 2>/dev/null

# Wait for processes to terminate
sleep 3

echo "Cleaning up any lingering processes on port 5000..."
# Try to find and kill processes using port 5000
ps aux | grep -E "dashboard_app|flask|:5000" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null

# Wait a bit more
sleep 2

echo "Starting dashboard..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating..."
    python3 -m venv venv
    source venv/bin/activate
    pip install flask==3.0.0 flask-socketio==5.3.6 pyzk==0.9
else
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Start the dashboard in background
nohup python dashboard_app.py > dashboard.log 2>&1 &
DASHBOARD_PID=$!

echo "Dashboard started with PID: $DASHBOARD_PID"
echo "Waiting for startup..."
sleep 5

# Check if dashboard is running
if kill -0 $DASHBOARD_PID 2>/dev/null; then
    echo "✅ Dashboard is running successfully!"
    echo "📊 Dashboard URL: http://localhost:5000"
    echo "🌐 Network URL: http://$(hostname -I | awk '{print $1}'):5000"
    echo "📋 Check logs with: tail -f dashboard.log"
    echo "🔄 Stop dashboard with: pkill -f dashboard_app.py"
else
    echo "❌ Dashboard failed to start. Check dashboard.log for errors:"
    tail -10 dashboard.log
fi

echo ""
echo "=== Dashboard Restart Complete ==="