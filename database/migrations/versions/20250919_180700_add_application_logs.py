"""Add ApplicationLog table for comprehensive logging

Revision ID: 20250919_180700
Revises: 4818f8acb84e
Create Date: 2025-09-19 18:07:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250919_180700'
down_revision = '4818f8acb84e'
branch_labels = None
depends_on = None


def upgrade():
    # ApplicationLog table already exists in database from previous operation
    # This migration just makes Alembic aware of it
    pass


def downgrade():
    # Don't remove the table since it contains important logging data
    pass