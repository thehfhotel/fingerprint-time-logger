#!/usr/bin/env python3
"""
Lightweight Employee Time Log Dashboard
Real-time attendance monitoring with minimal resource usage
"""

import csv
import json
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
from zk import ZK

app = Flask(__name__)
app.config['SECRET_KEY'] = 'attendance-dashboard-2025'
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuration - Optimized for minimal device strain
DEVICE_IP = "192.168.100.209"
DEVICE_PORT = 4370
UPDATE_INTERVAL = 120  # seconds (reduced from 30s to minimize device load)
USERID_CSV = "userid.csv"
DEVICE_TIMEOUT = 3  # seconds (reduced from 5s for faster operations)
MAX_RETRIES = 2  # Maximum connection retries
CACHE_DURATION = 300  # Cache data for 5 minutes

# Global data storage - Optimized with caching
employee_names = {}
attendance_data = {}
last_update = None
device_status = {"connected": False, "last_sync": None}
data_cache = {"last_record_count": 0, "last_cache_time": 0}
performance_stats = {"sync_time": 0, "record_count": 0, "errors": 0}

def load_employee_names():
    """Load employee name mappings from CSV - only employees with Thai names"""
    global employee_names
    try:
        with open(USERID_CSV, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                # Use Badgenumber to match with device user_id
                badge_number = row['Badgenumber'].strip()
                userid = row['USERID'].strip()
                
                # Only use employees with Thai names (ชื่อ column)
                thai_name = row['ชื่อ'].strip() if row['ชื่อ'] else ''
                
                # Only include employees with Thai names
                if thai_name:
                    # Map both badge number and userid to the Thai name
                    employee_names[badge_number] = thai_name
                    if badge_number != userid:
                        employee_names[userid] = thai_name
                    
        print(f"Loaded {len(employee_names)} employee name mappings (Thai names only)")
        print(f"Sample Thai employee mappings: {dict(list(employee_names.items())[:5])}")
    except Exception as e:
        print(f"Error loading employee names: {e}")
        employee_names = {}

def is_realistic_date(timestamp):
    """Check if a timestamp is realistic (within reasonable bounds)"""
    current_year = datetime.now().year
    record_year = timestamp.year
    
    # Temporarily allow 2065 dates until device time is properly synced
    # Consider dates realistic if they are:
    # - From 2020 onwards (past 5 years)
    # - Not more than 50 years in future (allows 2065 device dates)
    return (current_year - 5) <= record_year <= (current_year + 50)

def check_and_sync_device_time(conn):
    """Check device time and sync if necessary"""
    try:
        device_time = conn.get_time()
        server_time = datetime.now()
        time_diff = abs((device_time - server_time).total_seconds())
        
        # If time difference is more than 60 seconds, sync the device
        if time_diff > 60:
            print(f"Device time drift detected: {time_diff:.1f} seconds")
            print(f"Device time: {device_time}")
            print(f"Server time: {server_time}")
            print("Attempting to sync device time...")
            
            try:
                # Disable device to prevent user activity during time sync
                conn.disable_device()
                print("Device disabled for time sync...")
                
                # Set new time
                conn.set_time(server_time)
                
                # Verify the time was set correctly
                new_device_time = conn.get_time()
                new_diff = abs((new_device_time - server_time).total_seconds())
                
                # Re-enable device
                conn.enable_device()
                print("Device re-enabled after time sync")
                
                print(f"Time sync completed. New difference: {new_diff:.1f} seconds")
                return True, f"Time synced successfully (was {time_diff:.1f}s off)"
            except Exception as sync_error:
                try:
                    # Ensure device is re-enabled even if sync fails
                    conn.enable_device()
                    print("Device re-enabled after sync failure")
                except:
                    pass
                print(f"Failed to sync device time: {sync_error}")
                return False, f"Time sync failed: {str(sync_error)}"
        else:
            return True, f"Device time is accurate (diff: {time_diff:.1f}s)"
            
    except Exception as e:
        print(f"Error checking device time: {e}")
        return False, f"Time check failed: {str(e)}"

def is_data_fresh():
    """Check if cached data is still fresh to avoid unnecessary device queries"""
    import time
    current_time = time.time()
    return (current_time - data_cache.get("last_cache_time", 0)) < CACHE_DURATION

def get_device_data():
    """Fetch attendance data from ZKTeco device - Optimized for minimal device strain"""
    global attendance_data, device_status, last_update, data_cache, performance_stats
    
    print("🚀 get_device_data() called")
    sync_start_time = time.time()
    
    try:
        # Use shorter timeout and efficient connection settings
        zk = ZK(DEVICE_IP, port=DEVICE_PORT, timeout=DEVICE_TIMEOUT, 
               force_udp=False, ommit_ping=True)  # Skip ping for faster connection
        conn = zk.connect()
        
        device_status["connected"] = True
        device_status["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Get attendance records efficiently
        attendance_records = conn.get_attendance()
        
        # Quick check: if record count hasn't changed, skip processing
        current_record_count = len(attendance_records)
        if (current_record_count == data_cache.get("last_record_count", 0) and 
            is_data_fresh()):
            conn.disconnect()
            print(f"📊 Data unchanged ({current_record_count} records), using cache")
            return
            
        data_cache["last_record_count"] = current_record_count
        data_cache["last_cache_time"] = time.time()
        
        # Process and group attendance data - SHOW ALL DATA WITHOUT FILTERS
        print(f"🔍 Processing {len(attendance_records)} records (NO FILTERS)")
        
        # All attendance records in a single consolidated list
        all_attendance_records = []
        
        # Enhanced Thai employees mapping with more comprehensive list
        thai_names = {
            '105': 'ไกด์', '106': 'พราว', '107': 'ดรีม', '109': 'ช่างเก่ง', 
            '123': 'น้อยโหน่ง', '421': 'วิณัฐ', '1188': 'พนักงาน 1188',
            '2522': 'หมวย', '2537': 'รีวิว', '2541': 'สะเบ้นซ์', '2559': 'พี่หญิง',
            '37': 'จิ๋ม', '22': 'พรทิพย์', '10468': 'พนักงาน 10468'
        }
        
        processed_count = 0
        for record in attendance_records:
            timestamp = record.timestamp
            user_id = str(record.user_id)
            processed_count += 1
            
            # Get employee name - prioritize Thai names, but show ALL employees
            if user_id in employee_names and employee_names[user_id]:
                employee_name = employee_names[user_id]
            elif user_id in thai_names:
                employee_name = thai_names[user_id]
            else:
                employee_name = f"พนักงาน {user_id}"  # Default Thai format
            
            # Handle irregular dates by showing raw timestamp info
            try:
                formatted_date = timestamp.strftime("%Y-%m-%d")
                formatted_time = timestamp.strftime("%H:%M:%S")
                date_display = formatted_date
            except:
                # Handle irregular dates
                formatted_date = "IRREGULAR"
                formatted_time = str(timestamp)
                date_display = f"⚠️ {str(timestamp)}"
            
            # Create attendance entry with all information (JSON serializable)
            attendance_entry = {
                "employee_name": employee_name,
                "employee_id": user_id,
                "time": formatted_time,
                "date": formatted_date,
                "date_display": date_display,
                "status": "Check-in" if record.status == 1 else "Check-out",
                "punch_type": getattr(record, 'punch', 'Unknown'),
                "timestamp_str": str(timestamp),  # Convert datetime to string for JSON
                "full_datetime": f"{formatted_date} {formatted_time}"
            }
            
            all_attendance_records.append(attendance_entry)
            
            if processed_count <= 10:  # Show first 10 records being processed
                print(f"✅ Processing: {employee_name} (ID: {user_id}) - {timestamp}")
        
        # Sort ALL records by full datetime string (most recent first)
        all_attendance_records.sort(
            key=lambda x: x.get('full_datetime', '1900-01-01 00:00:00'),
            reverse=True
        )
        
        # Create consolidated view - all records in one place
        attendance_data = {
            "All Employees (Consolidated)": all_attendance_records[:100]  # Show top 100 most recent
        }
        
        print(f"📊 Processed {processed_count} total records")
        print(f"📋 Showing {len(all_attendance_records[:100])} most recent records")
        
        # Set total_processed for performance stats
        total_processed = len(all_attendance_records[:100])
        last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Check and sync device time BEFORE disconnecting
        time_sync_success, time_sync_message = check_and_sync_device_time(conn)
        
        conn.disconnect()
        
        # Log filtering statistics
        total_processed = sum(len(records) for records in attendance_data.values())
        # Update performance statistics
        sync_end_time = time.time()
        performance_stats["sync_time"] = sync_end_time - sync_start_time
        performance_stats["record_count"] = total_processed
        
        print(f"⚡ Data processing complete ({performance_stats['sync_time']:.1f}s):")
        print(f"  - {len(attendance_data)} consolidated view created")
        print(f"  - {total_processed} total records processed (ALL DATA - NO FILTERS)")
        print(f"  - Showing {len(all_attendance_records[:100])} most recent records")
        print(f"  - {time_sync_message}")
        print(f"  - Device load: {performance_stats['sync_time']:.1f}s connection time")
        
        # Update device status and performance stats
        if 'error' in device_status:
            del device_status['error']
        device_status['performance'] = {
            'sync_time': performance_stats['sync_time'],
            'record_count': performance_stats['record_count'],
            'last_sync_duration': f"{performance_stats['sync_time']:.1f}s"
        }
        
        # Update device status with time sync info
        device_status['time_sync'] = {
            'success': time_sync_success,
            'message': time_sync_message
        }
        
        # Emit update to connected clients
        socketio.emit('attendance_update', {
            'data': attendance_data,
            'last_update': last_update,
            'device_status': device_status,
            'stats': {
                'total_processed': total_processed,
                'filtered_count': filtered_count,
                'thai_employees_only': True
            }
        })
        
    except Exception as e:
        device_status["connected"] = False
        device_status["error"] = str(e)
        performance_stats["errors"] += 1
        print(f"❌ Error fetching device data: {e}")
        print(f"🔄 Will retry in {UPDATE_INTERVAL} seconds")
        
        # If connection keeps failing, increase retry interval temporarily
        if performance_stats["errors"] > 3:
            print(f"⚠️  Multiple connection failures detected. Consider checking device status.")

def background_updater():
    """Background thread to update attendance data"""
    while True:
        get_device_data()
        time.sleep(UPDATE_INTERVAL)

@app.route('/')
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/api/attendance')
def api_attendance():
    """API endpoint for attendance data"""
    return jsonify({
        'data': attendance_data,
        'last_update': last_update,
        'device_status': device_status,
        'total_employees': len(attendance_data),
        'total_records': sum(len(records) for records in attendance_data.values())
    })

@app.route('/api/refresh', methods=['POST'])
def api_manual_refresh():
    """Manual refresh endpoint"""
    try:
        print("🔄 Manual refresh API endpoint called")
        print("🔄 Manual refresh triggered - bypassing cache")
        # Clear cache to force refresh
        global data_cache
        data_cache["last_cache_time"] = 0
        data_cache["last_record_count"] = -1
        
        print("🔄 About to call get_device_data()")
        get_device_data()
        print("🔄 get_device_data() completed")
        
        result = {
            'success': True,
            'message': 'Data refreshed successfully',
            'last_update': last_update,
            'total_employees': len(attendance_data)
        }
        print(f"🔄 Returning result: {result}")
        return jsonify(result)
    except Exception as e:
        print(f"❌ Manual refresh failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'Refresh failed: {str(e)}'
        }), 500

@socketio.on('connect')
def on_connect(auth):
    """Handle client connection"""
    emit('attendance_update', {
        'data': attendance_data,
        'last_update': last_update,
        'device_status': device_status
    })

if __name__ == '__main__':
    print("=== Employee Time Log Dashboard ===")
    print("Loading employee name mappings...")
    load_employee_names()
    
    print("Starting background data updater...")
    updater_thread = threading.Thread(target=background_updater, daemon=True)
    updater_thread.start()
    
    print("Starting web server...")
    print("Dashboard will be available at: http://localhost:5000")
    
    # Initial data fetch
    get_device_data()
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)