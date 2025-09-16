#!/bin/bash

# Fingerprint Time Logger Testing and Verification Script
# Consolidates all testing operations: unit tests, E2E tests, security tests, quality checks

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APP_URL="${APP_URL:-http://localhost:5000}"
COVERAGE_THRESHOLD=80
BROWSER="${BROWSER:-chromium}"
PARALLEL="${PARALLEL:-false}"

# Test result tracking
UNIT_TESTS_PASSED=false
INTEGRATION_TESTS_PASSED=false
E2E_TESTS_PASSED=false
SECURITY_TESTS_PASSED=false
QUALITY_CHECKS_PASSED=false

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
    echo -e "${CYAN}=================================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}=================================================${NC}"
}

log_section() {
    echo -e "${PURPLE}--- $1 ---${NC}"
}

# Prerequisites check
check_prerequisites() {
    log_info "Checking test prerequisites..."

    # Check Python virtual environment
    if [[ "$VIRTUAL_ENV" == "" ]]; then
        if [[ -d "$PROJECT_ROOT/venv" ]]; then
            log_info "Activating virtual environment..."
            # shellcheck source=/dev/null
            source "$PROJECT_ROOT/venv/bin/activate"
        else
            log_error "No virtual environment found. Please activate venv or create one."
            exit 1
        fi
    fi

    # Check required packages
    local missing_packages=()

    if ! python -c "import pytest" 2>/dev/null; then
        missing_packages+=("pytest")
    fi

    if ! python -c "import coverage" 2>/dev/null; then
        missing_packages+=("coverage")
    fi

    if [[ ${#missing_packages[@]} -gt 0 ]]; then
        log_error "Missing required packages: ${missing_packages[*]}"
        log_info "Install with: pip install -r requirements.txt"
        exit 1
    fi

    log_success "Prerequisites check completed"
}

# Application availability check
check_application() {
    log_info "Checking application availability for E2E tests..."

    local max_attempts=10
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        if curl -s "$APP_URL/health" >/dev/null 2>&1; then
            log_success "Application is available at $APP_URL"
            return 0
        fi

        log_info "Attempt $attempt/$max_attempts: Application not ready, waiting..."
        sleep 2
        ((attempt++))
    done

    log_warning "Application not available at $APP_URL"
    log_info "E2E tests will be skipped. Start the application first with:"
    log_info "  ./scripts/manage-app.sh start"
    return 1
}

# Unit tests
run_unit_tests() {
    log_header "RUNNING UNIT TESTS"

    log_info "Starting unit test execution with coverage..."

    # Create reports directory
    mkdir -p "$PROJECT_ROOT/reports/unit"

    local pytest_args=(
        "tests/"
        "--ignore=tests/e2e"
        "--ignore=tests/security"
        "--ignore=tests/performance"
        "-v"
        "--tb=short"
        "--cov=app"
        "--cov-report=html:reports/unit/coverage"
        "--cov-report=xml:reports/unit/coverage.xml"
        "--cov-report=json:reports/unit/coverage.json"
        "--cov-report=term-missing"
        "--cov-fail-under=$COVERAGE_THRESHOLD"
        "--html=reports/unit/report.html"
        "--self-contained-html"
        "--json-report"
        "--json-report-file=reports/unit/report.json"
        "--maxfail=10"
    )

    log_section "Unit Tests Configuration"
    log_info "Coverage threshold: $COVERAGE_THRESHOLD%"
    log_info "Test discovery: tests/ (excluding e2e, security, performance)"
    log_info "Reports: reports/unit/"

    if python -m pytest "${pytest_args[@]}"; then
        log_success "Unit tests passed"
        UNIT_TESTS_PASSED=true

        # Parse coverage
        if [[ -f "reports/unit/coverage.xml" ]]; then
            local coverage
            coverage=$(python -c "
import xml.etree.ElementTree as ET
tree = ET.parse('reports/unit/coverage.xml')
root = tree.getroot()
print(f'{float(root.attrib[\"line-rate\"]) * 100:.1f}')
" 2>/dev/null || echo "Unknown")

            log_info "Test coverage: $coverage%"
        fi
    else
        log_error "Unit tests failed"
        UNIT_TESTS_PASSED=false
        return 1
    fi
}

# Integration tests
run_integration_tests() {
    log_header "RUNNING INTEGRATION TESTS"

    log_info "Starting integration test execution..."

    # Create reports directory
    mkdir -p "$PROJECT_ROOT/reports/integration"

    local pytest_args=(
        "tests/integration/"
        "-v"
        "--tb=short"
        "--html=reports/integration/report.html"
        "--self-contained-html"
        "--json-report"
        "--json-report-file=reports/integration/report.json"
        "--maxfail=5"
    )

    log_section "Integration Tests Configuration"
    log_info "Test discovery: tests/integration/"
    log_info "Reports: reports/integration/"

    if python -m pytest "${pytest_args[@]}" 2>/dev/null; then
        log_success "Integration tests passed"
        INTEGRATION_TESTS_PASSED=true
    else
        log_warning "Integration tests failed or not found"
        INTEGRATION_TESTS_PASSED=false
    fi
}

# E2E tests
run_e2e_tests() {
    log_header "RUNNING E2E TESTS"

    # Check if application is available
    if ! check_application; then
        log_warning "Skipping E2E tests - application not available"
        return 0
    fi

    # Check if E2E framework exists
    if [[ ! -f "$PROJECT_ROOT/scripts/run_e2e_tests.sh" ]]; then
        log_warning "E2E test framework not found - skipping E2E tests"
        return 0
    fi

    log_info "Starting E2E test execution..."

    # Create reports directory
    mkdir -p "$PROJECT_ROOT/reports/e2e"

    log_section "E2E Tests Configuration"
    log_info "Browser: $BROWSER"
    log_info "Application URL: $APP_URL"
    log_info "Parallel execution: $PARALLEL"

    # Set E2E environment variables
    export BROWSER="$BROWSER"
    export APP_URL="$APP_URL"
    export HEADLESS="true"

    # Run E2E tests with different suites
    local e2e_success=true

    # Smoke tests (critical paths)
    log_section "Running smoke tests..."
    if "$PROJECT_ROOT/scripts/run_e2e_tests.sh" smoke; then
        log_success "E2E smoke tests passed"
    else
        log_error "E2E smoke tests failed"
        e2e_success=false
    fi

    # Workflow tests (if smoke tests pass)
    if [[ $e2e_success == true ]]; then
        log_section "Running workflow tests..."
        if "$PROJECT_ROOT/scripts/run_e2e_tests.sh" workflows; then
            log_success "E2E workflow tests passed"
        else
            log_error "E2E workflow tests failed"
            e2e_success=false
        fi
    fi

    if [[ $e2e_success == true ]]; then
        log_success "E2E tests completed successfully"
        E2E_TESTS_PASSED=true
    else
        log_error "E2E tests failed"
        E2E_TESTS_PASSED=false
        return 1
    fi
}

# Security tests
run_security_tests() {
    log_header "RUNNING SECURITY TESTS"

    # Check if security framework exists
    if [[ ! -d "$PROJECT_ROOT/tests/security" ]]; then
        log_warning "Security test framework not found - skipping security tests"
        return 0
    fi

    log_info "Starting security test execution..."

    # Create reports directory
    mkdir -p "$PROJECT_ROOT/reports/security"

    local pytest_args=(
        "tests/security/"
        "-v"
        "--tb=short"
        "--html=reports/security/report.html"
        "--self-contained-html"
        "--json-report"
        "--json-report-file=reports/security/report.json"
        "--maxfail=5"
    )

    log_section "Security Tests Configuration"
    log_info "Test discovery: tests/security/"
    log_info "Reports: reports/security/"

    if python -m pytest "${pytest_args[@]}" 2>/dev/null; then
        log_success "Security tests passed"
        SECURITY_TESTS_PASSED=true
    else
        log_warning "Security tests failed or encountered issues"
        SECURITY_TESTS_PASSED=false
    fi
}

# Quality checks
run_quality_checks() {
    log_header "RUNNING QUALITY CHECKS"

    log_info "Starting code quality analysis..."

    local quality_success=true

    # Create reports directory
    mkdir -p "$PROJECT_ROOT/reports/quality"

    # Code style checks
    log_section "Code Style Checks"
    if command -v flake8 >/dev/null 2>&1; then
        log_info "Running flake8..."
        if flake8 app/ --output-file=reports/quality/flake8.txt --tee 2>/dev/null; then
            log_success "Flake8 checks passed"
        else
            log_warning "Flake8 found style issues"
            quality_success=false
        fi
    else
        log_info "Flake8 not installed - skipping style checks"
    fi

    # Security analysis
    log_section "Security Analysis"
    if command -v bandit >/dev/null 2>&1; then
        log_info "Running bandit security analysis..."
        if bandit -r app/ -f json -o reports/quality/bandit.json >/dev/null 2>&1; then
            log_success "Bandit security analysis passed"
        else
            log_warning "Bandit found security issues"
            quality_success=false
        fi
    else
        log_info "Bandit not installed - skipping security analysis"
    fi

    # Dependency checks
    log_section "Dependency Security"
    if command -v safety >/dev/null 2>&1; then
        log_info "Running safety dependency check..."
        if safety check --json --output reports/quality/safety.json >/dev/null 2>&1; then
            log_success "Safety dependency check passed"
        else
            log_warning "Safety found vulnerable dependencies"
            quality_success=false
        fi
    else
        log_info "Safety not installed - skipping dependency checks"
    fi

    # Type checking
    log_section "Type Checking"
    if command -v mypy >/dev/null 2>&1; then
        log_info "Running mypy type checking..."
        if mypy app/ --ignore-missing-imports --json-report reports/quality/mypy >/dev/null 2>&1; then
            log_success "MyPy type checking passed"
        else
            log_warning "MyPy found type issues"
            quality_success=false
        fi
    else
        log_info "MyPy not installed - skipping type checking"
    fi

    if [[ $quality_success == true ]]; then
        log_success "Quality checks completed successfully"
        QUALITY_CHECKS_PASSED=true
    else
        log_warning "Some quality checks found issues"
        QUALITY_CHECKS_PASSED=false
    fi
}

# Performance tests
run_performance_tests() {
    log_header "RUNNING PERFORMANCE TESTS"

    # Check if performance tests exist
    if [[ ! -d "$PROJECT_ROOT/tests/performance" ]]; then
        log_warning "Performance tests not found - skipping"
        return 0
    fi

    log_info "Starting performance test execution..."

    # Create reports directory
    mkdir -p "$PROJECT_ROOT/reports/performance"

    local pytest_args=(
        "tests/performance/"
        "-v"
        "--tb=short"
        "--benchmark-only"
        "--benchmark-json=reports/performance/benchmark.json"
        "--html=reports/performance/report.html"
        "--self-contained-html"
    )

    if python -m pytest "${pytest_args[@]}" 2>/dev/null; then
        log_success "Performance tests completed"
    else
        log_warning "Performance tests failed or not found"
    fi
}

# Generate comprehensive report
generate_report() {
    log_header "GENERATING TEST REPORT"

    local report_file="$PROJECT_ROOT/reports/test-summary.html"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Calculate overall score
    local passed_count=0
    local total_count=5

    [[ $UNIT_TESTS_PASSED == true ]] && ((passed_count++))
    [[ $INTEGRATION_TESTS_PASSED == true ]] && ((passed_count++))
    [[ $E2E_TESTS_PASSED == true ]] && ((passed_count++))
    [[ $SECURITY_TESTS_PASSED == true ]] && ((passed_count++))
    [[ $QUALITY_CHECKS_PASSED == true ]] && ((passed_count++))

    local success_rate=$((passed_count * 100 / total_count))

    cat > "$report_file" << EOF
<!DOCTYPE html>
<html>
<head>
    <title>Fingerprint Time Logger - Test Report</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .header { text-align: center; border-bottom: 2px solid #007bff; padding-bottom: 20px; margin-bottom: 30px; }
        .success { color: #28a745; }
        .warning { color: #ffc107; }
        .error { color: #dc3545; }
        .score { font-size: 48px; font-weight: bold; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }
        .card { background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid #007bff; }
        .card.success { border-left-color: #28a745; }
        .card.warning { border-left-color: #ffc107; }
        .card.error { border-left-color: #dc3545; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧪 Test Execution Report</h1>
            <p><strong>Generated:</strong> $timestamp</p>
            <div class="score $([ $success_rate -ge 80 ] && echo "success" || echo "warning")">$success_rate%</div>
            <p>Overall Success Rate</p>
        </div>

        <div class="grid">
            <div class="card $([ $UNIT_TESTS_PASSED == true ] && echo "success" || echo "error")">
                <h3>📋 Unit Tests</h3>
                <p>Status: $([ $UNIT_TESTS_PASSED == true ] && echo "✅ PASSED" || echo "❌ FAILED")</p>
                <p>Coverage threshold: $COVERAGE_THRESHOLD%</p>
                <a href="unit/coverage/index.html">Coverage Report</a> |
                <a href="unit/report.html">Test Report</a>
            </div>

            <div class="card $([ $INTEGRATION_TESTS_PASSED == true ] && echo "success" || echo "warning")">
                <h3>🔗 Integration Tests</h3>
                <p>Status: $([ $INTEGRATION_TESTS_PASSED == true ] && echo "✅ PASSED" || echo "⚠️ SKIPPED/FAILED")</p>
                <a href="integration/report.html">Test Report</a>
            </div>

            <div class="card $([ $E2E_TESTS_PASSED == true ] && echo "success" || echo "warning")">
                <h3>🖥️ E2E Tests</h3>
                <p>Status: $([ $E2E_TESTS_PASSED == true ] && echo "✅ PASSED" || echo "⚠️ SKIPPED/FAILED")</p>
                <p>Browser: $BROWSER</p>
                <a href="../tests/e2e/reports/">E2E Reports</a>
            </div>

            <div class="card $([ $SECURITY_TESTS_PASSED == true ] && echo "success" || echo "warning")">
                <h3>🔒 Security Tests</h3>
                <p>Status: $([ $SECURITY_TESTS_PASSED == true ] && echo "✅ PASSED" || echo "⚠️ SKIPPED/FAILED")</p>
                <a href="security/report.html">Security Report</a>
            </div>

            <div class="card $([ $QUALITY_CHECKS_PASSED == true ] && echo "success" || echo "warning")">
                <h3>🏆 Quality Checks</h3>
                <p>Status: $([ $QUALITY_CHECKS_PASSED == true ] && echo "✅ PASSED" || echo "⚠️ ISSUES FOUND")</p>
                <a href="quality/">Quality Reports</a>
            </div>
        </div>

        <div style="margin-top: 30px; padding: 20px; background: #e9ecef; border-radius: 8px;">
            <h3>📊 Summary</h3>
            <p><strong>Test Categories:</strong> $passed_count/$total_count passed</p>
            <p><strong>Success Rate:</strong> $success_rate%</p>
            <p><strong>Recommendation:</strong>
            $([ $success_rate -ge 90 ] && echo "Excellent - Ready for deployment" ||
              [ $success_rate -ge 80 ] && echo "Good - Minor issues to address" ||
              [ $success_rate -ge 60 ] && echo "Acceptable - Review failures before deployment" ||
              echo "Needs attention - Significant issues to resolve")</p>
        </div>
    </div>
</body>
</html>
EOF

    log_success "Test report generated: $report_file"
    log_info "Open in browser: file://$report_file"
}

# Show usage
show_usage() {
    cat << EOF
Fingerprint Time Logger - Testing and Verification Script

Usage: $0 <command> [options]

Commands:
    all             Run all tests and checks
    unit            Run unit tests only
    integration     Run integration tests only
    e2e             Run E2E tests only
    security        Run security tests only
    quality         Run quality checks only
    performance     Run performance tests only
    report          Generate comprehensive test report
    help            Show this help message

Options:
    --coverage N    Set coverage threshold (default: 80)
    --browser NAME  Set browser for E2E tests (default: chromium)
    --parallel      Run tests in parallel where possible
    --app-url URL   Set application URL for E2E tests (default: http://localhost:5000)

Examples:
    $0 all                           # Run complete test suite
    $0 unit --coverage 85            # Unit tests with 85% coverage
    $0 e2e --browser firefox         # E2E tests with Firefox
    $0 quality                       # Code quality checks only
    $0 all --parallel               # All tests with parallel execution

Environment Variables:
    COVERAGE_THRESHOLD    # Coverage threshold percentage
    BROWSER              # Browser for E2E tests
    APP_URL              # Application URL for testing
    PARALLEL             # Enable parallel execution

EOF
}

# Main execution
main() {
    local command="${1:-help}"

    # Parse options
    while [[ $# -gt 0 ]]; do
        case $1 in
            --coverage)
                COVERAGE_THRESHOLD="$2"
                shift 2
                ;;
            --browser)
                BROWSER="$2"
                shift 2
                ;;
            --parallel)
                PARALLEL="true"
                shift
                ;;
            --app-url)
                APP_URL="$2"
                shift 2
                ;;
            *)
                if [[ "$1" != "$command" ]]; then
                    log_error "Unknown option: $1"
                    show_usage
                    exit 1
                fi
                shift
                ;;
        esac
    done

    # Create reports directory
    mkdir -p "$PROJECT_ROOT/reports"

    # Change to project root
    cd "$PROJECT_ROOT"

    case "$command" in
        all)
            check_prerequisites
            run_unit_tests
            run_integration_tests
            run_e2e_tests
            run_security_tests
            run_quality_checks
            run_performance_tests
            generate_report
            ;;
        unit)
            check_prerequisites
            run_unit_tests
            ;;
        integration)
            check_prerequisites
            run_integration_tests
            ;;
        e2e)
            check_prerequisites
            run_e2e_tests
            ;;
        security)
            check_prerequisites
            run_security_tests
            ;;
        quality)
            check_prerequisites
            run_quality_checks
            ;;
        performance)
            check_prerequisites
            run_performance_tests
            ;;
        report)
            generate_report
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            log_error "Unknown command: $command"
            show_usage
            exit 1
            ;;
    esac

    # Final status
    if [[ "$command" == "all" ]]; then
        local exit_code=0

        if [[ $UNIT_TESTS_PASSED != true ]]; then
            exit_code=1
        fi

        log_header "FINAL RESULTS"
        log_info "Unit Tests: $([ $UNIT_TESTS_PASSED == true ] && echo "✅ PASSED" || echo "❌ FAILED")"
        log_info "Integration Tests: $([ $INTEGRATION_TESTS_PASSED == true ] && echo "✅ PASSED" || echo "⚠️ SKIPPED")"
        log_info "E2E Tests: $([ $E2E_TESTS_PASSED == true ] && echo "✅ PASSED" || echo "⚠️ SKIPPED")"
        log_info "Security Tests: $([ $SECURITY_TESTS_PASSED == true ] && echo "✅ PASSED" || echo "⚠️ SKIPPED")"
        log_info "Quality Checks: $([ $QUALITY_CHECKS_PASSED == true ] && echo "✅ PASSED" || echo "⚠️ ISSUES")"

        if [[ $exit_code -eq 0 ]]; then
            log_success "All critical tests passed!"
        else
            log_error "Some critical tests failed - review results"
        fi

        exit $exit_code
    fi
}

# Run main function with all arguments
main "$@"