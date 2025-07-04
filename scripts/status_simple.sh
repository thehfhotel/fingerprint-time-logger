#!/bin/bash
# Simplified status script for unified FastAPI server

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$PROJECT_ROOT/pids/unified_server.pid"
LOG_FILE="$PROJECT_ROOT/logs/unified_server.log"
PORT=5000

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Check server status
check_status() {
    echo "🔍 Fingerprint Time Logger - Server Status"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Check PID file
    if [ ! -f "$PID_FILE" ]; then
        log_error "Server is not running (no PID file)"
        echo ""
        echo "📋 Commands:"
        echo "   Start: ./scripts/start_simple.sh"
        return 1
    fi
    
    local pid=$(cat "$PID_FILE")
    
    # Check if process is running
    if ! kill -0 "$pid" 2>/dev/null; then
        log_error "Server is not running (stale PID file)"
        rm -f "$PID_FILE"
        echo ""
        echo "📋 Commands:"
        echo "   Start: ./scripts/start_simple.sh"
        return 1
    fi
    
    log_success "Server is running (PID: $pid)"
    
    # Check if server is responding
    local health_status="❌ Not responding"
    if curl -s -o /dev/null "http://localhost:$PORT/api/devices/health" 2>/dev/null; then
        health_status="✅ Healthy"
    fi
    
    # Get uptime
    local start_time=""
    if command -v ps >/dev/null 2>&1; then
        start_time=$(ps -o lstart= -p "$pid" 2>/dev/null | tr -s ' ')
    fi
    
    # Get memory usage
    local memory_usage=""
    if command -v ps >/dev/null 2>&1; then
        memory_usage=$(ps -o rss= -p "$pid" 2>/dev/null | tr -d ' ')
        if [ -n "$memory_usage" ]; then
            memory_usage="$((memory_usage / 1024))MB"
        fi
    fi
    
    echo ""
    echo "📊 Server Details:"
    echo "   Process ID: $pid"
    echo "   Port: $PORT"
    echo "   Health: $health_status"
    if [ -n "$start_time" ]; then
        echo "   Started: $start_time"
    fi
    if [ -n "$memory_usage" ]; then
        echo "   Memory: $memory_usage"
    fi
    
    echo ""
    echo "🌐 Access URLs:"
    echo "   📊 Dashboard: http://localhost:$PORT"
    echo "   🔌 API Health: http://localhost:$PORT/api/devices/health"
    echo "   📖 API Docs: http://localhost:$PORT/docs"
    
    echo ""
    echo "📁 Files:"
    echo "   PID File: $PID_FILE"
    echo "   Log File: $LOG_FILE"
    
    echo ""
    echo "📋 Commands:"
    echo "   Stop: ./scripts/stop_simple.sh"
    echo "   Logs: tail -f $LOG_FILE"
    
    # Show recent log entries
    echo ""
    echo "📝 Recent Log Entries:"
    if [ -f "$LOG_FILE" ]; then
        tail -5 "$LOG_FILE" | sed 's/^/   /'
    else
        echo "   No log file found"
    fi
    
    return 0
}

# Main function
main() {
    check_status
}

main "$@"