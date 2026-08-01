"""
Compatibility shim. The real implementation lives in `zk_session`.

Historically this module owned the pyzk connection via a per-call
connect/op/disconnect cycle behind a threading.Lock. That model can't
coexist with `live_capture` (which holds the single TCP session the K40
firmware supports), so all device access now goes through the long-lived
`ZkSession` daemon thread. This file preserves the legacy class+singleton
API so existing callers (`consolidated_devices.py`, `consolidated_employees.py`,
`device_cache_service.py`, tests) continue working without edits.
"""

from __future__ import annotations

import os
from typing import List, Optional

from app.services import zk_session as _zk_session


class ZkClient:
    """Thin facade over `zk_session` preserving the historical API surface."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        password: Optional[int] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_backoff_seconds: float = 3.0,
    ):
        self.host = host or os.getenv("ZKTECO_HOST", "192.168.100.209")
        self.port = int(port if port is not None else os.getenv("ZKTECO_PORT", "4370"))
        self.password = int(
            password if password is not None else os.getenv("ZKTECO_PASSWORD", "0")
        )
        self.timeout = int(timeout if timeout is not None else os.getenv("DEVICE_TIMEOUT", "5"))
        self.max_retries = int(
            max_retries if max_retries is not None else os.getenv("DEVICE_MAX_RETRIES", "3")
        )
        self.retry_backoff_seconds = retry_backoff_seconds

    def get_status(self) -> dict:
        return _zk_session.get_status()

    def get_time(self) -> dict:
        return _zk_session.get_time()

    def sync_time(self) -> dict:
        return _zk_session.sync_time()

    def get_users(self) -> List[dict]:
        return _zk_session.get_users()


zk_client = ZkClient()
