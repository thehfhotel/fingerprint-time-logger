"""
Connection Manager with Circuit Breaker Pattern for ZKTeco Device

This service manages ZKTeco device connections with resilience patterns
including circuit breaker, retry logic, and connection health monitoring.
"""

import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, Union
from enum import Enum
from dataclasses import dataclass
from zk import ZK
from sqlalchemy.orm import Session

from app.models.models import Device, DeviceStatusLog
from app.services.cache_service import CacheService


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class ConnectionState(Enum):
    """Device connection states"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class ConnectionMetrics:
    """Connection performance metrics"""
    connection_time_ms: float
    last_successful_ping: Optional[datetime]
    total_attempts: int
    successful_attempts: int
    failed_attempts: int
    avg_response_time_ms: float
    last_error: Optional[str]
    uptime_percentage: float


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration"""
    failure_threshold: int = 5           # Failures before opening circuit
    timeout_duration: int = 60          # Seconds to wait before half-open
    success_threshold: int = 3          # Successes needed to close circuit
    request_timeout: int = 10           # Individual request timeout in seconds
    monitoring_window: int = 300        # Time window for failure tracking (seconds)


class DeviceConnectionManager:
    """
    Manages ZKTeco device connections with resilience patterns
    
    Features:
    - Circuit breaker pattern for fault tolerance
    - Automatic retry with exponential backoff
    - Connection pooling and health monitoring
    - Performance metrics tracking
    """
    
    def __init__(self, db: Session, config: CircuitBreakerConfig = None):
        self.db = db
        self.cache_service = CacheService(db)
        self.config = config or CircuitBreakerConfig()
        
        # Circuit breaker state per device
        self.circuit_states: Dict[int, CircuitState] = {}
        self.failure_counts: Dict[int, int] = {}
        self.last_failure_times: Dict[int, datetime] = {}
        self.success_counts: Dict[int, int] = {}
        self.state_change_times: Dict[int, datetime] = {}
        
        # Connection pools and metrics
        self.active_connections: Dict[int, Any] = {}
        self.metrics: Dict[int, ConnectionMetrics] = {}
        
        print("🔧 DeviceConnectionManager initialized with circuit breaker pattern")
    
    def _get_circuit_state(self, device_id: int) -> CircuitState:
        """Get current circuit state for device"""
        return self.circuit_states.get(device_id, CircuitState.CLOSED)
    
    def _set_circuit_state(self, device_id: int, state: CircuitState) -> None:
        """Set circuit state and track state change time"""
        old_state = self.circuit_states.get(device_id, CircuitState.CLOSED)
        self.circuit_states[device_id] = state
        self.state_change_times[device_id] = datetime.now()
        
        if old_state != state:
            print(f"🔄 Device {device_id} circuit breaker: {old_state.value} → {state.value}")
            self._log_device_status(device_id, f"circuit_{state.value}")
    
    def _should_attempt_connection(self, device_id: int) -> bool:
        """Check if connection attempt should be made based on circuit state"""
        state = self._get_circuit_state(device_id)
        
        if state == CircuitState.CLOSED:
            return True
        
        if state == CircuitState.OPEN:
            # Check if timeout period has elapsed
            state_change_time = self.state_change_times.get(device_id)
            if state_change_time:
                time_elapsed = datetime.now() - state_change_time
                if time_elapsed.total_seconds() >= self.config.timeout_duration:
                    self._set_circuit_state(device_id, CircuitState.HALF_OPEN)
                    return True
            return False
        
        if state == CircuitState.HALF_OPEN:
            return True
        
        return False
    
    def _record_success(self, device_id: int) -> None:
        """Record successful operation and update circuit state"""
        state = self._get_circuit_state(device_id)
        
        # Reset failure count on success
        self.failure_counts[device_id] = 0
        
        if state == CircuitState.HALF_OPEN:
            self.success_counts[device_id] = self.success_counts.get(device_id, 0) + 1
            if self.success_counts[device_id] >= self.config.success_threshold:
                self._set_circuit_state(device_id, CircuitState.CLOSED)
                self.success_counts[device_id] = 0
        
        # Update metrics
        if device_id in self.metrics:
            metrics = self.metrics[device_id]
            metrics.successful_attempts += 1
            metrics.last_successful_ping = datetime.now()
    
    def _record_failure(self, device_id: int, error: str) -> None:
        """Record failed operation and update circuit state"""
        state = self._get_circuit_state(device_id)
        
        # Track failure
        self.failure_counts[device_id] = self.failure_counts.get(device_id, 0) + 1
        self.last_failure_times[device_id] = datetime.now()
        
        # Update metrics
        if device_id in self.metrics:
            metrics = self.metrics[device_id]
            metrics.failed_attempts += 1
            metrics.last_error = error
        
        # Check if we should open the circuit
        if state == CircuitState.CLOSED:
            if self.failure_counts[device_id] >= self.config.failure_threshold:
                self._set_circuit_state(device_id, CircuitState.OPEN)
        elif state == CircuitState.HALF_OPEN:
            # Failed during half-open, go back to open
            self._set_circuit_state(device_id, CircuitState.OPEN)
            self.success_counts[device_id] = 0
    
    def _initialize_metrics(self, device_id: int) -> None:
        """Initialize metrics for a device"""
        if device_id not in self.metrics:
            self.metrics[device_id] = ConnectionMetrics(
                connection_time_ms=0.0,
                last_successful_ping=None,
                total_attempts=0,
                successful_attempts=0,
                failed_attempts=0,
                avg_response_time_ms=0.0,
                last_error=None,
                uptime_percentage=0.0
            )
    
    def _update_connection_metrics(self, device_id: int, connection_time_ms: float, success: bool) -> None:
        """Update connection performance metrics"""
        self._initialize_metrics(device_id)
        metrics = self.metrics[device_id]
        
        metrics.total_attempts += 1
        if success:
            metrics.successful_attempts += 1
            metrics.connection_time_ms = connection_time_ms
            
            # Update average response time
            if metrics.avg_response_time_ms == 0:
                metrics.avg_response_time_ms = connection_time_ms
            else:
                metrics.avg_response_time_ms = (metrics.avg_response_time_ms + connection_time_ms) / 2
        
        # Calculate uptime percentage
        if metrics.total_attempts > 0:
            metrics.uptime_percentage = (metrics.successful_attempts / metrics.total_attempts) * 100
    
    def _log_device_status(self, device_id: int, status: str, error_message: str = None, metadata: Dict = None) -> None:
        """Log device status to database"""
        try:
            self.cache_service.log_device_status(
                device_id=device_id,
                status=status,
                error_message=error_message,
                metadata=metadata
            )
        except Exception as e:
            print(f"❌ Failed to log device status: {e}")
    
    async def get_device_connection(self, device_id: int, force_reconnect: bool = False) -> Optional[Any]:
        """
        Get ZKTeco device connection with circuit breaker protection
        
        Args:
            device_id: Device ID to connect to
            force_reconnect: Force new connection even if one exists
            
        Returns:
            ZK connection object if successful, None otherwise
        """
        # Check circuit breaker
        if not self._should_attempt_connection(device_id):
            print(f"🚫 Device {device_id} connection blocked by circuit breaker")
            return None
        
        # Return existing connection if available and not forcing reconnect
        if not force_reconnect and device_id in self.active_connections:
            conn = self.active_connections[device_id]
            if await self._test_connection(conn):
                return conn
            else:
                # Connection is stale, remove it
                del self.active_connections[device_id]
        
        # Get device configuration
        device = self.db.query(Device).filter(Device.id == device_id).first()
        if not device:
            print(f"❌ Device {device_id} not found in database")
            return None
        
        return await self._create_new_connection(device)
    
    async def _create_new_connection(self, device: Device) -> Optional[Any]:
        """Create new ZKTeco device connection"""
        start_time = time.time()
        
        try:
            print(f"🔌 Attempting connection to device {device.id} at {device.ip_address}:{device.port}")
            
            # Initialize ZK connection
            zk = ZK(device.ip_address, port=device.port, timeout=self.config.request_timeout, password=device.password)
            
            # Attempt connection
            conn = zk.connect()
            
            if conn:
                connection_time_ms = (time.time() - start_time) * 1000
                
                # Test the connection
                if await self._test_connection(conn):
                    # Store active connection
                    self.active_connections[device.id] = conn
                    
                    # Record success
                    self._record_success(device.id)
                    self._update_connection_metrics(device.id, connection_time_ms, True)
                    
                    # Log success
                    self._log_device_status(
                        device.id, 
                        ConnectionState.CONNECTED.value,
                        metadata={
                            "connection_time_ms": connection_time_ms,
                            "ip_address": device.ip_address,
                            "port": device.port
                        }
                    )
                    
                    print(f"✅ Connected to device {device.id} in {connection_time_ms:.1f}ms")
                    return conn
                else:
                    # Connection failed test
                    conn.disconnect()
                    raise Exception("Connection test failed")
            else:
                raise Exception("Failed to establish connection")
        
        except Exception as e:
            connection_time_ms = (time.time() - start_time) * 1000
            error_message = str(e)
            
            # Record failure
            self._record_failure(device.id, error_message)
            self._update_connection_metrics(device.id, connection_time_ms, False)
            
            # Log failure
            self._log_device_status(
                device.id,
                ConnectionState.ERROR.value,
                error_message=error_message,
                metadata={
                    "connection_attempt_time_ms": connection_time_ms,
                    "ip_address": device.ip_address,
                    "port": device.port,
                    "circuit_state": self._get_circuit_state(device.id).value
                }
            )
            
            print(f"❌ Failed to connect to device {device.id}: {error_message}")
            return None
    
    async def _test_connection(self, conn: Any) -> bool:
        """Test if connection is still alive and responsive"""
        try:
            if conn is None:
                return False
            
            # Try to get device info as a connection test
            # This is a lightweight operation that will fail if connection is dead
            conn.get_time()
            return True
        except Exception:
            return False
    
    async def health_check(self, device_id: int) -> Dict[str, Any]:
        """
        Perform comprehensive health check on device
        
        Returns:
            Dictionary with health check results
        """
        start_time = time.time()
        health_data = {
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
            "healthy": False,
            "circuit_state": self._get_circuit_state(device_id).value,
            "connection_state": ConnectionState.UNKNOWN.value,
            "response_time_ms": 0,
            "tests": {},
            "metrics": None,
            "error": None
        }
        
        try:
            # Get connection
            conn = await self.get_device_connection(device_id)
            if not conn:
                health_data["error"] = "Could not establish connection"
                health_data["connection_state"] = ConnectionState.DISCONNECTED.value
                return health_data
            
            health_data["connection_state"] = ConnectionState.CONNECTED.value
            
            # Test 1: Basic connectivity (get device time)
            test_start = time.time()
            try:
                device_time = conn.get_time()
                health_data["tests"]["time_sync"] = {
                    "passed": True,
                    "device_time": device_time.isoformat() if device_time else None,
                    "response_time_ms": (time.time() - test_start) * 1000
                }
            except Exception as e:
                health_data["tests"]["time_sync"] = {
                    "passed": False,
                    "error": str(e),
                    "response_time_ms": (time.time() - test_start) * 1000
                }
            
            # Test 2: User count check
            test_start = time.time()
            try:
                users = conn.get_users()
                user_count = len(users) if users else 0
                health_data["tests"]["user_data"] = {
                    "passed": True,
                    "user_count": user_count,
                    "response_time_ms": (time.time() - test_start) * 1000
                }
            except Exception as e:
                health_data["tests"]["user_data"] = {
                    "passed": False,
                    "error": str(e),
                    "response_time_ms": (time.time() - test_start) * 1000
                }
            
            # Test 3: Attendance record count
            test_start = time.time()
            try:
                attendances = conn.get_attendance()
                attendance_count = len(attendances) if attendances else 0
                health_data["tests"]["attendance_data"] = {
                    "passed": True,
                    "record_count": attendance_count,
                    "response_time_ms": (time.time() - test_start) * 1000
                }
            except Exception as e:
                health_data["tests"]["attendance_data"] = {
                    "passed": False,
                    "error": str(e),
                    "response_time_ms": (time.time() - test_start) * 1000
                }
            
            # Calculate overall health
            total_time = time.time() - start_time
            health_data["response_time_ms"] = total_time * 1000
            
            passed_tests = sum(1 for test in health_data["tests"].values() if test["passed"])
            total_tests = len(health_data["tests"])
            health_data["healthy"] = passed_tests == total_tests and total_time < 30  # 30 second max
            
            # Include current metrics
            if device_id in self.metrics:
                metrics = self.metrics[device_id]
                health_data["metrics"] = {
                    "uptime_percentage": metrics.uptime_percentage,
                    "avg_response_time_ms": metrics.avg_response_time_ms,
                    "total_attempts": metrics.total_attempts,
                    "successful_attempts": metrics.successful_attempts,
                    "failed_attempts": metrics.failed_attempts,
                    "last_successful_ping": metrics.last_successful_ping.isoformat() if metrics.last_successful_ping else None
                }
            
            # Record health check result
            self._record_success(device_id) if health_data["healthy"] else self._record_failure(device_id, "Health check failed")
            
            # Log health status
            self._log_device_status(
                device_id,
                "healthy" if health_data["healthy"] else "unhealthy",
                error_message=health_data.get("error"),
                metadata={
                    "health_score": f"{passed_tests}/{total_tests}",
                    "response_time_ms": health_data["response_time_ms"],
                    "tests": health_data["tests"]
                }
            )
            
        except Exception as e:
            health_data["error"] = str(e)
            health_data["connection_state"] = ConnectionState.ERROR.value
            self._record_failure(device_id, str(e))
        
        return health_data
    
    def disconnect_device(self, device_id: int) -> bool:
        """Disconnect from device and clean up connection"""
        try:
            if device_id in self.active_connections:
                conn = self.active_connections[device_id]
                conn.disconnect()
                del self.active_connections[device_id]
                
                self._log_device_status(device_id, ConnectionState.DISCONNECTED.value)
                print(f"🔌 Disconnected from device {device_id}")
                return True
            
            return False
        except Exception as e:
            print(f"❌ Error disconnecting from device {device_id}: {e}")
            return False
    
    def get_connection_status(self, device_id: int) -> Dict[str, Any]:
        """Get current connection status and metrics"""
        return {
            "device_id": device_id,
            "connected": device_id in self.active_connections,
            "circuit_state": self._get_circuit_state(device_id).value,
            "failure_count": self.failure_counts.get(device_id, 0),
            "last_failure": self.last_failure_times.get(device_id),
            "metrics": self.metrics.get(device_id),
            "state_change_time": self.state_change_times.get(device_id)
        }
    
    def reset_circuit_breaker(self, device_id: int) -> bool:
        """Manually reset circuit breaker for device"""
        try:
            self._set_circuit_state(device_id, CircuitState.CLOSED)
            self.failure_counts[device_id] = 0
            self.success_counts[device_id] = 0
            
            print(f"🔄 Circuit breaker reset for device {device_id}")
            return True
        except Exception as e:
            print(f"❌ Error resetting circuit breaker for device {device_id}: {e}")
            return False
    
    def cleanup_inactive_connections(self) -> int:
        """Clean up inactive/stale connections"""
        cleaned_count = 0
        
        for device_id in list(self.active_connections.keys()):
            conn = self.active_connections[device_id]
            
            # Test if connection is still alive
            if not asyncio.run(self._test_connection(conn)):
                try:
                    conn.disconnect()
                except:
                    pass  # Connection might already be dead
                
                del self.active_connections[device_id]
                cleaned_count += 1
                
                self._log_device_status(device_id, ConnectionState.DISCONNECTED.value, error_message="Connection cleanup - stale connection")
        
        if cleaned_count > 0:
            print(f"🧹 Cleaned up {cleaned_count} inactive connections")
        
        return cleaned_count


# Convenience function
def get_connection_manager(db: Session, config: CircuitBreakerConfig = None) -> DeviceConnectionManager:
    """Get a device connection manager instance"""
    return DeviceConnectionManager(db, config)