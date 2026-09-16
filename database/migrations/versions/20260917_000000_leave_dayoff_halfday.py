"""Add day-off leave type and half-day period to staff leave requests.

Revision ID: 20260917_000000
Revises: 20260916_010000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260917_000000"
down_revision = "20260916_010000"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.add_column(sa.Column("leave_portion", sa.String(20), nullable=False,
                                   server_default="full"))
        batch.drop_constraint("ck_staff_leave_type", type_="check")
        batch.create_check_constraint(
            "ck_staff_leave_type",
            "leave_type IN ('sick','personal','vacation','day_off')",
        )
        batch.create_check_constraint(
            "ck_staff_leave_portion",
            "leave_portion IN ('full','am','pm')",
        )
        batch.create_check_constraint(
            "ck_staff_leave_half_day_single_date",
            "leave_portion = 'full' OR date_to = date_from",
        )

    # Make the approved roster type visible to the existing leave-type legend/UI.
    op.execute(sa.text(
        "INSERT OR IGNORE INTO leave_types (code, name_th, color) "
        "VALUES ('day_off', 'ใช้วันหยุด', '#64748B')"
    ))


def downgrade():
    op.execute(sa.text("DELETE FROM leave_types WHERE code = 'day_off'"))
    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.drop_constraint("ck_staff_leave_half_day_single_date", type_="check")
        batch.drop_constraint("ck_staff_leave_portion", type_="check")
        batch.drop_constraint("ck_staff_leave_type", type_="check")
        batch.create_check_constraint(
            "ck_staff_leave_type",
            "leave_type IN ('sick','personal','vacation')",
        )
        batch.drop_column("leave_portion")
