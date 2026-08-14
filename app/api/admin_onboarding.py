"""Admin approval API for self-service employee onboarding (2026-07).

Mounted under /api/private/admin/onboarding/* — protected by
require_admin_auth (Cloudflare Access or the admin passcode session),
same posture as admin_line_codes.py.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.admin_auth import require_admin_auth
from app.core.database import get_db
from app.models.models import AttendanceRecord, Employee, EmployeeAppGrant
from app.services.admin_identity import admin_actor_label
from app.services.app_catalog import DEFAULT_GRANTED_APP_IDS
from app.services.staff_oa_provision import provision_for_badge

router = APIRouter()


class ApproveOnboardingRequest(BaseModel):
    badge_number: str


class RejectOnboardingRequest(BaseModel):
    badge_number: str


class PendingOnboardingResponse(BaseModel):
    badge_number: str
    thai_name: Optional[str]
    english_name: Optional[str]
    nickname: str
    location: Optional[str]
    department: Optional[str]
    position: Optional[str]
    line_display_name: Optional[str]
    line_picture_url: Optional[str]
    submitted_at: Optional[datetime]


def _require_pending_employee(db: Session, badge_number: str) -> Employee:
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail=f"ไม่พบพนักงาน badge number: {badge_number}")
    if not employee.pending_approval:
        raise HTTPException(status_code=400, detail="พนักงานรายนี้ไม่ได้อยู่ระหว่างรออนุมัติ")
    return employee


@router.get("/pending", response_model=List[PendingOnboardingResponse])
async def list_pending_onboardings(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth),
):
    """List self-onboarded employees awaiting admin review, oldest first."""
    employees = (
        db.query(Employee)
        .filter(Employee.pending_approval == True)  # noqa: E712
        .order_by(Employee.created_at.asc())
        .all()
    )
    return [
        PendingOnboardingResponse(
            badge_number=e.badge_number,
            thai_name=e.thai_name,
            english_name=e.english_name,
            nickname=e.display_name,
            location=e.location,
            department=e.department,
            position=e.position,
            line_display_name=e.line_display_name,
            line_picture_url=e.line_picture_url,
            submitted_at=e.created_at,
        )
        for e in employees
    ]


@router.post("/approve")
async def approve_onboarding(
    request: ApproveOnboardingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    identity: str = Depends(require_admin_auth),
):
    """Approve a pending onboarding: activate the employee, auto-fill their
    synthetic email if unset, and grant the default app set."""
    employee = _require_pending_employee(db, request.badge_number)

    employee.is_active = True
    employee.pending_approval = False
    if not employee.email:
        employee.email = f"{employee.badge_number.lower()}@emp.thehfhotel.org"
    employee.updated_at = datetime.now(timezone.utc)

    granted_by = admin_actor_label(identity)
    existing_grants = {
        g.app_id
        for g in db.query(EmployeeAppGrant)
        .filter(EmployeeAppGrant.employee_badge_number == employee.badge_number)
        .all()
    }
    for app_id in DEFAULT_GRANTED_APP_IDS:
        if app_id not in existing_grants:
            db.add(EmployeeAppGrant(
                employee_badge_number=employee.badge_number,
                app_id=app_id,
                granted_by=granted_by,
            ))

    db.commit()
    db.refresh(employee)

    # A self-onboarded row already carries the submitter's line_user_id (they
    # authenticated with LINE to reach the form), but it was is_active=False
    # until this moment — so every provisioning attempt before now returned
    # early on the inactive check. Approval is when the LINE link becomes
    # effective, which makes it the third trigger site alongside the grants
    # endpoint and the 6-digit link-account flow. Background + never-raises,
    # same posture: the approval is committed and must not depend on LINE.
    background_tasks.add_task(provision_for_badge, employee.badge_number)

    return {
        "success": True,
        "message": f"อนุมัติพนักงาน {employee.display_name} สำเร็จ",
        "badge_number": employee.badge_number,
        "email": employee.email,
        "granted_app_ids": list(DEFAULT_GRANTED_APP_IDS),
    }


@router.post("/reject")
async def reject_onboarding(
    request: RejectOnboardingRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth),
):
    """Reject a pending onboarding.

    Hard-deletes the employee row when it has zero attendance history
    (the common case — they never punched in before approval). If it
    somehow already has attendance records, deactivate instead of
    deleting so that history stays intact.
    """
    employee = _require_pending_employee(db, request.badge_number)

    has_attendance = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.employee_badge_number == employee.badge_number)
        .first()
        is not None
    )

    badge_number = employee.badge_number
    display_name = employee.display_name

    if has_attendance:
        employee.is_active = False
        employee.pending_approval = False
        employee.updated_at = datetime.now(timezone.utc)
        db.commit()
        action = "deactivated"
    else:
        db.delete(employee)
        db.commit()
        action = "deleted"

    return {
        "success": True,
        "message": f"ปฏิเสธการสมัครของ {display_name} สำเร็จ",
        "badge_number": badge_number,
        "action": action,
    }
