#!/bin/bash
# Restart script for unified FastAPI server architecture
# Safely stops and starts the unified server

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration
SERVICE="unified_server"
RESTART_DELAY=3

# Main execution
main() {
    echo "🔄 Fingerprint Time Logger - Restarting Unified Server"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    echo "🕐 Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    # Check if server is currently running
    local was_running=false
    if is_process_running "$SERVICE"; then
        was_running=true
        log_info "Unified server is currently running"
    else
        log_info "Unified server is not currently running"
    fi
    
    # Stop the server
    log_info "Stopping unified server..."
    if "$SCRIPT_DIR/stop.sh"; then
        if [ "$was_running" = true ]; then
            log_success "Server stopped successfully"
        else
            log_success "System cleanup completed"
        fi
    else
        log_error "Failed to stop server cleanly"
        echo "   Attempting to continue with restart..."
    fi
    
    # Wait for cleanup
    log_info "Waiting ${RESTART_DELAY} seconds for cleanup..."
    sleep $RESTART_DELAY
    
    # Verify server is stopped
    if is_process_running "$SERVICE"; then
        log_warn "Server still running, attempting force cleanup..."
        
        # Force cleanup any remaining processes
        local remaining_pids=$(pgrep -f "uvicorn.*app.main_unified" 2>/dev/null || true)
        if [ -n "$remaining_pids" ]; then
            log_info "Force stopping remaining processes: $remaining_pids"
            for pid in $remaining_pids; do
                kill -KILL "$pid" 2>/dev/null || true
            done
            sleep 2
        fi
    fi
    
    # Start the server
    log_info "Starting unified server..."
    if "$SCRIPT_DIR/start.sh"; then
        log_success "Restart completed successfully!"
        echo ""
        echo "🌐 Server Access:"
        echo "   📊 Dashboard: http://localhost:5000"
        echo "   🔌 API Health: http://localhost:5000/api/devices/health"
        echo "   📖 API Docs: http://localhost:5000/docs"
        echo ""
        echo "📋 Management Commands:"
        echo "   Status: ./scripts/status.sh"
        echo "   Stop:   ./scripts/stop.sh"
        echo ""
        exit 0
    else
        log_error "Failed to start server after restart"
        echo ""
        echo "🔧 Troubleshooting:"
        echo "   - Check logs: tail -f logs/unified_server.log"
        echo "   - Manual start: ./scripts/start.sh"
        echo "   - Check status: ./scripts/status.sh"
        echo ""
        exit 1
    fi
}

# Execute main function
main "$@"