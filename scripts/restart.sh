#!/bin/bash
set -e

# Fingerprint Time Logger - Unified Restart Script
# Safely restarts both API server and Dashboard with health verification

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESTART_DELAY=3

# Ensure we're in the project root
cd "$PROJECT_ROOT"

# Parse command line arguments
SERVICE_TO_RESTART="$1"  # Optional: "api", "dashboard", or empty for both
SKIP_HEALTH_CHECK="$2"   # Optional: "quick" to skip health checks

echo -e "${BLUE}🔄 Fingerprint Time Logger - Restarting Application${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${BLUE}📁 Project Root:${NC} $PROJECT_ROOT"
echo -e "${BLUE}🕐 Timestamp:${NC} $(date '+%Y-%m-%d %H:%M:%S')"

case "$SERVICE_TO_RESTART" in
    "api")
        echo -e "${BLUE}🔧 Restarting API Server only...${NC}"
        echo
        
        # Stop API Server
        echo -e "${YELLOW}🛑 Stopping API Server...${NC}"
        "$PROJECT_ROOT/scripts/stop.sh" api
        
        # Wait before restart
        echo -e "${YELLOW}⏳ Waiting $RESTART_DELAY seconds before restart...${NC}"
        sleep $RESTART_DELAY
        
        # Start API Server
        echo -e "${YELLOW}🚀 Starting API Server...${NC}"
        "$PROJECT_ROOT/scripts/start.sh"
        ;;
        
    "dashboard")
        echo -e "${BLUE}🖥️  Restarting Dashboard only...${NC}"
        echo
        
        # Stop Dashboard
        echo -e "${YELLOW}🛑 Stopping Dashboard...${NC}"
        "$PROJECT_ROOT/scripts/stop.sh" dashboard
        
        # Wait before restart
        echo -e "${YELLOW}⏳ Waiting $RESTART_DELAY seconds before restart...${NC}"
        sleep $RESTART_DELAY
        
        # Start Dashboard (this will also start API if not running)
        echo -e "${YELLOW}🚀 Starting Dashboard...${NC}"
        "$PROJECT_ROOT/scripts/start.sh"
        ;;
        
    "quick")
        echo -e "${BLUE}⚡ Quick restart (minimal health checks)...${NC}"
        echo
        
        # Stop all services
        echo -e "${YELLOW}🛑 Stopping all services...${NC}"
        "$PROJECT_ROOT/scripts/stop.sh"
        
        # Minimal wait
        echo -e "${YELLOW}⏳ Waiting 2 seconds...${NC}"
        sleep 2
        
        # Start all services
        echo -e "${YELLOW}🚀 Starting all services...${NC}"
        "$PROJECT_ROOT/scripts/start.sh"
        ;;
        
    *)
        echo -e "${BLUE}🔄 Full application restart...${NC}"
        echo
        
        # Show current status
        if [ "$SKIP_HEALTH_CHECK" != "quick" ]; then
            echo -e "${YELLOW}📊 Current status:${NC}"
            "$PROJECT_ROOT/scripts/status.sh" | head -20
            echo
        fi
        
        # Stop all services
        echo -e "${YELLOW}🛑 Stopping all services...${NC}"
        "$PROJECT_ROOT/scripts/stop.sh"
        
        # Wait before restart
        echo -e "${YELLOW}⏳ Waiting $RESTART_DELAY seconds before restart...${NC}"
        sleep $RESTART_DELAY
        
        # Start all services
        echo -e "${YELLOW}🚀 Starting all services...${NC}"
        "$PROJECT_ROOT/scripts/start.sh"
        ;;
esac

echo
echo -e "${GREEN}🎉 Restart operation completed!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Show post-restart status unless quick mode
if [ "$SKIP_HEALTH_CHECK" != "quick" ] && [ "$SERVICE_TO_RESTART" != "quick" ]; then
    echo -e "${BLUE}📊 Post-restart status:${NC}"
    echo
    "$PROJECT_ROOT/scripts/status.sh"
else
    echo -e "${YELLOW}💡 Run './scripts/status.sh' to check detailed status${NC}"
fi

echo
echo -e "${BLUE}💡 Available commands:${NC}"
echo -e "   Status:       ${YELLOW}./scripts/status.sh${NC}"
echo -e "   Stop:         ${YELLOW}./scripts/stop.sh${NC}"
echo -e "   Quick restart: ${YELLOW}./scripts/restart.sh quick${NC}"
echo