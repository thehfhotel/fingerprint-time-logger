#!/bin/bash
# Docker Compose restart script for Fingerprint Time Logger
# Updated to use containerized deployment

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration
SERVICE_NAME="fingerprint-time-logger"
RESTART_DELAY=3
PORT=5000

# Main execution
main() {
    echo "🔄 Fingerprint Time Logger - Restarting Docker Services"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    echo "🕐 Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    # Check if services are currently running
    local was_running=false
    if docker ps --filter "name=$SERVICE_NAME" --filter "status=running" | grep -q "$SERVICE_NAME"; then
        was_running=true
        log_info "Docker services are currently running"
    else
        log_info "Docker services are not currently running"
    fi
    
    # Stop the services
    log_info "Stopping Docker services..."
    if "$SCRIPT_DIR/stop.sh"; then
        if [ "$was_running" = true ]; then
            log_success "Services stopped successfully"
        else
            log_success "System cleanup completed"
        fi
    else
        log_error "Failed to stop services cleanly"
        echo "   Attempting to continue with restart..."
    fi
    
    # Wait for cleanup
    log_info "Waiting ${RESTART_DELAY} seconds for cleanup..."
    sleep $RESTART_DELAY
    
    # Verify services are stopped
    if docker ps --filter "name=$SERVICE_NAME" --filter "status=running" | grep -q "$SERVICE_NAME"; then
        log_warn "Services still running, attempting force cleanup..."
        
        # Force stop container
        log_info "Force stopping container: $SERVICE_NAME"
        docker stop "$SERVICE_NAME" >/dev/null 2>&1 || true
        docker rm "$SERVICE_NAME" >/dev/null 2>&1 || true
        
        sleep 2
    fi
    
    # Start the services
    log_info "Starting Docker services..."
    if "$SCRIPT_DIR/start.sh"; then
        log_success "Restart completed successfully!"
        echo ""
        echo "🌐 Server Access:"
        echo "   📊 Dashboard: http://localhost:$PORT"
        echo "   🔌 API Health: http://localhost:$PORT/api/devices/health"
        echo "   📖 API Docs: http://localhost:$PORT/docs"
        echo ""
        echo "📋 Management Commands:"
        echo "   Status: ./scripts/status.sh"
        echo "   Stop:   ./scripts/stop.sh"
        echo ""
        echo "🐳 Docker Commands:"
        echo "   Logs: docker logs $SERVICE_NAME"
        echo "   Shell: docker exec -it $SERVICE_NAME bash"
        echo ""
        exit 0
    else
        log_error "Failed to start services after restart"
        echo ""
        echo "🔧 Troubleshooting:"
        echo "   - Check logs: docker logs $SERVICE_NAME"
        echo "   - Manual start: ./scripts/start.sh"
        echo "   - Check status: ./scripts/status.sh"
        echo "   - View containers: docker ps -a"
        echo ""
        exit 1
    fi
}

# Execute main function
main "$@"