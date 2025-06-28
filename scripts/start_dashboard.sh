#!/bin/bash

echo "=== Starting Employee Time Log Dashboard ==="
echo "Checking dependencies..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies if needed
pip install flask==3.0.0 flask-socketio==5.3.6 pyzk==0.9 > /dev/null 2>&1

echo "Starting dashboard server..."
echo "Dashboard will be available at: http://localhost:5000"
echo "Press Ctrl+C to stop the server"
echo ""

# Start the dashboard
python dashboard_app.py