#!/usr/bin/env python3
"""
ZKTeco Device Connection PoC
Tests basic connectivity to a ZKTeco biometric device using IP address
"""

import sys
import argparse

try:
    from zk import ZK
except ImportError:
    print("Error: pyzk library is not installed.")
    print("\nTo install dependencies, run:")
    print("  1. sudo apt install python3-venv python3-pip")
    print("  2. python3 -m venv venv")
    print("  3. source venv/bin/activate")
    print("  4. pip install -r requirements.txt")
    print("\nOr install pyzk directly:")
    print("  sudo apt install python3-pip")
    print("  pip3 install pyzk")
    sys.exit(1)


def test_connection(ip_address, port=4370, timeout=5):
    """
    Test connection to ZKTeco device
    
    Args:
        ip_address: Device IP address
        port: Device port (default: 4370)
        timeout: Connection timeout in seconds
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    conn = None
    zk = ZK(ip_address, port=port, timeout=timeout)
    
    try:
        print(f"Attempting to connect to device at {ip_address}:{port}...")
        conn = zk.connect()
        
        print("✓ Connection successful!")
        print(f"  Device IP: {ip_address}")
        print(f"  Port: {port}")
        
        # Try to get basic device info to verify connection is working
        print("\nDevice Information:")
        print(f"  Firmware Version: {conn.get_firmware_version()}")
        print(f"  Device Name: {conn.get_device_name()}")
        print(f"  Serial Number: {conn.get_serialnumber()}")
        
        return True
        
    except Exception as e:
        print(f"✗ Connection failed!")
        print(f"  Error: {type(e).__name__}: {e}")
        return False
        
    finally:
        if conn:
            try:
                conn.disconnect()
                print("\n✓ Disconnected successfully")
            except Exception as e:
                print(f"\n✗ Error during disconnect: {e}")


def main():
    parser = argparse.ArgumentParser(description="Test connection to ZKTeco device")
    parser.add_argument("ip", help="Device IP address")
    parser.add_argument("-p", "--port", type=int, default=4370, help="Device port (default: 4370)")
    parser.add_argument("-t", "--timeout", type=int, default=5, help="Connection timeout in seconds (default: 5)")
    
    args = parser.parse_args()
    
    print("=== ZKTeco Device Connection Test ===\n")
    
    success = test_connection(args.ip, args.port, args.timeout)
    
    print("\n" + "="*36)
    if success:
        print("Result: CONNECTION SUCCESSFUL")
        sys.exit(0)
    else:
        print("Result: CONNECTION FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()