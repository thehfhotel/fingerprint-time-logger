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
SERVICE_NAME="fingerprint-logger"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
PORT=5000
HEALTH_ENDPOINT="http://localhost:$PORT/fingerprintlogs/health"
MAX_HEALTH_RETRIES=30
HEALTH_RETRY_DELAY=2

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
    if docker-compose -f "$COMPOSE_FILE" ps | grep -q "$SERVICE_NAME.*Up"; then
        log_warning "Application is already running"
        check_health
        return 0
    fi

    log_info "Starting application containers..."

    # Start with build to ensure latest image
    if docker-compose -f "$COMPOSE_FILE" up -d --build; then
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
}

stop_application() {
    log_header "STOPPING FINGERPRINT TIME LOGGER"

    check_docker
    check_compose_file

    # Check if running
    if ! docker-compose -f "$COMPOSE_FILE" ps | grep -q "$SERVICE_NAME"; then
        log_warning "No containers are currently running"
        return 0
    fi

    log_info "Stopping application containers..."

    if docker-compose -f "$COMPOSE_FILE" down; then
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
        docker-compose -f "$COMPOSE_FILE" ps || log_warning "Could not get container status"
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
    docker-compose -f "$COMPOSE_FILE" logs --tail=50 "$SERVICE_NAME" 2>/dev/null || log_error "Could not retrieve logs"
}

deploy_application() {
    log_header "DEPLOYING FINGERPRINT TIME LOGGER"

    check_docker
    check_compose_file

    log_info "Starting deployment process..."

    # Pull latest images
    log_info "Pulling latest base images..."
    docker-compose -f "$COMPOSE_FILE" pull || log_warning "Could not pull latest images"

    # Build with no cache to ensure fresh build
    log_info "Building application with latest changes..."
    if docker-compose -f "$COMPOSE_FILE" build --no-cache; then
        log_success "Build completed successfully"
    else
        log_error "Build failed"
        return 1
    fi

    # Deploy (restart with new images)
    log_info "Deploying application..."
    if docker-compose -f "$COMPOSE_FILE" up -d --force-recreate; then
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
    start       Start the application
    stop        Stop the application
    restart     Restart the application
    status      Show application status
    health      Check application health
    logs        Show application logs
    deploy      Deploy application with fresh build
    backup      Backup database
    help        Show this help message

Examples:
    $0 start                    # Start the application
    $0 stop                     # Stop the application
    $0 restart                  # Restart the application
    $0 status                   # Show comprehensive status
    $0 health                   # Quick health check
    $0 logs                     # Show recent logs
    $0 deploy                   # Deploy with fresh build
    $0 backup                   # Backup database

Environment Variables:
    SERVICE_NAME               # Docker service name (default: fingerprint-time-logger)
    PORT                      # Application port (default: 5000)
    MAX_HEALTH_RETRIES        # Health check retry count (default: 30)
    HEALTH_RETRY_DELAY        # Health check delay in seconds (default: 2)

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
    echo -e "${BLUE}9.${NC} Help"
    echo -e "${RED}0.${NC} Exit"
    echo ""
    echo -e "${YELLOW}=====================================${NC}"
}

get_user_choice() {
    local choice
    echo -ne "${GREEN}Enter your choice [0-9]: ${NC}" >&2
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

# Main execution with interactive menu or direct command support
main() {
    # If arguments provided, use command-line mode for backwards compatibility
    if [[ $# -gt 0 ]]; then
        case "${1:-help}" in
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
            help|--help|-h)
                show_usage
                ;;
            *)
                log_error "Unknown command: $1"
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