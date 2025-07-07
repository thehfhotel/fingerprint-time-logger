#!/bin/bash
# Common functions library for application management scripts

# Colors for logging
RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIFIED_PORT=${UNIFIED_PORT:-5000}  # Single unified server port
PYTHON_CMD=${PYTHON_CMD:-python3}
VENV_PATH="$PROJECT_ROOT/venv"
LOG_DIR="$PROJECT_ROOT/logs"
PID_DIR="$PROJECT_ROOT/pids"

# Logging functions
log_error() {
    echo -e "${RED}[ERROR $(date '+%H:%M:%S')]${NC} $*" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN $(date '+%H:%M:%S')]${NC} $*" >&2
}

log_info() {
    echo -e "${BLUE}[INFO $(date '+%H:%M:%S')]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[SUCCESS $(date '+%H:%M:%S')]${NC} $*"
}

# Ensure directories exist
ensure_directories() {
    mkdir -p "$LOG_DIR" "$PID_DIR"
}

# Check if port is in use
is_port_in_use() {
    local port=$1
    ss -tuln | grep -q ":$port "
}

# Get process ID using a port
get_process_on_port() {
    local port=$1
    ss -tlnp | grep ":$port " | grep -o 'pid=[0-9]*' | cut -d= -f2 | head -1
}

# Wait for port to be free
wait_for_port_free() {
    local port=$1
    local timeout=${2:-10}
    local count=0
    
    while is_port_in_use "$port" && [ $count -lt $timeout ]; do
        sleep 1
        count=$((count + 1))
    done
    
    [ $count -lt $timeout ]
}

# Find free port starting from given port
find_free_port() {
    local start_port=$1
    local port=$start_port
    
    while is_port_in_use "$port" && [ $port -lt $((start_port + 10)) ]; do
        port=$((port + 1))
    done
    
    if is_port_in_use "$port"; then
        return 1
    fi
    
    echo $port
}

# Check if process is running by PID file
is_process_running() {
    local service=$1
    local pid_file="$PID_DIR/${service}.pid"
    
    if [ ! -f "$pid_file" ]; then
        return 1
    fi
    
    local pid=$(cat "$pid_file" 2>/dev/null)
    if [ -z "$pid" ]; then
        return 1
    fi
    
    kill -0 "$pid" 2>/dev/null
}

# Kill process gracefully
kill_process_graceful() {
    local pid=$1
    local timeout=${2:-10}
    
    if ! kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    
    log_info "Sending SIGTERM to process $pid"
    kill -TERM "$pid" 2>/dev/null || return 0
    
    local count=0
    while kill -0 "$pid" 2>/dev/null && [ $count -lt $timeout ]; do
        sleep 1
        count=$((count + 1))
    done
    
    if kill -0 "$pid" 2>/dev/null; then
        log_warn "Process $pid did not terminate gracefully, sending SIGKILL"
        kill -KILL "$pid" 2>/dev/null || true
        sleep 2
    fi
    
    ! kill -0 "$pid" 2>/dev/null
}

# Execute with retry
execute_with_retry() {
    local max_attempts=3
    local delay=2
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if "$@"; then
            return 0
        fi
        
        if [ $attempt -lt $max_attempts ]; then
            log_warn "Attempt $attempt failed, retrying in ${delay}s..."
            sleep $delay
            delay=$((delay * 2))
        fi
        attempt=$((attempt + 1))
    done
    
    log_error "All $max_attempts attempts failed"
    return 1
}

# Check virtual environment
check_virtual_env() {
    if [ ! -d "$VENV_PATH" ]; then
        log_error "Virtual environment not found at $VENV_PATH"
        return 1
    fi
    
    if [ ! -f "$VENV_PATH/bin/activate" ]; then
        log_error "Virtual environment activation script not found"
        return 1
    fi
    
    return 0
}

# Activate virtual environment
activate_venv() {
    if ! check_virtual_env; then
        return 1
    fi
    
    # shellcheck source=/dev/null
    source "$VENV_PATH/bin/activate"
    log_info "Virtual environment activated"
}

# Check if service is healthy
check_service_health() {
    local service=$1
    local port=$2
    local endpoint=${3:-"/"}
    local timeout=${4:-5}
    
    # Check if process is running
    if ! is_process_running "$service"; then
        return 1
    fi
    
    # Check if port is listening
    if ! is_port_in_use "$port"; then
        return 1
    fi
    
    # HTTP health check
    if command -v curl >/dev/null 2>&1; then
        if curl -f -s --max-time "$timeout" "http://localhost:$port$endpoint" >/dev/null 2>&1; then
            return 0
        fi
    fi
    
    return 1
}

# Cleanup function
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Script exited with error code $exit_code"
    fi
}

# Set up error handling
setup_error_handling() {
    set -euo pipefail
    trap cleanup EXIT ERR
}

# Check disk space
check_disk_space() {
    local usage=$(df "$PROJECT_ROOT" | awk 'NR==2 {print $5}' | sed 's/%//')
    if [ "$usage" -gt 90 ]; then
        log_warn "Disk usage is ${usage}% - consider cleaning up"
        return 1
    fi
    return 0
}

# Check database file
check_database() {
    local db_file="$PROJECT_ROOT/database/attendance.db"
    if [ ! -f "$db_file" ]; then
        log_warn "Database file not found at $db_file"
        return 1
    fi
    
    if [ ! -r "$db_file" ]; then
        log_error "Database file is not readable"
        return 1
    fi
    
    return 0
}

# Clean up stale PID files
cleanup_stale_pids() {
    for pid_file in "$PID_DIR"/*.pid; do
        if [ -f "$pid_file" ]; then
            local service=$(basename "$pid_file" .pid)
            if ! is_process_running "$service"; then
                log_info "Removing stale PID file: $pid_file"
                rm -f "$pid_file"
            fi
        fi
    done
}

# Resolve port conflict
resolve_port_conflict() {
    local port=$1
    local service_name=$2
    
    if is_port_in_use "$port"; then
        log_warn "Port $port is in use, attempting resolution..."
        
        local pid=$(get_process_on_port "$port")
        if [ -n "$pid" ]; then
            log_info "Found process $pid using port $port"
            
            # Check if it's our own service
            local our_pid_file="$PID_DIR/${service_name}.pid"
            if [ -f "$our_pid_file" ]; then
                local our_pid=$(cat "$our_pid_file" 2>/dev/null)
                if [ "$pid" = "$our_pid" ]; then
                    log_info "Port is used by our own $service_name service"
                    return 0
                fi
            fi
            
            # Try graceful shutdown
            if kill_process_graceful "$pid" 5; then
                log_success "Successfully stopped conflicting process"
                return 0
            fi
        fi
        
        # Find alternative port
        local alt_port=$(find_free_port $((port + 1)))
        if [ -n "$alt_port" ]; then
            log_info "Using alternative port: $alt_port"
            echo "$alt_port"
            return 0
        fi
        
        log_error "Could not resolve port conflict for $port"
        return 1
    fi
    
    echo "$port"
    return 0
}