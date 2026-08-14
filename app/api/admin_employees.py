"""Admin employee registry API (2026-07): app grants, NFC card slot, and
the device-badge/Q-badge merge tool.

Mounted under /api/private/admin/employees/* — protected by
require_admin_auth (Cloudflare Access or the admin passcode session),
same posture as admin_line_codes.py.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.admin_auth import require_admin_auth
from app.core.database import get_db
from app.models.models import (
    ApplicationLog,
    AttendanceRecord,
    Employee,
    EmployeeAppGrant,
    EmployeeLeave,
    EmployeeSchedule,
    ShiftAssignment,
)
from app.services.admin_identity import admin_actor_label
from app.services.app_catalog import APP_CATALOG
from app.services.staff_oa_provision import provision_for_badge

logger = logging.getLogger(__name__)

router = APIRouter()

_CATALOG_APP_IDS = {app_id for app_id, _ in APP_CATALOG}

# Child tables with no unique constraint tied to the badge — every row for
# from_badge simply moves to to_badge, no collision handling needed.
_SIMPLE_CHILD_TABLES = [
    (AttendanceRecord, "employee_badge_number", "attendance_records"),
    (ApplicationLog, "employee_badge", "application_logs"),
]

# Child tables with UNIQUE(badge, <key column>) — a from-row that would
# collide with an existing to-row is dropped (the to-row wins) instead of
# moved.
_UNIQUE_CHILD_TABLES = [
    (ShiftAssignment, "employee_badge_number", ("date",), "shift_assignments"),
    (EmployeeSchedule, "employee_badge_number", ("effective_from",), "employee_schedules"),
    (EmployeeLeave, "employee_badge_number", ("date",), "employee_leaves"),
    (EmployeeAppGrant, "employee_badge_number", ("app_id",), "employee_app_grants"),
]

# Employee fields copied from 'from' onto 'to' when the 'to' side is
# NULL/empty (Case B merge only — Case A is a pure rename, nothing to copy).
_COPYABLE_FIELDS_IF_TARGET_EMPTY = (
    "line_user_id", "line_display_name", "line_picture_url",
    "line_linking_code", "line_linking_code_generated_at",
    "email", "nfc_card_uid",
    "english_name", "thai_name",
    "role", "location", "department", "position",
)


# ============================================================================
# App grants
# ============================================================================

class GrantsUpdateRequest(BaseModel):
    app_ids: List[str]


@router.get("/{badge_number}/grants")
async def get_employee_grants(
    badge_number: str,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth),
):
    """Current app grants for one employee, plus the full app catalog so
    the admin UI can render checkboxes without a second round-trip."""
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    granted = (
        db.query(EmployeeAppGrant)
        .filter(EmployeeAppGrant.employee_badge_number == badge_number)
        .all()
    )
    return {
        "badge_number": badge_number,
        "granted_app_ids": [g.app_id for g in granted],
        "catalog": [{"app_id": app_id, "name": name} for app_id, name in APP_CATALOG],
    }


@router.put("/{badge_number}/grants")
async def update_employee_grants(
    badge_number: str,
    body: GrantsUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    identity: str = Depends(require_admin_auth),
):
    """Full-set replace: the employee ends up granted exactly the app_ids
    in the request body (existing grants not listed are revoked).

    Also (re)provisions the employee's Employee Hub Role Menu on the staff
    LINE OA in the background, so ticking "Housekeeping" here is all it
    takes for the maid to see the menu — no ``staff_oa_sync.py --apply``
    run on the host. See app/services/staff_oa_provision.py."""
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    requested_app_ids = set(body.app_ids or [])
    unknown_app_ids = requested_app_ids - _CATALOG_APP_IDS
    if unknown_app_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown app id(s): {', '.join(sorted(unknown_app_ids))}",
        )

    existing_grants = {
        g.app_id: g
        for g in db.query(EmployeeAppGrant)
        .filter(EmployeeAppGrant.employee_badge_number == badge_number)
        .all()
    }
    granted_by = admin_actor_label(identity)

    for app_id, grant in existing_grants.items():
        if app_id not in requested_app_ids:
            db.delete(grant)

    for app_id in requested_app_ids:
        if app_id not in existing_grants:
            db.add(EmployeeAppGrant(
                employee_badge_number=badge_number,
                app_id=app_id,
                granted_by=granted_by,
            ))

    db.commit()

    # The grant write is DONE and durable at this point. Everything below is
    # best-effort decoration on top of it.
    #
    # Scheduled as a FastAPI BackgroundTask, which means two things that both
    # matter here: it runs AFTER the response is sent (so the admin's save
    # stays fast even when LINE is slow — the LINE client's per-call timeout
    # alone is 15s), and because provision_for_badge is a SYNC function
    # FastAPI runs it in a threadpool, so the blocking requests/PIL work
    # never occupies the event loop. This repo was bitten by exactly that
    # today: blocking LINE calls made on the loop stalled /oidc/token for
    # every other caller. provision_for_badge additionally swallows all of
    # its own exceptions, so a LINE outage cannot turn this 200 into a 500 or
    # roll back the commit above.
    background_tasks.add_task(provision_for_badge, badge_number)

    granted = (
        db.query(EmployeeAppGrant)
        .filter(EmployeeAppGrant.employee_badge_number == badge_number)
        .all()
    )
    return {"badge_number": badge_number, "granted_app_ids": sorted(g.app_id for g in granted)}


# ============================================================================
# NFC card slot
# ============================================================================

class NfcCardRequest(BaseModel):
    uid: Optional[str] = None


@router.put("/{badge_number}/nfc-card")
async def set_employee_nfc_card(
    badge_number: str,
    body: NfcCardRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth),
):
    """Set or clear an employee's physical NFC card UID. uid=null clears it."""
    employee = db.query(Employee).filter(Employee.badge_number == badge_number).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    uid = (body.uid or "").strip() or None

    if uid is not None:
        collision = db.query(Employee).filter(
            Employee.nfc_card_uid == uid,
            Employee.badge_number != badge_number,
        ).first()
        if collision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"บัตร NFC นี้ถูกใช้งานโดยพนักงาน {collision.display_name} ({collision.badge_number}) แล้ว",
            )

    employee.nfc_card_uid = uid
    employee.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="บัตร NFC นี้ถูกใช้งานโดยพนักงานอื่นแล้ว",
        )
    db.refresh(employee)

    return {"badge_number": employee.badge_number, "nfc_card_uid": employee.nfc_card_uid}


# ============================================================================
# Merge tool (device badge <-> Q-badge consolidation)
# ============================================================================

class MergeEmployeesRequest(BaseModel):
    from_badge: str
    to_badge: str


def _move_all(db: Session, model, badge_column: str, from_badge: str, to_badge: str) -> dict:
    """Bulk-move every row referencing from_badge to to_badge. Safe for
    tables with no unique constraint tied to the badge."""
    moved = (
        db.query(model)
        .filter(getattr(model, badge_column) == from_badge)
        .update({badge_column: to_badge}, synchronize_session=False)
    )
    return {"moved": moved, "dropped_duplicate": 0}


def _move_or_drop_duplicates(
    db: Session, model, badge_column: str, unique_columns: tuple, from_badge: str, to_badge: str
) -> dict:
    """Move rows referencing from_badge to to_badge one at a time, dropping
    a from-row when a to-row already occupies the same unique key (the
    to-row — the surviving identity — wins)."""
    moved = 0
    dropped = 0
    from_rows = db.query(model).filter(getattr(model, badge_column) == from_badge).all()
    for row in from_rows:
        collision_filters = [getattr(model, badge_column) == to_badge]
        for column_name in unique_columns:
            collision_filters.append(getattr(model, column_name) == getattr(row, column_name))
        collision = db.query(model).filter(*collision_filters).first()
        if collision:
            db.delete(row)
            dropped += 1
        else:
            setattr(row, badge_column, to_badge)
            moved += 1
    return {"moved": moved, "dropped_duplicate": dropped}


@router.post("/merge")
async def merge_employees(
    request: MergeEmployeesRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth),
):
    """Merge one employee record into another, in one transaction.

    Case A (to_badge has no employees row): a clean rename — from_badge's
    row and every child table row are renamed to to_badge.

    Case B (to_badge already exists): child rows move from -> to, with a
    from-row dropped when it would collide with an existing to-row on a
    unique constraint (the to-row wins). Scalar identity fields copy from
    'from' onto 'to' only where 'to' is still NULL/empty. The 'from' row
    is then deleted.

    Refuses (409) when both rows have a LINE account linked and they
    differ — merging would silently orphan one employee's LINE identity.
    """
    from_badge = request.from_badge.strip()
    to_badge = request.to_badge.strip()

    if not from_badge or not to_badge:
        raise HTTPException(status_code=400, detail="from_badge and to_badge are required")
    if from_badge == to_badge:
        raise HTTPException(status_code=400, detail="from_badge and to_badge must differ")

    from_employee = db.query(Employee).filter(Employee.badge_number == from_badge).first()
    if not from_employee:
        raise HTTPException(status_code=404, detail=f"ไม่พบพนักงาน {from_badge}")

    to_employee = db.query(Employee).filter(Employee.badge_number == to_badge).first()

    if (
        to_employee
        and from_employee.line_user_id
        and to_employee.line_user_id
        and from_employee.line_user_id != to_employee.line_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="ไม่สามารถรวมได้: ทั้งสองรหัสเชื่อมต่อบัญชี LINE คนละบัญชีกัน",
        )

    is_rename = to_employee is None
    summary: dict = {}

    try:
        if is_rename:
            from_employee.badge_number = to_badge
            from_employee.updated_at = datetime.now(timezone.utc)
            db.flush()

            for model, badge_column, label in _SIMPLE_CHILD_TABLES:
                summary[label] = _move_all(db, model, badge_column, from_badge, to_badge)
            for model, badge_column, _unique_columns, label in _UNIQUE_CHILD_TABLES:
                summary[label] = _move_all(db, model, badge_column, from_badge, to_badge)
        else:
            for model, badge_column, label in _SIMPLE_CHILD_TABLES:
                summary[label] = _move_all(db, model, badge_column, from_badge, to_badge)
            for model, badge_column, unique_columns, label in _UNIQUE_CHILD_TABLES:
                summary[label] = _move_or_drop_duplicates(
                    db, model, badge_column, unique_columns, from_badge, to_badge
                )

            # Capture the fields to copy BEFORE deleting the 'from' row, then
            # delete and flush before setting them on 'to' — some of these
            # (email, nfc_card_uid, line_user_id, line_linking_code) are
            # UNIQUE columns, so writing the copied value onto 'to' while
            # 'from' still holds the same value would trip the constraint.
            fields_to_copy = {}
            for field_name in _COPYABLE_FIELDS_IF_TARGET_EMPTY:
                from_value = getattr(from_employee, field_name)
                to_value = getattr(to_employee, field_name)
                if from_value not in (None, "") and to_value in (None, ""):
                    fields_to_copy[field_name] = from_value

            db.delete(from_employee)
            db.flush()

            for field_name, value in fields_to_copy.items():
                setattr(to_employee, field_name, value)
            to_employee.updated_at = datetime.now(timezone.utc)

        db.add(ApplicationLog(
            level="INFO",
            category="employee",
            action="merge_employees",
            message=f"Merged employee {from_badge} into {to_badge} ({'rename' if is_rename else 'merge'})",
            details=summary,
            employee_badge=to_badge,
            success=True,
        ))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Employee merge failed (%s -> %s): %s", from_badge, to_badge, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การรวมข้อมูลพนักงานล้มเหลว: {exc}",
        )

    return {
        "success": True,
        "from_badge": from_badge,
        "to_badge": to_badge,
        "case": "rename" if is_rename else "merge",
        "summary": summary,
    }
