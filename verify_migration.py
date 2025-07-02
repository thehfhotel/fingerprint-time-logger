#!/usr/bin/env python3
"""
Verify the Employee Model Unification migration was successful
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.models.models import Employee, AttendanceRecord
from app.core.database import get_db

def verify_database_structure():
    """Verify the new database structure"""
    print("=== Verifying Database Structure ===")
    
    engine = create_engine("sqlite:///./attendance.db")
    
    with engine.connect() as conn:
        # Check employees table structure
        result = conn.execute(text("PRAGMA table_info(employees)"))
        columns = result.fetchall()
        
        print("📋 Employees table columns:")
        for col in columns:
            print(f"   {col[1]} ({col[2]}) - {'NOT NULL' if col[3] else 'NULL'}")
        
        # Check attendance_records table structure  
        result = conn.execute(text("PRAGMA table_info(attendance_records)"))
        columns = result.fetchall()
        
        print("\n📋 AttendanceRecords table columns:")
        for col in columns:
            print(f"   {col[1]} ({col[2]}) - {'NOT NULL' if col[3] else 'NULL'}")
        
        # Check foreign keys
        result = conn.execute(text("PRAGMA foreign_key_list(attendance_records)"))
        fks = result.fetchall()
        
        print("\n🔗 Foreign Keys:")
        for fk in fks:
            print(f"   {fk[3]} -> {fk[2]}.{fk[4]}")

def verify_data_integrity():
    """Verify data was migrated correctly"""
    print("\n=== Verifying Data Integrity ===")
    
    engine = create_engine("sqlite:///./attendance.db")
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Count employees
        employee_count = db.query(Employee).count()
        print(f"👥 Total employees: {employee_count}")
        
        # Count with Thai names
        thai_count = db.query(Employee).filter(Employee.thai_name.isnot(None)).count()
        print(f"🇹🇭 Employees with Thai names: {thai_count}")
        
        # Count attendance records
        attendance_count = db.query(AttendanceRecord).count()
        print(f"📝 Total attendance records: {attendance_count}")
        
        # Sample employees
        print("\n📋 Sample employees:")
        employees = db.query(Employee).limit(5).all()
        for emp in employees:
            print(f"   {emp.badge_number}: {emp.display_name} (EN: {emp.english_name}, TH: {emp.thai_name})")
        
        # Test join with attendance records
        print("\n🔗 Testing Employee-Attendance join:")
        with_attendance = db.query(Employee).join(AttendanceRecord).limit(3).all()
        for emp in with_attendance:
            attendance_count = db.query(AttendanceRecord).filter(
                AttendanceRecord.employee_badge_number == emp.badge_number
            ).count()
            print(f"   {emp.badge_number} ({emp.display_name}): {attendance_count} records")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()

def test_model_operations():
    """Test basic model operations"""
    print("\n=== Testing Model Operations ===")
    
    engine = create_engine("sqlite:///./attendance.db")
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Test creating a new employee
        test_employee = Employee(
            badge_number="TEST999",
            english_name="Test User",
            thai_name="ผู้ใช้ทดสอบ",
            display_name="ผู้ใช้ทดสอบ",
            department="Testing",
            is_active=True
        )
        
        db.add(test_employee)
        db.commit()
        
        # Verify it was created
        created = db.query(Employee).filter(Employee.badge_number == "TEST999").first()
        if created:
            print(f"✅ Employee creation test: {created.display_name}")
            
            # Clean up
            db.delete(created)
            db.commit()
            print("✅ Employee deletion test: OK")
        else:
            print("❌ Employee creation failed")
            
    except Exception as e:
        print(f"❌ Model operation error: {e}")
    finally:
        db.close()

def main():
    print("🔍 Verifying Employee Model Unification Migration")
    print("=" * 50)
    
    verify_database_structure()
    verify_data_integrity()
    test_model_operations()
    
    print("\n" + "=" * 50)
    print("✅ Migration verification completed!")
    print("\nNext steps:")
    print("1. Test the unified API endpoints")
    print("2. Import data from userid.csv")
    print("3. Update dashboard to use new API")

if __name__ == "__main__":
    main()