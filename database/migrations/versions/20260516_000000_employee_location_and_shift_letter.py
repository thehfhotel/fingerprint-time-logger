"""employee location + shift letter (A/B/C/D)

Revision ID: 20260516_000000
Revises: 20260515_000000
Create Date: 2026-05-16

Adds:
  - employees.location  ('HF' | 'HF_VILLE' | NULL)
  - shifts.letter       (single char A/B/C/D, matching the reception
                         monthly roster spreadsheet — A=MORNING,
                         B=AFTERNOON, C=MID, D=NIGHT, NORMAL stays NULL)
  - index on employees(location)

Idempotent — the SQLite ALTER COLUMN happens once but the letter
UPDATEs are safe to re-run.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260516_000000'
down_revision = '20260515_000000'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('employees') as batch:
        batch.add_column(sa.Column('location', sa.String(length=20), nullable=True))
    op.create_index('ix_employees_location', 'employees', ['location'])

    with op.batch_alter_table('shifts') as batch:
        batch.add_column(sa.Column('letter', sa.String(length=1), nullable=True))

    # Backfill letters for the 4 reception shifts. NORMAL stays NULL.
    op.execute("UPDATE shifts SET letter='A' WHERE code='MORNING'")
    op.execute("UPDATE shifts SET letter='B' WHERE code='AFTERNOON'")
    op.execute("UPDATE shifts SET letter='C' WHERE code='MID'")
    op.execute("UPDATE shifts SET letter='D' WHERE code='NIGHT'")


def downgrade():
    with op.batch_alter_table('shifts') as batch:
        batch.drop_column('letter')

    op.drop_index('ix_employees_location', table_name='employees')
    with op.batch_alter_table('employees') as batch:
        batch.drop_column('location')
