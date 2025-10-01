"""
QR Check-In API Endpoints

Handles QR code scanning, GPS validation, and attendance recording.
Integrates QR service, location service, and LINE authentication.
"""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.models.models import Device, Employee, AttendanceRecord
from app.services.qr_service import qr_service
from app.services.location_service import location_service
from app.services.line_auth_service import line_auth_service


router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class QRScanRequest(BaseModel):
    """Request model for QR code scanning"""
    qr_token: str = Field(..., description="JWT token from QR code")
    jwt_token: str = Field(..., description="User's LINE authentication JWT token")
    latitude: float = Field(..., ge=-90, le=90, description="User's GPS latitude")
    longitude: float = Field(..., ge=-180, le=180, description="User's GPS longitude")
    accuracy: Optional[float] = Field(None, ge=0, description="GPS accuracy in meters")


class QRScanResponse(BaseModel):
    """Response model for QR code scanning"""
    success: bool
    message: str
    attendance_record: dict
    location_validation: dict


class QRCodeResponse(BaseModel):
    """Response model for QR code generation"""
    qr_image: str
    terminal_id: int
    terminal_name: str
    expires_at: str
    expires_in_seconds: int


# ============================================================================
# QR Check-In Endpoints
# ============================================================================

@router.post("/scan", response_model=QRScanResponse)
async def scan_qr_code(
    request: QRScanRequest,
    db: Session = Depends(get_db)
):
    """
    Process QR code scan and create attendance record

    Validation Flow:
    1. Verify JWT token (LINE authentication)
    2. Validate QR token (time + nonce)
    3. Validate GPS location (radius + accuracy)
    4. Verify LINE-to-employee link
    5. Create AttendanceRecord
    6. Return success with attendance data

    Returns:
        QRScanResponse with attendance record and validation details
    """
    try:
        # Step 1: Verify LINE authentication JWT token
        try:
            jwt_payload = line_auth_service.verify_jwt_token(request.jwt_token)
            line_user_id = jwt_payload.get("line_user_id")
            employee_badge = jwt_payload.get("employee_badge")
        except HTTPException as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="กรุณาเข้าสู่ระบบด้วย LINE อีกครั้ง"
            )

        # Step 2: Validate QR token (checks expiry and replay)
        qr_payload = qr_service.validate_qr_token(request.qr_token)
        terminal_id = qr_payload.get("terminal_id")

        # Step 3: Validate GPS location
        location_validation = location_service.validate_gps_location(
            user_lat=request.latitude,
            user_lon=request.longitude,
            user_accuracy=request.accuracy,
            terminal_id=terminal_id,
            db=db
        )

        if not location_validation["valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=location_validation["message"]
            )

        # Step 4: Verify LINE-to-employee link
        employee = db.query(Employee).filter(
            Employee.line_user_id == line_user_id,
            Employee.badge_number == employee_badge,
            Employee.is_active == True
        ).first()

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ไม่พบข้อมูลพนักงาน กรุณาเชื่อมต่อบัญชี LINE กับระบบก่อน"
            )

        # Step 5: Create AttendanceRecord
        attendance_record = AttendanceRecord(
            badge_number=employee.badge_number,
            timestamp=datetime.now(timezone.utc),
            device_id=terminal_id,
            sync_status="synced",  # QR check-in is always synced
            metadata=f"QR Check-in at {location_validation['terminal_location']['location_name']}, "
                    f"GPS: {request.latitude},{request.longitude}, "
                    f"Distance: {location_validation['distance']}m"
        )

        db.add(attendance_record)
        db.commit()
        db.refresh(attendance_record)

        # Step 6: Return success response
        return QRScanResponse(
            success=True,
            message=f"บันทึกเวลาสำเร็จ ที่ {location_validation['terminal_location']['location_name']}",
            attendance_record={
                "id": attendance_record.id,
                "badge_number": attendance_record.badge_number,
                "timestamp": attendance_record.timestamp.isoformat(),
                "employee_name": employee.display_name,
                "location": location_validation['terminal_location']['location_name']
            },
            location_validation={
                "distance": location_validation["distance"],
                "location_name": location_validation['terminal_location']['location_name'],
                "message": location_validation["message"]
            }
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การบันทึกเวลาล้มเหลว: {str(e)}"
        )


@router.get("/kiosk/{terminal_id}", response_model=QRCodeResponse)
async def get_qr_code_for_kiosk(
    terminal_id: int,
    db: Session = Depends(get_db)
):
    """
    Generate QR code for terminal display

    Args:
        terminal_id: ID of the QR terminal device

    Returns:
        QRCodeResponse with QR code image and expiration info
    """
    try:
        # Verify terminal exists and is QR terminal
        terminal = db.query(Device).filter(
            Device.id == terminal_id,
            Device.device_type == "qr_terminal"
        ).first()

        if not terminal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบเครื่อง QR terminal ID {terminal_id}"
            )

        # Get terminal location name for display
        import json
        try:
            metadata = json.loads(terminal.device_metadata) if terminal.device_metadata else {}
            terminal_name = metadata.get("gps", {}).get("location_name", f"Terminal {terminal_id}")
        except json.JSONDecodeError:
            terminal_name = f"Terminal {terminal_id}"

        # Generate QR code
        qr_data = qr_service.generate_qr_code_for_terminal(terminal_id, size=400)

        return QRCodeResponse(
            qr_image=qr_data["qr_image"],
            terminal_id=terminal_id,
            terminal_name=terminal_name,
            expires_at=qr_data["expires_at"],
            expires_in_seconds=qr_data["expires_in_seconds"]
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การสร้าง QR code ล้มเหลว: {str(e)}"
        )


@router.post("/refresh/{terminal_id}", response_model=QRCodeResponse)
async def refresh_qr_code(
    terminal_id: int,
    db: Session = Depends(get_db)
):
    """
    Manually refresh QR code for terminal

    This is identical to get_qr_code_for_kiosk but uses POST method
    for manual refresh button on kiosk display.

    Args:
        terminal_id: ID of the QR terminal device

    Returns:
        QRCodeResponse with new QR code image and expiration info
    """
    return await get_qr_code_for_kiosk(terminal_id, db)


@router.get("/validate-location")
async def validate_user_location(
    latitude: float,
    longitude: float,
    accuracy: Optional[float] = None,
    terminal_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Validate user GPS location (testing/debugging endpoint)

    Args:
        latitude: User's GPS latitude
        longitude: User's GPS longitude
        accuracy: GPS accuracy in meters (optional)
        terminal_id: Specific terminal to check (optional, checks all if not provided)

    Returns:
        Location validation results
    """
    try:
        if terminal_id:
            # Validate against specific terminal
            result = location_service.validate_gps_location(
                user_lat=latitude,
                user_lon=longitude,
                user_accuracy=accuracy,
                terminal_id=terminal_id,
                db=db
            )
        else:
            # Validate against all terminals
            result = location_service.validate_multiple_locations(
                user_lat=latitude,
                user_lon=longitude,
                user_accuracy=accuracy,
                db=db
            )

        return {
            "success": True,
            "validation": result
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การตรวจสอบตำแหน่งล้มเหลว: {str(e)}"
        )
