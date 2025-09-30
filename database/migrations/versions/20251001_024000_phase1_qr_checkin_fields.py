"""Add Phase 1 QR Check-in fields - LINE integration and QR terminals

Revision ID: 20251001_024000
Revises: 20250919_180700
Create Date: 2025-10-01 02:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251001_024000'
down_revision = '20250919_180700'
branch_labels = None
depends_on = None


def upgrade():
    # Add LINE integration fields to employees table
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.add_column(sa.Column('line_user_id', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('line_display_name', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('line_picture_url', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('line_linking_code', sa.String(length=6), nullable=True))
        batch_op.add_column(sa.Column('line_linking_code_generated_at', sa.DateTime(), nullable=True))
        batch_op.create_unique_constraint('uq_employees_line_user_id', ['line_user_id'])
        batch_op.create_unique_constraint('uq_employees_line_linking_code', ['line_linking_code'])

    # Add QR terminal support fields to devices table
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('device_type', sa.String(length=20), nullable=False, server_default='fingerprint'))
        batch_op.add_column(sa.Column('device_metadata', sa.Text(), nullable=True))


def downgrade():
    # Remove QR terminal support fields from devices table
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_column('device_metadata')
        batch_op.drop_column('device_type')

    # Remove LINE integration fields from employees table
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_constraint('uq_employees_line_linking_code', type_='unique')
        batch_op.drop_constraint('uq_employees_line_user_id', type_='unique')
        batch_op.drop_column('line_linking_code_generated_at')
        batch_op.drop_column('line_linking_code')
        batch_op.drop_column('line_picture_url')
        batch_op.drop_column('line_display_name')
        batch_op.drop_column('line_user_id')
