#!/bin/bash
# Updated stop script for unified FastAPI server architecture
# Simplified from dual-server to single unified server

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration for unified server
SERVICE="unified_server"
SERVICE_TO_STOP="${1:-}"  # Optional: specify service or empty for default

# Stop the unified service
stop_service() {
    local service=$1
    local pid_file="$PID_DIR/${service}.pid"
    
    if ! is_process_running "$service"; then
        log_warn "$service is not running"
        rm -f "$pid_file"
        return 0
    fi
    
    local pid=$(cat "$pid_file")
    log_info "Stopping $service (PID: $pid)..."
    
    # Kill process gracefully
    if kill_process_graceful "$pid" 10; then
        log_success "$service stopped successfully"
        rm -f "$pid_file"
        return 0
    else
        log_error "Failed to stop $service gracefully"
        return 1
    fi
}

# Cleanup processes by pattern (fallback)
cleanup_by_pattern() {
    local pattern=$1
    local service_name=$2
    
    log_info "Cleaning up any remaining $service_name processes..."
    
    local pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    
    if [ -z "$pids" ]; then
        log_success "No remaining $service_name processes found"
        return 0
    fi
    
    log_warn "Found remaining $service_name processes: $pids"
    
    for pid in $pids; do
        if kill -0 "$pid" 2>/dev/null; then
            log_info "Force stopping process $pid"
            kill_process_graceful "$pid" 3
        fi
    done
}

# Final cleanup
final_cleanup() {
    log_info "Performing final cleanup..."
    
    # Clean up stale PID files
    cleanup_stale_pids
    
    # Remove temporary files
    rm -f "$PID_DIR"/*.port 2>/dev/null || true
    
    # Clean Python cache
    find "$PROJECT_ROOT" -name "*.pyc" -delete 2>/dev/null || true
    find "$PROJECT_ROOT" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    
    log_success "Cleanup completed"
}

# Verify service is stopped
verify_stop() {
    local service=$1
    local pattern=$2
    
    # Check PID file
    if is_process_running "$service"; then
        return 1
    fi
    
    # Check by pattern
    local remaining=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$remaining" ]; then
        return 1
    fi
    
    return 0
}

# Main execution
main() {
    echo "🛑 Fingerprint Time Logger - Stopping Unified Server"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    
    ensure_directories
    
    case "$SERVICE_TO_STOP" in
        "")
            log_info "Stopping unified server..."
            
            local server_stopped=false
            
            # Stop unified server
            if stop_service "$SERVICE"; then
                server_stopped=true
            fi
            
            # Cleanup remaining processes
            cleanup_by_pattern "uvicorn.*app.main_unified" "Unified Server"
            
            # Verify service stopped
            if verify_stop "$SERVICE" "uvicorn.*app.main_unified"; then
                if [ "$server_stopped" = true ]; then
                    log_success "Unified server stopped successfully"
                else
                    log_success "No running server found, system is clean"
                fi
            else
                log_warn "Some server processes may still be running"
            fi
            ;;
            
        *)
            log_error "Unknown service: $SERVICE_TO_STOP"
            log_info "Usage: $0 [no arguments to stop unified server]"
            exit 1
            ;;
    esac
    
    # Final cleanup
    final_cleanup
    
    echo ""
    echo "📋 Management Commands:"
    echo "   Start:   ./scripts/start.sh"
    echo "   Status:  ./scripts/status.sh"
    echo "   Restart: ./scripts/restart.sh"
    echo ""
}

# Execute main function
main "$@"