"""Unit tests for the card-reader identity resolution API (app.api.reader):
the server-to-server NFC-card-UID -> employee lookup the new-hotel PMS calls,
guarded by the ``X-Reader-Secret`` shared secret.
"""
from app.models.models import Employee, EmployeeAppGrant

SECRET = "testsecret"


def _make_employee(test_db, badge, **overrides):
    defaults = dict(
        badge_number=badge, display_name=f"emp-{badge}", is_active=True, is_hidden=False
    )
    defaults.update(overrides)
    employee = Employee(**defaults)
    test_db.add(employee)
    test_db.commit()
    test_db.refresh(employee)
    return employee


def _headers(secret=SECRET):
    return {"X-Reader-Secret": secret}


class TestReaderResolveAuth:
    def test_dark_returns_404_when_secret_unset(self, test_client, test_db, monkeypatch):
        # No READER_RESOLVE_SECRET in the environment -> the surface is dark.
        monkeypatch.delenv("READER_RESOLVE_SECRET", raising=False)
        _make_employee(test_db, "1001", nfc_card_uid="AABBCCDD")

        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "AABBCCDD"},
            headers=_headers(),
        )
        assert response.status_code == 404

    def test_missing_header_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "AABBCCDD"},
        )
        assert response.status_code == 401

    def test_wrong_secret_returns_401(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "AABBCCDD"},
            headers=_headers("not-the-secret"),
        )
        assert response.status_code == 401


class TestReaderResolve:
    def test_found_returns_identity_and_apps(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(test_db, "1001", display_name="สมชาย", nfc_card_uid="AABBCCDD")
        test_db.add(EmployeeAppGrant(employee_badge_number="1001", app_id="rooms"))
        test_db.add(EmployeeAppGrant(employee_badge_number="1001", app_id="portal"))
        test_db.commit()

        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "AABBCCDD"},
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json() == {
            "found": True,
            "badge": "1001",
            "display_name": "สมชาย",
            "apps": ["portal", "rooms"],  # ordered by app_id
            "active": True,
            "pending": False,
        }

    def test_unknown_uid_returns_found_false(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "NOSUCHUID"},
            headers=_headers(),
        )
        assert response.status_code == 200
        assert response.json() == {
            "found": False,
            "badge": None,
            "display_name": None,
            "apps": [],
            "active": False,
            "pending": False,
        }

    def test_case_insensitive_match(self, test_client, test_db, monkeypatch):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        # Stored lowercase (mixed-case legacy data); the reader sends uppercase.
        _make_employee(test_db, "1002", nfc_card_uid="deadbeef")

        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "DEADBEEF"},
            headers=_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["badge"] == "1002"

    def test_inactive_pending_employee_still_found_with_flags(
        self, test_client, test_db, monkeypatch
    ):
        monkeypatch.setenv("READER_RESOLVE_SECRET", SECRET)
        _make_employee(
            test_db,
            "1003",
            nfc_card_uid="CAFEBABE",
            is_active=False,
            pending_approval=True,
        )

        response = test_client.post(
            "/api/private/reader/resolve",
            json={"uid": "CAFEBABE"},
            headers=_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["found"] is True
        assert data["badge"] == "1003"
        assert data["active"] is False
        assert data["pending"] is True
