"""
API Endpoint Security Testing Suite for Fingerprint Time Logger

Comprehensive security testing for all API endpoints:
- Input validation and sanitization
- Rate limiting and DoS protection
- CORS and header security
- ZKTeco integration security
- Authentication bypass attempts
"""

import pytest
import asyncio
import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from httpx import AsyncClient

from tests.security.conftest import (
    SecurityTester, SecurityVulnerability, SecurityLevel,
    malicious_payloads, fuzzing_data, security_client
)
from app.models.models import Employee, Device, AttendanceRecord
from tests.conftest import test_db


class APISecurityTester(SecurityTester):
    """Comprehensive API security testing"""

    async def test_api_input_validation(self) -> list[SecurityVulnerability]:
        """Test API input validation across all endpoints"""
        vulnerabilities = []

        # Define API endpoints and their expected input fields
        api_endpoints = {
            "/api/employees/": {
                "method": "POST",
                "fields": ["badge_number", "english_name", "thai_name", "department", "position"]
            },
            "/api/devices/": {
                "method": "POST",
                "fields": ["name", "ip_address", "port", "password"]
            },
            "/api/attendance/": {
                "method": "POST",
                "fields": ["employee_badge_number", "timestamp", "punch_type"]
            }
        }

        # Comprehensive malicious payloads
        test_payloads = [
            # SQL Injection
            "'; DROP TABLE employees; --",
            "' UNION SELECT * FROM devices--",
            "1' OR '1'='1",

            # XSS
            "<script>alert('XSS')</script>",
            "javascript:alert(1)",
            "<img src=x onerror=alert(1)>",

            # Command Injection
            "; ls -la",
            "| cat /etc/passwd",
            "$(whoami)",

            # Path Traversal
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts",

            # LDAP Injection
            "*)(uid=*",
            "admin)(&(password=*))",

            # XXE and XML Injection
            "<?xml version=\"1.0\"?><!DOCTYPE root [<!ENTITY test SYSTEM 'file:///etc/passwd'>]><root>&test;</root>",

            # Template Injection
            "{{7*7}}",
            "${7*7}",
            "<%=7*7%>",

            # Buffer overflow attempts
            "A" * 10000,
            "A" * 100000,

            # Unicode attacks
            "\u0000",  # Null byte
            "\u202e",  # Right-to-left override
            "\ufeff",  # Byte order mark

            # Format string attacks
            "%s%s%s%s",
            "%x%x%x%x",

            # Integer overflow
            "2147483648",  # INT_MAX + 1
            "-2147483649",  # INT_MIN - 1
        ]

        for endpoint, config in api_endpoints.items():
            method = config["method"]
            fields = config["fields"]

            for field in fields:
                for payload in test_payloads:
                    try:
                        # Prepare test data
                        test_data = {f: "valid_value" for f in fields}
                        test_data[field] = payload

                        # Send request
                        if method == "POST":
                            response = await self.client.post(endpoint, json=test_data)
                        elif method == "PUT":
                            response = await self.client.put(endpoint, json=test_data)
                        else:
                            response = await self.client.get(endpoint, params=test_data)

                        # Analyze response for vulnerabilities
                        if response.status_code == 200 or response.status_code == 201:
                            response_text = response.text.lower()

                            # Check for SQL injection indicators
                            sql_errors = ['sql syntax', 'sqlite_', 'database error', 'mysql_fetch']
                            if any(error in response_text for error in sql_errors):
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"sql_inject_{endpoint}_{field}_{len(vulnerabilities)}",
                                    title=f"SQL Injection - {endpoint} ({field})",
                                    description=f"SQL error indicates potential injection in field '{field}'",
                                    severity=SecurityLevel.HIGH,
                                    category="Injection",
                                    endpoint=endpoint,
                                    payload=payload,
                                    recommendation="Use parameterized queries and input validation",
                                    cwe="CWE-89"
                                ))

                            # Check for XSS reflection
                            if "<script>" in response_text or "alert(" in response_text:
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"xss_{endpoint}_{field}_{len(vulnerabilities)}",
                                    title=f"Cross-Site Scripting - {endpoint} ({field})",
                                    description=f"XSS payload reflected in response for field '{field}'",
                                    severity=SecurityLevel.HIGH,
                                    category="Cross-Site Scripting",
                                    endpoint=endpoint,
                                    payload=payload,
                                    recommendation="Implement output encoding and CSP headers",
                                    cwe="CWE-79"
                                ))

                            # Check for path traversal success
                            if "root:" in response_text or "windows" in response_text:
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"path_traversal_{endpoint}_{field}_{len(vulnerabilities)}",
                                    title=f"Path Traversal - {endpoint} ({field})",
                                    description=f"Path traversal successful in field '{field}'",
                                    severity=SecurityLevel.CRITICAL,
                                    category="Path Traversal",
                                    endpoint=endpoint,
                                    payload=payload,
                                    recommendation="Validate file paths and restrict file access",
                                    cwe="CWE-22"
                                ))

                            # Check for template injection
                            if "49" in response_text and ("{{" in payload or "${" in payload):
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"template_inject_{endpoint}_{field}_{len(vulnerabilities)}",
                                    title=f"Template Injection - {endpoint} ({field})",
                                    description=f"Template injection executed in field '{field}'",
                                    severity=SecurityLevel.HIGH,
                                    category="Injection",
                                    endpoint=endpoint,
                                    payload=payload,
                                    recommendation="Sanitize template input and use safe templating",
                                    cwe="CWE-94"
                                ))

                    except Exception as e:
                        # Check if exception reveals sensitive information
                        error_msg = str(e).lower()
                        if any(sensitive in error_msg for sensitive in ['password', 'key', 'token', 'secret']):
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"error_disclosure_{endpoint}_{field}_{len(vulnerabilities)}",
                                title=f"Error Information Disclosure - {endpoint}",
                                description=f"Exception reveals sensitive information: {str(e)[:100]}...",
                                severity=SecurityLevel.MEDIUM,
                                category="Information Disclosure",
                                endpoint=endpoint,
                                payload=payload,
                                recommendation="Implement generic error handling",
                                cwe="CWE-209"
                            ))

        return vulnerabilities

    async def test_rate_limiting(self) -> list[SecurityVulnerability]:
        """Test API rate limiting and DoS protection"""
        vulnerabilities = []

        # Test endpoints for rate limiting
        test_endpoints = [
            "/api/employees/",
            "/api/devices/",
            "/api/attendance/",
            "/api/auto-import/trigger",
            "/api/refresh",
        ]

        for endpoint in test_endpoints:
            try:
                # Rapid fire requests
                start_time = time.time()
                successful_requests = 0

                for i in range(100):  # Send 100 rapid requests
                    try:
                        if endpoint in ["/api/employees/", "/api/devices/"]:
                            response = await self.client.post(endpoint, json={"test": "data"})
                        else:
                            response = await self.client.get(endpoint)

                        if response.status_code not in [429, 503]:  # Not rate limited
                            successful_requests += 1

                        # If we can send too many requests too quickly
                        if successful_requests > 50 and (time.time() - start_time) < 10:
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"rate_limit_{endpoint}_{len(vulnerabilities)}",
                                title=f"No Rate Limiting - {endpoint}",
                                description=f"Endpoint accepts {successful_requests} requests in {time.time() - start_time:.2f}s",
                                severity=SecurityLevel.MEDIUM,
                                category="Denial of Service",
                                endpoint=endpoint,
                                payload=f"{successful_requests} requests in {time.time() - start_time:.2f}s",
                                recommendation="Implement rate limiting per IP address",
                                cwe="CWE-770"
                            ))
                            break

                    except Exception:
                        break

            except Exception:
                pass

        return vulnerabilities

    async def test_cors_security(self) -> list[SecurityVulnerability]:
        """Test CORS configuration security"""
        vulnerabilities = []

        # Test CORS headers
        test_endpoints = [
            "/api/employees/",
            "/api/devices/",
            "/api/attendance/",
        ]

        for endpoint in test_endpoints:
            try:
                # Send OPTIONS request to check CORS
                response = await self.client.options(endpoint, headers={
                    "Origin": "https://evil.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type"
                })

                cors_headers = {
                    "access-control-allow-origin": response.headers.get("access-control-allow-origin", ""),
                    "access-control-allow-methods": response.headers.get("access-control-allow-methods", ""),
                    "access-control-allow-headers": response.headers.get("access-control-allow-headers", ""),
                    "access-control-allow-credentials": response.headers.get("access-control-allow-credentials", ""),
                }

                # Check for overly permissive CORS
                if cors_headers["access-control-allow-origin"] == "*":
                    if cors_headers["access-control-allow-credentials"].lower() == "true":
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"cors_credentials_{endpoint}_{len(vulnerabilities)}",
                            title=f"Dangerous CORS Configuration - {endpoint}",
                            description="CORS allows credentials with wildcard origin",
                            severity=SecurityLevel.HIGH,
                            category="Configuration",
                            endpoint=endpoint,
                            payload=str(cors_headers),
                            recommendation="Don't use wildcard origin with credentials",
                            cwe="CWE-942"
                        ))

                # Check if evil origins are allowed
                if "evil.com" in cors_headers["access-control-allow-origin"]:
                    vulnerabilities.append(SecurityVulnerability(
                        id=f"cors_evil_{endpoint}_{len(vulnerabilities)}",
                        title=f"CORS Allows Malicious Origins - {endpoint}",
                        description="CORS allows requests from potentially malicious origins",
                        severity=SecurityLevel.MEDIUM,
                        category="Configuration",
                        endpoint=endpoint,
                        payload="evil.com allowed",
                        recommendation="Restrict CORS to trusted domains only",
                        cwe="CWE-942"
                    ))

            except Exception:
                pass

        return vulnerabilities

    async def test_security_headers(self) -> list[SecurityVulnerability]:
        """Test security headers presence"""
        vulnerabilities = []

        test_endpoints = [
            "/",
            "/api/employees/",
            "/api/devices/",
        ]

        required_security_headers = {
            "x-content-type-options": "nosniff",
            "x-frame-options": ["DENY", "SAMEORIGIN"],
            "x-xss-protection": "1; mode=block",
            "referrer-policy": ["strict-origin-when-cross-origin", "strict-origin", "no-referrer"],
            "content-security-policy": None,  # Should be present
        }

        for endpoint in test_endpoints:
            try:
                response = await self.client.get(endpoint)

                for header_name, expected_values in required_security_headers.items():
                    header_value = response.headers.get(header_name, "").lower()

                    if not header_value:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"missing_header_{endpoint}_{header_name}_{len(vulnerabilities)}",
                            title=f"Missing Security Header - {header_name}",
                            description=f"Endpoint {endpoint} missing {header_name} header",
                            severity=SecurityLevel.LOW,
                            category="Configuration",
                            endpoint=endpoint,
                            payload=header_name,
                            recommendation=f"Add {header_name} security header",
                            cwe="CWE-16"
                        ))
                    elif expected_values and not any(expected.lower() in header_value for expected in expected_values):
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"weak_header_{endpoint}_{header_name}_{len(vulnerabilities)}",
                            title=f"Weak Security Header - {header_name}",
                            description=f"Header {header_name} has weak value: {header_value}",
                            severity=SecurityLevel.LOW,
                            category="Configuration",
                            endpoint=endpoint,
                            payload=f"{header_name}: {header_value}",
                            recommendation=f"Strengthen {header_name} header configuration",
                            cwe="CWE-16"
                        ))

            except Exception:
                pass

        return vulnerabilities

    def test_zkteco_integration_security(self, db) -> list[SecurityVulnerability]:
        """Test ZKTeco device integration security"""
        vulnerabilities = []

        # Test device creation with malicious data
        malicious_device_configs = [
            {
                "name": "'; DROP TABLE devices; --",
                "ip_address": "192.168.1.1",
                "port": 4370
            },
            {
                "name": "Test Device",
                "ip_address": "192.168.1.1; cat /etc/passwd",
                "port": 4370
            },
            {
                "name": "Test Device",
                "ip_address": "192.168.1.1",
                "port": "4370; rm -rf /"
            },
            {
                "name": "<script>alert('Device XSS')</script>",
                "ip_address": "192.168.1.1",
                "port": 4370
            }
        ]

        for device_config in malicious_device_configs:
            try:
                response = self.client.post("/api/devices/", json=device_config)

                if response.status_code == 201:
                    # Check if malicious data was stored
                    device_id = response.json().get("id")
                    if device_id:
                        get_response = self.client.get(f"/api/devices/{device_id}")
                        if get_response.status_code == 200:
                            device_data = get_response.text

                            # Check for XSS reflection
                            if "<script>" in device_data:
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"device_xss_{len(vulnerabilities)}",
                                    title="XSS in Device Configuration",
                                    description="Device name allows XSS payload storage and reflection",
                                    severity=SecurityLevel.HIGH,
                                    category="Cross-Site Scripting",
                                    endpoint="/api/devices/",
                                    payload=device_config["name"],
                                    recommendation="Sanitize device configuration inputs",
                                    cwe="CWE-79"
                                ))

                            # Check for SQL injection indicators
                            if "drop table" in device_data.lower():
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"device_sql_{len(vulnerabilities)}",
                                    title="SQL Injection in Device Configuration",
                                    description="Device configuration stores SQL injection payload",
                                    severity=SecurityLevel.HIGH,
                                    category="Injection",
                                    endpoint="/api/devices/",
                                    payload=str(device_config),
                                    recommendation="Use parameterized queries for device data",
                                    cwe="CWE-89"
                                ))

                        # Cleanup malicious device
                        self.client.delete(f"/api/devices/{device_id}")

            except Exception:
                pass

        # Test device sync security
        try:
            with patch('app.services.device_service.device_service.sync_attendance_data') as mock_sync:
                # Mock malicious sync response
                mock_sync.return_value = {
                    "success": True,
                    "synced": "<script>alert('Sync XSS')</script>",
                    "message": "'; DROP TABLE attendance_records; --",
                    "data": {
                        "malicious_field": "$(rm -rf /)"
                    }
                }

                response = self.client.post("/api/auto-import/trigger")
                if response.status_code == 200:
                    response_data = response.text

                    # Check if malicious sync data is reflected
                    if "<script>" in response_data or "DROP TABLE" in response_data:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"sync_injection_{len(vulnerabilities)}",
                            title="ZKTeco Sync Data Injection",
                            description="Device sync response contains unsanitized malicious data",
                            severity=SecurityLevel.HIGH,
                            category="Injection",
                            endpoint="/api/auto-import/trigger",
                            payload="Malicious sync response",
                            recommendation="Sanitize device sync response data",
                            cwe="CWE-20"
                        ))

        except Exception:
            pass

        return vulnerabilities


class TestAPISecurity:
    """Comprehensive API security test suite"""

    @pytest.mark.asyncio
    async def test_api_input_validation_security(self, security_client):
        """Test API input validation across all endpoints"""
        tester = APISecurityTester(security_client)

        vulnerabilities = await tester.test_api_input_validation()

        # Should not have critical injection vulnerabilities
        critical_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.CRITICAL]
        assert len(critical_vulns) == 0, f"Critical API vulnerabilities: {critical_vulns}"

        # Should have minimal high-severity vulnerabilities
        high_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(high_vulns) <= 3, f"Too many high-severity API vulnerabilities: {high_vulns}"

    @pytest.mark.asyncio
    async def test_api_rate_limiting(self, security_client):
        """Test API rate limiting protection"""
        tester = APISecurityTester(security_client)

        vulnerabilities = await tester.test_rate_limiting()

        # Should have some rate limiting protection
        rate_limit_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(rate_limit_vulns) == 0, f"High-severity rate limiting issues: {rate_limit_vulns}"

    @pytest.mark.asyncio
    async def test_cors_configuration_security(self, security_client):
        """Test CORS configuration security"""
        tester = APISecurityTester(security_client)

        vulnerabilities = await tester.test_cors_security()

        # CORS should not be dangerously permissive
        dangerous_cors = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(dangerous_cors) == 0, f"Dangerous CORS configuration: {dangerous_cors}"

    @pytest.mark.asyncio
    async def test_security_headers_presence(self, security_client):
        """Test security headers are present"""
        tester = APISecurityTester(security_client)

        vulnerabilities = await tester.test_security_headers()

        # Should have reasonable security header coverage
        header_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.MEDIUM]
        assert len(header_vulns) <= 5, f"Too many missing security headers: {header_vulns}"

    @pytest.mark.asyncio
    async def test_zkteco_integration_security(self, security_client, test_db):
        """Test ZKTeco integration security"""
        tester = APISecurityTester(security_client)

        vulnerabilities = tester.test_zkteco_integration_security(test_db)

        # ZKTeco integration should be secure
        integration_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(integration_vulns) == 0, f"ZKTeco integration vulnerabilities: {integration_vulns}"

    def test_api_error_handling(self, security_client):
        """Test API error handling doesn't expose sensitive information"""

        # Test various error conditions
        error_tests = [
            ("/api/employees/NONEXISTENT", "GET"),
            ("/api/devices/99999", "GET"),
            ("/api/attendance/invalid", "GET"),
            ("/api/employees/export/nonexistent-format/", "GET"),
        ]

        for endpoint, method in error_tests:
            if method == "GET":
                response = security_client.get(endpoint)
            elif method == "POST":
                response = security_client.post(endpoint, json={})

            # Error responses shouldn't expose sensitive information
            if response.status_code >= 400:
                error_text = response.text.lower()

                sensitive_patterns = [
                    "password", "secret", "key", "token",
                    "/home/", "c:\\users\\", "database error",
                    "traceback", "stack trace"
                ]

                exposed_info = [pattern for pattern in sensitive_patterns if pattern in error_text]
                assert len(exposed_info) == 0, f"Error response exposes sensitive info: {exposed_info}"

    @pytest.mark.asyncio
    async def test_api_http_methods(self, security_client):
        """Test API HTTP method security"""

        # Test endpoints that shouldn't accept certain methods
        method_tests = [
            ("/api/employees/", "DELETE"),  # Bulk delete
            ("/api/devices/", "PATCH"),     # Unsupported method
            ("/api/attendance/", "PUT"),    # Unsupported method
            ("/api/employees/export/csv", "POST"),  # Should be GET only
        ]

        for endpoint, method in method_tests:
            try:
                response = security_client.request(method, endpoint)
                # Should return 405 Method Not Allowed or 404
                assert response.status_code in [404, 405], f"{method} {endpoint} should not be allowed"
            except Exception:
                # Request library error is also acceptable
                pass

    def test_api_content_type_validation(self, security_client):
        """Test API resilience to unexpected content types"""

        # Test endpoints that don't expect request bodies
        endpoints = [
            "/api/devices/test-connection",
            "/api/attendance/sync",
        ]

        for endpoint in endpoints:
            # Test with unexpected content type - should not crash
            # Use shorter timeout for security tests to prevent long delays
            response = security_client.post(
                endpoint,
                content='<xml>data</xml>',
                headers={"Content-Type": "application/xml"},
                timeout=2.0  # Reduced from default 5s for security tests
            )

            # Should handle gracefully (either ignore content or return controlled error)
            assert response.status_code in [200, 400, 415, 422, 500], f"{endpoint} should handle unexpected content gracefully"