"""
Admin Authentication API
Secure passcode authentication with session management
"""
from fastapi import APIRouter, HTTPException, Header, Depends, Response, Cookie, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
import logging

from app.services.admin_auth_service import admin_auth_service

logger = logging.getLogger(__name__)

router = APIRouter()

class LoginRequest(BaseModel):
    passcode: str = Field(..., min_length=1, description="Admin passcode")

class LoginResponse(BaseModel):
    success: bool
    token: str
    expires_at: str
    expires_in_seconds: int
    message: str

class ValidateResponse(BaseModel):
    valid: bool
    expires_in_seconds: Optional[int] = None
    expires_at: Optional[str] = None

class LogoutResponse(BaseModel):
    success: bool
    message: str

def get_token_from_header(authorization: Optional[str] = Header(None)) -> str:
    """
    Extract Bearer token from Authorization header

    Args:
        authorization: Authorization header value

    Returns:
        Token string

    Raises:
        HTTPException: If token is missing or invalid format
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    return parts[1]

def get_token_from_cookie_or_header(
    admin_session_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None)
) -> str:
    """
    Extract token from HttpOnly cookie or Authorization header

    Priority:
    1. HttpOnly cookie (preferred for browser requests)
    2. Authorization header (for API clients)

    Args:
        admin_session_token: Token from HttpOnly cookie
        authorization: Authorization header value

    Returns:
        Token string

    Raises:
        HTTPException: If token is missing from both sources
    """
    # Try cookie first (preferred for browser requests)
    if admin_session_token:
        return admin_session_token

    # Fall back to Authorization header
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]

    raise HTTPException(
        status_code=401,
        detail="Unauthorized: Missing authentication token"
    )

@router.post("/login")
async def admin_login(request: LoginRequest):
    """
    Authenticate admin user with passcode

    Returns session token valid for 1 hour and sets HttpOnly cookie
    """
    try:
        # Verify passcode
        if not admin_auth_service.verify_passcode(request.passcode):
            logger.warning("Failed login attempt with incorrect passcode")
            raise HTTPException(
                status_code=401,
                detail="รหัสผ่านไม่ถูกต้อง"
            )

        # Create session
        token = admin_auth_service.create_session()
        session_info = admin_auth_service.get_session_info(token)

        logger.info("Admin login successful")

        # Create JSON response
        response = JSONResponse(content={
            "success": True,
            "token": token,
            "expires_at": session_info['expires_at'],
            "expires_in_seconds": session_info['expires_in_seconds'],
            "message": "เข้าสู่ระบบสำเร็จ"
        })

        # Set HttpOnly cookie for server-side authentication
        # This prevents JavaScript access and XSS attacks
        response.set_cookie(
            key="admin_session_token",
            value=token,
            httponly=True,  # Prevent JavaScript access
            max_age=3600,  # 1 hour in seconds
            samesite="lax",  # CSRF protection
            secure=False  # Set to True in production with HTTPS
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=500,
            detail="เกิดข้อผิดพลาดในการเข้าสู่ระบบ"
        )

@router.get("/validate", response_model=ValidateResponse)
async def validate_session(token: str = Depends(get_token_from_header)):
    """
    Validate admin session token

    Returns session validity and remaining time
    """
    try:
        # Clean up expired sessions periodically
        admin_auth_service.cleanup_expired_sessions()

        # Validate token
        if not admin_auth_service.validate_session(token):
            return ValidateResponse(valid=False)

        # Get session info
        session_info = admin_auth_service.get_session_info(token)

        return ValidateResponse(
            valid=True,
            expires_in_seconds=session_info['expires_in_seconds'],
            expires_at=session_info['expires_at']
        )

    except Exception as e:
        logger.error(f"Session validation error: {e}")
        return ValidateResponse(valid=False)

@router.post("/logout")
async def admin_logout(token: str = Depends(get_token_from_header)):
    """
    Logout admin user and revoke session
    """
    try:
        admin_auth_service.revoke_session(token)
        logger.info("Admin logout successful")

        # Create JSON response
        response = JSONResponse(content={
            "success": True,
            "message": "ออกจากระบบสำเร็จ"
        })

        # Clear the HttpOnly cookie
        response.delete_cookie(key="admin_session_token")

        return response

    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(
            status_code=500,
            detail="เกิดข้อผิดพลาดในการออกจากระบบ"
        )

@router.get("/session-info")
async def get_session_info(token: str = Depends(get_token_from_header)):
    """
    Get current session information
    """
    try:
        if not admin_auth_service.validate_session(token):
            raise HTTPException(status_code=401, detail="Session expired or invalid")

        session_info = admin_auth_service.get_session_info(token)

        return {
            "success": True,
            "session": session_info
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get session info error: {e}")
        raise HTTPException(
            status_code=500,
            detail="เกิดข้อผิดพลาดในการดึงข้อมูล session"
        )

# Dependency for protected routes
async def require_admin_auth(token: str = Depends(get_token_from_cookie_or_header)) -> str:
    """
    Dependency to require valid admin authentication
    Accepts token from HttpOnly cookie or Authorization header

    Returns:
        Valid session token

    Raises:
        HTTPException: If authentication fails
    """
    if not admin_auth_service.validate_session(token):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Session expired or invalid"
        )
    return token
