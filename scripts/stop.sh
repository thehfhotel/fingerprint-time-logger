#!/bin/bash
# Docker Compose stop script for Fingerprint Time Logger
# Updated to use containerized deployment

# Source common functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

setup_error_handling

# Configuration
SERVICE_NAME="fingerprint-time-logger"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

# Stop Docker Compose services
stop_docker_services() {
    log_info "Stopping Docker Compose services..."
    
    cd "$PROJECT_ROOT"
    
    # Use docker compose (newer) or docker-compose (legacy)
    local compose_cmd="docker compose"
    if ! docker compose version >/dev/null 2>&1; then
        compose_cmd="docker-compose"
    fi
    
    # Stop services
    if $compose_cmd down; then
        log_success "Docker services stopped successfully"
        return 0
    else
        log_error "Failed to stop Docker services cleanly"
        return 1
    fi
}

# Force cleanup if needed
force_cleanup() {
    log_warn "Attempting force cleanup..."
    
    # Stop container forcefully
    if docker ps --filter "name=$SERVICE_NAME" | grep -q "$SERVICE_NAME"; then
        log_info "Force stopping container: $SERVICE_NAME"
        docker stop "$SERVICE_NAME" >/dev/null 2>&1 || true
        docker rm "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi
    
    # Clean up any orphaned containers
    local orphaned=$(docker ps -a --filter "name=$SERVICE_NAME" --format "{{.Names}}" 2>/dev/null || true)
    if [ -n "$orphaned" ]; then
        log_info "Cleaning up orphaned containers: $orphaned"
        echo "$orphaned" | xargs docker rm -f >/dev/null 2>&1 || true
    fi
    
    log_success "Force cleanup completed"
}

# Verify services are stopped
verify_stopped() {
    if docker ps --filter "name=$SERVICE_NAME" --filter "status=running" | grep -q "$SERVICE_NAME"; then
        return 1
    fi
    return 0
}

# Main execution
main() {
    echo "🛑 Fingerprint Time Logger - Stopping Docker Services"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📁 Project Root: $PROJECT_ROOT"
    echo ""
    
    # Check if services are running
    if ! docker ps --filter "name=$SERVICE_NAME" --filter "status=running" | grep -q "$SERVICE_NAME"; then
        log_info "No running services found"
        log_success "System is already stopped"
        echo ""
        echo "📋 Management Commands:"
        echo "   Start:   ./scripts/start.sh"
        echo "   Status:  ./scripts/status.sh"
        echo "   Restart: ./scripts/restart.sh"
        echo ""
        exit 0
    fi
    
    # Stop services
    local stop_success=false
    if stop_docker_services; then
        stop_success=true
    fi
    
    # Verify services stopped
    if verify_stopped; then
        if [ "$stop_success" = true ]; then
            log_success "All services stopped successfully"
        else
            log_success "Services are now stopped"
        fi
    else
        log_warn "Some services may still be running, attempting force cleanup..."
        force_cleanup
        
        if verify_stopped; then
            log_success "Force cleanup successful, all services stopped"
        else
            log_error "Some services may still be running"
            log_info "Check with: docker ps --filter 'name=$SERVICE_NAME'"
        fi
    fi
    
    echo ""
    echo "📋 Management Commands:"
    echo "   Start:   ./scripts/start.sh"
    echo "   Status:  ./scripts/status.sh"
    echo "   Restart: ./scripts/restart.sh"
    echo ""
    echo "🐳 Docker Commands:"
    echo "   View all containers: docker ps -a"
    echo "   Clean up images: docker system prune"
    echo ""
}

# Execute main function
main "$@"