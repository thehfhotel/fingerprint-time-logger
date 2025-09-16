"""
Dashboard Page Object Model
Encapsulates dashboard interactions for E2E testing
"""

from playwright.async_api import Page
from typing import Dict, List, Optional


class DashboardPage:
    """Page object for the main dashboard interface"""

    def __init__(self, page: Page):
        self.page = page

        # Selectors for dashboard elements
        self.selectors = {
            "title": "h1",
            "stats_cards": "[data-testid='stats-card']",
            "employee_count": "[data-testid='employee-count']",
            "attendance_count": "[data-testid='attendance-count']",
            "recent_records": "[data-testid='recent-records']",
            "real_time_updates": "[data-testid='real-time-updates']",
            "device_status": "[data-testid='device-status']",
            "sync_button": "[data-testid='sync-button']",
            "export_button": "[data-testid='export-button']",
            "employee_management_link": "a[href='/nickname-management']",
            "status_link": "a[href='/status']",
            "websocket_status": "[data-testid='websocket-status']",
            "last_sync_time": "[data-testid='last-sync']",
            "loading_spinner": ".loading-spinner"
        }

    async def navigate_to(self, base_url: str):
        """Navigate to dashboard page"""
        await self.page.goto(f"{base_url}/")
        await self.wait_for_load()

    async def wait_for_load(self):
        """Wait for dashboard to fully load"""
        # Wait for main content to be visible
        await self.page.wait_for_selector("h1", timeout=10000)

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
        """Get the dashboard page title"""
        return await self.page.text_content(self.selectors["title"])

    async def get_employee_count(self) -> int:
        """Get the total employee count from dashboard"""
        try:
            count_text = await self.page.text_content(self.selectors["employee_count"])
            # Extract number from text like "Total Employees: 15"
            import re
            numbers = re.findall(r'\d+', count_text)
            return int(numbers[0]) if numbers else 0
        except:
            return 0

    async def get_attendance_count(self) -> int:
        """Get the total attendance count from dashboard"""
        try:
            count_text = await self.page.text_content(self.selectors["attendance_count"])
            import re
            numbers = re.findall(r'\d+', count_text)
            return int(numbers[0]) if numbers else 0
        except:
            return 0

    async def get_recent_attendance_records(self) -> List[Dict[str, str]]:
        """Get recent attendance records displayed on dashboard"""
        records = []
        try:
            # Look for table rows in recent records section
            rows = await self.page.query_selector_all(
                f"{self.selectors['recent_records']} tbody tr"
            )

            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 4:
                    record = {
                        "employee": await cells[0].text_content(),
                        "time": await cells[1].text_content(),
                        "action": await cells[2].text_content(),
                        "status": await cells[3].text_content(),
                    }
                    records.append(record)
        except:
            pass  # No records or different structure

        return records

    async def get_device_status(self) -> Dict[str, str]:
        """Get device connection status"""
        try:
            status_element = await self.page.query_selector(self.selectors["device_status"])
            if status_element:
                status_text = await status_element.text_content()
                # Parse status (e.g., "Device: Connected" or "Device: Disconnected")
                if "Connected" in status_text:
                    return {"status": "connected", "message": status_text}
                else:
                    return {"status": "disconnected", "message": status_text}
        except:
            pass

        return {"status": "unknown", "message": "Status not available"}

    async def click_sync_button(self):
        """Click the sync button and wait for completion"""
        await self.page.click(self.selectors["sync_button"])

        # Wait for sync to complete (loading spinner or status change)
        try:
            # Wait for any loading indicators to appear and disappear
            await self.page.wait_for_selector(".loading", timeout=2000)
            await self.page.wait_for_selector(".loading", state="detached", timeout=30000)
        except:
            # No loading indicator, wait a moment for sync to complete
            await self.page.wait_for_timeout(2000)

    async def click_export_button(self):
        """Click the export button and handle download"""
        # Set up download handler
        async with self.page.expect_download() as download_info:
            await self.page.click(self.selectors["export_button"])

        download = await download_info.value
        return {
            "filename": download.suggested_filename,
            "path": await download.path()
        }

    async def navigate_to_employee_management(self):
        """Navigate to employee management page"""
        await self.page.click(self.selectors["employee_management_link"])
        await self.page.wait_for_url("**/nickname-management")

    async def navigate_to_status_page(self):
        """Navigate to status page"""
        await self.page.click(self.selectors["status_link"])
        await self.page.wait_for_url("**/status")

    async def wait_for_real_time_update(self, timeout: int = 10000):
        """Wait for a real-time update to appear"""
        initial_count = await self.get_attendance_count()

        # Wait for count to change (indicating real-time update)
        await self.page.wait_for_function(
            f"() => document.querySelector('{self.selectors['attendance_count']}')?.textContent !== '{initial_count}'",
            timeout=timeout
        )

    async def get_websocket_connection_status(self) -> str:
        """Check WebSocket connection status"""
        try:
            status_element = await self.page.query_selector(self.selectors["websocket_status"])
            if status_element:
                return await status_element.text_content()
        except:
            pass

        # Check via JavaScript if element not found
        return await self.page.evaluate("""
            () => {
                // Check if WebSocket is connected
                if (window.ws && window.ws.readyState === WebSocket.OPEN) {
                    return 'Connected';
                } else if (window.ws && window.ws.readyState === WebSocket.CONNECTING) {
                    return 'Connecting';
                } else {
                    return 'Disconnected';
                }
            }
        """)

    async def get_last_sync_time(self) -> Optional[str]:
        """Get the last sync timestamp"""
        try:
            sync_element = await self.page.query_selector(self.selectors["last_sync_time"])
            if sync_element:
                return await sync_element.text_content()
        except:
            pass

        return None

    async def verify_thai_content_displayed(self) -> bool:
        """Verify that Thai content is properly displayed on dashboard"""
        page_content = await self.page.content()

        # Check for common Thai characters or employee names
        thai_patterns = [
            "ก", "ข", "ค", "ง", "จ",  # Common Thai characters
            "สมชาย", "สมหญิง", "นาย", "นาง"  # Common Thai names
        ]

        for pattern in thai_patterns:
            if pattern in page_content:
                return True

        return False

    async def take_screenshot(self, name: str = "dashboard"):
        """Take a screenshot of the dashboard"""
        timestamp = await self.page.evaluate("() => new Date().toISOString().replace(/[:.]/g, '-')")
        filename = f"{name}_{timestamp}.png"

        await self.page.screenshot(path=f"tests/e2e/screenshots/{filename}")
        return filename

    async def verify_dashboard_elements_present(self) -> Dict[str, bool]:
        """Verify all expected dashboard elements are present"""
        elements_status = {}

        for element_name, selector in self.selectors.items():
            try:
                element = await self.page.query_selector(selector)
                elements_status[element_name] = element is not None
            except:
                elements_status[element_name] = False

        return elements_status

    async def simulate_device_sync(self):
        """Simulate a device sync operation for testing"""
        # This could trigger an API call or WebSocket message
        await self.page.evaluate("""
            () => {
                // Simulate a device sync by triggering any sync-related JavaScript
                if (window.triggerSync) {
                    window.triggerSync();
                } else if (window.syncDevice) {
                    window.syncDevice();
                }
            }
        """)

    async def wait_for_dashboard_data_load(self):
        """Wait for dashboard data to fully load"""
        # Wait for statistics to be populated
        await self.page.wait_for_function(
            """
            () => {
                const employeeCount = document.querySelector('[data-testid="employee-count"]');
                const attendanceCount = document.querySelector('[data-testid="attendance-count"]');

                return (employeeCount && employeeCount.textContent !== '0') ||
                       (attendanceCount && attendanceCount.textContent !== '0');
            }
            """,
            timeout=15000
        )