#!/bin/bash

# Build performance comparison script
# Compares standard Docker Compose build vs Docker Bake build

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}DOCKER BUILD PERFORMANCE COMPARISON${NC}"
echo -e "${CYAN}Standard Docker Compose vs Docker Bake${NC}"
echo -e "${CYAN}================================================${NC}"

# Function to run build and measure time
run_build() {
    local build_type=$1
    local build_command=$2

    echo -e "\n${BLUE}Testing: ${build_type}${NC}"
    echo -e "${YELLOW}Command: ${build_command}${NC}"
    echo -e "$(date '+%Y-%m-%d %H:%M:%S') - Starting build..."

    local start_time=$(date +%s.%N)

    # Run the build command
    eval $build_command > /tmp/build_output_$$.log 2>&1
    local build_status=$?

    local end_time=$(date +%s.%N)
    local build_time=$(echo "$end_time - $start_time" | bc -l)

    if [ $build_status -eq 0 ]; then
        echo -e "${GREEN}✅ Build successful in ${build_time}s${NC}"
        echo "$build_time"
    else
        echo -e "${RED}❌ Build failed${NC}"
        echo "Build output saved to: /tmp/build_output_$$.log"
        echo "0"
    fi
}

# Cleanup function
cleanup() {
    echo -e "\n${BLUE}Cleaning up...${NC}"
    docker system prune -f --filter "label=stage=intermediate" > /dev/null 2>&1 || true
    rm -f /tmp/build_output_$$.log
}

# Set trap for cleanup
trap cleanup EXIT

# Ensure we're in the right directory
if [[ ! -f "docker-compose.yml" || ! -f "docker-bake.hcl" ]]; then
    echo -e "${RED}ERROR: Please run this script from the project root directory${NC}"
    exit 1
fi

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"

if ! command -v bc &> /dev/null; then
    echo -e "${RED}ERROR: 'bc' calculator is required but not installed${NC}"
    echo "Install it with: sudo apt-get install bc"
    exit 1
fi

if ! docker buildx bake --help > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Docker Buildx with Bake support is not available${NC}"
    exit 1
fi

echo -e "${GREEN}✅ All prerequisites met${NC}"

# Prepare for clean builds
echo -e "\n${BLUE}Preparing for performance comparison...${NC}"
echo "This will perform clean builds (no cache) for accurate timing"

# Clean existing images to ensure fair comparison
echo "Removing existing images..."
docker rmi fingerprint-logger:latest > /dev/null 2>&1 || true
docker rmi fingerprint-time-logger:latest > /dev/null 2>&1 || true

# Run comparison tests
echo -e "\n${CYAN}=== PERFORMANCE COMPARISON ===${NC}"

# Test 1: Standard Docker Compose build
echo -e "\n${YELLOW}[Test 1/2] Standard Docker Compose Build${NC}"
compose_time=$(run_build "Docker Compose" "docker compose build --no-cache")

# Clean up between tests
docker rmi fingerprint-logger:latest > /dev/null 2>&1 || true

# Test 2: Docker Bake build
echo -e "\n${YELLOW}[Test 2/2] Docker Bake Build${NC}"
bake_time=$(run_build "Docker Bake" "docker buildx bake --no-cache fingerprint-logger")

# Calculate performance improvement
echo -e "\n${CYAN}=== RESULTS SUMMARY ===${NC}"

if [[ $(echo "$compose_time > 0" | bc -l) -eq 1 && $(echo "$bake_time > 0" | bc -l) -eq 1 ]]; then
    echo -e "Docker Compose Build Time: ${YELLOW}${compose_time}s${NC}"
    echo -e "Docker Bake Build Time:    ${YELLOW}${bake_time}s${NC}"

    # Calculate improvement
    improvement=$(echo "scale=1; ($compose_time - $bake_time) / $compose_time * 100" | bc -l)
    time_saved=$(echo "scale=2; $compose_time - $bake_time" | bc -l)

    if [[ $(echo "$improvement > 0" | bc -l) -eq 1 ]]; then
        echo -e "Performance Improvement:   ${GREEN}${improvement}% faster${NC}"
        echo -e "Time Saved:                ${GREEN}${time_saved}s${NC}"
    else
        # Handle case where Bake might be slower (rare, but possible)
        improvement_abs=$(echo "scale=1; ($improvement * -1)" | bc -l)
        echo -e "Performance Change:        ${RED}${improvement_abs}% slower${NC}"
    fi

    echo ""
    echo -e "${BLUE}Build Features Comparison:${NC}"
    echo "┌─────────────────────────┬─────────────────┬──────────────────┐"
    echo "│ Feature                 │ Docker Compose  │ Docker Bake      │"
    echo "├─────────────────────────┼─────────────────┼──────────────────┤"
    echo "│ Multi-stage builds      │ ✅ Yes          │ ✅ Yes           │"
    echo "│ Build caching           │ ✅ Basic        │ ✅ Advanced      │"
    echo "│ Parallel builds         │ ❌ No           │ ✅ Yes           │"
    echo "│ Multi-platform builds   │ ❌ Limited      │ ✅ Yes           │"
    echo "│ Build customization     │ ❌ Limited      │ ✅ Extensive     │"
    echo "│ Registry cache          │ ❌ No           │ ✅ Yes           │"
    echo "│ Build groups            │ ❌ No           │ ✅ Yes           │"
    echo "└─────────────────────────┴─────────────────┴──────────────────┘"

else
    echo -e "${RED}❌ Could not complete performance comparison due to build failures${NC}"
    echo "Check the build logs for detailed error information"
fi

echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "• Enable Bake in Docker Compose: Set COMPOSE_BAKE=true in .env"
echo "• Use build script: ./scripts/build-with-bake.sh"
echo "• For development: ./scripts/build-with-bake.sh --dev"
echo "• For production: ./scripts/build-with-bake.sh --prod"