# Scripts Directory

This directory contains utility scripts for development, testing, and operations.

## Testing Scripts

### `test_device_connection.py`
Basic connectivity test for ZKTeco devices.

```bash
python scripts/test_device_connection.py <IP_ADDRESS>
```

### `display_attendance.py`
Retrieve and display attendance data from device.

```bash
python scripts/display_attendance.py <IP_ADDRESS> [-d DAYS]
```

### `debug_data.py`
Debug script for data analysis and troubleshooting.

```bash
python scripts/debug_data.py
```

## Dashboard Management Scripts

### `start_dashboard.sh`
Start the Flask dashboard in background.

```bash
./scripts/start_dashboard.sh
```

### `stop_dashboard.sh`
Stop the running dashboard process.

```bash
./scripts/stop_dashboard.sh
```

### `restart_dashboard.sh`
Restart the dashboard (stop + start).

```bash
./scripts/restart_dashboard.sh
```

### `check_status.sh`
Check status of dashboard and API services.

```bash
./scripts/check_status.sh
```

## Performance Scripts

### `performance_summary.sh`
Generate performance metrics and system status.

```bash
./scripts/performance_summary.sh
```

## Usage Notes

- Make sure scripts are executable: `chmod +x scripts/*.sh`
- All Python scripts should be run from the project root directory
- Check script dependencies before running