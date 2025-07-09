"""Remove job roles - simplify employee management

Revision ID: 736245057be5
Revises: a823a6592a97
Create Date: 2025-07-09 09:23:46.965617

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '736245057be5'
down_revision: Union[str, None] = 'a823a6592a97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove job_role_id column from employees table
    with op.batch_alter_table('employees', recreate='always') as batch_op:
        batch_op.drop_column('job_role_id')
    
    # Drop job_roles table
    op.drop_table('job_roles')


def downgrade() -> None:
    # Recreate job_roles table
    op.create_table('job_roles',
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column('role_name', sa.VARCHAR(length=50), nullable=False),
        sa.Column('display_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('description', sa.TEXT(), nullable=True),
        sa.Column('has_shifts', sa.BOOLEAN(), nullable=False),
        sa.Column('is_active', sa.BOOLEAN(), nullable=False),
        sa.Column('created_at', sa.DATETIME(), nullable=True),
        sa.Column('updated_at', sa.DATETIME(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_name')
    )
    
    # Add job_role_id column back to employees table
    with op.batch_alter_table('employees', recreate='always') as batch_op:
        batch_op.add_column(sa.Column('job_role_id', sa.INTEGER(), nullable=True))
        batch_op.create_foreign_key('fk_employees_job_role_id', 'job_roles', ['job_role_id'], ['id'])
