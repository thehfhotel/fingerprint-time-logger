"""
LINE OAuth Service

Handles LINE authentication for QR check-in feature:
- Generate LINE authorization URL
- Exchange authorization code for access token
- Retrieve LINE user profile
- Create and verify JWT tokens for mobile sessions
- Mobile Safari compatibility with proper User-Agent handling

Adapted from loyalty-app OAuth service for employee account linking.
"""

import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from urllib.parse import urlencode

import jwt
import requests
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def _resolve_jwt_secret() -> str:
    """
    Resolve JWT_SECRET from environment, refusing to start in production
    when the env var is missing or set to the placeholder.
    """
    raw_secret = os.getenv("JWT_SECRET", "").strip()
    if not raw_secret or raw_secret == "your-secret-key-change-in-production":
        env_name = os.getenv("ENV", os.getenv("ENVIRONMENT", "production")).lower()
        # Treat pytest-controlled runs as dev-equivalent so test collection
        # works even when ENV/JWT_SECRET are unset in CI.
        _testing = (
            os.getenv("TESTING", "").lower() in ("1", "true", "yes")
            or bool(os.getenv("PYTEST_CURRENT_TEST"))
        )
        if env_name not in ("dev", "development", "local", "test") and not _testing:
            raise RuntimeError(
                "JWT_SECRET environment variable is required in production "
                "(must not be the placeholder)"
            )
        logger.warning(
            "JWT_SECRET not set — using insecure dev default. DO NOT use in production."
        )
        return "dev-jwt-secret-CHANGE-ME"
    return raw_secret


JWT_SECRET = _resolve_jwt_secret()


# LINE's in-app browser advertises itself with a `Line/<version>` product token
# tacked onto an otherwise ordinary WebKit/Chrome User-Agent, e.g.
#   Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) ... Line/13.5.0
# and the LIFF variant appends a marker: `... Line/13.5.0/IAB`.
#
# The lookbehind is the load-bearing part. A bare "line" substring turns up
# inside perfectly ordinary product names — Streamline/2.0, Airline/1.4,
# Baseline/9 — and treating one of those as LINE would strip
# disable_auto_login from a genuinely external browser, handing the user back
# the Safari cookie-jar bug described in generate_authorization_url(). So the
# token must be delimited on the left and followed by a version digit on the
# right; only a real `Line/<n>` product token qualifies.
#
# The match is deliberately case-insensitive even though LINE ships "Line/":
# the two failure directions are not symmetric. A missed detection merely
# leaves today's behaviour in place (login form inside LINE), while a false
# positive breaks the Access flow outright — and the boundary guard above,
# not letter case, is what actually keeps Streamline/Airline out.
_LINE_IN_APP_BROWSER_UA = re.compile(r"(?<![A-Za-z0-9])Line/\d", re.IGNORECASE)


def is_line_in_app_browser(user_agent: Optional[str]) -> bool:
    """
    True when this User-Agent is LINE's own in-app browser.

    Args:
        user_agent: Raw User-Agent header value, or None when unknown.

    Returns:
        False for None/empty. "Unknown" must count as NOT-LINE so callers
        that cannot supply a UA keep the conservative behaviour.
    """
    if not user_agent:
        return False
    return bool(_LINE_IN_APP_BROWSER_UA.search(user_agent))


class LineAuthService:
    """LINE OAuth 2.0 authentication service"""

    def __init__(self):
        self.channel_id = os.getenv("LINE_CHANNEL_ID", "")
        self.channel_secret = os.getenv("LINE_CHANNEL_SECRET", "")
        self.callback_url = os.getenv(
            "LINE_CALLBACK_URL",
            "http://localhost:5000/fingerprintlogs/api/auth/line/callback"
        )
        self.jwt_secret = JWT_SECRET
        self.jwt_expiry_hours = 24

        # LINE API endpoints
        self.line_auth_url = "https://access.line.me/oauth2/v2.1/authorize"
        self.line_token_url = "https://api.line.me/oauth2/v2.1/token"
        self.line_profile_url = "https://api.line.me/v2/profile"

        # State storage for CSRF protection (in-memory, 10-minute TTL)
        # Format: {state_token: (timestamp, redirect_hint)}
        self._state_storage: Dict[str, tuple] = {}
        self._state_ttl = 600  # 10 minutes
        # Protect _state_storage from concurrent mutation across threads.
        self._state_lock = threading.Lock()

    def generate_authorization_url(
        self,
        state: Optional[str] = None,
        redirect_hint: Optional[str] = None,
        prefer_qr: bool = False,
        user_agent: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Generate LINE OAuth authorization URL

        Args:
            state: Optional CSRF state token (generated if not provided)
            redirect_hint: Optional redirect destination hint (e.g., 'qr-scan-callback', 'mobile-checkin')
            prefer_qr: Open on the QR-code login screen. Only useful on a desktop
                browser, where the QR is scanned with the phone; on a phone it
                shows a code the user cannot scan from their own screen.
            user_agent: Raw User-Agent of the request that started the flow, used
                only to detect LINE's in-app browser (see disable_auto_login
                below). None means "unknown", which is treated as NOT LINE.

        Returns:
            Dict with 'auth_url' and 'state' keys
        """
        if not self.channel_id or self.channel_id == "your_channel_id":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LINE OAuth not configured - Channel ID required"
            )

        # Generate or use provided state for CSRF protection
        if not state:
            state = secrets.token_urlsafe(32)

        # Store state with timestamp and redirect_hint for TTL validation and callback routing
        with self._state_lock:
            self._state_storage[state] = (time.time(), redirect_hint)
        self._cleanup_expired_states()

        # Build authorization parameters
        params = {
            "response_type": "code",
            "client_id": self.channel_id,
            "redirect_uri": self.callback_url,
            "state": state,
            "scope": "profile openid email",  # Request profile and optional email

        }

        # switch_amr is deliberately never sent. It defaults to true, which
        # keeps the "Log in with email address" link on screen — this chooses
        # which method is offered FIRST and takes nothing away from anyone who
        # does have a password.
        if prefer_qr:
            # Staff LINE accounts are created on a phone and usually have no
            # email or password set, so the default form is one they cannot
            # complete ("unable to login", no way forward). On a desktop the QR
            # is scanned with the LINE app they already carry.
            params["initial_amr_display"] = "lineqr"

        # Keep the login inside the browser that started it — but ONLY for the
        # Cloudflare Access flow.
        #
        # With auto login (LINE's default) iOS hands off to the LINE app, which
        # completes the callback in its own LIFF in-app browser: a separate
        # cookie jar. An Access session created in Safari never sees it, so the
        # user returns to "Invalid session. Please try logging in again."
        #
        # Every OTHER caller — QR clock-in, mobile check-in, onboarding,
        # account linking, kiosk elevation — runs on the Cloudflare-BYPASSED
        # public paths. They hold no Access session to lose, and the app
        # hand-off is exactly the experience they want: tap, approve in LINE,
        # done. Disabling it for them broke QR check-in, which is why this is
        # scoped rather than global.
        #
        # Scoped once more, to non-LINE browsers only. Turning auto login off
        # makes LINE fall back to its web login FORM — and per the prefer_qr
        # note above, staff LINE accounts are made on a phone and typically
        # have no email or password set, so that form is a dead end. The people
        # on this path are 80+ housekeeping staff opening the app from a LINE
        # rich-menu button, i.e. already INSIDE LINE's in-app browser, where
        # the hand-off this flag guards against cannot happen: there is no
        # separate external browser session left holding the Access cookie.
        #
        # Unknown UA (None) counts as non-LINE and still gets the flag. That is
        # the safe direction — this carve-out can only ever remove the wall
        # inside LINE, never reintroduce the Safari bug for an unknown caller.
        if (redirect_hint or "").startswith("oidc:") and not is_line_in_app_browser(user_agent):
            params["disable_auto_login"] = "true"

        auth_url = f"{self.line_auth_url}?{urlencode(params)}"

        return {
            "auth_url": auth_url,
            "state": state
        }

    def validate_state(self, state: str) -> tuple[bool, Optional[str]]:
        """
        Validate CSRF state token

        Args:
            state: State token to validate

        Returns:
            Tuple of (is_valid, redirect_hint)
            - is_valid: True if state is valid and not expired
            - redirect_hint: Redirect destination hint if stored, None otherwise
        """
        self._cleanup_expired_states()

        with self._state_lock:
            if state not in self._state_storage:
                return (False, None)

            # Check if state has expired
            timestamp, redirect_hint = self._state_storage[state]
            if time.time() - timestamp > self._state_ttl:
                del self._state_storage[state]
                return (False, None)

            # Remove state after successful validation (one-time use)
            del self._state_storage[state]
            return (True, redirect_hint)

    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access token

        Args:
            code: Authorization code from LINE callback

        Returns:
            Dict with 'access_token', 'token_type', 'expires_in', 'refresh_token' (optional)

        Raises:
            HTTPException: If token exchange fails
        """
        if not self.channel_id or not self.channel_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="LINE OAuth not configured"
            )

        # Prepare token request
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.callback_url,
            "client_id": self.channel_id,
            "client_secret": self.channel_secret
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15"  # Mobile Safari compatibility
        }

        try:
            response = requests.post(
                self.line_token_url,
                data=data,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to exchange code for token: {str(e)}"
            )

    def get_user_profile(self, access_token: str) -> Dict[str, Any]:
        """
        Get LINE user profile using access token

        Args:
            access_token: LINE access token

        Returns:
            Dict with 'userId', 'displayName', 'pictureUrl', 'statusMessage'

        Raises:
            HTTPException: If profile retrieval fails
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15"  # Mobile Safari compatibility
        }

        try:
            response = requests.get(
                self.line_profile_url,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to get LINE profile: {str(e)}"
            )

    def create_jwt_token(
        self,
        line_user_id: str,
        employee_badge: Optional[str] = None,
        display_name: Optional[str] = None,
        picture_url: Optional[str] = None
    ) -> str:
        """
        Create JWT token for authenticated employee session

        Args:
            line_user_id: LINE user ID
            employee_badge: Employee badge number (None if not yet linked)
            display_name: LINE display name (optional, for pre-link sessions)
            picture_url: LINE profile picture URL (optional, for pre-link sessions)

        Returns:
            JWT token string
        """
        now = datetime.now(timezone.utc)
        exp = now + timedelta(hours=self.jwt_expiry_hours)

        payload = {
            "line_user_id": line_user_id,
            "employee_badge": employee_badge,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp())
        }

        # Include LINE profile data for pre-link sessions
        if display_name:
            payload["display_name"] = display_name
        if picture_url:
            payload["picture_url"] = picture_url

        token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")
        return token

    def verify_jwt_token(self, token: str) -> Dict[str, Any]:
        """
        Verify and decode JWT token

        Args:
            token: JWT token string

        Returns:
            Decoded token payload

        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

    def _cleanup_expired_states(self):
        """Remove expired state tokens from storage"""
        current_time = time.time()
        with self._state_lock:
            # Snapshot inside the lock to avoid concurrent-mutation iteration errors.
            expired_states = [
                state for state, (timestamp, _) in self._state_storage.items()
                if current_time - timestamp > self._state_ttl
            ]
            for state in expired_states:
                del self._state_storage[state]


# Singleton instance
line_auth_service = LineAuthService()
