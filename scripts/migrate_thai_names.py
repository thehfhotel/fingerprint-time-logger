#!/usr/bin/env python3
"""
Thai Name Migration Script
Migrates existing userid.csv data to database EmployeeThaiName table
"""

import csv
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine
from app.models.models import EmployeeThaiName, Base

def create_tables():
    """Create all database tables"""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully")

def load_thai_names_from_csv(csv_file: str = "userid.csv") -> dict:
    """Load Thai names from CSV file"""
    thai_names = {}
    csv_path = Path(csv_file)
    
    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        return thai_names
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                badge_number = row['Badgenumber'].strip()
                thai_name = row['ชื่อ'].strip() if row['ชื่อ'] else ''
                
                # Only include employees with Thai names
                if thai_name:
                    thai_names[badge_number] = thai_name
                    
        print(f"✅ Loaded {len(thai_names)} Thai names from CSV")
        print(f"Sample mappings: {dict(list(thai_names.items())[:3])}")
        return thai_names
        
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
        return {}

def migrate_to_database(thai_names: dict) -> bool:
    """Migrate Thai names to database"""
    if not thai_names:
        print("❌ No Thai names to migrate")
        return False
        
    db = SessionLocal()
    try:
        # Check if data already exists
        existing_count = db.query(EmployeeThaiName).count()
        if existing_count > 0:
            print(f"⚠️  Database already contains {existing_count} Thai name records")
            response = input("Continue with migration? This will skip duplicates (y/N): ").strip().lower()
            if response != 'y':
                print("Migration cancelled")
                return False
        
        # Insert Thai names
        inserted_count = 0
        skipped_count = 0
        
        for badge_number, thai_name in thai_names.items():
            # Check if badge number already exists
            existing = db.query(EmployeeThaiName).filter(
                EmployeeThaiName.badge_number == badge_number
            ).first()
            
            if existing:
                print(f"⚠️  Skipping existing badge number: {badge_number}")
                skipped_count += 1
                continue
                
            # Create new Thai name record
            thai_name_record = EmployeeThaiName(
                badge_number=badge_number,
                thai_name=thai_name,
                is_active=True
            )
            
            db.add(thai_name_record)
            inserted_count += 1
            print(f"✅ Added: {badge_number} → {thai_name}")
        
        # Commit all changes
        db.commit()
        print(f"\n🎉 Migration completed successfully!")
        print(f"   Inserted: {inserted_count} records")
        print(f"   Skipped: {skipped_count} records")
        print(f"   Total in database: {db.query(EmployeeThaiName).count()} records")
        
        return True
        
    except Exception as e:
        db.rollback()
        print(f"❌ Migration failed: {e}")
        return False
    finally:
        db.close()

def verify_migration() -> bool:
    """Verify migration was successful"""
    db = SessionLocal()
    try:
        # Get all Thai names from database
        thai_names = db.query(EmployeeThaiName).all()
        print(f"\n🔍 Verification: Found {len(thai_names)} records in database")
        
        # Show sample records
        print("Sample records:")
        for i, record in enumerate(thai_names[:5]):
            print(f"  {i+1}. Badge: {record.badge_number} → Thai: {record.thai_name}")
        
        if len(thai_names) > 5:
            print(f"  ... and {len(thai_names) - 5} more records")
            
        return len(thai_names) > 0
        
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return False
    finally:
        db.close()

def main():
    """Main migration function"""
    print("=== Thai Name Migration Script ===")
    print("Migrating userid.csv data to database...")
    
    # Change to project directory
    project_dir = Path(__file__).parent.parent
    os.chdir(project_dir)
    print(f"Working directory: {os.getcwd()}")
    
    # Step 1: Create database tables
    create_tables()
    
    # Step 2: Load Thai names from CSV
    thai_names = load_thai_names_from_csv()
    if not thai_names:
        print("❌ No Thai names loaded from CSV. Exiting.")
        return False
    
    # Step 3: Migrate to database
    success = migrate_to_database(thai_names)
    if not success:
        print("❌ Migration failed. Exiting.")
        return False
    
    # Step 4: Verify migration
    verification_success = verify_migration()
    if verification_success:
        print("\n✅ Migration completed and verified successfully!")
        print("Thai names are now stored in the database and ready for management.")
    else:
        print("\n❌ Migration verification failed!")
        
    return verification_success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)