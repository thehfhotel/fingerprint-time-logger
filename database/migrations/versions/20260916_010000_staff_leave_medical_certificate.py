"""Medical-certificate attachment for employee sick leave requests.

Revision ID: 20260916_010000
Revises: 20260916_000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260916_010000"
down_revision = "20260916_000000"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.add_column(sa.Column("medical_certificate", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("medical_certificate_content_type", sa.String(50), nullable=True))
        batch.add_column(sa.Column("medical_certificate_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("medical_certificate_uploaded_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("staff_leave_requests") as batch:
        batch.drop_column("medical_certificate_uploaded_at")
        batch.drop_column("medical_certificate_sha256")
        batch.drop_column("medical_certificate_content_type")
        batch.drop_column("medical_certificate")
