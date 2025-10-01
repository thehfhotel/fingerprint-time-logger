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

import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from urllib.parse import urlencode

import jwt
import requests
from fastapi import HTTPException, status


class LineAuthService:
    """LINE OAuth 2.0 authentication service"""

    def __init__(self):
        self.channel_id = os.getenv("LINE_CHANNEL_ID", "")
        self.channel_secret = os.getenv("LINE_CHANNEL_SECRET", "")
        self.callback_url = os.getenv(
            "LINE_CALLBACK_URL",
            "http://localhost:5000/fingerprintlogs/api/auth/line/callback"
        )
        self.jwt_secret = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
        self.jwt_expiry_hours = 24

        # LINE API endpoints
        self.line_auth_url = "https://access.line.me/oauth2/v2.1/authorize"
        self.line_token_url = "https://api.line.me/oauth2/v2.1/token"
        self.line_profile_url = "https://api.line.me/v2/profile"

        # State storage for CSRF protection (in-memory, 10-minute TTL)
        self._state_storage: Dict[str, float] = {}
        self._state_ttl = 600  # 10 minutes

    def generate_authorization_url(self, state: Optional[str] = None) -> Dict[str, str]:
        """
        Generate LINE OAuth authorization URL

        Args:
            state: Optional CSRF state token (generated if not provided)

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

        # Store state with timestamp for TTL validation
        self._state_storage[state] = time.time()
        self._cleanup_expired_states()

        # Build authorization parameters
        params = {
            "response_type": "code",
            "client_id": self.channel_id,
            "redirect_uri": self.callback_url,
            "state": state,
            "scope": "profile openid email"  # Request profile and optional email
        }

        auth_url = f"{self.line_auth_url}?{urlencode(params)}"

        return {
            "auth_url": auth_url,
            "state": state
        }

    def validate_state(self, state: str) -> bool:
        """
        Validate CSRF state token

        Args:
            state: State token to validate

        Returns:
            True if state is valid and not expired
        """
        self._cleanup_expired_states()

        if state not in self._state_storage:
            return False

        # Check if state has expired
        timestamp = self._state_storage[state]
        if time.time() - timestamp > self._state_ttl:
            del self._state_storage[state]
            return False

        # Remove state after successful validation (one-time use)
        del self._state_storage[state]
        return True

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

    def create_jwt_token(self, line_user_id: str, employee_badge: str) -> str:
        """
        Create JWT token for authenticated employee session

        Args:
            line_user_id: LINE user ID
            employee_badge: Employee badge number

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
        expired_states = [
            state for state, timestamp in self._state_storage.items()
            if current_time - timestamp > self._state_ttl
        ]
        for state in expired_states:
            del self._state_storage[state]


# Singleton instance
line_auth_service = LineAuthService()
