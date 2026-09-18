"""Merge day_off leave type into public_holiday.

Revision ID: 20260918_000000
Revises: 20260917_010000

OWNER DECISION (2026-09-18): day_off ("ใช้วันหยุด", added 2026-09-17 for the
LINE flow) and public_holiday ("วันหยุดนักขัตฤกษ์", the older roster/calendar
type) are the same leave. This migration folds day_off into public_holiday
everywhere: existing roster rows and LINE-filed requests are rewritten,
the leave_types row is replaced, and the staff_leave_requests check
constraint no longer allows day_off.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260918_000000"
down_revision = "20260917_010000"
branch_labels = None
depends_on = None


def upgrade():
    # The existing constraint allows day_off but not public_holiday, so the
    # data UPDATE below would fail against it. Widen it first (still
    # excluding neither old nor new value) so both are legal while the data
    # migrates, then narrow it to the final set once no day_off rows remain.
    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.drop_constraint("ck_staff_leave_type", type_="check")
        batch.create_check_constraint(
            "ck_staff_leave_type",
            "leave_type IN ('sick','personal','vacation','day_off','public_holiday')",
        )

    op.execute(sa.text(
        "UPDATE employee_leaves SET leave_type = 'public_holiday' "
        "WHERE leave_type = 'day_off'"
    ))
    op.execute(sa.text(
        "UPDATE staff_leave_requests SET leave_type = 'public_holiday' "
        "WHERE leave_type = 'day_off'"
    ))
    op.execute(sa.text(
        "INSERT OR IGNORE INTO leave_types (code, name_th, color) "
        "VALUES ('public_holiday', 'วันหยุดนักขัตฤกษ์', '#fca5a5')"
    ))
    op.execute(sa.text("DELETE FROM leave_types WHERE code = 'day_off'"))

    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.drop_constraint("ck_staff_leave_type", type_="check")
        batch.create_check_constraint(
            "ck_staff_leave_type",
            "leave_type IN ('sick','personal','vacation','public_holiday')",
        )


def downgrade():
    # Data is not split back apart: rows that were day_off before the
    # upgrade remain public_holiday after this downgrade. This only
    # restores the wider constraint and the day_off leave_types row so the
    # pre-merge schema shape is available again.
    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.drop_constraint("ck_staff_leave_type", type_="check")
        batch.create_check_constraint(
            "ck_staff_leave_type",
            "leave_type IN ('sick','personal','vacation','day_off','public_holiday')",
        )

    op.execute(sa.text(
        "INSERT OR IGNORE INTO leave_types (code, name_th, color) "
        "VALUES ('day_off', 'ใช้วันหยุด', '#64748B')"
    ))
