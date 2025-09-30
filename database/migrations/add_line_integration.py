"""Add LINE integration fields to Employee and AttendanceRecord

Revision ID: add_line_integration
Revises:
Create Date: 2025-01-28 10:00:00

This migration adds:
1. LINE integration fields to Employee table (line_user_id, display_name, picture_url)
2. LINE linking code fields to Employee table (linking_code, generated_at)
3. Metadata JSON field to AttendanceRecord table (for QR source, GPS, etc.)
4. device_type and metadata fields to Device table (for QR terminal support)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite


# revision identifiers, used by Alembic.
revision = 'add_line_integration'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Add LINE integration fields"""

    # Add LINE fields to employees table
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.add_column(sa.Column('line_user_id', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('line_display_name', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('line_picture_url', sa.String(500), nullable=True))
        batch_op.add_column(sa.Column('line_linking_code', sa.String(6), nullable=True))
        batch_op.add_column(sa.Column('line_linking_code_generated_at', sa.DateTime(), nullable=True))

        # Create indexes for faster lookups
        batch_op.create_index('ix_employees_line_user_id', ['line_user_id'], unique=False)
        batch_op.create_index('ix_employees_line_linking_code', ['line_linking_code'], unique=False)

    # Add metadata field to attendance_records table
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata', sa.JSON(), nullable=True))

    # Add device_type and metadata to devices table for QR terminal support
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('device_type', sa.String(20), nullable=False, server_default='fingerprint'))
        batch_op.add_column(sa.Column('metadata', sa.JSON(), nullable=True))


def downgrade():
    """Remove LINE integration fields"""

    # Remove fields from employees table
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_index('ix_employees_line_linking_code')
        batch_op.drop_index('ix_employees_line_user_id')
        batch_op.drop_column('line_linking_code_generated_at')
        batch_op.drop_column('line_linking_code')
        batch_op.drop_column('line_picture_url')
        batch_op.drop_column('line_display_name')
        batch_op.drop_column('line_user_id')

    # Remove metadata from attendance_records
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.drop_column('metadata')

    # Remove device_type and metadata from devices
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_column('metadata')
        batch_op.drop_column('device_type')
