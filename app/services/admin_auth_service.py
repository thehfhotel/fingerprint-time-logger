"""
Admin Authentication Service
Secure passcode-based authentication with bcrypt hashing and session management
"""
import os
import secrets
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

class AdminAuthService:
    def __init__(self):
        # Session storage: {token: {expires_at: datetime, created_at: datetime}}
        self._sessions: Dict[str, dict] = {}
        self._session_duration = timedelta(hours=1)

        # Get hashed passcode from environment variable
        # If not set, hash the provided passcode and log warning
        self._hashed_passcode = os.getenv('ADMIN_PASSCODE_HASH', '').encode('utf-8')

        if not self._hashed_passcode:
            logger.warning("ADMIN_PASSCODE_HASH not set in environment variables!")
            logger.warning("Using temporary hash - THIS IS NOT SECURE FOR PRODUCTION!")
            # Hash the provided passcode for first-time setup
            temp_passcode = 'H]sN4@Wa3wA9Fg9%<^2^VtJ^mWLDQ9!"j>Eptf,'
            self._hashed_passcode = bcrypt.hashpw(temp_passcode.encode('utf-8'), bcrypt.gensalt())
            logger.info(f"Generated hash (add to .env): ADMIN_PASSCODE_HASH={self._hashed_passcode.decode('utf-8')}")

    def verify_passcode(self, passcode: str) -> bool:
        """
        Verify passcode against stored hash using bcrypt

        Args:
            passcode: Plain text passcode to verify

        Returns:
            True if passcode matches, False otherwise
        """
        try:
            if not self._hashed_passcode:
                logger.error("No hashed passcode configured")
                return False

            return bcrypt.checkpw(passcode.encode('utf-8'), self._hashed_passcode)
        except Exception as e:
            logger.error(f"Error verifying passcode: {e}")
            return False

    def create_session(self) -> str:
        """
        Create a new session token with 1-hour expiration

        Returns:
            Secure random session token
        """
        # Generate cryptographically secure random token
        token = secrets.token_urlsafe(32)

        # Store session with expiration
        self._sessions[token] = {
            'expires_at': datetime.now() + self._session_duration,
            'created_at': datetime.now()
        }

        logger.info(f"Session created: {token[:8]}... (expires in 1 hour)")
        return token

    def validate_session(self, token: str) -> bool:
        """
        Validate session token and check expiration

        Args:
            token: Session token to validate

        Returns:
            True if session is valid and not expired, False otherwise
        """
        if not token or token not in self._sessions:
            return False

        session = self._sessions[token]

        # Check if session has expired
        if datetime.now() > session['expires_at']:
            logger.info(f"Session expired: {token[:8]}...")
            self.revoke_session(token)
            return False

        return True

    def revoke_session(self, token: str) -> None:
        """
        Revoke a session token (logout)

        Args:
            token: Session token to revoke
        """
        if token in self._sessions:
            del self._sessions[token]
            logger.info(f"Session revoked: {token[:8]}...")

    def cleanup_expired_sessions(self) -> int:
        """
        Remove all expired sessions from storage

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.now()
        expired_tokens = [
            token for token, session in self._sessions.items()
            if now > session['expires_at']
        ]

        for token in expired_tokens:
            del self._sessions[token]

        if expired_tokens:
            logger.info(f"Cleaned up {len(expired_tokens)} expired sessions")

        return len(expired_tokens)

    def get_session_info(self, token: str) -> Optional[dict]:
        """
        Get session information

        Args:
            token: Session token

        Returns:
            Session info dict or None if session doesn't exist
        """
        if token not in self._sessions:
            return None

        session = self._sessions[token]
        expires_in = (session['expires_at'] - datetime.now()).total_seconds()

        return {
            'created_at': session['created_at'].isoformat(),
            'expires_at': session['expires_at'].isoformat(),
            'expires_in_seconds': int(expires_in),
            'expires_in_minutes': int(expires_in / 60)
        }

# Singleton instance
admin_auth_service = AdminAuthService()
