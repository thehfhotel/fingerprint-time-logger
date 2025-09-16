"""
Status Page Object Model
Encapsulates system status and monitoring interactions for E2E testing
"""

from playwright.async_api import Page
from typing import Dict, List, Optional


class StatusPage:
    """Page object for the system status and monitoring interface"""

    def __init__(self, page: Page):
        self.page = page

        # Selectors for status page elements
        self.selectors = {
            "title": "h1",
            "system_status": "[data-testid='system-status']",
            "database_status": "[data-testid='database-status']",
            "device_status": "[data-testid='device-status']",
            "websocket_status": "[data-testid='websocket-status']",
            "api_status": "[data-testid='api-status']",

            # Status indicators
            "status_indicator": "[data-testid='status-indicator']",
            "status_healthy": "[data-testid='status-healthy']",
            "status_warning": "[data-testid='status-warning']",
            "status_error": "[data-testid='status-error']",

            # Device monitoring
            "device_list": "[data-testid='device-list']",
            "device_card": "[data-testid='device-card']",
            "device_name": "[data-testid='device-name']",
            "device_ip": "[data-testid='device-ip']",
            "device_connection_status": "[data-testid='device-connection-status']",
            "device_last_sync": "[data-testid='device-last-sync']",
            "test_connection_button": "[data-testid='test-connection']",
            "sync_device_button": "[data-testid='sync-device']",

            # System metrics
            "uptime": "[data-testid='uptime']",
            "cpu_usage": "[data-testid='cpu-usage']",
            "memory_usage": "[data-testid='memory-usage']",
            "disk_usage": "[data-testid='disk-usage']",
            "active_connections": "[data-testid='active-connections']",

            # Database information
            "database_size": "[data-testid='database-size']",
            "total_employees": "[data-testid='total-employees']",
            "total_records": "[data-testid='total-records']",
            "last_backup": "[data-testid='last-backup']",

            # Recent activity
            "recent_activity": "[data-testid='recent-activity']",
            "activity_log": "[data-testid='activity-log']",
            "activity_item": "[data-testid='activity-item']",

            # Error logs
            "error_log": "[data-testid='error-log']",
            "error_item": "[data-testid='error-item']",
            "clear_logs_button": "[data-testid='clear-logs']",

            # Actions
            "refresh_button": "[data-testid='refresh-status']",
            "export_logs_button": "[data-testid='export-logs']",
            "system_info_button": "[data-testid='system-info']",

            # Alerts and notifications
            "alert_banner": "[data-testid='alert-banner']",
            "notification": "[data-testid='notification']",
            "dismiss_alert": "[data-testid='dismiss-alert']",

            # Loading states
            "loading_spinner": ".loading-spinner",
            "status_loading": "[data-testid='status-loading']"
        }

    async def navigate_to(self, base_url: str):
        """Navigate to status page"""
        await self.page.goto(f"{base_url}/status")
        await self.wait_for_load()

    async def wait_for_load(self):
        """Wait for status page to fully load"""
        # Wait for main content to be visible
        await self.page.wait_for_selector("h1", timeout=10000)

        # Wait for system status to load
        await self.page.wait_for_selector(self.selectors["system_status"], timeout=10000)

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
        """Get the status page title"""
        return await self.page.text_content(self.selectors["title"])

    async def get_overall_system_status(self) -> str:
        """Get the overall system status"""
        try:
            status_element = await self.page.query_selector(self.selectors["system_status"])
            if status_element:
                status_text = await status_element.text_content()

                # Determine status based on indicators
                if await self.page.query_selector(f"{self.selectors['system_status']} {self.selectors['status_healthy']}"):
                    return "healthy"
                elif await self.page.query_selector(f"{self.selectors['system_status']} {self.selectors['status_warning']}"):
                    return "warning"
                elif await self.page.query_selector(f"{self.selectors['system_status']} {self.selectors['status_error']}"):
                    return "error"

                return "unknown"
        except:
            return "unavailable"

    async def get_component_statuses(self) -> Dict[str, str]:
        """Get status of all system components"""
        components = {
            "database": self.selectors["database_status"],
            "device": self.selectors["device_status"],
            "websocket": self.selectors["websocket_status"],
            "api": self.selectors["api_status"]
        }

        statuses = {}

        for component_name, selector in components.items():
            try:
                component_element = await self.page.query_selector(selector)
                if component_element:
                    # Check for status indicators
                    if await component_element.query_selector(self.selectors["status_healthy"].replace("[data-testid='status-healthy']", ".healthy, .success, .ok")):
                        statuses[component_name] = "healthy"
                    elif await component_element.query_selector(self.selectors["status_warning"].replace("[data-testid='status-warning']", ".warning, .warn")):
                        statuses[component_name] = "warning"
                    elif await component_element.query_selector(self.selectors["status_error"].replace("[data-testid='status-error']", ".error, .fail")):
                        statuses[component_name] = "error"
                    else:
                        status_text = await component_element.text_content()
                        statuses[component_name] = "healthy" if "ok" in status_text.lower() or "connected" in status_text.lower() else "unknown"
                else:
                    statuses[component_name] = "unavailable"
            except:
                statuses[component_name] = "error"

        return statuses

    async def get_device_statuses(self) -> List[Dict[str, str]]:
        """Get status of all connected devices"""
        devices = []

        try:
            device_cards = await self.page.query_selector_all(self.selectors["device_card"])

            for card in device_cards:
                try:
                    name_element = await card.query_selector(self.selectors["device_name"].replace("[data-testid='device-name']", "[data-testid='device-name']"))
                    ip_element = await card.query_selector(self.selectors["device_ip"].replace("[data-testid='device-ip']", "[data-testid='device-ip']"))
                    status_element = await card.query_selector(self.selectors["device_connection_status"].replace("[data-testid='device-connection-status']", "[data-testid='device-connection-status']"))
                    sync_element = await card.query_selector(self.selectors["device_last_sync"].replace("[data-testid='device-last-sync']", "[data-testid='device-last-sync']"))

                    device = {
                        "name": await name_element.text_content() if name_element else "",
                        "ip": await ip_element.text_content() if ip_element else "",
                        "status": await status_element.text_content() if status_element else "",
                        "last_sync": await sync_element.text_content() if sync_element else ""
                    }
                    devices.append(device)
                except:
                    continue
        except:
            pass

        return devices

    async def test_device_connection(self, device_identifier: str):
        """Test connection to a specific device"""
        device_card = await self.find_device_card(device_identifier)

        if device_card:
            test_button = await device_card.query_selector(self.selectors["test_connection_button"].replace("[data-testid='test-connection']", "[data-testid='test-connection']"))
            if test_button:
                await test_button.click()

                # Wait for test result
                await self.page.wait_for_timeout(3000)  # Allow time for connection test
                await self.wait_for_load()

    async def sync_device(self, device_identifier: str):
        """Trigger sync for a specific device"""
        device_card = await self.find_device_card(device_identifier)

        if device_card:
            sync_button = await device_card.query_selector(self.selectors["sync_device_button"].replace("[data-testid='sync-device']", "[data-testid='sync-device']"))
            if sync_button:
                await sync_button.click()

                # Wait for sync to complete
                await self.page.wait_for_timeout(5000)  # Allow time for sync
                await self.wait_for_load()

    async def find_device_card(self, identifier: str):
        """Find device card by name or IP"""
        cards = await self.page.query_selector_all(self.selectors["device_card"])

        for card in cards:
            try:
                name_element = await card.query_selector("[data-testid='device-name']")
                ip_element = await card.query_selector("[data-testid='device-ip']")

                name = await name_element.text_content() if name_element else ""
                ip = await ip_element.text_content() if ip_element else ""

                if identifier in name or identifier in ip:
                    return card
            except:
                continue

        return None

    async def get_system_metrics(self) -> Dict[str, str]:
        """Get system performance metrics"""
        metrics = {}

        metric_selectors = {
            "uptime": self.selectors["uptime"],
            "cpu_usage": self.selectors["cpu_usage"],
            "memory_usage": self.selectors["memory_usage"],
            "disk_usage": self.selectors["disk_usage"],
            "active_connections": self.selectors["active_connections"]
        }

        for metric_name, selector in metric_selectors.items():
            try:
                element = await self.page.query_selector(selector)
                if element:
                    metrics[metric_name] = await element.text_content()
                else:
                    metrics[metric_name] = "N/A"
            except:
                metrics[metric_name] = "Error"

        return metrics

    async def get_database_info(self) -> Dict[str, str]:
        """Get database information"""
        db_info = {}

        db_selectors = {
            "size": self.selectors["database_size"],
            "employees": self.selectors["total_employees"],
            "records": self.selectors["total_records"],
            "last_backup": self.selectors["last_backup"]
        }

        for info_name, selector in db_selectors.items():
            try:
                element = await self.page.query_selector(selector)
                if element:
                    db_info[info_name] = await element.text_content()
                else:
                    db_info[info_name] = "N/A"
            except:
                db_info[info_name] = "Error"

        return db_info

    async def get_recent_activity(self) -> List[Dict[str, str]]:
        """Get recent system activity"""
        activities = []

        try:
            activity_items = await self.page.query_selector_all(self.selectors["activity_item"])

            for item in activity_items:
                try:
                    activity_text = await item.text_content()
                    # Parse activity text for timestamp, action, etc.
                    # This would depend on the actual format of activity items
                    activity = {
                        "text": activity_text,
                        "timestamp": "",  # Would extract from text
                        "action": "",     # Would extract from text
                        "user": ""        # Would extract from text
                    }
                    activities.append(activity)
                except:
                    continue
        except:
            pass

        return activities

    async def get_error_logs(self) -> List[str]:
        """Get recent error logs"""
        errors = []

        try:
            error_items = await self.page.query_selector_all(self.selectors["error_item"])

            for item in error_items:
                try:
                    error_text = await item.text_content()
                    errors.append(error_text)
                except:
                    continue
        except:
            pass

        return errors

    async def clear_logs(self):
        """Clear system logs"""
        try:
            await self.page.click(self.selectors["clear_logs_button"])

            # Wait for confirmation dialog if it appears
            try:
                await self.page.wait_for_selector("[data-testid='confirm-clear-logs']", timeout=2000)
                await self.page.click("[data-testid='confirm-clear-logs']")
            except:
                pass

            # Wait for logs to be cleared
            await self.wait_for_load()
        except:
            pass

    async def refresh_status(self):
        """Refresh all status information"""
        await self.page.click(self.selectors["refresh_button"])
        await self.wait_for_load()

    async def export_logs(self):
        """Export system logs"""
        async with self.page.expect_download() as download_info:
            await self.page.click(self.selectors["export_logs_button"])

        download = await download_info.value
        return {
            "filename": download.suggested_filename,
            "path": await download.path()
        }

    async def get_alerts(self) -> List[str]:
        """Get active system alerts"""
        alerts = []

        try:
            alert_elements = await self.page.query_selector_all(self.selectors["alert_banner"])

            for alert in alert_elements:
                try:
                    alert_text = await alert.text_content()
                    alerts.append(alert_text)
                except:
                    continue
        except:
            pass

        return alerts

    async def dismiss_alert(self, alert_index: int = 0):
        """Dismiss a system alert"""
        try:
            alert_elements = await self.page.query_selector_all(self.selectors["alert_banner"])

            if alert_index < len(alert_elements):
                alert = alert_elements[alert_index]
                dismiss_button = await alert.query_selector(self.selectors["dismiss_alert"].replace("[data-testid='dismiss-alert']", "[data-testid='dismiss-alert']"))

                if dismiss_button:
                    await dismiss_button.click()
        except:
            pass

    async def wait_for_status_update(self, component: str, expected_status: str, timeout: int = 30000):
        """Wait for a specific component status to change"""
        component_selector = self.selectors.get(f"{component}_status")

        if not component_selector:
            return False

        try:
            await self.page.wait_for_function(
                f"""
                () => {{
                    const element = document.querySelector('{component_selector}');
                    if (!element) return false;

                    const text = element.textContent.toLowerCase();
                    return text.includes('{expected_status.lower()}');
                }}
                """,
                timeout=timeout
            )
            return True
        except:
            return False

    async def verify_websocket_connection(self) -> bool:
        """Verify WebSocket connection is active"""
        try:
            # Check WebSocket status indicator
            ws_status = await self.page.query_selector(self.selectors["websocket_status"])
            if ws_status:
                status_text = await ws_status.text_content()
                return "connected" in status_text.lower() or "active" in status_text.lower()

            # Fallback: check via JavaScript
            ws_status_js = await self.page.evaluate("""
                () => {
                    if (window.ws && window.ws.readyState === WebSocket.OPEN) {
                        return 'connected';
                    }
                    return 'disconnected';
                }
            """)

            return ws_status_js == 'connected'
        except:
            return False

    async def take_screenshot(self, name: str = "status"):
        """Take a screenshot of the status page"""
        timestamp = await self.page.evaluate("() => new Date().toISOString().replace(/[:.]/g, '-')")
        filename = f"{name}_{timestamp}.png"

        await self.page.screenshot(path=f"tests/e2e/screenshots/{filename}")
        return filename

    async def get_system_health_score(self) -> float:
        """Calculate overall system health score based on component statuses"""
        try:
            statuses = await self.get_component_statuses()

            total_components = len(statuses)
            healthy_components = sum(1 for status in statuses.values() if status == "healthy")
            warning_components = sum(1 for status in statuses.values() if status == "warning")

            if total_components == 0:
                return 0.0

            # Calculate weighted score: healthy = 1.0, warning = 0.5, error = 0.0
            score = (healthy_components + (warning_components * 0.5)) / total_components
            return round(score, 2)
        except:
            return 0.0

    async def wait_for_all_systems_healthy(self, timeout: int = 60000):
        """Wait for all system components to be in healthy state"""
        try:
            await self.page.wait_for_function(
                """
                () => {
                    const healthyIndicators = document.querySelectorAll('[data-testid*="status"] .healthy, [data-testid*="status"] .success, [data-testid*="status"] .ok');
                    const errorIndicators = document.querySelectorAll('[data-testid*="status"] .error, [data-testid*="status"] .fail');

                    return healthyIndicators.length >= 4 && errorIndicators.length === 0;
                }
                """,
                timeout=timeout
            )
            return True
        except:
            return False