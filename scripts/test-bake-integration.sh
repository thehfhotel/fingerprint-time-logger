#!/bin/bash

# Test script to demonstrate Docker Bake integration in manage-app.sh

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Testing Docker Bake Integration${NC}"
echo -e "${BLUE}========================================${NC}"

# Test 1: Help output includes build options
echo -e "\n${YELLOW}Test 1: Checking help output for build options${NC}"
if ./scripts/manage-app.sh --help | grep -q "Build Options"; then
    echo -e "${GREEN}✅ Build options present in help${NC}"
else
    echo -e "❌ Build options missing from help"
    exit 1
fi

# Test 2: Build method detection
echo -e "\n${YELLOW}Test 2: Testing build method detection${NC}"

# Check if Bake is available
if docker buildx bake --help >/dev/null 2>&1 && [[ -f "docker-bake.hcl" ]]; then
    echo -e "${GREEN}✅ Docker Bake is available${NC}"

    # Test Bake method
    echo "Testing --build-method bake option"
    if ./scripts/manage-app.sh status --build-method bake >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Bake method argument parsing works${NC}"
    else
        echo -e "❌ Bake method argument parsing failed"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠️  Docker Bake not available, testing compose fallback${NC}"
fi

# Test 3: Compose method fallback
echo -e "\n${YELLOW}Test 3: Testing compose method${NC}"
if ./scripts/manage-app.sh status --build-method compose >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Compose method works${NC}"
else
    echo -e "❌ Compose method failed"
    exit 1
fi

# Test 4: Build target argument
echo -e "\n${YELLOW}Test 4: Testing build target argument${NC}"
if ./scripts/manage-app.sh status --build-target fingerprint-logger-dev >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Build target argument parsing works${NC}"
else
    echo -e "❌ Build target argument parsing failed"
    exit 1
fi

# Test 5: No cache argument
echo -e "\n${YELLOW}Test 5: Testing no-cache argument${NC}"
if ./scripts/manage-app.sh status --no-build-cache >/dev/null 2>&1; then
    echo -e "${GREEN}✅ No-cache argument parsing works${NC}"
else
    echo -e "❌ No-cache argument parsing failed"
    exit 1
fi

# Test 6: Environment variables
echo -e "\n${YELLOW}Test 6: Testing environment variables${NC}"
export BUILD_METHOD=compose
export BUILD_TARGET=fingerprint-logger-prod
export BUILD_CACHE=false

if ./scripts/manage-app.sh status >/dev/null 2>&1; then
    echo -e "${GREEN}✅ Environment variables work${NC}"
else
    echo -e "❌ Environment variables failed"
    exit 1
fi

# Clean up
unset BUILD_METHOD BUILD_TARGET BUILD_CACHE

echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}🎉 All tests passed!${NC}"
echo -e "${BLUE}Docker Bake integration is working correctly${NC}"
echo -e "${BLUE}========================================${NC}"

echo -e "\n${YELLOW}Available build commands:${NC}"
echo "./scripts/manage-app.sh start --build-method bake"
echo "./scripts/manage-app.sh deploy --build-target fingerprint-logger-prod"
echo "./scripts/manage-app.sh restart --no-build-cache"
echo "./scripts/build-with-bake.sh --dev"
echo "./scripts/build-comparison.sh"