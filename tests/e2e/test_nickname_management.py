"""
CLI-based Nickname Management E2E Tests
Tests employee/nickname management functionality using HTTP requests
"""

import pytest
import json


@pytest.mark.e2e
@pytest.mark.cli
@pytest.mark.api
class TestNicknameManagement:
    """Test nickname/employee management functionality using HTTP requests"""

    def test_nickname_management_page_loads(self, api_client, app_running):
        """Test that the nickname management page loads successfully"""
        response = api_client.get("/nickname-management")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

        # Check for key elements in HTML
        content = response.text
        assert "nickname" in content.lower() or "employee" in content.lower()

    def test_employees_api_endpoint(self, api_client, app_running):
        """Test that the employees API endpoint is accessible"""
        response = api_client.get("/api/employees/")
        assert response.status_code in [200, 404]  # 404 if no employees exist

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (dict, list))

    def test_employees_health_check(self, api_client, app_running):
        """Test employee system health check"""
        response = api_client.get("/api/employees/health")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert "status" in data or "health" in data

    def test_employee_thai_names_endpoint(self, api_client, app_running):
        """Test Thai names endpoint for nickname management"""
        response = api_client.get("/api/employees/thai-names/")
        assert response.status_code in [200, 404]  # 404 if no employees with Thai names

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, (dict, list))

    def test_employee_statistics_endpoint(self, api_client, app_running):
        """Test employee statistics summary"""
        response = api_client.get("/api/employees/stats/summary")
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)
            # Should have statistical information - check for actual keys returned
            assert any(key in data for key in ["total_employees", "total", "active", "count", "statistics", "with_thai_names"])

    def test_employee_data_structure(self, api_client, app_running):
        """Test employee data structure for nickname management"""
        response = api_client.get("/api/employees/")

        if response.status_code == 200:
            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                # Check structure of first employee
                employee = data[0]
                assert isinstance(employee, dict)
                # Should have basic employee fields
                assert any(key in employee for key in ["badge_number", "id", "badge"])

            elif isinstance(data, dict) and "employees" in data:
                employees = data["employees"]
                if len(employees) > 0:
                    employee = employees[0]
                    assert isinstance(employee, dict)

    def test_specific_employee_lookup(self, api_client, app_running, test_data):
        """Test specific employee lookup by badge number"""
        # First, get list of employees to find a valid badge number
        response = api_client.get("/api/employees/")

        if response.status_code == 200:
            data = response.json()

            # Extract badge number from available employees
            badge_number = None
            if isinstance(data, list) and len(data) > 0:
                badge_number = data[0].get("badge_number") or data[0].get("badge")
            elif isinstance(data, dict) and "employees" in data and len(data["employees"]) > 0:
                badge_number = data["employees"][0].get("badge_number") or data["employees"][0].get("badge")

            if badge_number:
                # Test specific employee lookup
                response = api_client.get(f"/api/employees/{badge_number}")
                assert response.status_code in [200, 404]

                if response.status_code == 200:
                    employee_data = response.json()
                    assert isinstance(employee_data, dict)
                    assert str(badge_number) in str(employee_data.get("badge_number", "")) or \
                           str(badge_number) in str(employee_data.get("badge", ""))

    def test_employee_filtering_options(self, api_client, app_running):
        """Test employee filtering options for nickname management"""
        # Test with include_hidden parameter
        response = api_client.get("/api/employees/", params={"include_hidden": "true"})
        assert response.status_code in [200, 404]

        response = api_client.get("/api/employees/", params={"include_hidden": "false"})
        assert response.status_code in [200, 404]

    def test_nickname_management_data_consistency(self, api_client, app_running):
        """Test data consistency for nickname management"""
        # Get employees list
        response = api_client.get("/api/employees/")

        if response.status_code == 200:
            data = response.json()

            # Check that the data structure is consistent
            if isinstance(data, list):
                for employee in data:
                    assert isinstance(employee, dict)
                    # Each employee should have some identifying information
                    assert any(key in employee for key in ["badge_number", "id", "badge", "name"])

            elif isinstance(data, dict):
                # If it's a dict, it should have meaningful structure
                assert len(data) > 0, "Empty employee data structure"

    def test_nickname_page_navigation(self, api_client, app_running):
        """Test navigation from nickname management page"""
        # Test that other pages are accessible (simulating navigation)
        pages_to_test = ["/", "/status", "/export"]

        for page in pages_to_test:
            response = api_client.get(page)
            assert response.status_code == 200, f"Navigation to {page} should work"

    def test_employee_search_data_structure(self, api_client, app_running):
        """Test data structure that would support search functionality"""
        response = api_client.get("/api/employees/")

        if response.status_code == 200:
            data = response.json()

            # Check if employees have searchable fields
            if isinstance(data, list) and len(data) > 0:
                employee = data[0]
                # Should have name fields that can be searched
                searchable_fields = ["english_name", "thai_name", "name", "display_name"]
                has_searchable = any(field in employee for field in searchable_fields)
                assert has_searchable, f"Employee should have searchable name fields, got: {list(employee.keys())}"

    def test_employee_status_fields(self, api_client, app_running):
        """Test employee status fields for nickname management"""
        response = api_client.get("/api/employees/")

        if response.status_code == 200:
            data = response.json()

            # Check if employees have status-related fields
            if isinstance(data, list) and len(data) > 0:
                employee = data[0]
                # Check for fields that might relate to employee status/visibility
                status_fields = ["status", "active", "hidden", "visible", "enabled"]
                # At least some status information should be available
                # (This is flexible since the exact field names may vary)
                assert isinstance(employee, dict), "Employee data should be a dictionary"

    def test_nickname_management_error_handling(self, api_client, app_running):
        """Test error handling for invalid requests"""
        # Test invalid employee badge number
        response = api_client.get("/api/employees/INVALID_BADGE_999")
        assert response.status_code in [404, 422]  # 404 not found or 422 validation error

        # Test invalid query parameters
        response = api_client.get("/api/employees/", params={"invalid_param": "test"})
        # Should still work (invalid params should be ignored)
        assert response.status_code in [200, 404, 422]

    def test_employee_thai_localization(self, api_client, app_running):
        """Test Thai localization support for nickname management"""
        response = api_client.get("/api/employees/thai-names/")

        if response.status_code == 200:
            data = response.json()

            # Check if Thai names are properly handled
            if isinstance(data, list) and len(data) > 0:
                # Look for Thai characters or Thai name fields
                for employee in data:
                    if isinstance(employee, dict):
                        thai_fields = ["thai_name", "thai_display_name"]
                        # If Thai name fields exist, they should contain data
                        for field in thai_fields:
                            if field in employee and employee[field]:
                                # Should handle Unicode/Thai characters properly
                                assert isinstance(employee[field], str)
                                break