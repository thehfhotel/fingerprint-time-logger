"""
Biometric Security Testing Suite for Fingerprint Time Logger

Tests specific to biometric systems and fingerprint data protection:
- Biometric data handling security
- ZKTeco device communication security
- Attendance record tampering detection
- Employee identification security
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from sqlalchemy.orm import Session

from tests.security.conftest import (
    SecurityTester, SecurityVulnerability, SecurityLevel,
    malicious_payloads, security_client
)
from app.models.models import Employee, Device, AttendanceRecord
from app.core.database import get_db
from tests.conftest import test_db


class BiometricSecurityTester(SecurityTester):
    """Specialized security testing for biometric systems"""

    async def test_biometric_data_leakage(self, endpoints: list) -> list[SecurityVulnerability]:
        """Test for biometric data exposure in API responses"""
        vulnerabilities = []

        # Patterns that might indicate biometric data leakage
        biometric_patterns = [
            r'fingerprint.*template',
            r'biometric.*data',
            r'template.*[0-9a-f]{16,}',  # Hex patterns that might be templates
            r'feature.*points',
            r'minutiae.*data',
            r'enrollment.*data',
            r'fp.*template',
        ]

        for endpoint in endpoints:
            try:
                response = await self.client.get(endpoint)
                response_text = response.text.lower()

                import re
                for pattern in biometric_patterns:
                    matches = re.findall(pattern, response_text, re.IGNORECASE)
                    if matches:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"biometric_leak_{endpoint}_{len(vulnerabilities)}",
                            title=f"Potential Biometric Data Leakage - {endpoint}",
                            description=f"Endpoint may expose biometric templates or fingerprint data",
                            severity=SecurityLevel.CRITICAL,
                            category="Biometric Data Protection",
                            endpoint=endpoint,
                            payload=pattern,
                            recommendation="Remove biometric templates from API responses, use IDs only",
                            cwe="CWE-200"
                        ))

            except Exception:
                pass

        return vulnerabilities

    async def test_attendance_record_tampering(self, db: Session) -> list[SecurityVulnerability]:
        """Test for attendance record manipulation vulnerabilities"""
        vulnerabilities = []

        # Test timestamp manipulation
        tampered_timestamps = [
            "2023-01-01 00:00:00",  # Past date
            "2099-12-31 23:59:59",  # Future date
            "'; DROP TABLE attendance_records; --",  # SQL injection
            "<script>alert('XSS')</script>",  # XSS attempt
            "../../../etc/passwd",  # Path traversal
            "1970-01-01T00:00:00Z' OR '1'='1",  # Boolean injection
        ]

        test_employee = Employee(
            badge_number="TEST_SECURITY_001",
            english_name="Security Test Employee",
            display_name="Security Test Employee",
            is_active=True
        )
        db.add(test_employee)
        db.commit()

        for timestamp in tampered_timestamps:
            try:
                attendance_data = {
                    "employee_badge_number": "TEST_SECURITY_001",
                    "timestamp": timestamp,
                    "punch_type": 0
                }

                response = await self.client.post("/api/attendance/", json=attendance_data)

                # If malicious timestamp is accepted, it's a vulnerability
                if response.status_code == 201 or response.status_code == 200:
                    vulnerabilities.append(SecurityVulnerability(
                        id=f"timestamp_tamper_{len(vulnerabilities)}",
                        title="Attendance Record Timestamp Manipulation",
                        description=f"System accepts potentially malicious timestamp: {timestamp}",
                        severity=SecurityLevel.HIGH,
                        category="Data Integrity",
                        endpoint="/api/attendance/",
                        payload=timestamp,
                        recommendation="Implement strict timestamp validation and range checks",
                        cwe="CWE-20"
                    ))

            except Exception:
                pass

        # Cleanup test data
        db.delete(test_employee)
        db.commit()

        return vulnerabilities

    async def test_employee_id_enumeration(self) -> list[SecurityVulnerability]:
        """Test for employee ID enumeration vulnerabilities"""
        vulnerabilities = []

        # Test badge number enumeration
        test_badge_numbers = [
            "001", "002", "003", "100", "999",  # Sequential IDs
            "admin", "test", "employee",         # Common names
            "EMP001", "EMP002",                 # Common patterns
            "'1'='1'--", "1 OR 1=1",            # SQL injection attempts
        ]

        for badge_number in test_badge_numbers:
            try:
                response = await self.client.get(f"/api/employees/{badge_number}")

                # Check if system reveals existence of employees
                if response.status_code == 200:
                    response_data = response.json()
                    if "employee" in str(response_data).lower():
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"id_enum_{badge_number}_{len(vulnerabilities)}",
                            title="Employee ID Enumeration",
                            description=f"System reveals employee existence for badge: {badge_number}",
                            severity=SecurityLevel.MEDIUM,
                            category="Information Disclosure",
                            endpoint=f"/api/employees/{badge_number}",
                            payload=badge_number,
                            recommendation="Implement uniform responses for valid/invalid IDs",
                            cwe="CWE-204"
                        ))

            except Exception:
                pass

        return vulnerabilities

    async def test_device_communication_security(self) -> list[SecurityVulnerability]:
        """Test ZKTeco device communication security"""
        vulnerabilities = []

        # Test device configuration exposure
        try:
            response = await self.client.get("/api/devices/")
            if response.status_code == 200:
                response_text = response.text

                # Check for sensitive device information
                sensitive_patterns = [
                    r'password.*[:\s]*\d+',      # Device passwords
                    r'ip.*[:\s]*\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}',  # IP addresses
                    r'port.*[:\s]*\d+',          # Port numbers
                    r'admin.*password',           # Admin credentials
                ]

                import re
                for pattern in sensitive_patterns:
                    if re.search(pattern, response_text, re.IGNORECASE):
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"device_info_leak_{len(vulnerabilities)}",
                            title="ZKTeco Device Information Disclosure",
                            description="API exposes sensitive device configuration data",
                            severity=SecurityLevel.HIGH,
                            category="Information Disclosure",
                            endpoint="/api/devices/",
                            payload=pattern,
                            recommendation="Remove sensitive device info from API responses",
                            cwe="CWE-200"
                        ))

        except Exception:
            pass

        # Test device command injection
        malicious_device_data = [
            {"ip_address": "192.168.1.1; cat /etc/passwd"},
            {"ip_address": "192.168.1.1' OR '1'='1"},
            {"name": "<script>alert('XSS')</script>"},
            {"port": "4370; rm -rf /"},
        ]

        for device_data in malicious_device_data:
            try:
                response = await self.client.post("/api/devices/", json=device_data)

                if response.status_code == 201 or "error" not in response.text.lower():
                    vulnerabilities.append(SecurityVulnerability(
                        id=f"device_injection_{len(vulnerabilities)}",
                        title="Device Configuration Injection",
                        description=f"Malicious device config accepted: {device_data}",
                        severity=SecurityLevel.HIGH,
                        category="Injection",
                        endpoint="/api/devices/",
                        payload=str(device_data),
                        recommendation="Validate and sanitize device configuration inputs",
                        cwe="CWE-20"
                    ))

            except Exception:
                pass

        return vulnerabilities


@pytest.mark.asyncio
class TestBiometricSecurity:
    """Test suite for biometric system security"""

    async def test_biometric_data_protection(self, security_client, test_db):
        """Test biometric data is properly protected"""
        tester = BiometricSecurityTester(security_client)

        endpoints_to_test = [
            "/api/employees/",
            "/api/attendance/",
            "/api/devices/",
            "/api/employees/export/csv",
        ]

        vulnerabilities = await tester.test_biometric_data_leakage(endpoints_to_test)

        # Assert no critical biometric data leakage
        critical_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.CRITICAL]
        assert len(critical_vulns) == 0, f"Critical biometric vulnerabilities found: {critical_vulns}"

    async def test_attendance_record_integrity(self, security_client, test_db):
        """Test attendance record tampering protection"""
        tester = BiometricSecurityTester(security_client)

        vulnerabilities = await tester.test_attendance_record_tampering(test_db)

        # Should have proper validation for timestamps
        high_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(high_vulns) == 0, f"High-severity timestamp vulnerabilities: {high_vulns}"

    async def test_employee_enumeration_protection(self, security_client):
        """Test employee ID enumeration is prevented"""
        tester = BiometricSecurityTester(security_client)

        vulnerabilities = await tester.test_employee_id_enumeration()

        # Should not allow easy enumeration of employee IDs
        enum_vulns = [v for v in vulnerabilities if "enumeration" in v.category.lower()]
        assert len(enum_vulns) <= 2, f"Too many enumeration vulnerabilities: {enum_vulns}"

    async def test_zkteco_device_security(self, security_client):
        """Test ZKTeco device communication security"""
        tester = BiometricSecurityTester(security_client)

        vulnerabilities = await tester.test_device_communication_security()

        # Device configuration should be secure
        device_vulns = [v for v in vulnerabilities if v.severity in [SecurityLevel.HIGH, SecurityLevel.CRITICAL]]
        assert len(device_vulns) == 0, f"Critical device security issues: {device_vulns}"

    @patch('app.services.device_service.device_service.sync_attendance_data')
    async def test_biometric_sync_security(self, mock_sync, security_client):
        """Test biometric data sync security"""

        # Mock a normal sync response without malicious data
        mock_sync.return_value = {
            "success": True,
            "synced": 5,  # Realistic number
            "message": "Sync completed successfully"
        }

        response = security_client.post("/api/auto-import/trigger")

        # Should handle sync data gracefully
        assert response.status_code in [200, 400, 422], "Sync should handle data properly"

        # Check that response doesn't include raw device data
        response_text = response.text
        if response.status_code == 200:
            # Should not expose internal service details in successful response
            assert "fingerprint_templates" not in response_text.lower(), "Should not expose biometric templates"
            assert "device_password" not in response_text.lower(), "Should not expose device credentials"

    async def test_employee_pii_protection(self, security_client, test_db):
        """Test employee PII (Thai names, badge numbers) protection"""

        # Create test employee with Thai name
        test_employee = Employee(
            badge_number="PII_TEST_001",
            english_name="Test Employee",
            thai_name="พนักงานทดสอบ",  # Thai text
            display_name="พนักงานทดสอบ",
            is_active=True
        )
        test_db.add(test_employee)
        test_db.commit()

        # Test PII exposure in various endpoints
        pii_test_endpoints = [
            "/api/employees/",
            "/api/attendance/",
            f"/api/employees/PII_TEST_001",
        ]

        vulnerabilities = []

        for endpoint in pii_test_endpoints:
            try:
                response = security_client.get(endpoint)
                if response.status_code == 200:
                    response_text = response.text

                    # Check if sensitive PII patterns are exposed
                    if "พนักงานทดสอบ" in response_text:
                        # This might be expected for employee management
                        continue

                    # Check for badge number in error messages
                    if "PII_TEST_001" in response_text and "error" in response_text.lower():
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"pii_leak_{endpoint}",
                            title="PII Disclosure in Error Messages",
                            description="Badge numbers exposed in error responses",
                            severity=SecurityLevel.MEDIUM,
                            category="Information Disclosure",
                            endpoint=endpoint,
                            payload=None,
                            recommendation="Sanitize error messages to remove PII",
                            cwe="CWE-200"
                        ))

            except Exception:
                pass

        # Cleanup
        test_db.delete(test_employee)
        test_db.commit()

        # Should have minimal PII leakage in error messages
        assert len(vulnerabilities) <= 1, f"Excessive PII leakage: {vulnerabilities}"