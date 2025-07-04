#!/bin/bash
# Simplified start script for unified FastAPI server
# Single process deployment for fingerprint time logger

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/venv"
LOG_FILE="$PROJECT_ROOT/logs/unified_server.log"
PID_FILE="$PROJECT_ROOT/pids/unified_server.pid"
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

# Check if server is already running
check_running() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            log_warn "Server is already running (PID: $pid)"
            log_info "Access at: http://localhost:$PORT"
            log_info "Use './scripts/stop_simple.sh' to stop"
            return 0
        else
            rm -f "$PID_FILE"
        fi
    fi
    return 1
}

# Ensure directories exist
ensure_directories() {
    mkdir -p "$(dirname "$PID_FILE")"
    mkdir -p "$(dirname "$LOG_FILE")"
}

# Check virtual environment
check_venv() {
    if [ ! -f "$VENV_PATH/bin/python" ]; then
        log_error "Virtual environment not found at $VENV_PATH"
        log_info "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        return 1
    fi
    return 0
}

# Main function
main() {
    echo "🚀 Fingerprint Time Logger - Unified Server"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Check if already running
    if check_running; then
        exit 0
    fi
    
    # Setup
    ensure_directories
    
    # Check virtual environment
    if ! check_venv; then
        exit 1
    fi
    
    # Check if port is available
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        log_error "Port $PORT is already in use"
        log_info "Stop any existing server first or use a different port"
        exit 1
    fi
    
    # Start server
    log_info "Starting unified FastAPI server..."
    log_info "Project: $PROJECT_ROOT"
    log_info "Port: $PORT"
    log_info "Log: $LOG_FILE"
    
    cd "$PROJECT_ROOT"
    nohup "$VENV_PATH/bin/uvicorn" app.main_unified:app \
        --host 0.0.0.0 \
        --port $PORT \
        --reload \
        > "$LOG_FILE" 2>&1 &
    
    local pid=$!
    echo "$pid" > "$PID_FILE"
    
    # Wait for server to start
    log_info "Waiting for server to start (PID: $pid)..."
    sleep 3
    
    # Check if process is still running
    if ! kill -0 "$pid" 2>/dev/null; then
        log_error "Server failed to start"
        log_info "Check log file: $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
    
    # Check if server is responding
    local attempts=0
    while [ $attempts -lt 15 ]; do
        if curl -s -o /dev/null "http://localhost:$PORT/api/devices/health" 2>/dev/null; then
            break
        fi
        sleep 2
        attempts=$((attempts + 1))
    done
    
    if [ $attempts -eq 15 ]; then
        log_warn "Server started but health check failed"
        log_info "Server may still be initializing..."
    fi
    
    log_success "Server started successfully!"
    echo ""
    echo "🌐 Access URLs:"
    echo "   📊 Dashboard: http://localhost:$PORT"
    echo "   🔌 API Health: http://localhost:$PORT/api/devices/health"
    echo "   📖 API Docs: http://localhost:$PORT/docs"
    echo ""
    echo "📋 Commands:"
    echo "   Stop: ./scripts/stop_simple.sh"
    echo "   Logs: tail -f $LOG_FILE"
    echo ""
}

main "$@"