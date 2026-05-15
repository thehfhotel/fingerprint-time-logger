"""
Focused tests for employee API endpoints to increase coverage
Tests employee management functionality including Thai name support
"""

import pytest
from datetime import datetime


class TestEmployeeEndpoints:
    """Test core employee API endpoints"""

    def test_get_employees(self, test_client, test_company_setup):
        """Test GET /api/private/employees/ - Get all employees"""
        response = test_client.get("/api/private/employees/")
        assert response.status_code == 200
        data = response.json()
        assert "employees" in data
        assert isinstance(data["employees"], list)

    def test_get_employees_with_filters(self, test_client, test_company_setup):
        """Test GET /api/private/employees/ with filter parameters"""
        # Test with include_hidden=true
        response = test_client.get("/api/private/employees/?include_hidden=true")
        assert response.status_code == 200

        # Test with include_inactive=true
        response = test_client.get("/api/private/employees/?include_inactive=true")
        assert response.status_code == 200

    def test_get_employee_by_badge(self, test_client, test_company_setup):
        """Test GET /api/private/employees/{badge} - Get specific employee"""
        employees = test_company_setup["employees"]
        if employees:
            badge = employees[0].badge_number
            response = test_client.get(f"/api/private/employees/{badge}")
            assert response.status_code == 200
            data = response.json()
            assert data["badge_number"] == badge

    def test_get_employee_not_found(self, test_client):
        """Test getting non-existent employee"""
        response = test_client.get("/api/private/employees/NONEXISTENT")
        assert response.status_code == 404


    def test_update_employee(self, test_client, test_company_setup):
        """Test PUT /api/private/employees/{badge} - Update employee"""
        employees = test_company_setup["employees"]
        if employees:
            badge = employees[0].badge_number
            update_data = {
                "badge_number": badge,
                "english_name": "Updated Employee Name",
                "thai_name": employees[0].thai_name,
                "display_name": "Updated Employee Name",
                "department": "Updated Department",
                "position": employees[0].position,
                "is_active": True,
                "is_hidden": False
            }
            response = test_client.put(f"/api/private/employees/{badge}", json=update_data)
            assert response.status_code == 200
            data = response.json()
            assert data["english_name"] == update_data["english_name"]

    def test_update_employee_nickname(self, test_client, test_company_setup):
        """Test PUT /api/private/employees/{badge}/nickname - Update nickname"""
        employees = test_company_setup["employees"]
        if employees:
            badge = employees[0].badge_number
            nickname_data = {
                "display_name": "New Nickname"
            }
            response = test_client.put(f"/api/private/employees/{badge}/nickname", json=nickname_data)
            assert response.status_code == 200
            data = response.json()
            assert data["display_name"] == nickname_data["display_name"]

    def test_update_employee_status(self, test_client, test_company_setup):
        """Test PUT /api/private/employees/{badge}/status - Update status"""
        employees = test_company_setup["employees"]
        if employees:
            badge = employees[0].badge_number
            status_data = {
                "is_active": False
            }
            response = test_client.put(f"/api/private/employees/{badge}/status", json=status_data)
            assert response.status_code == 200
            data = response.json()
            assert data["is_active"] == status_data["is_active"]

    def test_update_employee_hidden(self, test_client, test_company_setup):
        """Test PUT /api/private/employees/{badge}/hidden - Update hidden status"""
        employees = test_company_setup["employees"]
        if employees:
            badge = employees[0].badge_number
            hidden_data = {
                "is_hidden": True
            }
            response = test_client.put(f"/api/private/employees/{badge}/hidden", json=hidden_data)
            assert response.status_code == 200
            data = response.json()
            assert data["is_hidden"] == hidden_data["is_hidden"]

    def test_delete_employee(self, test_client, test_company_setup):
        """Test DELETE /api/private/employees/{badge} - Delete employee"""
        employees = test_company_setup["employees"]
        if employees and len(employees) > 1:  # Don't delete if only one
            badge = employees[-1].badge_number  # Delete the last one
            response = test_client.delete(f"/api/private/employees/{badge}")
            assert response.status_code in [200, 204]

    def test_get_employee_statistics(self, test_client, test_company_setup):
        """Test GET /api/private/employees/stats/summary - Employee statistics"""
        response = test_client.get("/api/private/employees/stats/summary")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_employees_health_check(self, test_client):
        """Test GET /api/private/employees/health - Health check"""
        response = test_client.get("/api/private/employees/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


class TestEmployeeEndpointsValidation:
    """Test employee endpoint validation and error cases"""


    def test_update_nonexistent_employee(self, test_client):
        """Test updating non-existent employee"""
        update_data = {
            "badge_number": "NONEXISTENT",
            "english_name": "Updated Name",
            "thai_name": "ชื่อใหม่",
            "display_name": "Updated Name",
            "is_active": True
        }
        response = test_client.put("/api/private/employees/NONEXISTENT", json=update_data)
        assert response.status_code == 404

    def test_invalid_badge_format(self, test_client):
        """Test employee operations with invalid badge format"""
        # Test empty badge
        response = test_client.get("/api/private/employees/")  # Empty badge in path
        assert response.status_code == 200  # This should get all employees

        # Test very long badge
        long_badge = "A" * 100
        response = test_client.get(f"/api/private/employees/{long_badge}")
        assert response.status_code == 404

    def test_update_nickname_nonexistent(self, test_client):
        """Test updating nickname for non-existent employee - creates employee"""
        nickname_data = {"nickname": "New Nickname"}
        response = test_client.put("/api/private/employees/NONEXISTENT/nickname", json=nickname_data)
        # API creates employee if it doesn't exist - this is intended behavior
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["created"] == True
        assert data["badge_number"] == "NONEXISTENT"

    def test_update_status_nonexistent(self, test_client):
        """Test updating status for non-existent employee - creates employee"""
        status_data = {"is_active": False}
        response = test_client.put("/api/private/employees/NONEXISTENT2/status", json=status_data)
        # API creates employee if it doesn't exist - this is intended behavior
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["badge_number"] == "NONEXISTENT2"
        assert data["is_active"] == False


class TestEmployeeThaiNameSupport:
    """Test Thai name functionality"""

    def test_get_thai_names(self, test_client, test_company_setup):
        """Test GET /api/private/employees/thai-names/ - Get Thai names"""
        response = test_client.get("/api/private/employees/thai-names/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (dict, list))

    def test_update_thai_name(self, test_client, test_company_setup):
        """Test PUT /api/private/employees/thai-names/{badge} - Update Thai name"""
        employees = test_company_setup["employees"]
        if employees:
            badge = employees[0].badge_number
            thai_name_data = {
                "thai_name": "ชื่อไทยใหม่",
                "display_name": "ชื่อไทยใหม่"
            }
            response = test_client.put(f"/api/private/employees/thai-names/{badge}", json=thai_name_data)
            assert response.status_code == 200
            data = response.json()
            assert data["thai_name"] == thai_name_data["thai_name"]


    def test_empty_display_name_fallback(self, test_client):
        """Test display name fallback logic"""
        employee_data = {
            "badge_number": "FALLBACK001",
            "english_name": "Fallback Test",
            "thai_name": "",  # Empty Thai name
            "display_name": "",  # Empty display name
            "is_active": True
        }
        response = test_client.post("/api/private/employees/", json=employee_data)
        if response.status_code in [200, 201]:
            data = response.json()
            # Should fallback to english_name or badge number
            assert data["display_name"] in [employee_data["english_name"], f"พนักงาน {employee_data['badge_number']}"]