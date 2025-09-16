"""
Employee Management Page Object Model
Encapsulates employee management interactions for E2E testing
"""

from playwright.async_api import Page
from typing import Dict, List, Optional


class EmployeePage:
    """Page object for the employee management interface"""

    def __init__(self, page: Page):
        self.page = page

        # Selectors for employee management elements
        self.selectors = {
            "title": "h1",
            "employee_list": "[data-testid='employee-list']",
            "add_employee_button": "[data-testid='add-employee-button']",
            "search_input": "[data-testid='search-input']",
            "filter_dropdown": "[data-testid='filter-dropdown']",
            "employee_card": "[data-testid='employee-card']",
            "employee_name": "[data-testid='employee-name']",
            "employee_badge": "[data-testid='employee-badge']",
            "employee_status": "[data-testid='employee-status']",
            "edit_button": "[data-testid='edit-employee']",
            "delete_button": "[data-testid='delete-employee']",
            "status_toggle": "[data-testid='status-toggle']",
            "visibility_toggle": "[data-testid='visibility-toggle']",

            # Employee form elements
            "employee_form": "[data-testid='employee-form']",
            "badge_number_input": "[data-testid='badge-number']",
            "thai_name_input": "[data-testid='thai-name']",
            "english_name_input": "[data-testid='english-name']",
            "department_input": "[data-testid='department']",
            "position_input": "[data-testid='position']",
            "save_button": "[data-testid='save-employee']",
            "cancel_button": "[data-testid='cancel-employee']",

            # Bulk operations
            "bulk_select_all": "[data-testid='bulk-select-all']",
            "bulk_actions_dropdown": "[data-testid='bulk-actions']",
            "bulk_export_button": "[data-testid='bulk-export']",
            "bulk_status_update": "[data-testid='bulk-status-update']",

            # Pagination and sorting
            "pagination": "[data-testid='pagination']",
            "page_size_selector": "[data-testid='page-size']",
            "sort_dropdown": "[data-testid='sort-dropdown']",

            # Loading and error states
            "loading_spinner": ".loading-spinner",
            "error_message": "[data-testid='error-message']",
            "success_message": "[data-testid='success-message']",

            # Statistics and summaries
            "total_employees": "[data-testid='total-employees']",
            "active_employees": "[data-testid='active-employees']",
            "inactive_employees": "[data-testid='inactive-employees']"
        }

    async def navigate_to(self, base_url: str):
        """Navigate to employee management page"""
        await self.page.goto(f"{base_url}/nickname-management")
        await self.wait_for_load()

    async def wait_for_load(self):
        """Wait for employee management page to fully load"""
        # Wait for main content to be visible
        await self.page.wait_for_selector("h1", timeout=10000)

        # Wait for employee list to load
        await self.page.wait_for_selector(self.selectors["employee_list"], timeout=10000)

        # Wait for any loading spinners to disappear
        try:
            await self.page.wait_for_selector(
                self.selectors["loading_spinner"],
                state="detached",
                timeout=5000
            )
        except:
            pass  # No loading spinner present

        # Wait for network to be idle
        await self.page.wait_for_load_state("networkidle")

    async def get_page_title(self) -> str:
        """Get the employee management page title"""
        return await self.page.text_content(self.selectors["title"])

    async def get_employee_count(self) -> int:
        """Get the total number of employees displayed"""
        try:
            count_text = await self.page.text_content(self.selectors["total_employees"])
            import re
            numbers = re.findall(r'\d+', count_text)
            return int(numbers[0]) if numbers else 0
        except:
            # Fallback: count employee cards
            cards = await self.page.query_selector_all(self.selectors["employee_card"])
            return len(cards)

    async def search_employees(self, search_term: str):
        """Search for employees using the search input"""
        await self.page.fill(self.selectors["search_input"], search_term)

        # Wait for search results to load
        await self.page.wait_for_timeout(1000)  # Allow search debounce
        await self.wait_for_load()

    async def filter_employees(self, filter_value: str):
        """Filter employees using the filter dropdown"""
        await self.page.select_option(self.selectors["filter_dropdown"], filter_value)
        await self.wait_for_load()

    async def get_employee_list(self) -> List[Dict[str, str]]:
        """Get list of all visible employees"""
        employees = []

        try:
            # Get all employee cards
            cards = await self.page.query_selector_all(self.selectors["employee_card"])

            for card in cards:
                try:
                    name_element = await card.query_selector(self.selectors["employee_name"].replace("[data-testid='employee-name']", "[data-testid='employee-name']"))
                    badge_element = await card.query_selector(self.selectors["employee_badge"].replace("[data-testid='employee-badge']", "[data-testid='employee-badge']"))
                    status_element = await card.query_selector(self.selectors["employee_status"].replace("[data-testid='employee-status']", "[data-testid='employee-status']"))

                    employee = {
                        "name": await name_element.text_content() if name_element else "",
                        "badge": await badge_element.text_content() if badge_element else "",
                        "status": await status_element.text_content() if status_element else "",
                    }
                    employees.append(employee)
                except:
                    continue  # Skip malformed employee cards
        except:
            pass  # No employee cards found

        return employees

    async def click_add_employee(self):
        """Click the add employee button"""
        await self.page.click(self.selectors["add_employee_button"])

        # Wait for employee form to appear
        await self.page.wait_for_selector(self.selectors["employee_form"], timeout=5000)

    async def fill_employee_form(self, employee_data: Dict[str, str]):
        """Fill out the employee form with provided data"""
        form_fields = {
            "badge_number": self.selectors["badge_number_input"],
            "thai_name": self.selectors["thai_name_input"],
            "english_name": self.selectors["english_name_input"],
            "department": self.selectors["department_input"],
            "position": self.selectors["position_input"]
        }

        for field_name, selector in form_fields.items():
            if field_name in employee_data:
                await self.page.fill(selector, employee_data[field_name])

    async def save_employee(self):
        """Save the employee form"""
        await self.page.click(self.selectors["save_button"])

        # Wait for save operation to complete
        try:
            # Wait for success message or form to disappear
            await self.page.wait_for_selector(
                self.selectors["success_message"],
                timeout=5000
            )
        except:
            # Alternative: wait for form to disappear
            try:
                await self.page.wait_for_selector(
                    self.selectors["employee_form"],
                    state="detached",
                    timeout=5000
                )
            except:
                pass

        # Wait for page to update
        await self.wait_for_load()

    async def cancel_employee_form(self):
        """Cancel the employee form"""
        await self.page.click(self.selectors["cancel_button"])

        # Wait for form to disappear
        await self.page.wait_for_selector(
            self.selectors["employee_form"],
            state="detached",
            timeout=5000
        )

    async def edit_employee(self, employee_identifier: str):
        """Edit an employee by badge number or name"""
        # Find the employee card
        employee_card = await self.find_employee_card(employee_identifier)

        if employee_card:
            edit_button = await employee_card.query_selector(self.selectors["edit_button"].replace("[data-testid='edit-employee']", "[data-testid='edit-employee']"))
            if edit_button:
                await edit_button.click()

                # Wait for employee form to appear
                await self.page.wait_for_selector(self.selectors["employee_form"], timeout=5000)

    async def delete_employee(self, employee_identifier: str):
        """Delete an employee by badge number or name"""
        # Find the employee card
        employee_card = await self.find_employee_card(employee_identifier)

        if employee_card:
            delete_button = await employee_card.query_selector(self.selectors["delete_button"].replace("[data-testid='delete-employee']", "[data-testid='delete-employee']"))
            if delete_button:
                await delete_button.click()

                # Handle confirmation dialog if it appears
                try:
                    await self.page.wait_for_selector("[data-testid='confirm-delete']", timeout=2000)
                    await self.page.click("[data-testid='confirm-delete']")
                except:
                    pass  # No confirmation dialog

                # Wait for deletion to complete
                await self.wait_for_load()

    async def toggle_employee_status(self, employee_identifier: str):
        """Toggle an employee's active/inactive status"""
        employee_card = await self.find_employee_card(employee_identifier)

        if employee_card:
            status_toggle = await employee_card.query_selector(self.selectors["status_toggle"].replace("[data-testid='status-toggle']", "[data-testid='status-toggle']"))
            if status_toggle:
                await status_toggle.click()
                await self.wait_for_load()

    async def toggle_employee_visibility(self, employee_identifier: str):
        """Toggle an employee's visibility status"""
        employee_card = await self.find_employee_card(employee_identifier)

        if employee_card:
            visibility_toggle = await employee_card.query_selector(self.selectors["visibility_toggle"].replace("[data-testid='visibility-toggle']", "[data-testid='visibility-toggle']"))
            if visibility_toggle:
                await visibility_toggle.click()
                await self.wait_for_load()

    async def find_employee_card(self, identifier: str):
        """Find employee card by badge number or name"""
        cards = await self.page.query_selector_all(self.selectors["employee_card"])

        for card in cards:
            try:
                name_element = await card.query_selector("[data-testid='employee-name']")
                badge_element = await card.query_selector("[data-testid='employee-badge']")

                name = await name_element.text_content() if name_element else ""
                badge = await badge_element.text_content() if badge_element else ""

                if identifier in name or identifier in badge:
                    return card
            except:
                continue

        return None

    async def bulk_select_employees(self, employee_identifiers: List[str]):
        """Select multiple employees for bulk operations"""
        for identifier in employee_identifiers:
            employee_card = await self.find_employee_card(identifier)
            if employee_card:
                checkbox = await employee_card.query_selector("[data-testid='employee-checkbox']")
                if checkbox:
                    await checkbox.click()

    async def bulk_export_selected(self):
        """Export selected employees"""
        async with self.page.expect_download() as download_info:
            await self.page.click(self.selectors["bulk_export_button"])

        download = await download_info.value
        return {
            "filename": download.suggested_filename,
            "path": await download.path()
        }

    async def set_page_size(self, size: int):
        """Set the number of employees displayed per page"""
        await self.page.select_option(self.selectors["page_size_selector"], str(size))
        await self.wait_for_load()

    async def go_to_page(self, page_number: int):
        """Navigate to a specific page in pagination"""
        page_link = f"[data-testid='page-{page_number}']"
        await self.page.click(page_link)
        await self.wait_for_load()

    async def sort_employees(self, sort_option: str):
        """Sort employees by the specified option"""
        await self.page.select_option(self.selectors["sort_dropdown"], sort_option)
        await self.wait_for_load()

    async def verify_thai_names_displayed(self) -> bool:
        """Verify that Thai names are properly displayed"""
        page_content = await self.page.content()

        # Check for common Thai characters
        thai_patterns = [
            "ก", "ข", "ค", "ง", "จ", "ช", "ท", "น", "ม", "ร", "ส", "ต",
            "สมชาย", "สมหญิง", "นาย", "นาง", "นางสาว"
        ]

        for pattern in thai_patterns:
            if pattern in page_content:
                return True

        return False

    async def get_error_message(self) -> Optional[str]:
        """Get any error message displayed on the page"""
        try:
            error_element = await self.page.query_selector(self.selectors["error_message"])
            if error_element:
                return await error_element.text_content()
        except:
            pass

        return None

    async def get_success_message(self) -> Optional[str]:
        """Get any success message displayed on the page"""
        try:
            success_element = await self.page.query_selector(self.selectors["success_message"])
            if success_element:
                return await success_element.text_content()
        except:
            pass

        return None

    async def take_screenshot(self, name: str = "employee-management"):
        """Take a screenshot of the employee management page"""
        timestamp = await self.page.evaluate("() => new Date().toISOString().replace(/[:.]/g, '-')")
        filename = f"{name}_{timestamp}.png"

        await self.page.screenshot(path=f"tests/e2e/screenshots/{filename}")
        return filename

    async def wait_for_employee_form_validation(self) -> Dict[str, str]:
        """Wait for and capture form validation messages"""
        validation_messages = {}

        # Common validation selectors
        validation_selectors = {
            "badge_number": "[data-testid='badge-number-error']",
            "thai_name": "[data-testid='thai-name-error']",
            "english_name": "[data-testid='english-name-error']"
        }

        for field, selector in validation_selectors.items():
            try:
                element = await self.page.query_selector(selector)
                if element:
                    validation_messages[field] = await element.text_content()
            except:
                pass

        return validation_messages

    async def verify_employee_created(self, employee_data: Dict[str, str]) -> bool:
        """Verify that an employee was successfully created"""
        # Search for the newly created employee
        if "badge_number" in employee_data:
            await self.search_employees(employee_data["badge_number"])
        elif "english_name" in employee_data:
            await self.search_employees(employee_data["english_name"])

        # Check if employee appears in results
        employees = await self.get_employee_list()

        for employee in employees:
            if (employee_data.get("badge_number", "") in employee.get("badge", "") or
                employee_data.get("english_name", "") in employee.get("name", "") or
                employee_data.get("thai_name", "") in employee.get("name", "")):
                return True

        return False