"""Remove AttendanceAdjustment table and late marking functionality

Revision ID: 4818f8acb84e
Revises: fdab665563da
Create Date: 2025-09-18 17:09:40.989803

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4818f8acb84e'
down_revision: Union[str, None] = 'fdab665563da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the attendance_adjustments table if it exists
    from sqlalchemy import inspect

    # Get the connection from the current context
    connection = op.get_bind()
    inspector = inspect(connection)

    # Check if table exists
    existing_tables = inspector.get_table_names()

    if 'attendance_adjustments' in existing_tables:
        op.drop_table('attendance_adjustments')


def downgrade() -> None:
    # Recreate the attendance_adjustments table
    op.create_table('attendance_adjustments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attendance_record_id', sa.Integer(), nullable=False),
        sa.Column('adjustment_type', sa.String(length=20), nullable=False),
        sa.Column('is_marked_late', sa.Boolean(), nullable=False),
        sa.Column('late_reason', sa.String(length=200), nullable=True),
        sa.Column('adjusted_by', sa.String(length=50), nullable=True),
        sa.Column('adjustment_timestamp', sa.DateTime(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['attendance_record_id'], ['attendance_records.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_attendance_adjustments_id'), 'attendance_adjustments', ['id'], unique=False)
