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
from app.services.location_service import location_service, safe_location_name
from app.services.line_auth_service import line_auth_service


router = APIRouter()


def _linked_fingerprint_device_ids(terminal: Device) -> list[int]:
    """Parse the list of fingerprint device IDs whose records this kiosk
    should surface, from terminal.device_metadata.linked_fingerprint_device_ids.

    Stored as a JSON array of ints inside the same device_metadata blob that
    already holds the GPS config — e.g.::

        {"gps": {...}, "linked_fingerprint_device_ids": [1]}

    Missing / malformed metadata returns []. Non-int entries are silently
    dropped so a manual SQL edit that puts a string ID in won't 500 the
    endpoint.
    """
    import json
    if not terminal.device_metadata:
        return []
    try:
        meta = json.loads(terminal.device_metadata)
    except (json.JSONDecodeError, TypeError):
        return []
    raw = meta.get("linked_fingerprint_device_ids", [])
    if not isinstance(raw, list):
        return []
    return [int(x) for x in raw if isinstance(x, (int, float)) and not isinstance(x, bool)]


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
    # 0 = check-in, 1 = check-out. User chooses on the scan page AFTER scanning.
    punch_type: int = Field(0, ge=0, le=1, description="0=check-in, 1=check-out")


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
    # Device IDs (typically fingerprint scanners) whose attendance records
    # should also surface on this kiosk's feed. Empty list means QR-only.
    # The kiosk JS unions these with TERMINAL_ID when filtering WebSocket
    # broadcasts; the /recent endpoint applies the same union for backfill.
    linked_fingerprint_device_ids: list[int] = []


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
        # User chose check-in (0) or check-out (1) on the scan page after the
        # QR scan. The validation_message tag ("QR Check-in" / "QR Check-out")
        # is what mobile-checkin.js parses to display the action.
        action_label = "QR Check-out" if request.punch_type == 1 else "QR Check-in"
        attendance_record = AttendanceRecord(
            employee_badge_number=employee.badge_number,
            timestamp=datetime.now(timezone.utc),
            device_id=terminal_id,
            punch_type=request.punch_type,
            sync_status="synced",  # QR check-in is always synced
            validation_message=f"{action_label} at {location_validation['terminal_location']['location_name']}, "
                             f"GPS: {request.latitude},{request.longitude}, "
                             f"Distance: {location_validation['distance']}m"
        )

        db.add(attendance_record)
        db.commit()
        db.refresh(attendance_record)

        # Invalidate the dashboard's attendance_summary cache (5-min TTL).
        # Without this, the next /api/private/attendance/summary fetch
        # returns a stale snapshot that doesn't include this scan, and
        # the dashboard waits up to 5 min for the scheduler to refresh.
        try:
            from app.services.device_cache_service import device_cache_service
            device_cache_service.invalidate("attendance_summary")
        except Exception as cache_error:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to invalidate attendance_summary cache: {cache_error}"
            )

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

            # Defense-in-depth: strip HTML-special chars before returning to clients
            terminal_list.append(TerminalInfo(
                id=terminal.id,
                name=terminal.name,
                location_name=safe_location_name(location_name),
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

        # Defense-in-depth: strip HTML-special chars before returning to clients
        terminal_name = safe_location_name(terminal_name) or f"Terminal {terminal_id}"

        # Generate QR code
        qr_data = qr_service.generate_qr_code_for_terminal(terminal_id, size=400)

        return QRCodeResponse(
            qr_image=qr_data["qr_image"],
            terminal_id=terminal_id,
            terminal_name=terminal_name,
            expires_at=qr_data["expires_at"],
            expires_in_seconds=qr_data["expires_in_seconds"],
            linked_fingerprint_device_ids=_linked_fingerprint_device_ids(terminal),
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
# TERMINAL RECENT FEED (Unprotected, per-branch)
# ============================================================================

@router.get("/recent/{terminal_id}")
async def get_recent_for_terminal(
    terminal_id: int,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Recent attendance records for one QR terminal (kiosk feed backfill).

    Scoped to {terminal_id} ∪ terminal.device_metadata.linked_fingerprint_device_ids
    so each branch sees its own QR check-ins plus any fingerprint scanners
    linked to it. The link list is configured per-terminal — empty by
    default (QR-only), populated to include the at-branch fingerprint
    device. Today is interpreted in Bangkok time.
    """
    try:
        from datetime import timedelta
        from app.services.attendance_service import attendance_service

        # Verify the terminal exists and is a QR terminal
        terminal = db.query(Device).filter(
            Device.id == terminal_id,
            Device.device_type == "qr_terminal"
        ).first()
        if not terminal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบเครื่อง QR terminal ID {terminal_id}"
            )

        bangkok_tz = timezone(timedelta(hours=7))
        today_bkk = datetime.now(bangkok_tz).date()

        # Union of this kiosk's own QR check-ins (device_id == terminal_id)
        # and any fingerprint scans on devices we've explicitly linked here.
        device_ids = [terminal_id] + _linked_fingerprint_device_ids(terminal)

        records = attendance_service.get_attendance_records(
            start_date=today_bkk,
            end_date=today_bkk,
            device_ids=device_ids,
            limit=max(1, min(limit, 50)),
        )

        badges = {r.employee_badge_number for r in records}
        employees = {
            e.badge_number: e
            for e in db.query(Employee)
            .filter(Employee.badge_number.in_(badges))
            .all()
        } if badges else {}

        return {
            "terminal_id": terminal_id,
            "records": [
                {
                    "id": r.id,
                    "badge_number": r.employee_badge_number,
                    "employee_name": (
                        employees[r.employee_badge_number].display_name
                        if r.employee_badge_number in employees
                        else f"รหัส {r.employee_badge_number}"
                    ),
                    "timestamp": r.timestamp.replace(tzinfo=timezone.utc).isoformat()
                        if r.timestamp else None,
                    "device_id": r.device_id,
                    "punch_type": r.punch_type,
                    "metadata": r.validation_message,
                }
                for r in records
            ],
            "total": len(records),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การโหลดประวัติล่าสุดล้มเหลว: {str(e)}"
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
