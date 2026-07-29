"""Unit tests for the admin onboarding-approval API
(app.api.admin_onboarding), mounted at /api/private/admin/onboarding/*.
"""
from datetime import datetime

from app.models.models import AttendanceRecord, Employee, EmployeeAppGrant
from app.services.admin_auth_service import admin_auth_service
from app.services.badge_service import create_self_onboarded_employee


def _admin_cookies():
    return {"admin_session_token": admin_auth_service.create_session()}


def _make_pending_employee(test_db, line_user_id="line-admin-onb"):
    return create_self_onboarded_employee(
        test_db,
        thai_name="สมหญิง ดีใจ",
        english_name=None,
        nickname="หญิง",
        location="HF_VILLE",
        department=None,
        position=None,
        line_user_id=line_user_id,
        line_display_name="Somying",
        line_picture_url=None,
    )


class TestListPending:
    def test_requires_admin_auth(self, test_client):
        response = test_client.get("/api/private/admin/onboarding/pending")
        assert response.status_code == 401

    def test_lists_pending_employees(self, test_client, test_db):
        employee = _make_pending_employee(test_db)

        response = test_client.get(
            "/api/private/admin/onboarding/pending", cookies=_admin_cookies()
        )
        assert response.status_code == 200
        badges = [row["badge_number"] for row in response.json()]
        assert employee.badge_number in badges

    def test_approved_employee_not_listed(self, test_client, test_db):
        employee = _make_pending_employee(test_db, line_user_id="line-admin-onb-listed")
        employee.is_active = True
        employee.pending_approval = False
        test_db.commit()

        response = test_client.get(
            "/api/private/admin/onboarding/pending", cookies=_admin_cookies()
        )
        badges = [row["badge_number"] for row in response.json()]
        assert employee.badge_number not in badges


class TestApprove:
    def test_requires_admin_auth(self, test_client):
        response = test_client.post(
            "/api/private/admin/onboarding/approve", json={"badge_number": "Q1001"}
        )
        assert response.status_code == 401

    def test_approve_activates_and_grants_default_apps(self, test_client, test_db):
        employee = _make_pending_employee(test_db)

        response = test_client.post(
            "/api/private/admin/onboarding/approve",
            json={"badge_number": employee.badge_number},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 200
        data = response.json()
        expected_email = f"{employee.badge_number.lower()}@emp.thehfhotel.org"
        assert data["email"] == expected_email
        assert set(data["granted_app_ids"]) == {"rooms", "portal", "reimbursement"}

        test_db.refresh(employee)
        assert employee.is_active is True
        assert employee.pending_approval is False
        assert employee.email == expected_email

        grants = (
            test_db.query(EmployeeAppGrant)
            .filter(EmployeeAppGrant.employee_badge_number == employee.badge_number)
            .all()
        )
        assert {g.app_id for g in grants} == {"rooms", "portal", "reimbursement"}

    def test_approve_keeps_existing_email(self, test_client, test_db):
        employee = _make_pending_employee(test_db, line_user_id="line-admin-onb-email")
        employee.email = "custom@example.com"
        test_db.commit()

        response = test_client.post(
            "/api/private/admin/onboarding/approve",
            json={"badge_number": employee.badge_number},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 200
        assert response.json()["email"] == "custom@example.com"

    def test_approve_nonexistent_badge_404(self, test_client):
        response = test_client.post(
            "/api/private/admin/onboarding/approve",
            json={"badge_number": "Q9999"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 404

    def test_approve_non_pending_employee_400(self, test_client, test_db):
        employee = _make_pending_employee(test_db, line_user_id="line-admin-onb-2")
        employee.pending_approval = False
        test_db.commit()

        response = test_client.post(
            "/api/private/admin/onboarding/approve",
            json={"badge_number": employee.badge_number},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 400


class TestReject:
    def test_requires_admin_auth(self, test_client):
        response = test_client.post(
            "/api/private/admin/onboarding/reject", json={"badge_number": "Q1001"}
        )
        assert response.status_code == 401

    def test_reject_hard_deletes_when_no_attendance(self, test_client, test_db):
        employee = _make_pending_employee(test_db, line_user_id="line-admin-onb-3")
        badge = employee.badge_number

        response = test_client.post(
            "/api/private/admin/onboarding/reject",
            json={"badge_number": badge},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 200
        assert response.json()["action"] == "deleted"
        assert test_db.query(Employee).filter(Employee.badge_number == badge).first() is None

    def test_reject_deactivates_when_attendance_exists(self, test_client, test_db, test_device):
        employee = _make_pending_employee(test_db, line_user_id="line-admin-onb-4")
        test_db.add(AttendanceRecord(
            employee_badge_number=employee.badge_number,
            device_id=test_device.id,
            timestamp=datetime.utcnow(),
            punch_type=0,
        ))
        test_db.commit()

        response = test_client.post(
            "/api/private/admin/onboarding/reject",
            json={"badge_number": employee.badge_number},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 200
        assert response.json()["action"] == "deactivated"

        test_db.refresh(employee)
        assert employee.is_active is False
        assert employee.pending_approval is False
        assert (
            test_db.query(Employee).filter(Employee.badge_number == employee.badge_number).first()
            is not None
        )

    def test_reject_non_pending_employee_400(self, test_client, test_db):
        employee = _make_pending_employee(test_db, line_user_id="line-admin-onb-5")
        employee.pending_approval = False
        test_db.commit()

        response = test_client.post(
            "/api/private/admin/onboarding/reject",
            json={"badge_number": employee.badge_number},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 400
