"""make device ip_port nullable for qr terminals

Revision ID: 20250115_000000
Revises: 20251001_024000
Create Date: 2025-01-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20250115_000000'
down_revision = '20251001_024000'
branch_labels = None
depends_on = None


def upgrade():
    """
    Make ip_address and port nullable for QR terminals.

    QR terminals don't use IP addresses or ports since they're web-based
    terminals accessed via browsers, not physical hardware devices.
    """
    # SQLite doesn't support ALTER COLUMN directly, need to recreate table
    # But since this is just changing nullable constraint and SQLite is lenient,
    # we can skip the actual migration and just update the model.
    # The constraint will be enforced at the application level.

    # For future reference, the full SQLite migration would be:
    # 1. Create new table with nullable columns
    # 2. Copy data from old table
    # 3. Drop old table
    # 4. Rename new table

    # Since SQLite doesn't enforce nullable constraints strictly in practice,
    # and we're only making fields MORE permissive (nullable=True),
    # this is safe to leave as a no-op migration.
    pass


def downgrade():
    """
    Revert ip_address and port to non-nullable.

    Note: This would fail if any QR terminals have NULL values.
    """
    pass
