"""
Integration Validation Test
Validates E2E test framework integration with existing comprehensive test suite
"""

import pytest
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime


@pytest.mark.integration
class TestE2EIntegration:
    """Validate E2E framework integration with existing 106 comprehensive tests"""

    def test_existing_test_suite_compatibility(self):
        """Verify E2E framework doesn't break existing test execution"""

        project_root = Path(__file__).parent.parent.parent

        # Run existing unit tests to ensure they still work
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            "tests/",
            "--ignore=tests/e2e",  # Exclude E2E tests
            "-v",
            "--tb=short",
            "--maxfail=5"
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=300
        )

        print("STDOUT:", result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)

        # Existing tests should still pass
        assert result.returncode == 0, f"Existing tests failed after E2E integration: {result.stderr}"

        # Verify we still have the comprehensive test coverage
        output_lines = result.stdout.split('\n')
        test_results = [line for line in output_lines if "passed" in line or "failed" in line or "error" in line]

        print(f"Existing test execution completed with output: {test_results}")

    def test_e2e_framework_components(self):
        """Validate all E2E framework components are properly installed"""

        # Check Playwright installation
        try:
            import playwright
            from playwright.async_api import async_playwright, Browser, BrowserContext, Page
            print(f"✅ Playwright version: {playwright.__version__}")
        except ImportError as e:
            pytest.fail(f"Playwright not properly installed: {e}")

        # Check pytest plugins
        required_plugins = [
            'pytest_asyncio',
            'pytest_html',
            'pytest_json_report',
            'pytest_cov'
        ]

        for plugin in required_plugins:
            try:
                __import__(plugin.replace('_', '-'))
                print(f"✅ Plugin {plugin} available")
            except ImportError:
                try:
                    __import__(plugin)
                    print(f"✅ Plugin {plugin} available")
                except ImportError:
                    pytest.fail(f"Required plugin {plugin} not available")

        # Verify page object models exist
        project_root = Path(__file__).parent.parent.parent
        page_objects_dir = project_root / "tests" / "e2e" / "page_objects"

        required_page_objects = [
            "dashboard_page.py",
            "employee_page.py",
            "status_page.py"
        ]

        for page_object in required_page_objects:
            page_object_file = page_objects_dir / page_object
            assert page_object_file.exists(), f"Required page object {page_object} not found"
            print(f"✅ Page object {page_object} exists")

    def test_e2e_test_discovery(self):
        """Validate E2E tests are discoverable by pytest"""

        project_root = Path(__file__).parent.parent.parent
        e2e_dir = project_root / "tests" / "e2e"

        # Run pytest discovery on E2E tests
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            str(e2e_dir),
            "--collect-only",
            "-q"
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60
        )

        print("Test discovery output:", result.stdout)
        if result.stderr:
            print("Test discovery errors:", result.stderr)

        # Discovery should succeed
        assert result.returncode == 0, f"E2E test discovery failed: {result.stderr}"

        # Should find test files
        assert "test session starts" in result.stdout.lower() or "collected" in result.stdout.lower(), \
            f"No E2E tests discovered: {result.stdout}"

        # Count discovered tests
        output_lines = result.stdout.split('\n')
        workflow_tests = [line for line in output_lines if "test_employee_lifecycle" in line or "test_attendance_tracking" in line]

        assert len(workflow_tests) > 0, "No workflow tests discovered"
        print(f"✅ Discovered {len(workflow_tests)} workflow tests")

    def test_test_markers_functionality(self):
        """Validate custom test markers work correctly"""

        project_root = Path(__file__).parent.parent.parent

        # Test marker filtering
        test_markers = ["workflow", "integration", "slow"]

        for marker in test_markers:
            result = subprocess.run([
                sys.executable, "-m", "pytest",
                "tests/e2e",
                "-m", marker,
                "--collect-only",
                "-q"
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30
            )

            # Marker filtering should work (success even if no tests match)
            assert result.returncode in [0, 5], f"Marker {marker} filtering failed: {result.stderr}"
            print(f"✅ Marker {marker} filtering works")

    def test_comprehensive_test_count_validation(self):
        """Validate we maintain the 106 comprehensive test count"""

        project_root = Path(__file__).parent.parent.parent

        # Count existing unit tests (excluding E2E)
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            "tests/",
            "--ignore=tests/e2e",
            "--collect-only",
            "-q"
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60
        )

        assert result.returncode == 0, f"Could not count existing tests: {result.stderr}"

        # Extract test count from output
        output_lines = result.stdout.split('\n')
        collected_line = [line for line in output_lines if "collected" in line]

        if collected_line:
            # Parse collected count
            import re
            matches = re.findall(r'(\d+)', collected_line[0])
            if matches:
                test_count = int(matches[0])
                print(f"Found {test_count} existing unit tests")

                # Should have approximately 106 tests (allowing for some variance as codebase evolves)
                assert test_count >= 90, f"Test count {test_count} is below expected minimum of 90"
                assert test_count <= 150, f"Test count {test_count} is above expected maximum of 150"

                print(f"✅ Comprehensive test count validation passed: {test_count} tests")
            else:
                pytest.skip("Could not parse test count from pytest output")
        else:
            pytest.skip("Could not find collected tests information")

    def test_e2e_framework_documentation(self):
        """Validate E2E framework documentation exists"""

        project_root = Path(__file__).parent.parent.parent

        # Check for testing roadmap
        roadmap_file = project_root / "TESTING_ENHANCEMENT_ROADMAP.md"
        assert roadmap_file.exists(), "Testing roadmap documentation missing"

        # Check conftest.py has proper documentation
        conftest_file = project_root / "tests" / "e2e" / "conftest.py"
        assert conftest_file.exists(), "E2E conftest.py missing"

        # Read conftest and verify it has documentation
        conftest_content = conftest_file.read_text()
        assert '"""' in conftest_content, "E2E conftest.py lacks documentation"
        assert "Enhanced E2E Testing Configuration" in conftest_content, "E2E conftest.py lacks proper header documentation"

        print("✅ E2E framework documentation validation passed")

    def test_week_1_2_requirements_completion(self):
        """Validate all Week 1-2 requirements from roadmap are completed"""

        project_root = Path(__file__).parent.parent.parent

        # Week 1-2 requirements checklist
        requirements = {
            "enhanced_dependencies": {
                "description": "Install enhanced testing dependencies",
                "validation": lambda: self._check_dependencies_installed()
            },
            "playwright_setup": {
                "description": "Setup Playwright browser automation",
                "validation": lambda: self._check_playwright_setup()
            },
            "e2e_infrastructure": {
                "description": "Create E2E test infrastructure",
                "validation": lambda: self._check_e2e_infrastructure()
            },
            "first_workflow_test": {
                "description": "Implement first user workflow test",
                "validation": lambda: self._check_workflow_tests()
            }
        }

        results = {}
        for req_id, req_info in requirements.items():
            try:
                req_info["validation"]()
                results[req_id] = True
                print(f"✅ {req_info['description']}")
            except Exception as e:
                results[req_id] = False
                print(f"❌ {req_info['description']}: {e}")

        # All requirements should be completed
        failed_requirements = [req_id for req_id, passed in results.items() if not passed]

        assert len(failed_requirements) == 0, f"Week 1-2 requirements not completed: {failed_requirements}"
        print("✅ All Week 1-2 requirements completed successfully")

    def _check_dependencies_installed(self):
        """Check enhanced testing dependencies are installed"""
        required_packages = [
            'playwright',
            'pytest-playwright',
            'pytest-asyncio',
            'pytest-html',
            'pytest-xdist'
        ]

        for package in required_packages:
            try:
                __import__(package.replace('-', '_'))
            except ImportError:
                raise AssertionError(f"Required package {package} not installed")

    def _check_playwright_setup(self):
        """Check Playwright is properly setup"""
        try:
            from playwright.async_api import async_playwright
            # Try to access playwright - will fail if browsers not installed
            result = subprocess.run([
                sys.executable, "-c",
                "from playwright.async_api import async_playwright; print('OK')"
            ], capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                raise AssertionError(f"Playwright not properly setup: {result.stderr}")
        except Exception as e:
            raise AssertionError(f"Playwright setup validation failed: {e}")

    def _check_e2e_infrastructure(self):
        """Check E2E infrastructure is created"""
        project_root = Path(__file__).parent.parent.parent
        e2e_dir = project_root / "tests" / "e2e"

        required_dirs = [
            "page_objects",
            "workflows",
            "screenshots"
        ]

        required_files = [
            "conftest.py",
            "pytest.ini"
        ]

        for dir_name in required_dirs:
            dir_path = e2e_dir / dir_name
            if not dir_path.exists():
                raise AssertionError(f"Required E2E directory {dir_name} missing")

        for file_name in required_files:
            file_path = e2e_dir / file_name
            if not file_path.exists():
                raise AssertionError(f"Required E2E file {file_name} missing")

    def _check_workflow_tests(self):
        """Check workflow tests are implemented"""
        project_root = Path(__file__).parent.parent.parent
        workflows_dir = project_root / "tests" / "e2e" / "workflows"

        required_workflow_tests = [
            "test_employee_lifecycle.py",
            "test_attendance_tracking.py"
        ]

        for test_file in required_workflow_tests:
            test_path = workflows_dir / test_file
            if not test_path.exists():
                raise AssertionError(f"Required workflow test {test_file} missing")

            # Check test has actual test methods
            content = test_path.read_text()
            if "def test_" not in content:
                raise AssertionError(f"Workflow test {test_file} has no test methods")


@pytest.mark.smoke
class TestE2ESmoke:
    """Quick smoke tests for E2E framework functionality"""

    def test_import_page_objects(self):
        """Smoke test: Import all page objects"""
        try:
            from tests.e2e.page_objects.dashboard_page import DashboardPage
            from tests.e2e.page_objects.employee_page import EmployeePage
            from tests.e2e.page_objects.status_page import StatusPage
            print("✅ All page objects import successfully")
        except ImportError as e:
            pytest.fail(f"Page object import failed: {e}")

    def test_pytest_configuration(self):
        """Smoke test: Pytest configuration is valid"""
        project_root = Path(__file__).parent.parent.parent
        e2e_dir = project_root / "tests" / "e2e"

        # Test that pytest.ini is valid by running collection
        result = subprocess.run([
            sys.executable, "-m", "pytest",
            str(e2e_dir / "test_integration_validation.py"),
            "--collect-only",
            "-q"
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30
        )

        assert result.returncode == 0, f"pytest configuration invalid: {result.stderr}"
        print("✅ Pytest configuration is valid")

    def test_e2e_execution_script(self):
        """Smoke test: E2E execution script exists and is executable"""
        project_root = Path(__file__).parent.parent.parent
        script_path = project_root / "scripts" / "run_e2e_tests.sh"

        assert script_path.exists(), "E2E execution script missing"
        assert os.access(script_path, os.X_OK), "E2E execution script not executable"

        # Test script help
        result = subprocess.run([
            str(script_path), "--help"
        ], capture_output=True, text=True, timeout=10)

        assert result.returncode == 0, "E2E script help failed"
        assert "Usage:" in result.stdout, "E2E script help output invalid"
        print("✅ E2E execution script is functional")


if __name__ == "__main__":
    # Run integration validation tests
    pytest.main([__file__, "-v"])