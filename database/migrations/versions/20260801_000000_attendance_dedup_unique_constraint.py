"""Attendance dedup unique constraint

Revision ID: 20260801_000000
Revises: 20260702_000000
Create Date: 2026-08-01

Adds a database-level guard against duplicate attendance punches, closing
the gap left by the ZK ingestion redesign (catch-up sweeps + realtime
stream can both attempt to insert the same punch):

1. UniqueConstraint('employee_badge_number', 'timestamp', 'punch_type',
   name='uq_attendance_badge_ts_punch') on attendance_records — matches
   the dedup/exists key both ingestion paths (zk_session catch-up and
   realtime _handle_punch) already use in app code. The DB now rejects
   what app-level dedup misses instead of silently double-counting hours.

Before creating the constraint, upgrade() pre-checks attendance_records
for existing (employee_badge_number, timestamp, punch_type) duplicate
groups and ABORTS with a clear message listing up to 20 offending groups
if any are found — it never silently deletes data. The old app-level
dedup was stricter than this key, so no duplicates are expected in
practice; if the pre-check does fire, an operator must resolve the
duplicates by hand (decide which row is authoritative) before re-running
this migration.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260801_000000'
down_revision = '20260702_000000'
branch_labels = None
depends_on = None


DUPLICATE_CHECK_SQL = """
    SELECT employee_badge_number, timestamp, punch_type, COUNT(*) AS cnt
    FROM attendance_records
    GROUP BY employee_badge_number, timestamp, punch_type
    HAVING COUNT(*) > 1
    ORDER BY cnt DESC, employee_badge_number, timestamp
    LIMIT 20
"""


def upgrade():
    connection = op.get_bind()

    duplicates = connection.execute(sa.text(DUPLICATE_CHECK_SQL)).fetchall()
    if duplicates:
        lines = [
            f"  badge={row[0]!r} timestamp={row[1]!r} punch_type={row[2]!r} count={row[3]}"
            for row in duplicates
        ]
        raise RuntimeError(
            "Cannot add uq_attendance_badge_ts_punch: attendance_records has "
            "existing duplicate (employee_badge_number, timestamp, punch_type) "
            "groups. Resolve these rows by hand (decide which one is "
            "authoritative and delete/merge the rest) before re-running this "
            "migration. Offending groups (badge, timestamp, punch_type, count), "
            "up to 20 shown:\n" + "\n".join(lines)
        )

    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_attendance_badge_ts_punch',
            ['employee_badge_number', 'timestamp', 'punch_type'],
        )


def downgrade():
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.drop_constraint('uq_attendance_badge_ts_punch', type_='unique')
