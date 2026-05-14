#!/usr/bin/env python3
"""
CSV Backup Script for Fingerprint Time Logger Database
Exports employees and attendance records to CSV files.
"""

import csv
import sqlite3
import os
from datetime import datetime, timedelta

# Configuration
DATABASE_PATH = os.path.join(os.path.dirname(__file__), '..', 'database', 'attendance.db')
BACKUP_DIR = os.path.join(os.path.dirname(__file__), '..', 'backups')

def create_backup_dir():
    """Create backup directory if it doesn't exist."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return BACKUP_DIR

def get_timestamp():
    """Get formatted timestamp for filenames."""
    return datetime.now().strftime('%Y%m%d_%H%M%S')

def export_employees(conn, backup_dir, timestamp):
    """Export employees table to CSV."""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT
            id, badge_number, english_name, thai_name, display_name,
            department, position, is_active, is_hidden,
            line_user_id, line_display_name,
            created_at, updated_at
        FROM employees
        ORDER BY badge_number
    ''')

    rows = cursor.fetchall()
    columns = [
        'id', 'badge_number', 'english_name', 'thai_name', 'display_name',
        'department', 'position', 'is_active', 'is_hidden',
        'line_user_id', 'line_display_name',
        'created_at', 'updated_at'
    ]

    filename = os.path.join(backup_dir, f'employees_{timestamp}.csv')
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"Exported {len(rows)} employees to: {filename}")
    return filename, len(rows)

def export_attendance_records(conn, backup_dir, timestamp, months_back=3):
    """Export attendance records to CSV."""
    cursor = conn.cursor()

    # Calculate date for filtering (3 months back)
    cutoff_date = datetime.now() - timedelta(days=months_back * 30)
    cutoff_str = cutoff_date.strftime('%Y-%m-%d')

    cursor.execute('''
        SELECT
            ar.id, ar.employee_badge_number, ar.device_id, ar.timestamp,
            ar.punch_type, ar.status, ar.sync_status,
            ar.validation_status, ar.lateness_minutes, ar.early_minutes,
            ar.validation_message, ar.created_at,
            e.display_name as employee_name,
            d.name as device_name
        FROM attendance_records ar
        LEFT JOIN employees e ON ar.employee_badge_number = e.badge_number
        LEFT JOIN devices d ON ar.device_id = d.id
        WHERE ar.timestamp >= ?
        ORDER BY ar.timestamp DESC
    ''', (cutoff_str,))

    rows = cursor.fetchall()
    columns = [
        'id', 'employee_badge_number', 'device_id', 'timestamp',
        'punch_type', 'status', 'sync_status',
        'validation_status', 'lateness_minutes', 'early_minutes',
        'validation_message', 'created_at',
        'employee_name', 'device_name'
    ]

    filename = os.path.join(backup_dir, f'attendance_records_{timestamp}.csv')
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"Exported {len(rows)} attendance records (since {cutoff_str}) to: {filename}")
    return filename, len(rows)

def verify_data_coverage(conn, months_back=3):
    """Verify that data covers at least the specified months back."""
    cursor = conn.cursor()
    cutoff_date = datetime.now() - timedelta(days=months_back * 30)
    cutoff_str = cutoff_date.strftime('%Y-%m-%d')

    # Get date range of records in the backup period
    cursor.execute('''
        SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
        FROM attendance_records
        WHERE timestamp >= ?
    ''', (cutoff_str,))
    min_date, max_date, count = cursor.fetchone()

    # Get monthly breakdown
    cursor.execute('''
        SELECT
            strftime('%Y-%m', timestamp) as month,
            COUNT(*) as record_count
        FROM attendance_records
        WHERE timestamp >= ?
        GROUP BY strftime('%Y-%m', timestamp)
        ORDER BY month
    ''', (cutoff_str,))
    monthly = cursor.fetchall()

    print("\n" + "="*60)
    print("DATA VERIFICATION")
    print("="*60)
    print(f"Cutoff date: {cutoff_str}")
    print(f"Records in range: {count}")
    print(f"Date range: {min_date} to {max_date}")
    print("\nMonthly breakdown:")
    for month, rec_count in monthly:
        print(f"  {month}: {rec_count} records")

    return count, monthly

def export_attendance_all(conn, backup_dir, timestamp):
    """Export ALL attendance records to CSV (year >= 2000)."""
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            ar.id, ar.employee_badge_number, ar.device_id, ar.timestamp,
            ar.punch_type, ar.status, ar.sync_status,
            ar.validation_status, ar.lateness_minutes, ar.early_minutes,
            ar.validation_message, ar.created_at,
            e.display_name as employee_name,
            d.name as device_name
        FROM attendance_records ar
        LEFT JOIN employees e ON ar.employee_badge_number = e.badge_number
        LEFT JOIN devices d ON ar.device_id = d.id
        WHERE ar.timestamp >= '2000-01-01'
        ORDER BY ar.timestamp DESC
    ''')

    rows = cursor.fetchall()
    columns = [
        'id', 'employee_badge_number', 'device_id', 'timestamp',
        'punch_type', 'status', 'sync_status',
        'validation_status', 'lateness_minutes', 'early_minutes',
        'validation_message', 'created_at',
        'employee_name', 'device_name'
    ]

    filename = os.path.join(backup_dir, f'attendance_records_ALL_{timestamp}.csv')
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    # Get date range
    cursor.execute('SELECT MIN(timestamp), MAX(timestamp) FROM attendance_records WHERE timestamp >= "2000-01-01"')
    min_date, max_date = cursor.fetchone()

    print(f"Exported {len(rows)} attendance records (ALL since 2000) to: {filename}")
    print(f"Date range: {min_date} to {max_date}")
    return filename, len(rows)

def main():
    """Main backup function."""
    import sys
    full_backup = '--all' in sys.argv or '--full' in sys.argv

    print("="*60)
    print("CSV BACKUP - Fingerprint Time Logger Database")
    print("="*60)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'FULL BACKUP (all records)' if full_backup else 'Last 3 months'}")

    # Create backup directory
    backup_dir = create_backup_dir()
    timestamp = get_timestamp()
    print(f"Backup directory: {backup_dir}")

    # Connect to database
    db_path = os.path.abspath(DATABASE_PATH)
    print(f"Database: {db_path}")

    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)

    try:
        # Export employees
        print("\n" + "-"*40)
        emp_file, emp_count = export_employees(conn, backup_dir, timestamp)

        # Export attendance records
        print("\n" + "-"*40)
        if full_backup:
            att_file, att_count = export_attendance_all(conn, backup_dir, timestamp)
        else:
            att_file, att_count = export_attendance_records(conn, backup_dir, timestamp, months_back=3)

        # Verify data coverage
        total_records, monthly = verify_data_coverage(conn, months_back=3 if not full_backup else 120)

        # Summary
        print("\n" + "="*60)
        print("BACKUP COMPLETE")
        print("="*60)
        print(f"Files created:")
        print(f"  1. {os.path.basename(emp_file)} ({emp_count} employees)")
        print(f"  2. {os.path.basename(att_file)} ({att_count} attendance records)")
        print(f"\nLocation: {backup_dir}")

        # Verify 3 months coverage
        if len(monthly) >= 3:
            print(f"\nVERIFICATION: Data covers {len(monthly)} months")
        else:
            print(f"\nWARNING: Data only covers {len(monthly)} month(s)")

        return 0

    finally:
        conn.close()

if __name__ == '__main__':
    exit(main())
