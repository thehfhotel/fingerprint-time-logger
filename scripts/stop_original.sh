#!/bin/bash
# Self-correcting stop script for Fingerprint Time Logger
# Gracefully shuts down services with forced cleanup

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration
API_SERVICE="api"
DASHBOARD_SERVICE="dashboard"
SERVICE_TO_STOP="${1:-}"  # Optional: "api", "dashboard", or empty for both

# Stop a specific service
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
    
    # Special handling for dashboard background threads
    if [ "$service" = "$DASHBOARD_SERVICE" ]; then
        stop_dashboard_threads "$pid"
    fi
    
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

# Stop dashboard background threads
stop_dashboard_threads() {
    local main_pid=$1
    log_info "Stopping dashboard background threads..."
    
    # Find all child processes
    local child_pids=$(pgrep -P "$main_pid" 2>/dev/null || true)
    
    # Stop child processes first
    if [ -n "$child_pids" ]; then
        for child_pid in $child_pids; do
            log_info "Stopping child process: $child_pid"
            kill_process_graceful "$child_pid" 5
        done
    fi
    
    # Give main process time to clean up
    sleep 2
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

# Verify services are stopped
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
    echo "🛑 Fingerprint Time Logger - Stopping Application"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    
    ensure_directories
    
    case "$SERVICE_TO_STOP" in
        "api")
            log_info "Stopping API server only..."
            
            if stop_service "$API_SERVICE"; then
                cleanup_by_pattern "uvicorn.*app.main:app" "API Server"
                
                if verify_stop "$API_SERVICE" "uvicorn.*app.main:app"; then
                    log_success "API server stopped successfully"
                else
                    log_warn "Some API processes may still be running"
                fi
            fi
            ;;
            
        "dashboard")
            log_info "Stopping dashboard only..."
            
            if stop_service "$DASHBOARD_SERVICE"; then
                cleanup_by_pattern "python.*dashboard_app.py" "Dashboard"
                
                if verify_stop "$DASHBOARD_SERVICE" "python.*dashboard_app.py"; then
                    log_success "Dashboard stopped successfully"
                else
                    log_warn "Some dashboard processes may still be running"
                fi
            fi
            ;;
            
        *)
            log_info "Stopping all services..."
            
            local api_stopped=false
            local dashboard_stopped=false
            
            # Stop API service
            if stop_service "$API_SERVICE"; then
                api_stopped=true
            fi
            
            # Stop dashboard service
            if stop_service "$DASHBOARD_SERVICE"; then
                dashboard_stopped=true
            fi
            
            # Cleanup remaining processes
            cleanup_by_pattern "uvicorn.*app.main:app" "API Server"
            cleanup_by_pattern "python.*dashboard_app.py" "Dashboard"
            
            # Verify all services stopped
            local all_stopped=true
            
            if ! verify_stop "$API_SERVICE" "uvicorn.*app.main:app"; then
                log_error "API server may still be running"
                all_stopped=false
            fi
            
            if ! verify_stop "$DASHBOARD_SERVICE" "python.*dashboard_app.py"; then
                log_error "Dashboard may still be running"
                all_stopped=false
            fi
            
            if [ "$all_stopped" = true ]; then
                log_success "All services stopped successfully"
            else
                log_warn "Some services may still be running"
            fi
            ;;
    esac
    
    # Final cleanup
    final_cleanup
    
    echo ""
    echo "📋 Management Commands:"
    echo "   Start:   ./scripts/start.sh"
    echo "   Status:  ./scripts/status.sh"
    echo ""
}

# Execute main function
main "$@"