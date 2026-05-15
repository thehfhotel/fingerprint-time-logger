"""employee shifts + role + per-day assignments

Revision ID: 20260515_000000
Revises: 20250115_000000
Create Date: 2026-05-15

Adds employee shift scheduling:
  - Creates ``shifts`` table and seeds 5 rows (NORMAL, MORNING, MID,
    AFTERNOON, NIGHT). Bangkok-local HH:MM. NIGHT crosses midnight
    (22:00–07:00) — the code treats end_time<=start_time as the
    overnight signal.
  - Adds ``role`` (VARCHAR(20), nullable) and ``default_shift_id``
    (INTEGER FK, nullable) to ``employees``. Existing rows get
    NULL/NULL — meaning "untracked" until the admin assigns a role.
  - Creates ``shift_assignments`` table for per-day overrides
    (badge, date, shift_id). shift_id NULL means "scheduled off".

Notes:
  - SQLite (our prod DB) doesn't enforce FK constraints unless
    PRAGMA foreign_keys=ON, but we declare them anyway for clarity
    and to match what Postgres would do if we migrate.
  - The seed inserts are idempotent (INSERT OR IGNORE) so the
    migration is safe to re-run on a DB that already has shifts.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260515_000000'
down_revision = '20250115_000000'
branch_labels = None
depends_on = None


def upgrade():
    # --- shifts table ---
    op.create_table(
        'shifts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(length=20), nullable=False, unique=True),
        sa.Column('name_th', sa.String(length=50), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=False),
        sa.Column('end_time', sa.Time(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_shifts_code', 'shifts', ['code'], unique=True)

    # Seed the 5 shifts. INSERT OR IGNORE lets re-runs be no-ops.
    op.execute("""
        INSERT OR IGNORE INTO shifts (code, name_th, start_time, end_time, is_active)
        VALUES
            ('NORMAL',    'ปกติ', '08:00', '17:00', 1),
            ('MORNING',   'เช้า', '07:00', '16:00', 1),
            ('MID',       'สาย', '11:00', '20:00', 1),
            ('AFTERNOON', 'บ่าย', '13:00', '22:00', 1),
            ('NIGHT',     'ดึก', '22:00', '07:00', 1)
    """)

    # --- employees: add role + default_shift_id ---
    # SQLite allows ADD COLUMN with nullable + no default; we declare
    # the FK in the column def for clarity even though SQLite doesn't
    # actually enforce it without PRAGMA foreign_keys=ON.
    with op.batch_alter_table('employees') as batch:
        batch.add_column(sa.Column('role', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column(
            'default_shift_id', sa.Integer(),
            sa.ForeignKey('shifts.id'),
            nullable=True,
        ))
    op.create_index('ix_employees_role', 'employees', ['role'])

    # --- shift_assignments table ---
    op.create_table(
        'shift_assignments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'employee_badge_number',
            sa.String(length=50),
            sa.ForeignKey('employees.badge_number'),
            nullable=False,
        ),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column(
            'shift_id',
            sa.Integer(),
            sa.ForeignKey('shifts.id'),
            nullable=True,  # NULL = scheduled off
        ),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            'employee_badge_number', 'date',
            name='uq_assignment_badge_date',
        ),
    )
    op.create_index(
        'ix_shift_assignments_badge',
        'shift_assignments',
        ['employee_badge_number'],
    )
    op.create_index(
        'ix_shift_assignments_date',
        'shift_assignments',
        ['date'],
    )


def downgrade():
    # Reverse order: drop child tables / columns first.
    op.drop_index('ix_shift_assignments_date', table_name='shift_assignments')
    op.drop_index('ix_shift_assignments_badge', table_name='shift_assignments')
    op.drop_table('shift_assignments')

    op.drop_index('ix_employees_role', table_name='employees')
    with op.batch_alter_table('employees') as batch:
        batch.drop_column('default_shift_id')
        batch.drop_column('role')

    op.drop_index('ix_shifts_code', table_name='shifts')
    op.drop_table('shifts')
