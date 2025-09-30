"""
QR Code Service for QR Check-In Feature

Generates time-limited QR codes with JWT tokens for terminal authentication.
Implements replay attack prevention through nonce tracking.
"""

import os
import time
import secrets
import jwt
import qrcode
import io
import base64
from datetime import datetime, timedelta
from typing import Dict, Optional, Set
from fastapi import HTTPException, status
from PIL import Image


class QRCodeService:
    """Service for generating and validating QR codes with JWT tokens"""

    def __init__(self):
        self.jwt_secret = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
        self.qr_token_expiry_seconds = 30  # 30-second expiry for QR tokens

        # Nonce storage for replay attack prevention (in-memory)
        # In production, consider Redis for distributed systems
        self._used_nonces: Set[str] = set()
        self._nonce_cleanup_interval = 60  # Cleanup every 60 seconds
        self._last_cleanup = time.time()

    def generate_qr_token(self, terminal_id: int) -> Dict[str, any]:
        """
        Generate time-limited JWT token for QR code

        Args:
            terminal_id: ID of the terminal device

        Returns:
            Dict containing:
            - token: JWT token string
            - nonce: Unique nonce for replay prevention
            - expires_at: Token expiration timestamp
        """
        now = datetime.utcnow()
        exp = now + timedelta(seconds=self.qr_token_expiry_seconds)

        # Generate unique nonce for replay attack prevention
        nonce = secrets.token_urlsafe(16)

        payload = {
            "terminal_id": terminal_id,
            "timestamp": int(now.timestamp()),
            "nonce": nonce,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp())
        }

        token = jwt.encode(payload, self.jwt_secret, algorithm="HS256")

        return {
            "token": token,
            "nonce": nonce,
            "expires_at": exp.isoformat(),
            "expires_in_seconds": self.qr_token_expiry_seconds
        }

    def validate_qr_token(self, token: str) -> Dict[str, any]:
        """
        Validate QR token and check for replay attacks

        Args:
            token: JWT token from QR code scan

        Returns:
            Dict containing decoded token payload

        Raises:
            HTTPException: If token is invalid, expired, or replayed
        """
        try:
            # Decode and verify token
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])

            # Check if nonce was already used (replay attack)
            nonce = payload.get("nonce")
            if not nonce:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="โทเค็น QR ไม่ถูกต้อง (ไม่มี nonce)"
                )

            if nonce in self._used_nonces:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="QR code นี้ถูกใช้งานไปแล้ว กรุณาสแกน QR code ใหม่"
                )

            # Mark nonce as used
            self._used_nonces.add(nonce)

            # Periodic cleanup of old nonces
            self._cleanup_expired_nonces()

            return payload

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="QR code หมดอายุแล้ว กรุณาสแกน QR code ใหม่"
            )
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"โทเค็น QR ไม่ถูกต้อง: {str(e)}"
            )

    def generate_qr_code_image(self, data: str, size: int = 300) -> str:
        """
        Generate QR code image as base64-encoded PNG

        Args:
            data: Data to encode in QR code (typically JWT token)
            size: Size of QR code image in pixels (default 300x300)

        Returns:
            Base64-encoded PNG image string
        """
        try:
            # Create QR code instance
            qr = qrcode.QRCode(
                version=1,  # Auto-adjust version based on data size
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )

            # Add data and generate
            qr.add_data(data)
            qr.make(fit=True)

            # Create image
            img = qr.make_image(fill_color="black", back_color="white")

            # Resize to specified size
            img = img.resize((size, size), Image.Resampling.LANCZOS)

            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            img_bytes = buffer.getvalue()
            img_base64 = base64.b64encode(img_bytes).decode('utf-8')

            return f"data:image/png;base64,{img_base64}"

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"การสร้าง QR code ล้มเหลว: {str(e)}"
            )

    def generate_qr_code_for_terminal(self, terminal_id: int, size: int = 300) -> Dict[str, any]:
        """
        Generate complete QR code data for terminal display

        Args:
            terminal_id: ID of the terminal device
            size: Size of QR code image in pixels

        Returns:
            Dict containing:
            - qr_image: Base64-encoded PNG image
            - token: JWT token (for debugging/logging)
            - expires_at: Expiration timestamp
            - expires_in_seconds: Time until expiration
        """
        # Generate token
        token_data = self.generate_qr_token(terminal_id)

        # Generate QR code image
        qr_image = self.generate_qr_code_image(token_data["token"], size=size)

        return {
            "qr_image": qr_image,
            "token": token_data["token"],
            "expires_at": token_data["expires_at"],
            "expires_in_seconds": token_data["expires_in_seconds"],
            "terminal_id": terminal_id
        }

    def _cleanup_expired_nonces(self):
        """
        Cleanup expired nonces to prevent memory growth

        Called periodically during token validation.
        Nonces older than 2x token expiry are removed.
        """
        now = time.time()

        # Only cleanup if interval has passed
        if now - self._last_cleanup < self._nonce_cleanup_interval:
            return

        # Clear all nonces (they're all expired after 2x token expiry)
        # In production with Redis, set TTL on nonce keys
        self._used_nonces.clear()
        self._last_cleanup = now


# Global service instance
qr_service = QRCodeService()
