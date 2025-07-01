#!/bin/bash
# Self-correcting start script for Fingerprint Time Logger
# Handles port conflicts, environment issues, and automatic recovery

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration
API_SERVICE="api"
DASHBOARD_SERVICE="dashboard"

# Start API server
start_api_server() {
    log_info "Starting API server..."
    
    # Resolve port conflicts
    local api_port
    api_port=$(resolve_port_conflict "$API_PORT" "$API_SERVICE")
    if [ $? -ne 0 ]; then
        log_error "Failed to resolve API port conflict"
        return 1
    fi
    
    # Start API server
    local api_pid_file="$PID_DIR/${API_SERVICE}.pid"
    local api_log_file="$LOG_DIR/api.log"
    
    cd "$PROJECT_ROOT"
    nohup "$VENV_PATH/bin/uvicorn" app.main:app \
        --host 0.0.0.0 \
        --port "$api_port" \
        --reload \
        > "$api_log_file" 2>&1 &
    
    local api_pid=$!
    echo "$api_pid" > "$api_pid_file"
    
    # Wait for API to start
    log_info "Waiting for API server to start (PID: $api_pid, Port: $api_port)..."
    local attempts=0
    while [ $attempts -lt 30 ]; do
        if check_service_health "$API_SERVICE" "$api_port" "/docs"; then
            log_success "API server started successfully on port $api_port"
            return 0
        fi
        
        # Check if process is still running
        if ! kill -0 "$api_pid" 2>/dev/null; then
            log_error "API server process died"
            cat "$api_log_file" | tail -10
            return 1
        fi
        
        sleep 2
        attempts=$((attempts + 1))
    done
    
    log_error "API server failed to start within 60 seconds"
    return 1
}

# Start dashboard
start_dashboard() {
    log_info "Starting dashboard..."
    
    # Resolve port conflicts
    local dashboard_port
    dashboard_port=$(resolve_port_conflict "$DASHBOARD_PORT" "$DASHBOARD_SERVICE")
    if [ $? -ne 0 ]; then
        log_error "Failed to resolve dashboard port conflict"
        return 1
    fi
    
    # Start dashboard
    local dashboard_pid_file="$PID_DIR/${DASHBOARD_SERVICE}.pid"
    local dashboard_log_file="$LOG_DIR/dashboard.log"
    
    cd "$PROJECT_ROOT"
    
    # Set dashboard port environment variable if different
    if [ "$dashboard_port" != "$DASHBOARD_PORT" ]; then
        export DASHBOARD_PORT="$dashboard_port"
    fi
    
    nohup "$VENV_PATH/bin/python" dashboard_app.py \
        > "$dashboard_log_file" 2>&1 &
    
    local dashboard_pid=$!
    echo "$dashboard_pid" > "$dashboard_pid_file"
    
    # Wait for dashboard to start
    log_info "Waiting for dashboard to start (PID: $dashboard_pid, Port: $dashboard_port)..."
    local attempts=0
    while [ $attempts -lt 30 ]; do
        if check_service_health "$DASHBOARD_SERVICE" "$dashboard_port" "/"; then
            log_success "Dashboard started successfully on port $dashboard_port"
            return 0
        fi
        
        # Check if process is still running
        if ! kill -0 "$dashboard_pid" 2>/dev/null; then
            log_error "Dashboard process died"
            cat "$dashboard_log_file" | tail -10
            return 1
        fi
        
        sleep 2
        attempts=$((attempts + 1))
    done
    
    log_error "Dashboard failed to start within 60 seconds"
    return 1
}

# Pre-flight checks
pre_flight_checks() {
    log_info "Running pre-flight checks..."
    
    # Check if already running
    if is_process_running "$API_SERVICE" && is_process_running "$DASHBOARD_SERVICE"; then
        log_warn "Both services are already running"
        log_info "Use './scripts/status.sh' to check status"
        log_info "Use './scripts/stop.sh' to stop services first"
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
    
    local api_healthy=false
    local dashboard_healthy=false
    
    # Check API health
    if check_service_health "$API_SERVICE" "$API_PORT" "/docs"; then
        api_healthy=true
        log_success "API server is healthy"
    else
        log_error "API server health check failed"
    fi
    
    # Check dashboard health  
    if check_service_health "$DASHBOARD_SERVICE" "$DASHBOARD_PORT" "/"; then
        dashboard_healthy=true
        log_success "Dashboard is healthy"
    else
        log_error "Dashboard health check failed"
    fi
    
    if [ "$api_healthy" = true ] && [ "$dashboard_healthy" = true ]; then
        log_success "All services are healthy and running"
        log_info "API: http://localhost:$API_PORT"
        log_info "Dashboard: http://localhost:$DASHBOARD_PORT"
        return 0
    else
        log_error "Some services failed health checks"
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
    echo "🚀 Fingerprint Time Logger - Starting Application"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    
    # Pre-flight checks with retry
    if ! execute_with_retry pre_flight_checks; then
        log_error "Pre-flight checks failed after retries"
        exit 1
    fi
    
    # Start services with recovery
    local start_attempts=0
    local max_start_attempts=2
    
    while [ $start_attempts -lt $max_start_attempts ]; do
        log_info "Starting services (attempt $((start_attempts + 1))/$max_start_attempts)..."
        
        # Start API server
        if start_api_server; then
            # Start dashboard
            if start_dashboard; then
                # Validate both services
                if post_start_validation; then
                    log_success "Application started successfully!"
                    echo ""
                    echo "🌐 Access URLs:"
                    echo "   📊 Dashboard: http://localhost:$DASHBOARD_PORT"
                    echo "   🔌 API Server: http://localhost:$API_PORT"
                    echo "   📖 API Docs: http://localhost:$API_PORT/docs"
                    echo ""
                    echo "📋 Management Commands:"
                    echo "   Status: ./scripts/status.sh"
                    echo "   Stop:   ./scripts/stop.sh"
                    echo ""
                    exit 0
                fi
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