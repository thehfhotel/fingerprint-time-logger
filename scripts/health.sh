#!/bin/bash

# Fingerprint Time Logger - Quick Health Check
# Fast health check script suitable for monitoring and automated checks

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS_DIR="$PROJECT_ROOT/pids"
API_PORT=8000
DASHBOARD_PORT=5000
API_PID_FILE="$PIDS_DIR/api.pid"
DASHBOARD_PID_FILE="$PIDS_DIR/dashboard.pid"

# Exit codes
EXIT_OK=0
EXIT_WARNING=1
EXIT_CRITICAL=2

# Counters
HEALTHY_SERVICES=0
TOTAL_SERVICES=2

# Function to check service health
check_service_health() {
    local pid_file=$1
    local port=$2
    local service_name=$3
    
    # Check if PID file exists and process is running
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        
        if kill -0 "$pid" 2>/dev/null; then
            # Process is running, check HTTP endpoint
            if curl -s -f "http://localhost:$port/health" >/dev/null 2>&1 || \
               curl -s -f "http://localhost:$port/" >/dev/null 2>&1; then
                echo -e "${GREEN}✅ $service_name: Healthy${NC}"
                ((HEALTHY_SERVICES++))
                return 0
            else
                echo -e "${YELLOW}⚠️  $service_name: Running but not responding${NC}"
                return 1
            fi
        else
            echo -e "${RED}❌ $service_name: Process not running${NC}"
            return 1
        fi
    else
        echo -e "${RED}❌ $service_name: Not started${NC}"
        return 1
    fi
}

# Quick mode (just exit codes, no output)
if [ "$1" = "--quiet" ] || [ "$1" = "-q" ]; then
    # Silent health check
    api_healthy=0
    dashboard_healthy=0
    
    # Check API
    if [ -f "$API_PID_FILE" ]; then
        pid=$(cat "$API_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            if curl -s -f "http://localhost:$API_PORT/health" >/dev/null 2>&1; then
                api_healthy=1
            fi
        fi
    fi
    
    # Check Dashboard
    if [ -f "$DASHBOARD_PID_FILE" ]; then
        pid=$(cat "$DASHBOARD_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            if curl -s -f "http://localhost:$DASHBOARD_PORT/" >/dev/null 2>&1; then
                dashboard_healthy=1
            fi
        fi
    fi
    
    # Exit with appropriate code
    if [ $api_healthy -eq 1 ] && [ $dashboard_healthy -eq 1 ]; then
        exit $EXIT_OK
    elif [ $api_healthy -eq 1 ] || [ $dashboard_healthy -eq 1 ]; then
        exit $EXIT_WARNING
    else
        exit $EXIT_CRITICAL
    fi
fi

# Normal mode with output
echo "🏥 Quick Health Check - $(date '+%H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check services
check_service_health "$API_PID_FILE" "$API_PORT" "API Server"
check_service_health "$DASHBOARD_PID_FILE" "$DASHBOARD_PORT" "Dashboard"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Summary
if [ $HEALTHY_SERVICES -eq $TOTAL_SERVICES ]; then
    echo -e "${GREEN}🎉 System Status: All services healthy ($HEALTHY_SERVICES/$TOTAL_SERVICES)${NC}"
    exit $EXIT_OK
elif [ $HEALTHY_SERVICES -gt 0 ]; then
    echo -e "${YELLOW}⚠️  System Status: Partial ($HEALTHY_SERVICES/$TOTAL_SERVICES services healthy)${NC}"
    exit $EXIT_WARNING
else
    echo -e "${RED}💥 System Status: Critical (no services healthy)${NC}"
    exit $EXIT_CRITICAL
fi