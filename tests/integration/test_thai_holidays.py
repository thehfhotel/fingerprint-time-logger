"""
Integration tests for the public-holiday config endpoints:
  - GET /api/private/leaves/holidays/thailand/{year}  (Thai preset list)
  - GET/POST/DELETE /api/private/leaves/holidays       (company-wide CRUD)
"""
from datetime import date as date_type

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main_unified import app


@pytest.fixture
def client():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool, echo=False,
    )
    Base.metadata.create_all(bind=eng)
    SessionLocal = sessionmaker(bind=eng)

    def override():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    c = TestClient(app)
    try:
        yield c
    finally:
        app.dependency_overrides.clear()
        eng.dispose()


class TestThaiPreset:
    def test_2026_is_curated(self, client):
        r = client.get("/api/private/leaves/holidays/thailand/2026")
        assert r.status_code == 200
        data = r.json()
        dates = {h["date"] for h in data}
        # spot-check fixed + curated lunar/observed dates
        assert "2026-01-01" in dates           # New Year
        assert "2026-04-13" in dates           # Songkran
        assert "2026-05-31" in dates           # Visakha Bucha (curated)
        assert "2026-10-23" in dates           # Chulalongkorn
        # sorted ascending
        assert [h["date"] for h in data] == sorted(h["date"] for h in data)
        assert all(h["name"] for h in data)

    def test_other_year_fixed_fallback(self, client):
        data = client.get("/api/private/leaves/holidays/thailand/2027").json()
        dates = {h["date"] for h in data}
        assert "2027-01-01" in dates
        assert "2027-12-31" in dates
        # lunar Buddhist days are NOT in the fixed fallback
        assert not any(h["name"] == "วันมาฆบูชา" for h in data)

    def test_bad_year(self, client):
        assert client.get("/api/private/leaves/holidays/thailand/1500").status_code == 400


class TestHolidayCrud:
    def test_roundtrip(self, client):
        # add two
        assert client.post("/api/private/leaves/holidays",
                           json={"date": "2026-01-01", "name": "วันขึ้นปีใหม่"}).status_code == 200
        assert client.post("/api/private/leaves/holidays",
                           json={"date": "2026-12-31", "name": "วันสิ้นปี"}).status_code == 200
        # list the year
        rows = client.get("/api/private/leaves/holidays",
                          params={"from": "2026-01-01", "to": "2026-12-31"}).json()
        assert [h["date"] for h in rows] == ["2026-01-01", "2026-12-31"]
        # upsert updates the name
        client.post("/api/private/leaves/holidays",
                    json={"date": "2026-01-01", "name": "ปีใหม่"})
        rows = client.get("/api/private/leaves/holidays",
                          params={"from": "2026-01-01", "to": "2026-12-31"}).json()
        assert next(h for h in rows if h["date"] == "2026-01-01")["name"] == "ปีใหม่"
        # delete one
        assert client.delete("/api/private/leaves/holidays/2026-01-01").status_code == 204
        rows = client.get("/api/private/leaves/holidays",
                          params={"from": "2026-01-01", "to": "2026-12-31"}).json()
        assert [h["date"] for h in rows] == ["2026-12-31"]
