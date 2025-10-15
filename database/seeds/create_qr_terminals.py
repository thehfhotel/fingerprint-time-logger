"""
Seed QR Terminal Devices

Creates 2 virtual QR terminal devices for multi-location support:
- Terminal 1: Main Office (GPS: 13.7563, 100.5018, radius: 200m)
- Terminal 2: Branch Office (GPS: 13.7200, 100.5200, radius: 200m)

Usage:
    python database/seeds/create_qr_terminals.py
"""
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.models import Device, Base
import json

# Database configuration
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./database/attendance.db')
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_qr_terminals(db=None):
    """Create 2 virtual QR terminal devices with GPS metadata

    Args:
        db: Optional database session (for testing). If None, creates new session.
    """

    # Use provided session or create new one
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        # Terminal 1: Main Office
        terminal1_metadata = {
            "gps": {
                "latitude": 13.7563,
                "longitude": 100.5018,
                "radius_meters": 200,
                "location_name": "Main Office"
            },
            "display": {
                "fullscreen": True,
                "refresh_interval": 30,
                "show_recent_checkins": True
            }
        }

        terminal1 = db.query(Device).filter(
            Device.name == "QR Terminal - Main Office"
        ).first()

        if not terminal1:
            terminal1 = Device(
                name="QR Terminal - Main Office",
                ip_address=None,  # Not used for QR terminals
                port=None,  # Not used for QR terminals
                password=0,
                device_type="qr_terminal",
                device_metadata=json.dumps(terminal1_metadata),
                is_active=True,
                created_at=datetime.now()
            )
            db.add(terminal1)
            print("✅ Created Terminal 1: Main Office")
            print(f"   GPS: {terminal1_metadata['gps']['latitude']}, {terminal1_metadata['gps']['longitude']}")
            print(f"   Radius: {terminal1_metadata['gps']['radius_meters']}m")
        else:
            terminal1.device_type = "qr_terminal"
            terminal1.device_metadata = json.dumps(terminal1_metadata)
            terminal1.is_active = True
            print("⚠️  Updated existing Terminal 1: Main Office")

        # Terminal 2: Branch Office
        terminal2_metadata = {
            "gps": {
                "latitude": 13.7200,
                "longitude": 100.5200,
                "radius_meters": 200,
                "location_name": "Branch Office"
            },
            "display": {
                "fullscreen": True,
                "refresh_interval": 30,
                "show_recent_checkins": True
            }
        }

        terminal2 = db.query(Device).filter(
            Device.name == "QR Terminal - Branch Office"
        ).first()

        if not terminal2:
            terminal2 = Device(
                name="QR Terminal - Branch Office",
                ip_address=None,  # Not used for QR terminals
                port=None,  # Not used for QR terminals
                password=0,
                device_type="qr_terminal",
                device_metadata=json.dumps(terminal2_metadata),
                is_active=True,
                created_at=datetime.now()
            )
            db.add(terminal2)
            print("✅ Created Terminal 2: Branch Office")
            print(f"   GPS: {terminal2_metadata['gps']['latitude']}, {terminal2_metadata['gps']['longitude']}")
            print(f"   Radius: {terminal2_metadata['gps']['radius_meters']}m")
        else:
            terminal2.device_type = "qr_terminal"
            terminal2.device_metadata = json.dumps(terminal2_metadata)
            terminal2.is_active = True
            print("⚠️  Updated existing Terminal 2: Branch Office")

        db.commit()

        print("\n📊 QR Terminal Summary:")
        print(f"   Total terminals: 2")
        print(f"   Terminal 1 ID: {terminal1.id}")
        print(f"   Terminal 2 ID: {terminal2.id}")
        print("\n✅ QR terminal seeding complete!")

        return True

    except Exception as e:
        db.rollback()
        print(f"\n❌ Error creating QR terminals: {e}")
        return False

    finally:
        # Only close if we created the session
        if own_session:
            db.close()


def verify_qr_terminals(db=None):
    """Verify QR terminals were created correctly

    Args:
        db: Optional database session (for testing). If None, creates new session.
    """

    # Use provided session or create new one
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        qr_terminals = db.query(Device).filter(
            Device.device_type == "qr_terminal"
        ).all()

        print("\n🔍 Verification:")
        print(f"   Found {len(qr_terminals)} QR terminals")

        for terminal in qr_terminals:
            print(f"\n   Terminal: {terminal.name}")
            print(f"   ID: {terminal.id}")
            print(f"   Type: {terminal.device_type}")
            print(f"   Active: {terminal.is_active}")

            if terminal.device_metadata:
                metadata = json.loads(terminal.device_metadata)
                gps = metadata.get('gps', {})
                print(f"   GPS: {gps.get('latitude')}, {gps.get('longitude')}")
                print(f"   Radius: {gps.get('radius_meters')}m")
                print(f"   Location: {gps.get('location_name')}")

        return len(qr_terminals) == 2

    finally:
        # Only close if we created the session
        if own_session:
            db.close()


if __name__ == "__main__":
    print("🚀 Starting QR Terminal Seeding...\n")

    # Ensure database exists
    Base.metadata.create_all(bind=engine)

    # Create terminals
    success = create_qr_terminals()

    if success:
        # Verify creation
        verified = verify_qr_terminals()

        if verified:
            print("\n✅ All QR terminals verified successfully!")
            sys.exit(0)
        else:
            print("\n⚠️  Warning: Verification found issues")
            sys.exit(1)
    else:
        print("\n❌ Failed to create QR terminals")
        sys.exit(1)
