"""Employee LINE leave requests and atomic per-day overlap reservations.

Revision ID: 20260916_000000
Revises: 20260905_000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260916_000000"
down_revision = "20260905_000000"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "staff_leave_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("employee_badge_number", sa.String(50), sa.ForeignKey("employees.badge_number"), nullable=False),
        sa.Column("employee_name", sa.String(100), nullable=False),
        sa.Column("department", sa.String(100)),
        sa.Column("location", sa.String(20)),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_by", sa.String(254)),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.CheckConstraint("status IN ('pending','approved','rejected','cancelled')", name="ck_staff_leave_status"),
        sa.CheckConstraint("leave_type IN ('sick','personal','vacation')", name="ck_staff_leave_type"),
        sa.CheckConstraint("date_to >= date_from", name="ck_staff_leave_dates"),
    )
    op.create_index("ix_staff_leave_requests_employee_badge_number", "staff_leave_requests", ["employee_badge_number"])
    op.create_index("ix_staff_leave_requests_status", "staff_leave_requests", ["status"])
    op.create_table(
        "staff_leave_days",
        sa.Column("employee_badge_number", sa.String(50), sa.ForeignKey("employees.badge_number"), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("request_id", sa.String(32), sa.ForeignKey("staff_leave_requests.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_staff_leave_days_request_id", "staff_leave_days", ["request_id"])


def downgrade():
    op.drop_index("ix_staff_leave_days_request_id", table_name="staff_leave_days")
    op.drop_table("staff_leave_days")
    op.drop_index("ix_staff_leave_requests_status", table_name="staff_leave_requests")
    op.drop_index("ix_staff_leave_requests_employee_badge_number", table_name="staff_leave_requests")
    op.drop_table("staff_leave_requests")
