#!/bin/bash
# Simplified stop script for unified FastAPI server

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$PROJECT_ROOT/pids/unified_server.pid"

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

# Stop server gracefully
stop_server() {
    local pid=$1
    
    log_info "Stopping server (PID: $pid)..."
    
    # Try graceful shutdown first
    if kill -TERM "$pid" 2>/dev/null; then
        # Wait up to 10 seconds for graceful shutdown
        local attempts=0
        while [ $attempts -lt 10 ]; do
            if ! kill -0 "$pid" 2>/dev/null; then
                log_success "Server stopped gracefully"
                return 0
            fi
            sleep 1
            attempts=$((attempts + 1))
        done
        
        # Force kill if still running
        log_warn "Graceful shutdown timeout, forcing stop..."
        if kill -KILL "$pid" 2>/dev/null; then
            sleep 2
            if ! kill -0 "$pid" 2>/dev/null; then
                log_success "Server stopped forcefully"
                return 0
            fi
        fi
    fi
    
    log_error "Failed to stop server"
    return 1
}

# Main function
main() {
    echo "🛑 Fingerprint Time Logger - Stop Server"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Check if PID file exists
    if [ ! -f "$PID_FILE" ]; then
        log_warn "No PID file found - server may not be running"
        
        # Check for any running uvicorn processes
        local running_pids=$(pgrep -f "uvicorn.*app.main_unified" 2>/dev/null || true)
        if [ -n "$running_pids" ]; then
            log_info "Found running server processes: $running_pids"
            for pid in $running_pids; do
                if stop_server "$pid"; then
                    log_success "Stopped orphaned process $pid"
                fi
            done
        else
            log_info "No running server processes found"
        fi
        return 0
    fi
    
    # Read PID
    local pid=$(cat "$PID_FILE")
    
    # Check if process is actually running
    if ! kill -0 "$pid" 2>/dev/null; then
        log_warn "Process $pid is not running (stale PID file)"
        rm -f "$PID_FILE"
        return 0
    fi
    
    # Stop the server
    if stop_server "$pid"; then
        rm -f "$PID_FILE"
        
        # Clean up any remaining processes
        local remaining=$(pgrep -f "uvicorn.*app.main_unified" 2>/dev/null || true)
        if [ -n "$remaining" ]; then
            log_warn "Cleaning up remaining processes: $remaining"
            for remaining_pid in $remaining; do
                kill -KILL "$remaining_pid" 2>/dev/null || true
            done
        fi
        
        log_success "All processes stopped successfully"
    else
        log_error "Failed to stop server"
        exit 1
    fi
    
    echo ""
    echo "📋 Commands:"
    echo "   Start: ./scripts/start_simple.sh"
    echo ""
}

main "$@"