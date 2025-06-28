#!/usr/bin/env python3
"""
Debug script to see what data is available and why it's being filtered
"""

from zk import ZK
from datetime import datetime, timedelta
import csv

# Thai employees we know exist
KNOWN_THAI_EMPLOYEES = {
    '105': 'ไกด์', '106': 'พราว', '107': 'ดรีม', '109': 'ช่างเก่ง', 
    '123': 'น้อยโหน่ง', '421': 'วิณัฐ', '1188': 'Employee 1188',
    '2522': 'หมวย', '2537': 'รีวิว', '2541': 'สะเบ้นซ์', '2559': 'พี่หญิง'
}

def debug_attendance():
    print("=== Debugging Attendance Data ===")
    
    try:
        zk = ZK("192.168.100.209", port=4370, timeout=3)
        conn = zk.connect()
        
        print("✅ Connected to device")
        
        # Get all attendance records
        records = conn.get_attendance()
        print(f"📊 Total records in device: {len(records)}")
        
        # Check recent records
        today = datetime.now().date()
        last_week = today - timedelta(days=7)
        
        recent_records = []
        thai_employee_records = {}
        
        for record in records[-100:]:  # Check last 100 records
            user_id = str(record.user_id)
            timestamp = record.timestamp
            
            # Check if it's a Thai employee
            if user_id in KNOWN_THAI_EMPLOYEES:
                employee_name = KNOWN_THAI_EMPLOYEES[user_id]
                
                if employee_name not in thai_employee_records:
                    thai_employee_records[employee_name] = []
                
                thai_employee_records[employee_name].append({
                    'user_id': user_id,
                    'timestamp': timestamp,
                    'date': timestamp.strftime("%Y-%m-%d"),
                    'time': timestamp.strftime("%H:%M:%S"),
                    'status': record.status
                })
        
        print(f"\n🇹🇭 Thai employees with recent records:")
        for name, records in thai_employee_records.items():
            latest = records[-1] if records else None
            if latest:
                print(f"  - {name}: {len(records)} records, latest: {latest['date']} {latest['time']}")
        
        print(f"\n📅 Date analysis of last 10 records:")
        for record in records[-10:]:
            user_id = str(record.user_id)
            employee_name = KNOWN_THAI_EMPLOYEES.get(user_id, f"Employee {user_id}")
            print(f"  {employee_name}: {record.timestamp} (User ID: {user_id})")
        
        conn.disconnect()
        
        if thai_employee_records:
            print(f"\n✅ Found {len(thai_employee_records)} Thai employees with data")
            return True
        else:
            print(f"\n❌ No Thai employee data found")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    debug_attendance()