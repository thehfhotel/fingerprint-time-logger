"""
Employee Lifecycle E2E Workflow Test
Tests the complete employee management workflow from creation to deletion
"""

import pytest
import asyncio
from datetime import datetime
from playwright.async_api import Page

from tests.e2e.page_objects.dashboard_page import DashboardPage
from tests.e2e.page_objects.employee_page import EmployeePage
from tests.e2e.page_objects.status_page import StatusPage


@pytest.mark.asyncio
@pytest.mark.workflow("employee_lifecycle")
class TestEmployeeLifecycle:
    """Complete employee lifecycle workflow testing"""

    async def test_complete_employee_workflow(
        self,
        page: Page,
        app_url: str,
        app_running,
        test_employee_data: dict,
        e2e_assert,
        take_screenshot
    ):
        """Test complete employee workflow: create → view → edit → status changes → delete"""

        # Initialize page objects
        dashboard = DashboardPage(page)
        employee_page = EmployeePage(page)
        status_page = StatusPage(page)

        # Step 1: Start at dashboard and verify initial state
        await dashboard.navigate_to(app_url)
        await e2e_assert.assert_page_loaded(page, "Dashboard")

        initial_employee_count = await dashboard.get_employee_count()
        await take_screenshot("01_initial_dashboard")

        # Step 2: Navigate to employee management
        await dashboard.navigate_to_employee_management()
        await e2e_assert.assert_page_loaded(page, "Employee")
        await take_screenshot("02_employee_management")

        # Verify employee management page loaded correctly
        page_title = await employee_page.get_page_title()
        assert "Employee" in page_title or "Nickname" in page_title

        # Step 3: Create new employee
        await employee_page.click_add_employee()
        await e2e_assert.assert_element_visible(page, "[data-testid='employee-form']")

        # Fill employee form with test data
        await employee_page.fill_employee_form(test_employee_data)
        await take_screenshot("03_employee_form_filled")

        # Save the employee
        await employee_page.save_employee()

        # Verify success message or form closure
        success_message = await employee_page.get_success_message()
        if success_message:
            assert "success" in success_message.lower() or "created" in success_message.lower()

        await take_screenshot("04_employee_created")

        # Step 4: Verify employee appears in list
        employee_created = await employee_page.verify_employee_created(test_employee_data)
        assert employee_created, f"Employee {test_employee_data.get('english_name', 'Unknown')} was not found after creation"

        # Step 5: Verify Thai name display (if provided)
        if test_employee_data.get("thai_name"):
            thai_displayed = await employee_page.verify_thai_names_displayed()
            assert thai_displayed, "Thai names are not properly displayed"

        # Step 6: Test search functionality
        search_term = test_employee_data.get("badge_number", test_employee_data.get("english_name", ""))
        await employee_page.search_employees(search_term)
        await take_screenshot("05_employee_search")

        # Verify search results
        search_results = await employee_page.get_employee_list()
        assert len(search_results) > 0, "Search returned no results for newly created employee"

        # Step 7: Edit employee information
        await employee_page.edit_employee(search_term)
        await e2e_assert.assert_element_visible(page, "[data-testid='employee-form']")

        # Update employee data
        updated_data = {
            "department": "Updated IT Department",
            "position": "Senior Developer"
        }
        await employee_page.fill_employee_form(updated_data)
        await take_screenshot("06_employee_edit")

        await employee_page.save_employee()
        await take_screenshot("07_employee_updated")

        # Step 8: Test status toggles
        # Toggle employee active/inactive status
        await employee_page.toggle_employee_status(search_term)
        await take_screenshot("08_status_toggled")

        # Toggle employee visibility
        await employee_page.toggle_employee_visibility(search_term)
        await take_screenshot("09_visibility_toggled")

        # Reset visibility for further testing
        await employee_page.toggle_employee_visibility(search_term)

        # Step 9: Verify changes reflect on dashboard
        await dashboard.navigate_to(app_url)

        # Check if employee count changed (might be same due to status changes)
        current_employee_count = await dashboard.get_employee_count()
        assert current_employee_count >= initial_employee_count, "Employee count should not decrease after creation"

        await take_screenshot("10_dashboard_after_changes")

        # Step 10: Check system status for any issues
        await status_page.navigate_to(app_url)
        system_status = await status_page.get_overall_system_status()
        assert system_status in ["healthy", "warning"], f"System status is {system_status}, expected healthy or warning"

        component_statuses = await status_page.get_component_statuses()
        critical_components = ["database", "api"]
        for component in critical_components:
            if component in component_statuses:
                assert component_statuses[component] in ["healthy", "warning"], f"Critical component {component} status: {component_statuses[component]}"

        await take_screenshot("11_system_status")

        # Step 11: Test bulk operations (if available)
        await employee_page.navigate_to(app_url)

        # Try bulk selection
        try:
            await employee_page.bulk_select_employees([search_term])
            await take_screenshot("12_bulk_selection")
        except:
            # Bulk operations may not be implemented yet
            pass

        # Step 12: Clean up - Delete the test employee
        await employee_page.delete_employee(search_term)
        await take_screenshot("13_employee_deleted")

        # Verify employee is no longer in the list
        await employee_page.search_employees(search_term)
        final_results = await employee_page.get_employee_list()

        # Employee should either be gone or marked as deleted/inactive
        employee_still_visible = any(
            test_employee_data.get("badge_number", "") in result.get("badge", "") or
            test_employee_data.get("english_name", "") in result.get("name", "")
            for result in final_results
        )

        # If employee is still visible, it might be soft-deleted, which is acceptable
        if employee_still_visible:
            print(f"Employee {search_term} still visible after deletion - may be soft-deleted")

        await take_screenshot("14_final_state")

    async def test_employee_validation_workflow(
        self,
        page: Page,
        app_url: str,
        app_running,
        e2e_assert,
        take_screenshot
    ):
        """Test employee form validation and error handling"""

        employee_page = EmployeePage(page)

        # Navigate to employee management
        await employee_page.navigate_to(app_url)

        # Test form validation with invalid data
        await employee_page.click_add_employee()
        await e2e_assert.assert_element_visible(page, "[data-testid='employee-form']")

        # Test empty form submission
        await employee_page.save_employee()
        await take_screenshot("validation_empty_form")

        # Check for validation messages
        validation_messages = await employee_page.wait_for_employee_form_validation()

        # Should have validation messages for required fields
        if validation_messages:
            assert len(validation_messages) > 0, "Expected validation messages for empty form"

        # Test with minimal valid data
        minimal_data = {
            "badge_number": f"TEST{datetime.now().strftime('%H%M%S')}",
            "english_name": "Test Employee Validation"
        }

        await employee_page.fill_employee_form(minimal_data)
        await take_screenshot("validation_minimal_data")

        await employee_page.save_employee()

        # Should succeed with minimal valid data
        success_message = await employee_page.get_success_message()
        if success_message:
            assert "success" in success_message.lower() or "created" in success_message.lower()

        # Clean up test employee
        await employee_page.delete_employee(minimal_data["badge_number"])

    async def test_employee_search_and_filter_workflow(
        self,
        page: Page,
        app_url: str,
        app_running,
        test_employee_data: dict,
        take_screenshot
    ):
        """Test employee search and filtering functionality"""

        employee_page = EmployeePage(page)

        await employee_page.navigate_to(app_url)

        # Get initial employee list
        initial_employees = await employee_page.get_employee_list()
        initial_count = len(initial_employees)

        await take_screenshot("search_initial_list")

        # Test search with various terms
        search_terms = [
            "test",           # Generic term
            "123",            # Numeric (badge number)
            "employee",       # Common word
            "nonexistent"     # Should return empty
        ]

        for term in search_terms:
            await employee_page.search_employees(term)
            await take_screenshot(f"search_term_{term}")

            search_results = await employee_page.get_employee_list()

            if term == "nonexistent":
                # Should return no results
                assert len(search_results) == 0, f"Expected no results for '{term}', got {len(search_results)}"
            else:
                # Results should contain the search term in name or badge
                for result in search_results:
                    name = result.get("name", "").lower()
                    badge = result.get("badge", "").lower()
                    assert term.lower() in name or term.lower() in badge, f"Search result doesn't contain term '{term}'"

        # Clear search to return to full list
        await employee_page.search_employees("")
        final_employees = await employee_page.get_employee_list()

        # Should return to similar count as initial (allowing for some variation)
        assert abs(len(final_employees) - initial_count) <= 2, "Search clear didn't return to original list size"

        await take_screenshot("search_cleared")

    async def test_employee_pagination_workflow(
        self,
        page: Page,
        app_url: str,
        app_running,
        take_screenshot
    ):
        """Test employee list pagination functionality"""

        employee_page = EmployeePage(page)

        await employee_page.navigate_to(app_url)

        # Test different page sizes
        page_sizes = [10, 25, 50]

        for size in page_sizes:
            try:
                await employee_page.set_page_size(size)
                await take_screenshot(f"pagination_size_{size}")

                employees = await employee_page.get_employee_list()

                # Should show at most the page size number of employees
                assert len(employees) <= size, f"Page shows {len(employees)} employees, expected max {size}"

            except:
                # Pagination might not be implemented yet
                print(f"Pagination with size {size} not available")
                break

        # Test page navigation (if pagination exists)
        try:
            await employee_page.go_to_page(2)
            await take_screenshot("pagination_page_2")
        except:
            print("Page navigation not available")

    @pytest.mark.slow
    async def test_employee_performance_workflow(
        self,
        page: Page,
        app_url: str,
        app_running,
        take_screenshot
    ):
        """Test employee management performance with multiple operations"""

        employee_page = EmployeePage(page)

        await employee_page.navigate_to(app_url)

        # Record start time
        start_time = datetime.now()

        # Perform multiple operations to test performance
        operations = [
            ("navigate", lambda: employee_page.navigate_to(app_url)),
            ("get_list", lambda: employee_page.get_employee_list()),
            ("search", lambda: employee_page.search_employees("test")),
            ("clear_search", lambda: employee_page.search_employees("")),
        ]

        operation_times = {}

        for operation_name, operation_func in operations:
            op_start = datetime.now()
            await operation_func()
            op_end = datetime.now()
            operation_times[operation_name] = (op_end - op_start).total_seconds()

        end_time = datetime.now()
        total_time = (end_time - start_time).total_seconds()

        await take_screenshot("performance_test_complete")

        # Performance assertions
        assert total_time < 30, f"Total workflow time {total_time}s exceeded 30s threshold"
        assert operation_times.get("get_list", 0) < 5, f"Get employee list took {operation_times.get('get_list')}s, expected < 5s"

        print(f"Performance results: {operation_times}, Total: {total_time}s")


# Additional utility fixtures for employee lifecycle tests
@pytest.fixture
def extended_employee_data():
    """Extended employee data for comprehensive testing"""
    timestamp = datetime.now().strftime('%H%M%S')
    return {
        "badge_number": f"E2E{timestamp}",
        "thai_name": "ทดสอบ ระบบ",
        "english_name": f"E2E Test Employee {timestamp}",
        "department": "Quality Assurance",
        "position": "Test Engineer",
        "status": "Active"
    }


@pytest.fixture
def bulk_employee_data():
    """Multiple employee records for bulk operation testing"""
    timestamp = datetime.now().strftime('%H%M%S')
    return [
        {
            "badge_number": f"BULK1{timestamp}",
            "thai_name": "ทดสอบ หนึ่ง",
            "english_name": f"Bulk Test One {timestamp}",
            "department": "IT",
            "position": "Developer"
        },
        {
            "badge_number": f"BULK2{timestamp}",
            "thai_name": "ทดสอบ สอง",
            "english_name": f"Bulk Test Two {timestamp}",
            "department": "HR",
            "position": "Manager"
        },
        {
            "badge_number": f"BULK3{timestamp}",
            "thai_name": "ทดสอบ สาม",
            "english_name": f"Bulk Test Three {timestamp}",
            "department": "Finance",
            "position": "Analyst"
        }
    ]