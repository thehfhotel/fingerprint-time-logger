"""
QR Code Service for QR Check-In Feature

Generates time-limited QR codes with JWT tokens for terminal authentication.
Security provided through short token expiry, GPS validation, and JWT signatures.
"""

import os
import secrets
import logging
import jwt
import qrcode
import io
import base64
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from fastapi import HTTPException, status
from PIL import Image

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


class QRCodeService:
    """Service for generating and validating QR codes with JWT tokens"""

    def __init__(self):
        self.jwt_secret = JWT_SECRET
        self.qr_token_expiry_seconds = 60  # 60-second expiry for QR tokens
        self.qr_grace_period_seconds = 15  # 15-second grace period after expiry

    def generate_qr_token(self, terminal_id: int) -> Dict[str, any]:
        """
        Generate time-limited JWT token for QR code

        Args:
            terminal_id: ID of the terminal device

        Returns:
            Dict containing:
            - token: JWT token string
            - nonce: Unique nonce for token structure
            - expires_at: Token expiration timestamp
        """
        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=self.qr_token_expiry_seconds)

        # Generate unique nonce for token uniqueness (not for replay prevention)
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
        Validate QR token for terminal check-in with grace period

        Args:
            token: JWT token from QR code scan

        Returns:
            Dict containing decoded token payload

        Raises:
            HTTPException: If token is invalid or expired beyond grace period

        Note:
            Nonce replay prevention is disabled to allow multiple users to scan
            the same QR code simultaneously. Security is maintained through:
            - 60-second token expiry (short validity window)
            - 15-second grace period (accepts slightly expired tokens)
            - GPS location validation (must be at terminal location)
            - JWT signature verification (prevents token tampering)
        """
        try:
            # Decode and verify token (checks signature and expiry)
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])

            # Verify nonce is present (for token structure validation)
            nonce = payload.get("nonce")
            if not nonce:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="โทเค็น QR ไม่ถูกต้อง (ไม่มี nonce)"
                )

            # NOTE: Nonce replay prevention is intentionally disabled
            # This allows multiple employees to scan the same QR code within
            # the validity window + grace period, which is required for shared terminals

            return payload

        except jwt.ExpiredSignatureError:
            # Check if token is within grace period
            try:
                # Decode without verifying expiry to check timestamp
                payload = jwt.decode(
                    token,
                    self.jwt_secret,
                    algorithms=["HS256"],
                    options={"verify_exp": False}
                )

                exp_timestamp = payload.get("exp")
                if exp_timestamp:
                    now = datetime.now(timezone.utc)
                    exp_time = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
                    elapsed_seconds = (now - exp_time).total_seconds()

                    # Accept token if within grace period
                    if elapsed_seconds <= self.qr_grace_period_seconds:
                        logger.info(
                            "Accepting expired QR token within grace period (%.1fs elapsed)",
                            elapsed_seconds,
                        )
                        return payload

            except Exception as grace_error:
                logger.warning("QR grace period check failed: %s", grace_error)

            # Token expired beyond grace period
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

        # Create deep link URL for one-scan check-in
        # This URL can be scanned directly from iPhone Camera or generic QR scanners
        base_url = os.getenv("BASE_URL", "https://erp.thehfhotel.org")
        qr_url = f"{base_url}/qr-checkin/scan?token={token_data['token']}&terminal={terminal_id}"

        # Generate QR code image with URL (not just token)
        qr_image = self.generate_qr_code_image(qr_url, size=size)

        return {
            "qr_image": qr_image,
            "token": token_data["token"],
            "qr_url": qr_url,  # Include URL for debugging
            "expires_at": token_data["expires_at"],
            "expires_in_seconds": token_data["expires_in_seconds"],
            "terminal_id": terminal_id
        }


# Global service instance
qr_service = QRCodeService()
