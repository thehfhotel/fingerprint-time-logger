"""
Enhanced E2E Testing Configuration
Builds upon existing pytest infrastructure with Playwright integration
for comprehensive user workflow testing
"""

import pytest
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from typing import Generator, AsyncGenerator
from datetime import datetime

# Import existing fixtures from base conftest
import sys
sys.path.append(str(Path(__file__).parent.parent))
from conftest import *

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def browser() -> AsyncGenerator[Browser, None]:
    """Launch browser for E2E testing with proper configuration"""
    async with async_playwright() as p:
        # Use Chromium for consistent results
        browser = await p.chromium.launch(
            headless=True,  # Set to False for debugging
            args=[
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--disable-dev-shm-usage",
                "--no-sandbox",  # Required for some CI environments
                "--disable-extensions",
                "--disable-background-timer-throttling",
            ]
        )
        yield browser
        await browser.close()

@pytest.fixture
async def browser_context(browser: Browser) -> AsyncGenerator[BrowserContext, None]:
    """Create browser context with proper configuration for fingerprint system testing"""
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="th-TH",  # Thai locale for localization testing
        timezone_id="Asia/Bangkok",
        # Accept any SSL certificates for local testing
        ignore_https_errors=True,
        # Mock permissions for notifications if needed
        permissions=["notifications"]
    )

    # Enable console logging for debugging
    context.on("console", lambda msg: print(f"Browser console: {msg.text}"))

    yield context
    await context.close()

@pytest.fixture
async def page(browser_context: BrowserContext) -> AsyncGenerator[Page, None]:
    """Create page for testing with proper error handling"""
    page = await browser_context.new_page()

    # Set longer timeout for network requests
    page.set_default_timeout(30000)  # 30 seconds

    # Handle page errors
    page.on("pageerror", lambda err: print(f"Page error: {err}"))
    page.on("requestfailed", lambda req: print(f"Request failed: {req.url}"))

    yield page
    await page.close()

@pytest.fixture
def app_url():
    """Base URL for the fingerprint time logger application"""
    # Use environment variable or default to localhost
    return os.environ.get("APP_URL", "http://localhost:5000")

@pytest.fixture
def app_running(app_url):
    """Ensure the application is running before tests"""
    import requests
    import time

    max_attempts = 10
    for attempt in range(max_attempts):
        try:
            response = requests.get(f"{app_url}/health", timeout=5)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue

    pytest.skip(f"Application not running at {app_url}")

@pytest.fixture
def test_employee_data():
    """Test data for employee workflows including Thai names"""
    return {
        "badge_number": f"E{datetime.now().strftime('%H%M%S')}",  # Unique badge
        "thai_name": "สมชาย ใจดี",
        "english_name": "Somchai Jaidee",
        "department": "IT Department",
        "position": "Software Developer",
        "status": "Active"
    }

@pytest.fixture
def test_attendance_data():
    """Test data for attendance workflow testing"""
    return {
        "device_id": 1,
        "punch_type": 0,  # Check-in
        "timestamp": datetime.now(),
        "status": "Normal"
    }

@pytest.fixture
async def dashboard_page(page: Page, app_url: str, app_running):
    """Navigate to dashboard and return configured page"""
    await page.goto(f"{app_url}/")

    # Wait for dashboard to load
    await page.wait_for_selector("[data-testid='dashboard-content']", timeout=10000)

    return page

@pytest.fixture
async def employee_management_page(page: Page, app_url: str, app_running):
    """Navigate to employee management and return configured page"""
    await page.goto(f"{app_url}/nickname-management")

    # Wait for employee management to load
    await page.wait_for_selector("[data-testid='employee-list']", timeout=10000)

    return page

@pytest.fixture
def screenshot_dir():
    """Directory for storing test screenshots"""
    screenshot_path = Path(__file__).parent / "screenshots"
    screenshot_path.mkdir(exist_ok=True)
    return screenshot_path

@pytest.fixture
async def take_screenshot(page: Page, screenshot_dir: Path):
    """Utility function to take screenshots during tests"""
    async def _screenshot(name: str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = screenshot_dir / f"{name}_{timestamp}.png"
        await page.screenshot(path=str(filepath))
        print(f"Screenshot saved: {filepath}")
        return filepath

    return _screenshot

# Markers for test categorization
@pytest.fixture(autouse=True)
def setup_test_markers(request):
    """Setup test markers for better test organization"""
    # Add marker information to test reports
    if hasattr(request.node, 'get_closest_marker'):
        marker = request.node.get_closest_marker('workflow')
        if marker:
            print(f"Running workflow test: {marker.args[0] if marker.args else 'Unknown'}")

# Custom assertions for E2E testing
class E2EAssertions:
    """Custom assertions for E2E testing"""

    @staticmethod
    async def assert_page_loaded(page: Page, title_contains: str = None):
        """Assert page has loaded properly"""
        await page.wait_for_load_state("networkidle")

        if title_contains:
            title = await page.title()
            assert title_contains.lower() in title.lower(), f"Page title '{title}' should contain '{title_contains}'"

    @staticmethod
    async def assert_element_visible(page: Page, selector: str, timeout: int = 5000):
        """Assert element is visible within timeout"""
        await page.wait_for_selector(selector, state="visible", timeout=timeout)
        is_visible = await page.is_visible(selector)
        assert is_visible, f"Element '{selector}' should be visible"

    @staticmethod
    async def assert_element_contains_text(page: Page, selector: str, text: str):
        """Assert element contains specific text"""
        element_text = await page.text_content(selector)
        assert text in element_text, f"Element '{selector}' should contain text '{text}', but got '{element_text}'"

    @staticmethod
    async def assert_thai_text_displayed(page: Page, thai_text: str):
        """Assert Thai text is properly displayed"""
        # Check if Thai text is visible anywhere on the page
        page_content = await page.content()
        assert thai_text in page_content, f"Thai text '{thai_text}' should be displayed on page"

@pytest.fixture
def e2e_assert():
    """Provide E2E assertion utilities"""
    return E2EAssertions()

# WebSocket testing utilities
class WebSocketTester:
    """Utilities for testing WebSocket connections"""

    def __init__(self, page: Page):
        self.page = page
        self.messages = []

    async def setup_websocket_listener(self, url_pattern: str = "ws://localhost:5000/ws"):
        """Setup WebSocket message listener"""
        await self.page.evaluate("""
            () => {
                window.testWebSocketMessages = [];
                const originalWebSocket = window.WebSocket;

                window.WebSocket = function(url, protocols) {
                    const ws = new originalWebSocket(url, protocols);

                    ws.addEventListener('message', (event) => {
                        window.testWebSocketMessages.push({
                            timestamp: Date.now(),
                            data: event.data
                        });
                    });

                    return ws;
                };
            }
        """)

    async def get_websocket_messages(self):
        """Get captured WebSocket messages"""
        messages = await self.page.evaluate("() => window.testWebSocketMessages || []")
        return messages

    async def wait_for_websocket_message(self, timeout: int = 5000):
        """Wait for at least one WebSocket message"""
        await self.page.wait_for_function(
            "() => window.testWebSocketMessages && window.testWebSocketMessages.length > 0",
            timeout=timeout
        )

@pytest.fixture
async def websocket_tester(page: Page):
    """Provide WebSocket testing utilities"""
    tester = WebSocketTester(page)
    await tester.setup_websocket_listener()
    return tester