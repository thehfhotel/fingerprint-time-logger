"""Employee registry — self-onboarding + app grants + NFC slot

Revision ID: 20260702_000000
Revises: 20260701_000000
Create Date: 2026-07-02

Adds the Employee Management + self-service onboarding feature:

1. employees.email — nullable UNIQUE synthetic identity slot, admin-side
   only (never collected from the employee — LINE-only policy). Auto-filled
   on approval as "<badge lowercase>@emp.thehfhotel.org" when still NULL.
2. employees.pending_approval — NOT NULL default false. True from
   self-onboard submission until an admin approves/rejects.
3. employees.join_source — NOT NULL default 'device'. One of
   'device' | 'manual' | 'self_onboard'.
4. employees.nfc_card_uid — nullable UNIQUE physical card slot for the
   HF ID identity layer built next.
5. employee_app_grants table — per-employee app access grants (rooms,
   portal, ...). App catalog is a constant in code, not a table.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260702_000000'
down_revision = '20260701_000000'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=120), nullable=True))
        batch_op.add_column(
            sa.Column('pending_approval', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )
        batch_op.add_column(
            sa.Column('join_source', sa.String(length=20), nullable=False, server_default='device')
        )
        batch_op.add_column(sa.Column('nfc_card_uid', sa.String(length=64), nullable=True))

    op.create_index('ix_employees_email', 'employees', ['email'], unique=True)
    op.create_index('ix_employees_nfc_card_uid', 'employees', ['nfc_card_uid'], unique=True)

    op.create_table(
        'employee_app_grants',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'employee_badge_number',
            sa.String(length=50),
            sa.ForeignKey('employees.badge_number'),
            nullable=False,
        ),
        sa.Column('app_id', sa.String(length=50), nullable=False),
        sa.Column('granted_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('granted_by', sa.String(length=100), nullable=True),
        sa.UniqueConstraint('employee_badge_number', 'app_id', name='uq_employee_app_grant'),
    )
    op.create_index(
        'ix_employee_app_grants_badge', 'employee_app_grants', ['employee_badge_number']
    )


def downgrade():
    op.drop_index('ix_employee_app_grants_badge', table_name='employee_app_grants')
    op.drop_table('employee_app_grants')

    op.drop_index('ix_employees_nfc_card_uid', table_name='employees')
    op.drop_index('ix_employees_email', table_name='employees')

    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_column('nfc_card_uid')
        batch_op.drop_column('join_source')
        batch_op.drop_column('pending_approval')
        batch_op.drop_column('email')
