"""
Tests for app/services/zk_client.py — now a thin compatibility shim over
`zk_session`. The shim preserves the historical public API
(`get_status`, `get_time`, `sync_time`, `get_users`) but delegates all
device I/O to the long-lived `ZkSession` daemon. So these tests verify the
shim contract rather than the lock-bracket invariants that lived in the old
implementation (those have moved to `test_zk_session.py`).

`pull_attendance` (zk_client + zk_session) was deleted (fix/zk-ingestion-loss —
zero callers, superseded by `catch_up_now(full=...)`); its dedicated
watermark-filter coverage now lives in `test_zk_ingestion.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from app.services import zk_client as zk_client_module
from app.services import zk_session as zk_session_module
from app.services.zk_client import ZkClient


class FakeConn:
    def __init__(self, *, device_time=None, attendance=None, users=None):
        self.device_time = device_time or datetime(2024, 1, 1, 12, 0, 0)
        self.attendance = attendance or []
        self.users = users or []
        self.disconnected = False

    def get_firmware_version(self):
        return "Ver 6.60 Jun 18 2018"

    def get_time(self):
        return self.device_time

    def set_time(self, target):
        self.device_time = target

    def get_attendance(self):
        return self.attendance

    def get_users(self):
        return self.users

    def disconnect(self):
        self.disconnected = True


def _patch_one_shot_with(conn):
    """Patch the ZK constructor inside zk_session so the one-shot path
    (used when the daemon thread isn't running) hands back our FakeConn."""
    zk_instance = MagicMock()
    zk_instance.connect.return_value = conn
    return patch.object(zk_session_module, "ZK", return_value=zk_instance)


# ---------------------------------------------------------------------------
# Shim public API
# ---------------------------------------------------------------------------


def test_get_status_returns_firmware_when_connected():
    conn = FakeConn()
    with _patch_one_shot_with(conn):
        result = ZkClient(max_retries=1).get_status()
    assert result["connected"] is True
    assert result["firmware"] == "Ver 6.60 Jun 18 2018"
    assert conn.disconnected is True


def test_get_status_returns_error_on_connect_failure():
    zk_instance = MagicMock()
    zk_instance.connect.side_effect = Exception("can't reach device")
    with patch.object(zk_session_module, "ZK", return_value=zk_instance):
        result = ZkClient(max_retries=1).get_status()
    assert result["connected"] is False
    assert "can't reach device" in result["error"]


def test_get_time_returns_drift_dict():
    conn = FakeConn(device_time=datetime(2024, 1, 1, 12, 0, 0))
    with _patch_one_shot_with(conn):
        result = ZkClient(max_retries=1).get_time()
    assert result["success"] is True
    assert "time_difference_seconds" in result
    assert conn.disconnected is True


def test_sync_time_reads_writes_and_verifies():
    conn = FakeConn(device_time=datetime(2024, 1, 1, 11, 59, 0))
    with _patch_one_shot_with(conn), patch("app.services.zk_session.time.sleep", lambda *_: None):
        result = ZkClient(max_retries=1).sync_time()
    assert result["success"] is True
    assert result["time_diff_after"] < 5.0
    assert result["time_diff_before"] >= 0
    assert conn.disconnected is True


def test_get_users_returns_normalized_user_dicts():
    user = MagicMock(user_id=42, privilege=0, password="", group_id="1")
    user.name = "Test User"  # `name` is a reserved Mock kwarg; set explicitly.
    conn = FakeConn(users=[user])
    with _patch_one_shot_with(conn):
        out = ZkClient().get_users()
    assert out == [
        {
            "user_id": "42",
            "name": "Test User",
            "privilege": 0,
            "password": "",
            "group_id": "1",
        }
    ]


def test_zk_client_singleton_exposes_legacy_attributes():
    """Callers like consolidated_devices.py read `zk_client.timeout` and
    `zk_client.max_retries`. The shim must keep those attributes."""
    client = zk_client_module.zk_client
    assert isinstance(client.timeout, int)
    assert isinstance(client.max_retries, int)
    assert isinstance(client.host, str)
    assert isinstance(client.port, int)
