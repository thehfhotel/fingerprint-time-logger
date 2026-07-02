"""Public self-service employee onboarding API (2026-07).

Endpoints for the LINE-authenticated onboarding form at
/qr-checkin/onboard (see app.api.line_auth for the shared LINE OAuth flow
this reuses). No admin auth here — these are public, LINE-JWT-gated
endpoints, rate-limited like /api/public/auth/line/link-account.

Employees are LINE-only by policy: this module never collects or stores
an email/password for the employee themselves.
"""
import logging
import os
import threading
import time
from typing import Dict, List, Optional

import requests
from fastapi import APIRouter, Header, HTTPException, Request, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee
from app.services.badge_service import create_self_onboarded_employee
from app.services.line_auth_service import line_auth_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Branches this deployment operates. Mirrors
# app.api.consolidated_employees._ALLOWED_LOCATIONS — kept as a separate
# constant here (not imported) so this public-facing module has no
# dependency on the admin employees router's internals.
_ALLOWED_LOCATIONS = ("HF", "HF_VILLE")


# ============================================================================
# Submission rate limiting (mirrors line_auth.py's link-account brute-force
# protection: per-(IP, LINE user) sliding window, no persistent lockout —
# a single stray retry storm shouldn't lock a real employee out of ever
# onboarding, just slow down abuse).
# ============================================================================

_SUBMIT_ATTEMPT_WINDOW_SECONDS = 60
_SUBMIT_ATTEMPT_MAX_PER_WINDOW = 5
_SUBMIT_ATTEMPT_RETENTION_SECONDS = 300

_submit_attempts: Dict[str, List[float]] = {}
_submit_attempts_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """Resolve the client IP when behind a trusted proxy (same trust order
    as line_auth.py._client_ip)."""
    if os.getenv("BEHIND_PROXY", "false").lower() == "true":
        cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
        if cf_ip:
            return cf_ip
        forwarded = request.headers.get("X-Forwarded-For", "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_submit_rate_limit(ip: str, line_user_id: str) -> None:
    """Raise HTTP 429 if this (ip, line_user_id) pair has submitted too
    many onboarding requests in the last minute."""
    key = f"{ip}:{line_user_id}"
    now = time.time()

    with _submit_attempts_lock:
        cutoff = now - _SUBMIT_ATTEMPT_RETENTION_SECONDS
        timestamps = [t for t in _submit_attempts.get(key, []) if t > cutoff]

        window_cutoff = now - _SUBMIT_ATTEMPT_WINDOW_SECONDS
        in_window = [t for t in timestamps if t > window_cutoff]
        if len(in_window) >= _SUBMIT_ATTEMPT_MAX_PER_WINDOW:
            retry_after = int(_SUBMIT_ATTEMPT_WINDOW_SECONDS - (now - in_window[0])) + 1
            _submit_attempts[key] = timestamps
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="ส่งคำขอสมัครบ่อยเกินไป กรุณาลองใหม่ภายหลัง",
                headers={"Retry-After": str(max(1, retry_after))},
            )

        timestamps.append(now)
        _submit_attempts[key] = timestamps


def _bearer_token(authorization: Optional[str]) -> str:
    """Extract a bearer token from an Authorization header, or 401."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
        )
    return parts[1].strip()


# ============================================================================
# Slack notification
# ============================================================================

def _notify_onboarding_submitted(employee: Employee) -> None:
    """Best-effort Slack ping when a new self-onboarding is pending admin
    review. Never raises — a failed notification must not fail the
    employee's submission.
    """
    webhook_url = os.getenv("ONBOARDING_SLACK_WEBHOOK_URL") or os.getenv("ZK_SYNC_SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("[public_onboarding] no Slack webhook configured; skipping notification")
        return

    text = (
        f"🆕 พนักงานใหม่รออนุมัติ: {employee.display_name} ({employee.thai_name}) — "
        f"{employee.location} — "
        f"อนุมัติที่ https://erp.thehfhotel.org/fingerprintlogs/employee-management"
    )
    try:
        response = requests.post(webhook_url, json={"text": text}, timeout=10)
        if response.status_code != 200:
            logger.warning(
                "[public_onboarding] Slack webhook returned HTTP %s: %s",
                response.status_code, response.text[:200],
            )
    except Exception as exc:
        logger.warning("[public_onboarding] Slack notification failed: %s", exc)


# ============================================================================
# Request/response models
# ============================================================================

class OnboardingSubmitRequest(BaseModel):
    jwt_token: str
    thai_name: str = Field(..., min_length=1, max_length=100)
    english_name: Optional[str] = None
    nickname: str = Field(..., min_length=1, max_length=100)
    location: str
    department: Optional[str] = None
    position: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/submit")
async def submit_onboarding(
    body: OnboardingSubmitRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    """Submit a new self-service onboarding request.

    Creates a pending, inactive Employee row with a fresh Q-badge and the
    submitter's LINE identity already linked (they authenticated via LINE
    to reach this form — no 6-digit admin code needed). An admin approves
    or rejects it from the employee-management page.
    """
    token_payload = line_auth_service.verify_jwt_token(body.jwt_token)
    line_user_id = token_payload.get("line_user_id")
    if not line_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing LINE user ID",
        )

    client_ip = _client_ip(http_request)
    _enforce_submit_rate_limit(client_ip, line_user_id)

    location = (body.location or "").strip()
    if location not in _ALLOWED_LOCATIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"location must be one of {_ALLOWED_LOCATIONS}",
        )

    thai_name = body.thai_name.strip()
    nickname = body.nickname.strip()
    if not thai_name:
        raise HTTPException(status_code=400, detail="กรุณาระบุชื่อจริงภาษาไทย")
    if not nickname:
        raise HTTPException(status_code=400, detail="กรุณาระบุชื่อเล่น")

    # One pending (or already-linked) submission per LINE account.
    existing = db.query(Employee).filter(Employee.line_user_id == line_user_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="บัญชี LINE นี้มีข้อมูลพนักงานอยู่แล้ว",
        )

    employee = create_self_onboarded_employee(
        db,
        thai_name=thai_name,
        english_name=(body.english_name or "").strip() or None,
        nickname=nickname,
        location=location,
        department=(body.department or "").strip() or None,
        position=(body.position or "").strip() or None,
        line_user_id=line_user_id,
        line_display_name=token_payload.get("display_name"),
        line_picture_url=token_payload.get("picture_url"),
    )

    _notify_onboarding_submitted(employee)

    return {
        "success": True,
        "message": "ส่งข้อมูลสมัครสำเร็จ กรุณารอผู้ดูแลระบบอนุมัติ",
        "badge_number": employee.badge_number,
        "status": "pending",
    }


@router.get("/status")
async def get_onboarding_status(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Onboarding status for the caller's LINE identity.

    Returns one of:
      - none:     no employee row for this LINE user — show the form
      - pending:  self-onboarded, awaiting admin review — waiting screen
      - approved: admin approved — link to /qr-checkin/mobile
      - rejected: admin rejected but kept the record (had attendance
                  history) — inactive, not pending, self-onboarded

    Always includes the caller's LINE display name/picture (from the JWT,
    no DB lookup needed) so the client can prefill the form.
    """
    token = _bearer_token(authorization)
    token_payload = line_auth_service.verify_jwt_token(token)
    line_user_id = token_payload.get("line_user_id")
    if not line_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing LINE user ID",
        )

    line_profile = {
        "line_display_name": token_payload.get("display_name"),
        "line_picture_url": token_payload.get("picture_url"),
    }

    employee = db.query(Employee).filter(Employee.line_user_id == line_user_id).first()
    if not employee:
        return {"status": "none", **line_profile}

    if employee.pending_approval:
        return {
            "status": "pending",
            "badge_number": employee.badge_number,
            "nickname": employee.display_name,
            "location": employee.location,
            **line_profile,
        }

    if employee.is_active:
        return {
            "status": "approved",
            "badge_number": employee.badge_number,
            **line_profile,
        }

    if employee.join_source == "self_onboard":
        return {"status": "rejected", **line_profile}

    # Linked-but-inactive for a reason unrelated to self-onboarding
    # (e.g. an admin deactivated a long-standing device employee who also
    # happens to have LINE linked). Not this page's concern.
    return {"status": "none", **line_profile}
