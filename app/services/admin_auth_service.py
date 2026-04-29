"""
Admin Authentication Service
Secure passcode-based authentication with bcrypt hashing and session management
"""
import os
import secrets
import threading
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

# Environments where running without ADMIN_PASSCODE_HASH is permitted.
_DEV_ENVIRONMENTS = ("dev", "development", "local", "test")
# Generic placeholder used only when explicitly running in a dev environment
# without ADMIN_PASSCODE_HASH set. NOT a real production credential.
_DEV_DEFAULT_PASSCODE = "dev-passcode-CHANGE-ME"


class AdminAuthService:
    def __init__(self):
        # Session storage: {token: {expires_at: datetime, created_at: datetime}}
        self._sessions: Dict[str, dict] = {}
        self._sessions_lock = threading.RLock()
        self._session_duration = timedelta(hours=1)

        # Get hashed passcode from environment variable.
        # In production it MUST be set; in dev environments we fall back to a
        # placeholder dev passcode so the service can boot for local testing.
        hashed = os.getenv('ADMIN_PASSCODE_HASH', '').strip()

        if not hashed:
            env = os.getenv('ENV', os.getenv('ENVIRONMENT', 'production')).lower()
            if env not in _DEV_ENVIRONMENTS:
                raise RuntimeError(
                    "ADMIN_PASSCODE_HASH environment variable is required in production"
                )
            logger.warning(
                "ADMIN_PASSCODE_HASH not set — using insecure dev default. "
                "DO NOT use in production."
            )
            dev_passcode = os.getenv('ADMIN_PASSCODE_DEV_DEFAULT', _DEV_DEFAULT_PASSCODE)
            self._hashed_passcode = bcrypt.hashpw(
                dev_passcode.encode('utf-8'), bcrypt.gensalt()
            )
            logger.info(
                "Generated dev hash (add to .env to override): "
                f"ADMIN_PASSCODE_HASH={self._hashed_passcode.decode('utf-8')}"
            )
        else:
            self._hashed_passcode = hashed.encode('utf-8')

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
        with self._sessions_lock:
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
        if not token:
            return False

        with self._sessions_lock:
            session = self._sessions.get(token)
            if session is None:
                return False

            # Check if session has expired
            if datetime.now() > session['expires_at']:
                # Inline removal to avoid lock re-entry / TOCTOU.
                self._sessions.pop(token, None)
                logger.info(f"Session expired: {token[:8]}...")
                return False

        return True

    def revoke_session(self, token: str) -> None:
        """
        Revoke a session token (logout)

        Args:
            token: Session token to revoke
        """
        with self._sessions_lock:
            removed = self._sessions.pop(token, None)
        if removed is not None:
            logger.info(f"Session revoked: {token[:8]}...")

    def cleanup_expired_sessions(self) -> int:
        """
        Remove all expired sessions from storage

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.now()
        with self._sessions_lock:
            # Snapshot the items to avoid mutating while iterating.
            expired_tokens = [
                token for token, session in list(self._sessions.items())
                if now > session['expires_at']
            ]
            for token in expired_tokens:
                self._sessions.pop(token, None)

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
        with self._sessions_lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            # Copy out the fields we need so we can release the lock quickly.
            created_at = session['created_at']
            expires_at = session['expires_at']

        expires_in = (expires_at - datetime.now()).total_seconds()

        return {
            'created_at': created_at.isoformat(),
            'expires_at': expires_at.isoformat(),
            'expires_in_seconds': int(expires_in),
            'expires_in_minutes': int(expires_in / 60)
        }

# Singleton instance
admin_auth_service = AdminAuthService()
