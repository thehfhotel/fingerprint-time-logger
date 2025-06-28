#!/bin/bash

echo "=== Dashboard Status Check ==="

# Check if dashboard process is running
DASHBOARD_PID=$(ps aux | grep dashboard_app.py | grep -v grep | awk '{print $2}')

if [ ! -z "$DASHBOARD_PID" ]; then
    echo "✅ Dashboard is running (PID: $DASHBOARD_PID)"
    
    # Check if port 5000 is responding
    if curl -s http://localhost:5000/api/attendance > /dev/null 2>&1; then
        echo "✅ Dashboard API is responding"
        
        # Get dashboard statistics
        echo ""
        echo "📊 Dashboard Statistics:"
        curl -s http://localhost:5000/api/attendance | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    device_status = data.get('device_status', {})
    time_sync = device_status.get('time_sync', {})
    
    print(f'  • Device connected: {\"✅\" if device_status.get(\"connected\") else \"❌\"} {device_status.get(\"connected\", False)}')
    print(f'  • Thai employees: {len(data[\"data\"])}')
    print(f'  • Total records: {sum(len(records) for records in data[\"data\"].values())}')
    print(f'  • Last update: {data.get(\"last_update\", \"Never\")}')
    print(f'  • Time sync: {\"✅\" if time_sync.get(\"success\") else \"❌\"} {time_sync.get(\"message\", \"No sync info\")}')
    
    if data['data']:
        print('')
        print('  Thai employees with attendance:')
        for i, (name, records) in enumerate(list(data['data'].items())[:5]):
            print(f'    {i+1}. {name} ({len(records)} records)')
        if len(data['data']) > 5:
            print(f'    ... and {len(data[\"data\"]) - 5} more employees')
            
except Exception as e:
    print(f'  Error parsing API response: {e}')
"
    else
        echo "❌ Dashboard API is not responding"
    fi
    
    echo ""
    echo "🌐 Access URLs:"
    echo "  • Local: http://localhost:5000"
    echo "  • Network: http://$(hostname -I | awk '{print $1}'):5000"
    
else
    echo "❌ Dashboard is not running"
    echo ""
    echo "🔄 To start dashboard, run: ./restart_dashboard.sh"
fi

echo ""
echo "📋 Recent logs (last 5 lines):"
tail -5 dashboard.log 2>/dev/null || echo "  No log file found"

echo ""
echo "=== Status Check Complete ==="