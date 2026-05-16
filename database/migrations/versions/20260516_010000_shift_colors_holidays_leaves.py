"""shift colors + public holidays + employee leaves

Revision ID: 20260516_010000
Revises: 20260516_000000
Create Date: 2026-05-16

Adds three things:
  - shifts.color (hex string) + backfill 5 defaults
  - public_holidays table (date PK, name) for company-wide non-working
    days. Applies to every employee at every location.
  - employee_leaves table for per-employee leaves (vacation / personal
    / sick). One row per (badge, date); multi-day leaves are inserted
    as N rows.

Roster cells and the /by-date page consult both tables in addition to
shift_assignments.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260516_010000'
down_revision = '20260516_000000'
branch_labels = None
depends_on = None


# Default color per shift code. Light pastels — they're cell backgrounds
# behind A/B/C/D text in the monthly roster, so they need to be readable
# without contrast issues.
_DEFAULT_SHIFT_COLORS = {
    "MORNING":   "#86efac",  # A — green
    "AFTERNOON": "#93c5fd",  # B — blue
    "MID":       "#fde68a",  # C — yellow
    "NIGHT":     "#c4b5fd",  # D — purple
    "NORMAL":    "#e5e7eb",  # gray (not a reception shift)
}


def upgrade():
    # --- shifts.color ---
    with op.batch_alter_table('shifts') as batch:
        batch.add_column(sa.Column('color', sa.String(length=7), nullable=True))

    for code, color in _DEFAULT_SHIFT_COLORS.items():
        op.execute(
            sa.text("UPDATE shifts SET color = :color WHERE code = :code")
            .bindparams(color=color, code=code)
        )

    # --- public_holidays ---
    op.create_table(
        'public_holidays',
        sa.Column('date', sa.Date(), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # --- employee_leaves ---
    op.create_table(
        'employee_leaves',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'employee_badge_number',
            sa.String(length=50),
            sa.ForeignKey('employees.badge_number'),
            nullable=False,
        ),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('leave_type', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            'employee_badge_number', 'date',
            name='uq_leave_badge_date',
        ),
    )
    op.create_index(
        'ix_employee_leaves_badge',
        'employee_leaves',
        ['employee_badge_number'],
    )
    op.create_index(
        'ix_employee_leaves_date',
        'employee_leaves',
        ['date'],
    )


def downgrade():
    op.drop_index('ix_employee_leaves_date', table_name='employee_leaves')
    op.drop_index('ix_employee_leaves_badge', table_name='employee_leaves')
    op.drop_table('employee_leaves')
    op.drop_table('public_holidays')

    with op.batch_alter_table('shifts') as batch:
        batch.drop_column('color')
