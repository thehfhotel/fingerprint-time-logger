"""Q-badge generation for self-service employee onboarding (2026-07).

Self-onboarded employees never had a ZK device badge assigned, so they get
a synthetic badge in the "Q1001", "Q1002", ... series (the business key
used everywhere else — see app.models.models.Employee.badge_number).
"""
import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import Employee

logger = logging.getLogger(__name__)

# First Q-badge issued when no Q-badge exists yet.
_Q_BADGE_START = 1001
_Q_BADGE_PREFIX = "Q"


def generate_next_q_badge(db: Session) -> str:
    """Return the next unused Q-badge: max existing Q-number + 1, or Q1001
    if none exist yet.

    Only reads — does not reserve the badge. Callers that need
    uniqueness under concurrent writers should retry on IntegrityError
    (see create_self_onboarded_employee).
    """
    existing_q_badges = (
        db.query(Employee.badge_number)
        .filter(Employee.badge_number.like(f"{_Q_BADGE_PREFIX}%"))
        .all()
    )

    highest_number = _Q_BADGE_START - 1
    for (badge_number,) in existing_q_badges:
        suffix = badge_number[len(_Q_BADGE_PREFIX):]
        if suffix.isdigit():
            highest_number = max(highest_number, int(suffix))

    return f"{_Q_BADGE_PREFIX}{highest_number + 1}"


def create_self_onboarded_employee(
    db: Session,
    *,
    thai_name: str,
    english_name: Optional[str],
    nickname: str,
    location: str,
    department: Optional[str],
    position: Optional[str],
    line_user_id: str,
    line_display_name: Optional[str],
    line_picture_url: Optional[str],
    max_attempts: int = 5,
) -> Employee:
    """Create a pending, inactive, self-onboarded Employee row with a fresh
    Q-badge. Retries with a freshly generated badge on a uniqueness
    collision (concurrent onboarding submissions racing for the same
    next-Q-number).
    """
    last_error: Optional[Exception] = None

    for _ in range(max_attempts):
        badge_number = generate_next_q_badge(db)

        employee = Employee(
            badge_number=badge_number,
            thai_name=thai_name,
            english_name=english_name,
            display_name=nickname,
            department=department,
            position=position,
            location=location,
            is_active=False,
            is_hidden=False,
            pending_approval=True,
            join_source="self_onboard",
            line_user_id=line_user_id,
            line_display_name=line_display_name,
            line_picture_url=line_picture_url,
        )
        db.add(employee)

        try:
            db.commit()
            db.refresh(employee)
            return employee
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
            logger.warning(
                "Q-badge collision generating %s, retrying: %s", badge_number, exc
            )
            continue

    logger.error("Failed to allocate a unique Q-badge after %d attempts: %s", max_attempts, last_error)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="ไม่สามารถออกรหัสพนักงานใหม่ได้ กรุณาลองอีกครั้ง",
    )
