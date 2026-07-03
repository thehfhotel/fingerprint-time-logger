"""Unit tests for the admin employee-registry API (app.api.admin_employees):
app grants, NFC card slot, and the device-badge/Q-badge merge tool.
"""
import datetime

from app.models.models import (
    Employee,
    EmployeeAppGrant,
    EmployeeLeave,
    ShiftAssignment,
)
from app.services.admin_auth_service import admin_auth_service


def _admin_cookies():
    return {"admin_session_token": admin_auth_service.create_session()}


def _make_employee(test_db, badge, **overrides):
    defaults = dict(badge_number=badge, display_name=f"emp-{badge}", is_active=True, is_hidden=False)
    defaults.update(overrides)
    employee = Employee(**defaults)
    test_db.add(employee)
    test_db.commit()
    test_db.refresh(employee)
    return employee


class TestAppGrants:
    def test_requires_admin_auth(self, test_client, test_db):
        _make_employee(test_db, "1001")
        response = test_client.get("/api/private/admin/employees/1001/grants")
        assert response.status_code == 401

    def test_get_grants_empty_by_default(self, test_client, test_db):
        _make_employee(test_db, "1002")
        response = test_client.get(
            "/api/private/admin/employees/1002/grants", cookies=_admin_cookies()
        )
        assert response.status_code == 200
        data = response.json()
        assert data["granted_app_ids"] == []
        assert {c["app_id"] for c in data["catalog"]} == {"rooms", "portal", "payroll"}

    def test_put_grants_full_set_replace(self, test_client, test_db):
        _make_employee(test_db, "1003")

        first = test_client.put(
            "/api/private/admin/employees/1003/grants",
            json={"app_ids": ["rooms"]},
            cookies=_admin_cookies(),
        )
        assert first.status_code == 200
        assert first.json()["granted_app_ids"] == ["rooms"]

        second = test_client.put(
            "/api/private/admin/employees/1003/grants",
            json={"app_ids": ["portal"]},
            cookies=_admin_cookies(),
        )
        assert second.status_code == 200
        assert second.json()["granted_app_ids"] == ["portal"]

        grants = (
            test_db.query(EmployeeAppGrant)
            .filter(EmployeeAppGrant.employee_badge_number == "1003")
            .all()
        )
        assert [g.app_id for g in grants] == ["portal"]

    def test_put_grants_rejects_unknown_app_id(self, test_client, test_db):
        _make_employee(test_db, "1004")
        response = test_client.put(
            "/api/private/admin/employees/1004/grants",
            json={"app_ids": ["not-a-real-app"]},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 400

    def test_grants_for_nonexistent_employee_404(self, test_client):
        response = test_client.get(
            "/api/private/admin/employees/9999/grants", cookies=_admin_cookies()
        )
        assert response.status_code == 404


class TestNfcCard:
    def test_set_and_clear_nfc_card(self, test_client, test_db):
        _make_employee(test_db, "1005")

        set_response = test_client.put(
            "/api/private/admin/employees/1005/nfc-card",
            json={"uid": "AABBCCDD"},
            cookies=_admin_cookies(),
        )
        assert set_response.status_code == 200
        assert set_response.json()["nfc_card_uid"] == "AABBCCDD"

        clear_response = test_client.put(
            "/api/private/admin/employees/1005/nfc-card",
            json={"uid": None},
            cookies=_admin_cookies(),
        )
        assert clear_response.status_code == 200
        assert clear_response.json()["nfc_card_uid"] is None

    def test_nfc_card_collision_returns_409_naming_other_employee(self, test_client, test_db):
        _make_employee(test_db, "1006", nfc_card_uid="DEADBEEF")
        _make_employee(test_db, "1007")

        response = test_client.put(
            "/api/private/admin/employees/1007/nfc-card",
            json={"uid": "DEADBEEF"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 409
        assert "1006" in response.json()["detail"]

    def test_nfc_card_nonexistent_employee_404(self, test_client):
        response = test_client.put(
            "/api/private/admin/employees/9999/nfc-card",
            json={"uid": "ANYTHING"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 404


class TestMergeEmployees:
    def test_requires_admin_auth(self, test_client):
        response = test_client.post(
            "/api/private/admin/employees/merge",
            json={"from_badge": "Q1001", "to_badge": "1001"},
        )
        assert response.status_code == 401

    def test_rename_case_when_target_missing(self, test_client, test_db, test_device):
        _make_employee(test_db, "Q1001", thai_name="สมชาย")
        test_db.add(EmployeeAppGrant(employee_badge_number="Q1001", app_id="rooms"))
        test_db.commit()

        response = test_client.post(
            "/api/private/admin/employees/merge",
            json={"from_badge": "Q1001", "to_badge": "2001"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["case"] == "rename"

        assert test_db.query(Employee).filter(Employee.badge_number == "Q1001").first() is None
        renamed = test_db.query(Employee).filter(Employee.badge_number == "2001").first()
        assert renamed is not None
        assert renamed.thai_name == "สมชาย"

        assert (
            test_db.query(EmployeeAppGrant)
            .filter(EmployeeAppGrant.employee_badge_number == "2001")
            .count()
            == 1
        )

    def test_merge_case_moves_children_and_drops_duplicates(self, test_client, test_db):
        _make_employee(test_db, "Q1002")
        _make_employee(test_db, "2002", email="existing@example.com")

        same_date = datetime.date(2026, 7, 1)
        # Collision: both from and to have a leave on the same date -> from's is dropped.
        test_db.add(EmployeeLeave(employee_badge_number="Q1002", date=same_date, leave_type="sick"))
        test_db.add(EmployeeLeave(employee_badge_number="2002", date=same_date, leave_type="vacation"))
        # No collision: from has a leave on a distinct date -> moved.
        test_db.add(EmployeeLeave(
            employee_badge_number="Q1002", date=datetime.date(2026, 7, 2), leave_type="personal"
        ))
        test_db.commit()

        response = test_client.post(
            "/api/private/admin/employees/merge",
            json={"from_badge": "Q1002", "to_badge": "2002"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["case"] == "merge"
        assert data["summary"]["employee_leaves"]["moved"] == 1
        assert data["summary"]["employee_leaves"]["dropped_duplicate"] == 1

        assert test_db.query(Employee).filter(Employee.badge_number == "Q1002").first() is None
        to_employee = test_db.query(Employee).filter(Employee.badge_number == "2002").first()
        assert to_employee.email == "existing@example.com"  # untouched, already set

        remaining_leaves = (
            test_db.query(EmployeeLeave)
            .filter(EmployeeLeave.employee_badge_number == "2002")
            .all()
        )
        assert len(remaining_leaves) == 2
        assert {l.leave_type for l in remaining_leaves} == {"vacation", "personal"}

    def test_merge_copies_fields_only_when_target_empty(self, test_client, test_db):
        _make_employee(test_db, "Q1003", email="fromq@example.com", department="แม่บ้าน")
        _make_employee(test_db, "2003", email=None, department=None)

        response = test_client.post(
            "/api/private/admin/employees/merge",
            json={"from_badge": "Q1003", "to_badge": "2003"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 200

        to_employee = test_db.query(Employee).filter(Employee.badge_number == "2003").first()
        assert to_employee.email == "fromq@example.com"
        assert to_employee.department == "แม่บ้าน"

    def test_refuses_when_both_have_different_line_accounts(self, test_client, test_db):
        _make_employee(test_db, "Q1004", line_user_id="line-A")
        _make_employee(test_db, "2004", line_user_id="line-B")

        response = test_client.post(
            "/api/private/admin/employees/merge",
            json={"from_badge": "Q1004", "to_badge": "2004"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 409

        assert test_db.query(Employee).filter(Employee.badge_number == "Q1004").first() is not None
        assert test_db.query(Employee).filter(Employee.badge_number == "2004").first() is not None

    def test_from_badge_not_found_404(self, test_client, test_db):
        _make_employee(test_db, "2005")
        response = test_client.post(
            "/api/private/admin/employees/merge",
            json={"from_badge": "QNOPE", "to_badge": "2005"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 404

    def test_same_badge_rejected(self, test_client, test_db):
        _make_employee(test_db, "2006")
        response = test_client.post(
            "/api/private/admin/employees/merge",
            json={"from_badge": "2006", "to_badge": "2006"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 400

    def test_transactionality_forced_failure_leaves_everything_untouched(
        self, test_client, test_db, monkeypatch
    ):
        """A failure partway through the merge rolls back ALL of it —
        including a child-table move that already succeeded before the
        injected failure."""
        _make_employee(test_db, "Q1005", email="fromq@example.com")
        _make_employee(test_db, "2007", email=None)
        test_db.add(ShiftAssignment(
            employee_badge_number="Q1005", date=datetime.date(2026, 7, 3), shift_id=None
        ))
        test_db.add(EmployeeLeave(
            employee_badge_number="Q1005", date=datetime.date(2026, 7, 4), leave_type="sick"
        ))
        test_db.commit()

        import app.api.admin_employees as admin_employees_module

        original = admin_employees_module._move_or_drop_duplicates
        call_count = {"n": 0}

        def boom(db, model, badge_column, unique_columns, from_badge, to_badge):
            call_count["n"] += 1
            result = original(db, model, badge_column, unique_columns, from_badge, to_badge)
            if call_count["n"] == 1:
                # ShiftAssignment (first in _UNIQUE_CHILD_TABLES) succeeded —
                # now blow up before EmployeeSchedule/EmployeeLeave/EmployeeAppGrant run.
                raise RuntimeError("injected failure")
            return result

        monkeypatch.setattr(admin_employees_module, "_move_or_drop_duplicates", boom)

        response = test_client.post(
            "/api/private/admin/employees/merge",
            json={"from_badge": "Q1005", "to_badge": "2007"},
            cookies=_admin_cookies(),
        )
        assert response.status_code == 500

        # Nothing changed: both employees still exist, unmodified.
        assert test_db.query(Employee).filter(Employee.badge_number == "Q1005").first() is not None
        to_employee = test_db.query(Employee).filter(Employee.badge_number == "2007").first()
        assert to_employee is not None
        assert to_employee.email is None  # copy-if-empty never committed

        # The ShiftAssignment move that succeeded before the injected
        # failure was rolled back along with everything else.
        assert (
            test_db.query(ShiftAssignment)
            .filter(ShiftAssignment.employee_badge_number == "Q1005")
            .count()
            == 1
        )
        assert (
            test_db.query(ShiftAssignment)
            .filter(ShiftAssignment.employee_badge_number == "2007")
            .count()
            == 0
        )
        assert (
            test_db.query(EmployeeLeave)
            .filter(EmployeeLeave.employee_badge_number == "Q1005")
            .count()
            == 1
        )
