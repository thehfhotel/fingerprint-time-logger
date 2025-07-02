#!/bin/bash
# Updated start script for unified FastAPI server architecture
# Simplified from dual-server to single unified server

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration for unified server
SERVICE="unified_server"
PORT=5000

# Start unified server
start_unified_server() {
    log_info "Starting unified FastAPI server..."
    
    # Resolve port conflicts
    local server_port
    server_port=$(resolve_port_conflict "$PORT" "$SERVICE")
    if [ $? -ne 0 ]; then
        log_error "Failed to resolve port conflict"
        return 1
    fi
    
    # Start unified server
    local pid_file="$PID_DIR/${SERVICE}.pid"
    local log_file="$LOG_DIR/unified_server.log"
    
    cd "$PROJECT_ROOT"
    nohup "$VENV_PATH/bin/uvicorn" app.main_unified:app \
        --host 0.0.0.0 \
        --port "$server_port" \
        --reload \
        > "$log_file" 2>&1 &
    
    local pid=$!
    echo "$pid" > "$pid_file"
    
    # Wait for server to start
    log_info "Waiting for unified server to start (PID: $pid, Port: $server_port)..."
    local attempts=0
    while [ $attempts -lt 30 ]; do
        if check_service_health "$SERVICE" "$server_port" "/api/devices/health"; then
            log_success "Unified server started successfully on port $server_port"
            return 0
        fi
        
        # Check if process is still running
        if ! kill -0 "$pid" 2>/dev/null; then
            log_error "Unified server process died"
            cat "$log_file" | tail -10
            return 1
        fi
        
        sleep 2
        attempts=$((attempts + 1))
    done
    
    log_error "Unified server failed to start within 60 seconds"
    return 1
}

# Pre-flight checks
pre_flight_checks() {
    log_info "Running pre-flight checks..."
    
    # Check if already running
    if is_process_running "$SERVICE"; then
        log_warn "Unified server is already running"
        log_info "Use './scripts/status.sh' to check status"
        log_info "Use './scripts/stop.sh' to stop service first"
        return 1
    fi
    
    # Ensure directories exist
    ensure_directories
    
    # Clean up stale PID files
    cleanup_stale_pids
    
    # Check virtual environment
    if ! check_virtual_env; then
        log_error "Virtual environment check failed"
        log_info "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
        return 1
    fi
    
    # Activate virtual environment
    if ! activate_venv; then
        log_error "Failed to activate virtual environment"
        return 1
    fi
    
    # Check database
    if ! check_database; then
        log_warn "Database issues detected, but continuing..."
    fi
    
    # Check disk space
    if ! check_disk_space; then
        log_warn "Low disk space detected, but continuing..."
    fi
    
    log_success "Pre-flight checks completed"
    return 0
}

# Post-start validation
post_start_validation() {
    log_info "Running post-start validation..."
    
    # Check unified server health
    if check_service_health "$SERVICE" "$PORT" "/api/devices/health"; then
        log_success "Unified server is healthy"
        log_info "Dashboard: http://localhost:$PORT"
        log_info "API Health: http://localhost:$PORT/api/devices/health"
        log_info "API Docs: http://localhost:$PORT/docs"
        return 0
    else
        log_error "Unified server health check failed"
        return 1
    fi
}

# Recovery attempt
attempt_recovery() {
    log_warn "Attempting recovery..."
    
    # Stop any partially started services
    "$SCRIPT_DIR/stop.sh" >/dev/null 2>&1 || true
    
    sleep 2
    
    # Clean up and retry
    cleanup_stale_pids
    
    # Wait a bit longer for ports to be freed
    sleep 3
    
    log_info "Recovery attempt complete, retrying startup..."
}

# Main execution
main() {
    echo "🚀 Fingerprint Time Logger - Starting Unified Server"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    
    # Pre-flight checks with retry
    if ! execute_with_retry pre_flight_checks; then
        log_error "Pre-flight checks failed after retries"
        exit 1
    fi
    
    # Start service with recovery
    local start_attempts=0
    local max_start_attempts=2
    
    while [ $start_attempts -lt $max_start_attempts ]; do
        log_info "Starting unified server (attempt $((start_attempts + 1))/$max_start_attempts)..."
        
        # Start unified server
        if start_unified_server; then
            # Validate service
            if post_start_validation; then
                log_success "Application started successfully!"
                echo ""
                echo "🌐 Access URLs:"
                echo "   📊 Dashboard: http://localhost:$PORT"
                echo "   🔌 API Health: http://localhost:$PORT/api/devices/health"
                echo "   📖 API Docs: http://localhost:$PORT/docs"
                echo ""
                echo "📋 Management Commands:"
                echo "   Status: ./scripts/status.sh"
                echo "   Stop:   ./scripts/stop.sh"
                echo "   Restart: ./scripts/restart.sh"
                echo ""
                exit 0
            fi
        fi
        
        start_attempts=$((start_attempts + 1))
        
        if [ $start_attempts -lt $max_start_attempts ]; then
            attempt_recovery
        fi
    done
    
    log_error "Failed to start application after $max_start_attempts attempts"
    log_info "Check logs in $LOG_DIR/ for more details"
    exit 1
}

# Execute main function
main "$@"