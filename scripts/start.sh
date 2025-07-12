#!/bin/bash
# Docker Compose start script for Fingerprint Time Logger
# Updated to use containerized deployment

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration
SERVICE_NAME="fingerprint-time-logger"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
PORT=5000

# Check Docker and Docker Compose
check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker is not installed or not in PATH"
        return 1
    fi
    
    if ! command -v docker-compose >/dev/null 2>&1 && ! docker compose version >/dev/null 2>&1; then
        log_error "Docker Compose is not installed or not in PATH"
        return 1
    fi
    
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker daemon is not running"
        return 1
    fi
    
    return 0
}

# Start with Docker Compose
start_docker_service() {
    log_info "Starting Docker Compose services..."
    
    cd "$PROJECT_ROOT"
    
    # Use docker compose (newer) or docker-compose (legacy)
    local compose_cmd="docker compose"
    if ! docker compose version >/dev/null 2>&1; then
        compose_cmd="docker-compose"
    fi
    
    # Build and start services
    if $compose_cmd up -d --build; then
        log_success "Docker services started successfully"
        return 0
    else
        log_error "Failed to start Docker services"
        return 1
    fi
}

# Wait for service to be ready
wait_for_service() {
    log_info "Waiting for service to be ready..."
    
    local attempts=0
    local max_attempts=30
    
    while [ $attempts -lt $max_attempts ]; do
        if curl -f http://localhost:$PORT/api/devices/health >/dev/null 2>&1; then
            log_success "Service is ready and healthy"
            return 0
        fi
        
        # Check if container is running
        if ! docker ps --filter "name=$SERVICE_NAME" --filter "status=running" | grep -q "$SERVICE_NAME"; then
            log_error "Container is not running"
            return 1
        fi
        
        sleep 2
        attempts=$((attempts + 1))
    done
    
    log_error "Service failed to become ready within $((max_attempts * 2)) seconds"
    return 1
}

# Show service status
show_service_info() {
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
    echo "🐳 Docker Commands:"
    echo "   Logs: docker logs $SERVICE_NAME"
    echo "   Shell: docker exec -it $SERVICE_NAME bash"
    echo ""
}

# Main execution
main() {
    echo "🚀 Fingerprint Time Logger - Starting Docker Services"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    echo ""
    
    # Pre-flight checks
    log_info "Running pre-flight checks..."
    
    if ! check_docker; then
        log_error "Docker environment check failed"
        exit 1
    fi
    
    # Check if already running
    if docker ps --filter "name=$SERVICE_NAME" --filter "status=running" | grep -q "$SERVICE_NAME"; then
        log_warn "Service is already running"
        log_info "Use './scripts/status.sh' to check status"
        log_info "Use './scripts/stop.sh' to stop service first"
        show_service_info
        exit 0
    fi
    
    log_success "Pre-flight checks completed"
    
    # Start services
    if start_docker_service; then
        if wait_for_service; then
            log_success "Application started successfully!"
            show_service_info
            exit 0
        else
            log_error "Service failed to become ready"
            log_info "Check logs with: docker logs $SERVICE_NAME"
            exit 1
        fi
    else
        log_error "Failed to start Docker services"
        exit 1
    fi
}

# Execute main function
main "$@"