"""Fix nullable column constraints

Revision ID: cbd059abd42d
Revises: 6285b7d1c7eb
Create Date: 2025-07-02 20:25:22.847558

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cbd059abd42d'
down_revision: Union[str, None] = '6285b7d1c7eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires table recreation to change nullable constraints
    
    # Fix attendance_records table
    with op.batch_alter_table('attendance_records', recreate='always') as batch_op:
        batch_op.alter_column('id',
                   existing_type=sa.INTEGER(),
                   nullable=False,
                   autoincrement=True)
        batch_op.alter_column('sync_status',
                   existing_type=sa.VARCHAR(length=20),
                   nullable=False,
                   server_default=sa.text("'synced'"))
    
    # Fix employees table
    with op.batch_alter_table('employees', recreate='always') as batch_op:
        batch_op.alter_column('id',
                   existing_type=sa.INTEGER(),
                   nullable=False,
                   autoincrement=True)
        # Keep is_active and is_hidden as NOT NULL with defaults
        batch_op.alter_column('is_active',
                   existing_type=sa.BOOLEAN(),
                   nullable=False,
                   server_default=sa.text('1'))
        batch_op.alter_column('is_hidden',
                   existing_type=sa.BOOLEAN(),
                   nullable=False,
                   server_default=sa.text('0'))


def downgrade() -> None:
    # Revert changes using batch operations
    
    # Revert employees table
    with op.batch_alter_table('employees', recreate='always') as batch_op:
        batch_op.alter_column('id',
                   existing_type=sa.INTEGER(),
                   nullable=True,
                   autoincrement=True)
        batch_op.alter_column('is_active',
                   existing_type=sa.BOOLEAN(),
                   nullable=False,
                   server_default=sa.text('1'))
        batch_op.alter_column('is_hidden',
                   existing_type=sa.BOOLEAN(),
                   nullable=False,
                   server_default=sa.text('0'))
    
    # Revert attendance_records table
    with op.batch_alter_table('attendance_records', recreate='always') as batch_op:
        batch_op.alter_column('id',
                   existing_type=sa.INTEGER(),
                   nullable=True,
                   autoincrement=True)
        batch_op.alter_column('sync_status',
                   existing_type=sa.VARCHAR(length=20),
                   nullable=True,
                   server_default=sa.text("'synced'"))
