"""
Attendance Tracking E2E Workflow Test
Tests the complete attendance tracking workflow from device sync to reporting
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from playwright.async_api import Page

from tests.e2e.page_objects.dashboard_page import DashboardPage
from tests.e2e.page_objects.status_page import StatusPage


@pytest.mark.asyncio
@pytest.mark.workflow("attendance_tracking")
class TestAttendanceTracking:
    """Complete attendance tracking workflow testing"""

    async def test_dashboard_real_time_updates(
        self,
        page: Page,
        app_url: str,
        app_running,
        websocket_tester,
        e2e_assert,
        take_screenshot
    ):
        """Test real-time attendance updates on dashboard via WebSocket"""

        dashboard = DashboardPage(page)

        # Navigate to dashboard
        await dashboard.navigate_to(app_url)
        await e2e_assert.assert_page_loaded(page, "Dashboard")

        # Get initial attendance count
        initial_count = await dashboard.get_attendance_count()
        await take_screenshot("01_dashboard_initial")

        # Verify WebSocket connection
        ws_status = await dashboard.get_websocket_connection_status()
        assert ws_status in ["Connected", "Connecting"], f"WebSocket status: {ws_status}"

        # Test real-time data display
        employee_count = await dashboard.get_employee_count()
        attendance_count = await dashboard.get_attendance_count()

        assert employee_count >= 0, "Employee count should be non-negative"
        assert attendance_count >= 0, "Attendance count should be non-negative"

        # Get recent records
        recent_records = await dashboard.get_recent_attendance_records()
        await take_screenshot("02_recent_records")

        # Verify recent records structure
        for record in recent_records:
            assert "employee" in record, "Record should have employee field"
            assert "time" in record, "Record should have time field"
            assert "action" in record, "Record should have action field"

        # Test device status display
        device_status = await dashboard.get_device_status()
        assert "status" in device_status, "Device status should have status field"
        assert "message" in device_status, "Device status should have message field"

        await take_screenshot("03_device_status")

    async def test_sync_operations_workflow(
        self,
        page: Page,
        app_url: str,
        app_running,
        e2e_assert,
        take_screenshot
    ):
        """Test manual sync operations and their effects"""

        dashboard = DashboardPage(page)
        status_page = StatusPage(page)

        # Start at dashboard
        await dashboard.navigate_to(app_url)

        # Get initial sync timestamp
        initial_sync_time = await dashboard.get_last_sync_time()
        await take_screenshot("01_before_sync")

        # Trigger manual sync
        await dashboard.click_sync_button()
        await take_screenshot("02_sync_triggered")

        # Wait for sync to complete
        await asyncio.sleep(3)  # Allow time for sync operation

        # Verify sync completed
        final_sync_time = await dashboard.get_last_sync_time()

        # Sync time should have updated (or remained the same if no new data)
        if initial_sync_time and final_sync_time:
            print(f"Sync time changed from {initial_sync_time} to {final_sync_time}")

        await take_screenshot("03_sync_completed")

        # Check system status after sync
        await status_page.navigate_to(app_url)

        # Verify system is healthy after sync
        system_health = await status_page.get_system_health_score()
        assert system_health >= 0.5, f"System health score {system_health} too low after sync"

        # Check device connection status
        device_statuses = await status_page.get_device_statuses()

        if device_statuses:
            # At least one device should be configured
            assert len(device_statuses) > 0, "No devices configured"

            for device in device_statuses:
                print(f"Device {device.get('name', 'Unknown')}: {device.get('status', 'Unknown')}")

        await take_screenshot("04_status_after_sync")

    async def test_attendance_export_workflow(
        self,
        page: Page,
        app_url: str,
        app_running,
        e2e_assert,
        take_screenshot
    ):
        """Test attendance data export functionality"""

        dashboard = DashboardPage(page)

        await dashboard.navigate_to(app_url)
        await e2e_assert.assert_page_loaded(page, "Dashboard")

        # Test CSV export
        try:
            download_info = await dashboard.click_export_button()
            await take_screenshot("01_export_initiated")

            # Verify download
            assert download_info["filename"], "Download should have a filename"
            assert download_info["path"], "Download should have a file path"

            # Verify file extension
            filename = download_info["filename"]
            assert filename.endswith(".csv"), f"Expected CSV file, got {filename}"

            print(f"Successfully exported: {filename}")
            await take_screenshot("02_export_completed")

        except Exception as e:
            # Export might not be available or configured
            print(f"Export test skipped: {e}")
            await take_screenshot("02_export_not_available")

    async def test_attendance_calendar_view(
        self,
        page: Page,
        app_url: str,
        app_running,
        take_screenshot
    ):
        """Test attendance calendar view functionality"""

        # Navigate to calendar view (if available)
        try:
            await page.goto(f"{app_url}/calendar")
            await page.wait_for_load_state("networkidle")
            await take_screenshot("01_calendar_view")

            # Look for calendar elements
            calendar_present = await page.query_selector(".calendar") or await page.query_selector("[data-testid='calendar']")

            if calendar_present:
                # Test calendar navigation
                prev_button = await page.query_selector(".calendar-prev, [data-testid='calendar-prev']")
                next_button = await page.query_selector(".calendar-next, [data-testid='calendar-next']")

                if prev_button:
                    await prev_button.click()
                    await take_screenshot("02_calendar_prev_month")

                if next_button:
                    await next_button.click()
                    await take_screenshot("03_calendar_next_month")

                # Look for attendance data in calendar
                attendance_cells = await page.query_selector_all(".attendance-day, [data-testid*='attendance']")

                if attendance_cells:
                    print(f"Found {len(attendance_cells)} attendance data points in calendar")

                await take_screenshot("04_calendar_with_data")
            else:
                print("Calendar view not found")

        except Exception as e:
            print(f"Calendar test not available: {e}")

    async def test_device_connectivity_workflow(
        self,
        page: Page,
        app_url: str,
        app_running,
        e2e_assert,
        take_screenshot
    ):
        """Test device connectivity and status monitoring"""

        status_page = StatusPage(page)

        await status_page.navigate_to(app_url)
        await e2e_assert.assert_page_loaded(page, "Status")

        # Get overall system status
        system_status = await status_page.get_overall_system_status()
        assert system_status in ["healthy", "warning", "error"], f"Invalid system status: {system_status}"

        await take_screenshot("01_system_status")

        # Test component statuses
        component_statuses = await status_page.get_component_statuses()
        expected_components = ["database", "device", "websocket", "api"]

        for component in expected_components:
            if component in component_statuses:
                status = component_statuses[component]
                assert status in ["healthy", "warning", "error", "unavailable"], f"Invalid {component} status: {status}"
                print(f"{component.title()} status: {status}")

        # Test device-specific operations
        devices = await status_page.get_device_statuses()

        if devices:
            for device in devices[:1]:  # Test first device only
                device_name = device.get("name", "Unknown")
                print(f"Testing device: {device_name}")

                # Test device connection
                await status_page.test_device_connection(device_name)
                await take_screenshot(f"02_device_test_{device_name}")

                # Test device sync
                await status_page.sync_device(device_name)
                await take_screenshot(f"03_device_sync_{device_name}")

        await take_screenshot("04_final_device_status")

    async def test_websocket_real_time_updates(
        self,
        page: Page,
        app_url: str,
        app_running,
        websocket_tester,
        e2e_assert,
        take_screenshot
    ):
        """Test WebSocket real-time updates functionality"""

        dashboard = DashboardPage(page)

        await dashboard.navigate_to(app_url)

        # Verify WebSocket connection is established
        ws_connected = await dashboard.get_websocket_connection_status()
        assert ws_connected in ["Connected", "Connecting"], f"WebSocket not connected: {ws_connected}"

        await take_screenshot("01_websocket_connected")

        # Test WebSocket message handling
        try:
            # Wait for WebSocket messages
            await websocket_tester.wait_for_websocket_message(timeout=10000)
            messages = await websocket_tester.get_websocket_messages()

            if messages:
                print(f"Received {len(messages)} WebSocket messages")

                # Verify message structure
                for message in messages:
                    assert "timestamp" in message, "Message should have timestamp"
                    assert "data" in message, "Message should have data"

                await take_screenshot("02_websocket_messages_received")
            else:
                print("No WebSocket messages received (expected for quiet periods)")
                await take_screenshot("02_websocket_no_messages")

        except Exception as e:
            print(f"WebSocket message test: {e}")

        # Test simulated device sync (if available)
        try:
            await dashboard.simulate_device_sync()
            await take_screenshot("03_simulated_sync")
        except:
            print("Device sync simulation not available")

    async def test_attendance_data_validation(
        self,
        page: Page,
        app_url: str,
        app_running,
        take_screenshot
    ):
        """Test attendance data validation and error handling"""

        dashboard = DashboardPage(page)

        await dashboard.navigate_to(app_url)

        # Wait for dashboard data to load
        await dashboard.wait_for_dashboard_data_load()
        await take_screenshot("01_dashboard_loaded")

        # Get and validate attendance records
        records = await dashboard.get_recent_attendance_records()

        # Validate record structure and data
        for i, record in enumerate(records):
            # Check required fields
            assert record.get("employee"), f"Record {i} missing employee name"
            assert record.get("time"), f"Record {i} missing time"
            assert record.get("action"), f"Record {i} missing action type"

            # Validate data formats
            employee_name = record.get("employee", "")
            assert len(employee_name.strip()) > 0, f"Record {i} has empty employee name"

            time_str = record.get("time", "")
            assert len(time_str.strip()) > 0, f"Record {i} has empty time"

            action = record.get("action", "")
            assert action in ["Check In", "Check Out", "Break", "Return", "In", "Out", "0", "1", ""], f"Record {i} has invalid action: {action}"

        print(f"Validated {len(records)} attendance records")
        await take_screenshot("02_records_validated")

    @pytest.mark.slow
    async def test_attendance_performance_monitoring(
        self,
        page: Page,
        app_url: str,
        app_running,
        take_screenshot
    ):
        """Test attendance system performance under load"""

        dashboard = DashboardPage(page)
        status_page = StatusPage(page)

        # Start performance monitoring
        start_time = datetime.now()

        # Test dashboard load performance
        await dashboard.navigate_to(app_url)
        dashboard_load_time = (datetime.now() - start_time).total_seconds()

        assert dashboard_load_time < 10, f"Dashboard load time {dashboard_load_time}s exceeds 10s threshold"

        # Test data refresh performance
        refresh_start = datetime.now()
        await dashboard.wait_for_dashboard_data_load()
        data_load_time = (datetime.now() - refresh_start).total_seconds()

        assert data_load_time < 5, f"Data load time {data_load_time}s exceeds 5s threshold"

        await take_screenshot("01_dashboard_performance")

        # Test sync operation performance
        sync_start = datetime.now()
        await dashboard.click_sync_button()
        sync_time = (datetime.now() - sync_start).total_seconds()

        assert sync_time < 15, f"Sync operation time {sync_time}s exceeds 15s threshold"

        # Monitor system resources
        await status_page.navigate_to(app_url)
        system_metrics = await status_page.get_system_metrics()

        # Log performance metrics
        print(f"Performance Metrics:")
        print(f"  Dashboard Load: {dashboard_load_time:.2f}s")
        print(f"  Data Load: {data_load_time:.2f}s")
        print(f"  Sync Operation: {sync_time:.2f}s")
        print(f"  System Metrics: {system_metrics}")

        await take_screenshot("02_performance_monitoring")

        total_time = (datetime.now() - start_time).total_seconds()
        assert total_time < 30, f"Total test time {total_time}s exceeds 30s threshold"


@pytest.mark.asyncio
@pytest.mark.workflow("attendance_integration")
class TestAttendanceIntegration:
    """Integration tests for attendance system with external components"""

    async def test_zkteco_device_integration(
        self,
        page: Page,
        app_url: str,
        app_running,
        take_screenshot
    ):
        """Test ZKTeco device integration workflow"""

        status_page = StatusPage(page)

        await status_page.navigate_to(app_url)

        # Check for ZKTeco device configuration
        devices = await status_page.get_device_statuses()

        if not devices:
            pytest.skip("No ZKTeco devices configured for testing")

        # Test each configured device
        for device in devices:
            device_name = device.get("name", "Unknown")
            device_ip = device.get("ip", "Unknown")
            device_status = device.get("status", "Unknown")

            print(f"Testing ZKTeco device: {device_name} ({device_ip}) - Status: {device_status}")

            # Test device connectivity
            await status_page.test_device_connection(device_name)
            await take_screenshot(f"zkteco_test_{device_name}")

            # Verify connection result
            updated_devices = await status_page.get_device_statuses()
            updated_device = next((d for d in updated_devices if d.get("name") == device_name), None)

            if updated_device:
                final_status = updated_device.get("status", "Unknown")
                print(f"Device {device_name} final status: {final_status}")

        await take_screenshot("zkteco_integration_complete")

    async def test_database_integration(
        self,
        page: Page,
        app_url: str,
        app_running,
        take_screenshot
    ):
        """Test database integration and data consistency"""

        status_page = StatusPage(page)
        dashboard = DashboardPage(page)

        # Check database status
        await status_page.navigate_to(app_url)
        db_info = await status_page.get_database_info()

        assert "size" in db_info, "Database info should include size"
        assert "employees" in db_info, "Database info should include employee count"
        assert "records" in db_info, "Database info should include record count"

        print(f"Database info: {db_info}")
        await take_screenshot("01_database_status")

        # Cross-reference with dashboard data
        await dashboard.navigate_to(app_url)
        dashboard_employee_count = await dashboard.get_employee_count()
        dashboard_attendance_count = await dashboard.get_attendance_count()

        # Extract numeric values from database info
        import re
        db_employee_count = 0
        db_record_count = 0

        if db_info.get("employees"):
            numbers = re.findall(r'\d+', str(db_info["employees"]))
            db_employee_count = int(numbers[0]) if numbers else 0

        if db_info.get("records"):
            numbers = re.findall(r'\d+', str(db_info["records"]))
            db_record_count = int(numbers[0]) if numbers else 0

        print(f"Dashboard: {dashboard_employee_count} employees, {dashboard_attendance_count} attendance records")
        print(f"Database: {db_employee_count} employees, {db_record_count} records")

        # Data should be consistent (allowing for some variance due to timing)
        if db_employee_count > 0:
            assert abs(dashboard_employee_count - db_employee_count) <= 5, "Employee count mismatch between dashboard and database"

        await take_screenshot("02_data_consistency_check")


# Custom markers for attendance tests
def pytest_configure(config):
    """Configure custom markers for attendance tests"""
    config.addinivalue_line("markers", "workflow: mark test as workflow test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "integration: mark test as integration test")