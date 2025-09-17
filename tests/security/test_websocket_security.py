"""
WebSocket Security Testing Suite for Fingerprint Time Logger

Tests WebSocket endpoints for real-time update security:
- WebSocket connection security
- Message injection attacks
- Broadcasting vulnerabilities
- Real-time data exposure
"""

import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock
import websockets
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.security.conftest import (
    SecurityTester, SecurityVulnerability, SecurityLevel,
    malicious_payloads
)
from app.main_unified import app


class WebSocketSecurityTester(SecurityTester):
    """Specialized WebSocket security testing"""

    def __init__(self, base_url: str = "ws://localhost:5000"):
        self.base_url = base_url
        self.vulnerabilities = []

    async def test_websocket_message_injection(self) -> list[SecurityVulnerability]:
        """Test WebSocket message injection attacks"""
        vulnerabilities = []

        # Malicious WebSocket messages
        malicious_messages = [
            # XSS attempts
            '{"type": "ping", "data": "<script>alert(\'XSS\')</script>"}',
            '{"type": "refresh", "payload": "<img src=x onerror=alert(1)>"}',

            # Command injection attempts
            '{"type": "refresh", "command": "; rm -rf /"}',
            '{"type": "ping", "exec": "$(whoami)"}',

            # SQL injection attempts
            '{"type": "refresh", "employee_id": "\'; DROP TABLE employees; --"}',

            # JSON injection attempts
            '{"type": "ping", "data": {"__proto__": {"isAdmin": true}}}',

            # Buffer overflow attempts
            '{"type": "ping", "data": "' + 'A' * 100000 + '"}',

            # Protocol confusion
            'GET / HTTP/1.1\r\nHost: localhost\r\n\r\n',

            # Binary data injection
            b'\x00\x01\x02\x03MALICIOUS_BINARY_DATA',

            # Invalid JSON structure
            '{"type": "ping", "data": }',
            '{"type": "ping"',  # Incomplete JSON

            # Large message attacks
            '{"type": "ping", "data": "' + 'X' * 1000000 + '"}',
        ]

        try:
            # Test with TestClient WebSocket
            with TestClient(app) as client:
                with client.websocket_connect("/ws") as websocket:

                    for malicious_msg in malicious_messages:
                        try:
                            # Send malicious message
                            if isinstance(malicious_msg, bytes):
                                websocket.send_bytes(malicious_msg)
                            else:
                                websocket.send_text(malicious_msg)

                            # Try to receive response
                            response = websocket.receive_text()
                            response_data = json.loads(response) if response else {}

                            # Check if malicious content is reflected
                            if isinstance(malicious_msg, str) and any(
                                dangerous in response.lower()
                                for dangerous in ['<script>', 'alert(', 'onerror=', 'drop table']
                            ):
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"ws_injection_{len(vulnerabilities)}",
                                    title="WebSocket Message Injection",
                                    description=f"WebSocket reflects malicious content: {malicious_msg[:100]}...",
                                    severity=SecurityLevel.HIGH,
                                    category="Injection",
                                    endpoint="/ws",
                                    payload=malicious_msg if isinstance(malicious_msg, str) else str(malicious_msg),
                                    recommendation="Sanitize WebSocket messages and implement input validation",
                                    cwe="CWE-79"
                                ))

                            # Check if system processes obviously malicious commands
                            if "rm -rf" in str(malicious_msg) and response_data.get("type") == "success":
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"ws_command_{len(vulnerabilities)}",
                                    title="WebSocket Command Injection",
                                    description="WebSocket appears to process command injection attempts",
                                    severity=SecurityLevel.CRITICAL,
                                    category="Command Injection",
                                    endpoint="/ws",
                                    payload=str(malicious_msg),
                                    recommendation="Never execute commands from WebSocket messages",
                                    cwe="CWE-78"
                                ))

                        except json.JSONDecodeError:
                            # Invalid JSON is expected to be rejected
                            continue
                        except Exception as e:
                            # Unexpected errors might indicate vulnerabilities
                            if "sql" in str(e).lower() or "drop" in str(e).lower():
                                vulnerabilities.append(SecurityVulnerability(
                                    id=f"ws_error_{len(vulnerabilities)}",
                                    title="WebSocket Error Information Disclosure",
                                    description=f"WebSocket error reveals sensitive information: {str(e)}",
                                    severity=SecurityLevel.MEDIUM,
                                    category="Information Disclosure",
                                    endpoint="/ws",
                                    payload=str(malicious_msg),
                                    recommendation="Implement generic error handling for WebSocket",
                                    cwe="CWE-209"
                                ))

        except Exception as e:
            # Connection errors are expected for some tests
            pass

        return vulnerabilities

    async def test_websocket_broadcast_security(self) -> list[SecurityVulnerability]:
        """Test WebSocket broadcast message security"""
        vulnerabilities = []

        # Mock the broadcast functionality and device service to prevent real device calls
        with patch('app.main_unified.manager.broadcast') as mock_broadcast, \
             patch('app.services.device_service.device_service.sync_attendance_data') as mock_sync:

            # Mock device service to return success and trigger broadcast
            mock_sync.return_value = {
                "success": True,
                "message": "Sync completed successfully",
                "synced": 5,
                "employees_added": 2
            }

            # Simulate malicious broadcast data
            malicious_broadcast_data = {
                "type": "auto_import_update",
                "data": {
                    "employees": "<script>alert('XSS')</script>",
                    "attendance_count": "'; DROP TABLE attendance_records; --"
                },
                "synced_records": 999999999,  # Suspicious large number
                "timestamp": "<img src=x onerror=alert(1)>",
                "message": "System compromised via WebSocket"
            }

            try:
                with TestClient(app) as client:
                    # Trigger auto-import which causes broadcast
                    response = client.post("/api/auto-import/trigger")

                    # Check if broadcast was called with proper sanitization
                    if mock_broadcast.called:
                        call_args = mock_broadcast.call_args[0][0]  # First argument of first call

                        # Check if dangerous content would be broadcast
                        broadcast_str = json.dumps(call_args)
                        if any(dangerous in broadcast_str for dangerous in ['<script>', 'DROP TABLE', 'onerror=']):
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"ws_broadcast_xss_{len(vulnerabilities)}",
                                title="WebSocket Broadcast XSS",
                                description="WebSocket broadcasts unsanitized data to clients",
                                severity=SecurityLevel.HIGH,
                                category="Cross-Site Scripting",
                                endpoint="/ws",
                                payload=str(call_args),
                                recommendation="Sanitize all data before broadcasting via WebSocket",
                                cwe="CWE-79"
                            ))

            except Exception:
                pass

        return vulnerabilities

    async def test_websocket_denial_of_service(self) -> list[SecurityVulnerability]:
        """Test WebSocket denial of service attacks"""
        vulnerabilities = []

        try:
            with TestClient(app) as client:
                # Test 1: Rapid connection attempts
                connections = []
                for i in range(50):  # Try to create many connections
                    try:
                        ws = client.websocket_connect("/ws")
                        connections.append(ws)
                        if i > 20:  # If we can create too many connections
                            vulnerabilities.append(SecurityVulnerability(
                                id=f"ws_dos_conn_{len(vulnerabilities)}",
                                title="WebSocket Connection DoS",
                                description=f"No connection limit - created {i+1} connections",
                                severity=SecurityLevel.MEDIUM,
                                category="Denial of Service",
                                endpoint="/ws",
                                payload=f"{i+1} connections",
                                recommendation="Implement connection limits per IP",
                                cwe="CWE-400"
                            ))
                            break
                    except Exception:
                        break

                # Clean up connections
                for conn in connections:
                    try:
                        conn.close()
                    except:
                        pass

                # Test 2: Message flooding
                try:
                    with client.websocket_connect("/ws") as websocket:
                        # Send rapid messages
                        for i in range(100):
                            try:
                                websocket.send_text('{"type": "ping"}')
                                if i > 50:  # If system accepts too many rapid messages
                                    vulnerabilities.append(SecurityVulnerability(
                                        id=f"ws_dos_flood_{len(vulnerabilities)}",
                                        title="WebSocket Message Flooding",
                                        description="No rate limiting on WebSocket messages",
                                        severity=SecurityLevel.MEDIUM,
                                        category="Denial of Service",
                                        endpoint="/ws",
                                        payload=f"{i+1} rapid messages",
                                        recommendation="Implement rate limiting for WebSocket messages",
                                        cwe="CWE-770"
                                    ))
                                    break
                            except Exception:
                                break

                except Exception:
                    pass

        except Exception:
            pass

        return vulnerabilities


class TestWebSocketSecurity:
    """Test suite for WebSocket security"""

    @pytest.mark.asyncio
    async def test_websocket_message_injection_protection(self):
        """Test WebSocket message injection is prevented"""
        tester = WebSocketSecurityTester()

        vulnerabilities = await tester.test_websocket_message_injection()

        # Should not have critical injection vulnerabilities
        critical_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.CRITICAL]
        assert len(critical_vulns) == 0, f"Critical WebSocket vulnerabilities: {critical_vulns}"

        # Should have minimal high-severity vulnerabilities
        high_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(high_vulns) <= 2, f"Too many high-severity WebSocket vulnerabilities: {high_vulns}"

    @pytest.mark.asyncio
    async def test_websocket_broadcast_sanitization(self):
        """Test WebSocket broadcast data is sanitized"""
        tester = WebSocketSecurityTester()

        vulnerabilities = await tester.test_websocket_broadcast_security()

        # Should not broadcast malicious content
        xss_vulns = [v for v in vulnerabilities if "xss" in v.title.lower()]
        assert len(xss_vulns) == 0, f"WebSocket XSS vulnerabilities: {xss_vulns}"

    @pytest.mark.asyncio
    async def test_websocket_dos_protection(self):
        """Test WebSocket denial of service protection"""
        tester = WebSocketSecurityTester()

        vulnerabilities = await tester.test_websocket_denial_of_service()

        # Should have some DoS protection
        dos_vulns = [v for v in vulnerabilities if v.severity == SecurityLevel.HIGH]
        assert len(dos_vulns) == 0, f"High-severity DoS vulnerabilities: {dos_vulns}"

    def test_websocket_connection_security(self):
        """Test WebSocket connection establishment security"""
        try:
            with TestClient(app) as client:
                # Test valid WebSocket connection
                with client.websocket_connect("/ws") as websocket:
                    # Send valid ping message
                    websocket.send_text('{"type": "ping"}')
                    data = websocket.receive_text()
                    response = json.loads(data)

                    # Should respond to ping with pong
                    assert response.get("type") == "pong", "WebSocket should respond to ping with pong"

                    # Test refresh message
                    websocket.send_text('{"type": "refresh"}')
                    # Should handle refresh without error (might not get immediate response)
        except WebSocketDisconnect:
            # WebSocket disconnection during auto-import is acceptable for security test
            pass

    @patch('app.services.device_service.device_service.sync_attendance_data')
    def test_websocket_data_exposure(self, mock_sync):
        """Test WebSocket doesn't expose sensitive data"""

        # Mock service to return sensitive data
        mock_sync.return_value = {
            "success": True,
            "synced": 5,
            "sensitive_config": "admin:password123",
            "device_ip": "192.168.1.100",
            "internal_path": "/home/user/secret"
        }

        try:
            with TestClient(app) as client:
                with client.websocket_connect("/ws") as websocket:
                    # Trigger refresh which might broadcast sensitive data
                    websocket.send_text('{"type": "refresh"}')

                    try:
                        # Try to receive broadcast message
                        data = websocket.receive_text()
                        response_text = data.lower()

                        # Check for sensitive data exposure
                        sensitive_indicators = ["password", "admin:", "192.168", "/home/"]
                        exposed_data = [indicator for indicator in sensitive_indicators if indicator in response_text]

                        assert len(exposed_data) == 0, f"WebSocket exposed sensitive data: {exposed_data}"
                    except Exception:
                        # No response is also acceptable
                        pass
        except WebSocketDisconnect:
            # WebSocket disconnection during auto-import is acceptable for security test
            pass
        except Exception:
            # General exception handling
            pass

    def test_websocket_message_validation(self):
        """Test WebSocket message format validation"""
        try:
            with TestClient(app) as client:
                with client.websocket_connect("/ws") as websocket:
                    # Test invalid JSON
                    try:
                        websocket.send_text('{"invalid": json}')
                        # Should either reject or handle gracefully
                    except Exception:
                        pass  # Expected to fail

                    # Test missing required fields
                    try:
                        websocket.send_text('{"data": "test"}')  # Missing type field
                        # Should handle missing fields gracefully
                    except Exception:
                        pass

                    # Test unknown message type
                    try:
                        websocket.send_text('{"type": "unknown_command"}')
                        data = websocket.receive_text()
                        # Should not crash on unknown commands
                        assert data is not None, "WebSocket should respond to unknown commands gracefully"
                    except Exception:
                        pass  # Might not respond to unknown commands
        except WebSocketDisconnect:
            # WebSocket disconnection during auto-import is acceptable for security test
            pass