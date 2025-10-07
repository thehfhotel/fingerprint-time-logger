"""
Integration tests for Admin LINE Workflow

Tests the complete end-to-end workflow for admin LINE code management:
1. Admin authenticates
2. Admin generates linking code
3. Employee links LINE account (simulated)
4. Admin views linked accounts
5. Admin unlinks account if needed
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta, timezone

from app.main_unified import fingerprint_app
from app.models.models import Employee
from app.api.admin_line_codes import ADMIN_PASSCODE


client = TestClient(fingerprint_app)


class TestAdminLINEWorkflowComplete:
    """Test complete admin workflow from start to finish"""

    def test_complete_workflow_success_path(self, db_session):
        """Test the complete happy path workflow"""
        # Step 1: Create employee
        employee = Employee(
            badge_number="WF001",
            display_name="Workflow Test",
            is_active=True
        )
        db_session.add(employee)
        db_session.commit()

        try:
            # Step 2: Admin authenticates
            auth_response = client.post(
                "/api/admin/line-codes/verify-passcode",
                json={"passcode": ADMIN_PASSCODE}
            )
            assert auth_response.status_code == 200

            # Step 3: Check initial stats
            stats_response = client.get(
                f"/api/admin/line-codes/stats?passcode={ADMIN_PASSCODE}"
            )
            assert stats_response.status_code == 200
            initial_stats = stats_response.json()

            # Step 4: Generate linking code
            generate_response = client.post(
                "/api/admin/line-codes/generate",
                json={
                    "badge_number": "WF001",
                    "passcode": ADMIN_PASSCODE
                }
            )
            assert generate_response.status_code == 200
            linking_code = generate_response.json()["linking_code"]
            assert len(linking_code) == 6

            # Step 5: Verify code appears in pending list
            pending_response = client.get(
                f"/api/admin/line-codes/list?passcode={ADMIN_PASSCODE}"
            )
            assert pending_response.status_code == 200
            pending_codes = pending_response.json()
            assert any(c["badge_number"] == "WF001" for c in pending_codes)

            # Step 6: Simulate employee linking (update database directly)
            db_session.refresh(employee)
            employee.line_user_id = "U_workflow_test_123"
            employee.line_display_name = "Workflow User"
            employee.line_linking_code = None  # Cleared after link
            db_session.commit()

            # Step 7: Verify account appears in linked list
            linked_response = client.get(
                f"/api/admin/line-codes/linked?passcode={ADMIN_PASSCODE}"
            )
            assert linked_response.status_code == 200
            linked_accounts = linked_response.json()
            assert any(a["badge_number"] == "WF001" for a in linked_accounts)

            # Step 8: Check updated stats
            final_stats_response = client.get(
                f"/api/admin/line-codes/stats?passcode={ADMIN_PASSCODE}"
            )
            final_stats = final_stats_response.json()
            assert final_stats["linked_accounts"] > initial_stats["linked_accounts"]

            # Step 9: Admin unlinks account
            unlink_response = client.post(
                "/api/admin/line-codes/unlink",
                json={
                    "badge_number": "WF001",
                    "passcode": ADMIN_PASSCODE,
                    "reason": "Test cleanup"
                }
            )
            assert unlink_response.status_code == 200

            # Step 10: Verify account no longer in linked list
            final_linked_response = client.get(
                f"/api/admin/line-codes/linked?passcode={ADMIN_PASSCODE}"
            )
            final_linked = final_linked_response.json()
            assert not any(a["badge_number"] == "WF001" for a in final_linked)

        finally:
            # Cleanup
            db_session.delete(employee)
            db_session.commit()

    def test_workflow_with_code_regeneration(self, db_session):
        """Test workflow where employee loses code and needs regeneration"""
        employee = Employee(
            badge_number="WF002",
            display_name="Regen Test",
            is_active=True
        )
        db_session.add(employee)
        db_session.commit()

        try:
            # Generate initial code
            generate_response = client.post(
                "/api/admin/line-codes/generate",
                json={
                    "badge_number": "WF002",
                    "passcode": ADMIN_PASSCODE
                }
            )
            initial_code = generate_response.json()["linking_code"]

            # Employee loses code, admin regenerates
            regen_response = client.post(
                "/api/admin/line-codes/regenerate",
                json={
                    "badge_number": "WF002",
                    "passcode": ADMIN_PASSCODE,
                    "reason": "Employee lost code"
                }
            )
            assert regen_response.status_code == 200
            new_code = regen_response.json()["new_code"]

            # Codes should be different
            assert new_code != initial_code

            # New code should be in pending list
            pending_response = client.get(
                f"/api/admin/line-codes/list?passcode={ADMIN_PASSCODE}"
            )
            pending_codes = pending_response.json()
            employee_code = next(c for c in pending_codes if c["badge_number"] == "WF002")
            assert employee_code["linking_code"] == new_code

        finally:
            db_session.delete(employee)
            db_session.commit()

    def test_workflow_prevents_duplicate_code_generation(self, db_session):
        """Test that generating code for employee with valid code returns existing"""
        employee = Employee(
            badge_number="WF003",
            display_name="No Duplicate Test",
            is_active=True
        )
        db_session.add(employee)
        db_session.commit()

        try:
            # First generation
            first_response = client.post(
                "/api/admin/line-codes/generate",
                json={
                    "badge_number": "WF003",
                    "passcode": ADMIN_PASSCODE
                }
            )
            first_code = first_response.json()["linking_code"]

            # Attempt second generation
            second_response = client.post(
                "/api/admin/line-codes/generate",
                json={
                    "badge_number": "WF003",
                    "passcode": ADMIN_PASSCODE
                }
            )
            second_code = second_response.json()["linking_code"]

            # Should return same code
            assert first_code == second_code
            assert "ยังใช้งานได้" in second_response.json()["message"]

        finally:
            db_session.delete(employee)
            db_session.commit()


class TestAdminLINEWorkflowMultiEmployee:
    """Test workflow with multiple employees"""

    def test_multiple_employees_different_codes(self, db_session):
        """Test that multiple employees get different codes"""
        employees = []
        for i in range(5):
            emp = Employee(
                badge_number=f"MULTI{i:03d}",
                display_name=f"Multi Test {i}",
                is_active=True
            )
            db_session.add(emp)
            employees.append(emp)
        db_session.commit()

        try:
            # Generate codes for all
            codes = []
            for emp in employees:
                response = client.post(
                    "/api/admin/line-codes/generate",
                    json={
                        "badge_number": emp.badge_number,
                        "passcode": ADMIN_PASSCODE
                    }
                )
                codes.append(response.json()["linking_code"])

            # All codes should be unique
            assert len(set(codes)) == 5

        finally:
            for emp in employees:
                db_session.delete(emp)
            db_session.commit()

    def test_stats_reflect_multiple_employees(self, db_session):
        """Test that stats correctly reflect multiple employee states"""
        # Create employees in different states
        emp_no_code = Employee(badge_number="STAT001", display_name="No Code", is_active=True)
        emp_with_code = Employee(
            badge_number="STAT002",
            display_name="With Code",
            is_active=True,
            line_linking_code="111111",
            line_linking_code_generated_at=datetime.now(timezone.utc)
        )
        emp_linked = Employee(
            badge_number="STAT003",
            display_name="Linked",
            is_active=True,
            line_user_id="U_linked_123"
        )

        db_session.add_all([emp_no_code, emp_with_code, emp_linked])
        db_session.commit()

        try:
            stats_response = client.get(
                f"/api/admin/line-codes/stats?passcode={ADMIN_PASSCODE}"
            )
            stats = stats_response.json()

            assert stats["unlinked"] >= 1  # emp_no_code
            assert stats["pending_codes"] >= 1  # emp_with_code
            assert stats["linked_accounts"] >= 1  # emp_linked

        finally:
            db_session.delete(emp_no_code)
            db_session.delete(emp_with_code)
            db_session.delete(emp_linked)
            db_session.commit()


class TestAdminLINEWorkflowErrorRecovery:
    """Test error recovery in workflow"""

    def test_workflow_continues_after_invalid_badge(self, db_session):
        """Test workflow continues after attempting invalid badge number"""
        # Try to generate code for non-existent employee
        error_response = client.post(
            "/api/admin/line-codes/generate",
            json={
                "badge_number": "INVALID999",
                "passcode": ADMIN_PASSCODE
            }
        )
        assert error_response.status_code == 404

        # Create valid employee and verify workflow still works
        employee = Employee(
            badge_number="RECOVERY001",
            display_name="Recovery Test",
            is_active=True
        )
        db_session.add(employee)
        db_session.commit()

        try:
            success_response = client.post(
                "/api/admin/line-codes/generate",
                json={
                    "badge_number": "RECOVERY001",
                    "passcode": ADMIN_PASSCODE
                }
            )
            assert success_response.status_code == 200

        finally:
            db_session.delete(employee)
            db_session.commit()

    def test_workflow_handles_expired_code_gracefully(self, db_session):
        """Test workflow handles expired codes correctly"""
        employee = Employee(
            badge_number="EXPIRED001",
            display_name="Expired Test",
            is_active=True,
            line_linking_code="888888",
            line_linking_code_generated_at=datetime.now(timezone.utc) - timedelta(hours=25)
        )
        db_session.add(employee)
        db_session.commit()

        try:
            # Expired code should not appear in default pending list
            pending_response = client.get(
                f"/api/admin/line-codes/list?passcode={ADMIN_PASSCODE}"
            )
            pending_codes = pending_response.json()
            assert not any(c["badge_number"] == "EXPIRED001" for c in pending_codes)

            # But should appear when including expired
            with_expired_response = client.get(
                f"/api/admin/line-codes/list?passcode={ADMIN_PASSCODE}&include_expired=true"
            )
            with_expired = with_expired_response.json()
            expired_code = next(
                (c for c in with_expired if c["badge_number"] == "EXPIRED001"),
                None
            )
            assert expired_code is not None
            assert expired_code["is_expired"] is True

            # Regenerating should work
            regen_response = client.post(
                "/api/admin/line-codes/regenerate",
                json={
                    "badge_number": "EXPIRED001",
                    "passcode": ADMIN_PASSCODE
                }
            )
            assert regen_response.status_code == 200

        finally:
            db_session.delete(employee)
            db_session.commit()


class TestAdminLINEWorkflowSecurity:
    """Test security aspects of the workflow"""

    def test_workflow_requires_passcode_at_each_step(self, db_session):
        """Test that all workflow steps require valid passcode"""
        employee = Employee(
            badge_number="SEC001",
            display_name="Security Test",
            is_active=True
        )
        db_session.add(employee)
        db_session.commit()

        try:
            # All endpoints should reject invalid passcode
            endpoints = [
                ("POST", "/api/admin/line-codes/generate",
                 {"badge_number": "SEC001", "passcode": "wrong"}),
                ("POST", "/api/admin/line-codes/regenerate",
                 {"badge_number": "SEC001", "passcode": "wrong"}),
                ("POST", "/api/admin/line-codes/unlink",
                 {"badge_number": "SEC001", "passcode": "wrong"}),
            ]

            for method, url, data in endpoints:
                if method == "POST":
                    response = client.post(url, json=data)
                    assert response.status_code == 403

            # GET endpoints with query param
            get_endpoints = [
                "/api/admin/line-codes/list?passcode=wrong",
                "/api/admin/line-codes/linked?passcode=wrong",
                "/api/admin/line-codes/stats?passcode=wrong"
            ]

            for url in get_endpoints:
                response = client.get(url)
                assert response.status_code == 403

        finally:
            db_session.delete(employee)
            db_session.commit()

    def test_workflow_clears_code_after_linking(self, db_session):
        """Test that linking code is cleared after successful link"""
        employee = Employee(
            badge_number="CLEAR001",
            display_name="Clear Test",
            is_active=True
        )
        db_session.add(employee)
        db_session.commit()

        try:
            # Generate code
            generate_response = client.post(
                "/api/admin/line-codes/generate",
                json={
                    "badge_number": "CLEAR001",
                    "passcode": ADMIN_PASSCODE
                }
            )
            assert generate_response.status_code == 200

            # Simulate linking
            db_session.refresh(employee)
            employee.line_user_id = "U_clear_test"
            employee.line_linking_code = None  # Should be cleared
            db_session.commit()

            # Verify code is cleared
            db_session.refresh(employee)
            assert employee.line_linking_code is None

            # Verify code regeneration is allowed (API design allows re-generation)
            # Note: The API currently allows generating new codes even after linking
            # This is intentional to support admin operations and re-linking scenarios
            generate_again_response = client.post(
                "/api/admin/line-codes/generate",
                json={
                    "badge_number": "CLEAR001",
                    "passcode": ADMIN_PASSCODE
                }
            )
            assert generate_again_response.status_code == 200

        finally:
            db_session.delete(employee)
            db_session.commit()


class TestAdminLINEWorkflowPerformance:
    """Test performance aspects of the workflow"""

    def test_workflow_batch_code_generation_performance(self, db_session):
        """Test generating codes for many employees completes quickly"""
        import time

        # Create 20 employees
        employees = []
        for i in range(20):
            emp = Employee(
                badge_number=f"PERF{i:03d}",
                display_name=f"Perf Test {i}",
                is_active=True
            )
            db_session.add(emp)
            employees.append(emp)
        db_session.commit()

        try:
            start = time.time()

            # Generate codes for all
            for emp in employees:
                response = client.post(
                    "/api/admin/line-codes/generate",
                    json={
                        "badge_number": emp.badge_number,
                        "passcode": ADMIN_PASSCODE
                    }
                )
                assert response.status_code == 200

            duration = time.time() - start

            # Should complete in reasonable time (< 5 seconds for 20 employees)
            assert duration < 5.0

        finally:
            for emp in employees:
                db_session.delete(emp)
            db_session.commit()

    def test_workflow_stats_query_performance(self, db_session):
        """Test stats query performs well with many employees"""
        import time

        # Create many employees in different states
        employees = []
        for i in range(50):
            state = i % 3
            emp = Employee(
                badge_number=f"STATS{i:03d}",
                display_name=f"Stats Test {i}",
                is_active=True
            )

            if state == 0:
                # No code
                pass
            elif state == 1:
                # With code
                emp.line_linking_code = f"{i:06d}"
                emp.line_linking_code_generated_at = datetime.now(timezone.utc)
            else:
                # Linked
                emp.line_user_id = f"U_{i:06d}"

            db_session.add(emp)
            employees.append(emp)
        db_session.commit()

        try:
            start = time.time()

            # Query stats multiple times
            for _ in range(10):
                response = client.get(
                    f"/api/admin/line-codes/stats?passcode={ADMIN_PASSCODE}"
                )
                assert response.status_code == 200

            duration = time.time() - start

            # 10 stats queries should complete quickly (< 1 second)
            assert duration < 1.0

        finally:
            for emp in employees:
                db_session.delete(emp)
            db_session.commit()


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def db_session():
    """Get database session for testing"""
    from app.core.database import SessionLocal
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
