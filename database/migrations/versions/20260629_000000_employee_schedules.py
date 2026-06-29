"""employee effective-dated schedules (workdays + custom hours + role history)

Revision ID: 20260629_000000
Revises: 20260516_020000
Create Date: 2026-06-29

Adds the employee_schedules table: one effective-dated row per schedule
version (role + work_days + work_start/work_end), so role/workday/hours
changes keep history. For any date D the applicable row is the latest
with effective_from <= D.

Backfill is non-destructive: every tracked employee (role set, or a
default_shift_id set) gets one version at 2000-01-01 that reproduces
today's behaviour exactly — non-reception roles get work_days = all 7
(every calendar day, matching the old role-default behaviour) and hours
from their default/role shift; reception gets role-only (roster-driven).
So every existing report stays byte-identical until an admin edits a
schedule. Idempotent: skips employees that already have a version.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260629_000000'
down_revision = '20260516_020000'
branch_labels = None
depends_on = None


_ROLE_DEFAULT_CODE = {
    'housekeeping': 'MORNING',
    'technician': 'NORMAL',
    'admin': 'NORMAL',
}
_ALL_DAYS = '0,1,2,3,4,5,6'
_EPOCH = '2000-01-01'


def upgrade():
    op.create_table(
        'employee_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_badge_number', sa.String(length=50), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=True),
        sa.Column('work_days', sa.String(length=20), nullable=True),
        sa.Column('work_start', sa.Time(), nullable=True),
        sa.Column('work_end', sa.Time(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['employee_badge_number'], ['employees.badge_number']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'employee_badge_number', 'effective_from',
            name='uq_employee_schedule_date',
        ),
    )
    op.create_index(
        'ix_employee_schedules_badge', 'employee_schedules',
        ['employee_badge_number'],
    )
    op.create_index(
        'ix_employee_schedules_effective_from', 'employee_schedules',
        ['effective_from'],
    )

    # ---- Backfill -------------------------------------------------------
    bind = op.get_bind()
    shift_hours = {
        row[0]: (row[1], row[2])
        for row in bind.execute(sa.text(
            "SELECT code, start_time, end_time FROM shifts"
        ))
    }
    employees = bind.execute(sa.text(
        "SELECT e.badge_number, e.role, s.code "
        "FROM employees e LEFT JOIN shifts s ON e.default_shift_id = s.id"
    )).fetchall()

    insert = sa.text(
        "INSERT INTO employee_schedules "
        "(employee_badge_number, effective_from, role, work_days, "
        " work_start, work_end, created_at, updated_at) "
        "VALUES (:b, :ef, :role, :wd, :ws, :we, "
        " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    for badge, role, default_code in employees:
        if role is None and default_code is None:
            continue  # untracked — leave it untracked (legacy fallback)

        already = bind.execute(sa.text(
            "SELECT 1 FROM employee_schedules "
            "WHERE employee_badge_number = :b LIMIT 1"
        ), {"b": badge}).first()
        if already:
            continue

        if role == 'reception':
            work_days = work_start = work_end = None
        else:
            work_days = _ALL_DAYS
            code = default_code or _ROLE_DEFAULT_CODE.get(role)
            hours = shift_hours.get(code) if (code and code != 'OFF') else None
            work_start, work_end = hours if hours else (None, None)

        bind.execute(insert, {
            "b": badge, "ef": _EPOCH, "role": role,
            "wd": work_days, "ws": work_start, "we": work_end,
        })


def downgrade():
    op.drop_index('ix_employee_schedules_effective_from', table_name='employee_schedules')
    op.drop_index('ix_employee_schedules_badge', table_name='employee_schedules')
    op.drop_table('employee_schedules')
