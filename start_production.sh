#!/bin/bash
# Production startup script for Fingerprint Time Logger
# Replaces Werkzeug development server with Gunicorn

set -e  # Exit on any error

echo "=== Fingerprint Time Logger - Production Startup ==="
echo "Date: $(date)"
echo "Working Directory: $(pwd)"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Error: Virtual environment not found. Please create it first:"
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Set Python path
export PYTHONPATH=/home/nut/fingerprint-time-logger

# Check if Gunicorn is installed
if ! python -c "import gunicorn" 2>/dev/null; then
    echo "❌ Error: Gunicorn not installed. Installing production dependencies..."
    pip install gunicorn eventlet
fi

# Create logs directory
mkdir -p logs

echo "🚀 Starting production servers..."

# Start FastAPI backend
echo "📡 Starting FastAPI backend on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 > logs/api.log 2>&1 &
API_PID=$!
echo "   API Server PID: $API_PID"

# Wait a moment for API to start
sleep 2

# Start dashboard with Gunicorn (NOT Werkzeug)
echo "📊 Starting Dashboard with Gunicorn on port 5000..."
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 dashboard_app:app > logs/dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo "   Dashboard PID: $DASHBOARD_PID"

# Create PID file for monitoring
echo $API_PID > logs/api.pid
echo $DASHBOARD_PID > logs/dashboard.pid

echo ""
echo "✅ Production servers started successfully!"
echo ""
echo "🌐 Access Points:"
echo "   Dashboard: http://localhost:5000"
echo "   API: http://localhost:8000"
echo "   API Docs: http://localhost:8000/docs"
echo ""
echo "📋 Process Information:"
echo "   API PID: $API_PID (logs/api.log)"
echo "   Dashboard PID: $DASHBOARD_PID (logs/dashboard.log)"
echo ""
echo "⚠️  IMPORTANT: Using Gunicorn (production server), NOT Werkzeug"
echo ""
echo "📖 To stop servers:"
echo "   kill $API_PID $DASHBOARD_PID"
echo "   or run: ./stop_production.sh"
echo ""

# Wait for both processes (keeps script running)
wait