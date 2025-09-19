#!/bin/bash

# Fingerprint Time Logger Application Management Script
# Consolidates all application lifecycle operations: start, stop, restart, deploy, health checks

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="app"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
BAKE_FILE="$PROJECT_ROOT/docker-bake.hcl"
PORT=5000
HEALTH_ENDPOINT="http://localhost:$PORT/fingerprintlogs/health"
MAX_HEALTH_RETRIES=30
HEALTH_RETRY_DELAY=2

# Build configuration
BUILD_METHOD=${BUILD_METHOD:-"auto"}  # auto, bake, compose
BUILD_TARGET=${BUILD_TARGET:-"fingerprint-time-logger"}

# Source common functions if available
if [[ -f "$SCRIPT_DIR/lib/common.sh" ]]; then
    # shellcheck source=lib/common.sh
    source "$SCRIPT_DIR/lib/common.sh"
fi

# Logging functions
log_info() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')] INFO: $1${NC}"
}

log_success() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')] SUCCESS: $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] WARNING: $1${NC}"
}

log_error() {
    echo -e "${RED}[$(date +'%H:%M:%S')] ERROR: $1${NC}"
}

log_header() {
    echo -e "${CYAN}=====================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}=====================================${NC}"
}

# Docker and system checks
check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi

    if ! command -v docker-compose >/dev/null 2>&1 && ! docker compose version >/dev/null 2>&1; then
        log_error "Docker Compose is not available"
        exit 1
    fi

    # Check if Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker daemon is not running"
        exit 1
    fi

    log_info "Docker environment validated"
}

check_compose_file() {
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        log_error "Docker compose file not found: $COMPOSE_FILE"
        exit 1
    fi
    log_info "Docker compose file found: $COMPOSE_FILE"
}

# Docker Compose helper function
get_compose_cmd() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    else
        echo "docker-compose"
    fi
}

# Docker Bake support functions
check_bake_support() {
    if command -v docker >/dev/null 2>&1 && docker buildx bake --help >/dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

check_bake_file() {
    if [[ -f "$BAKE_FILE" ]]; then
        return 0
    else
        return 1
    fi
}

determine_build_method() {
    local method="$1"

    case "$method" in
        "bake")
            if check_bake_support && check_bake_file; then
                echo "bake"
            else
                log_warning "Bake requested but not available, falling back to Compose" >&2
                echo "compose"
            fi
            ;;
        "compose")
            echo "compose"
            ;;
        "auto"|*)
            if check_bake_support && check_bake_file; then
                log_info "Docker Bake detected - using optimized build system" >&2
                echo "bake"
            else
                log_info "Using standard Docker Compose build" >&2
                echo "compose"
            fi
            ;;
    esac
}

# ==============================================================================
# CACHE MANAGEMENT FUNCTIONS
# ==============================================================================

detect_cache_staleness() {
    local cache_state_file=".docker-cache-state"
    local staleness_hours=${CACHE_STALENESS_HOURS:-24}
    local critical_files=("Dockerfile" "requirements.txt" "requirements-*.txt" "docker-bake.hcl" "docker-compose.yml")
    local stale_files=()

    # Check if cache state file exists
    if [[ ! -f "$cache_state_file" ]]; then
        log_info "No cache state found - cache will be considered stale"
        return 0  # Stale
    fi

    # Check critical files for modifications
    for pattern in "${critical_files[@]}"; do
        while IFS= read -r -d '' file; do
            if [[ "$file" -nt "$cache_state_file" ]]; then
                stale_files+=("$file")
            fi
        done < <(find . -maxdepth 1 -name "$pattern" -print0 2>/dev/null)
    done

    # Check source code modifications (app directory)
    if [[ -d "app" ]]; then
        local app_files_newer
        app_files_newer=$(find app/ -name "*.py" -newer "$cache_state_file" 2>/dev/null | wc -l)
        if [[ $app_files_newer -gt 0 ]]; then
            stale_files+=("app/ ($app_files_newer files)")
        fi
    fi

    # Check cache age
    if [[ -f "$cache_state_file" ]]; then
        local cache_age_hours
        cache_age_hours=$(( ($(date +%s) - $(stat -c %Y "$cache_state_file" 2>/dev/null || stat -f %m "$cache_state_file" 2>/dev/null || echo 0)) / 3600 ))
        if [[ $cache_age_hours -gt $staleness_hours ]]; then
            stale_files+=("cache age: ${cache_age_hours}h (limit: ${staleness_hours}h)")
        fi
    fi

    # Report findings
    if [[ ${#stale_files[@]} -gt 0 ]]; then
        if [[ "${CACHE_DEBUG:-false}" == "true" ]]; then
            log_warning "Cache staleness detected:"
            for file in "${stale_files[@]}"; do
                log_warning "  - $file"
            done
        fi
        return 0  # Stale
    else
        if [[ "${CACHE_DEBUG:-false}" == "true" ]]; then
            log_info "Cache appears fresh"
        fi
        return 1  # Fresh
    fi
}

clear_buildkit_cache() {
    log_info "Clearing BuildKit cache..."
    local cache_size_before
    cache_size_before=$(docker buildx du --verbose 2>/dev/null | grep "^Total:" | awk '{print $2}' || echo "Unknown")

    if command -v docker buildx >/dev/null 2>&1; then
        if docker buildx prune -f; then
            local cache_size_after
            cache_size_after=$(docker buildx du --verbose 2>/dev/null | grep "^Total:" | awk '{print $2}' || echo "0B")
            log_success "BuildKit cache cleared (was: $cache_size_before, now: $cache_size_after)"
        else
            log_error "Failed to clear BuildKit cache"
            return 1
        fi
    else
        log_warning "Docker buildx not available, skipping BuildKit cache clear"
        return 1
    fi
}

clear_docker_cache() {
    log_info "Clearing Docker build cache..."
    if docker builder prune -f; then
        log_success "Docker build cache cleared"
    else
        log_error "Failed to clear Docker build cache"
        return 1
    fi
}

apply_cache_strategy() {
    local cache_strategy=${CACHE_STRATEGY:-fast}
    local force_fresh=${1:-false}

    # Force fresh build overrides everything
    if [[ "$force_fresh" == "true" ]]; then
        log_info "Fresh build requested - clearing all caches"
        clear_buildkit_cache
        clear_docker_cache
        return 0
    fi

    case "$cache_strategy" in
        "auto")
            if detect_cache_staleness; then
                log_info "Auto cache strategy: Stale cache detected, clearing..."
                clear_buildkit_cache
                # Don't clear docker cache for compose builds unless explicitly needed
            else
                log_info "Auto cache strategy: Cache is fresh, using existing cache"
            fi
            ;;
        "fresh")
            log_info "Fresh cache strategy: Clearing all caches"
            clear_buildkit_cache
            clear_docker_cache
            ;;
        "preserve")
            log_info "Preserve cache strategy: Using existing cache"
            ;;
        "fast")
            log_info "Fast cache strategy: Maximum cache utilization for speed"
            # Never clear cache unless forced, rely on CACHEBUST for invalidation
            ;;
        *)
            log_warning "Unknown cache strategy '$cache_strategy', using auto"
            apply_cache_strategy "auto" "$force_fresh"
            ;;
    esac
}

update_cache_state() {
    local cache_state_file=".docker-cache-state"
    local build_method=${1:-$(determine_build_method "$BUILD_METHOD")}

    # Create cache state file with metadata
    cat > "$cache_state_file" << EOF
# Cache state file - generated $(date)
# Build method: $build_method
# Cache strategy: ${CACHE_STRATEGY:-fast}
# Last updated: $(date -u -Iseconds)
EOF

    if [[ "${CACHE_DEBUG:-false}" == "true" ]]; then
        log_info "Cache state updated: $cache_state_file"
    fi
}

show_cache_status() {
    local cache_state_file=".docker-cache-state"

    log_header "CACHE STATUS"

    # Cache state file info
    if [[ -f "$cache_state_file" ]]; then
        local last_updated
        last_updated=$(stat -c %y "$cache_state_file" 2>/dev/null || stat -f %Sm "$cache_state_file" 2>/dev/null || echo "Unknown")
        log_info "Last cache update: $last_updated"

        # Show cache file content if debug enabled
        if [[ "${CACHE_DEBUG:-false}" == "true" ]]; then
            echo ""
            cat "$cache_state_file"
            echo ""
        fi
    else
        log_warning "No cache state file found (.docker-cache-state)"
    fi

    # Docker cache sizes
    echo ""
    log_info "Docker cache usage:"
    if command -v docker system >/dev/null 2>&1; then
        docker system df
    else
        log_error "Docker not available"
    fi

    # BuildKit cache info if available
    echo ""
    if command -v docker buildx >/dev/null 2>&1; then
        log_info "BuildKit cache info:"
        docker buildx du 2>/dev/null || log_warning "BuildKit cache info not available"
    fi

    # Staleness detection
    echo ""
    if detect_cache_staleness; then
        log_warning "Cache Status: STALE (recommend clearing)"
    else
        log_success "Cache Status: FRESH (can reuse)"
    fi

    # Current configuration
    echo ""
    log_info "Cache configuration:"
    log_info "  CACHE_STRATEGY: ${CACHE_STRATEGY:-fast}"
    log_info "  CACHE_STALENESS_HOURS: ${CACHE_STALENESS_HOURS:-24}"
    log_info "  CACHE_DEBUG: ${CACHE_DEBUG:-false}"
}

cache_clear_command() {
    log_header "CLEARING ALL BUILD CACHES"

    local cleared=false

    # Clear BuildKit cache
    if clear_buildkit_cache; then
        cleared=true
    fi

    # Clear Docker cache
    if clear_docker_cache; then
        cleared=true
    fi

    # Clear system cache if requested
    if [[ "${1:-}" == "--system" ]]; then
        log_info "Clearing system Docker cache..."
        if docker system prune -f; then
            log_success "System Docker cache cleared"
            cleared=true
        else
            log_error "Failed to clear system Docker cache"
        fi
    fi

    if [[ "$cleared" == "true" ]]; then
        # Update cache state to reflect clearing
        update_cache_state
        log_success "Cache clearing completed"
    else
        log_error "No caches were successfully cleared"
        return 1
    fi
}

rebuild_command() {
    log_header "RELIABLE REBUILD WITH CACHE BUSTING"

    local target="${BUILD_TARGET:-fingerprint-time-logger}"
    local cachebust
    cachebust=$(date +%s)

    log_info "Using cache-busting value: $cachebust"
    log_info "Target: $target"

    # Determine build method
    local actual_method
    actual_method=$(determine_build_method "$BUILD_METHOD")

    case "$actual_method" in
        "bake")
            log_info "Rebuilding with Docker Bake and cache busting..."
            if check_bake_support && check_bake_file; then
                log_info "Running: docker buildx bake --set $target.args.CACHEBUST=$cachebust $target"
                if docker buildx bake --set "$target.args.CACHEBUST=$cachebust" "$target"; then
                    log_success "Bake rebuild with cache busting completed successfully"
                    update_cache_state
                    return 0
                else
                    log_error "Bake rebuild failed"
                    return 1
                fi
            else
                log_error "Docker Bake not available"
                return 1
            fi
            ;;
        "compose")
            log_info "Rebuilding with Docker Compose..."
            if docker compose build; then
                log_success "Compose rebuild completed successfully"
                update_cache_state
                return 0
            else
                log_error "Compose rebuild failed"
                return 1
            fi
            ;;
        *)
            log_error "Unknown build method: $actual_method"
            return 1
            ;;
    esac
}

# ==============================================================================
# BUILD FUNCTIONS
# ==============================================================================

# Enhanced build function with cache management
build_application() {
    local fresh_build=${1:-false}
    local actual_method
    actual_method=$(determine_build_method "$BUILD_METHOD")

    log_info "Building application using $actual_method method..."

    # Apply cache strategy before building
    apply_cache_strategy "$fresh_build"

    case "$actual_method" in
        "bake")
            build_with_bake
            ;;
        "compose")
            build_with_compose
            ;;
        *)
            log_error "Unknown build method: $actual_method"
            return 1
            ;;
    esac

    # Update cache state after successful build
    if [[ $? -eq 0 ]]; then
        update_cache_state "$actual_method"
    fi
}

build_with_bake() {
    local original_dir="$(pwd)"

    log_info "Running Docker Bake build with target: $BUILD_TARGET"

    # Change to project root to ensure bake definition file is found
    cd "$PROJECT_ROOT"

    # Simple Docker Bake build - no cache complexity
    if docker buildx bake --load "$BUILD_TARGET"; then
        cd "$original_dir"
        log_success "Bake build completed successfully"
        return 0
    else
        cd "$original_dir"
        log_error "Bake build failed"
        return 1
    fi
}

build_with_compose() {
    log_info "Running Docker Compose build"

    # Use docker compose (modern) or docker-compose (legacy)
    local compose_cmd="docker compose"
    if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
        compose_cmd="docker-compose"
    fi

    # Simple Compose build
    if $compose_cmd -f "$COMPOSE_FILE" build; then
        log_success "Compose build completed successfully"
        return 0
    else
        log_error "Compose build failed"
        return 1
    fi
}

# Health check functions
wait_for_health() {
    local retries=0
    log_info "Waiting for application health check..."

    while [[ $retries -lt $MAX_HEALTH_RETRIES ]]; do
        if curl -s -f "$HEALTH_ENDPOINT" >/dev/null 2>&1; then
            log_success "Application is healthy"
            return 0
        fi

        retries=$((retries + 1))
        echo -n "."
        sleep $HEALTH_RETRY_DELAY
    done

    echo ""
    log_error "Application failed to become healthy after $((MAX_HEALTH_RETRIES * HEALTH_RETRY_DELAY)) seconds"
    return 1
}

check_health() {
    log_info "Checking application health..."

    if curl -s -f "$HEALTH_ENDPOINT" >/dev/null 2>&1; then
        local health_response
        health_response=$(curl -s "$HEALTH_ENDPOINT" 2>/dev/null || echo "{}")

        echo "Health Status:"
        echo "$health_response" | python3 -m json.tool 2>/dev/null || echo "$health_response"

        log_success "Application is healthy"
        return 0
    else
        log_error "Application health check failed"
        return 1
    fi
}

# Application management functions
start_application() {
    log_header "STARTING FINGERPRINT TIME LOGGER"

    check_docker
    check_compose_file

    # Check if already running
    local compose_cmd
    compose_cmd=$(get_compose_cmd)
    if $compose_cmd -f "$COMPOSE_FILE" ps | grep -q "$SERVICE_NAME.*Up"; then
        log_warning "Application is already running"
        check_health
        return 0
    fi

    log_info "Starting application containers..."

    # Build with enhanced build system
    if build_application; then
        log_info "Starting containers with latest image..."

        # Get the appropriate compose command
        compose_cmd=$(get_compose_cmd)

        if $compose_cmd -f "$COMPOSE_FILE" up -d; then
            log_success "Containers started successfully"

            # Wait for application to be healthy
            if wait_for_health; then
                log_success "Application started and is healthy"
                echo ""
                log_info "Application URLs:"
                log_info "  Dashboard: http://localhost:$PORT/"
                log_info "  API Docs:  http://localhost:$PORT/docs"
                log_info "  Status:    http://localhost:$PORT/status"
            else
                log_error "Application started but health check failed"
                show_logs
                return 1
            fi
        else
            log_error "Failed to start application containers"
            return 1
        fi
    else
        log_error "Build failed"
        return 1
    fi
}

stop_application() {
    log_header "STOPPING FINGERPRINT TIME LOGGER"

    check_docker
    check_compose_file

    # Check if running
    local compose_cmd
    compose_cmd=$(get_compose_cmd)
    if ! $compose_cmd -f "$COMPOSE_FILE" ps | grep -q "$SERVICE_NAME"; then
        log_warning "No containers are currently running"
        return 0
    fi

    log_info "Stopping application containers..."

    if $compose_cmd -f "$COMPOSE_FILE" down; then
        log_success "Application stopped successfully"
    else
        log_error "Failed to stop application"
        return 1
    fi

    # Clean up any orphaned containers
    log_info "Cleaning up any orphaned containers..."
    docker system prune -f >/dev/null 2>&1 || true
}

restart_application() {
    log_header "RESTARTING FINGERPRINT TIME LOGGER"

    stop_application
    sleep 2
    start_application
}

show_status() {
    log_header "APPLICATION STATUS"

    check_docker

    # Container status
    echo "Container Status:"
    if [[ -f "$COMPOSE_FILE" ]]; then
        local compose_cmd
        compose_cmd=$(get_compose_cmd)
        $compose_cmd -f "$COMPOSE_FILE" ps || log_warning "Could not get container status"
    else
        log_warning "Docker compose file not found"
    fi

    echo ""

    # Health status
    check_health

    echo ""

    # System resources
    echo "System Resources:"
    if command -v docker >/dev/null 2>&1; then
        echo "Docker containers resource usage:"
        docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" 2>/dev/null | head -10 || log_warning "Could not get resource stats"
    fi

    # Database status
    echo ""
    echo "Database Status:"
    if [[ -f "$PROJECT_ROOT/database/attendance.db" ]]; then
        local db_size
        db_size=$(du -h "$PROJECT_ROOT/database/attendance.db" 2>/dev/null | cut -f1)
        log_info "Database file: $db_size"
    else
        log_warning "Database file not found"
    fi

    # Port status
    echo ""
    echo "Port Status:"
    if command -v netstat >/dev/null 2>&1; then
        if netstat -tulpn 2>/dev/null | grep -q ":$PORT "; then
            log_info "Port $PORT is in use"
        else
            log_warning "Port $PORT is not in use"
        fi
    elif command -v ss >/dev/null 2>&1; then
        if ss -tulpn 2>/dev/null | grep -q ":$PORT "; then
            log_info "Port $PORT is in use"
        else
            log_warning "Port $PORT is not in use"
        fi
    fi
}

show_logs() {
    log_header "APPLICATION LOGS"

    check_docker
    check_compose_file

    log_info "Showing recent application logs..."
    local compose_cmd
    compose_cmd=$(get_compose_cmd)
    $compose_cmd -f "$COMPOSE_FILE" logs --tail=50 "$SERVICE_NAME" 2>/dev/null || log_error "Could not retrieve logs"
}

deploy_application() {
    local fresh_build=false

    # Check for --fresh-build flag in remaining args
    for arg in "${remaining_args[@]}"; do
        if [[ "$arg" == "--fresh-build" ]]; then
            fresh_build=true
            break
        fi
    done

    log_header "DEPLOYING FINGERPRINT TIME LOGGER"

    check_docker
    check_compose_file

    log_info "Starting deployment process..."

    # Pull latest images and build with enhanced build system
    if [[ "$fresh_build" == "true" ]]; then
        log_info "Fresh build requested - clearing caches and building application..."
    else
        log_info "Pulling latest base images and building application..."
    fi

    if build_application "$fresh_build"; then
        log_success "Build completed successfully"
    else
        log_error "Build failed"
        return 1
    fi

    # Deploy (restart with new images)
    log_info "Deploying application..."

    # Get the appropriate compose command
    local compose_cmd
    compose_cmd=$(get_compose_cmd)

    if $compose_cmd -f "$COMPOSE_FILE" up -d --force-recreate; then
        log_success "Deployment completed"

        # Wait for health check
        if wait_for_health; then
            log_success "Deployment successful and application is healthy"
        else
            log_error "Deployment completed but health check failed"
            show_logs
            return 1
        fi
    else
        log_error "Deployment failed"
        return 1
    fi
}

backup_database() {
    log_header "DATABASE BACKUP"

    local backup_dir="$PROJECT_ROOT/backups"
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local backup_file="$backup_dir/attendance_backup_$timestamp.db"

    # Create backup directory
    mkdir -p "$backup_dir"

    if [[ -f "$PROJECT_ROOT/database/attendance.db" ]]; then
        log_info "Creating database backup..."
        if cp "$PROJECT_ROOT/database/attendance.db" "$backup_file"; then
            log_success "Database backed up to: $backup_file"

            # Compress backup
            if command -v gzip >/dev/null 2>&1; then
                gzip "$backup_file"
                log_info "Backup compressed: ${backup_file}.gz"
            fi

            # Clean up old backups (keep last 10)
            find "$backup_dir" -name "attendance_backup_*.db.gz" -type f | sort -r | tail -n +11 | xargs rm -f 2>/dev/null || true
        else
            log_error "Failed to create database backup"
            return 1
        fi
    else
        log_error "Database file not found for backup"
        return 1
    fi
}

show_usage() {
    cat << EOF
Fingerprint Time Logger - Application Management Script

Usage: $0 <command> [options]

Commands:
    start           Start the application
    stop            Stop the application
    restart         Restart the application
    status          Show application status
    health          Check application health
    logs            Show application logs
    deploy          Deploy application with fresh build
    backup          Backup database
    cache-status    Show Docker BuildKit cache status
    cache-clear     Clear Docker BuildKit cache
    rebuild         Force rebuild with cache busting (reliable for file changes)
    help            Show this help message

Build Options:
    --build-method METHOD      Set build method (auto, bake, compose)
    --build-target TARGET      Set Docker Bake target (fingerprint-logger, fingerprint-logger-dev, fingerprint-logger-prod)
    --no-build-cache          Force rebuild without cache (clears BuildKit cache first)
    --fresh-build             Clear cache and rebuild from scratch (for deploy command)

Cache Management:
    --cache-strategy STRATEGY  Cache strategy: auto, fast, preserve, fresh (default: fast)
    --cache-debug             Enable cache debugging output

Examples:
    $0 start                           # Start with auto-detected build method
    $0 start --build-method bake       # Start with Docker Bake build
    $0 deploy --build-target fingerprint-logger-prod  # Deploy production build
    $0 deploy --fresh-build            # Deploy with complete cache clear
    $0 restart --no-build-cache        # Restart with fresh build
    $0 status                          # Show comprehensive status
    $0 health                          # Quick health check
    $0 logs                            # Show recent logs
    $0 backup                          # Backup database
    $0 cache-status                    # Check BuildKit cache status
    $0 cache-clear                     # Clear BuildKit cache (40GB+ possible)
    $0 rebuild                         # Force reliable rebuild with cache busting

Environment Variables:
    BUILD_METHOD              # Build method (auto, bake, compose) (default: auto)
    BUILD_TARGET              # Docker Bake target (default: fingerprint-time-logger)
    SERVICE_NAME              # Docker service name (default: app)
    PORT                      # Application port (default: 5000)
    MAX_HEALTH_RETRIES        # Health check retry count (default: 30)
    HEALTH_RETRY_DELAY        # Health check delay in seconds (default: 2)
    CACHE_STRATEGY            # Cache management strategy (auto, fast, preserve, fresh) (default: fast)
    CACHE_STALENESS_HOURS     # Hours before cache is considered stale (default: 24)
    CACHE_DEBUG               # Enable cache debugging output (true/false) (default: false)

Build Methods:
    auto        Automatically detect and use Docker Bake if available, fallback to Compose
    bake        Force use of Docker Bake (requires docker buildx bake support)
    compose     Force use of standard Docker Compose build

Build Targets (Docker Bake):
    fingerprint-time-logger        Standard production build (default)
    fingerprint-time-logger-dev    Development build with additional tools
    fingerprint-time-logger-prod   Production optimized build

Cache Management Notes:
    The Docker BuildKit cache can grow very large (40GB+) and may cause build issues where
    file changes are not detected. The cache management commands help resolve these issues:

    - cache-status: Shows current BuildKit cache size and age
    - cache-clear: Clears all BuildKit cache (may take several minutes)
    - auto: Intelligent cache management - clears when code changes detected (balanced)
    - fast: Maximum cache utilization for fastest builds (relies on CACHEBUST for invalidation)
    - preserve: Never clear cache, use existing layers for maximum speed
    - fresh: Always clear cache for clean builds (slowest but most reliable)

    If your builds are not picking up file changes, use:
    $0 rebuild                         # Reliable rebuild with cache busting
    $0 cache-clear && $0 restart       # Alternative: clear cache then restart

EOF
}

# Interactive menu system
show_menu() {
    clear
    echo -e "${CYAN}=====================================${NC}"
    echo -e "${CYAN}  Fingerprint Time Logger Manager${NC}"
    echo -e "${CYAN}=====================================${NC}"
    echo ""
    echo -e "${GREEN}Available Operations:${NC}"
    echo ""
    echo -e "${BLUE}1.${NC} Start Application"
    echo -e "${BLUE}2.${NC} Stop Application"
    echo -e "${BLUE}3.${NC} Restart Application"
    echo -e "${BLUE}4.${NC} Show Status"
    echo -e "${BLUE}5.${NC} Health Check"
    echo -e "${BLUE}6.${NC} Show Logs"
    echo -e "${BLUE}7.${NC} Deploy Application"
    echo -e "${BLUE}8.${NC} Backup Database"
    echo ""
    echo -e "${CYAN}Cache Management:${NC}"
    echo -e "${BLUE}9.${NC} Show Cache Status"
    echo -e "${BLUE}10.${NC} Clear BuildKit Cache"
    echo -e "${BLUE}11.${NC} Force Rebuild (Cache Busting)"
    echo ""
    echo -e "${BLUE}12.${NC} Help"
    echo -e "${RED}0.${NC} Exit"
    echo ""
    echo -e "${YELLOW}=====================================${NC}"
}

get_user_choice() {
    local choice
    echo -ne "${GREEN}Enter your choice [0-12]: ${NC}" >&2
    read -r choice
    echo "$choice"
}

execute_choice() {
    local choice=$1

    case $choice in
        1)
            log_info "Starting application..."
            start_application
            ;;
        2)
            log_info "Stopping application..."
            stop_application
            ;;
        3)
            log_info "Restarting application..."
            restart_application
            ;;
        4)
            show_status
            ;;
        5)
            check_health
            ;;
        6)
            show_logs
            ;;
        7)
            log_info "Deploying application..."
            deploy_application
            ;;
        8)
            log_info "Creating database backup..."
            backup_database
            ;;
        9)
            log_info "Checking cache status..."
            show_cache_status
            ;;
        10)
            log_info "Clearing BuildKit cache..."
            cache_clear_command
            ;;
        11)
            log_info "Force rebuilding with cache busting..."
            rebuild_command
            ;;
        12)
            show_usage
            ;;
        0)
            log_info "Exiting..."
            exit 0
            ;;
        *)
            log_error "Invalid choice: $choice"
            ;;
    esac
}

wait_for_continue() {
    echo ""
    echo -ne "${YELLOW}Press Enter to continue...${NC}"
    read -r
}

# Argument parsing function
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --build-method)
                BUILD_METHOD="$2"
                shift 2
                ;;
            --build-target)
                BUILD_TARGET="$2"
                shift 2
                ;;
            --help|-h)
                show_usage
                exit 0
                ;;
            -*)
                log_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
            *)
                # This should be the command, stop parsing
                break
                ;;
        esac
    done
}

# Main execution with interactive menu or direct command support
main() {
    # Parse command line arguments first
    local original_args=("$@")
    parse_arguments "$@"

    # Remove parsed arguments to get the command
    local remaining_args=()
    local skip_next=false
    for arg in "${original_args[@]}"; do
        if [[ "$skip_next" == "true" ]]; then
            skip_next=false
            continue
        fi
        case "$arg" in
            --build-method|--build-target)
                skip_next=true
                ;;
            --help|-h)
                ;;
            *)
                remaining_args+=("$arg")
                ;;
        esac
    done

    # If arguments provided, use command-line mode for backwards compatibility
    if [[ ${#remaining_args[@]} -gt 0 ]]; then
        case "${remaining_args[0]:-help}" in
            start)
                start_application
                ;;
            stop)
                stop_application
                ;;
            restart)
                restart_application
                ;;
            status)
                show_status
                ;;
            health)
                check_health
                ;;
            logs)
                show_logs
                ;;
            deploy)
                deploy_application
                ;;
            backup)
                backup_database
                ;;
            cache-status)
                show_cache_status
                ;;
            cache-clear)
                cache_clear_command "${remaining_args[@]:1}"
                ;;
            rebuild)
                rebuild_command
                ;;
            help|--help|-h)
                show_usage
                ;;
            *)
                log_error "Unknown command: ${remaining_args[0]}"
                echo ""
                show_usage
                exit 1
                ;;
        esac
        return
    fi

    # Interactive menu mode
    while true; do
        show_menu
        choice=$(get_user_choice)
        echo ""

        execute_choice "$choice"

        if [[ "$choice" != "0" && "$choice" != "9" ]]; then
            wait_for_continue
        fi

        if [[ "$choice" == "0" ]]; then
            break
        fi
    done
}

# Run main function with all arguments
main "$@"