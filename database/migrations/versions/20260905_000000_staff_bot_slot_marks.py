"""Staff bot slot marks — once-per-slot-per-group digest bookkeeping

Revision ID: 20260905_000000
Revises: 20260801_000000
Create Date: 2026-09-05

Phase 2 of the staff bot (HF ภายใน, hf-erp ADR 0007): four daily Bangkok
slots (06:00-10:00, 12:00-14:00, 14:30-16:30, 19:30-21:30) each carry ONE
งานค้าง digest into a LINE group, riding a free reply token on human
traffic instead of a metered push.

"Once per slot" must survive a container restart mid-debounce, so the mark
is a row, not in-process state:

    staff_bot_slot_marks(id, group_id, bkk_date, slot, state, filed_at,
                         sent_at, trigger)
    UNIQUE(group_id, bkk_date, slot)

`state` is 'pending' (filed when the slot triggers, before the debounced
reply goes out) or 'sent' (the reply succeeded). Every other outcome — send
failed, housekeeping dark so nothing was posted, or a 'pending' left stale
by a restart — DELETES the row so the next qualifying message in the same
window re-triggers. `bkk_date` is the Bangkok calendar date ('YYYY-MM-DD')
of the triggering event, because the windows are Bangkok wall-clock.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260905_000000'
down_revision = '20260801_000000'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'staff_bot_slot_marks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('group_id', sa.String(length=64), nullable=False),
        sa.Column('bkk_date', sa.String(length=10), nullable=False),
        sa.Column('slot', sa.String(length=20), nullable=False),
        sa.Column('state', sa.String(length=10), nullable=False),
        sa.Column('filed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('trigger', sa.String(length=20), nullable=False),
        sa.UniqueConstraint('group_id', 'bkk_date', 'slot', name='uq_staff_bot_slot_mark'),
    )
    op.create_index(
        'ix_staff_bot_slot_marks_group_id', 'staff_bot_slot_marks', ['group_id']
    )


def downgrade():
    op.drop_index('ix_staff_bot_slot_marks_group_id', table_name='staff_bot_slot_marks')
    op.drop_table('staff_bot_slot_marks')
