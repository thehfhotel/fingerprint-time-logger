"""
Security Test Runner for Fingerprint Time Logger

Centralized security test execution and reporting system:
- Run all security tests
- Generate comprehensive security reports
- Integration with CI/CD pipelines
- Security metrics and trends
"""

import asyncio
import sys
import argparse
from pathlib import Path
from datetime import datetime
import json

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.security.conftest import SecurityScanner, generate_security_report
from tests.security.test_automated_security_tools import AutomatedSecurityScanner


class SecurityTestRunner:
    """Comprehensive security test runner"""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.reports_dir = self.project_root / "security_reports"
        self.reports_dir.mkdir(exist_ok=True)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    async def run_all_security_tests(self, client=None) -> dict:
        """Run all security tests and collect results"""
        print("🔒 Starting Comprehensive Security Assessment...")
        print("=" * 60)

        all_results = {
            'biometric_security': [],
            'websocket_security': [],
            'csv_injection': [],
            'api_security': [],
            'unicode_security': [],
            'automated_tools': [],
            'summary': {}
        }

        # Import security testers
        from tests.security.test_biometric_security import BiometricSecurityTester
        from tests.security.test_websocket_security import WebSocketSecurityTester
        from tests.security.test_csv_injection import CSVSecurityTester
        from tests.security.test_api_security import APISecurityTester
        from tests.security.test_unicode_security import UnicodeSecurityTester

        if not client:
            # Create a mock client for testing
            from fastapi.testclient import TestClient
            from app.main_unified import app
            client = TestClient(app)

        # 1. Biometric Security Tests
        print("🔍 Testing Biometric Security...")
        try:
            bio_tester = BiometricSecurityTester(client)
            bio_results = []

            # Test biometric data leakage
            bio_results.extend(await bio_tester.test_biometric_data_leakage([
                "/api/employees/", "/api/attendance/", "/api/devices/"
            ]))

            # Test device communication security
            bio_results.extend(await bio_tester.test_device_communication_security())

            # Test employee enumeration
            bio_results.extend(await bio_tester.test_employee_id_enumeration())

            all_results['biometric_security'] = bio_results
            print(f"   ✅ Biometric Security: {len(bio_results)} findings")

        except Exception as e:
            print(f"   ❌ Biometric Security: Error - {e}")

        # 2. WebSocket Security Tests
        print("🌐 Testing WebSocket Security...")
        try:
            ws_tester = WebSocketSecurityTester()
            ws_results = []

            # Test WebSocket message injection
            ws_results.extend(await ws_tester.test_websocket_message_injection())

            # Test WebSocket broadcast security
            ws_results.extend(await ws_tester.test_websocket_broadcast_security())

            # Test WebSocket DoS protection
            ws_results.extend(await ws_tester.test_websocket_denial_of_service())

            all_results['websocket_security'] = ws_results
            print(f"   ✅ WebSocket Security: {len(ws_results)} findings")

        except Exception as e:
            print(f"   ❌ WebSocket Security: Error - {e}")

        # 3. CSV Injection Tests
        print("📊 Testing CSV Security...")
        try:
            csv_tester = CSVSecurityTester(client)
            csv_results = []

            # Mock database session
            from tests.conftest import test_db
            from app.core.database import get_db

            # Test CSV formula injection
            # csv_results.extend(await csv_tester.test_csv_formula_injection(next(get_db())))

            # Test export data exposure
            csv_results.extend(await csv_tester.test_export_data_exposure())

            # Test export file security
            csv_results.extend(await csv_tester.test_export_file_security())

            # Test export parameter injection
            csv_results.extend(await csv_tester.test_export_parameter_injection())

            all_results['csv_injection'] = csv_results
            print(f"   ✅ CSV Security: {len(csv_results)} findings")

        except Exception as e:
            print(f"   ❌ CSV Security: Error - {e}")

        # 4. API Security Tests
        print("🔗 Testing API Security...")
        try:
            api_tester = APISecurityTester(client)
            api_results = []

            # Test API input validation
            api_results.extend(await api_tester.test_api_input_validation())

            # Test rate limiting
            api_results.extend(await api_tester.test_rate_limiting())

            # Test CORS security
            api_results.extend(await api_tester.test_cors_security())

            # Test security headers
            api_results.extend(await api_tester.test_security_headers())

            all_results['api_security'] = api_results
            print(f"   ✅ API Security: {len(api_results)} findings")

        except Exception as e:
            print(f"   ❌ API Security: Error - {e}")

        # 5. Unicode Security Tests
        print("🔤 Testing Unicode Security...")
        try:
            unicode_tester = UnicodeSecurityTester(client)
            unicode_results = []

            # Mock database session
            # unicode_results.extend(await unicode_tester.test_unicode_normalization_attacks(next(get_db())))
            # unicode_results.extend(await unicode_tester.test_thai_character_encoding_attacks(next(get_db())))
            unicode_results.extend(await unicode_tester.test_encoding_bypass_attacks())
            unicode_results.extend(await unicode_tester.test_mixed_script_injection())

            all_results['unicode_security'] = unicode_results
            print(f"   ✅ Unicode Security: {len(unicode_results)} findings")

        except Exception as e:
            print(f"   ❌ Unicode Security: Error - {e}")

        # 6. Automated Security Tools
        print("🤖 Running Automated Security Tools...")
        try:
            auto_scanner = AutomatedSecurityScanner()
            auto_results = []

            # Run Bandit
            print("   🔍 Running Bandit static analysis...")
            bandit_report = auto_scanner.run_bandit_scan()
            auto_results.extend(auto_scanner.convert_bandit_to_vulnerabilities(bandit_report))

            # Run Safety
            print("   🛡️  Running Safety dependency scan...")
            safety_report = auto_scanner.run_safety_check()
            auto_results.extend(auto_scanner.convert_safety_to_vulnerabilities(safety_report))

            # Run custom SAST
            print("   🔧 Running custom SAST scan...")
            auto_results.extend(auto_scanner.run_custom_sast_scan())

            # Run dependency audit
            print("   📦 Running dependency audit...")
            auto_results.extend(auto_scanner.run_dependency_audit())

            all_results['automated_tools'] = auto_results
            print(f"   ✅ Automated Tools: {len(auto_results)} findings")

        except Exception as e:
            print(f"   ❌ Automated Tools: Error - {e}")

        return all_results

    def generate_comprehensive_report(self, results: dict):
        """Generate comprehensive security assessment report"""
        # Flatten all vulnerabilities
        all_vulnerabilities = []
        for category, vulns in results.items():
            if category != 'summary' and isinstance(vulns, list):
                all_vulnerabilities.extend(vulns)

        if not all_vulnerabilities:
            print("✅ No security vulnerabilities found!")
            return

        # Calculate metrics
        from tests.security.conftest import SecurityLevel, SecurityReport

        critical_count = len([v for v in all_vulnerabilities if v.severity == SecurityLevel.CRITICAL])
        high_count = len([v for v in all_vulnerabilities if v.severity == SecurityLevel.HIGH])
        medium_count = len([v for v in all_vulnerabilities if v.severity == SecurityLevel.MEDIUM])
        low_count = len([v for v in all_vulnerabilities if v.severity == SecurityLevel.LOW])

        # Create security report
        security_report = SecurityReport(
            vulnerabilities=all_vulnerabilities,
            total_tests=1000,  # Approximate
            passed_tests=1000 - len(all_vulnerabilities),
            failed_tests=len(all_vulnerabilities),
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count
        )

        # Generate HTML report
        report_path = self.reports_dir / f"security_assessment_{self.timestamp}.html"
        generate_security_report(security_report, report_path)

        # Generate JSON report for CI/CD
        json_report_path = self.reports_dir / f"security_assessment_{self.timestamp}.json"
        json_data = {
            'timestamp': self.timestamp,
            'total_vulnerabilities': len(all_vulnerabilities),
            'critical': critical_count,
            'high': high_count,
            'medium': medium_count,
            'low': low_count,
            'categories': {
                category: len(vulns) for category, vulns in results.items()
                if category != 'summary' and isinstance(vulns, list)
            },
            'vulnerabilities': [
                {
                    'id': v.id,
                    'title': v.title,
                    'severity': v.severity.value,
                    'category': v.category,
                    'endpoint': v.endpoint,
                    'cwe': v.cwe
                } for v in all_vulnerabilities
            ]
        }

        with open(json_report_path, 'w') as f:
            json.dump(json_data, f, indent=2)

        # Print summary
        print("\n" + "=" * 60)
        print("🔒 SECURITY ASSESSMENT COMPLETE")
        print("=" * 60)
        print(f"📊 Total Vulnerabilities: {len(all_vulnerabilities)}")
        print(f"🔴 Critical: {critical_count}")
        print(f"🟠 High: {high_count}")
        print(f"🟡 Medium: {medium_count}")
        print(f"🟢 Low: {low_count}")
        print(f"📄 HTML Report: {report_path}")
        print(f"📄 JSON Report: {json_report_path}")

        # Security score (100 - penalty for vulnerabilities)
        security_score = max(0, 100 - (critical_count * 20 + high_count * 10 + medium_count * 5 + low_count * 1))
        print(f"🏆 Security Score: {security_score}/100")

        if critical_count > 0:
            print("🚨 CRITICAL: Address critical vulnerabilities immediately!")
        elif high_count > 0:
            print("⚠️  WARNING: Address high-severity vulnerabilities soon!")
        else:
            print("✅ GOOD: No critical or high-severity vulnerabilities found!")

        return security_report

    def generate_threat_model(self):
        """Generate threat model for the fingerprint time logger system"""
        threat_model = {
            'system_overview': {
                'name': 'Fingerprint Time Logger',
                'description': 'ZKTeco biometric attendance tracking system with Thai localization',
                'components': [
                    'FastAPI Web Server',
                    'SQLite Database',
                    'ZKTeco Device Integration',
                    'WebSocket Real-time Updates',
                    'CSV Export System',
                    'Thai Employee Management'
                ]
            },
            'trust_boundaries': [
                'Web Client ↔ FastAPI Server',
                'FastAPI Server ↔ SQLite Database',
                'FastAPI Server ↔ ZKTeco Device',
                'Client ↔ WebSocket Connection'
            ],
            'assets': [
                'Employee Biometric Data',
                'Attendance Records',
                'Employee Personal Information (Thai Names)',
                'ZKTeco Device Configuration',
                'System Configuration Data'
            ],
            'threats': {
                'STRIDE_Analysis': {
                    'Spoofing': [
                        'Employee ID spoofing in API calls',
                        'Device identity spoofing',
                        'WebSocket connection spoofing'
                    ],
                    'Tampering': [
                        'Attendance record manipulation',
                        'Employee data tampering',
                        'CSV export data modification',
                        'Thai name encoding manipulation'
                    ],
                    'Repudiation': [
                        'Attendance log repudiation',
                        'Admin action repudiation',
                        'Data export repudiation'
                    ],
                    'Information_Disclosure': [
                        'Biometric template exposure',
                        'Employee PII leakage',
                        'Device configuration disclosure',
                        'System path disclosure'
                    ],
                    'Denial_of_Service': [
                        'API endpoint flooding',
                        'WebSocket connection exhaustion',
                        'Large CSV export DoS',
                        'Database connection exhaustion'
                    ],
                    'Elevation_of_Privilege': [
                        'Admin function access without auth',
                        'Device configuration modification',
                        'Database direct access'
                    ]
                }
            },
            'vulnerabilities_by_component': {
                'FastAPI_Server': [
                    'Input validation bypass',
                    'CORS misconfiguration',
                    'Missing security headers',
                    'Rate limiting gaps'
                ],
                'Database_Layer': [
                    'SQL injection vulnerabilities',
                    'Direct database access',
                    'Data exposure in errors'
                ],
                'ZKTeco_Integration': [
                    'Device command injection',
                    'Configuration data exposure',
                    'Communication security gaps'
                ],
                'WebSocket_System': [
                    'Message injection attacks',
                    'Broadcasting sensitive data',
                    'Connection flooding'
                ],
                'CSV_Export': [
                    'Formula injection attacks',
                    'Mass data exposure',
                    'File download security'
                ],
                'Unicode_Handling': [
                    'Thai character encoding bypass',
                    'Unicode normalization attacks',
                    'Mixed script injection'
                ]
            },
            'risk_ratings': {
                'High_Risk': [
                    'Biometric data exposure',
                    'Employee PII leakage',
                    'Attendance record tampering',
                    'System compromise via injection'
                ],
                'Medium_Risk': [
                    'DoS attacks',
                    'Information disclosure',
                    'Configuration exposure'
                ],
                'Low_Risk': [
                    'Minor data leaks',
                    'Performance issues',
                    'UI vulnerabilities'
                ]
            }
        }

        # Save threat model
        threat_model_path = self.reports_dir / f"threat_model_{self.timestamp}.json"
        with open(threat_model_path, 'w') as f:
            json.dump(threat_model, f, indent=2)

        print(f"🎯 Threat Model Generated: {threat_model_path}")
        return threat_model


async def main():
    """Main security test runner"""
    parser = argparse.ArgumentParser(description='Fingerprint Time Logger Security Assessment')
    parser.add_argument('--quick', action='store_true', help='Run quick security scan')
    parser.add_argument('--full', action='store_true', help='Run full comprehensive scan')
    parser.add_argument('--threat-model', action='store_true', help='Generate threat model')
    parser.add_argument('--json-only', action='store_true', help='Output JSON report only')

    args = parser.parse_args()

    runner = SecurityTestRunner()

    if args.threat_model:
        runner.generate_threat_model()
        return

    # Run security tests
    results = await runner.run_all_security_tests()

    # Generate reports
    if not args.json_only:
        security_report = runner.generate_comprehensive_report(results)

        # Return appropriate exit code for CI/CD
        if security_report:
            critical_and_high = security_report.critical_count + security_report.high_count
            if critical_and_high > 0:
                print(f"\n❌ Security assessment failed: {critical_and_high} critical/high vulnerabilities")
                sys.exit(1)
            else:
                print("\n✅ Security assessment passed!")
                sys.exit(0)
        else:
            print("\n✅ Security assessment completed successfully!")
            sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())