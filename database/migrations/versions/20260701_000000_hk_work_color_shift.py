"""Housekeeping 'ปกติ' work-color pseudo-shift (HK_WORK)

Adds a Shift row code='HK_WORK' that exists ONLY to hold the colour the
housekeeping day-off grid uses for its "ปกติ" (work) cells — independent of
the real MORNING / NORMAL shifts, so recolouring it does NOT change
reception's "A" (which is MORNING). Mirrors the existing OFF pseudo-shift,
with two deliberate differences:

  * letter = NULL  → kept OUT of the reception roster legend
    (SHIFTS.filter(s => s.letter)) and the reception cell options
    (s.letter && code !== 'OFF'); only the housekeeping grid reads its colour.
  * 00:00-00:00 hours never match a real maid schedule, so _shift_for_hours
    never resolves to it, and the assignment API rejects it — it is never
    assigned to any day.

Incremental on top of the live head (employee_schedules); production applies
it via the container's `alembic upgrade head` on the next deploy.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260701_000000'
down_revision = '20260629_000000'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("""
        INSERT OR IGNORE INTO shifts (code, letter, name_th, start_time, end_time, color, is_active)
        VALUES ('HK_WORK', NULL, 'ปกติ (แม่บ้าน)', '00:00', '00:00', '#86efac', 1)
    """))


def downgrade():
    op.execute("DELETE FROM shifts WHERE code = 'HK_WORK'")
