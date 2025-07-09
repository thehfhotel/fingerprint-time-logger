"""Add AttendanceAdjustment table for late marking

Revision ID: fdab665563da
Revises: 736245057be5
Create Date: 2025-07-09 10:04:27.250452

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fdab665563da'
down_revision: Union[str, None] = '736245057be5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create attendance_adjustments table if it doesn't exist
    import sqlite3
    from sqlalchemy import create_engine, inspect
    
    # Get the connection from the current context
    connection = op.get_bind()
    inspector = inspect(connection)
    
    # Check if table exists
    existing_tables = inspector.get_table_names()
    
    if 'attendance_adjustments' not in existing_tables:
        op.create_table('attendance_adjustments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('attendance_record_id', sa.Integer(), nullable=False),
            sa.Column('adjustment_type', sa.String(length=20), nullable=False),
            sa.Column('is_marked_late', sa.Boolean(), nullable=False, default=False),
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


def downgrade() -> None:
    # Drop attendance_adjustments table if it exists
    from sqlalchemy import inspect
    
    connection = op.get_bind()
    inspector = inspect(connection)
    existing_tables = inspector.get_table_names()
    
    if 'attendance_adjustments' in existing_tables:
        op.drop_index(op.f('ix_attendance_adjustments_id'), table_name='attendance_adjustments')
        op.drop_table('attendance_adjustments')
