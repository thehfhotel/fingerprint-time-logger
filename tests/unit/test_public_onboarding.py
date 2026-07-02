"""Unit tests for the public self-service onboarding API
(app.api.public_onboarding), mounted at /api/public/onboarding/*.
"""
from app.models.models import Employee
from app.services.line_auth_service import line_auth_service


def _jwt_for(line_user_id, display_name="Somchai", picture_url=None):
    return line_auth_service.create_jwt_token(
        line_user_id=line_user_id,
        employee_badge=None,
        display_name=display_name,
        picture_url=picture_url,
    )


VALID_BODY = {
    "thai_name": "สมชาย ใจดี",
    "english_name": "Somchai Jaidee",
    "nickname": "ชาย",
    "location": "HF",
    "department": "แม่บ้าน",
    "position": "พนักงานทำความสะอาด",
}


class TestSubmitOnboarding:
    def test_creates_pending_employee(self, test_client, test_db):
        token = _jwt_for("line-submit-001")
        response = test_client.post(
            "/api/public/onboarding/submit",
            json={"jwt_token": token, **VALID_BODY},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["badge_number"].startswith("Q")
        assert data["status"] == "pending"

        employee = (
            test_db.query(Employee)
            .filter(Employee.badge_number == data["badge_number"])
            .first()
        )
        assert employee is not None
        assert employee.pending_approval is True
        assert employee.is_active is False
        assert employee.join_source == "self_onboard"
        assert employee.line_user_id == "line-submit-001"
        assert employee.location == "HF"
        assert employee.display_name == "ชาย"
        assert employee.thai_name == "สมชาย ใจดี"

    def test_rejects_invalid_location(self, test_client):
        token = _jwt_for("line-submit-002")
        response = test_client.post(
            "/api/public/onboarding/submit",
            json={"jwt_token": token, **{**VALID_BODY, "location": "MARS"}},
        )
        assert response.status_code == 400

    def test_rejects_blank_thai_name(self, test_client):
        token = _jwt_for("line-submit-003")
        response = test_client.post(
            "/api/public/onboarding/submit",
            json={"jwt_token": token, **{**VALID_BODY, "thai_name": "   "}},
        )
        assert response.status_code == 400

    def test_rejects_invalid_jwt(self, test_client):
        response = test_client.post(
            "/api/public/onboarding/submit",
            json={"jwt_token": "not-a-real-jwt", **VALID_BODY},
        )
        assert response.status_code == 401

    def test_rejects_second_submission_for_same_line_account(self, test_client):
        token = _jwt_for("line-submit-004")
        first = test_client.post(
            "/api/public/onboarding/submit", json={"jwt_token": token, **VALID_BODY}
        )
        assert first.status_code == 200

        second = test_client.post(
            "/api/public/onboarding/submit", json={"jwt_token": token, **VALID_BODY}
        )
        assert second.status_code == 409

    def test_rate_limits_rapid_submissions(self, test_client):
        line_user_id = "line-submit-ratelimit"
        last_status = None
        for _ in range(6):
            token = _jwt_for(line_user_id)
            response = test_client.post(
                "/api/public/onboarding/submit", json={"jwt_token": token, **VALID_BODY}
            )
            last_status = response.status_code
        assert last_status == 429


class TestOnboardingStatus:
    def test_status_none_when_no_employee(self, test_client):
        token = _jwt_for("line-status-001")
        response = test_client.get(
            "/api/public/onboarding/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "none"

    def test_status_pending_after_submit(self, test_client):
        token = _jwt_for("line-status-002")
        submit = test_client.post(
            "/api/public/onboarding/submit", json={"jwt_token": token, **VALID_BODY}
        )
        assert submit.status_code == 200

        response = test_client.get(
            "/api/public/onboarding/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["badge_number"] == submit.json()["badge_number"]

    def test_status_approved_after_admin_approval(self, test_client, test_db):
        token = _jwt_for("line-status-003")
        submit = test_client.post(
            "/api/public/onboarding/submit", json={"jwt_token": token, **VALID_BODY}
        )
        badge = submit.json()["badge_number"]

        employee = test_db.query(Employee).filter(Employee.badge_number == badge).first()
        employee.is_active = True
        employee.pending_approval = False
        test_db.commit()

        response = test_client.get(
            "/api/public/onboarding/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["status"] == "approved"

    def test_status_rejected_after_admin_rejection_with_kept_history(self, test_client, test_db):
        token = _jwt_for("line-status-004")
        submit = test_client.post(
            "/api/public/onboarding/submit", json={"jwt_token": token, **VALID_BODY}
        )
        badge = submit.json()["badge_number"]

        employee = test_db.query(Employee).filter(Employee.badge_number == badge).first()
        employee.is_active = False
        employee.pending_approval = False
        test_db.commit()

        response = test_client.get(
            "/api/public/onboarding/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["status"] == "rejected"

    def test_status_requires_bearer_token(self, test_client):
        response = test_client.get("/api/public/onboarding/status")
        assert response.status_code == 401

    def test_status_includes_line_profile(self, test_client):
        token = _jwt_for("line-status-005", display_name="Nueng")
        response = test_client.get(
            "/api/public/onboarding/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.json()["line_display_name"] == "Nueng"
