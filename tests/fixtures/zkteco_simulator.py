"""
ZKTeco Device Simulator for Testing
Provides mock implementation of ZKTeco device functionality without hardware dependency
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from unittest.mock import MagicMock
import random
import time

try:
    from zk.attendance import Attendance as _PyzkAttendance
except Exception:  # pragma: no cover - fallback when pyzk import path differs
    _PyzkAttendance = None


class ZKTecoSimulator:
    """
    Mock ZKTeco device for testing
    Simulates all device operations without requiring actual hardware
    """

    def __init__(self, ip: str = "192.168.100.209", port: int = 4370):
        self.ip = ip
        self.port = port
        self.password = 0
        self.connected = False
        self.connection_stable = True

        # Simulated device state
        self.users: List[Dict[str, Any]] = []
        self.attendance_records: List[Dict[str, Any]] = []
        self.device_info = {
            'model': 'ZKTeco K40',
            'serial_number': 'ZKT123456789',
            'firmware': '6.60.00',
            'platform': 'ZEM600'
        }

        # Simulation behavior controls
        self.simulate_network_issues = False
        self.simulate_device_errors = False
        self.response_delay = 0.1  # Simulated network delay

    def connect(self) -> bool:
        """Simulate device connection"""
        if self.simulate_network_issues:
            return False

        self.connected = True
        return True

    def disconnect(self):
        """Simulate device disconnection"""
        self.connected = False

    def is_connected(self) -> bool:
        """Check connection status"""
        return self.connected

    def get_device_info(self) -> Dict[str, Any]:
        """Get simulated device information"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        return self.device_info.copy()

    def get_time(self) -> datetime:
        """Get simulated device time"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        # Simulate slight time drift
        drift_seconds = random.randint(-30, 30)
        return datetime.now() + timedelta(seconds=drift_seconds)

    def set_time(self, new_time: datetime) -> bool:
        """Set device time (simulated)"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        if self.simulate_device_errors:
            return False

        return True

    def get_users(self) -> List[Dict[str, Any]]:
        """Get all users from simulated device"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        return self.users.copy()

    def add_user(self, user_id: str, name: str, privilege: int = 0,
                 password: str = "", group_id: str = "", user_id_int: int = None):
        """Add user to simulated device"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        user = {
            'uid': user_id_int or int(user_id),
            'user_id': user_id,
            'name': name,
            'privilege': privilege,
            'password': password,
            'group_id': group_id
        }

        # Remove existing user with same ID
        self.users = [u for u in self.users if u['user_id'] != user_id]
        self.users.append(user)

        return True

    def delete_user(self, user_id: str) -> bool:
        """Delete user from simulated device"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        original_count = len(self.users)
        self.users = [u for u in self.users if u['user_id'] != user_id]

        return len(self.users) < original_count

    def get_attendance(self) -> List[Dict[str, Any]]:
        """Get all attendance records from simulated device"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        return self.attendance_records.copy()

    def add_attendance_record(self, user_id: str, timestamp: datetime,
                            punch_type: int, status: int = 0):
        """Add attendance record to simulator"""
        record = {
            'uid': int(user_id),
            'user_id': user_id,
            'timestamp': timestamp,
            'punch': punch_type,
            'status': status
        }
        self.attendance_records.append(record)

    def clear_attendance(self) -> bool:
        """Clear all attendance records from simulated device"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        if self.simulate_device_errors:
            return False

        self.attendance_records.clear()
        return True

    def get_attendance_count(self) -> int:
        """Get count of attendance records"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        return len(self.attendance_records)

    def get_user_count(self) -> int:
        """Get count of users"""
        if not self.connected:
            raise ConnectionError("Device not connected")

        return len(self.users)


class ZKTecoSimulatorFactory:
    """Factory for creating configured ZKTeco simulators for different test scenarios"""

    @staticmethod
    def create_healthy_device() -> ZKTecoSimulator:
        """Create a simulator with normal, healthy device behavior"""
        return ZKTecoSimulator()

    @staticmethod
    def create_network_issues_device() -> ZKTecoSimulator:
        """Create a simulator that has network connectivity problems"""
        simulator = ZKTecoSimulator()
        simulator.simulate_network_issues = True
        return simulator

    @staticmethod
    def create_error_prone_device() -> ZKTecoSimulator:
        """Create a simulator that has device errors"""
        simulator = ZKTecoSimulator()
        simulator.simulate_device_errors = True
        return simulator

    @staticmethod
    def create_slow_device() -> ZKTecoSimulator:
        """Create a simulator with slow response times"""
        simulator = ZKTecoSimulator()
        simulator.response_delay = 2.0  # 2 second delay
        return simulator

    @staticmethod
    def create_populated_device(user_count: int = 50,
                              attendance_days: int = 30) -> ZKTecoSimulator:
        """Create a simulator pre-populated with users and attendance data"""
        simulator = ZKTecoSimulator()

        # Add users
        for i in range(user_count):
            user_id = f"{i+1:04d}"
            simulator.add_user(
                user_id=user_id,
                name=f"Test Employee {i+1}",
                privilege=0,
                user_id_int=i+1
            )

        # Add attendance records for the last N days
        for day in range(attendance_days):
            date = datetime.now() - timedelta(days=day)

            # Skip weekends
            if date.weekday() >= 5:
                continue

            for user_num in range(1, user_count + 1):
                user_id = f"{user_num:04d}"

                # 90% probability of attendance each day
                if random.random() < 0.9:
                    # Morning check-in (8-9 AM)
                    checkin_time = date.replace(
                        hour=8,
                        minute=random.randint(0, 59),
                        second=random.randint(0, 59)
                    )
                    simulator.add_attendance_record(
                        user_id, checkin_time, punch_type=0
                    )

                    # Evening check-out (17-18 PM) - 85% probability
                    if random.random() < 0.85:
                        checkout_time = date.replace(
                            hour=17,
                            minute=random.randint(0, 59),
                            second=random.randint(0, 59)
                        )
                        simulator.add_attendance_record(
                            user_id, checkout_time, punch_type=1
                        )

        return simulator


class MockZKConnection:
    """
    Mock implementation of the actual ZK connection object
    Compatible with pyzk library interfaces
    """

    def __init__(self, simulator: ZKTecoSimulator):
        self.simulator = simulator
        self._connected = False
        # live_capture support — pyzk sets these on the conn object.
        self.end_live_capture = False
        self._pending_punches: List[Any] = []
        # Optional override: when set, live_capture's idle wait sleeps this
        # many seconds regardless of `new_timeout`. Lets tests skip sleeps.
        self._live_capture_idle_override: Optional[float] = None

    def connect(self):
        """Mock connection method"""
        self._connected = self.simulator.connect()
        return self._connected

    def disconnect(self):
        """Mock disconnection method"""
        self.simulator.disconnect()
        self._connected = False

    def is_connect(self):
        """Mock connection check (matches pyzk interface)"""
        return self._connected

    def get_users(self):
        """Mock get users method"""
        return self.simulator.get_users()

    def get_attendance(self):
        """Mock get attendance method"""
        return self.simulator.get_attendance()

    def get_time(self):
        """Mock get time method"""
        return self.simulator.get_time()

    def set_time(self, new_time):
        """Mock set time method"""
        return self.simulator.set_time(new_time)

    def get_device_info(self):
        """Mock get device info method"""
        return self.simulator.get_device_info()

    def get_firmware_version(self):
        """Mock firmware version (used by zk_session.get_status)."""
        return self.simulator.device_info.get('firmware', 'Unknown')

    def clear_attendance(self):
        """Mock clear attendance method"""
        return self.simulator.clear_attendance()

    def queue_punch(self, badge_number: str, timestamp: datetime,
                    punch_type: int = 0, status: int = 0) -> None:
        """Push a punch onto the live_capture queue."""
        if _PyzkAttendance is not None:
            att = _PyzkAttendance(badge_number, timestamp, status, punch_type, 0)
        else:
            att = MagicMock(user_id=badge_number, timestamp=timestamp,
                            punch=punch_type, status=status, uid=0)
        self._pending_punches.append(att)

    def live_capture(self, new_timeout: float = 10):
        """Mock pyzk live_capture generator.

        Yields each queued Attendance object, then yields None after an idle
        wait (`new_timeout` seconds, or `_live_capture_idle_override` if
        callers want to bypass the sleep). Exits when `end_live_capture` is
        True — checked before AND between yields so the consumer can break
        the loop by setting the flag during iteration.
        """
        self.end_live_capture = False
        idle = self._live_capture_idle_override if self._live_capture_idle_override is not None else new_timeout
        while not self.end_live_capture:
            if self._pending_punches:
                yield self._pending_punches.pop(0)
                if self.end_live_capture:
                    return
                continue
            if idle > 0:
                time.sleep(idle)
            yield None


# Pytest fixtures for common simulator scenarios

def pytest_simulator_healthy():
    """Pytest fixture for healthy device simulator"""
    return ZKTecoSimulatorFactory.create_healthy_device()

def pytest_simulator_network_issues():
    """Pytest fixture for network issues simulator"""
    return ZKTecoSimulatorFactory.create_network_issues_device()

def pytest_simulator_populated():
    """Pytest fixture for populated device simulator"""
    return ZKTecoSimulatorFactory.create_populated_device()

def pytest_mock_connection(simulator):
    """Pytest fixture for mock ZK connection"""
    return MockZKConnection(simulator)


# Export convenience functions and classes
__all__ = [
    'ZKTecoSimulator',
    'ZKTecoSimulatorFactory',
    'MockZKConnection',
    'pytest_simulator_healthy',
    'pytest_simulator_network_issues',
    'pytest_simulator_populated',
    'pytest_mock_connection'
]