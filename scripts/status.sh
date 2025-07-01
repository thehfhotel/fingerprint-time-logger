#!/bin/bash
# Self-correcting status script for Fingerprint Time Logger
# Comprehensive health checks with diagnostics and recovery recommendations

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration
API_SERVICE="api"
DASHBOARD_SERVICE="dashboard"

# Exit codes for monitoring integration
EXIT_CODE_OK=0
EXIT_CODE_WARNING=1
EXIT_CODE_CRITICAL=2

# Service health check
check_service_detailed() {
    local service=$1
    local port=$2
    local endpoint=${3:-"/"}
    
    local pid_file="$PID_DIR/${service}.pid"
    local healthy=true
    
    echo "🔍 Checking $service..."
    
    # Check if process is running
    if is_process_running "$service"; then
        local pid=$(cat "$pid_file")
        log_success "$service is running (PID: $pid)"
        
        # Get process information
        local process_info=$(ps -p "$pid" -o pid,ppid,etime,pcpu,pmem,cmd --no-headers 2>/dev/null || echo "N/A")
        echo "   Process: $process_info"
        
        # Check port binding
        if is_port_in_use "$port"; then
            log_success "Port $port is listening"
            
            # HTTP health check
            if check_service_health "$service" "$port" "$endpoint"; then
                log_success "HTTP health check passed"
            else
                log_error "HTTP health check failed"
                healthy=false
            fi
        else
            log_error "Port $port is not listening"
            healthy=false
        fi
        
        # Check log for recent errors
        check_recent_errors "$service"
        
    else
        log_error "$service is not running"
        healthy=false
        
        # Check if port is still in use (conflict)
        if is_port_in_use "$port"; then
            local conflicting_pid=$(get_process_on_port "$port")
            log_warn "Port $port is in use by process $conflicting_pid"
        fi
    fi
    
    if [ "$healthy" = true ]; then
        return 0
    else
        return 1
    fi
}

# Check for recent errors in logs
check_recent_errors() {
    local service=$1
    local log_file="$LOG_DIR/${service}.log"
    
    if [ -f "$log_file" ]; then
        local error_count=$(tail -50 "$log_file" 2>/dev/null | grep -i -c "error\|exception\|failed\|traceback" || echo "0")
        
        if [ "$error_count" -gt 0 ]; then
            log_warn "Found $error_count recent errors in $service log"
            echo "   Recent errors:"
            tail -50 "$log_file" | grep -i "error\|exception\|failed" | tail -3 | while read -r line; do
                echo "     $line"
            done
        else
            log_success "No recent errors in $service log"
        fi
        
        # Log file size check
        local log_size=$(du -m "$log_file" | cut -f1)
        if [ "$log_size" -gt 100 ]; then
            log_warn "$service log file is ${log_size}MB (consider rotating)"
        fi
    else
        log_warn "$service log file not found"
    fi
}

# System health checks
system_health_checks() {
    echo ""
    echo "🔧 System Health Checks:"
    
    local issues_found=false
    
    # Check disk space
    if ! check_disk_space; then
        issues_found=true
    fi
    
    # Check virtual environment
    if ! check_virtual_env; then
        log_error "Virtual environment issues detected"
        issues_found=true
    else
        log_success "Virtual environment is healthy"
    fi
    
    # Check database
    if ! check_database; then
        issues_found=true
    else
        log_success "Database is accessible"
    fi
    
    # Check dependencies
    check_dependencies
    
    if [ "$issues_found" = true ]; then
        return 1
    else
        return 0
    fi
}

# Check key dependencies
check_dependencies() {
    echo ""
    echo "📦 Dependencies Check:"
    
    if [ -f "$VENV_PATH/bin/pip" ]; then
        local missing_deps=false
        
        for pkg in fastapi uvicorn flask pyzk sqlalchemy alembic; do
            if "$VENV_PATH/bin/pip" show "$pkg" >/dev/null 2>&1; then
                local version=$("$VENV_PATH/bin/pip" show "$pkg" | grep Version | cut -d' ' -f2)
                echo "   ✅ $pkg: $version"
            else
                echo "   ❌ $pkg: Not installed"
                missing_deps=true
            fi
        done
        
        if [ "$missing_deps" = true ]; then
            log_error "Some dependencies are missing"
            echo "   💡 Fix: pip install -r requirements.txt"
        fi
    else
        log_error "Pip not found in virtual environment"
    fi
}

# Network accessibility check
network_check() {
    echo ""
    echo "🌐 Network Accessibility:"
    
    # Get network IP
    local network_ip=$(ip route get 8.8.8.8 2>/dev/null | grep -oP 'src \K\S+' | head -1 || echo "unknown")
    
    echo "   Local access:"
    echo "     Dashboard: http://localhost:$DASHBOARD_PORT"
    echo "     API: http://localhost:$API_PORT"
    
    if [ "$network_ip" != "unknown" ]; then
        echo "   Network access:"
        echo "     Dashboard: http://$network_ip:$DASHBOARD_PORT"
        echo "     API: http://$network_ip:$API_PORT"
    fi
}

# Performance metrics
performance_metrics() {
    echo ""
    echo "📊 Performance Metrics:"
    
    # Memory usage
    local memory_info=$(free -h | grep "Mem:" | awk '{print "Used: " $3 "/" $2 " (" $3/$2*100 "%)"}' 2>/dev/null || echo "N/A")
    echo "   Memory: $memory_info"
    
    # CPU load
    local load_avg=$(uptime | awk -F'load average:' '{print $2}' | xargs || echo "N/A")
    echo "   Load Average: $load_avg"
    
    # Disk usage for project directory
    local disk_usage=$(df -h "$PROJECT_ROOT" | awk 'NR==2 {print $5}' || echo "N/A")
    echo "   Disk Usage: $disk_usage"
}

# Recovery recommendations
provide_recommendations() {
    local api_healthy=$1
    local dashboard_healthy=$2
    local system_healthy=$3
    
    echo ""
    echo "💡 Recommendations:"
    
    if [ "$api_healthy" = false ]; then
        echo "   🔧 API Server Issues:"
        echo "     - Check logs: tail -f $LOG_DIR/api.log"
        echo "     - Restart API: ./scripts/stop.sh api && ./scripts/start.sh"
    fi
    
    if [ "$dashboard_healthy" = false ]; then
        echo "   🖥️  Dashboard Issues:"
        echo "     - Check logs: tail -f $LOG_DIR/dashboard.log"
        echo "     - Restart Dashboard: ./scripts/stop.sh dashboard && ./scripts/start.sh"
    fi
    
    if [ "$system_healthy" = false ]; then
        echo "   🔧 System Issues:"
        echo "     - Check disk space: df -h"
        echo "     - Reinstall dependencies: pip install -r requirements.txt"
        echo "     - Check database: ls -la attendance.db"
    fi
    
    if [ "$api_healthy" = false ] || [ "$dashboard_healthy" = false ]; then
        echo "   🔄 Full restart: ./scripts/stop.sh && ./scripts/start.sh"
    fi
}

# Determine overall exit code
determine_exit_code() {
    local api_healthy=$1
    local dashboard_healthy=$2
    local system_healthy=$3
    
    if [ "$api_healthy" = true ] && [ "$dashboard_healthy" = true ] && [ "$system_healthy" = true ]; then
        return $EXIT_CODE_OK
    elif [ "$api_healthy" = true ] || [ "$dashboard_healthy" = true ]; then
        return $EXIT_CODE_WARNING
    else
        return $EXIT_CODE_CRITICAL
    fi
}

# Main execution
main() {
    echo "📊 Fingerprint Time Logger - System Status"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    echo "🕐 Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    
    ensure_directories
    
    local api_healthy=false
    local dashboard_healthy=false
    local system_healthy=false
    
    # Check API service
    echo "🔧 Service Status:"
    echo ""
    echo "📡 API Server:"
    if check_service_detailed "$API_SERVICE" "$API_PORT" "/docs"; then
        api_healthy=true
    fi
    
    echo ""
    echo "🖥️  Dashboard:"
    if check_service_detailed "$DASHBOARD_SERVICE" "$DASHBOARD_PORT" "/"; then
        dashboard_healthy=true
    fi
    
    # System health checks
    if system_health_checks; then
        system_healthy=true
    fi
    
    # Additional information
    network_check
    performance_metrics
    
    # Show recent activity
    echo ""
    echo "📈 Recent Activity (Last 5 Log Entries):"
    echo ""
    echo "API Server:"
    if [ -f "$LOG_DIR/api.log" ]; then
        tail -5 "$LOG_DIR/api.log" 2>/dev/null | while read -r line; do
            echo "   > $line"
        done
    else
        echo "   No API log file found"
    fi
    
    echo ""
    echo "Dashboard:"
    if [ -f "$LOG_DIR/dashboard.log" ]; then
        tail -5 "$LOG_DIR/dashboard.log" 2>/dev/null | while read -r line; do
            echo "   > $line"
        done
    else
        echo "   No Dashboard log file found"
    fi
    
    # Provide recommendations
    provide_recommendations "$api_healthy" "$dashboard_healthy" "$system_healthy"
    
    echo ""
    echo "📋 Management Commands:"
    echo "   Start:   ./scripts/start.sh"
    echo "   Stop:    ./scripts/stop.sh"
    echo "   Restart: ./scripts/restart.sh"
    echo ""
    
    # Overall status
    if [ "$api_healthy" = true ] && [ "$dashboard_healthy" = true ] && [ "$system_healthy" = true ]; then
        log_success "Status check completed! All systems healthy."
    elif [ "$api_healthy" = true ] || [ "$dashboard_healthy" = true ]; then
        log_warn "Status check completed with warnings. Some issues detected."
    else
        log_error "Status check completed with errors. Critical issues detected."
    fi
    
    # Return appropriate exit code for monitoring
    determine_exit_code "$api_healthy" "$dashboard_healthy" "$system_healthy"
}

# Execute main function
main "$@"