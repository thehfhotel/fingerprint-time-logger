#!/bin/bash

echo "=== Stopping Dashboard ==="

# Find dashboard processes
DASHBOARD_PIDS=$(ps aux | grep dashboard_app.py | grep -v grep | awk '{print $2}')

if [ ! -z "$DASHBOARD_PIDS" ]; then
    echo "Found dashboard processes: $DASHBOARD_PIDS"
    
    # Try graceful shutdown first
    echo "Attempting graceful shutdown..."
    echo "$DASHBOARD_PIDS" | xargs kill
    
    # Wait a moment
    sleep 3
    
    # Check if still running
    REMAINING_PIDS=$(ps aux | grep dashboard_app.py | grep -v grep | awk '{print $2}')
    
    if [ ! -z "$REMAINING_PIDS" ]; then
        echo "Force stopping remaining processes: $REMAINING_PIDS"
        echo "$REMAINING_PIDS" | xargs kill -9
        sleep 1
    fi
    
    # Final check
    FINAL_CHECK=$(ps aux | grep dashboard_app.py | grep -v grep | awk '{print $2}')
    
    if [ -z "$FINAL_CHECK" ]; then
        echo "✅ Dashboard stopped successfully"
    else
        echo "❌ Some processes may still be running: $FINAL_CHECK"
    fi
    
else
    echo "ℹ️  No dashboard processes found running"
fi

echo ""
echo "🔄 To start dashboard: ./restart_dashboard.sh"
echo "📊 To check status: ./check_status.sh"

echo ""
echo "=== Stop Complete ==="