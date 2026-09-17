"""Track staff leave delivery in HF Family slot reports.

Revision ID: 20260917_010000
Revises: 20260917_000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260917_010000"
down_revision = "20260917_000000"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.add_column(sa.Column("family_reported_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_staff_leave_requests_family_reported_at", ["family_reported_at"])


def downgrade():
    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.drop_index("ix_staff_leave_requests_family_reported_at")
        batch.drop_column("family_reported_at")
