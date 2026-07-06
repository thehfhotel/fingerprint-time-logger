"""Card-reader identity resolution API (2026-07).

Server-to-server endpoint the new-hotel PMS calls to turn a tapped NFC card
UID into an employee identity. This service is the central identity authority
for staff NFC cards.

Mounted under /api/private/reader/* — but unlike the other private routers
(which sit behind Cloudflare Access or the admin passcode session), this one is
called machine-to-machine and authenticates with a shared secret in the
``X-Reader-Secret`` header, compared in constant time.

Ships DARK: when ``READER_RESOLVE_SECRET`` is unset the whole surface returns
404, mirroring the HF ID (OIDC) dark-until-configured posture in
``app/services/oidc_service.py``.
"""
import hmac
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.models import Employee, EmployeeAppGrant

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_secret() -> str:
    """The shared reader secret from the environment (may be empty).

    Read directly via ``os.getenv`` (same convention as the HFID_* secrets in
    oidc_service) — never via the pydantic Settings object or the image.
    """
    return os.getenv("READER_RESOLVE_SECRET", "").strip()


def is_enabled() -> bool:
    """Whether the reader-resolve endpoint is configured. When False the whole
    surface is dark (returns 404), like HF ID without a signing key."""
    return bool(_resolve_secret())


class ResolveRequest(BaseModel):
    uid: str


@router.post("/resolve")
async def resolve_card(
    body: ResolveRequest,
    x_reader_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Resolve a tapped NFC card UID into an employee identity.

    Auth: constant-time match of the ``X-Reader-Secret`` header against
    ``READER_RESOLVE_SECRET``. Dark (404) when the secret is unset; 401 when
    the header is missing or wrong.

    A UID with no matching employee is a normal answer (found=false, HTTP 200),
    not an error.
    """
    expected = _resolve_secret()
    if not expected:
        # Dark until configured — indistinguishable from a non-existent route.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if not x_reader_secret or not hmac.compare_digest(x_reader_secret, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid reader secret"
        )

    # The reader sends uppercase hex. The admin assign endpoint stores the UID
    # verbatim (no case normalization), so existing data may be mixed-case —
    # compare case-insensitively on both sides so lookups line up regardless.
    uid = body.uid.strip().upper()
    employee = (
        db.query(Employee)
        .filter(func.upper(Employee.nfc_card_uid) == uid)
        .first()
    )

    if employee is None:
        return {
            "found": False,
            "badge": None,
            "display_name": None,
            "apps": [],
            "active": False,
            "pending": False,
        }

    apps = [
        grant.app_id
        for grant in (
            db.query(EmployeeAppGrant)
            .filter(EmployeeAppGrant.employee_badge_number == employee.badge_number)
            .order_by(EmployeeAppGrant.app_id)
            .all()
        )
    ]

    return {
        "found": True,
        "badge": employee.badge_number,
        "display_name": employee.display_name,
        "apps": apps,
        "active": bool(employee.is_active),
        "pending": bool(employee.pending_approval),
    }
