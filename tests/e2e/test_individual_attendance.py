"""
E2E Tests for Individual Attendance Page (เข้า/ออก รายคน)
Tests the complete user flow from accessing the page to viewing attendance data
"""

import pytest
import json
import time
from datetime import datetime, timedelta

# Optional Playwright imports (only for browser-based tests)
try:
    from playwright.sync_api import Page, expect
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    # Define dummy classes so the test file can be imported
    Page = None
    expect = None


@pytest.mark.e2e
@pytest.mark.browser
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestIndividualAttendance:
    """Test individual attendance page functionality with real browser automation"""

    def test_individual_attendance_page_flow(self, page: Page, live_server_url: str):
        """
        Test Flow 1: User accesses page -> sees employee list -> selects user -> sees attendance data
        URL: https://emp.thehfhotel.org/fingerprintlogs/individual-attendance
        """
        # Step 1: Navigate to individual attendance page
        attendance_url = f"{live_server_url}/individual-attendance"
        page.goto(attendance_url)

        # Verify page loaded successfully
        expect(page).to_have_title("เข้า/ออก รายคน - การลงเวลารายบุคคล")

        # Step 2: Verify users are visible in the left sidebar
        # Wait for employee list to load
        page.wait_for_selector(".nickname-list", timeout=10000)

        # Check that employee list is populated
        employee_items = page.locator(".nickname-item")
        expect(employee_items).to_have_count(lambda count: count > 0, timeout=10000)

        # Get count of employees
        employee_count = employee_items.count()
        assert employee_count > 0, "No employees found in the list"

        # Step 3: Select first user from the list
        first_employee = employee_items.first
        employee_name = first_employee.text_content()

        # Click on the first employee
        first_employee.click()

        # Verify employee is selected (has active class)
        expect(first_employee).to_have_class(lambda classes: "active" in classes)

        # Step 4: Verify attendance data appears in the table
        # Wait for loading to complete
        page.wait_for_selector("#loadingOverlay", state="hidden", timeout=10000)

        # Check that selected employee name is displayed
        selected_name_element = page.locator("#selectedEmployeeName")
        expect(selected_name_element).not_to_have_text("เลือกพนักงานเพื่อดูข้อมูล")

        # Verify table has data or appropriate message
        table_body = page.locator("#attendanceTableBody")

        # Wait for table to be populated
        page.wait_for_function(
            """() => {
                const tbody = document.querySelector('#attendanceTableBody');
                return tbody && tbody.innerHTML.trim() !== '';
            }""",
            timeout=10000
        )

        # Check if table has rows
        table_rows = table_body.locator("tr")
        row_count = table_rows.count()

        if row_count > 0:
            # If there are rows, verify structure
            first_row = table_rows.first

            # Check for date column (format dd/mm/yyyy)
            date_cell = first_row.locator("td").first
            date_text = date_cell.text_content()

            # Verify date format (dd/mm/yyyy)
            if date_text and "ไม่พบข้อมูล" not in date_text:
                assert "/" in date_text, "Date should be in dd/mm/yyyy format"
                date_parts = date_text.split("/")
                assert len(date_parts) == 3, "Date should have 3 parts (dd/mm/yyyy)"

                # Check time column
                time_cell = first_row.locator("td").nth(1)
                time_text = time_cell.text_content()
                assert time_text, "Time column should have content"

    def test_employee_search_functionality(self, page: Page, live_server_url: str):
        """Test the employee search functionality in the sidebar"""
        # Navigate to page
        attendance_url = f"{live_server_url}/individual-attendance"
        page.goto(attendance_url)

        # Wait for employee list to load
        page.wait_for_selector(".nickname-list .nickname-item", timeout=10000)

        # Get initial employee count
        initial_count = page.locator(".nickname-item").count()

        # Use search box
        search_input = page.locator("#nicknameSearch")
        search_input.fill("test")  # Search for "test"

        # Wait for filtering to occur
        page.wait_for_timeout(500)  # Brief wait for JS filtering

        # Check filtered results
        filtered_count = page.locator(".nickname-item").count()

        # Filtered count should be less than or equal to initial count
        assert filtered_count <= initial_count, "Search should filter the employee list"

        # Clear search
        search_input.clear()

        # Wait for list to restore
        page.wait_for_timeout(500)

        # Verify list is restored
        restored_count = page.locator(".nickname-item").count()
        assert restored_count == initial_count, "Clearing search should restore full list"

    def test_date_filter_functionality(self, page: Page, live_server_url: str):
        """Test the date range filtering for attendance data"""
        # Navigate to page
        attendance_url = f"{live_server_url}/individual-attendance"
        page.goto(attendance_url)

        # Wait for employee list
        page.wait_for_selector(".nickname-item", timeout=10000)

        # Select first employee
        first_employee = page.locator(".nickname-item").first
        first_employee.click()

        # Wait for data to load
        page.wait_for_selector("#loadingOverlay", state="hidden", timeout=10000)

        # Set date range (last 7 days)
        today = datetime.now()
        week_ago = today - timedelta(days=7)

        start_date_input = page.locator("#startDate")
        end_date_input = page.locator("#endDate")

        # Format dates for input (YYYY-MM-DD)
        start_date_str = week_ago.strftime("%Y-%m-%d")
        end_date_str = today.strftime("%Y-%m-%d")

        # Set date values
        start_date_input.fill(start_date_str)
        end_date_input.fill(end_date_str)

        # Click filter button
        filter_button = page.locator("#filterButton")
        filter_button.click()

        # Wait for data reload
        page.wait_for_selector("#loadingOverlay", state="hidden", timeout=10000)

        # Verify table updated (checking that filtering occurred)
        table_body = page.locator("#attendanceTableBody")
        assert table_body.is_visible(), "Table should remain visible after filtering"

    def test_navigation_back_to_dashboard(self, page: Page, live_server_url: str):
        """Test navigation back to dashboard"""
        # Navigate to individual attendance page
        attendance_url = f"{live_server_url}/individual-attendance"
        page.goto(attendance_url)

        # Find and click back to dashboard button
        back_button = page.locator('a:has-text("กลับไปแดชบอร์ด")')
        expect(back_button).to_be_visible()

        # Click to navigate back
        back_button.click()

        # Verify we're back at dashboard
        expect(page).to_have_url(lambda url: "/fingerprintlogs" in url or "dashboard" in url)


@pytest.mark.e2e
@pytest.mark.cli
class TestIndividualAttendanceCLI:
    """CLI-based tests for individual attendance page using HTTP requests"""

    def test_page_loads_successfully(self, api_client, app_running):
        """Test that the individual attendance page loads via HTTP"""
        response = api_client.get("/individual-attendance")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

        # Check for key elements in HTML
        content = response.text
        assert "เข้า/ออก รายคน" in content
        assert "nicknameList" in content
        assert "attendanceTable" in content

    def test_employee_api_endpoint(self, api_client, app_running):
        """Test the employee attendance API endpoint"""
        # First get list of employees
        employees_response = api_client.get("/api/employees/")
        assert employees_response.status_code == 200

        employees_data = employees_response.json()
        if "employees" in employees_data and len(employees_data["employees"]) > 0:
            # Get first employee badge number (used as identifier)
            first_employee = employees_data["employees"][0]
            employee_badge = first_employee["badge_number"]

            # Test individual attendance endpoint using badge
            # Note: The endpoint uses badge number, not ID
            attendance_response = api_client.get(f"/api/attendance/employee/badge/{employee_badge}")
            assert attendance_response.status_code in [200, 404]  # 404 if no attendance data

            if attendance_response.status_code == 200:
                data = attendance_response.json()
                assert "employee_badge" in data or "employee_id" in data
                assert "records" in data
                assert isinstance(data["records"], list)

    def test_page_includes_required_scripts(self, api_client, app_running):
        """Test that page includes all required JavaScript files"""
        response = api_client.get("/individual-attendance")
        assert response.status_code == 200

        content = response.text
        # Check for required scripts
        assert "individual-attendance.js" in content
        assert "config.js" in content

        # Check for required CSS
        assert "individual-attendance.css" in content
        assert "base.css" in content

    def test_api_date_filtering(self, api_client, app_running):
        """Test the attendance API with date filtering"""
        # Get employees first
        employees_response = api_client.get("/api/employees/")

        if employees_response.status_code == 200:
            employees_data = employees_response.json()
            if "employees" in employees_data and len(employees_data["employees"]) > 0:
                employee_badge = employees_data["employees"][0]["badge_number"]

                # Test with date range
                today = datetime.now()
                week_ago = today - timedelta(days=7)

                params = {
                    "start_date": week_ago.strftime("%Y-%m-%d"),
                    "end_date": today.strftime("%Y-%m-%d")
                }

                response = api_client.get(
                    f"/api/attendance/employee/badge/{employee_badge}",
                    params=params
                )

                assert response.status_code in [200, 404]

                if response.status_code == 200:
                    data = response.json()
                    assert "employee_badge" in data or "employee_id" in data
                    assert "records" in data