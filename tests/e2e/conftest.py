"""
E2E Testing Configuration
Supports both CLI-based HTTP testing and browser automation with Playwright
"""

import pytest
import requests
import os
import time
from typing import Generator

# Optional Playwright imports (only for browser-based tests)
try:
    from playwright.sync_api import Page, Browser, Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@pytest.fixture(scope="session")
def app_url() -> str:
    """Base URL for the fingerprint time logger application"""
    return os.environ.get("APP_URL", "http://localhost:5000/fingerprintlogs")


@pytest.fixture(scope="session")
def app_running(app_url: str) -> bool:
    """Ensure the application is running before tests"""
    max_attempts = 5
    health_url = f"{app_url}/health"

    for attempt in range(max_attempts):
        try:
            # Try to reach the health endpoint
            response = requests.get(health_url, timeout=5)
            if response.status_code == 200:
                return True
            else:
                print(f"Attempt {attempt + 1}: Got status {response.status_code} from {health_url}")
        except requests.RequestException as e:
            print(f"Attempt {attempt + 1}: Failed to connect to {health_url}: {e}")
            if attempt < max_attempts - 1:
                time.sleep(2)
                continue

    pytest.skip(f"Application not running at {app_url} (checked {health_url})")


@pytest.fixture
def http_session() -> Generator[requests.Session, None, None]:
    """HTTP session for making requests"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "E2E-Test-Client/1.0",
        "Accept": "application/json, text/html"
    })
    yield session
    session.close()


@pytest.fixture
def api_client(app_url: str, http_session: requests.Session):
    """API client wrapper for making requests"""
    class APIClient:
        def __init__(self, base_url: str, session: requests.Session):
            self.base_url = base_url
            self.session = session

        def get(self, endpoint: str, **kwargs):
            """Make GET request"""
            url = f"{self.base_url}{endpoint}"
            response = self.session.get(url, **kwargs)
            return response

        def post(self, endpoint: str, **kwargs):
            """Make POST request"""
            url = f"{self.base_url}{endpoint}"
            response = self.session.post(url, **kwargs)
            return response

        def health_check(self):
            """Check if application is healthy"""
            try:
                response = self.get("/health")
                return response.status_code == 200
            except:
                return False

        def get_page(self, path: str):
            """Get HTML page content"""
            response = self.get(path)
            if response.status_code == 200:
                return response.text
            return None

        def check_api_endpoint(self, endpoint: str):
            """Check if API endpoint is accessible"""
            try:
                response = self.get(endpoint)
                return response.status_code in [200, 404]  # 404 is also valid (endpoint exists but may have no data)
            except:
                return False

    return APIClient(app_url, http_session)


@pytest.fixture
def test_data():
    """Test data for CLI-based tests"""
    return {
        "expected_pages": [
            "/",  # Dashboard
            "/status",  # Status page
            "/export",  # Export page
            "/nickname-management",  # Nickname management
            "/docs"  # API documentation
        ],
        "api_endpoints": [
            "/api/attendance/",
            "/api/employees/",
            "/api/devices/",
            "/api/system/health",
            "/health"
        ],
        "export_formats": ["csv"],
        "test_employee_data": {
            "badge_number": "TEST001",
            "english_name": "Test Employee",
            "thai_name": "พนักงานทดสอบ"
        }
    }


def pytest_configure(config):
    """Configure custom markers for E2E tests"""
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test")
    config.addinivalue_line("markers", "cli: mark test as CLI-based test")
    config.addinivalue_line("markers", "browser: mark test as browser-based test")
    config.addinivalue_line("markers", "api: mark test as API test")
    config.addinivalue_line("markers", "slow: mark test as slow running")


def pytest_collection_modifyitems(config, items):
    """Configure test collection for E2E tests"""
    # Skip browser tests if playwright is not available
    try:
        import playwright
    except ImportError:
        skip_browser = pytest.mark.skip(reason="playwright not installed")
        for item in items:
            if "browser" in item.keywords:
                item.add_marker(skip_browser)


# Playwright fixtures for browser-based testing
@pytest.fixture(scope="session")
def live_server_url() -> str:
    """URL for the live server (can be different from app_url)"""
    # For production testing, this would be https://emp.thehfhotel.org
    # For local testing, use the local server
    return os.environ.get("LIVE_SERVER_URL", "http://localhost:5000/fingerprintlogs")


@pytest.fixture(scope="session")
def browser_type() -> str:
    """Browser type for Playwright tests"""
    return os.environ.get("BROWSER", "chromium")  # chromium, firefox, or webkit


@pytest.fixture(scope="session")
def headless_mode() -> bool:
    """Whether to run browser in headless mode"""
    return os.environ.get("HEADLESS", "true").lower() == "true"


# Playwright session-scoped fixtures
@pytest.fixture(scope="session")
def playwright():
    """Playwright instance for browser automation"""
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright not available")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright: Playwright, browser_type: str, headless_mode: bool):
    """Shared browser instance for all tests"""
    if browser_type == "firefox":
        browser = playwright.firefox.launch(headless=headless_mode)
    elif browser_type == "webkit":
        browser = playwright.webkit.launch(headless=headless_mode)
    else:
        browser = playwright.chromium.launch(headless=headless_mode)

    yield browser
    browser.close()


@pytest.fixture
def base_url(live_server_url: str) -> str:
    """Base URL for tests - aliases live_server_url to avoid pytest-base-url conflict"""
    return live_server_url


@pytest.fixture(scope="function")
def page(browser: Browser):
    """New page for each test"""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="th-TH"
    )
    page = context.new_page()
    yield page
    context.close()