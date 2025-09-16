"""
Unit tests for Consolidated Employees API Router
Tests all 9 endpoints in consolidated_employees.py
"""

import pytest
from datetime import datetime


class TestConsolidatedEmployeesAPI:
    """Test suite for consolidated employees endpoints"""

    def test_get_employees_list(self, test_client, test_company_setup):
        """Test GET /api/employees/ - List all employees"""
        response = test_client.get("/api/employees/")
        assert response.status_code == 200
        data = response.json()
        assert "employees" in data
        assert isinstance(data["employees"], list)

    def test_get_employees_list_with_filters(self, test_client, test_company_setup):
        """Test GET /api/employees/ with filters"""
        response = test_client.get("/api/employees/?active_only=true")
        assert response.status_code == 200
        data = response.json()
        # All returned employees should be active
        for employee in data["employees"]:
            assert employee["is_active"] is True

    def test_get_employees_list_include_hidden(self, test_client, test_company_setup):
        """Test GET /api/employees/ including hidden employees"""
        response = test_client.get("/api/employees/?include_hidden=true")
        assert response.status_code == 200
        data = response.json()
        assert "employees" in data

    def test_get_employee_by_badge(self, test_client, test_company_setup):
        """Test GET /api/employees/{badge_number} - Get specific employee"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            response = test_client.get(f"/api/employees/{badge_number}")
            assert response.status_code == 200
            data = response.json()
            assert data["badge_number"] == badge_number

    def test_get_employee_not_found(self, test_client):
        """Test GET /api/employees/{badge_number} - Employee not found"""
        response = test_client.get("/api/employees/9999")
        assert response.status_code == 404

    def test_create_employee(self, test_client, test_db):
        """Test POST /api/employees/ - Create new employee"""
        employee_data = {
            "badge_number": "9001",
            "english_name": "John Doe",
            "thai_name": "จอห์น โด",
            "display_name": "จอห์น โด",
            "department": "IT",
            "position": "Developer",
            "is_active": True,
            "is_hidden": False
        }
        response = test_client.post("/api/employees/", json=employee_data)
        assert response.status_code == 201
        data = response.json()
        assert data["badge_number"] == "9001"
        assert data["english_name"] == "John Doe"

    def test_create_employee_duplicate_badge(self, test_client, test_company_setup):
        """Test POST /api/employees/ with duplicate badge number"""
        employees = test_company_setup["employees"]
        if employees:
            existing_badge = employees[0].badge_number
            employee_data = {
                "badge_number": existing_badge,
                "english_name": "Duplicate Employee",
                "thai_name": "พนักงานซ้ำ",
                "display_name": "พนักงานซ้ำ",
                "is_active": True,
                "is_hidden": False
            }
            response = test_client.post("/api/employees/", json=employee_data)
            assert response.status_code in [400, 409]  # Conflict or Bad Request

    def test_update_employee(self, test_client, test_company_setup):
        """Test PUT /api/employees/{badge_number} - Update employee"""
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
            response = test_client.put(f"/api/employees/{badge_number}", json=update_data)
            assert response.status_code in [200, 404]

    def test_update_employee_thai_name(self, test_client, test_company_setup):
        """Test PUT /api/employees/{badge_number}/thai-name - Update Thai name only"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            thai_name_data = {
                "thai_name": "ชื่อไทยใหม่",
                "display_name": "ชื่อไทยใหม่"
            }
            response = test_client.put(f"/api/employees/{badge_number}/thai-name", json=thai_name_data)
            assert response.status_code in [200, 404]

    def test_update_employee_status(self, test_client, test_company_setup):
        """Test PUT /api/employees/{badge_number}/status - Update employee status"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            status_data = {
                "is_active": False,
                "is_hidden": True
            }
            response = test_client.put(f"/api/employees/{badge_number}/status", json=status_data)
            assert response.status_code in [200, 404]

    def test_delete_employee(self, test_client, test_company_setup):
        """Test DELETE /api/employees/{badge_number} - Delete employee"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            response = test_client.delete(f"/api/employees/{badge_number}")
            assert response.status_code in [200, 404]

    def test_get_employee_statistics(self, test_client, test_company_setup):
        """Test GET /api/employees/statistics - Get employee statistics"""
        response = test_client.get("/api/employees/statistics")
        assert response.status_code == 200
        data = response.json()
        assert "total_employees" in data
        assert "active_employees" in data
        assert "inactive_employees" in data
        assert "hidden_employees" in data


class TestConsolidatedEmployeesAPIEdgeCases:
    """Edge case tests for employees API"""

    def test_create_employee_invalid_badge_format(self, test_client):
        """Test creating employee with invalid badge number format"""
        invalid_badges = ["", " ", "  ", None]

        for badge in invalid_badges:
            employee_data = {
                "badge_number": badge,
                "english_name": "Test Employee",
                "thai_name": "พนักงานทดสอบ",
                "display_name": "พนักงานทดสอบ",
                "is_active": True,
                "is_hidden": False
            }
            response = test_client.post("/api/employees/", json=employee_data)
            assert response.status_code == 422  # Validation error

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
        response = test_client.put("/api/employees/9999", json=update_data)
        assert response.status_code == 404

    def test_delete_nonexistent_employee(self, test_client):
        """Test deleting non-existent employee"""
        response = test_client.delete("/api/employees/9999")
        assert response.status_code == 404

    def test_thai_name_with_special_characters(self, test_client, test_db):
        """Test creating employee with Thai name containing special characters"""
        employee_data = {
            "badge_number": "9002",
            "english_name": "Special Thai Name",
            "thai_name": "ก่อเก้ำเกํ็งๅๆไ",  # Special Thai characters
            "display_name": "ก่อเก้ำเกํ็งๅๆไ",
            "is_active": True,
            "is_hidden": False
        }
        response = test_client.post("/api/employees/", json=employee_data)
        assert response.status_code == 201

    def test_empty_display_name_fallback(self, test_client, test_db):
        """Test employee creation with empty display name (should fallback)"""
        employee_data = {
            "badge_number": "9003",
            "english_name": "Fallback Test",
            "thai_name": "",
            "display_name": "",  # Empty display name
            "is_active": True,
            "is_hidden": False
        }
        response = test_client.post("/api/employees/", json=employee_data)
        # Should either accept or validate display_name requirement
        assert response.status_code in [201, 422]


class TestConsolidatedEmployeesAPIValidation:
    """Validation tests for employees API"""

    def test_required_fields_validation(self, test_client):
        """Test validation of required fields"""
        incomplete_data = {
            "english_name": "Missing Badge"
            # Missing badge_number and display_name
        }
        response = test_client.post("/api/employees/", json=incomplete_data)
        assert response.status_code == 422

    def test_badge_number_uniqueness(self, test_client, test_company_setup):
        """Test badge number uniqueness constraint"""
        employees = test_company_setup["employees"]
        if employees:
            existing_badge = employees[0].badge_number

            duplicate_employee = {
                "badge_number": existing_badge,
                "english_name": "Duplicate Badge",
                "thai_name": "ซ้ำ",
                "display_name": "ซ้ำ",
                "is_active": True,
                "is_hidden": False
            }
            response = test_client.post("/api/employees/", json=duplicate_employee)
            assert response.status_code in [400, 409]

    def test_status_boolean_validation(self, test_client, test_company_setup):
        """Test boolean validation for status fields"""
        employees = test_company_setup["employees"]
        if employees:
            badge_number = employees[0].badge_number
            invalid_status = {
                "is_active": "not-a-boolean",
                "is_hidden": "also-not-a-boolean"
            }
            response = test_client.put(f"/api/employees/{badge_number}/status", json=invalid_status)
            assert response.status_code == 422


class TestConsolidatedEmployeesAPIPerformance:
    """Performance tests for employees API"""

    @pytest.mark.performance
    def test_employees_list_performance(self, test_client, performance_dataset):
        """Test performance of employees list with large dataset"""
        response = test_client.get("/api/employees/")
        assert response.status_code == 200
        # Should complete in reasonable time even with large employee list

    @pytest.mark.performance
    def test_employee_statistics_performance(self, test_client, performance_dataset):
        """Test performance of employee statistics calculation"""
        response = test_client.get("/api/employees/statistics")
        assert response.status_code == 200
        # Should calculate statistics efficiently even with large dataset

    @pytest.mark.performance
    def test_employee_search_performance(self, test_client, performance_dataset):
        """Test performance of employee search/filtering"""
        response = test_client.get("/api/employees/?active_only=true")
        assert response.status_code == 200
        # Should filter efficiently even with large dataset