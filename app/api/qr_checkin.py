"""
QR Check-In API Endpoints

Handles QR code scanning, GPS validation, and attendance recording.
Integrates QR service, location service, and LINE authentication.
"""

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote
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


class TerminalInfo(BaseModel):
    """Terminal information for location selector"""
    id: int
    name: str
    location_name: Optional[str] = None
    is_active: bool


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
        # URL-decode token to handle URL-encoded special characters (+, /, =)
        decoded_qr_token = unquote(request.qr_token)
        qr_payload = qr_service.validate_qr_token(decoded_qr_token)
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
            # Log failed check-in attempt for monitoring
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"[QR CHECK-IN FAILED] Location validation failed - "
                f"Employee: {employee_badge}, "
                f"Terminal: {terminal_id} ({location_validation['terminal_location']['location_name']}), "
                f"Distance: {location_validation['distance']}m, "
                f"Allowed: {location_validation['allowed_radius']}m, "
                f"GPS: ({request.latitude}, {request.longitude}), "
                f"Accuracy: {request.accuracy}m"
            )

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
            employee_badge_number=employee.badge_number,
            timestamp=datetime.now(timezone.utc),
            device_id=terminal_id,
            punch_type=0,  # 0 = check_in (auto-determine based on time)
            sync_status="synced",  # QR check-in is always synced
            validation_message=f"QR Check-in at {location_validation['terminal_location']['location_name']}, "
                             f"GPS: {request.latitude},{request.longitude}, "
                             f"Distance: {location_validation['distance']}m"
        )

        db.add(attendance_record)
        db.commit()
        db.refresh(attendance_record)

        # Broadcast attendance update to WebSocket clients (QR terminal display)
        try:
            from app.main_unified import manager

            await manager.broadcast({
                "type": "attendance_update",
                "data": {
                    "device_id": terminal_id,
                    "badge_number": employee.badge_number,
                    "employee_name": employee.display_name,
                    "timestamp": attendance_record.timestamp.replace(tzinfo=timezone.utc).isoformat(),
                    "metadata": attendance_record.validation_message
                }
            })
        except Exception as broadcast_error:
            # Log but don't fail the request if broadcast fails
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to broadcast QR check-in update: {broadcast_error}")

        # Step 6: Return success response
        response_data = QRScanResponse(
            success=True,
            message=f"บันทึกเวลาสำเร็จ ที่ {location_validation['terminal_location']['location_name']}",
            attendance_record={
                "id": attendance_record.id,
                "badge_number": attendance_record.employee_badge_number,
                "timestamp": attendance_record.timestamp.replace(tzinfo=timezone.utc).isoformat(),
                "employee_name": employee.display_name,
                "location": location_validation['terminal_location']['location_name']
            },
            location_validation={
                "distance": location_validation["distance"],
                "location_name": location_validation['terminal_location']['location_name'],
                "message": location_validation["message"]
            }
        )

        # DEBUG: Log response structure
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[QR CHECK-IN DEBUG] Response structure: {response_data.model_dump()}")
        logger.info(f"[QR CHECK-IN DEBUG] location_validation keys: {list(response_data.location_validation.keys())}")

        return response_data

    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การบันทึกเวลาล้มเหลว: {str(e)}"
        )


@router.get("/terminals", response_model=list[TerminalInfo])
async def list_qr_terminals(db: Session = Depends(get_db)):
    """
    List all available QR terminals for location selector

    Returns:
        List of QR terminal devices with their information
    """
    try:
        import json

        terminals = db.query(Device).filter(
            Device.device_type == "qr_terminal"
        ).all()

        terminal_list = []
        for terminal in terminals:
            # Extract location name from metadata
            location_name = terminal.name
            try:
                if terminal.device_metadata:
                    metadata = json.loads(terminal.device_metadata)
                    location_name = metadata.get("gps", {}).get("location_name", terminal.name)
            except (json.JSONDecodeError, AttributeError):
                pass

            terminal_list.append(TerminalInfo(
                id=terminal.id,
                name=terminal.name,
                location_name=location_name,
                is_active=terminal.is_active
            ))

        return terminal_list

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การโหลดรายการเทอร์มินัลล้มเหลว: {str(e)}"
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


# ============================================================================
# ATTENDANCE RECORDS FOR MOBILE PAGE (Unprotected Path)
# ============================================================================

@router.get("/attendance/employee/badge/{employee_badge}")
async def get_employee_attendance_for_mobile(
    employee_badge: str,
    limit: int = 5,
    db: Session = Depends(get_db)
):
    """Get recent attendance records for mobile check-in page (unprotected path)"""
    try:
        from app.services.attendance_service import attendance_service

        # Check if employee exists
        employee = db.query(Employee).filter(Employee.badge_number == employee_badge).first()
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        # Get recent attendance records
        records = attendance_service.get_attendance_records(
            employee_badge=employee_badge,
            limit=limit
        )

        return {
            "employee_badge": employee_badge,
            "records": [
                {
                    "id": record.id,
                    "timestamp": record.timestamp.replace(tzinfo=timezone.utc).isoformat() if record.timestamp else None,
                    "punch_type": record.punch_type,
                    "status": record.status,
                    "device_id": record.device_id,
                    "validation_message": record.validation_message  # Include for QR check-in detection
                }
                for record in records
            ],
            "total": len(records)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
