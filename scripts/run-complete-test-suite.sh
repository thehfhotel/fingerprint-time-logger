#!/bin/bash

# ============================================================================
# Complete Test Suite Runner
# ============================================================================
# Executes all tests (unit, integration, E2E) and generates comprehensive report
# Continues execution even on errors, capturing all results for analysis
#
# Usage:
#   ./scripts/run-complete-test-suite.sh
#   ./scripts/run-complete-test-suite.sh --parallel  # Run with pytest-xdist
#   ./scripts/run-complete-test-suite.sh --verbose   # Detailed output
#
# Output:
#   - Console: Real-time progress and summary
#   - File: test-reports/test-report-TIMESTAMP.txt
# ============================================================================

set +e  # Continue on errors

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPORT_DIR="$PROJECT_ROOT/test-reports"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORT_FILE="$REPORT_DIR/test-report-$TIMESTAMP.txt"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"

# Parse arguments
PARALLEL_FLAG=""
VERBOSE_FLAG=""
for arg in "$@"; do
    case $arg in
        --parallel)
            PARALLEL_FLAG="-n auto"
            ;;
        --verbose)
            VERBOSE_FLAG="-v"
            ;;
    esac
done

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Create report directory
mkdir -p "$REPORT_DIR"

# Initialize report
cat > "$REPORT_FILE" << EOF
================================================================================
FINGERPRINT TIME LOGGER - COMPLETE TEST SUITE REPORT
================================================================================
Generated: $(date +"%Y-%m-%d %H:%M:%S %Z")
Project: Fingerprint Time Logger
Test Runner: run-complete-test-suite.sh

EXECUTION SUMMARY:
--------------------------------------------------------------------------------
EOF

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     FINGERPRINT TIME LOGGER - COMPLETE TEST SUITE RUNNER              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Report will be saved to: $REPORT_FILE${NC}"
echo ""

# Function to run test category and capture results
run_test_category() {
    local category_name="$1"
    local test_path="$2"
    local additional_flags="$3"

    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Running: $category_name${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

    # Write category header to report
    cat >> "$REPORT_FILE" << EOF

================================================================================
$category_name
================================================================================
Test Path: $test_path
Start Time: $(date +"%H:%M:%S")

EOF

    # Run tests and capture output
    local temp_output=$(mktemp)
    $VENV_PYTHON -m pytest "$test_path" \
        $PARALLEL_FLAG \
        $VERBOSE_FLAG \
        --tb=short \
        -q \
        $additional_flags \
        2>&1 | tee "$temp_output"

    local exit_code=$?

    # Append results to report
    cat "$temp_output" >> "$REPORT_FILE"

    cat >> "$REPORT_FILE" << EOF

End Time: $(date +"%H:%M:%S")
Exit Code: $exit_code

EOF

    # Print summary
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✓ $category_name: PASSED${NC}"
    elif [ $exit_code -eq 5 ]; then
        echo -e "${YELLOW}⚠ $category_name: NO TESTS COLLECTED${NC}"
    else
        echo -e "${RED}✗ $category_name: FAILED (exit code: $exit_code)${NC}"
    fi

    rm -f "$temp_output"
    return $exit_code
}

# Track overall statistics
declare -A category_results
total_categories=0
passed_categories=0
failed_categories=0
skipped_categories=0

# ============================================================================
# PHASE 1: Unit Tests
# ============================================================================

echo -e "\n${YELLOW}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}PHASE 1: UNIT TESTS${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════${NC}"

cat >> "$REPORT_FILE" << EOF

################################################################################
#                              PHASE 1: UNIT TESTS                             #
################################################################################

EOF

# Unit Test Categories
run_test_category "Unit Tests: LINE Authentication Security" \
    "tests/unit/test_line_auth_security.py"
category_results["unit_line_auth_security"]=$?

run_test_category "Unit Tests: LINE Authentication Service" \
    "tests/unit/test_line_auth_service.py"
category_results["unit_line_auth_service"]=$?

run_test_category "Unit Tests: Timezone Handling" \
    "tests/unit/test_timezone_handling.py"
category_results["unit_timezone"]=$?

run_test_category "Unit Tests: Location Service" \
    "tests/unit/test_location_service.py"
category_results["unit_location"]=$?

run_test_category "Unit Tests: QR Service" \
    "tests/unit/test_qr_service.py"
category_results["unit_qr"]=$?

run_test_category "Unit Tests: Configuration" \
    "tests/unit/test_config.py"
category_results["unit_config"]=$?

run_test_category "Unit Tests: Cache Busting" \
    "tests/unit/test_cache_busting.py"
category_results["unit_cache"]=$?

run_test_category "Unit Tests: Admin LINE Codes" \
    "tests/unit/test_admin_line_codes.py"
category_results["unit_admin_codes"]=$?

run_test_category "Unit Tests: All Remaining Unit Tests" \
    "tests/unit/" \
    "--ignore=tests/unit/test_line_auth_security.py --ignore=tests/unit/test_line_auth_service.py --ignore=tests/unit/test_timezone_handling.py --ignore=tests/unit/test_location_service.py --ignore=tests/unit/test_qr_service.py --ignore=tests/unit/test_config.py --ignore=tests/unit/test_cache_busting.py --ignore=tests/unit/test_admin_line_codes.py"
category_results["unit_remaining"]=$?

# ============================================================================
# PHASE 2: Integration Tests
# ============================================================================

echo -e "\n${YELLOW}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}PHASE 2: INTEGRATION TESTS${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════${NC}"

cat >> "$REPORT_FILE" << EOF

################################################################################
#                          PHASE 2: INTEGRATION TESTS                          #
################################################################################

EOF

run_test_category "Integration Tests: Auto-Import Scheduler" \
    "tests/integration/test_auto_import_scheduler.py"
category_results["integration_auto_import"]=$?

run_test_category "Integration Tests: Multi-Office GPS" \
    "tests/integration/test_multi_office_gps.py"
category_results["integration_multi_office"]=$?

run_test_category "Integration Tests: QR Check-in API" \
    "tests/integration/test_qr_checkin_api.py"
category_results["integration_qr_api"]=$?

run_test_category "Integration Tests: QR Terminal Display" \
    "tests/integration/test_qr_terminal_display.py"
category_results["integration_qr_display"]=$?

run_test_category "Integration Tests: LINE Auth API" \
    "tests/integration/test_line_auth_api.py"
category_results["integration_line_api"]=$?

run_test_category "Integration Tests: All Remaining Integration Tests" \
    "tests/integration/" \
    "--ignore=tests/integration/test_auto_import_scheduler.py --ignore=tests/integration/test_multi_office_gps.py --ignore=tests/integration/test_qr_checkin_api.py --ignore=tests/integration/test_qr_terminal_display.py --ignore=tests/integration/test_line_auth_api.py"
category_results["integration_remaining"]=$?

# ============================================================================
# PHASE 3: E2E Tests (Browser Automation)
# ============================================================================

echo -e "\n${YELLOW}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}PHASE 3: E2E TESTS (Requires Running Application)${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════════════════════${NC}"

cat >> "$REPORT_FILE" << EOF

################################################################################
#                    PHASE 3: E2E TESTS (BROWSER AUTOMATION)                   #
################################################################################

Note: E2E tests require the application to be running on http://localhost:5000
If application is not running, these tests will be skipped or fail.

EOF

# Check if application is running
if curl -s -o /dev/null -w "%{http_code}" http://localhost:5000 | grep -q "200\|302"; then
    echo -e "${GREEN}✓ Application detected on http://localhost:5000${NC}\n"
    APP_RUNNING=true
else
    echo -e "${YELLOW}⚠ Application not detected on http://localhost:5000${NC}"
    echo -e "${YELLOW}  E2E tests will be attempted but may fail${NC}\n"
    APP_RUNNING=false
fi

run_test_category "E2E Tests: GPS Persistence" \
    "tests/e2e/test_gps_persistence.py"
category_results["e2e_gps"]=$?

run_test_category "E2E Tests: LINE Persistent Login" \
    "tests/e2e/test_line_persistent_login.py"
category_results["e2e_line_login"]=$?

run_test_category "E2E Tests: LINE OAuth Flow" \
    "tests/e2e/test_line_oauth_flow.py"
category_results["e2e_oauth"]=$?

run_test_category "E2E Tests: QR Terminal Real-time" \
    "tests/e2e/test_qr_terminal_realtime.py"
category_results["e2e_qr_realtime"]=$?

run_test_category "E2E Tests: All Remaining E2E Tests" \
    "tests/e2e/" \
    "--ignore=tests/e2e/test_gps_persistence.py --ignore=tests/e2e/test_line_persistent_login.py --ignore=tests/e2e/test_line_oauth_flow.py --ignore=tests/e2e/test_qr_terminal_realtime.py"
category_results["e2e_remaining"]=$?

# ============================================================================
# Generate Final Summary
# ============================================================================

echo -e "\n${BLUE}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}GENERATING FINAL REPORT${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════════════${NC}\n"

# Count results
for result in "${category_results[@]}"; do
    ((total_categories++))
    if [ $result -eq 0 ]; then
        ((passed_categories++))
    elif [ $result -eq 5 ]; then
        ((skipped_categories++))
    else
        ((failed_categories++))
    fi
done

# Calculate pass rate
if [ $total_categories -gt 0 ]; then
    pass_rate=$(echo "scale=1; $passed_categories * 100 / $total_categories" | bc)
else
    pass_rate=0
fi

# Generate summary section
cat >> "$REPORT_FILE" << EOF

================================================================================
FINAL SUMMARY
================================================================================
Generated: $(date +"%Y-%m-%d %H:%M:%S %Z")

OVERALL STATISTICS:
------------------
Total Test Categories: $total_categories
Passed Categories: $passed_categories
Failed Categories: $failed_categories
Skipped Categories: $skipped_categories
Pass Rate: ${pass_rate}%

CATEGORY BREAKDOWN:
------------------
EOF

# Add detailed breakdown
for category in "${!category_results[@]}"; do
    result=${category_results[$category]}
    if [ $result -eq 0 ]; then
        status="✓ PASSED"
    elif [ $result -eq 5 ]; then
        status="⊘ SKIPPED"
    else
        status="✗ FAILED (exit code: $result)"
    fi
    echo "$category: $status" >> "$REPORT_FILE"
done

cat >> "$REPORT_FILE" << EOF

================================================================================
RECOMMENDATIONS FOR CLAUDE AI:
================================================================================

1. REVIEW FAILED CATEGORIES:
   - Check test failures for root cause analysis
   - Identify if failures are test issues or code issues
   - Prioritize fixing critical path failures

2. E2E TEST STATUS:
EOF

if [ "$APP_RUNNING" = true ]; then
    echo "   - Application was running during E2E test execution" >> "$REPORT_FILE"
    echo "   - E2E test failures indicate real issues" >> "$REPORT_FILE"
else
    echo "   - Application was NOT running during E2E test execution" >> "$REPORT_FILE"
    echo "   - E2E test failures expected - start app and re-run" >> "$REPORT_FILE"
fi

cat >> "$REPORT_FILE" << EOF

3. TEST COVERAGE ANALYSIS:
   - Total categories tested: $total_categories
   - Coverage includes: Unit, Integration, E2E
   - Success rate: ${pass_rate}%

4. NEXT STEPS:
   - If pass rate < 90%: Investigate failures
   - If E2E failed: Ensure application running
   - If integration failed: Check database setup
   - If unit failed: Review recent code changes

================================================================================
END OF REPORT
================================================================================
EOF

# Display console summary
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                        FINAL TEST SUMMARY                              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Total Categories: ${BLUE}$total_categories${NC}"
echo -e "Passed: ${GREEN}$passed_categories${NC}"
echo -e "Failed: ${RED}$failed_categories${NC}"
echo -e "Skipped: ${YELLOW}$skipped_categories${NC}"
echo -e "Pass Rate: ${GREEN}${pass_rate}%${NC}"
echo ""
echo -e "${YELLOW}Detailed report saved to:${NC}"
echo -e "${BLUE}$REPORT_FILE${NC}"
echo ""

# Set exit code based on failures
if [ $failed_categories -gt 0 ]; then
    echo -e "${RED}⚠ Some test categories failed. Review the report for details.${NC}"
    exit 1
else
    echo -e "${GREEN}✓ All test categories passed!${NC}"
    exit 0
fi
