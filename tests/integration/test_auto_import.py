"""
Integration tests for auto-import background task.

Tests verify that the auto-import background task:
1. Starts correctly on application startup
2. Runs at scheduled intervals (non-blocking async timers)
3. Syncs attendance data from device
4. Broadcasts updates via WebSocket
5. Updates device.last_sync timestamp

Uses asyncio for non-blocking timer verification instead of CPU-blocking loops.
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


class TestAutoImportScheduling:
    """Test auto-import background task scheduling and execution"""

    @pytest.fixture
    def mock_device_service(self):
        """Mock device service for testing"""
        with patch('app.services.device_service.device_service') as mock:
            mock.sync_attendance_data = Mock(return_value={
                "success": True,
                "synced": 5,
                "total_processed": 100,
                "message": "Sync completed"
            })
            yield mock

    @pytest.fixture
    def mock_websocket_manager(self):
        """Mock WebSocket manager for testing"""
        with patch('app.main_unified.manager') as mock:
            mock.broadcast = AsyncMock()
            yield mock

    @pytest.fixture
    def mock_attendance_service(self):
        """Mock attendance service for testing"""
        with patch('app.services.attendance_service.attendance_service') as mock:
            mock.get_attendance_summary = Mock(return_value={
                'data': {'105': []},
                'last_import': datetime.now().isoformat(),
                'total_employees': 1,
                'total_records': 5
            })
            yield mock

    @pytest.mark.asyncio
    async def test_auto_import_initial_execution(
        self,
        mock_device_service,
        mock_websocket_manager,
        mock_attendance_service
    ):
        """Test that auto-import executes immediately on startup"""
        from app.main_unified import auto_import_fingerprint_logs

        # Create task that will execute initial import then stop
        task = asyncio.create_task(auto_import_fingerprint_logs())

        # Wait for initial import to complete (should be immediate)
        await asyncio.sleep(0.5)

        # Cancel the ongoing loop
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify initial import was called
        mock_device_service.sync_attendance_data.assert_called_once()
        mock_attendance_service.get_attendance_summary.assert_called_once()
        mock_websocket_manager.broadcast.assert_called_once()

        # Verify broadcast message
        broadcast_call = mock_websocket_manager.broadcast.call_args[0][0]
        assert broadcast_call['type'] == 'auto_import_update'
        assert 'data' in broadcast_call
        assert 'synced_records' in broadcast_call

    @pytest.mark.asyncio
    async def test_auto_import_periodic_execution_with_timer(
        self,
        mock_device_service,
        mock_websocket_manager,
        mock_attendance_service
    ):
        """Test that auto-import runs at scheduled intervals using async timer (non-blocking)"""
        # Track execution times
        execution_times = []
        execution_count = 0
        original_sync = mock_device_service.sync_attendance_data

        def track_execution(*args, **kwargs):
            nonlocal execution_count
            execution_count += 1
            execution_times.append(datetime.now())
            return original_sync(*args, **kwargs)

        mock_device_service.sync_attendance_data.side_effect = track_execution

        # Mock asyncio.sleep to make it instant for first call, then normal for subsequent
        original_sleep = asyncio.sleep
        sleep_call_count = 0

        async def fast_sleep(seconds):
            nonlocal sleep_call_count
            sleep_call_count += 1
            # First sleep (in while loop) should be instant for testing
            if sleep_call_count == 1:
                await original_sleep(0.1)  # 100ms instead of 30 minutes
            else:
                await original_sleep(seconds)

        with patch('asyncio.sleep', side_effect=fast_sleep):
            from app.main_unified import auto_import_fingerprint_logs

            # Start auto-import task
            task = asyncio.create_task(auto_import_fingerprint_logs())

            # Wait for initial execution and one periodic execution (non-blocking)
            start_time = datetime.now()
            while execution_count < 2 and (datetime.now() - start_time).total_seconds() < 5:
                await original_sleep(0.2)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Verify we got at least 2 executions (initial + 1 scheduled)
        assert execution_count >= 2, f"Expected at least 2 executions, got {execution_count}"
        assert len(execution_times) >= 2, "Expected to track at least 2 execution times"

    @pytest.mark.asyncio
    async def test_auto_import_error_handling_continues_execution(
        self,
        mock_websocket_manager,
        mock_attendance_service
    ):
        """Test that auto-import continues after errors (non-blocking async timer)"""
        with patch('app.services.device_service.device_service') as mock_service:
            # First call fails, second succeeds
            mock_service.sync_attendance_data.side_effect = [
                Exception("Device connection failed"),
                {"success": True, "synced": 0, "total_processed": 100}
            ]

            # Mock asyncio.sleep to make it fast for testing
            original_sleep = asyncio.sleep

            async def fast_sleep(seconds):
                # Make all sleeps fast for testing
                await original_sleep(0.1)

            with patch('asyncio.sleep', side_effect=fast_sleep):
                from app.main_unified import auto_import_fingerprint_logs

                task = asyncio.create_task(auto_import_fingerprint_logs())

                # Wait for initial execution and one retry (non-blocking)
                await original_sleep(2)

                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

                # Verify both calls happened (initial error + retry after sleep)
                assert mock_service.sync_attendance_data.call_count >= 2

    @pytest.mark.asyncio
    async def test_auto_import_broadcasts_correct_message_format(
        self,
        mock_device_service,
        mock_websocket_manager,
        mock_attendance_service
    ):
        """Test that auto-import broadcasts properly formatted WebSocket message"""
        from app.main_unified import auto_import_fingerprint_logs

        task = asyncio.create_task(auto_import_fingerprint_logs())
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Get broadcast message
        broadcast_call = mock_websocket_manager.broadcast.call_args[0][0]

        # Verify message structure
        assert broadcast_call['type'] == 'auto_import_update'
        assert 'data' in broadcast_call
        assert 'synced_records' in broadcast_call
        assert 'timestamp' in broadcast_call
        assert 'message' in broadcast_call

        # Verify data content
        assert isinstance(broadcast_call['data'], dict)
        assert broadcast_call['synced_records'] == 5
        assert isinstance(broadcast_call['timestamp'], str)

    @pytest.mark.asyncio
    async def test_auto_import_updates_last_import_time(
        self,
        mock_device_service,
        mock_websocket_manager,
        mock_attendance_service
    ):
        """Test that auto-import includes updated last_import timestamp"""
        # Mock attendance service to return specific timestamp
        test_timestamp = datetime.now().isoformat()
        mock_attendance_service.get_attendance_summary.return_value = {
            'data': {},
            'last_import': test_timestamp,
            'total_employees': 0,
            'total_records': 0
        }

        from app.main_unified import auto_import_fingerprint_logs

        task = asyncio.create_task(auto_import_fingerprint_logs())
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Verify broadcast includes last_import in data
        broadcast_call = mock_websocket_manager.broadcast.call_args[0][0]
        assert 'data' in broadcast_call
        assert broadcast_call['data']['last_import'] == test_timestamp


class TestAutoImportIntegration:
    """Integration tests for complete auto-import workflow"""

    @pytest.mark.asyncio
    async def test_auto_import_with_actual_database(self, test_db):
        """Test auto-import with real database operations"""
        from app.main_unified import auto_import_fingerprint_logs
        from app.models.models import Device
        from app.core.database import get_db

        # Setup test device
        db = next(get_db())
        device = db.query(Device).first()
        if not device:
            device = Device(
                name="Test Device",
                ip_address="192.168.100.209",
                port=4370,
                is_active=True
            )
            db.add(device)
            db.commit()

        initial_sync_time = device.last_sync

        # Mock device connection to avoid actual hardware
        with patch('app.services.device_service.SimpleDeviceService.connect_to_device') as mock_connect:
            mock_conn = MagicMock()
            mock_conn.get_attendance.return_value = []
            mock_connect.return_value = mock_conn

            with patch('app.main_unified.manager.broadcast', new_callable=AsyncMock):
                task = asyncio.create_task(auto_import_fingerprint_logs())
                await asyncio.sleep(1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Refresh device from DB
        db.refresh(device)

        # Verify last_sync was updated
        assert device.last_sync != initial_sync_time
        assert device.last_sync is not None

        db.close()

    def test_auto_import_status_endpoint(self, test_client):
        """Test auto-import status API endpoint"""
        response = test_client.get("/api/auto-import/status")
        assert response.status_code == 200

        data = response.json()
        assert 'enabled' in data
        assert 'interval_minutes' in data
        assert 'task_status' in data
        # Note: In test mode, background_task may not be running
        # We just verify the endpoint structure, not the actual task state
        assert data['task_status'] in ['running', 'stopped']
        assert isinstance(data['interval_minutes'], int)

    def test_manual_trigger_endpoint(self, test_client):
        """Test manual import trigger endpoint"""
        with patch('app.services.device_service.device_service.sync_attendance_data') as mock_sync:
            mock_sync.return_value = {
                "success": True,
                "synced": 3,
                "message": "Test sync"
            }

            with patch('app.main_unified.manager.broadcast', new_callable=AsyncMock):
                response = test_client.post("/api/auto-import/trigger")
                assert response.status_code == 200

                data = response.json()
                assert data['success'] is True
                assert data['synced'] == 3
                assert 'message' in data


@pytest.fixture
def test_client():
    """Create test client for API testing"""
    from app.main_unified import fingerprint_app
    from fastapi.testclient import TestClient
    return TestClient(fingerprint_app)