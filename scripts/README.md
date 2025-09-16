# Scripts Directory

This directory contains utility scripts for managing the Fingerprint Time Logger application.

## Consolidated Scripts (Primary)

### Application Management
- **`manage-app.sh`** - **Interactive application lifecycle management**
  - **Interactive Mode**: Run without arguments for guided menu
  - **Command Mode**: Traditional command-line interface
  - Functions: `start`, `stop`, `restart`, `status`, `health`, `logs`, `deploy`, `backup`

### Testing & Verification
- **`test-verify.sh`** - **Interactive testing and quality verification**
  - **Interactive Mode**: Run without arguments for guided menu with configuration
  - **Command Mode**: Traditional command-line interface
  - **Configuration**: Interactive settings for coverage, browser, parallel execution
  - Functions: `all`, `unit`, `integration`, `e2e`, `security`, `quality`, `performance`, `setup`, `report`

## Specialized Scripts

### Utilities
- **`display_attendance.py`** - Display formatted attendance records

### Support Directories
- **`lib/common.sh`** - Shared functions for scripts
- **`archive/`** - Legacy scripts maintained for reference

## Usage Examples

```bash
# Interactive Mode (NEW) - Run without arguments for guided menus
./scripts/manage-app.sh                 # Interactive application management
./scripts/test-verify.sh                # Interactive testing with configuration

# Command Mode (Traditional) - Direct commands for automation
./scripts/manage-app.sh start           # Start application
./scripts/manage-app.sh status          # Check comprehensive status
./scripts/manage-app.sh backup          # Backup database
./scripts/manage-app.sh deploy          # Deploy with fresh build

./scripts/test-verify.sh setup                 # Setup testing infrastructure
./scripts/test-verify.sh all                   # Complete test suite
./scripts/test-verify.sh unit --coverage 85    # Unit tests with coverage
./scripts/test-verify.sh e2e --browser firefox # E2E tests with Firefox
./scripts/test-verify.sh quality               # Code quality checks
./scripts/test-verify.sh all --parallel        # All tests in parallel
```

## Script Organization

```
scripts/
├── manage-app.sh           # 🎯 Application lifecycle management
├── test-verify.sh          # 🧪 Testing and quality verification (enhanced)
├── display_attendance.py   # 📊 Utility scripts
├── lib/common.sh           # 📚 Shared functions
└── archive/                # 📦 Legacy scripts (archived)
    ├── run_e2e_tests.sh        # (Legacy E2E framework)
    ├── setup_enhanced_testing.sh # (Legacy setup script)
    └── [other legacy scripts]
```

## Application Access

After starting with `./scripts/manage-app.sh start`:

- **Dashboard**: http://localhost:5000
- **API Documentation**: http://localhost:5000/docs
- **System Status**: http://localhost:5000/status
- **Health Check**: http://localhost:5000/health

## Migration from Legacy Scripts

Old scripts have been consolidated but archived for reference:

| Legacy Script | New Command |
|---------------|-------------|
| `start.sh` | `./scripts/manage-app.sh start` |
| `stop.sh` | `./scripts/manage-app.sh stop` |
| `restart.sh` | `./scripts/manage-app.sh restart` |
| `status.sh` | `./scripts/manage-app.sh status` |
| `health.sh` | `./scripts/manage-app.sh health` |
| `run_tests.sh` | `./scripts/test-verify.sh all` |
| `test_status.sh` | `./scripts/test-verify.sh report` |
| `run_e2e_tests.sh` | `./scripts/test-verify.sh e2e` |
| `setup_enhanced_testing.sh` | `./scripts/test-verify.sh setup` |

## Health Check Exit Codes

- `0` = Healthy/Success
- `1` = Partial Issues/Warnings
- `2` = Critical Failures

## Test Reporting

The consolidated testing script generates comprehensive reports:

- **HTML Reports**: `reports/test-summary.html` (main report)
- **Unit Coverage**: `reports/unit/coverage/index.html`
- **E2E Results**: `tests/e2e/reports/`
- **Quality Reports**: `reports/quality/`

## Database & Files

- **Database**: `database/attendance.db`
- **Backups**: `backups/` (created by backup command)
- **Logs**: Docker container logs (accessed via `manage-app.sh logs`)
- **Reports**: `reports/` (test results and coverage)

## Troubleshooting

```bash
# Check application status
./scripts/manage-app.sh status

# View recent logs
./scripts/manage-app.sh logs

# Health check with details
./scripts/manage-app.sh health

# Run diagnostics
./scripts/test-verify.sh all

# Test device connectivity
python3 scripts/display_attendance.py

# Force restart
./scripts/manage-app.sh stop && ./scripts/manage-app.sh start
```

## Advanced Configuration

### Environment Variables

**Application Management:**
- `SERVICE_NAME` - Docker service name (default: fingerprint-time-logger)
- `PORT` - Application port (default: 5000)
- `MAX_HEALTH_RETRIES` - Health check retry count (default: 30)

**Testing & Verification:**
- `COVERAGE_THRESHOLD` - Coverage threshold percentage (default: 80)
- `BROWSER` - Browser for E2E tests (default: chromium)
- `APP_URL` - Application URL for testing (default: http://localhost:5000)
- `PARALLEL` - Enable parallel execution (default: false)

### Script Options

```bash
# Application management options
./scripts/manage-app.sh start --no-build    # Start without rebuilding
./scripts/manage-app.sh deploy --force      # Force deploy without checks

# Testing options
./scripts/test-verify.sh all --coverage 90 --parallel --browser firefox
./scripts/test-verify.sh e2e --app-url http://localhost:8000
```