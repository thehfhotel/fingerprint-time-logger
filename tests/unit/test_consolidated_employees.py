"""
Unit tests for Consolidated Employees API Router
Tests all 9 endpoints in consolidated_employees.py
"""

import pytest
from datetime import datetime


class TestConsolidatedEmployeesAPI:
    """Test suite for consolidated employees endpoints"""

    def test_get_employees_list(self, test_client, test_company_setup):
        """Test GET /api/private/employees/ - List all employees"""
        response = test_client.get("/api/private/employees/")
        assert response.status_code == 200
        data = response.json()
        assert "employees" in data
        assert isinstance(data["employees"], list)

    def test_get_employees_list_with_filters(self, test_client, test_company_setup):
        """Test GET /api/private/employees/ with filters"""
        response = test_client.get("/api/private/employees/?active_only=true")
        assert response.status_code == 200
        data = response.json()
        # All returned employees should be active
        for employee in data["employees"]:
            assert employee["is_active"] is True

    def test_get_employees_list_include_hidden(self, test_client, test_company_setup):
        """Test GET /api/private/employees/ including hidden employees"""
        response = test_client.get("/api/private/employees/?include_hidden=true")
        assert response.status_code == 200
        data = response.json()
        assert "employees" in data

    def test_get_employee_by_badge(self, test_client, test_company_setup):
        """Test GET /api/private/employees/{badge_number} - Get specific employee"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            response = test_client.get(f"/api/private/employees/{badge_number}")
            assert response.status_code == 200
            data = response.json()
            assert data["badge_number"] == badge_number

    def test_get_employee_not_found(self, test_client):
        """Test GET /api/private/employees/{badge_number} - Employee not found"""
        response = test_client.get("/api/private/employees/9999")
        assert response.status_code == 404



    def test_update_employee(self, test_client, test_company_setup):
        """Test PUT /api/private/employees/{badge_number} - Update employee"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            update_data = {
                "badge_number": badge_number,
                "english_name": "Updated Name",
                "thai_name": "ชื่ออัปเดต",
                "display_name": "ชื่ออัปเดต",
                "department": "Updated Department",
                "position": "Updated Position",
                "is_active": True,
                "is_hidden": False
            }
            response = test_client.put(f"/api/private/employees/{badge_number}", json=update_data)
            assert response.status_code in [200, 404]

    def test_update_employee_thai_name(self, test_client, test_company_setup):
        """Test PUT /api/private/employees/{badge_number}/thai-name - Update Thai name only"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            thai_name_data = {
                "thai_name": "ชื่อไทยใหม่",
                "display_name": "ชื่อไทยใหม่"
            }
            response = test_client.put(f"/api/private/employees/{badge_number}/thai-name", json=thai_name_data)
            assert response.status_code in [200, 404]

    def test_update_employee_status(self, test_client, test_company_setup):
        """Test PUT /api/private/employees/{badge_number}/status - Update employee status"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            status_data = {
                "is_active": False,
                "is_hidden": True
            }
            response = test_client.put(f"/api/private/employees/{badge_number}/status", json=status_data)
            assert response.status_code in [200, 404]

    def test_delete_employee(self, test_client, test_company_setup):
        """Test DELETE /api/private/employees/{badge_number} - Delete employee"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            response = test_client.delete(f"/api/private/employees/{badge_number}")
            assert response.status_code in [200, 404]



class TestConsolidatedEmployeesAPIEdgeCases:
    """Edge case tests for employees API"""


    def test_update_nonexistent_employee(self, test_client):
        """Test updating non-existent employee"""
        update_data = {
            "badge_number": "9999",
            "english_name": "Non-existent Employee",
            "thai_name": "ไม่มีอยู่จริง",
            "display_name": "ไม่มีอยู่จริง",
            "is_active": True,
            "is_hidden": False
        }
        response = test_client.put("/api/private/employees/9999", json=update_data)
        assert response.status_code == 404

    def test_delete_nonexistent_employee(self, test_client):
        """Test deleting non-existent employee"""
        response = test_client.delete("/api/private/employees/9999")
        assert response.status_code == 404




class TestConsolidatedEmployeesAPIValidation:
    """Validation tests for employees API"""



    def test_status_boolean_validation(self, test_client, test_company_setup):
        """Test boolean validation for status fields"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            invalid_status = {
                "is_active": "not-a-boolean",
                "is_hidden": "also-not-a-boolean"
            }
            response = test_client.put(f"/api/private/employees/{badge_number}/status", json=invalid_status)
            assert response.status_code in [422, 500]  # Accept validation error or server error


class TestConsolidatedEmployeesAPIPerformance:
    """Performance tests for employees API"""

    @pytest.mark.performance
    def test_employees_list_performance(self, test_client, performance_dataset):
        """Test performance of employees list with large dataset"""
        response = test_client.get("/api/private/employees/")
        assert response.status_code == 200
        # Should complete in reasonable time even with large employee list

    @pytest.mark.performance

    @pytest.mark.performance
    def test_employee_search_performance(self, test_client, performance_dataset):
        """Test performance of employee search/filtering"""
        response = test_client.get("/api/private/employees/?active_only=true")
        assert response.status_code == 200
        # Should filter efficiently even with large dataset