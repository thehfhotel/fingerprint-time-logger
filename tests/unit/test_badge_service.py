"""Unit tests for Q-badge generation (app.services.badge_service),
covering the self-service employee onboarding feature (2026-07).
"""
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.models import Employee
from app.services.badge_service import create_self_onboarded_employee, generate_next_q_badge


class TestGenerateNextQBadge:
    def test_empty_db_returns_q1001(self, test_db):
        assert generate_next_q_badge(test_db) == "Q1001"

    def test_ignores_non_q_badges(self, test_db):
        test_db.add(Employee(badge_number="0001", display_name="A"))
        test_db.commit()

        assert generate_next_q_badge(test_db) == "Q1001"

    def test_existing_q_badges_returns_max_plus_one(self, test_db):
        test_db.add(Employee(badge_number="Q1001", display_name="A"))
        test_db.add(Employee(badge_number="Q1005", display_name="B"))
        test_db.commit()

        assert generate_next_q_badge(test_db) == "Q1006"

    def test_ignores_malformed_q_suffix(self, test_db):
        test_db.add(Employee(badge_number="QABC", display_name="A"))
        test_db.commit()

        assert generate_next_q_badge(test_db) == "Q1001"


class TestCreateSelfOnboardedEmployee:
    def _kwargs(self, **overrides):
        base = dict(
            thai_name="สมชาย ใจดี",
            english_name=None,
            nickname="ชาย",
            location="HF",
            department=None,
            position=None,
            line_user_id="line-user-1",
            line_display_name="Somchai",
            line_picture_url=None,
        )
        base.update(overrides)
        return base

    def test_creates_pending_inactive_employee_with_q_badge(self, test_db):
        employee = create_self_onboarded_employee(test_db, **self._kwargs())

        assert employee.badge_number == "Q1001"
        assert employee.pending_approval is True
        assert employee.is_active is False
        assert employee.join_source == "self_onboard"
        assert employee.display_name == "ชาย"
        assert employee.line_user_id == "line-user-1"

    def test_uniqueness_retry_safety(self, test_db, monkeypatch):
        """A commit collision on the first attempt is retried with a fresh badge."""
        original_commit = test_db.commit
        call_count = {"n": 0}

        def flaky_commit():
            call_count["n"] += 1
            if call_count["n"] == 1:
                test_db.rollback()
                raise IntegrityError("stmt", {}, Exception("UNIQUE constraint failed"))
            return original_commit()

        monkeypatch.setattr(test_db, "commit", flaky_commit)

        employee = create_self_onboarded_employee(test_db, **self._kwargs())

        assert employee.badge_number == "Q1001"
        assert call_count["n"] == 2

    def test_raises_500_after_max_attempts_exhausted(self, test_db, monkeypatch):
        def always_fail():
            test_db.rollback()
            raise IntegrityError("stmt", {}, Exception("UNIQUE constraint failed"))

        monkeypatch.setattr(test_db, "commit", always_fail)

        with pytest.raises(HTTPException) as exc_info:
            create_self_onboarded_employee(test_db, max_attempts=3, **self._kwargs())

        assert exc_info.value.status_code == 500
