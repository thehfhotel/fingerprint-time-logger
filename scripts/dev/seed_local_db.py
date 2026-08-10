#!/usr/bin/env python3
"""
Seed a throwaway local SQLite database with realistic fake attendance data.

Purpose: give a UI agent something real to look at when running the app
locally (see scripts/dev/run_local.sh) without touching a ZKTeco device or
the production database. Builds the schema straight from the SQLAlchemy
models (same approach ci.yml / build.yml use — see app/core/database.py),
then inserts:

  - Devices: 1 fingerprint device (satisfies AttendanceRecord.device_id FK).
  - Shifts: the 7 rows normally seeded by the Alembic migrations
    (NORMAL/MORNING/MID/AFTERNOON/NIGHT + the OFF and HK_WORK pseudo-shifts)
    — see database/migrations/versions/20260515_000000_employee_shifts.py,
    20260516_010000_shift_colors_holidays_leaves.py,
    20260516_020000_off_shift_and_leave_types.py, and
    20260701_000000_hk_work_color_shift.py. We build the schema via
    Base.metadata.create_all() rather than replaying Alembic (same
    rationale as ci.yml), so these rows don't exist until we insert them.
  - Leave types + one public holiday.
  - 12 employees spanning reception / housekeeping / technician / admin
    roles, Thai + English names + nicknames (display_name), plus a couple
    of deliberately "untracked" / inactive rows.
  - ~60 days of AttendanceRecord punches per employee, including:
      * a rotating reception roster (shift_assignments) with days off
      * a role-default schedule for housekeeping/technician/admin
      * a dedicated night-shift employee whose punches cross midnight
      * a technician day with a missing punch-out
      * a technician day with a duplicate check-in punch
      * an employee with ZERO punches for the whole window
      * an "untracked" employee (no role/default shift) with scattered
        punches that /by-date and /monthly both ignore
      * an inactive+hidden employee who stopped punching before leaving

Usage:
    python3 scripts/dev/seed_local_db.py           # seed if empty
    python3 scripts/dev/seed_local_db.py --reset    # wipe + reseed

Requires the same throwaway env vars as CI for import-time config
validation to pass (ENV=test at minimum) — see scripts/dev/run_local.sh,
which sets these before invoking this script.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, datetime, time, timedelta

# Make `app` importable regardless of CWD this is invoked from.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.models.models import (  # noqa: E402
    AttendanceRecord,
    Device,
    Employee,
    EmployeeLeave,
    LeaveType,
    PublicHoliday,
    Shift,
    ShiftAssignment,
)

RNG = random.Random(42)  # deterministic across reruns -> stable screenshots

BANGKOK_OFFSET = timedelta(hours=7)
DAYS_OF_HISTORY = 60
PUNCH_IN = 0
PUNCH_OUT = 1


def bkk(d: date, hh: int, mm: int, ss: int = 0) -> datetime:
    """Bangkok-local wall-clock time -> naive UTC datetime.

    Matches how the app stores AttendanceRecord.timestamp (naive, UTC) and
    how app/services/shift_service.py converts shift windows: a plain
    +7:00 offset, no DST (Thailand has none).
    """
    return datetime(d.year, d.month, d.day, hh, mm, ss) - BANGKOK_OFFSET


def jitter_minutes(base_hh: int, base_mm: int, lo: int, hi: int) -> tuple[int, int]:
    """base time +/- a random number of minutes in [lo, hi], wrapped to 0-23h."""
    total = base_hh * 60 + base_mm + RNG.randint(lo, hi)
    total %= 24 * 60
    return total // 60, total % 60


# ============================================================================
# Reference data: shifts + leave types + one public holiday
# ============================================================================

# (code, letter, name_th, start_time, end_time, color) — mirrors the Alembic
# seed data exactly so local pages render the same labels/colors as prod.
SHIFT_SEEDS = [
    ("NORMAL", None, "ปกติ", time(8, 0), time(17, 0), "#e5e7eb"),
    ("MORNING", "A", "เช้า", time(7, 0), time(16, 0), "#86efac"),
    ("MID", "C", "สาย", time(11, 0), time(20, 0), "#fde68a"),
    ("AFTERNOON", "B", "บ่าย", time(13, 0), time(22, 0), "#93c5fd"),
    ("NIGHT", "D", "ดึก", time(22, 0), time(7, 0), "#c4b5fd"),
    ("OFF", "OFF", "หยุด", time(0, 0), time(0, 0), "#e5e7eb"),
    ("HK_WORK", None, "ปกติ (แม่บ้าน)", time(0, 0), time(0, 0), "#86efac"),
]

LEAVE_TYPE_SEEDS = [
    ("vacation", "ลาพักร้อน", "#bbf7d0"),
    ("personal", "ลากิจ", "#fdba74"),
    ("sick", "ลาป่วย", "#fbcfe8"),
    ("public_holiday", "วันหยุดนักขัตฤกษ์", "#fca5a5"),
]

# ============================================================================
# Employees — 12 rows spanning every role + a few deliberate edge cases.
# ============================================================================

EMPLOYEE_SEEDS = [
    dict(badge_number="R001", english_name="Somying Jaidee", thai_name="สมหญิง ใจดี",
         display_name="หญิง", department="Front Office", position="Receptionist",
         role="reception", location="HF"),
    dict(badge_number="R002", english_name="Kamolchanok Saengthong", thai_name="กมลชนก แสงทอง",
         display_name="แนน", department="Front Office", position="Receptionist",
         role="reception", location="HF"),
    dict(badge_number="R003", english_name="Thanakorn Srisuk", thai_name="ธนกร ศรีสุข",
         display_name="กร", department="Front Office", position="Receptionist",
         role="reception", location="HF_VILLE"),
    dict(badge_number="R004", english_name="Piyada Rungrueang", thai_name="ปิยะดา รุ่งเรือง",
         display_name="ดา", department="Front Office", position="Receptionist",
         role="reception", location=None),
    dict(badge_number="H001", english_name="Malee Boonmak", thai_name="มาลี บุญมาก",
         display_name="มาลี", department="Housekeeping", position="Room Attendant",
         role="housekeeping", location="HF"),
    # H002: role set (so it's "tracked") but ZERO attendance records —
    # the "employee with no punches" edge case. Every scheduled day
    # should show up as "absent" on /by-date and /monthly.
    dict(badge_number="H002", english_name="Sunee Promma", thai_name="สุนีย์ พรมมา",
         display_name="นีย์", department="Housekeeping", position="Room Attendant",
         role="housekeeping", location="HF"),
    dict(badge_number="H003", english_name="Wilai Thongdee", thai_name="วิไล ทองดี",
         display_name="ไหล", department="Housekeeping", position="Room Attendant",
         role="housekeeping", location="HF_VILLE"),
    # T001: technician on the normal day shift — carries the "missing
    # punch-out" and "duplicate punch" edge cases.
    dict(badge_number="T001", english_name="Prayuth Changdee", thai_name="ประยุทธ ช่างดี",
         display_name="ยุทธ", department="Maintenance", position="Technician",
         role="technician", location="HF"),
    # T002: explicit default_shift_id=NIGHT (assigned after shifts are
    # inserted, below) — the "night shift crossing midnight" edge case.
    dict(badge_number="T002", english_name="Anucha Duangtawan", thai_name="อนุชา ดวงตะวัน",
         display_name="ชา", department="Maintenance", position="Technician",
         role="technician", location="HF"),
    dict(badge_number="A001", english_name="Napatsorn Wongsuwan", thai_name="นภัสสร วงศ์สุวรรณ",
         display_name="นภา", department="Administration", position="Admin Officer",
         role="admin", location="HF"),
    # U001: no role, no default shift -> "untracked". Appears in the raw
    # attendance feed / employee list but is skipped entirely by
    # /by-date and /monthly (see app/services/shift_service.py).
    dict(badge_number="U001", english_name="Chaiwat Pandee", thai_name="ชัยวัฒน์ พันธ์ดี",
         display_name="ชัย", department="Front Office", position="Trainee",
         role=None, location=None),
    # I001: inactive + hidden — a former employee. Excluded from
    # _fetch_active_employees() and from the default employee list
    # (include_hidden/include_inactive both default False).
    dict(badge_number="I001", english_name="Rattana Tipwong", thai_name="รัตนา ทิพย์วงศ์",
         display_name="รัตน์", department="Housekeeping", position="Room Attendant",
         role=None, location="HF", is_active=False, is_hidden=True),
]

RECEPTION_BADGES = ["R001", "R002", "R003", "R004"]
DAILY_ROLE_BADGES = ["H001", "H003", "T001", "A001"]  # role-default schedule, Sundays off
NIGHT_BADGE = "T002"
NO_PUNCHES_BADGE = "H002"
UNTRACKED_BADGE = "U001"
INACTIVE_BADGE = "I001"

ROLE_DEFAULT_SHIFT = {
    "housekeeping": "MORNING",
    "technician": "NORMAL",
    "admin": "NORMAL",
}

RECEPTION_ROTATION = ["MORNING", "AFTERNOON", "MID", "NIGHT"]


def build_schema() -> None:
    Base.metadata.create_all(bind=engine)


def already_seeded(db) -> bool:
    return db.query(Employee).first() is not None


def reset_db(db) -> None:
    print("--reset: dropping all tables and recreating schema")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_reference_data(db) -> dict[str, Shift]:
    shifts: dict[str, Shift] = {}
    for code, letter, name_th, start_time, end_time, color in SHIFT_SEEDS:
        s = Shift(
            code=code, letter=letter, name_th=name_th,
            start_time=start_time, end_time=end_time,
            color=color, is_active=True,
        )
        db.add(s)
        shifts[code] = s

    for code, name_th, color in LEAVE_TYPE_SEEDS:
        db.add(LeaveType(code=code, name_th=name_th, color=color))

    today = date.today()
    db.add(PublicHoliday(
        date=today - timedelta(days=14),
        name="วันหยุดนักขัตฤกษ์ (ข้อมูลทดสอบ)",
    ))

    db.flush()  # assign shift.id values before employees reference them
    return shifts


def seed_device(db) -> Device:
    device = Device(
        name="ZKTeco Main - Front Desk",
        ip_address="192.168.100.209",
        port=4370,
        password=0,
        is_active=True,
        device_type="fingerprint",
    )
    db.add(device)
    db.flush()
    return device


def seed_employees(db, shifts: dict[str, Shift]) -> dict[str, Employee]:
    employees: dict[str, Employee] = {}
    for seed in EMPLOYEE_SEEDS:
        kwargs = dict(seed)
        badge = kwargs["badge_number"]
        display_name = kwargs.pop("display_name")
        kwargs.setdefault("is_active", True)
        kwargs.setdefault("is_hidden", False)
        emp = Employee(
            display_name=display_name,
            join_source="device",
            pending_approval=False,
            email=f"{badge.lower()}@emp.thehfhotel.org",
            **kwargs,
        )
        db.add(emp)
        employees[badge] = emp

    # T002's edge case: an explicit default_shift_id (NIGHT), resolved
    # before role_default in app/services/shift_service.py's precedence.
    employees[NIGHT_BADGE].default_shift = shifts["NIGHT"]

    db.flush()
    return employees


def seed_leaves(db) -> None:
    today = date.today()
    # R002: a 3-day vacation, ~3 weeks ago.
    start = today - timedelta(days=21)
    for i in range(3):
        db.add(EmployeeLeave(
            employee_badge_number="R002",
            date=start + timedelta(days=i),
            leave_type="vacation",
            note="พักร้อนประจำปี",
        ))
    # H001: a single sick day, ~10 days ago.
    db.add(EmployeeLeave(
        employee_badge_number="H001",
        date=today - timedelta(days=10),
        leave_type="sick",
        note="ไม่สบาย",
    ))


def add_punch(db, badge: str, device_id: int, ts: datetime, punch_type: int) -> None:
    db.add(AttendanceRecord(
        employee_badge_number=badge,
        device_id=device_id,
        timestamp=ts,
        punch_type=punch_type,
    ))


def seed_reception_schedule_and_punches(db, device: Device, shifts: dict[str, Shift]) -> None:
    """Rotating roster (shift_assignments) + punches for the 4 reception staff.

    Each has a fixed weekly day off, then rotates through
    MORNING -> AFTERNOON -> MID -> NIGHT with a per-employee offset so
    the roster looks staggered rather than everyone on the same shift.
    """
    today = date.today()
    days = [today - timedelta(days=n) for n in range(DAYS_OF_HISTORY - 1, -1, -1)]

    for idx, badge in enumerate(RECEPTION_BADGES):
        day_off_weekday = idx  # R001 off Mon, R002 off Tue, R003 off Wed, R004 off Thu

        for day_idx, day in enumerate(days):
            if day > today:
                continue
            if day.weekday() == day_off_weekday:
                db.add(ShiftAssignment(
                    employee_badge_number=badge, date=day, shift_id=None,
                ))
                continue

            code = RECEPTION_ROTATION[(day_idx + idx) % len(RECEPTION_ROTATION)]
            shift = shifts[code]
            db.add(ShiftAssignment(
                employee_badge_number=badge, date=day, shift_id=shift.id,
            ))

            roll = RNG.random()
            if roll < 0.06:
                # Absent: scheduled, but no punches at all this day.
                continue

            start_h, start_m = shift.start_time.hour, shift.start_time.minute
            end_h, end_m = shift.end_time.hour, shift.end_time.minute
            crosses_midnight = shift.end_time <= shift.start_time

            in_h, in_m = jitter_minutes(start_h, start_m, -10, 25)  # occasionally late
            in_day = day
            db.add(AttendanceRecord(
                employee_badge_number=badge, device_id=device.id,
                timestamp=bkk(in_day, in_h, in_m, RNG.randint(0, 59)),
                punch_type=PUNCH_IN,
            ))

            if roll < 0.12:
                # Missing punch-out.
                continue

            out_day = day + timedelta(days=1) if crosses_midnight else day
            out_h, out_m = jitter_minutes(end_h, end_m, -15, 20)
            db.add(AttendanceRecord(
                employee_badge_number=badge, device_id=device.id,
                timestamp=bkk(out_day, out_h, out_m, RNG.randint(0, 59)),
                punch_type=PUNCH_OUT,
            ))


def seed_role_default_schedule_and_punches(db, device: Device) -> None:
    """Housekeeping / technician / admin: role-default shift every day
    except Sunday (explicit ShiftAssignment off). T001 additionally gets
    the "missing punch-out" and "duplicate punch" edge-case days.
    """
    today = date.today()
    days = [today - timedelta(days=n) for n in range(DAYS_OF_HISTORY - 1, -1, -1)]

    # Pick two workdays for T001's edge cases up front (not Sundays,
    # not the same day, comfortably inside the window).
    t001_workdays = [d for d in days if d.weekday() != 6]
    missing_out_day = t001_workdays[len(t001_workdays) // 3]
    duplicate_punch_day = t001_workdays[2 * len(t001_workdays) // 3]

    for badge in DAILY_ROLE_BADGES:
        role = next(e["role"] for e in EMPLOYEE_SEEDS if e["badge_number"] == badge)
        shift_start = time(7, 0) if role == "housekeeping" else time(8, 0)
        shift_end = time(16, 0) if role == "housekeeping" else time(17, 0)

        for day in days:
            if day > today:
                continue
            if day.weekday() == 6:  # Sunday off, company-wide 6-day week
                db.add(ShiftAssignment(
                    employee_badge_number=badge, date=day, shift_id=None,
                ))
                continue

            if badge == NO_PUNCHES_BADGE:
                continue  # H002 handled separately: zero punches, ever.

            if badge == "T001" and day == missing_out_day:
                in_h, in_m = jitter_minutes(shift_start.hour, shift_start.minute, -5, 10)
                add_punch(db, badge, device.id, bkk(day, in_h, in_m), PUNCH_IN)
                continue  # no check-out this day

            if badge == "T001" and day == duplicate_punch_day:
                in_h, in_m = jitter_minutes(shift_start.hour, shift_start.minute, -5, 5)
                first_in = bkk(day, in_h, in_m, 0)
                add_punch(db, badge, device.id, first_in, PUNCH_IN)
                # Device double-scan: a near-identical second check-in a
                # few seconds later (distinct timestamp so it doesn't
                # collide with the UNIQUE(badge, timestamp, punch_type)
                # constraint, but is clearly a duplicate in the UI).
                add_punch(db, badge, device.id, first_in + timedelta(seconds=8), PUNCH_IN)
                out_h, out_m = jitter_minutes(shift_end.hour, shift_end.minute, -10, 15)
                add_punch(db, badge, device.id, bkk(day, out_h, out_m), PUNCH_OUT)
                continue

            roll = RNG.random()
            if roll < 0.05:
                continue  # ordinary absence

            in_h, in_m = jitter_minutes(shift_start.hour, shift_start.minute, -10, 20)
            add_punch(db, badge, device.id, bkk(day, in_h, in_m, RNG.randint(0, 59)), PUNCH_IN)

            if roll < 0.10:
                continue  # ordinary missing punch-out

            out_h, out_m = jitter_minutes(shift_end.hour, shift_end.minute, -10, 25)
            add_punch(db, badge, device.id, bkk(day, out_h, out_m, RNG.randint(0, 59)), PUNCH_OUT)

    # H002: scheduled the same as the other daily-role employees
    # (Sundays off, above) but literally zero AttendanceRecord rows.


def seed_night_shift_punches(db, device: Device) -> None:
    """T002: default_shift_id=NIGHT (22:00-07:00). Punches cross midnight
    into the next calendar day — the dedicated overnight edge case.
    Sundays off, same as the other daily-role staff.
    """
    today = date.today()
    days = [today - timedelta(days=n) for n in range(DAYS_OF_HISTORY - 1, -1, -1)]

    for day in days:
        if day > today:
            continue
        if day.weekday() == 6:
            db.add(ShiftAssignment(
                employee_badge_number=NIGHT_BADGE, date=day, shift_id=None,
            ))
            continue

        roll = RNG.random()
        if roll < 0.05:
            continue  # absent

        in_h, in_m = jitter_minutes(22, 0, -10, 20)
        add_punch(db, NIGHT_BADGE, device.id, bkk(day, in_h, in_m, RNG.randint(0, 59)), PUNCH_IN)

        if roll < 0.10:
            continue  # missing punch-out

        out_day = day + timedelta(days=1)
        if out_day > today:
            continue  # don't punch out "in the future" for the last night
        out_h, out_m = jitter_minutes(7, 0, -15, 20)
        add_punch(db, NIGHT_BADGE, device.id, bkk(out_day, out_h, out_m, RNG.randint(0, 59)), PUNCH_OUT)


def seed_untracked_and_inactive_punches(db, device: Device) -> None:
    today = date.today()
    days = [today - timedelta(days=n) for n in range(DAYS_OF_HISTORY - 1, -1, -1)]

    # U001: untracked (no role/default shift) — scattered plausible
    # office-hours punches. Ignored by /by-date and /monthly, but shows
    # up in the raw attendance feed and employee list.
    sample_days = RNG.sample(days, k=18)
    for day in sample_days:
        in_h, in_m = jitter_minutes(9, 0, -20, 30)
        add_punch(db, UNTRACKED_BADGE, device.id, bkk(day, in_h, in_m), PUNCH_IN)
        if RNG.random() < 0.8:
            out_h, out_m = jitter_minutes(18, 0, -30, 30)
            add_punch(db, UNTRACKED_BADGE, device.id, bkk(day, out_h, out_m), PUNCH_OUT)

    # I001: inactive+hidden, stopped showing up before being deactivated
    # — punches only in the first third of the window, then nothing.
    early_days = [d for d in days if d <= days[0] + timedelta(days=DAYS_OF_HISTORY // 3)]
    for day in RNG.sample(early_days, k=min(8, len(early_days))):
        in_h, in_m = jitter_minutes(8, 0, -10, 15)
        add_punch(db, INACTIVE_BADGE, device.id, bkk(day, in_h, in_m), PUNCH_IN)
        out_h, out_m = jitter_minutes(17, 0, -10, 15)
        add_punch(db, INACTIVE_BADGE, device.id, bkk(day, out_h, out_m), PUNCH_OUT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true",
        help="Drop all tables and reseed from scratch (destroys existing local data).",
    )
    args = parser.parse_args()

    build_schema()
    db = SessionLocal()
    try:
        if args.reset:
            reset_db(db)
        elif already_seeded(db):
            print("Database already has employees — skipping seed (use --reset to reseed).")
            return

        print(f"Seeding {DAYS_OF_HISTORY} days of fake attendance data...")
        shifts = seed_reference_data(db)
        device = seed_device(db)
        seed_employees(db, shifts)
        seed_leaves(db)
        seed_reception_schedule_and_punches(db, device, shifts)
        seed_role_default_schedule_and_punches(db, device)
        seed_night_shift_punches(db, device)
        seed_untracked_and_inactive_punches(db, device)

        db.commit()

        n_employees = db.query(Employee).count()
        n_punches = db.query(AttendanceRecord).count()
        n_assignments = db.query(ShiftAssignment).count()
        print(
            f"Seeded: {n_employees} employees, {n_punches} attendance records, "
            f"{n_assignments} shift assignments."
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
