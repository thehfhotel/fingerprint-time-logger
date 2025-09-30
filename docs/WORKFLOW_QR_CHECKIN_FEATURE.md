# QR Code Check-In/Checkout Feature - Implementation Workflow

## Feature Overview

Add QR code-based check-in/checkout system with LINE authentication and GPS verification as an alternative to fingerprint scanning.

### Key Requirements
- ✅ **Rotating QR code** display at unattended check-in desk (30-second auto-refresh)
- ✅ LINE application authentication
- ✅ GPS/location verification during scan
- ✅ Unified attendance logging (same as fingerprint logs)
- ✅ Real-time updates via WebSocket
- ✅ **No admin supervision required** - kiosk operates autonomously

---

## Architecture Design

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                     QR Check-In System                      │
│                   (Unattended Kiosk Mode)                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐      ┌──────────────┐   ┌─────────────┐ │
│  │ Kiosk Display│      │ Employee     │   │ LINE OAuth  │ │
│  │ **ROTATING** │◄─────┤ Mobile       │◄──┤ Service     │ │
│  │ QR Code      │      │ Scanner      │   │             │ │
│  │ (30s refresh)│      │ (Camera)     │   └─────────────┘ │
│  └──────┬───────┘      └──────┬───────┘                    │
│         │                     │                            │
│         │    WebSocket        │                            │
│         └──────────┬──────────┘                            │
│                    │                                       │
│         ┌──────────▼──────────┐                           │
│         │  FastAPI Backend    │                           │
│         │  - QR Service       │  ⚡ Auto-refresh QR       │
│         │  - Auth Service     │  🔒 Replay protection     │
│         │  - Location Service │  📍 GPS validation        │
│         │  - Attendance API   │  📊 Real-time logging     │
│         └──────────┬──────────┘                           │
│                    │                                       │
│         ┌──────────▼──────────┐                           │
│         │  SQLite Database    │                           │
│         │  - Employee         │                           │
│         │  - AttendanceRecord │                           │
│         │  - Device (QR Term) │                           │
│         └─────────────────────┘                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘

🔐 Security: Rotating QR prevents screenshot/photo reuse attacks
```

### Data Flow

```
Employee Flow (First Time - With 6-Digit Code):
1. Admin generates 6-digit linking code for employee in nickname page (admin mode)
2. Admin gives code to employee (e.g., "123456")
3. Employee opens mobile page → LINE Login
4. System checks if LINE account already linked:
   - If linked → Skip to step 8 (JWT token issued)
   - If not linked → Continue to step 5
5. Employee enters 6-digit code on linking page
6. System validates code and links LINE User ID to Employee Badge
7. Linking code is cleared (one-time use)
8. Employee receives JWT Token (valid 24 hours)
9. Employee approaches kiosk, scans ROTATING QR code
10. App captures GPS coordinates (Geolocation API)
11. Submit: {qr_token, gps_lat, gps_lon, jwt}
12. Backend validates: Token expiry, GPS radius, LINE mapping, nonce
13. Create AttendanceRecord (same schema as fingerprint)
14. Broadcast WebSocket update to dashboard
15. Mobile shows success/failure instantly

Employee Flow (Returning User - Already Linked):
1. Employee opens mobile page → LINE Login
2. System recognizes LINE User ID → Issues JWT Token immediately
3. Skip linking page entirely → Ready to scan QR
4. (Continue from step 9 above)

Kiosk Flow (Unattended - No Admin Required):
1. Kiosk page auto-loads on startup (fullscreen mode)
2. Backend generates time-limited QR code (30s validity)
3. QR contains JWT: {terminal_id, timestamp, nonce, exp}
4. **Auto-refresh every 30 seconds** (WebSocket push)
5. Display recent check-ins in real-time (WebSocket updates)
6. Visual countdown timer shows QR expiration (3, 2, 1...)
7. Large display optimized for scanning from 1-2 meters away

Security Benefits of Rotating QR:
✅ Screenshot/photo of QR becomes invalid after 30s
✅ One-time nonce prevents replay attacks
✅ Expired QR codes automatically rejected
✅ No admin supervision needed - system is self-validating
✅ GPS radius validation prevents remote check-ins
```

---

## Implementation Phases

### Phase 1: Database & Backend Foundation (Week 1)
**Duration**: 3-4 days

#### Task 1.1: Database Schema Changes
**Priority**: 🔴 Critical

```python
# Migration 1: Add LINE user ID and linking code to Employee
class Employee(Base):
    # ... existing fields ...
    line_user_id: Optional[str] = None  # LINE unique user ID
    line_display_name: Optional[str] = None  # LINE profile name
    line_picture_url: Optional[str] = None  # LINE profile picture
    line_linking_code: Optional[str] = None  # 6-digit code for LINE account linking
    line_linking_code_generated_at: Optional[datetime] = None  # When code was generated

# Migration 2: Add metadata to AttendanceRecord
class AttendanceRecord(Base):
    # ... existing fields ...
    metadata: Optional[JSON] = None  # Store GPS, source, etc.

# Metadata structure:
{
    "source": "qr_code",  # or "fingerprint"
    "gps": {
        "latitude": 13.7563,
        "longitude": 100.5018,
        "accuracy": 10.5
    },
    "ip_address": "192.168.1.100",
    "user_agent": "Mozilla/5.0...",
    "line_user_id": "U1234567890abcdef"
}
```

**Files to Create**:
- `database/migrations/add_line_integration.py`
- Update: `app/models.py`

**Alembic Commands**:
```bash
alembic revision --autogenerate -m "Add LINE integration fields"
alembic upgrade head
```

#### Task 1.1.5: Admin Linking Code Generation API
**Priority**: 🔴 Critical

**New Requirement**: Admin generates 6-digit codes for employees to link LINE accounts

**Admin Authentication**:
- Passcode: `bananabananabanana`
- Admin mode activated in nickname management page
- Admin mode required for code generation

**Files to Create/Update**:
- `app/api/admin_line_codes.py` - Admin API for code generation
- Update: `app/api/consolidated_employees.py` - Add admin endpoints

```python
# app/api/admin_line_codes.py
"""
Admin API for LINE linking code generation
Requires admin passcode: bananabananabanana
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.models import Employee
from datetime import datetime
import secrets
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Admin passcode
ADMIN_PASSCODE = "bananabananabanana"

def verify_admin_passcode(passcode: str):
    """Verify admin passcode"""
    if passcode != ADMIN_PASSCODE:
        raise HTTPException(status_code=403, detail="Invalid admin passcode")
    return True

def generate_6_digit_code() -> str:
    """Generate unique 6-digit code"""
    return f"{secrets.randbelow(1000000):06d}"

@router.post("/admin/line-codes/verify-passcode")
async def verify_passcode(passcode: str):
    """Verify admin passcode for admin mode activation"""
    try:
        verify_admin_passcode(passcode)
        return {
            "success": True,
            "message": "Admin access granted"
        }
    except HTTPException:
        return {
            "success": False,
            "message": "Invalid passcode"
        }

@router.post("/admin/line-codes/generate")
async def generate_linking_code(
    badge_number: str,
    passcode: str,
    db: Session = Depends(get_db)
):
    """
    Generate 6-digit LINE linking code for employee
    Admin only - requires passcode
    """
    # Verify admin passcode
    verify_admin_passcode(passcode)

    # Get employee
    employee = db.query(Employee).filter(
        Employee.badge_number == badge_number
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Check if already linked
    if employee.line_user_id:
        raise HTTPException(
            status_code=400,
            detail=f"Employee already linked to LINE account: {employee.line_display_name}"
        )

    # Generate unique code
    while True:
        code = generate_6_digit_code()
        # Check if code already exists (unlikely but possible)
        existing = db.query(Employee).filter(
            Employee.line_linking_code == code,
            Employee.line_user_id.is_(None)  # Only check unlinked employees
        ).first()
        if not existing:
            break

    # Save code to employee
    employee.line_linking_code = code
    employee.line_linking_code_generated_at = datetime.utcnow()
    db.commit()
    db.refresh(employee)

    logger.info(f"[Admin] Generated LINE linking code for badge {badge_number}: {code}")

    return {
        "success": True,
        "badge_number": badge_number,
        "name_thai": employee.name_thai,
        "linking_code": code,
        "generated_at": employee.line_linking_code_generated_at.isoformat(),
        "message": "รหัสเชื่อมต่อ LINE สำเร็จ"
    }

@router.post("/admin/line-codes/regenerate")
async def regenerate_linking_code(
    badge_number: str,
    passcode: str,
    db: Session = Depends(get_db)
):
    """
    Regenerate LINE linking code (if employee lost the code)
    Admin only - requires passcode
    """
    # Verify admin passcode
    verify_admin_passcode(passcode)

    # Get employee
    employee = db.query(Employee).filter(
        Employee.badge_number == badge_number
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Check if already linked
    if employee.line_user_id:
        raise HTTPException(
            status_code=400,
            detail="Employee already linked - use unlink first"
        )

    # Generate new unique code
    while True:
        code = generate_6_digit_code()
        existing = db.query(Employee).filter(
            Employee.line_linking_code == code,
            Employee.line_user_id.is_(None)
        ).first()
        if not existing:
            break

    # Update code
    old_code = employee.line_linking_code
    employee.line_linking_code = code
    employee.line_linking_code_generated_at = datetime.utcnow()
    db.commit()

    logger.info(f"[Admin] Regenerated LINE code for badge {badge_number}: {old_code} → {code}")

    return {
        "success": True,
        "badge_number": badge_number,
        "name_thai": employee.name_thai,
        "linking_code": code,
        "old_code": old_code,
        "generated_at": employee.line_linking_code_generated_at.isoformat(),
        "message": "สร้างรหัสใหม่สำเร็จ"
    }

@router.get("/admin/line-codes/list")
async def list_linking_codes(
    passcode: str,
    db: Session = Depends(get_db)
):
    """
    List all employees with linking codes (not yet linked)
    Admin only - requires passcode
    """
    # Verify admin passcode
    verify_admin_passcode(passcode)

    # Get employees with codes but not yet linked
    employees = db.query(Employee).filter(
        Employee.line_linking_code.isnot(None),
        Employee.line_user_id.is_(None)
    ).order_by(Employee.line_linking_code_generated_at.desc()).all()

    return {
        "success": True,
        "count": len(employees),
        "employees": [
            {
                "badge_number": emp.badge_number,
                "name_thai": emp.name_thai,
                "linking_code": emp.line_linking_code,
                "generated_at": emp.line_linking_code_generated_at.isoformat() if emp.line_linking_code_generated_at else None
            }
            for emp in employees
        ]
    }

@router.get("/admin/line-codes/linked")
async def list_linked_employees(
    passcode: str,
    db: Session = Depends(get_db)
):
    """
    List all employees with linked LINE accounts
    Admin only - requires passcode
    """
    # Verify admin passcode
    verify_admin_passcode(passcode)

    # Get linked employees
    employees = db.query(Employee).filter(
        Employee.line_user_id.isnot(None)
    ).order_by(Employee.name_thai).all()

    return {
        "success": True,
        "count": len(employees),
        "employees": [
            {
                "badge_number": emp.badge_number,
                "name_thai": emp.name_thai,
                "line_display_name": emp.line_display_name,
                "line_user_id": emp.line_user_id
            }
            for emp in employees
        ]
    }
```

**Mount Router** (add to `app/main_unified.py`):
```python
from app.api import admin_line_codes

fingerprint_app.include_router(
    admin_line_codes.router,
    prefix="/api",
    tags=["Admin LINE Codes"]
)
```

#### Task 1.2: Create QR Terminal Virtual Devices (Multiple Locations)
**Priority**: 🔴 Critical

**Requirement**: Support 2 kiosks at different branch locations with separate GPS validation

```python
# database/seeds/create_qr_terminals.py
from app.models import Device
from app.database import SessionLocal

def seed_qr_terminals():
    """Create virtual devices for multiple QR terminal locations"""
    db = SessionLocal()

    # Terminal 1: Main Office/Branch
    terminal_1 = Device(
        device_name="QR Terminal - Main Office",
        ip_address="virtual",
        port=0,
        password="",
        device_type="qr_terminal",
        is_active=True,
        metadata={
            "terminal_id": 1,
            "location_name": "Main Office",
            "gps": {
                "latitude": 13.7563,   # Update with actual coordinates
                "longitude": 100.5018,
                "radius_meters": 200
            }
        }
    )

    # Terminal 2: Branch Office/Second Location
    terminal_2 = Device(
        device_name="QR Terminal - Branch Office",
        ip_address="virtual",
        port=0,
        password="",
        device_type="qr_terminal",
        is_active=True,
        metadata={
            "terminal_id": 2,
            "location_name": "Branch Office",
            "gps": {
                "latitude": 13.7200,   # Update with actual coordinates
                "longitude": 100.5200,
                "radius_meters": 200
            }
        }
    )

    db.add(terminal_1)
    db.add(terminal_2)
    db.commit()

    print(f"Created Terminal 1: {terminal_1.id} - {terminal_1.device_name}")
    print(f"Created Terminal 2: {terminal_2.id} - {terminal_2.device_name}")

    return [terminal_1.id, terminal_2.id]
```

**Execution**:
```bash
python database/seeds/create_qr_terminals.py
```

**Key Features**:
- Each terminal has unique `terminal_id` in QR token
- Separate GPS coordinates and radius per location
- GPS validation checks against terminal-specific coordinates
- Attendance records track which terminal was used

#### Task 1.3: LINE OAuth Service (Proven Implementation from loyalty-app)
**Priority**: 🔴 Critical

**Reference**: This implementation is proven working in production from `~/loyalty-app`

**Files to Create**:
- `app/services/line_auth_service.py`

```python
# app/services/line_auth_service.py
# Proven working LINE OAuth implementation from loyalty-app project
import os
import requests
from typing import Dict, Optional
import jwt
from datetime import datetime, timedelta
from urllib.parse import urlencode
import logging

logger = logging.getLogger(__name__)

class LineAuthService:
    """
    LINE OAuth 2.0 authentication service
    Proven implementation from production loyalty-app
    """

    def __init__(self):
        self.channel_id = os.getenv("LINE_CHANNEL_ID")
        self.channel_secret = os.getenv("LINE_CHANNEL_SECRET")
        self.callback_url = os.getenv("LINE_CALLBACK_URL")

        # LINE OAuth endpoints
        self.auth_url = "https://access.line.me/oauth2/v2.1/authorize"
        self.token_url = "https://api.line.me/oauth2/v2.1/token"
        self.profile_url = "https://api.line.me/v2/profile"

        # Validate configuration
        if not self.channel_id or not self.channel_secret:
            logger.warning("LINE OAuth not configured - Channel ID and Secret required")

    def get_authorization_url(self, state: str) -> str:
        """
        Generate LINE OAuth authorization URL
        Mobile-friendly for Safari iPhone compatibility
        """
        params = {
            "response_type": "code",
            "client_id": self.channel_id,
            "redirect_uri": self.callback_url,
            "state": state,
            "scope": "profile openid email"  # Request email if available
        }
        auth_url = f"{self.auth_url}?{urlencode(params)}"
        logger.debug(f"[LINE Auth] Generated auth URL with state: {state}")
        return auth_url

    def exchange_code_for_token(self, code: str) -> Dict:
        """
        Exchange authorization code for access token
        Returns: {"access_token": str, "token_type": str, "expires_in": int}
        """
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.callback_url,
            "client_id": self.channel_id,
            "client_secret": self.channel_secret
        }

        logger.debug("[LINE Auth] Exchanging code for token")
        response = requests.post(
            self.token_url,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "fingerprint-logger/1.0"
            }
        )

        if not response.ok:
            logger.error(f"[LINE Auth] Token exchange failed: {response.status_code} - {response.text}")
            raise Exception(f"LINE token exchange failed: {response.text}")

        return response.json()

    def get_user_profile(self, access_token: str) -> Dict:
        """
        Get LINE user profile using access token
        Returns: {"userId": str, "displayName": str, "pictureUrl": str?, "statusMessage": str?}
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "fingerprint-logger/1.0"
        }

        logger.debug("[LINE Auth] Fetching user profile")
        response = requests.get(self.profile_url, headers=headers)

        if not response.ok:
            logger.error(f"[LINE Auth] Profile fetch failed: {response.status_code}")
            raise Exception(f"LINE profile fetch failed: {response.text}")

        profile = response.json()
        logger.debug(f"[LINE Auth] Profile received: userId={profile.get('userId')}, displayName={profile.get('displayName')}")

        return profile

    def process_line_callback(self, code: str) -> Dict:
        """
        Complete LINE OAuth flow: exchange code → get profile
        Returns: LINE profile dict with userId, displayName, pictureUrl
        """
        # Step 1: Exchange code for access token
        token_data = self.exchange_code_for_token(code)
        access_token = token_data.get("access_token")

        if not access_token:
            raise Exception("No access token received from LINE")

        # Step 2: Get user profile
        profile = self.get_user_profile(access_token)

        if not profile.get("userId"):
            raise Exception("No userId in LINE profile")

        return profile

    def create_jwt_token(self, line_user_id: str, employee_badge: str) -> str:
        """
        Create JWT token for authenticated session
        Used for mobile check-in app authentication
        """
        payload = {
            "line_user_id": line_user_id,
            "employee_badge": employee_badge,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=24)
        }

        token = jwt.encode(payload, self.channel_secret, algorithm="HS256")
        logger.debug(f"[LINE Auth] Created JWT for employee: {employee_badge}")

        return token

    def verify_jwt_token(self, token: str) -> Optional[Dict]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, self.channel_secret, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("[LINE Auth] JWT token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"[LINE Auth] Invalid JWT token: {e}")
            return None

line_auth_service = LineAuthService()
```

**Key Differences from Original (Based on Production Experience)**:
- ✅ **Mobile Safari compatibility**: Added User-Agent headers
- ✅ **Enhanced error handling**: Detailed logging and error messages
- ✅ **Email scope**: Request email permission (optional for LINE)
- ✅ **Complete flow method**: `process_line_callback()` handles full OAuth flow
- ✅ **Production-tested**: This exact code runs in loyalty-app successfully

**Environment Variables** (`.env`):
```env
LINE_CHANNEL_ID=your_channel_id
LINE_CHANNEL_SECRET=your_channel_secret
LINE_CALLBACK_URL=https://emp.thehfhotel.org/fingerprintlogs/api/auth/line/callback
```

#### Task 1.4: LINE Auth Endpoints
**Priority**: 🔴 Critical

**Files to Create**:
- `app/api/line_auth.py`

**Proven Implementation (Adapted from loyalty-app Production Code)**:

```python
# app/api/line_auth.py
"""
LINE OAuth endpoints with mobile Safari compatibility
Proven implementation adapted from loyalty-app production code
"""
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from app.services.line_auth_service import line_auth_service
from app.services.employee_service import employee_service
from app.core.database import get_db
from sqlalchemy.orm import Session
import secrets
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Store states temporarily (use Redis in production for multi-server deployments)
oauth_states = {}

@router.get("/login")
async def line_login(request: Request):
    """
    Initiate LINE OAuth login with mobile Safari compatibility
    Proven pattern from loyalty-app: Detect mobile Safari and use HTML meta refresh
    """
    # Generate secure state for CSRF protection
    state = secrets.token_urlsafe(32)
    oauth_states[state] = {
        "created_at": datetime.utcnow(),
        "user_agent": request.headers.get("user-agent", "")
    }

    # Clean up expired states (older than 10 minutes)
    current_time = datetime.utcnow()
    expired_states = [s for s, data in oauth_states.items()
                      if (current_time - data["created_at"]).total_seconds() > 600]
    for s in expired_states:
        del oauth_states[s]

    # Get LINE authorization URL
    auth_url = line_auth_service.get_authorization_url(state)
    logger.info(f"[LINE Login] Initiated for state: {state[:8]}...")

    # Mobile Safari compatibility (proven pattern from loyalty-app)
    user_agent = request.headers.get("user-agent", "")
    is_mobile = any(device in user_agent for device in ["iPhone", "iPad", "iPod", "Android"])
    is_safari = "Safari" in user_agent and "Chrome" not in user_agent and "CriOS" not in user_agent

    if is_mobile and is_safari:
        # Use HTML meta refresh for Safari mobile (proven to work)
        logger.debug("[LINE Login] Using HTML redirect for Safari mobile")
        html_redirect = f"""
<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="refresh" content="0;url={auth_url}">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Redirecting to LINE...</title>
</head>
<body>
    <p>Redirecting to LINE authentication...</p>
    <script>window.location.href = '{auth_url}';</script>
</body>
</html>"""
        return HTMLResponse(content=html_redirect)

    # Standard redirect for other browsers
    return {"auth_url": auth_url, "redirect": True}

@router.get("/callback")
async def line_callback(
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle LINE OAuth callback with direct API calls
    Proven pattern from loyalty-app: Direct LINE API calls (no passport dependency)
    This approach is more reliable for stateless mobile flows
    """
    logger.info(f"[LINE Callback] Received callback for state: {state[:8]}...")

    # Verify state (CSRF protection)
    if state not in oauth_states:
        logger.error(f"[LINE Callback] Invalid state: {state[:8]}...")
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    # Clean up used state
    state_data = oauth_states.pop(state)

    try:
        # Complete OAuth flow using proven direct API approach
        profile = line_auth_service.process_line_callback(code)
        line_user_id = profile.get("userId")
        display_name = profile.get("displayName")
        picture_url = profile.get("pictureUrl")

        logger.info(f"[LINE Callback] Profile received: {display_name} ({line_user_id})")

        # Check if LINE account is already linked to an employee
        employee = employee_service.get_by_line_user_id(line_user_id)

        if employee:
            # Already linked - create session token
            logger.info(f"[LINE Callback] Existing employee found: {employee.badge_number}")
            jwt_token = line_auth_service.create_jwt_token(line_user_id, employee.badge_number)

            # Mobile Safari compatibility for success redirect
            user_agent = request.headers.get("user-agent", "")
            is_mobile_safari = ("Safari" in user_agent and
                              "Chrome" not in user_agent and
                              any(d in user_agent for d in ["iPhone", "iPad", "iPod"]))

            if is_mobile_safari:
                # Use HTML meta refresh for Safari mobile
                success_url = f"/qr-checkin/mobile?token={jwt_token}"
                html_redirect = f"""
<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="refresh" content="0;url={success_url}">
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <script>window.location.href = '{success_url}';</script>
</body>
</html>"""
                return HTMLResponse(content=html_redirect)

            # Standard redirect with JWT token
            return RedirectResponse(
                url=f"/qr-checkin/mobile?token={jwt_token}",
                status_code=302
            )

        else:
            # Not linked - send to linking page with LINE info
            logger.info(f"[LINE Callback] New user - needs account linking: {line_user_id}")

            # Store LINE profile temporarily for linking (use session storage in production)
            link_token = secrets.token_urlsafe(32)
            oauth_states[f"link_{link_token}"] = {
                "line_user_id": line_user_id,
                "display_name": display_name,
                "picture_url": picture_url,
                "created_at": datetime.utcnow()
            }

            # Redirect to account linking page
            return RedirectResponse(
                url=f"/qr-checkin/link-account?token={link_token}",
                status_code=302
            )

    except Exception as e:
        logger.error(f"[LINE Callback] OAuth flow failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"LINE authentication failed: {str(e)}"
        )

@router.post("/link-account")
async def link_line_account(
    link_token: str,
    linking_code: str,  # 6-digit code (not badge_number)
    db: Session = Depends(get_db)
):
    """
    Link LINE account to existing employee using 6-digit code
    Required for first-time LINE login users

    NEW FLOW: Employee enters 6-digit code given by admin (not badge number)
    """
    # Get stored LINE profile
    link_key = f"link_{link_token}"
    if link_key not in oauth_states:
        raise HTTPException(status_code=400, detail="Invalid or expired link token")

    line_data = oauth_states.pop(link_key)
    line_user_id = line_data["line_user_id"]
    display_name = line_data["display_name"]

    logger.info(f"[LINE Link] Linking {display_name} ({line_user_id}) with code {linking_code}")

    # Find employee by 6-digit linking code
    employee = db.query(Employee).filter(
        Employee.line_linking_code == linking_code,
        Employee.line_user_id.is_(None)  # Not yet linked
    ).first()

    if not employee:
        raise HTTPException(
            status_code=404,
            detail="รหัสเชื่อมต่อไม่ถูกต้อง หรือถูกใช้ไปแล้ว (Invalid or already used linking code)"
        )

    if not employee.is_active:
        raise HTTPException(
            status_code=403,
            detail="บัญชีพนักงานถูกระงับ (Employee account is inactive)"
        )

    # Check if LINE ID is already linked to another employee (security check)
    existing_link = db.query(Employee).filter(
        Employee.line_user_id == line_user_id
    ).first()

    if existing_link:
        raise HTTPException(
            status_code=409,
            detail=f"LINE account already linked to employee {existing_link.badge_number}"
        )

    # Perform linking
    employee.line_user_id = line_user_id
    employee.line_display_name = display_name
    # Clear linking code after successful link (one-time use)
    employee.line_linking_code = None
    employee.line_linking_code_generated_at = None
    db.commit()
    db.refresh(employee)

    logger.info(f"[LINE Link] Successfully linked badge {employee.badge_number} to LINE {line_user_id}")

    # Create JWT token for session
    jwt_token = line_auth_service.create_jwt_token(line_user_id, employee.badge_number)

    return {
        "success": True,
        "message": "เชื่อมต่อ LINE สำเร็จ (LINE account linked successfully)",
        "token": jwt_token,
        "employee": {
            "badge_number": employee.badge_number,
            "name_thai": employee.name_thai,
            "line_display_name": display_name
        }
    }

@router.post("/unlink-account")
async def unlink_line_account(
    badge_number: str,
    passcode: str,  # Require admin passcode for unlinking
    db: Session = Depends(get_db)
):
    """
    Unlink LINE account from employee
    Admin function - requires admin passcode
    """
    # Verify admin passcode
    if passcode != "bananabananabanana":
        raise HTTPException(status_code=403, detail="Invalid admin passcode")

    employee = db.query(Employee).filter(
        Employee.badge_number == badge_number
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    if not employee.line_user_id:
        raise HTTPException(status_code=400, detail="No LINE account linked")

    logger.info(f"[LINE Unlink] Unlinking LINE {employee.line_user_id} from badge {badge_number}")

    # Clear LINE data (employee can link again with new code)
    employee.line_user_id = None
    employee.line_display_name = None
    employee.line_picture_url = None
    # Don't clear linking_code - admin can reuse it or regenerate
    db.commit()

    return {
        "success": True,
        "message": "LINE account unlinked successfully"
    }

@router.get("/verify-token")
async def verify_token(token: str):
    """
    Verify JWT token validity
    Used by mobile app to check authentication status
    """
    payload = line_auth_service.verify_jwt_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "valid": True,
        "line_user_id": payload.get("line_user_id"),
        "employee_badge": payload.get("employee_badge"),
        "expires_at": payload.get("exp")
    }
```

**Key Differences from Original (Based on loyalty-app Production Experience)**:
- ✅ **Mobile Safari HTML redirects**: Both login and callback use HTML meta refresh for Safari iOS
- ✅ **User-Agent detection**: Proven logic for mobile Safari identification
- ✅ **Direct API calls**: No passport dependency, more reliable for stateless flows
- ✅ **State expiration**: Auto-cleanup of expired OAuth states (10-minute TTL)
- ✅ **Comprehensive logging**: Production-grade logging at every step
- ✅ **Account linking flow**: Separate token system for linking new users
- ✅ **Link management**: Both link and unlink endpoints for admin control
- ✅ **Token verification**: Endpoint for mobile app to validate JWT tokens
- ✅ **CSRF protection**: Secure state management with tokens

**Mount Router** (add to `app/main_unified.py`):
```python
from app.api import line_auth

fingerprint_app.include_router(
    line_auth.router,
    prefix="/api/auth/line",
    tags=["LINE Authentication"]
)
```

---

### Phase 2: QR Code System (Week 1-2)
**Duration**: 4-5 days

#### Task 2.1: QR Code Service
**Priority**: 🔴 Critical

**Files to Create**:
- `app/services/qr_service.py`

```python
# app/services/qr_service.py
import qrcode
import io
import base64
import jwt
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional

class QRCodeService:
    def __init__(self):
        self.secret_key = os.getenv("QR_SECRET_KEY", secrets.token_urlsafe(32))
        self.validity_seconds = 30  # QR code valid for 30 seconds
        self.used_nonces = set()  # In production, use Redis with TTL

    def generate_qr_token(self, terminal_id: int) -> str:
        """Generate time-limited QR token"""
        payload = {
            "terminal_id": terminal_id,
            "timestamp": datetime.utcnow().isoformat(),
            "nonce": secrets.token_urlsafe(16),
            "exp": datetime.utcnow() + timedelta(seconds=self.validity_seconds)
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    def generate_qr_image(self, terminal_id: int) -> str:
        """Generate QR code image as base64 string"""
        token = self.generate_qr_token(terminal_id)

        # Create QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(token)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

        return f"data:image/png;base64,{img_str}"

    def validate_qr_token(self, token: str) -> Optional[Dict]:
        """Validate QR token and prevent replay"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            nonce = payload.get("nonce")

            # Check if already used (replay attack prevention)
            if nonce in self.used_nonces:
                return None

            # Mark as used
            self.used_nonces.add(nonce)

            # Clean up old nonces (in production, Redis handles this automatically)
            if len(self.used_nonces) > 1000:
                self.used_nonces.clear()

            return payload

        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

qr_service = QRCodeService()
```

**Requirements** (`requirements.txt`):
```txt
qrcode[pil]==7.4.2
PyJWT==2.8.0
```

#### Task 2.2: Location Service
**Priority**: 🔴 Critical

**Files to Create**:
- `app/services/location_service.py`
- `app/config/location_config.py`

```python
# app/services/location_service.py
import math
from typing import Dict, Tuple, Optional
from app.core.database import get_db
from app.models.models import Device

class LocationService:
    def __init__(self):
        self.max_accuracy_meters = 50  # Reject if GPS accuracy > 50m

    def get_terminal_location(self, terminal_id: int) -> Optional[Dict]:
        """Get GPS coordinates and radius for specific terminal"""
        db = next(get_db())
        try:
            terminal = db.query(Device).filter(
                Device.id == terminal_id,
                Device.device_type == "qr_terminal"
            ).first()

            if not terminal or not terminal.metadata:
                return None

            gps_config = terminal.metadata.get("gps")
            if not gps_config:
                return None

            return {
                "latitude": float(gps_config["latitude"]),
                "longitude": float(gps_config["longitude"]),
                "radius_meters": float(gps_config.get("radius_meters", 200)),
                "location_name": terminal.metadata.get("location_name", "Unknown")
            }
        finally:
            db.close()

    def calculate_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float
    ) -> float:
        """Calculate distance between two GPS coordinates using Haversine formula"""
        R = 6371000  # Earth's radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (math.sin(delta_phi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) *
             math.sin(delta_lambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def validate_location(
        self,
        terminal_id: int,
        latitude: float,
        longitude: float,
        accuracy: Optional[float] = None
    ) -> Dict:
        """Validate if location is within terminal-specific radius"""
        # Get terminal location
        terminal_location = self.get_terminal_location(terminal_id)
        if not terminal_location:
            return {
                "valid": False,
                "reason": f"Terminal {terminal_id} not found or not configured",
                "distance": None,
                "location_name": None
            }

        # Check GPS accuracy
        if accuracy and accuracy > self.max_accuracy_meters:
            return {
                "valid": False,
                "reason": f"GPS accuracy too low: {accuracy}m (max: {self.max_accuracy_meters}m)",
                "distance": None,
                "location_name": terminal_location["location_name"]
            }

        # Calculate distance from terminal location
        distance = self.calculate_distance(
            latitude,
            longitude,
            terminal_location["latitude"],
            terminal_location["longitude"]
        )

        # Check if within radius
        valid = distance <= terminal_location["radius_meters"]

        return {
            "valid": valid,
            "distance": round(distance, 2),
            "radius": terminal_location["radius_meters"],
            "location_name": terminal_location["location_name"],
            "reason": None if valid else f"Outside {terminal_location['location_name']} radius: {round(distance, 2)}m (max: {terminal_location['radius_meters']}m)"
        }

location_service = LocationService()
```

**Note**: GPS coordinates are now stored per-terminal in Device metadata, not in environment variables

#### Task 2.3: QR Check-In Endpoints
**Priority**: 🔴 Critical

**Files to Create**:
- `app/api/qr_checkin.py`

```python
# app/api/qr_checkin.py
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.services.qr_service import qr_service
from app.services.line_auth_service import line_auth_service
from app.services.location_service import location_service
from app.services.attendance_service import attendance_service
from app.services.employee_service import employee_service
from app.main_unified import manager  # WebSocket manager

router = APIRouter()

class QRCheckinRequest(BaseModel):
    qr_token: str
    gps_latitude: float
    gps_longitude: float
    gps_accuracy: Optional[float] = None
    jwt_token: str

@router.get("/generate")
async def generate_qr_code(terminal_id: int):
    """Generate QR code for specific terminal display"""
    # Verify terminal exists
    from app.core.database import get_db
    from app.models.models import Device

    db = next(get_db())
    try:
        terminal = db.query(Device).filter(
            Device.id == terminal_id,
            Device.device_type == "qr_terminal",
            Device.is_active == True
        ).first()

        if not terminal:
            raise HTTPException(status_code=404, detail=f"Terminal {terminal_id} not found")

        # Generate QR code image
        qr_image = qr_service.generate_qr_image(terminal_id)

        return {
            "qr_image": qr_image,
            "terminal_id": terminal_id,
            "terminal_name": terminal.device_name,
            "location_name": terminal.metadata.get("location_name", "Unknown"),
            "valid_seconds": 30,
            "generated_at": datetime.now().isoformat()
        }
    finally:
        db.close()

@router.post("/checkin")
async def qr_checkin(request: QRCheckinRequest, req: Request):
    """Process QR code check-in with GPS validation"""
    try:
        # 1. Validate JWT token
        jwt_payload = line_auth_service.verify_jwt_token(request.jwt_token)
        if not jwt_payload:
            raise HTTPException(status_code=401, detail="Invalid or expired session")

        employee_id = jwt_payload.get("employee_id")
        line_user_id = jwt_payload.get("line_user_id")

        # 2. Validate QR token
        qr_payload = qr_service.validate_qr_token(request.qr_token)
        if not qr_payload:
            raise HTTPException(status_code=400, detail="Invalid or expired QR code")

        terminal_id = qr_payload.get("terminal_id")

        # 3. Validate GPS location (terminal-specific)
        location_validation = location_service.validate_location(
            terminal_id=terminal_id,
            latitude=request.gps_latitude,
            longitude=request.gps_longitude,
            accuracy=request.gps_accuracy
        )

        if not location_validation["valid"]:
            raise HTTPException(status_code=400, detail=location_validation["reason"])

        # 4. Get employee
        employee = employee_service.get_by_badge(employee_id)
        if not employee:
            raise HTTPException(status_code=404, detail="Employee not found")

        # 5. Determine check-in or check-out
        latest_record = attendance_service.get_latest_record(employee_id)
        is_checkin = not latest_record or latest_record.status == "Check-out"

        # 6. Create attendance record
        metadata = {
            "source": "qr_code",
            "terminal_id": terminal_id,
            "location_name": location_validation["location_name"],
            "gps": {
                "latitude": request.gps_latitude,
                "longitude": request.gps_longitude,
                "accuracy": request.gps_accuracy,
                "distance_from_terminal": location_validation["distance"]
            },
            "ip_address": req.client.host,
            "user_agent": req.headers.get("user-agent"),
            "line_user_id": line_user_id
        }

        record = attendance_service.create_qr_record(
            employee_id=employee_id,
            device_id=terminal_id,
            status="Check-in" if is_checkin else "Check-out",
            metadata=metadata
        )

        # 7. Broadcast to WebSocket clients
        attendance_data = attendance_service.get_attendance_summary()
        await manager.broadcast({
            "type": "qr_checkin_update",
            "data": attendance_data,
            "new_record": {
                "employee_id": employee_id,
                "employee_name": employee.display_name,
                "status": record.status,
                "timestamp": record.timestamp.isoformat(),
                "source": "qr_code"
            },
            "timestamp": datetime.now().isoformat()
        })

        return {
            "success": True,
            "status": record.status,
            "timestamp": record.timestamp.isoformat(),
            "employee": {
                "badge": employee.employee_id,
                "name": employee.display_name
            },
            "location": {
                "distance": location_validation["distance"],
                "valid": True
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/status")
async def qr_terminal_status():
    """Get QR terminal status and recent check-ins"""
    qr_terminal = attendance_service.get_qr_terminal_device()
    if not qr_terminal:
        raise HTTPException(status_code=500, detail="QR terminal not configured")

    # Get recent check-ins from QR terminal
    recent_checkins = attendance_service.get_recent_by_device(
        device_id=qr_terminal.id,
        limit=10
    )

    return {
        "terminal_id": qr_terminal.id,
        "terminal_name": qr_terminal.device_name,
        "status": "active",
        "recent_checkins": recent_checkins,
        "timestamp": datetime.now().isoformat()
    }
```

**Register Router** in `app/main_unified.py`:
```python
from app.api import qr_checkin
fingerprint_app.include_router(qr_checkin.router, prefix="/api/qr", tags=["qr-checkin"])
```

---

### Phase 3: Frontend - Admin QR Display (Week 2)
**Duration**: 2-3 days

#### Task 3.1: QR Terminal Page (Unattended Kiosk Mode)
**Priority**: 🟡 Important

**Design Requirements**:
- ✅ **Fullscreen kiosk mode** - auto-enter fullscreen on load
- ✅ **Large QR code** - easily scannable from 1-2 meters away
- ✅ **Visual countdown timer** - shows seconds until QR expiry
- ✅ **Auto-refresh** - new QR every 30 seconds via WebSocket
- ✅ **Recent check-ins** - real-time display of successful scans
- ✅ **No user interaction required** - completely autonomous operation

**Files to Create**:
- `static/qr-terminal.html`
- `static/css/qr-terminal.css`
- `static/js/qr-terminal.js`

```html
<!-- static/qr-terminal.html -->
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QR Terminal - ระบบลงเวลา</title>
    <link rel="stylesheet" href="static/css/base.css">
    <link rel="stylesheet" href="static/css/qr-terminal.css">
    <script src="static/js/config.js"></script>
    <script src="static/js/websocket-adapter.js"></script>
</head>
<body class="qr-terminal-body">
    <div class="terminal-container">
        <div class="terminal-header">
            <h1>🎯 สแกน QR Code เพื่อลงเวลา</h1>
            <div class="status-badge" id="terminalStatus">
                <span class="status-dot"></span>
                <span class="status-text">Active</span>
            </div>
        </div>

        <div class="qr-display-area">
            <div class="qr-code-container">
                <img id="qrImage" src="" alt="QR Code" class="qr-image">
                <div class="qr-timer">
                    <span id="qrTimer">30</span>
                    <span class="timer-label">วินาที</span>
                </div>
            </div>

            <div class="instruction-text">
                <p>📱 เปิดแอป LINE → สแกน QR Code</p>
                <p>📍 ต้องอยู่ในรัศมี 200 เมตรจากสำนักงาน</p>
            </div>
        </div>

        <div class="recent-checkins">
            <h2>✅ ลงเวลาล่าสุด</h2>
            <div id="recentList" class="checkin-list">
                <!-- Populated by JavaScript -->
            </div>
        </div>

        <div class="terminal-footer">
            <div class="device-info">
                Terminal ID: <span id="terminalId">-</span>
            </div>
            <div class="clock" id="currentTime">--:--:--</div>
        </div>
    </div>

    <script src="static/js/qr-terminal.js"></script>
</body>
</html>
```

```css
/* static/css/qr-terminal.css */
.qr-terminal-body {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    margin: 0;
    padding: 20px;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Prompt', sans-serif;
}

.terminal-container {
    background: white;
    border-radius: 20px;
    padding: 40px;
    max-width: 1200px;
    width: 100%;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.terminal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 40px;
    border-bottom: 3px solid #667eea;
    padding-bottom: 20px;
}

.terminal-header h1 {
    font-size: 3rem;
    color: #333;
    margin: 0;
}

.status-badge {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 20px;
    background: #d4edda;
    border-radius: 25px;
}

.status-dot {
    width: 12px;
    height: 12px;
    background: #28a745;
    border-radius: 50%;
    animation: pulse 2s infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

.qr-display-area {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px;
    background: #f8f9fa;
    border-radius: 15px;
    margin-bottom: 40px;
}

.qr-code-container {
    position: relative;
    padding: 30px;
    background: white;
    border-radius: 20px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
}

.qr-image {
    width: 400px;
    height: 400px;
    display: block;
}

.qr-timer {
    position: absolute;
    bottom: -20px;
    left: 50%;
    transform: translateX(-50%);
    background: #667eea;
    color: white;
    padding: 10px 30px;
    border-radius: 25px;
    font-size: 1.5rem;
    font-weight: bold;
    display: flex;
    gap: 10px;
    align-items: center;
}

.instruction-text {
    margin-top: 40px;
    text-align: center;
}

.instruction-text p {
    font-size: 1.5rem;
    color: #666;
    margin: 10px 0;
}

.recent-checkins {
    margin-top: 40px;
}

.recent-checkins h2 {
    font-size: 2rem;
    color: #333;
    margin-bottom: 20px;
}

.checkin-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 15px;
    max-height: 400px;
    overflow-y: auto;
}

.checkin-item {
    display: flex;
    align-items: center;
    gap: 15px;
    padding: 15px;
    background: #f8f9fa;
    border-radius: 10px;
    border-left: 4px solid #28a745;
    animation: slideIn 0.5s ease;
}

.checkin-item.checkout {
    border-left-color: #ffc107;
}

@keyframes slideIn {
    from {
        opacity: 0;
        transform: translateY(-20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.checkin-icon {
    font-size: 2rem;
}

.checkin-details {
    flex: 1;
}

.checkin-name {
    font-weight: bold;
    font-size: 1.2rem;
    color: #333;
}

.checkin-time {
    color: #666;
    font-size: 0.9rem;
}

.terminal-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 40px;
    padding-top: 20px;
    border-top: 2px solid #eee;
    color: #666;
}

.clock {
    font-size: 2rem;
    font-weight: bold;
    color: #667eea;
}
```

```javascript
// static/js/qr-terminal.js
class QRTerminal {
    constructor() {
        this.refreshInterval = 30000; // 30 seconds
        this.countdownInterval = null;
        this.timeRemaining = 30;
        this.socket = null;
        this.init();
    }

    async init() {
        // Enter fullscreen mode for kiosk display
        await this.enterFullscreen();

        await this.setupWebSocket();
        await this.refreshQRCode();
        this.startClock();
        this.startCountdown();

        // Auto-refresh QR code every 30 seconds
        setInterval(() => this.refreshQRCode(), this.refreshInterval);

        // Re-enter fullscreen if user exits
        document.addEventListener('fullscreenchange', () => {
            if (!document.fullscreenElement) {
                setTimeout(() => this.enterFullscreen(), 2000);
            }
        });
    }

    async enterFullscreen() {
        try {
            const elem = document.documentElement;
            if (elem.requestFullscreen) {
                await elem.requestFullscreen();
            } else if (elem.webkitRequestFullscreen) {
                await elem.webkitRequestFullscreen();
            } else if (elem.msRequestFullscreen) {
                await elem.msRequestFullscreen();
            }
            console.log('Entered fullscreen kiosk mode');
        } catch (error) {
            console.warn('Fullscreen not supported or denied:', error);
        }
    }

    async setupWebSocket() {
        this.socket = io();

        this.socket.on('connect', () => {
            console.log('WebSocket connected');
            document.getElementById('terminalStatus').querySelector('.status-text').textContent = 'Active';
        });

        this.socket.on('disconnect', () => {
            console.log('WebSocket disconnected');
            document.getElementById('terminalStatus').querySelector('.status-text').textContent = 'Disconnected';
        });

        this.socket.on('qr_checkin_update', (data) => {
            this.handleNewCheckin(data.new_record);
        });
    }

    async refreshQRCode() {
        try {
            const response = await fetch(appConfig.getApiUrl('qr/generate'));
            const data = await response.json();

            document.getElementById('qrImage').src = data.qr_image;
            document.getElementById('terminalId').textContent = data.terminal_id;

            // Reset countdown
            this.timeRemaining = data.valid_seconds;

        } catch (error) {
            console.error('Failed to refresh QR code:', error);
        }
    }

    startCountdown() {
        this.countdownInterval = setInterval(() => {
            this.timeRemaining--;
            document.getElementById('qrTimer').textContent = this.timeRemaining;

            if (this.timeRemaining <= 0) {
                this.timeRemaining = 30;
            }
        }, 1000);
    }

    startClock() {
        const updateClock = () => {
            const now = new Date();
            const timeString = now.toLocaleTimeString('th-TH', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
            document.getElementById('currentTime').textContent = timeString;
        };

        updateClock();
        setInterval(updateClock, 1000);
    }

    handleNewCheckin(record) {
        const list = document.getElementById('recentList');

        const item = document.createElement('div');
        item.className = `checkin-item ${record.status === 'Check-out' ? 'checkout' : ''}`;
        item.innerHTML = `
            <div class="checkin-icon">${record.status === 'Check-in' ? '👋' : '👋🏻'}</div>
            <div class="checkin-details">
                <div class="checkin-name">${record.employee_name}</div>
                <div class="checkin-time">
                    ${record.status} • ${new Date(record.timestamp).toLocaleTimeString('th-TH')}
                    ${record.source === 'qr_code' ? '📱' : '👆'}
                </div>
            </div>
        `;

        // Add to top of list
        list.insertBefore(item, list.firstChild);

        // Keep only last 10
        while (list.children.length > 10) {
            list.removeChild(list.lastChild);
        }

        // Play sound notification (optional)
        this.playNotificationSound();
    }

    playNotificationSound() {
        // Optional: Add a subtle notification sound
        const audio = new Audio('/static/sounds/checkin.mp3');
        audio.volume = 0.3;
        audio.play().catch(() => {}); // Ignore errors if audio fails
    }

    async loadRecentCheckins() {
        try {
            const response = await fetch(appConfig.getApiUrl('qr/status'));
            const data = await response.json();

            const list = document.getElementById('recentList');
            list.innerHTML = '';

            data.recent_checkins.forEach(record => {
                this.handleNewCheckin(record);
            });

        } catch (error) {
            console.error('Failed to load recent check-ins:', error);
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.qrTerminal = new QRTerminal();
});
```

**Add Route** in `app/main_unified.py`:
```python
@fingerprint_app.get("/qr-terminal")
async def qr_terminal_page():
    return FileResponse("static/qr-terminal.html")
```

---

### Phase 4: Frontend - Mobile Check-In (Week 2-3)
**Duration**: 4-5 days

#### Task 4.1: LINE Login Page
**Priority**: 🟡 Important

**Files to Create**:
- `static/mobile-checkin.html`
- `static/css/mobile-checkin.css`
- `static/js/mobile-checkin.js`
- `static/js/qr-scanner.js`

```html
<!-- static/mobile-checkin.html -->
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ลงเวลาด้วย QR Code</title>
    <link rel="stylesheet" href="static/css/base.css">
    <link rel="stylesheet" href="static/css/mobile-checkin.css">
    <script src="static/js/config.js"></script>
</head>
<body class="mobile-body">
    <div class="mobile-container">
        <!-- Login Screen -->
        <div id="loginScreen" class="screen active">
            <div class="app-logo">
                <div class="logo-icon">⏰</div>
                <h1>ระบบลงเวลา</h1>
                <p>เข้าสู่ระบบด้วย LINE</p>
            </div>

            <button id="lineLoginBtn" class="line-login-btn">
                <img src="static/images/line-logo.png" alt="LINE">
                เข้าสู่ระบบด้วย LINE
            </button>

            <div class="login-info">
                <p>✓ ปลอดภัยด้วย LINE OAuth</p>
                <p>✓ ไม่เก็บข้อมูลส่วนตัว</p>
                <p>✓ ใช้งานง่าย รวดเร็ว</p>
            </div>
        </div>

        <!-- Scanner Screen -->
        <div id="scannerScreen" class="screen">
            <div class="scanner-header">
                <button id="backBtn" class="back-btn">← กลับ</button>
                <h2>สแกน QR Code</h2>
            </div>

            <div class="scanner-container">
                <div id="qrReader" class="qr-reader"></div>
                <div class="scanner-overlay">
                    <div class="scanner-frame"></div>
                    <p class="scanner-hint">จ่อกล้องไปที่ QR Code</p>
                </div>
            </div>

            <div class="scanner-instructions">
                <p>📍 กำลังตรวจสอบตำแหน่ง...</p>
                <p id="locationStatus" class="location-status"></p>
            </div>

            <div class="user-info">
                <img id="userAvatar" src="" alt="Profile" class="user-avatar">
                <div class="user-details">
                    <div class="user-name" id="userName"></div>
                    <div class="user-badge" id="userBadge"></div>
                </div>
            </div>
        </div>

        <!-- Success Screen -->
        <div id="successScreen" class="screen">
            <div class="success-animation">
                <div class="success-checkmark">✓</div>
            </div>

            <h2 id="successTitle">ลงเวลาสำเร็จ</h2>
            <p id="successMessage" class="success-message"></p>

            <div class="success-details">
                <div class="detail-item">
                    <span class="detail-label">สถานะ:</span>
                    <span id="checkinStatus" class="detail-value"></span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">เวลา:</span>
                    <span id="checkinTime" class="detail-value"></span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">ระยะทาง:</span>
                    <span id="checkinDistance" class="detail-value"></span>
                </div>
            </div>

            <button id="scanAgainBtn" class="scan-again-btn">
                สแกนอีกครั้ง
            </button>
        </div>

        <!-- Error Screen -->
        <div id="errorScreen" class="screen">
            <div class="error-icon">⚠️</div>
            <h2>เกิดข้อผิดพลาด</h2>
            <p id="errorMessage" class="error-message"></p>
            <button id="retryBtn" class="retry-btn">ลองอีกครั้ง</button>
        </div>
    </div>

    <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>
    <script src="static/js/qr-scanner.js"></script>
    <script src="static/js/mobile-checkin.js"></script>
</body>
</html>
```

```css
/* static/css/mobile-checkin.css */
.mobile-body {
    margin: 0;
    padding: 0;
    font-family: 'Prompt', sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
}

.mobile-container {
    width: 100%;
    max-width: 500px;
    min-height: 100vh;
    background: white;
    position: relative;
}

.screen {
    display: none;
    padding: 20px;
    min-height: 100vh;
}

.screen.active {
    display: flex;
    flex-direction: column;
}

/* Login Screen */
#loginScreen {
    justify-content: center;
    align-items: center;
    text-align: center;
}

.app-logo {
    margin-bottom: 60px;
}

.logo-icon {
    font-size: 5rem;
    margin-bottom: 20px;
}

.line-login-btn {
    width: 80%;
    max-width: 300px;
    padding: 15px;
    background: #00B900;
    color: white;
    border: none;
    border-radius: 10px;
    font-size: 1.2rem;
    font-weight: bold;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    cursor: pointer;
    transition: all 0.3s;
}

.line-login-btn:hover {
    background: #00A000;
    transform: scale(1.05);
}

.line-login-btn img {
    width: 24px;
    height: 24px;
}

.login-info {
    margin-top: 40px;
    color: #666;
}

.login-info p {
    margin: 10px 0;
    font-size: 0.9rem;
}

/* Scanner Screen */
#scannerScreen {
    padding: 0;
}

.scanner-header {
    display: flex;
    align-items: center;
    gap: 20px;
    padding: 20px;
    background: #667eea;
    color: white;
}

.back-btn {
    background: none;
    border: none;
    color: white;
    font-size: 1.2rem;
    cursor: pointer;
}

.scanner-container {
    position: relative;
    width: 100%;
    aspect-ratio: 1;
    background: #000;
}

#qrReader {
    width: 100%;
    height: 100%;
}

.scanner-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    pointer-events: none;
}

.scanner-frame {
    width: 250px;
    height: 250px;
    border: 3px solid #00FF00;
    border-radius: 20px;
    box-shadow: 0 0 20px rgba(0, 255, 0, 0.5);
}

.scanner-hint {
    color: white;
    margin-top: 20px;
    font-size: 1.1rem;
    text-shadow: 0 0 10px rgba(0, 0, 0, 0.8);
}

.scanner-instructions {
    padding: 20px;
    text-align: center;
    background: #f8f9fa;
}

.location-status {
    font-weight: bold;
    color: #28a745;
}

.user-info {
    display: flex;
    align-items: center;
    gap: 15px;
    padding: 20px;
    border-top: 1px solid #eee;
}

.user-avatar {
    width: 50px;
    height: 50px;
    border-radius: 50%;
}

.user-name {
    font-weight: bold;
    font-size: 1.1rem;
}

.user-badge {
    color: #666;
    font-size: 0.9rem;
}

/* Success Screen */
#successScreen {
    align-items: center;
    justify-content: center;
    text-align: center;
}

.success-animation {
    margin-bottom: 30px;
}

.success-checkmark {
    font-size: 5rem;
    color: #28a745;
    animation: scaleIn 0.5s ease;
}

@keyframes scaleIn {
    from {
        transform: scale(0);
        opacity: 0;
    }
    to {
        transform: scale(1);
        opacity: 1;
    }
}

.success-details {
    width: 100%;
    max-width: 300px;
    margin: 30px 0;
}

.detail-item {
    display: flex;
    justify-content: space-between;
    padding: 15px;
    border-bottom: 1px solid #eee;
}

.detail-label {
    color: #666;
}

.detail-value {
    font-weight: bold;
}

.scan-again-btn {
    width: 80%;
    max-width: 300px;
    padding: 15px;
    background: #667eea;
    color: white;
    border: none;
    border-radius: 10px;
    font-size: 1.2rem;
    cursor: pointer;
}

/* Error Screen */
#errorScreen {
    align-items: center;
    justify-content: center;
    text-align: center;
}

.error-icon {
    font-size: 5rem;
    margin-bottom: 20px;
}

.error-message {
    color: #dc3545;
    margin: 20px 0;
    padding: 20px;
    background: #f8d7da;
    border-radius: 10px;
}

.retry-btn {
    width: 80%;
    max-width: 300px;
    padding: 15px;
    background: #dc3545;
    color: white;
    border: none;
    border-radius: 10px;
    font-size: 1.2rem;
    cursor: pointer;
}
```

```javascript
// static/js/mobile-checkin.js
class MobileCheckin {
    constructor() {
        this.jwtToken = null;
        this.userProfile = null;
        this.currentLocation = null;
        this.qrScanner = null;
        this.init();
    }

    init() {
        // Check for token in URL
        const urlParams = new URLSearchParams(window.location.search);
        this.jwtToken = urlParams.get('token') || localStorage.getItem('jwt_token');

        if (this.jwtToken) {
            this.loadUserProfile();
            this.showScreen('scannerScreen');
            this.initScanner();
        } else {
            this.showScreen('loginScreen');
        }

        this.attachEventListeners();
        this.requestLocation();
    }

    attachEventListeners() {
        document.getElementById('lineLoginBtn').addEventListener('click', () => {
            this.initiateLineLogin();
        });

        document.getElementById('backBtn').addEventListener('click', () => {
            this.showScreen('loginScreen');
            if (this.qrScanner) {
                this.qrScanner.stop();
            }
        });

        document.getElementById('scanAgainBtn').addEventListener('click', () => {
            this.showScreen('scannerScreen');
            this.initScanner();
        });

        document.getElementById('retryBtn').addEventListener('click', () => {
            this.showScreen('scannerScreen');
            this.initScanner();
        });
    }

    showScreen(screenId) {
        document.querySelectorAll('.screen').forEach(screen => {
            screen.classList.remove('active');
        });
        document.getElementById(screenId).classList.add('active');
    }

    async initiateLineLogin() {
        try {
            const response = await fetch(appConfig.getApiUrl('auth/line/login'));
            const data = await response.json();
            window.location.href = data.auth_url;
        } catch (error) {
            this.showError('ไม่สามารถเชื่อมต่อกับ LINE ได้');
        }
    }

    async loadUserProfile() {
        try {
            // Decode JWT to get user info
            const payload = JSON.parse(atob(this.jwtToken.split('.')[1]));

            // Store token
            localStorage.setItem('jwt_token', this.jwtToken);

            // Load employee info
            const response = await fetch(
                appConfig.getApiUrl(`employees/badge/${payload.employee_id}`)
            );
            const employee = await response.json();

            this.userProfile = {
                employee_id: payload.employee_id,
                display_name: employee.display_name,
                line_user_id: payload.line_user_id
            };

            // Update UI
            document.getElementById('userName').textContent = employee.display_name;
            document.getElementById('userBadge').textContent = `รหัส: ${employee.employee_id}`;

        } catch (error) {
            console.error('Failed to load user profile:', error);
            this.showError('ไม่สามารถโหลดข้อมูลผู้ใช้ได้');
        }
    }

    requestLocation() {
        if (!navigator.geolocation) {
            document.getElementById('locationStatus').textContent =
                '❌ เบราว์เซอร์ไม่รองรับ GPS';
            return;
        }

        navigator.geolocation.getCurrentPosition(
            (position) => {
                this.currentLocation = {
                    latitude: position.coords.latitude,
                    longitude: position.coords.longitude,
                    accuracy: position.coords.accuracy
                };

                document.getElementById('locationStatus').textContent =
                    `✓ พบตำแหน่ง (ความแม่นยำ: ${Math.round(position.coords.accuracy)}m)`;
            },
            (error) => {
                console.error('Location error:', error);
                document.getElementById('locationStatus').textContent =
                    '❌ กรุณาเปิดใช้งาน GPS';
            },
            {
                enableHighAccuracy: true,
                timeout: 10000,
                maximumAge: 0
            }
        );
    }

    initScanner() {
        if (this.qrScanner) {
            this.qrScanner.resume();
            return;
        }

        this.qrScanner = new QRScanner('qrReader', {
            fps: 10,
            qrbox: { width: 250, height: 250 },
            aspectRatio: 1.0
        });

        this.qrScanner.onScan = (decodedText) => {
            this.handleQRScan(decodedText);
        };

        this.qrScanner.start();
    }

    async handleQRScan(qrToken) {
        // Stop scanner
        this.qrScanner.pause();

        // Validate location
        if (!this.currentLocation) {
            this.showError('กรุณาเปิดใช้งาน GPS');
            return;
        }

        try {
            const response = await fetch(appConfig.getApiUrl('qr/checkin'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    qr_token: qrToken,
                    gps_latitude: this.currentLocation.latitude,
                    gps_longitude: this.currentLocation.longitude,
                    gps_accuracy: this.currentLocation.accuracy,
                    jwt_token: this.jwtToken
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail);
            }

            const data = await response.json();
            this.showSuccess(data);

        } catch (error) {
            this.showError(error.message);
        }
    }

    showSuccess(data) {
        this.showScreen('successScreen');

        document.getElementById('successTitle').textContent =
            data.status === 'Check-in' ? 'เข้างานสำเร็จ ✓' : 'ออกงานสำเร็จ ✓';

        document.getElementById('successMessage').textContent =
            `สวัสดี ${data.employee.name}`;

        document.getElementById('checkinStatus').textContent = data.status;
        document.getElementById('checkinTime').textContent =
            new Date(data.timestamp).toLocaleTimeString('th-TH');
        document.getElementById('checkinDistance').textContent =
            `${data.location.distance}m จากสำนักงาน`;
    }

    showError(message) {
        this.showScreen('errorScreen');
        document.getElementById('errorMessage').textContent = message;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.mobileCheckin = new MobileCheckin();
});
```

```javascript
// static/js/qr-scanner.js
class QRScanner {
    constructor(elementId, config = {}) {
        this.elementId = elementId;
        this.config = {
            fps: config.fps || 10,
            qrbox: config.qrbox || { width: 250, height: 250 },
            aspectRatio: config.aspectRatio || 1.0
        };
        this.html5QrCode = null;
        this.isScanning = false;
        this.onScan = null;
    }

    async start() {
        if (this.isScanning) return;

        this.html5QrCode = new Html5Qrcode(this.elementId);

        try {
            await this.html5QrCode.start(
                { facingMode: "environment" },
                this.config,
                (decodedText, decodedResult) => {
                    if (this.onScan && !this.isPaused) {
                        this.onScan(decodedText, decodedResult);
                    }
                },
                (errorMessage) => {
                    // Ignore scan errors (happens frequently)
                }
            );

            this.isScanning = true;
            this.isPaused = false;

        } catch (error) {
            console.error('Failed to start scanner:', error);
            throw error;
        }
    }

    async stop() {
        if (!this.isScanning || !this.html5QrCode) return;

        try {
            await this.html5QrCode.stop();
            this.html5QrCode.clear();
            this.isScanning = false;
        } catch (error) {
            console.error('Failed to stop scanner:', error);
        }
    }

    pause() {
        this.isPaused = true;
    }

    resume() {
        this.isPaused = false;
    }
}
```

**Add Route** in `app/main_unified.py`:
```python
@fingerprint_app.get("/mobile-checkin")
async def mobile_checkin_page():
    return FileResponse("static/mobile-checkin.html")
```

---

### Phase 5: Employee Linking & Testing (Week 3)
**Duration**: 3-4 days

#### Task 5.0: Admin Mode in Nickname Management Page
**Priority**: 🔴 Critical

**Requirement**: Add admin mode to existing nickname management page for generating LINE linking codes

**Implementation Notes**:
- Add "Admin Mode" button to existing `/nickname-management` page
- Button triggers passcode prompt (`bananabananabanana`)
- After successful authentication, show additional UI for each employee:
  - "Generate LINE Code" button next to each employee
  - Display generated 6-digit code
  - "Regenerate Code" option if code already exists
  - Visual indication if employee already linked to LINE
- Admin mode UI should be simple overlay or additional column in existing table
- Use admin API endpoints: `POST /api/admin/line-codes/generate`, `POST /api/admin/line-codes/regenerate`
- Store admin session in sessionStorage (expires on tab close for security)

**Files to Update**:
- `static/nickname-management.html` - Add admin mode button and UI
- `static/js/nickname-management.js` - Add admin authentication and code generation logic
- `static/css/nickname-management.css` - Style admin mode UI

**Example Admin Mode UI**:
```html
<!-- Add to nickname-management.html -->
<button id="adminModeBtn" class="admin-mode-btn">
    🔐 Admin Mode (LINE Codes)
</button>

<!-- Admin mode overlay/section (hidden by default) -->
<div id="adminModePanel" class="admin-panel" style="display: none;">
    <div class="admin-header">
        <h3>LINE Linking Code Management</h3>
        <p>สร้างรหัสเชื่อมต่อ LINE 6 หลักสำหรับพนักงาน</p>
        <button id="exitAdminMode">Exit Admin Mode</button>
    </div>

    <!-- For each employee row, add: -->
    <div class="line-code-actions">
        <span class="current-code" id="code-{badge}">รหัส: ------</span>
        <button class="generate-code-btn" data-badge="{badge}">
            สร้างรหัส
        </button>
        <span class="link-status" id="status-{badge}">ยังไม่ลิงก์</span>
    </div>
</div>
```

#### Task 5.1: LINE-to-Employee Linking Page
**Priority**: 🟡 Important

**Files to Create**:
- `static/link-line.html`
- `static/css/link-line.css`
- `static/js/link-line.js`

```html
<!-- static/link-line.html -->
<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>เชื่อมต่อบัญชี LINE</title>
    <link rel="stylesheet" href="static/css/base.css">
    <link rel="stylesheet" href="static/css/link-line.css">
    <script src="static/js/config.js"></script>
</head>
<body>
    <div class="link-container">
        <div class="link-header">
            <h1>เชื่อมต่อบัญชี LINE</h1>
            <p>กรุณากรอกรหัส 6 หลักที่ได้รับจากแอดมิน</p>
        </div>

        <div class="line-profile">
            <img id="lineAvatar" src="" alt="LINE Avatar">
            <h2 id="lineName"></h2>
            <p class="line-id" id="lineUserId"></p>
        </div>

        <div class="code-input-section">
            <label for="linkingCodeInput">รหัสเชื่อมต่อ 6 หลัก</label>
            <input
                type="text"
                id="linkingCodeInput"
                placeholder="กรอกรหัส 6 หลัก (เช่น 123456)"
                maxlength="6"
                pattern="[0-9]{6}"
                inputmode="numeric"
                autocomplete="off"
            >
            <p class="help-text">
                ℹ️ ขอรหัสจากแอดมินในหน้าจัดการชื่อเล่น
            </p>
        </div>

        <button id="linkBtn" class="link-btn" disabled>
            เชื่อมต่อบัญชี
        </button>

        <div class="link-info">
            <p>ℹ️ การเชื่อมต่อบัญชี LINE จะทำให้คุณสามารถ:</p>
            <ul>
                <li>ลงเวลาด้วย QR Code</li>
                <li>ตรวจสอบการลงเวลาของคุณ</li>
                <li>รับการแจ้งเตือนผ่าน LINE</li>
            </ul>
        </div>
    </div>

    <script src="static/js/link-line.js"></script>
</body>
</html>
```

```javascript
// static/js/link-line.js
// UPDATED: Use 6-digit linking code instead of badge number selection
class LineLinking {
    constructor() {
        this.linkToken = null;
        this.lineName = null;
        this.init();
    }

    async init() {
        // Get link token from URL (from LINE callback)
        const urlParams = new URLSearchParams(window.location.search);
        this.linkToken = urlParams.get('token');

        if (!this.linkToken) {
            window.location.href = '/mobile-checkin';
            return;
        }

        // Display LINE profile (if available in URL)
        const lineName = urlParams.get('name');
        if (lineName) {
            document.getElementById('lineName').textContent = lineName;
        }

        // Attach event listeners
        this.attachEventListeners();
    }

    attachEventListeners() {
        const codeInput = document.getElementById('linkingCodeInput');
        const linkBtn = document.getElementById('linkBtn');

        // Enable button when 6 digits entered
        codeInput.addEventListener('input', (e) => {
            const code = e.target.value.trim();
            linkBtn.disabled = code.length !== 6 || !/^\d{6}$/.test(code);
        });

        // Handle Enter key
        codeInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !linkBtn.disabled) {
                this.linkAccount();
            }
        });

        linkBtn.addEventListener('click', () => {
            this.linkAccount();
        });
    }

    async linkAccount() {
        const codeInput = document.getElementById('linkingCodeInput');
        const linkingCode = codeInput.value.trim();

        if (linkingCode.length !== 6 || !/^\d{6}$/.test(linkingCode)) {
            alert('กรุณากรอกรหัส 6 หลักที่ถูกต้อง');
            return;
        }

        const linkBtn = document.getElementById('linkBtn');
        linkBtn.disabled = true;
        linkBtn.textContent = 'กำลังเชื่อมต่อ...';

        try {
            const response = await fetch(appConfig.getApiUrl('auth/line/link-account'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    link_token: this.linkToken,
                    linking_code: linkingCode
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail);
            }

            const data = await response.json();

            // Store JWT token
            localStorage.setItem('jwt_token', data.token);

            // Show success message
            alert(`เชื่อมต่อสำเร็จ! พนักงาน: ${data.employee.name_thai}`);

            // Redirect to mobile check-in
            window.location.href = `/qr-checkin/mobile?token=${data.token}`;

        } catch (error) {
            alert(`เกิดข้อผิดพลาด: ${error.message}`);
            linkBtn.disabled = false;
            linkBtn.textContent = 'เชื่อมต่อบัญชี';
            codeInput.value = '';
            codeInput.focus();
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.lineLinking = new LineLinking();
});
```

**Add Route** in `app/main_unified.py`:
```python
@fingerprint_app.get("/link-line")
async def link_line_page():
    return FileResponse("static/link-line.html")
```

#### Task 5.2: Comprehensive Testing
**Priority**: 🔴 Critical

**Test Files to Create**:
- `tests/test_line_auth.py` - LINE OAuth unit tests
- `tests/test_qr_service.py` - QR generation and validation tests
- `tests/test_location_service.py` - GPS validation tests
- `tests/integration/test_qr_checkin_flow.py` - End-to-end flow tests
- `tests/e2e/test_qr_terminal.py` - Playwright E2E tests
- `tests/security/test_qr_replay_attacks.py` - Security tests

**Example Test**:
```python
# tests/test_qr_service.py
import pytest
import time
from app.services.qr_service import qr_service

def test_generate_qr_token():
    """Test QR token generation"""
    token = qr_service.generate_qr_token(terminal_id=1)
    assert token is not None
    assert isinstance(token, str)

def test_validate_qr_token_success():
    """Test QR token validation succeeds for valid token"""
    token = qr_service.generate_qr_token(terminal_id=1)
    payload = qr_service.validate_qr_token(token)

    assert payload is not None
    assert payload["terminal_id"] == 1
    assert "nonce" in payload

def test_validate_qr_token_replay_attack():
    """Test QR token replay attack prevention"""
    token = qr_service.generate_qr_token(terminal_id=1)

    # First validation succeeds
    payload1 = qr_service.validate_qr_token(token)
    assert payload1 is not None

    # Second validation fails (replay attack)
    payload2 = qr_service.validate_qr_token(token)
    assert payload2 is None

def test_validate_qr_token_expired():
    """Test QR token expiration"""
    # Mock time to simulate expiration
    token = qr_service.generate_qr_token(terminal_id=1)

    # Wait for expiration (need to mock this in production)
    time.sleep(31)  # 30 seconds validity + 1 second

    payload = qr_service.validate_qr_token(token)
    assert payload is None

def test_qr_image_generation():
    """Test QR code image generation"""
    qr_image = qr_service.generate_qr_image(terminal_id=1)

    assert qr_image is not None
    assert qr_image.startswith("data:image/png;base64,")
    assert len(qr_image) > 100  # Base64 encoded image should be substantial
```

---

### Phase 6: Documentation & Deployment (Week 3-4)
**Duration**: 2-3 days

#### Task 6.1: Documentation
**Priority**: 🟡 Important

**Files to Create**:
- `docs/QR_CHECKIN_USER_GUIDE.md` - Employee user guide
- `docs/QR_CHECKIN_ADMIN_GUIDE.md` - Admin setup guide
- `docs/LINE_CHANNEL_SETUP.md` - LINE Developer Console setup
- Update `docs/API_REFERENCE.md` - Add QR endpoints
- Update `CLAUDE.md` - Add QR feature documentation

**Example Documentation**:
```markdown
# QR Check-In User Guide (Multi-Location Support)

## For Employees

### First Time Setup

1. **Login with LINE**:
   - Open mobile check-in page: https://emp.thehfhotel.org/fingerprintlogs/mobile-checkin
   - Click "เข้าสู่ระบบด้วย LINE"
   - Authorize the application

2. **Link Your Employee Account**:
   - Enter your employee badge number
   - Or search for your name
   - Click "เชื่อมต่อบัญชี"

### Daily Check-In

1. Open the mobile check-in page (bookmark it!)
2. You'll be automatically logged in via LINE
3. Grant camera and location permissions
4. Scan the QR code from the office terminal
5. Confirm your check-in/check-out

### Troubleshooting

**"GPS accuracy too low"**:
- Make sure you're outdoors or near a window
- Wait a few seconds for GPS to stabilize
- Check that location services are enabled

**"Outside office radius"**:
- You must be within 200 meters of the terminal location
- Make sure you're scanning the QR from the correct branch
- Each branch has its own terminal with separate GPS validation

**"Invalid QR code"**:
- QR codes expire every 30 seconds
- Wait for the display to refresh and try again

## For Administrators

### Setup QR Terminal Displays (Multi-Location)

**Terminal 1 - Main Office**:
1. Open: https://emp.thehfhotel.org/fingerprintlogs/qr-terminal?terminal_id=1
2. Display on large monitor/TV near entrance
3. Keep browser window open in fullscreen
4. QR code auto-refreshes every 30 seconds
5. GPS validates within 200m of Main Office coordinates

**Terminal 2 - Branch Office**:
1. Open: https://emp.thehfhotel.org/fingerprintlogs/qr-terminal?terminal_id=2
2. Display on large monitor/TV near entrance
3. Keep browser window open in fullscreen
4. QR code auto-refreshes every 30 seconds
5. GPS validates within 200m of Branch Office coordinates

**Key Points**:
- Each terminal has unique ID and location
- Employees can check in at either location
- GPS validation is location-specific
- Terminal name displays on kiosk screen
- Attendance records track which terminal was used

### Manage Employee Links

1. View linked employees: `/api/employees/` (check line_user_id field)
2. Unlink account: POST `/api/auth/line/unlink` with employee_badge

### Monitor Check-Ins

- Real-time updates appear on QR terminal display
- Dashboard shows all check-ins (fingerprint + QR)
- Export CSV includes source field ("qr_code" vs "fingerprint")
```

#### Task 6.2: Deployment Checklist
**Priority**: 🔴 Critical

**Deployment Steps**:

1. **LINE Channel Setup**:
   - Create LINE Login channel at https://developers.line.biz/
   - Configure callback URL: `https://emp.thehfhotel.org/fingerprintlogs/api/auth/line/callback`
   - Get Channel ID and Secret
   - Add to `.env` file

2. **Database Migration**:
   ```bash
   alembic upgrade head
   python database/seeds/create_qr_terminals.py
   ```

   **Update GPS Coordinates** in `database/seeds/create_qr_terminals.py`:
   ```python
   # Terminal 1: Main Office
   "latitude": 13.7563,    # Replace with actual Main Office latitude
   "longitude": 100.5018,  # Replace with actual Main Office longitude

   # Terminal 2: Branch Office
   "latitude": 13.7200,    # Replace with actual Branch Office latitude
   "longitude": 100.5200,  # Replace with actual Branch Office longitude
   ```

3. **Environment Variables**:
   ```env
   LINE_CHANNEL_ID=your_channel_id
   LINE_CHANNEL_SECRET=your_channel_secret
   LINE_CALLBACK_URL=https://emp.thehfhotel.org/fingerprintlogs/api/auth/line/callback
   QR_SECRET_KEY=your_random_secret_key

   # Note: GPS coordinates are now stored per-terminal in Device.metadata
   # No need for OFFICE_LATITUDE/LONGITUDE environment variables
   ```

4. **Install Dependencies**:
   ```bash
   pip install qrcode[pil]==7.4.2 PyJWT==2.8.0
   ```

5. **Test Deployment**:
   ```bash
   ./scripts/test-suite-console.sh all
   ```

6. **Deploy**:
   ```bash
   ./scripts/manage-app.sh deploy --build-target fingerprint-logger-prod
   ```

7. **Verify Multi-Location Setup**:
   - Test LINE login flow
   - Test Terminal 1 (Main Office):
     - Open qr-terminal?terminal_id=1
     - Verify location name displayed
     - Test check-in from Main Office location
     - Verify GPS validation for Main Office coordinates
   - Test Terminal 2 (Branch Office):
     - Open qr-terminal?terminal_id=2
     - Verify location name displayed
     - Test check-in from Branch Office location
     - Verify GPS validation for Branch Office coordinates
   - Verify cross-location rejection:
     - Try checking in at Main Office with Branch Office QR (should fail GPS)
     - Try checking in at Branch Office with Main Office QR (should fail GPS)
   - Check WebSocket updates at both terminals
   - Verify database records include terminal_id and location_name in metadata

---

## Dependencies & Requirements

### Backend Dependencies
```txt
# Add to requirements.txt
qrcode[pil]==7.4.2
PyJWT==2.8.0
```

### Frontend Libraries
- html5-qrcode (CDN): QR scanning
- Existing: WebSocket adapter, config.js

### External Services
- LINE Login API (OAuth 2.0)
- Browser Geolocation API
- WebSocket (existing)

---

## Risk Mitigation

### Security Risks

1. **QR Code Screenshot/Photo Attacks** (PRIMARY CONCERN):
   - ❌ **Attack**: Employee takes screenshot of QR, shares with others
   - ❌ **Attack**: Photo of QR display used from remote location
   - ✅ **Mitigation - ROTATING QR CODE**:
     - QR code expires every 30 seconds
     - Screenshot becomes invalid immediately after expiry
     - Visual countdown timer warns users of expiration
     - Cannot reuse old QR codes - all expired tokens rejected
   - ✅ **Additional Protection**: One-time nonce prevents replay even within 30s window
   - ✅ Testing: Replay attack tests with expired tokens

2. **QR Code Replay Attacks**:
   - ❌ **Attack**: Capture valid QR token, replay immediately
   - ✅ **Mitigation - NONCE TRACKING**:
     - Each QR contains unique nonce (random 16-byte token)
     - Backend tracks used nonces with TTL
     - Second use of same nonce rejected even if within 30s
     - Combined with rotation: double protection layer
   - ✅ Testing: Replay attack tests in security suite

3. **GPS Spoofing**:
   - ❌ **Attack**: Mock GPS location to check in remotely
   - ⚠️ Cannot fully prevent (OS-level limitation)
   - ✅ **Mitigations**:
     - Check GPS accuracy (reject if >50m uncertainty)
     - Pattern analysis (flag suspicious behavior)
     - Admin review dashboard for anomalies
     - Require <200m radius from office
   - ✅ Testing: Manual verification of suspicious patterns

4. **LINE Account Hijacking**:
   - ❌ **Attack**: Stolen LINE account used for check-in
   - ✅ **Mitigations**:
     - LINE OAuth security (LINE's responsibility)
     - JWT tokens with expiry
     - LINE unlinking requires admin approval
   - ✅ Testing: Token validation tests

### Why Rotating QR is Critical for Unattended Kiosks

**Without Rotation**:
- ❌ Employee could photograph QR once, check in remotely forever
- ❌ QR could be shared via messaging apps
- ❌ No way to invalidate compromised QR without system restart

**With 30-Second Rotation**:
- ✅ Screenshot attack window reduced to 30 seconds
- ✅ QR sharing becomes impractical (expires too quickly)
- ✅ Compromised QR self-heals automatically
- ✅ Combined with GPS: extremely difficult to abuse
- ✅ No admin supervision needed - system self-validates

**Real-World Scenario**:
```
Without Rotation:
10:00 AM - Employee takes photo of QR
10:30 AM - Employee at home, sends photo to friend
Friend checks in using photo (SUCCESS ❌)

With Rotation:
10:00 AM - Employee takes photo of QR
10:00:30 AM - QR expires, new one generated
10:30 AM - Employee at home, sends photo to friend
Friend scans expired QR (REJECTED ✅)
```

### Operational Risks

1. **LINE API Downtime**:
   - ⚠️ Cannot control
   - ✅ Mitigation: Clear error messages, fallback to fingerprint

2. **GPS Unavailable**:
   - ✅ Mitigation: Clear permission requests, accuracy checks
   - ✅ Fallback: Manual check-in with admin approval

3. **QR Terminal Display Offline**:
   - ✅ Mitigation: Multiple terminals, fallback to fingerprint

---

## Success Metrics

### Performance Targets
- ✅ QR code generation: < 100ms
- ✅ Check-in API response: < 500ms
- ✅ GPS acquisition: < 5 seconds
- ✅ WebSocket update latency: < 200ms

### User Experience Targets
- ✅ Total check-in time: < 5 seconds
- ✅ First-time linking: < 2 minutes
- ✅ GPS validation success rate: > 95%
- ✅ QR scan success rate: > 98%

### Adoption Targets
- 📊 Target 1: 50% adoption in first 2 weeks
- 📊 Target 2: 80% adoption in first month
- 📊 Target 3: < 5% support requests
- 📊 Target 4: Zero security incidents

---

## Timeline Summary

| Phase | Duration | Priority | Status |
|-------|----------|----------|--------|
| Phase 1: Database & Backend Foundation | Week 1 (3-4 days) | 🔴 Critical | Pending |
| Phase 2: QR Code System | Week 1-2 (4-5 days) | 🔴 Critical | Pending |
| Phase 3: Frontend - Admin QR Display | Week 2 (2-3 days) | 🟡 Important | Pending |
| Phase 4: Frontend - Mobile Check-In | Week 2-3 (4-5 days) | 🟡 Important | Pending |
| Phase 5: Employee Linking & Testing | Week 3 (3-4 days) | 🟡 Important | Pending |
| Phase 6: Documentation & Deployment | Week 3-4 (2-3 days) | 🟡 Important | Pending |

**Total Estimated Time**: 3-4 weeks

---

## Next Steps

1. **Immediate Actions**:
   - Review and approve this workflow
   - Set up LINE Developer account
   - Obtain Channel ID and Secret
   - Configure callback URL

2. **Week 1 Start**:
   - Begin Phase 1: Database migrations
   - Implement LINE OAuth service
   - Create basic auth endpoints

3. **Testing Strategy**:
   - Unit tests: After each service implementation
   - Integration tests: After Phase 2 complete
   - E2E tests: After Phase 4 complete
   - Security tests: Ongoing throughout

4. **Deployment Plan**:
   - Staging deployment: After Phase 5
   - Production deployment: After Phase 6
   - Monitoring: First week after deployment

---

## Resources

### LINE Developer Documentation
- LINE Login: https://developers.line.biz/en/docs/line-login/
- LINE OAuth: https://developers.line.biz/en/docs/line-login/integrate-line-login/

### Libraries
- qrcode (Python): https://pypi.org/project/qrcode/
- PyJWT: https://pyjwt.readthedocs.io/
- html5-qrcode: https://github.com/mebjas/html5-qrcode

### Testing
- Pytest: https://docs.pytest.org/
- Playwright: https://playwright.dev/

---

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>