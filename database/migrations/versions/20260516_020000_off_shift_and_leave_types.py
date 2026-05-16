"""OFF shift row + leave_types table

Revision ID: 20260516_020000
Revises: 20260516_010000
Create Date: 2026-05-16

Two additions for the "ตั้งค่าสีกะ" legend on /v2/shifts-admin:

1. Inserts a Shift row with code='OFF'. OFF is a pseudo-shift used
   purely for color display on the roster — it isn't actually
   assignable (the API rejects shift_code='OFF' in /assignments PUT;
   the cell handler writes shift_code=null when admin picks OFF).
   Giving it a real Shift row lets the existing
   PATCH /shifts/OFF/color endpoint work without special-casing.

2. Creates `leave_types` table seeded with the 4 types
   (vacation/personal/sick/public_holiday) + their default colors.
   Admin can recolor each via PATCH /api/private/leaves/types/{code}/color.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260516_020000'
down_revision = '20260516_010000'
branch_labels = None
depends_on = None


# Same palette the frontend had hardcoded — kept identical so the
# initial UI render is unchanged after migration.
_LEAVE_TYPE_SEEDS = [
    ("vacation",       "ลาพักร้อน",        "#bbf7d0"),
    ("personal",       "ลากิจ",            "#fdba74"),
    ("sick",           "ลาป่วย",           "#fbcfe8"),
    ("public_holiday", "วันหยุดนักขัตฤกษ์", "#fca5a5"),
]


def upgrade():
    # ---- OFF pseudo-shift row ----
    # Times set to 00:00-00:00 because they're never used (shift_window_for
    # is never called against OFF). Letter='OFF' so the roster legend
    # filter (SHIFTS.filter(s => s.letter)) naturally includes it.
    op.execute(sa.text("""
        INSERT OR IGNORE INTO shifts (code, letter, name_th, start_time, end_time, color, is_active)
        VALUES ('OFF', 'OFF', 'หยุด', '00:00', '00:00', '#e5e7eb', 1)
    """))

    # ---- leave_types table ----
    op.create_table(
        'leave_types',
        sa.Column('code', sa.String(length=20), primary_key=True),
        sa.Column('name_th', sa.String(length=50), nullable=False),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    for code, name_th, color in _LEAVE_TYPE_SEEDS:
        op.execute(sa.text(
            "INSERT OR IGNORE INTO leave_types (code, name_th, color) "
            "VALUES (:c, :n, :col)"
        ).bindparams(c=code, n=name_th, col=color))


def downgrade():
    op.drop_table('leave_types')
    op.execute("DELETE FROM shifts WHERE code = 'OFF'")
