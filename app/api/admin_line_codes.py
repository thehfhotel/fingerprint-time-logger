"""
Admin Line Codes API

Endpoints for admin to manage LINE linking codes in nickname management page.
Protected by admin session authentication (same as admin console).
"""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import random
import string

from app.core.database import get_db
from app.models.models import Employee
from app.api.admin_auth import require_admin_auth

router = APIRouter()

# NOTE: All endpoints now use admin session token authentication
# No separate passcode needed - page is already protected by admin console auth


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class GenerateCodeRequest(BaseModel):
    badge_number: str


class RegenerateCodeRequest(BaseModel):
    badge_number: str
    reason: Optional[str] = None


class UnlinkAccountRequest(BaseModel):
    badge_number: str
    reason: Optional[str] = None


class PendingCodeResponse(BaseModel):
    badge_number: str
    display_name: str
    english_name: Optional[str]
    thai_name: Optional[str]
    linking_code: str
    generated_at: datetime
    expires_at: datetime
    is_expired: bool


class LinkedAccountResponse(BaseModel):
    badge_number: str
    display_name: str
    english_name: Optional[str]
    thai_name: Optional[str]
    line_user_id: str
    line_display_name: Optional[str]
    line_picture_url: Optional[str]
    linked_at: Optional[datetime]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def generate_6_digit_code() -> str:
    """Generate random 6-digit numeric code"""
    return ''.join(random.choices(string.digits, k=6))


def is_code_expired(generated_at: datetime, expiry_hours: int = 24) -> bool:
    """Check if linking code has expired (default 24 hours)"""
    if not generated_at:
        return True

    # Ensure generated_at is timezone-aware for comparison
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    expiry_time = generated_at + timedelta(hours=expiry_hours)
    return datetime.now(timezone.utc) > expiry_time


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post("/generate")
async def generate_linking_code(
    request: GenerateCodeRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth)
):
    """
    Generate 6-digit LINE linking code for employee
    - One code per badge number
    - Code expires after 24 hours
    - If already linked: unlinks old account and generates new code for re-linking
    - Protected by admin session authentication
    """

    # Find employee by badge number
    employee = db.query(Employee).filter(
        Employee.badge_number == request.badge_number
    ).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail=f"ไม่พบพนักงาน badge number: {request.badge_number}"
        )

    # Store old LINE info if re-linking
    old_line_user_id = None
    old_line_display_name = None
    is_relink = False

    # Check if already linked - if so, unlink for re-linking
    if employee.line_user_id:
        is_relink = True
        old_line_user_id = employee.line_user_id
        old_line_display_name = employee.line_display_name

        # Unlink old account
        employee.line_user_id = None
        employee.line_display_name = None
        employee.line_picture_url = None

    # Check if existing code is still valid (not expired) and not re-linking
    if not is_relink and employee.line_linking_code and employee.line_linking_code_generated_at:
        if not is_code_expired(employee.line_linking_code_generated_at):
            return {
                "success": True,
                "message": "รหัสเชื่อมต่อที่มีอยู่ยังใช้งานได้",
                "badge_number": employee.badge_number,
                "display_name": employee.display_name,
                "linking_code": employee.line_linking_code,
                "generated_at": employee.line_linking_code_generated_at.isoformat(),
                "expires_at": (employee.line_linking_code_generated_at + timedelta(hours=24)).isoformat(),
                "is_relink": False
            }

    # Generate unique 6-digit code
    max_attempts = 100
    for _ in range(max_attempts):
        code = generate_6_digit_code()

        # Check if code is unique among pending (unexpired) codes
        existing = db.query(Employee).filter(
            Employee.line_linking_code == code,
            Employee.line_user_id.is_(None)  # Only unlinked accounts
        ).first()

        if not existing:
            break
    else:
        raise HTTPException(
            status_code=500,
            detail="ไม่สามารถสร้างรหัสที่ไม่ซ้ำได้ กรุณาลองอีกครั้ง"
        )

    # Save code to employee
    employee.line_linking_code = code
    employee.line_linking_code_generated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(employee)

    # Different messages for new link vs re-link
    if is_relink:
        message = f"ยกเลิกการเชื่อมต่อเดิม ({old_line_display_name}) และสร้างรหัสใหม่สำหรับ {employee.display_name} สำเร็จ"
    else:
        message = f"สร้างรหัสเชื่อมต่อสำหรับ {employee.display_name} สำเร็จ"

    return {
        "success": True,
        "message": message,
        "badge_number": employee.badge_number,
        "display_name": employee.display_name,
        "linking_code": employee.line_linking_code,
        "generated_at": employee.line_linking_code_generated_at.isoformat(),
        "expires_at": (employee.line_linking_code_generated_at + timedelta(hours=24)).isoformat(),
        "is_relink": is_relink,
        "old_line_user_id": old_line_user_id,
        "old_line_display_name": old_line_display_name
    }


@router.post("/regenerate")
async def regenerate_linking_code(
    request: RegenerateCodeRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth)
):
    """
    Regenerate LINE linking code if employee lost it
    - Replaces existing code
    - Resets expiry timer
    - Protected by admin session authentication
    """

    # Find employee
    employee = db.query(Employee).filter(
        Employee.badge_number == request.badge_number
    ).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail=f"ไม่พบพนักงาน badge number: {request.badge_number}"
        )

    # Check if already linked
    if employee.line_user_id:
        raise HTTPException(
            status_code=400,
            detail=f"พนักงาน {employee.display_name} เชื่อมต่อ LINE แล้ว ไม่สามารถสร้างรหัสใหม่ได้"
        )

    # Generate new unique code
    max_attempts = 100
    for _ in range(max_attempts):
        code = generate_6_digit_code()

        existing = db.query(Employee).filter(
            Employee.line_linking_code == code,
            Employee.line_user_id.is_(None)
        ).first()

        if not existing:
            break
    else:
        raise HTTPException(
            status_code=500,
            detail="ไม่สามารถสร้างรหัสที่ไม่ซ้ำได้ กรุณาลองอีกครั้ง"
        )

    old_code = employee.line_linking_code

    # Update code
    employee.line_linking_code = code
    employee.line_linking_code_generated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(employee)

    return {
        "success": True,
        "message": f"สร้างรหัสใหม่สำหรับ {employee.display_name} สำเร็จ",
        "badge_number": employee.badge_number,
        "display_name": employee.display_name,
        "old_code": old_code,
        "new_code": employee.line_linking_code,
        "generated_at": employee.line_linking_code_generated_at.isoformat(),
        "expires_at": (employee.line_linking_code_generated_at + timedelta(hours=24)).isoformat(),
        "reason": request.reason
    }


@router.get("/list", response_model=List[PendingCodeResponse])
async def list_pending_codes(
    include_expired: bool = False,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth)
):
    """
    List all pending LINE linking codes
    - Shows employees with codes but not yet linked
    - Optionally include expired codes
    - Protected by admin session authentication
    """

    # Query employees with linking codes but no LINE account
    employees = db.query(Employee).filter(
        Employee.line_linking_code.isnot(None),
        Employee.line_user_id.is_(None)
    ).order_by(Employee.line_linking_code_generated_at.desc()).all()

    result = []
    for employee in employees:
        if not employee.line_linking_code_generated_at:
            continue

        expired = is_code_expired(employee.line_linking_code_generated_at)

        # Skip expired codes if not requested
        if expired and not include_expired:
            continue

        expires_at = employee.line_linking_code_generated_at + timedelta(hours=24)

        result.append(PendingCodeResponse(
            badge_number=employee.badge_number,
            display_name=employee.display_name,
            english_name=employee.english_name,
            thai_name=employee.thai_name,
            linking_code=employee.line_linking_code,
            generated_at=employee.line_linking_code_generated_at,
            expires_at=expires_at,
            is_expired=expired
        ))

    return result


@router.get("/linked", response_model=List[LinkedAccountResponse])
async def list_linked_accounts(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth)
):
    """
    List all employees with linked LINE accounts
    - Protected by admin session authentication
    """

    # Query employees with LINE accounts
    employees = db.query(Employee).filter(
        Employee.line_user_id.isnot(None)
    ).order_by(Employee.updated_at.desc()).all()

    result = []
    for employee in employees:
        result.append(LinkedAccountResponse(
            badge_number=employee.badge_number,
            display_name=employee.display_name,
            english_name=employee.english_name,
            thai_name=employee.thai_name,
            line_user_id=employee.line_user_id,
            line_display_name=employee.line_display_name,
            line_picture_url=employee.line_picture_url,
            linked_at=employee.updated_at
        ))

    return result


@router.post("/unlink")
async def unlink_line_account(
    request: UnlinkAccountRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth)
):
    """
    Unlink LINE account from employee (admin only)
    - Removes LINE user ID and profile data
    - Allows employee to link a different LINE account
    - Protected by admin session authentication
    """

    # Find employee
    employee = db.query(Employee).filter(
        Employee.badge_number == request.badge_number
    ).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail=f"ไม่พบพนักงาน badge number: {request.badge_number}"
        )

    # Check if linked
    if not employee.line_user_id:
        raise HTTPException(
            status_code=400,
            detail=f"พนักงาน {employee.display_name} ยังไม่ได้เชื่อมต่อ LINE"
        )

    old_line_id = employee.line_user_id
    old_display_name = employee.line_display_name

    # Remove LINE data
    employee.line_user_id = None
    employee.line_display_name = None
    employee.line_picture_url = None
    employee.line_linking_code = None
    employee.line_linking_code_generated_at = None

    db.commit()
    db.refresh(employee)

    return {
        "success": True,
        "message": f"ยกเลิกการเชื่อมต่อ LINE สำหรับ {employee.display_name} สำเร็จ",
        "badge_number": employee.badge_number,
        "display_name": employee.display_name,
        "unlinked_line_id": old_line_id,
        "unlinked_line_name": old_display_name,
        "reason": request.reason
    }


# ============================================================================
# STATISTICS ENDPOINT
# ============================================================================

@router.get("/stats")
async def get_linking_stats(
    db: Session = Depends(get_db),
    _: str = Depends(require_admin_auth)
):
    """
    Get LINE linking statistics
    - Protected by admin session authentication
    """

    total_employees = db.query(Employee).filter(
        Employee.is_active == True
    ).count()

    linked_count = db.query(Employee).filter(
        Employee.is_active == True,
        Employee.line_user_id.isnot(None)
    ).count()

    pending_count = db.query(Employee).filter(
        Employee.is_active == True,
        Employee.line_linking_code.isnot(None),
        Employee.line_user_id.is_(None)
    ).count()

    unlinked_count = db.query(Employee).filter(
        Employee.is_active == True,
        Employee.line_user_id.is_(None),
        Employee.line_linking_code.is_(None)
    ).count()

    return {
        "total_active_employees": total_employees,
        "linked_accounts": linked_count,
        "pending_codes": pending_count,
        "unlinked": unlinked_count,
        "linking_percentage": round((linked_count / total_employees * 100) if total_employees > 0 else 0, 2)
    }
