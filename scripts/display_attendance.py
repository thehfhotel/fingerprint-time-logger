#!/usr/bin/env python3
"""
Display attendance records from ZKTeco device
Shows recent attendance logs with employee information
"""

from zk import ZK
import sys
import argparse
from datetime import datetime, timedelta
from collections import defaultdict


def get_attendance_data(ip_address, port=4370, timeout=5, days_back=7):
    """
    Retrieve and display attendance data from ZKTeco device
    
    Args:
        ip_address: Device IP address
        port: Device port (default: 4370)
        timeout: Connection timeout in seconds
        days_back: Number of days to look back for attendance records
    """
    conn = None
    zk = ZK(ip_address, port=port, timeout=timeout)
    
    try:
        print(f"Connecting to device at {ip_address}:{port}...")
        conn = zk.connect()
        print("✓ Connected successfully!\n")
        
        # Get device info
        print("=== DEVICE INFORMATION ===")
        print(f"Device Name: {conn.get_device_name()}")
        print(f"Serial Number: {conn.get_serialnumber()}")
        print(f"Firmware Version: {conn.get_firmware_version()}")
        
        # Get users
        print("\n=== REGISTERED USERS ===")
        users = conn.get_users()
        user_dict = {user.user_id: user for user in users}
        print(f"Total registered users: {len(users)}")
        
        # Display first 10 users
        print("\nSample users (first 10):")
        for i, user in enumerate(users[:10]):
            print(f"  {i+1}. ID: {user.user_id}, Name: {user.name}, Card: {user.card}, Admin: {user.privilege}")
        
        # Get attendance records
        print(f"\n=== ATTENDANCE RECORDS (Last {days_back} days) ===")
        attendances = conn.get_attendance()
        
        # Filter by date
        cutoff_date = datetime.now() - timedelta(days=days_back)
        recent_attendances = [att for att in attendances if att.timestamp >= cutoff_date]
        
        print(f"Total records in device: {len(attendances)}")
        print(f"Records in last {days_back} days: {len(recent_attendances)}")
        
        if recent_attendances:
            # Sort by timestamp
            recent_attendances.sort(key=lambda x: x.timestamp, reverse=True)
            
            # Group by date
            attendance_by_date = defaultdict(list)
            for att in recent_attendances:
                date_key = att.timestamp.strftime("%Y-%m-%d")
                attendance_by_date[date_key].append(att)
            
            # Display by date
            for date_str in sorted(attendance_by_date.keys(), reverse=True):
                print(f"\n--- {date_str} ---")
                daily_records = attendance_by_date[date_str]
                
                # Group by user for this date
                user_records = defaultdict(list)
                for att in daily_records:
                    user_records[att.user_id].append(att)
                
                for user_id, records in user_records.items():
                    user = user_dict.get(user_id)
                    user_name = user.name if user else f"Unknown (ID: {user_id})"
                    
                    # Sort records by time for this user
                    records.sort(key=lambda x: x.timestamp)
                    
                    print(f"\n  {user_name}:")
                    for att in records:
                        punch_type = "Check-in" if att.punch in [0, 1] else "Check-out"
                        time_str = att.timestamp.strftime("%H:%M:%S")
                        status = f"Status: {att.status}" if att.status else ""
                        print(f"    {time_str} - {punch_type} {status}")
                
        else:
            print("\nNo attendance records found in the specified time period.")
        
        # Display summary statistics
        print("\n=== SUMMARY STATISTICS ===")
        if recent_attendances:
            unique_users = len(set(att.user_id for att in recent_attendances))
            print(f"Unique users with attendance: {unique_users}")
            
            # Count by punch type
            punch_counts = defaultdict(int)
            for att in recent_attendances:
                punch_counts[att.punch] += 1
            
            print("\nPunch type distribution:")
            for punch, count in sorted(punch_counts.items()):
                print(f"  Type {punch}: {count} records")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Error occurred!")
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
    parser = argparse.ArgumentParser(description="Display attendance records from ZKTeco device")
    parser.add_argument("ip", help="Device IP address")
    parser.add_argument("-p", "--port", type=int, default=4370, help="Device port (default: 4370)")
    parser.add_argument("-t", "--timeout", type=int, default=5, help="Connection timeout in seconds (default: 5)")
    parser.add_argument("-d", "--days", type=int, default=7, help="Number of days to look back (default: 7)")
    
    args = parser.parse_args()
    
    print("=== ZKTeco Attendance Display ===\n")
    
    success = get_attendance_data(args.ip, args.port, args.timeout, args.days)
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()