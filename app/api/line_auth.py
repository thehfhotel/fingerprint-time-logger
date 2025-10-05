"""
LINE Authentication API

Endpoints for LINE OAuth integration with QR check-in:
- Initiate LINE OAuth login flow
- Handle LINE OAuth callback
- Link LINE account with employee using 6-digit code
- Verify JWT tokens
- Unlink LINE accounts (admin only)

Mobile Safari compatible with HTML meta refresh redirects.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Query, Request, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee
from app.services.line_auth_service import line_auth_service

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class LinkAccountRequest(BaseModel):
    """Request to link LINE account with employee"""
    linking_code: str
    jwt_token: str


class UnlinkAccountRequest(BaseModel):
    """Request to unlink LINE account (admin only)"""
    badge_number: str
    admin_passcode: str
    reason: Optional[str] = None


class VerifyTokenRequest(BaseModel):
    """Request to verify JWT token"""
    token: str


# ============================================================================
# OAuth Flow Endpoints
# ============================================================================

@router.get("/login")
async def line_login(request: Request):
    """
    Initiate LINE OAuth login flow

    Returns:
        HTML response with meta refresh redirect for Mobile Safari compatibility
    """
    try:
        auth_data = line_auth_service.generate_authorization_url()
        auth_url = auth_data["auth_url"]

        # Mobile Safari compatible redirect using HTML meta refresh
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta http-equiv="refresh" content="0; url={auth_url}">
            <title>เข้าสู่ระบบด้วย LINE</title>
            <style>
                body {{
                    font-family: 'Prompt', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #06C755 0%, #00B900 100%);
                }}
                .loading {{
                    text-align: center;
                    color: white;
                }}
                .spinner {{
                    border: 4px solid rgba(255, 255, 255, 0.3);
                    border-radius: 50%;
                    border-top: 4px solid white;
                    width: 40px;
                    height: 40px;
                    animation: spin 1s linear infinite;
                    margin: 0 auto 20px;
                }}
                @keyframes spin {{
                    0% {{ transform: rotate(0deg); }}
                    100% {{ transform: rotate(360deg); }}
                }}
            </style>
        </head>
        <body>
            <div class="loading">
                <div class="spinner"></div>
                <h2>กำลังเชื่อมต่อ LINE...</h2>
                <p>หากไม่ถูกเปลี่ยนเส้นทางอัตโนมัติ <a href="{auth_url}" style="color: white;">คลิกที่นี่</a></p>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate LINE login: {str(e)}"
        )


@router.get("/callback")
async def line_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Handle LINE OAuth callback

    Query Parameters:
        code: Authorization code from LINE
        state: CSRF state token
        error: Error code if authentication failed
        error_description: Error description if authentication failed

    Returns:
        HTML response redirecting to link account page with LINE profile data
    """
    # Handle OAuth errors
    if error:
        error_msg = error_description or error
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>การเข้าสู่ระบบล้มเหลว</title>
            <style>
                body {{
                    font-family: 'Prompt', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: #f5f5f5;
                }}
                .error-box {{
                    background: white;
                    padding: 30px;
                    border-radius: 8px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    text-align: center;
                    max-width: 400px;
                }}
                .error-icon {{
                    font-size: 48px;
                    color: #dc3545;
                    margin-bottom: 20px;
                }}
                h2 {{
                    color: #333;
                    margin-bottom: 10px;
                }}
                p {{
                    color: #666;
                    margin-bottom: 20px;
                }}
                a {{
                    display: inline-block;
                    padding: 10px 20px;
                    background: #06C755;
                    color: white;
                    text-decoration: none;
                    border-radius: 4px;
                }}
            </style>
        </head>
        <body>
            <div class="error-box">
                <div class="error-icon">❌</div>
                <h2>การเข้าสู่ระบบล้มเหลว</h2>
                <p>{error_msg}</p>
                <a href="/qr-checkin/mobile">ลองอีกครั้ง</a>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content, status_code=400)

    # Validate required parameters
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter"
        )

    try:
        # Validate CSRF state token
        if not line_auth_service.validate_state(state):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired state token"
            )

        # Exchange code for access token
        token_data = line_auth_service.exchange_code_for_token(code)
        access_token = token_data["access_token"]

        # Get LINE user profile
        profile = line_auth_service.get_user_profile(access_token)

        # Extract profile data
        line_user_id = profile.get("userId", "")
        display_name = profile.get("displayName", "ผู้ใช้ LINE")
        picture_url = profile.get("pictureUrl", "")

        # Check if this LINE user is already linked to an employee
        existing_employee = db.query(Employee).filter(
            Employee.line_user_id == line_user_id
        ).first()

        # Create JWT token with employee_badge if already linked
        if existing_employee:
            jwt_token = line_auth_service.create_jwt_token(
                line_user_id=line_user_id,
                employee_badge=existing_employee.badge_number,
                display_name=display_name,
                picture_url=picture_url
            )
            # Already linked - redirect to mobile check-in
            redirect_url = f"/qr-checkin/mobile?jwt={jwt_token}"
        else:
            # Not yet linked - redirect to link account page
            jwt_token = line_auth_service.create_jwt_token(
                line_user_id=line_user_id,
                employee_badge=None,
                display_name=display_name,
                picture_url=picture_url
            )
            redirect_url = (
                f"/qr-checkin/link-account"
                f"?jwt={jwt_token}"
                f"&line_user_id={line_user_id}"
                f"&display_name={display_name}"
                f"&picture_url={picture_url}"
            )

        link_url = redirect_url

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta http-equiv="refresh" content="0; url={link_url}">
            <title>เข้าสู่ระบบสำเร็จ</title>
            <style>
                body {{
                    font-family: 'Prompt', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background: linear-gradient(135deg, #06C755 0%, #00B900 100%);
                }}
                .loading {{
                    text-align: center;
                    color: white;
                }}
                .spinner {{
                    border: 4px solid rgba(255, 255, 255, 0.3);
                    border-radius: 50%;
                    border-top: 4px solid white;
                    width: 40px;
                    height: 40px;
                    animation: spin 1s linear infinite;
                    margin: 0 auto 20px;
                }}
                @keyframes spin {{
                    0% {{ transform: rotate(0deg); }}
                    100% {{ transform: rotate(360deg); }}
                }}
            </style>
        </head>
        <body>
            <div class="loading">
                <div class="spinner"></div>
                <h2>เข้าสู่ระบบสำเร็จ!</h2>
                <p>กำลังเชื่อมต่อบัญชี...</p>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth callback failed: {str(e)}"
        )


# ============================================================================
# Account Linking Endpoints
# ============================================================================

@router.post("/link-account")
async def link_account(
    request: LinkAccountRequest,
    db: Session = Depends(get_db)
):
    """
    Link LINE account with employee using 6-digit code

    Request Body:
        linking_code: 6-digit code from admin
        jwt_token: JWT token containing LINE user ID

    Returns:
        Success message with new JWT token for authenticated session

    Raises:
        400: Invalid linking code or already linked
        401: Invalid JWT token
        404: Employee not found
    """
    try:
        # Verify JWT token to get LINE user data
        token_payload = line_auth_service.verify_jwt_token(request.jwt_token)
        line_user_id = token_payload.get("line_user_id")
        line_display_name = token_payload.get("display_name")
        line_picture_url = token_payload.get("picture_url")

        if not line_user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing LINE user ID"
            )

        # Find employee by linking code
        employee = db.query(Employee).filter(
            Employee.line_linking_code == request.linking_code,
            Employee.is_active == True
        ).first()

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="รหัสเชื่อมต่อไม่ถูกต้องหรือหมดอายุ"
            )

        # Check if linking code has expired (24 hours)
        if employee.line_linking_code_generated_at:
            # Ensure timezone-aware datetime for comparison
            generated_at = employee.line_linking_code_generated_at
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            expiry = generated_at + timedelta(hours=24)
            if now > expiry:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="รหัสเชื่อมต่อหมดอายุแล้ว กรุณาติดต่อเจ้าหน้าที่"
                )

        # Check if employee already has LINE linked
        if employee.line_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="บัญชีนี้เชื่อมต่อ LINE แล้ว"
            )

        # Link LINE account to employee
        employee.line_user_id = line_user_id
        employee.line_display_name = line_display_name
        employee.line_picture_url = line_picture_url
        employee.line_linking_code = None  # Clear code after successful link
        employee.line_linking_code_generated_at = None
        employee.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(employee)

        # Create new JWT token with employee badge for authenticated session
        new_token = line_auth_service.create_jwt_token(
            line_user_id=line_user_id,
            employee_badge=employee.badge_number,
            display_name=line_display_name,
            picture_url=line_picture_url
        )

        return {
            "success": True,
            "message": "เชื่อมต่อบัญชีสำเร็จ",
            "employee": {
                "badge_number": employee.badge_number,
                "display_name": employee.display_name,
                "line_user_id": employee.line_user_id
            },
            "token": new_token
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การเชื่อมต่อบัญชีล้มเหลว: {str(e)}"
        )


@router.post("/unlink-account")
async def unlink_account(
    request: UnlinkAccountRequest,
    db: Session = Depends(get_db)
):
    """
    Unlink LINE account from employee (admin only)

    Request Body:
        badge_number: Employee badge number
        admin_passcode: Admin password
        reason: Optional reason for unlinking

    Returns:
        Success message

    Raises:
        403: Invalid admin passcode
        404: Employee not found
        400: Employee not linked
    """
    from app.api.admin_line_codes import ADMIN_PASSCODE

    # Verify admin passcode
    if request.admin_passcode != ADMIN_PASSCODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="รหัสผ่านผู้ดูแลระบบไม่ถูกต้อง"
        )

    try:
        # Find employee
        employee = db.query(Employee).filter(
            Employee.badge_number == request.badge_number,
            Employee.is_active == True
        ).first()

        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ไม่พบพนักงาน"
            )

        # Check if employee has LINE linked
        if not employee.line_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="พนักงานนี้ไม่ได้เชื่อมต่อ LINE"
            )

        # Unlink LINE account
        old_line_user_id = employee.line_user_id
        employee.line_user_id = None
        employee.line_display_name = None
        employee.line_picture_url = None
        employee.line_linking_code = None
        employee.line_linking_code_generated_at = None
        employee.updated_at = datetime.now(timezone.utc)

        db.commit()

        return {
            "success": True,
            "message": "ยกเลิกการเชื่อมต่อสำเร็จ",
            "badge_number": employee.badge_number,
            "old_line_user_id": old_line_user_id,
            "reason": request.reason
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"การยกเลิกการเชื่อมต่อล้มเหลว: {str(e)}"
        )


@router.post("/verify-token")
async def verify_token(request: VerifyTokenRequest):
    """
    Verify JWT token

    Request Body:
        token: JWT token to verify

    Returns:
        Token validation with employee badge and LINE profile data

    Raises:
        401: Invalid or expired token
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[verify-token] Received request: {request}")
        logger.info(f"[verify-token] Token value: {request.token[:20] if request.token else 'None'}...")

        payload = line_auth_service.verify_jwt_token(request.token)

        # Return structure expected by mobile-checkin.js
        result = {
            "valid": True,
            "employee_badge": payload.get("employee_badge"),  # None if not linked
            "line_profile": {
                "user_id": payload.get("line_user_id"),
                "display_name": payload.get("display_name"),
                "picture_url": payload.get("picture_url")
            },
            "payload": payload  # Keep original payload for backward compatibility
        }
        logger.info(f"[verify-token] Returning: valid=True, employee_badge={result['employee_badge']}")
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"[verify-token] Unexpected error: {str(e)}")
        raise
