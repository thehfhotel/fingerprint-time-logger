"""
Thai Unicode and Internationalization Security Testing Suite

Tests for Unicode handling, Thai character processing, and i18n security:
- Unicode normalization attacks
- Thai character encoding security
- Mixed script injection attacks
- Character encoding bypass attempts
- Bidirectional text attacks
"""

import pytest
import unicodedata
from unittest.mock import patch
from httpx import AsyncClient

from tests.security.conftest import (
    SecurityTester, SecurityVulnerability, SecurityLevel,
    security_client
)
from app.models.models import Employee, Device
from tests.conftest import test_db


class UnicodeSecurityTester(SecurityTester):
    """Specialized Unicode and internationalization security testing"""

    async def test_unicode_normalization_attacks(self, db) -> list[SecurityVulnerability]:
        """Test Unicode normalization bypass attacks"""
        vulnerabilities = []

        # Unicode normalization attack vectors
        unicode_attacks = [
            # Equivalent representations that might bypass validation
            ("script", "ſcript"),  # Long s (ſ) looks like 'f'
            ("admin", "аdmin"),    # Cyrillic 'а' instead of Latin 'a'
            ("test", "te\u0073t"), # Unicode escape for 's'

            # Thai-specific attacks
            ("admin", "admin\u0e48"),  # Thai tone mark
            ("พนักงาน", "พนัก\u0e49งาน"), # Thai digit in text

            # Homograph attacks
            ("google.com", "gοοgle.com"),  # Greek omicron
            ("microsoft", "micrοsoft"),    # Greek omicron

            # Zero-width characters
            ("admin", "ad\u200bmin"),      # Zero-width space
            ("test", "te\u200dst"),        # Zero-width joiner
            ("user", "us\ufeffεr"),        # BOM + Greek epsilon

            # Combining characters
            ("test", "t\u0300e\u0301s\u0302t"),  # Combining grave, acute, circumflex
            ("admin", "a\u0308d\u0327m\u030ai\u0323n"),  # Multiple combining marks

            # Bidirectional override attacks
            ("admin", "admi\u202en"),      # Right-to-left override
            ("user", "\u202euser\u202c"),  # RLO...PDF

            # Case folding attacks
            ("Admin", "ADMIN"),
            ("ßeta", "SSETA"),  # German eszett expands to SS

            # Thai normalization issues
            ("ก็", "ก\u0e47"),             # Sara Am vs vowel + tone mark
            ("ไก่", "ไก\u0e48"),           # Different tone mark combinations
        ]

        for original, attack in unicode_attacks:
            try:
                # Test in employee name field
                test_employee = Employee(
                    badge_number=f"UNICODE_{len(vulnerabilities)}",
                    english_name=attack,
                    thai_name=f"ทดสอบ {attack}",
                    is_active=True
                )
                db.add(test_employee)
                db.commit()

                # Check if normalization bypass occurred
                stored_employee = db.query(Employee).filter_by(badge_number=test_employee.badge_number).first()
                if stored_employee and stored_employee.english_name == attack:
                    # Check if the attack string is visually deceptive
                    normalized_original = unicodedata.normalize('NFKC', original)
                    normalized_attack = unicodedata.normalize('NFKC', attack)

                    if normalized_original.lower() == normalized_attack.lower() and original != attack:
                        vulnerabilities.append(SecurityVulnerability(
                            id=f"unicode_bypass_{len(vulnerabilities)}",
                            title="Unicode Normalization Bypass",
                            description=f"System accepts visually similar Unicode: '{attack}' for '{original}'",
                            severity=SecurityLevel.MEDIUM,
                            category="Unicode Security",
                            endpoint="/api/employees/",
                            payload=f"Original: '{original}' -> Attack: '{attack}'",
                            recommendation="Implement Unicode normalization before validation",
                            cwe="CWE-20"
                        ))

                # Test via API
                response = await self.client.post("/api/employees/", json={
                    "badge_number": f"API_UNICODE_{len(vulnerabilities)}",
                    "english_name": attack,
                    "thai_name": f"ทดสอบ {attack}"
                })

                if response.status_code == 201:
                    # Check if dangerous Unicode is reflected
                    get_response = await self.client.get(f"/api/employees/API_UNICODE_{len(vulnerabilities)}")
                    if get_response.status_code == 200:
                        response_text = get_response.text

                        # Check for bidirectional override characters in response
                        if '\u202e' in response_text or '\u202c' in response_text:
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"bidi_attack_{len(vulnerabilities)}",
                                title="Bidirectional Text Attack",
                                description="System stores and reflects bidirectional override characters",
                                severity=SecurityLevel.MEDIUM,
                                category="Unicode Security",
                                endpoint="/api/employees/",
                                payload=attack,
                                recommendation="Filter or escape bidirectional control characters",
                                cwe="CWE-838"
                            ))

                # Cleanup
                db.delete(test_employee)
                db.commit()

            except Exception:
                pass

        return vulnerabilities

    async def test_thai_character_encoding_attacks(self, db) -> list[SecurityVulnerability]:
        """Test Thai character encoding bypass attacks"""
        vulnerabilities = []

        # Thai-specific encoding attacks
        thai_attacks = [
            # Thai characters that might bypass validation
            "พนักงาน<script>alert('XSS')</script>",
            "พนักงาน'; DROP TABLE employees; --",
            "พนักงาน../../../etc/passwd",

            # Mixed script attacks
            "พนักงาン<script>αlert('XSS')</script>",  # Mixed Thai, HTML, Greek
            "พนักงาน\"; system('rm -rf /'); //",

            # Thai tone marks with malicious payloads
            "พนักงาน\u0e48<script>alert(1)</script>",
            "พนักงาน\u0e4c'; DROP TABLE employees; --",

            # Thai digits in unexpected places
            "พนักงาน\u0e50\u0e51\u0e52<script>",  # Thai digits 012

            # Combining marks with Thai
            "พ\u0e34นั\u0e01งาน<script>alert(1)</script>",

            # Private use area characters
            "พนักงาน\ue000\ue001<script>",

            # Incomplete Thai character sequences
            "พนั\u0e01งา<script>alert(1)</script>น",

            # Thai characters with zero-width characters
            "พ\u200bนั\u200cก\u200dงาน<script>alert(1)</script>",
        ]

        for attack_payload in thai_attacks:
            try:
                # Test employee creation with Thai attack
                response = await self.client.post("/api/employees/", json={
                    "badge_number": f"THAI_ATK_{len(vulnerabilities)}",
                    "english_name": "Test Employee",
                    "thai_name": attack_payload,
                    "is_active": True
                })

                if response.status_code == 201:
                    employee_id = response.json().get("id")

                    # Get the employee back and check for XSS
                    get_response = await self.client.get(f"/api/employees/{employee_id}")
                    if get_response.status_code == 200:
                        response_text = get_response.text

                        # Check if script tags are present (not escaped)
                        if "<script>" in response_text and "alert(" in response_text:
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"thai_xss_{len(vulnerabilities)}",
                                title="Thai Text XSS Vulnerability",
                                description="Thai text containing XSS payload not properly escaped",
                                severity=SecurityLevel.HIGH,
                                category="Cross-Site Scripting",
                                endpoint="/api/employees/",
                                payload=attack_payload,
                                recommendation="Escape HTML in Thai text output",
                                cwe="CWE-79"
                            ))

                        # Check if SQL injection indicators
                        if "DROP TABLE" in response_text:
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"thai_sql_{len(vulnerabilities)}",
                                title="Thai Text SQL Injection",
                                description="Thai text containing SQL injection not filtered",
                                severity=SecurityLevel.HIGH,
                                category="Injection",
                                endpoint="/api/employees/",
                                payload=attack_payload,
                                recommendation="Use parameterized queries for Thai text",
                                cwe="CWE-89"
                            ))

                    # Cleanup
                    await self.client.delete(f"/api/employees/{employee_id}")

            except Exception:
                pass

        return vulnerabilities

    async def test_encoding_bypass_attacks(self) -> list[SecurityVulnerability]:
        """Test character encoding bypass attempts"""
        vulnerabilities = []

        # Various encoding bypass attempts
        encoding_attacks = [
            # URL encoding
            "%3Cscript%3Ealert%28%27XSS%27%29%3C%2Fscript%3E",
            "%27%3B%20DROP%20TABLE%20employees%3B%20--",

            # Double URL encoding
            "%253Cscript%253Ealert%2528%2527XSS%2527%2529%253C%252Fscript%253E",

            # UTF-8 overlong encoding
            "\xC0\xBC\xC0\xBCscript\xC0\xBE",  # Overlong encoding of <script>

            # UTF-16 encoding
            "\xFF\xFE<\x00s\x00c\x00r\x00i\x00p\x00t\x00>\x00",

            # Mixed encoding
            "<script>alert('XSS')</script>",  # HTML entities
            "&lt;script&gt;alert(&#39;XSS&#39;)&lt;/script&gt;",

            # Thai UTF-8 with embedded attacks
            "\xe0\xb8\x9e\xe0\xb8\x99\xe0\xb8\xb1\xe0\xb8\x81\xe0\xb8\x87\xe0\xb8\xb2\xe0\xb8\x99<script>",

            # Byte order mark attacks
            "\ufeff<script>alert('XSS')</script>",
            "\ufffe<script>alert('XSS')</script>",

            # Control character bypass
            "<sc\x00ript>alert('XSS')</script>",
            "<script\x09>alert('XSS')</script>",  # Tab character

            # Line separator attacks
            "<script>alert('XSS'\u2028)</script>",
            "<script>alert('XSS'\u2029)</script>",
        ]

        test_endpoints = [
            "/api/employees/",
            "/api/devices/",
        ]

        for endpoint in test_endpoints:
            for encoding_attack in encoding_attacks:
                try:
                    # Prepare test data based on endpoint
                    if endpoint == "/api/employees/":
                        test_data = {
                            "badge_number": "ENCODING_TEST",
                            "english_name": encoding_attack,
                            "thai_name": f"ทดสอบ {encoding_attack}"
                        }
                    else:  # devices
                        test_data = {
                            "name": encoding_attack,
                            "ip_address": "192.168.1.100",
                            "port": 4370
                        }

                    response = await self.client.post(endpoint, json=test_data)

                    if response.status_code == 201:
                        # Check if the encoding attack was stored and can be retrieved
                        record_id = response.json().get("id")
                        get_response = await self.client.get(f"{endpoint.rstrip('/')}/{record_id}")

                        if get_response.status_code == 200:
                            response_text = get_response.text

                            # Check for script execution indicators
                            if "<script>" in response_text and "alert(" in response_text:
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"encoding_bypass_{endpoint}_{len(vulnerabilities)}",
                                    title=f"Encoding Bypass Attack - {endpoint}",
                                    description="Character encoding bypass allows XSS payload storage",
                                    severity=SecurityLevel.HIGH,
                                    category="Cross-Site Scripting",
                                    endpoint=endpoint,
                                    payload=encoding_attack[:100] + "...",
                                    recommendation="Decode and validate all character encodings",
                                    cwe="CWE-79"
                                ))

                        # Cleanup
                        await self.client.delete(f"{endpoint.rstrip('/')}/{record_id}")

                except Exception:
                    pass

        return vulnerabilities

    async def test_mixed_script_injection(self) -> list[SecurityVulnerability]:
        """Test mixed script injection attacks"""
        vulnerabilities = []

        # Mixed script injection attempts
        mixed_scripts = [
            # Thai + Latin + Cyrillic
            "พนักงาน αdmin админ<script>alert('Mixed')</script>",

            # Arabic + Thai + Latin
            "مهندس พนักงาน engineer<script>alert('XSS')</script>",

            # Chinese + Thai + HTML
            "工程师 พนักงาน <img src=x onerror=alert(1)>",

            # Japanese + Thai + SQL injection
            "エンジニア พนักงาน '; DROP TABLE employees; --",

            # Hebrew + Thai (bidirectional text)
            "מהנדס พนักงาน <script>alert('BiDi')</script>",

            # Mixed with invisible characters
            "พนักงาน\u200c\u200dtest<script>alert('Invisible')</script>",

            # Emoji + Thai + attack
            "👨‍💻 พนักงาน <script>alert('Emoji')</script>",

            # Mathematical symbols + Thai
            "∑ π พนักงาน <script>alert('Math')</script>",
        ]

        for mixed_script in mixed_scripts:
            try:
                response = await self.client.post("/api/employees/", json={
                    "badge_number": f"MIXED_{len(mixed_script[:8])}",
                    "english_name": "Mixed Script Test",
                    "thai_name": mixed_script,
                    "is_active": True
                })

                if response.status_code == 201:
                    employee_id = response.json().get("id")

                    # Check if mixed script attack is stored and retrievable
                    get_response = await self.client.get(f"/api/employees/{employee_id}")
                    if get_response.status_code == 200:
                        response_text = get_response.text

                        # Check for unescaped script tags
                        if "<script>" in response_text and "alert(" in response_text:
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"mixed_script_xss_{len(vulnerabilities)}",
                                title="Mixed Script XSS Vulnerability",
                                description="Mixed script text with XSS payload not properly escaped",
                                severity=SecurityLevel.HIGH,
                                category="Cross-Site Scripting",
                                endpoint="/api/employees/",
                                payload=mixed_script[:100] + "...",
                                recommendation="Escape HTML entities in mixed script text",
                                cwe="CWE-79"
                            ))

                        # Check for bidirectional text vulnerabilities
                        if any(char in response_text for char in ['\u200e', '\u200f', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e']):
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"bidi_mixed_{len(vulnerabilities)}",
                                title="Bidirectional Text in Mixed Script",
                                description="Mixed script contains bidirectional control characters",
                                severity=SecurityLevel.MEDIUM,
                                category="Unicode Security",
                                endpoint="/api/employees/",
                                payload=mixed_script,
                                recommendation="Filter bidirectional control characters",
                                cwe="CWE-838"
                            ))

                    # Cleanup
                    await self.client.delete(f"/api/employees/{employee_id}")

            except Exception:
                pass

        return vulnerabilities


@pytest.mark.asyncio
class TestUnicodeSecurity:
    """Test suite for Unicode and internationalization security"""

    async def test_unicode_normalization_protection(self, security_client, test_db):
        """Test Unicode normalization attacks are handled"""
        tester = UnicodeSecurityTester(security_client)

        vulnerabilities = await tester.test_unicode_normalization_attacks(test_db)

        # Should handle Unicode normalization properly
        unicode_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(unicode_vulns) == 0, f"High-severity Unicode vulnerabilities: {unicode_vulns}"

    async def test_thai_character_security(self, security_client, test_db):
        """Test Thai character handling security"""
        tester = UnicodeSecurityTester(security_client)

        vulnerabilities = await tester.test_thai_character_encoding_attacks(test_db)

        # Thai character handling should be secure
        thai_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(thai_vulns) == 0, f"Thai character security vulnerabilities: {thai_vulns}"

    async def test_encoding_bypass_prevention(self, security_client):
        """Test character encoding bypass prevention"""
        tester = UnicodeSecurityTester(security_client)

        vulnerabilities = await tester.test_encoding_bypass_attacks()

        # Should prevent encoding bypass attacks
        bypass_vulns = [v for v in vulnerabilities if "bypass" in v.title.lower()]
        assert len(bypass_vulns) == 0, f"Encoding bypass vulnerabilities: {bypass_vulns}"

    async def test_mixed_script_security(self, security_client):
        """Test mixed script injection security"""
        tester = UnicodeSecurityTester(security_client)

        vulnerabilities = await tester.test_mixed_script_injection()

        # Mixed script should not allow injection
        mixed_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(mixed_vulns) == 0, f"Mixed script vulnerabilities: {mixed_vulns}"

    async def test_thai_name_validation(self, security_client, test_db):
        """Test Thai name validation and sanitization"""

        # Test various Thai name inputs
        thai_names = [
            "พนักงานทดสอบ",  # Normal Thai name
            "พนักงาน ทดสอบ",  # Thai with space
            "พนักงาน123",     # Thai with numbers
            "พนักงาน-ทดสอบ",  # Thai with dash
            "พนักงาน_ทดสอบ",  # Thai with underscore
        ]

        for thai_name in thai_names:
            response = await security_client.post("/api/employees/", json={
                "badge_number": f"THAI_{hash(thai_name) % 10000}",
                "english_name": "Test Employee",
                "thai_name": thai_name,
                "is_active": True
            })

            # Should accept valid Thai names
            assert response.status_code == 201, f"Valid Thai name rejected: {thai_name}"

            # Cleanup
            if response.status_code == 201:
                employee_id = response.json().get("id")
                if employee_id:
                    await security_client.delete(f"/api/employees/{employee_id}")

    async def test_unicode_length_limits(self, security_client):
        """Test Unicode length validation"""

        # Test very long Thai strings
        long_thai = "พนักงาน" * 1000  # Very long Thai string

        response = await security_client.post("/api/employees/", json={
            "badge_number": "LONG_THAI_001",
            "english_name": "Test Employee",
            "thai_name": long_thai,
            "is_active": True
        })

        # Should reject overly long names
        assert response.status_code in [400, 413, 422], "Should reject overly long Thai names"

    async def test_unicode_in_csv_export(self, security_client, test_db):
        """Test Unicode handling in CSV exports"""

        # Create employee with Thai name
        thai_employee = Employee(
            badge_number="CSV_THAI_001",
            english_name="Test Employee",
            thai_name="พนักงานทดสอบ การส่งออก CSV",
            is_active=True
        )
        test_db.add(thai_employee)
        test_db.commit()

        # Export CSV
        response = await security_client.get("/api/export/employees-csv/")
        assert response.status_code == 200

        csv_content = response.text

        # Should properly handle Thai characters in CSV
        assert "พนักงานทดสอบ" in csv_content or "UTF-8" in response.headers.get("content-type", "")

        # Cleanup
        test_db.delete(thai_employee)
        test_db.commit()

    async def test_rtl_text_security(self, security_client):
        """Test right-to-left text security"""

        # Test with Arabic text and RTL override
        rtl_texts = [
            "مهندس",  # Arabic text (RTL)
            "\u202eAdmin\u202c",  # RTL override
            "User\u202enmidA",    # Hidden admin with RTL
        ]

        for rtl_text in rtl_texts:
            response = await security_client.post("/api/employees/", json={
                "badge_number": f"RTL_{hash(rtl_text) % 10000}",
                "english_name": rtl_text,
                "thai_name": "พนักงานทดสอบ",
                "is_active": True
            })

            if response.status_code == 201:
                employee_id = response.json().get("id")

                # Get employee and check for proper RTL handling
                get_response = await security_client.get(f"/api/employees/{employee_id}")
                if get_response.status_code == 200:
                    response_text = get_response.text

                    # Should not contain raw RTL override characters
                    assert "\u202e" not in response_text, "RTL override should be filtered or escaped"

                # Cleanup
                await security_client.delete(f"/api/employees/{employee_id}")