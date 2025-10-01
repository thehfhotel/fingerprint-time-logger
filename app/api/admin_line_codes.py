"""
Admin Line Codes API

Endpoints for admin to manage LINE linking codes in nickname management page.
Admin mode activated with passcode: "bananabananabanana"
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

router = APIRouter()

# Admin passcode (hardcoded as per requirements)
ADMIN_PASSCODE = "bananabananabanana"


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class AdminPasscodeVerify(BaseModel):
    passcode: str


class GenerateCodeRequest(BaseModel):
    badge_number: str
    passcode: str


class RegenerateCodeRequest(BaseModel):
    badge_number: str
    passcode: str
    reason: Optional[str] = None


class UnlinkAccountRequest(BaseModel):
    badge_number: str
    passcode: str
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

def verify_admin_passcode(passcode: str):
    """Verify admin passcode"""
    if passcode != ADMIN_PASSCODE:
        raise HTTPException(
            status_code=403,
            detail="รหัสผ่านผู้ดูแลระบบไม่ถูกต้อง (Invalid admin passcode)"
        )


def generate_6_digit_code() -> str:
    """Generate random 6-digit numeric code"""
    return ''.join(random.choices(string.digits, k=6))


def is_code_expired(generated_at: datetime, expiry_hours: int = 24) -> bool:
    """Check if linking code has expired (default 24 hours)"""
    if not generated_at:
        return True
    expiry_time = generated_at + timedelta(hours=expiry_hours)
    return datetime.now(timezone.utc) > expiry_time


# ============================================================================
# API ENDPOINTS
# ============================================================================

@router.post("/verify-passcode")
async def verify_passcode(request: AdminPasscodeVerify):
    """
    Verify admin passcode
    Returns success if passcode is correct
    """
    try:
        verify_admin_passcode(request.passcode)
        return {
            "success": True,
            "message": "ยืนยันตัวตนผู้ดูแลระบบสำเร็จ (Admin authenticated)"
        }
    except HTTPException as e:
        raise e


@router.post("/generate")
async def generate_linking_code(
    request: GenerateCodeRequest,
    db: Session = Depends(get_db)
):
    """
    Generate 6-digit LINE linking code for employee
    - One code per badge number
    - Code expires after 24 hours
    - Only unlinked employees can have codes
    """
    verify_admin_passcode(request.passcode)

    # Find employee by badge number
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
            detail=f"พนักงาน {employee.display_name} เชื่อมต่อ LINE แล้ว"
        )

    # Check if existing code is still valid (not expired)
    if employee.line_linking_code and employee.line_linking_code_generated_at:
        if not is_code_expired(employee.line_linking_code_generated_at):
            return {
                "success": True,
                "message": "รหัสเชื่อมต่อที่มีอยู่ยังใช้งานได้",
                "badge_number": employee.badge_number,
                "display_name": employee.display_name,
                "linking_code": employee.line_linking_code,
                "generated_at": employee.line_linking_code_generated_at.isoformat(),
                "expires_at": (employee.line_linking_code_generated_at + timedelta(hours=24)).isoformat()
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

    return {
        "success": True,
        "message": f"สร้างรหัสเชื่อมต่อสำหรับ {employee.display_name} สำเร็จ",
        "badge_number": employee.badge_number,
        "display_name": employee.display_name,
        "linking_code": employee.line_linking_code,
        "generated_at": employee.line_linking_code_generated_at.isoformat(),
        "expires_at": (employee.line_linking_code_generated_at + timedelta(hours=24)).isoformat()
    }


@router.post("/regenerate")
async def regenerate_linking_code(
    request: RegenerateCodeRequest,
    db: Session = Depends(get_db)
):
    """
    Regenerate LINE linking code if employee lost it
    - Replaces existing code
    - Resets expiry timer
    """
    verify_admin_passcode(request.passcode)

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
    passcode: str,
    include_expired: bool = False,
    db: Session = Depends(get_db)
):
    """
    List all pending LINE linking codes
    - Shows employees with codes but not yet linked
    - Optionally include expired codes
    """
    verify_admin_passcode(passcode)

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
    passcode: str,
    db: Session = Depends(get_db)
):
    """
    List all employees with linked LINE accounts
    """
    verify_admin_passcode(passcode)

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
    db: Session = Depends(get_db)
):
    """
    Unlink LINE account from employee (admin only)
    - Removes LINE user ID and profile data
    - Allows employee to link a different LINE account
    """
    verify_admin_passcode(request.passcode)

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
    passcode: str,
    db: Session = Depends(get_db)
):
    """
    Get LINE linking statistics
    """
    verify_admin_passcode(passcode)

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
