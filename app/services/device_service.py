"""
Device lookups — pure DB, no device I/O.

ARCHITECTURE NOTE: this module used to open its own pyzk connections
(`connect_to_device`, `sync_attendance_data`, etc.) in parallel with the
`ZkSession` daemon thread's `live_capture` session — two independent TCP
sessions racing the K40's single-session limit. All device I/O now goes
exclusively through `app/services/zk_session.py` (see its module docstring)
via the `zk_client`/`zk_session` facade. This module keeps only the
device-row lookup that has real callers outside the device-I/O path.
"""

from typing import Optional
import os

from app.models.models import Device
from app.core.database import get_db


class SimpleDeviceService:
    """Pure-DB device lookups."""

    def get_default_device(self) -> Optional[Device]:
        """Get the default ZKTeco device, creating one from env vars if none exists."""
        db = next(get_db())
        try:
            device = (
                db.query(Device)
                .filter(Device.is_active == True)
                .order_by(Device.id)
                .first()
            )
            if not device:
                # Create default device if none exists
                device = Device(
                    name=os.getenv('DEVICE_NAME', 'ZKTeco Device'),
                    ip_address=os.getenv('ZKTECO_HOST', '192.168.100.209'),
                    port=int(os.getenv('ZKTECO_PORT', '4370')),
                    password=int(os.getenv('ZKTECO_PASSWORD', '0')),
                    is_active=True
                )
                db.add(device)
                db.commit()
                db.refresh(device)
            return device
        finally:
            db.close()


# Global service instance
device_service = SimpleDeviceService()
