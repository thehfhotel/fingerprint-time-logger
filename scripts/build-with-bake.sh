#!/bin/bash

# Build script using Docker Bake for enhanced performance
# Provides better caching, parallelization, and build optimization

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=====================================${NC}"
echo -e "${BLUE}DOCKER BAKE BUILD - FINGERPRINT LOGGER${NC}"
echo -e "${BLUE}=====================================${NC}"

# Default values
BUILD_TARGET="fingerprint-logger"
BUILD_PLATFORM="linux/amd64"
BUILD_CACHE=${BUILD_CACHE:-true}
BUILD_PARALLEL=${BUILD_PARALLEL:-true}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --target)
            BUILD_TARGET="$2"
            shift 2
            ;;
        --dev)
            BUILD_TARGET="fingerprint-logger-dev"
            shift
            ;;
        --prod)
            BUILD_TARGET="fingerprint-logger-prod"
            shift
            ;;
        --no-cache)
            BUILD_CACHE=false
            shift
            ;;
        --platform)
            BUILD_PLATFORM="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --target TARGET     Build specific target (default: fingerprint-logger)"
            echo "  --dev              Build development target"
            echo "  --prod             Build production target"
            echo "  --no-cache         Disable build cache"
            echo "  --platform PLATFORM Set build platform (default: linux/amd64)"
            echo "  --help             Show this help message"
            echo ""
            echo "Available targets:"
            echo "  fingerprint-logger     Main application (default)"
            echo "  fingerprint-logger-dev Development with tools"
            echo "  fingerprint-logger-prod Production optimized"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

echo -e "${YELLOW}Build Configuration:${NC}"
echo -e "  Target: ${BUILD_TARGET}"
echo -e "  Platform: ${BUILD_PLATFORM}"
echo -e "  Cache: ${BUILD_CACHE}"
echo -e "  Parallel: ${BUILD_PARALLEL}"
echo ""

# Check if docker buildx bake is available
if ! docker buildx bake --help > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Docker Buildx with Bake support is not available${NC}"
    echo "Please ensure Docker Buildx is installed and properly configured"
    exit 1
fi

# Verify docker-bake.hcl exists
if [[ ! -f "docker-bake.hcl" ]]; then
    echo -e "${RED}ERROR: docker-bake.hcl not found${NC}"
    echo "Please ensure you're running this script from the project root"
    exit 1
fi

# Build command construction
BAKE_ARGS=""

# Set platform if specified
if [[ -n "$BUILD_PLATFORM" ]]; then
    BAKE_ARGS="$BAKE_ARGS --set *.platform=$BUILD_PLATFORM"
fi

# Handle cache settings
if [[ "$BUILD_CACHE" == "false" ]]; then
    BAKE_ARGS="$BAKE_ARGS --no-cache"
fi

# Build with timing
echo -e "${BLUE}Starting Bake build...${NC}"
START_TIME=$(date +%s)

# Execute build with error handling
if docker buildx bake $BAKE_ARGS $BUILD_TARGET; then
    END_TIME=$(date +%s)
    BUILD_TIME=$((END_TIME - START_TIME))

    echo ""
    echo -e "${GREEN}=====================================${NC}"
    echo -e "${GREEN}BUILD COMPLETED SUCCESSFULLY${NC}"
    echo -e "${GREEN}=====================================${NC}"
    echo -e "${GREEN}Build time: ${BUILD_TIME} seconds${NC}"
    echo -e "${GREEN}Target: ${BUILD_TARGET}${NC}"

    # Show image information
    if docker images fingerprint-logger:latest --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}" 2>/dev/null; then
        echo ""
        echo -e "${BLUE}Image Information:${NC}"
        docker images fingerprint-logger:latest --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
    fi

else
    echo ""
    echo -e "${RED}=====================================${NC}"
    echo -e "${RED}BUILD FAILED${NC}"
    echo -e "${RED}=====================================${NC}"
    exit 1
fi

# Performance tips
echo ""
echo -e "${YELLOW}Performance Tips:${NC}"
echo "• Use --dev for development builds with additional tools"
echo "• Use --prod for optimized production builds"
echo "• Enable registry cache for team builds:"
echo "  export BUILDX_CACHE_TO=type=registry,ref=your-registry/fingerprint-logger:cache"
echo "• Use BuildKit for faster builds:"
echo "  export DOCKER_BUILDKIT=1"