"""Isolated test of the 20260918_000000 data migration that merges the
`day_off` leave type into `public_holiday`.

Loads the migration module directly by file path (its filename starts with
digits and is not import-able as a normal dotted module) and runs its
`upgrade()` against a minimal, hand-built SQLite schema that mirrors just the
columns/constraints the migration touches — not the full app metadata,
because the app models already carry the POST-merge constraint.
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database/migrations/versions/20260918_000000_merge_day_off_into_public_holiday.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "merge_day_off_into_public_holiday_migration", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_pre_merge_schema(engine):
    """Minimal tables shaped like the pre-migration production schema:
    staff_leave_requests still carries the OLD (day_off, no public_holiday)
    check constraint that was live before this migration."""
    md = sa.MetaData()
    sa.Table(
        "leave_types", md,
        sa.Column("code", sa.String(20), primary_key=True),
        sa.Column("name_th", sa.String(50), nullable=False),
        sa.Column("color", sa.String(7)),
    )
    sa.Table(
        "employee_leaves", md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("employee_badge_number", sa.String(50), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("note", sa.String(200)),
    )
    sa.Table(
        "staff_leave_requests", md,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("employee_badge_number", sa.String(50), nullable=False),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("date_from", sa.Date, nullable=False),
        sa.Column("date_to", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint(
            "leave_type IN ('sick','personal','vacation','day_off')",
            name="ck_staff_leave_type",
        ),
    )
    md.create_all(engine)


def _run_upgrade(module, conn):
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        module.upgrade()


@pytest.fixture
def migrated_conn():
    module = _load_migration_module()
    engine = sa.create_engine("sqlite://")
    _build_pre_merge_schema(engine)
    conn = engine.connect()

    conn.execute(sa.text(
        "INSERT INTO leave_types (code, name_th, color) "
        "VALUES ('day_off', 'ใช้วันหยุด', '#64748B')"
    ))
    conn.execute(sa.text(
        "INSERT INTO employee_leaves (employee_badge_number, date, leave_type, note) "
        "VALUES ('B1', '2026-09-18', 'day_off', NULL)"
    ))
    conn.execute(sa.text(
        "INSERT INTO staff_leave_requests "
        "(id, employee_badge_number, leave_type, date_from, date_to, status, version) "
        "VALUES ('r1', 'B1', 'day_off', '2026-09-18', '2026-09-18', 'approved', 1)"
    ))
    conn.commit()

    _run_upgrade(module, conn)
    conn.commit()

    try:
        yield conn
    finally:
        conn.close()
        engine.dispose()


def test_employee_leaves_row_becomes_public_holiday(migrated_conn):
    rows = migrated_conn.execute(
        sa.text("SELECT leave_type FROM employee_leaves WHERE employee_badge_number = 'B1'")
    ).fetchall()
    assert [r[0] for r in rows] == ["public_holiday"]


def test_staff_leave_request_row_becomes_public_holiday(migrated_conn):
    rows = migrated_conn.execute(
        sa.text("SELECT leave_type FROM staff_leave_requests WHERE id = 'r1'")
    ).fetchall()
    assert [r[0] for r in rows] == ["public_holiday"]


def test_day_off_leave_type_row_is_gone_and_public_holiday_exists(migrated_conn):
    codes = {
        r[0] for r in migrated_conn.execute(sa.text("SELECT code FROM leave_types")).fetchall()
    }
    assert codes == {"public_holiday"}
    name = migrated_conn.execute(
        sa.text("SELECT name_th FROM leave_types WHERE code = 'public_holiday'")
    ).scalar()
    assert name == "วันหยุดนักขัตฤกษ์"


def test_inserting_a_day_off_request_now_fails_the_constraint(migrated_conn):
    with pytest.raises(sa.exc.IntegrityError):
        migrated_conn.execute(sa.text(
            "INSERT INTO staff_leave_requests "
            "(id, employee_badge_number, leave_type, date_from, date_to, status, version) "
            "VALUES ('r2', 'B1', 'day_off', '2026-09-19', '2026-09-19', 'pending', 1)"
        ))
    migrated_conn.rollback()
