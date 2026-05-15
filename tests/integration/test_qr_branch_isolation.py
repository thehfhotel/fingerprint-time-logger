"""
Integration tests for per-branch QR isolation and check-in/check-out punch_type.

Regression coverage for the two-branch leak we hit on the kiosk feed: a
QR check-in at HF Ville showed up on the HF kiosk because the WebSocket
filter on the client OR'd a metadata substring. The leak is fixed in
qr-terminal.js; this file pins down the *server-side* contracts that the
client now depends on:

  1. /api/public/qr-checkin/recent/{terminal_id} only returns records
     whose device_id matches that terminal — never cross-branch.
  2. /api/public/qr-checkin/scan respects the new punch_type field
     (0 = check-in, 1 = check-out) and tags validation_message
     accordingly. Default-0 keeps backward compatibility with older
     clients that don't send punch_type.
  3. attendance_service.get_attendance_records() honours a device_id
     filter (the building block the /recent endpoint relies on).
"""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main_unified import app
from app.core.database import Base, get_db
from app.models.models import Device, Employee, AttendanceRecord
from app.services.qr_service import qr_service
from app.services.line_auth_service import line_auth_service
from app.services.attendance_service import attendance_service


# --- shared in-memory DB + test client ------------------------------------

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def test_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def _service_get_db():
    """get_db override that yields a *fresh* session per call.

    attendance_service.get_attendance_records() calls db.close() on
    whatever it receives. If we yielded the test's shared `test_db`,
    that close would detach every model instance the test holds. By
    handing out a new session bound to the same in-memory engine, the
    service can close its copy without disturbing the fixtures.
    """
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        pass


@pytest.fixture
def client(test_db):
    app.dependency_overrides[get_db] = _service_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_terminal(db, *, id_, name, location_name, lat, lon, radius=200,
                   linked_fingerprint_device_ids=None):
    """Helper: insert a QR-terminal Device with GPS metadata.

    Pass ``linked_fingerprint_device_ids=[1]`` to model the HF kiosk that's
    co-located with the ZK fingerprint scanner (so the kiosk feed unions
    QR scans + fingerprint scans for the same branch).
    """
    metadata = {
        "gps": {
            "latitude": lat,
            "longitude": lon,
            "radius": radius,
            "location_name": location_name,
        }
    }
    if linked_fingerprint_device_ids is not None:
        metadata["linked_fingerprint_device_ids"] = linked_fingerprint_device_ids

    terminal = Device(
        id=id_,
        name=name,
        ip_address=f"192.168.1.{id_}",
        device_type="qr_terminal",
        device_metadata=json.dumps(metadata),
        is_active=True,
    )
    db.add(terminal)
    db.commit()
    db.refresh(terminal)
    return terminal


def _make_fingerprint_device(db, *, id_, name="ZK Fingerprint"):
    fp = Device(
        id=id_,
        name=name,
        ip_address="192.168.100.209",
        device_type="fingerprint",
        is_active=True,
    )
    db.add(fp)
    db.commit()
    db.refresh(fp)
    return fp


def _make_employee(db, *, badge, line_user_id, display_name="พนักงาน"):
    emp = Employee(
        badge_number=badge,
        display_name=display_name,
        is_active=True,
        line_user_id=line_user_id,
        line_display_name=display_name,
        line_linking_code=None,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _seed_record(db, *, badge, device_id, ts, punch_type=0, msg="QR Check-in at X"):
    rec = AttendanceRecord(
        employee_badge_number=badge,
        timestamp=ts,
        device_id=device_id,
        punch_type=punch_type,
        sync_status="synced",
        validation_message=msg,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


# --- unit-ish: attendance_service.device_id filter ------------------------

class TestAttendanceServiceDeviceFilter:
    """get_attendance_records(device_id=...) must scope to one device."""

    def test_device_id_filter_returns_only_matching_device(self, test_db, monkeypatch):
        # attendance_service.get_attendance_records calls db.close() on
        # the yielded session. Hand it a fresh one per call so closing
        # it doesn't detach the instances test_db is holding.
        monkeypatch.setattr(
            "app.services.attendance_service.get_db", _service_get_db
        )

        hf = _make_terminal(test_db, id_=2, name="HF", location_name="HF",
                            lat=13.7563, lon=100.5018)
        ville = _make_terminal(test_db, id_=3, name="HF Ville", location_name="HF Ville",
                               lat=13.7600, lon=100.5100)
        _make_employee(test_db, badge="EMP001", line_user_id="U_hf")
        _make_employee(test_db, badge="EMP002", line_user_id="U_ville")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        _seed_record(test_db, badge="EMP001", device_id=hf.id, ts=now,
                     msg="QR Check-in at HF")
        _seed_record(test_db, badge="EMP002", device_id=ville.id, ts=now,
                     msg="QR Check-in at HF Ville")

        # Snapshot ids before crossing the service boundary — once the
        # service has run, our locally-attached instances would still
        # need a session refresh otherwise.
        hf_id, ville_id = hf.id, ville.id

        hf_only = attendance_service.get_attendance_records(device_id=hf_id)
        ville_only = attendance_service.get_attendance_records(device_id=ville_id)

        assert {r.device_id for r in hf_only} == {hf_id}
        assert {r.device_id for r in ville_only} == {ville_id}
        # Sanity: both records exist when unfiltered.
        all_records = attendance_service.get_attendance_records()
        assert {r.device_id for r in all_records} == {hf_id, ville_id}


# --- /recent/{terminal_id} endpoint: branch isolation contract -----------

class TestRecentEndpointBranchIsolation:
    """The /recent endpoint is what the kiosk uses to backfill from the
    DB on load. It must never return another branch's records, otherwise
    the leak we just fixed on the WebSocket side re-appears via backfill.
    """

    def _seed_two_branches(self, test_db, monkeypatch):
        # See _service_get_db — needed so the service-side close() doesn't
        # detach the records we want to look at afterwards.
        monkeypatch.setattr(
            "app.services.attendance_service.get_db", _service_get_db
        )

        hf = _make_terminal(test_db, id_=2, name="HF", location_name="HF",
                            lat=13.7563, lon=100.5018)
        ville = _make_terminal(test_db, id_=3, name="HF Ville", location_name="HF Ville",
                               lat=13.7600, lon=100.5100)
        _make_employee(test_db, badge="EMP001", line_user_id="U_hf",
                       display_name="Alice")
        _make_employee(test_db, badge="EMP002", line_user_id="U_ville",
                       display_name="Bob")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        _seed_record(test_db, badge="EMP001", device_id=hf.id, ts=now,
                     msg="QR Check-in at HF, GPS: 13.7563,100.5018, Distance: 5m")
        _seed_record(test_db, badge="EMP002", device_id=ville.id, ts=now,
                     msg="QR Check-in at HF Ville, GPS: 13.7600,100.5100, Distance: 5m")
        return hf.id, ville.id

    def test_recent_returns_only_this_terminal(self, client, test_db, monkeypatch):
        hf_id, ville_id = self._seed_two_branches(test_db, monkeypatch)

        r_hf = client.get(f"/api/public/qr-checkin/recent/{hf_id}")
        r_ville = client.get(f"/api/public/qr-checkin/recent/{ville_id}")

        assert r_hf.status_code == 200, r_hf.text
        assert r_ville.status_code == 200, r_ville.text

        hf_records = r_hf.json()["records"]
        ville_records = r_ville.json()["records"]

        # Strict device_id scoping — the whole point of this test.
        assert all(rec["device_id"] == hf_id for rec in hf_records)
        assert all(rec["device_id"] == ville_id for rec in ville_records)

        hf_badges = {rec["badge_number"] for rec in hf_records}
        ville_badges = {rec["badge_number"] for rec in ville_records}
        assert hf_badges == {"EMP001"}
        assert ville_badges == {"EMP002"}

    def test_recent_includes_employee_display_name(self, client, test_db, monkeypatch):
        hf_id, _ = self._seed_two_branches(test_db, monkeypatch)
        r = client.get(f"/api/public/qr-checkin/recent/{hf_id}")
        assert r.status_code == 200
        names = {rec["employee_name"] for rec in r.json()["records"]}
        assert "Alice" in names

    def test_recent_404_for_non_qr_terminal(self, client, test_db, monkeypatch):
        # A fingerprint device (not a qr_terminal) must be rejected — the
        # endpoint is only valid for kiosk devices.
        monkeypatch.setattr(
            "app.services.attendance_service.get_db", _service_get_db
        )
        fp = Device(
            id=99,
            name="Fingerprint",
            ip_address="192.168.1.99",
            device_type="fingerprint",
            is_active=True,
        )
        test_db.add(fp)
        test_db.commit()

        r = client.get("/api/public/qr-checkin/recent/99")
        assert r.status_code == 404


# --- /recent + /kiosk: linked fingerprint device pull-through ------------

class TestLinkedFingerprintDevices:
    """Each kiosk can pull in records from fingerprint scanners explicitly
    linked to it via terminal.device_metadata.linked_fingerprint_device_ids.

    Real-world setup: the physical ZK scanner lives at HF (main office),
    so its records should show on the HF kiosk feed; HF Ville stays
    QR-only. The link is opt-in per kiosk so HF Ville doesn't suddenly
    surface scans that happened at a different branch.
    """

    def _seed(self, test_db, monkeypatch, *, hf_links_zk=True, ville_links_zk=False):
        monkeypatch.setattr(
            "app.services.attendance_service.get_db", _service_get_db
        )

        zk = _make_fingerprint_device(test_db, id_=1)
        hf = _make_terminal(
            test_db, id_=2, name="HF", location_name="HF",
            lat=13.7563, lon=100.5018,
            linked_fingerprint_device_ids=[zk.id] if hf_links_zk else [],
        )
        ville = _make_terminal(
            test_db, id_=3, name="HF Ville", location_name="HF Ville",
            lat=13.7600, lon=100.5100,
            linked_fingerprint_device_ids=[zk.id] if ville_links_zk else [],
        )
        _make_employee(test_db, badge="EMP001", line_user_id="U_hf", display_name="Alice")
        _make_employee(test_db, badge="EMP002", line_user_id="U_ville", display_name="Bob")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # QR check-ins at each branch
        _seed_record(test_db, badge="EMP001", device_id=hf.id, ts=now,
                     msg="QR Check-in at HF, GPS: 13.7563,100.5018, Distance: 5m")
        _seed_record(test_db, badge="EMP002", device_id=ville.id, ts=now,
                     msg="QR Check-in at HF Ville, GPS: 13.7600,100.5100, Distance: 5m")
        # Fingerprint scan (no QR metadata tag, lives on the ZK device row)
        _seed_record(test_db, badge="EMP001", device_id=zk.id, ts=now, msg=None)
        return zk.id, hf.id, ville.id

    def test_hf_kiosk_recent_includes_linked_fingerprint_records(
        self, client, test_db, monkeypatch
    ):
        zk_id, hf_id, ville_id = self._seed(test_db, monkeypatch)

        r = client.get(f"/api/public/qr-checkin/recent/{hf_id}")
        assert r.status_code == 200, r.text
        device_ids = {rec["device_id"] for rec in r.json()["records"]}
        # HF's QR + the linked fingerprint device; no HF Ville leakage.
        assert hf_id in device_ids
        assert zk_id in device_ids
        assert ville_id not in device_ids

    def test_unlinked_kiosk_excludes_fingerprint(
        self, client, test_db, monkeypatch
    ):
        zk_id, _hf_id, ville_id = self._seed(test_db, monkeypatch)

        r = client.get(f"/api/public/qr-checkin/recent/{ville_id}")
        assert r.status_code == 200, r.text
        device_ids = {rec["device_id"] for rec in r.json()["records"]}
        # HF Ville never opted in, so no fingerprint records reach it.
        assert ville_id in device_ids
        assert zk_id not in device_ids

    def test_kiosk_response_surfaces_linked_ids(
        self, client, test_db, monkeypatch
    ):
        """The list is also exposed via /kiosk/{id} so the JS WebSocket
        filter can mirror the backend's union — see qr-terminal.js
        handleAttendanceUpdate() / allowedDeviceIds.
        """
        zk_id, hf_id, ville_id = self._seed(test_db, monkeypatch)

        hf_resp = client.get(f"/api/public/qr-checkin/kiosk/{hf_id}").json()
        assert hf_resp["linked_fingerprint_device_ids"] == [zk_id]

        ville_resp = client.get(f"/api/public/qr-checkin/kiosk/{ville_id}").json()
        assert ville_resp["linked_fingerprint_device_ids"] == []


# --- /scan endpoint: punch_type contract ---------------------------------

class TestScanPunchType:
    """The /scan endpoint must accept punch_type and tag records correctly.

    Default-omitted must remain check-in for backward compatibility with
    older mobile clients still in the wild (i.e. before this rollout).
    """

    @pytest.fixture
    def hf_terminal(self, test_db):
        return _make_terminal(
            test_db, id_=2, name="HF", location_name="HF",
            lat=13.7563, lon=100.5018,
        )

    @pytest.fixture
    def linked_emp(self, test_db):
        return _make_employee(test_db, badge="EMP001", line_user_id="U_hf")

    def _scan_payload(self, qr_token, jwt_token, *, punch_type=None):
        payload = {
            "qr_token": qr_token,
            "jwt_token": jwt_token,
            "latitude": 13.7565,
            "longitude": 100.5020,
            "accuracy": 10.0,
        }
        if punch_type is not None:
            payload["punch_type"] = punch_type
        return payload

    def test_scan_checkout_stores_punch_type_1_and_tags_metadata(
        self, client, test_db, hf_terminal, linked_emp
    ):
        qr_data = qr_service.generate_qr_code_for_terminal(hf_terminal.id)
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_emp.line_user_id,
            employee_badge=linked_emp.badge_number,
        )

        r = client.post(
            "/api/public/qr-checkin/scan",
            json=self._scan_payload(qr_data["token"], jwt_token, punch_type=1),
        )
        assert r.status_code == 200, r.text

        rec = test_db.query(AttendanceRecord).filter(
            AttendanceRecord.employee_badge_number == linked_emp.badge_number
        ).first()
        assert rec is not None
        assert rec.punch_type == 1
        assert "QR Check-out" in rec.validation_message
        # Must not be mis-tagged as a check-in:
        assert "QR Check-in" not in rec.validation_message

    def test_scan_checkin_default_when_omitted(
        self, client, test_db, hf_terminal, linked_emp
    ):
        # Older mobile clients won't send punch_type — they must still
        # produce a check-in record (backward compatible).
        qr_data = qr_service.generate_qr_code_for_terminal(hf_terminal.id)
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_emp.line_user_id,
            employee_badge=linked_emp.badge_number,
        )

        r = client.post(
            "/api/public/qr-checkin/scan",
            json=self._scan_payload(qr_data["token"], jwt_token),  # no punch_type
        )
        assert r.status_code == 200, r.text

        rec = test_db.query(AttendanceRecord).filter(
            AttendanceRecord.employee_badge_number == linked_emp.badge_number
        ).first()
        assert rec is not None
        assert rec.punch_type == 0
        assert "QR Check-in" in rec.validation_message

    def test_scan_rejects_invalid_punch_type(
        self, client, test_db, hf_terminal, linked_emp
    ):
        qr_data = qr_service.generate_qr_code_for_terminal(hf_terminal.id)
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_emp.line_user_id,
            employee_badge=linked_emp.badge_number,
        )
        r = client.post(
            "/api/public/qr-checkin/scan",
            json=self._scan_payload(qr_data["token"], jwt_token, punch_type=7),
        )
        # FastAPI/pydantic validation error → 422
        assert r.status_code == 422

    def test_scan_invalidates_attendance_summary_cache(
        self, client, test_db, hf_terminal, linked_emp
    ):
        """The dashboard's /attendance/summary endpoint serves from a
        5-minute cache keyed on 'attendance_summary'. Without explicit
        invalidation, a QR scan only surfaces on the dashboard after the
        background scheduler refreshes the cache — which is the latency
        the user reported. Pin the invalidation here so it can't regress.
        """
        from app.services.device_cache_service import device_cache_service

        # Pre-populate the cache with a sentinel value so we can detect
        # whether /scan actually invalidates it. (Direct .set bypasses
        # the warmer so the test doesn't depend on real data.)
        device_cache_service.set("attendance_summary", {"sentinel": True})
        assert device_cache_service.get("attendance_summary") is not None

        qr_data = qr_service.generate_qr_code_for_terminal(hf_terminal.id)
        jwt_token = line_auth_service.create_jwt_token(
            line_user_id=linked_emp.line_user_id,
            employee_badge=linked_emp.badge_number,
        )
        r = client.post(
            "/api/public/qr-checkin/scan",
            json=self._scan_payload(qr_data["token"], jwt_token),
        )
        assert r.status_code == 200, r.text
        assert device_cache_service.get("attendance_summary") is None
