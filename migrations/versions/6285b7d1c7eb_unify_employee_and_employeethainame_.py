"""Unify Employee and EmployeeThaiName models

Revision ID: 6285b7d1c7eb
Revises: 
Create Date: 2025-07-02 10:37:57.716711

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6285b7d1c7eb'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Migrate Employee and EmployeeThaiName models into unified Employee model
    Steps:
    1. Add new columns to employees table
    2. Migrate data from employee_thai_names to employees
    3. Update attendance_records foreign key
    4. Drop old employee_thai_names table
    """
    
    # Step 1: Add new columns to employees table
    op.add_column('employees', sa.Column('badge_number', sa.String(length=50), nullable=True))  # Temporary nullable
    op.add_column('employees', sa.Column('english_name', sa.String(length=100), nullable=True))
    op.add_column('employees', sa.Column('thai_name', sa.String(length=100), nullable=True))
    op.add_column('employees', sa.Column('display_name', sa.String(length=100), nullable=True))  # Temporary nullable
    op.add_column('employees', sa.Column('job_role_id', sa.Integer(), nullable=True))
    op.add_column('employees', sa.Column('is_hidden', sa.Boolean(), nullable=True))
    
    # Step 2: Migrate existing employee data - copy employee_id to badge_number and name to english_name
    op.execute("""
        UPDATE employees 
        SET badge_number = employee_id,
            english_name = name,
            display_name = name,
            is_hidden = 0
    """)
    
    # Step 3: Merge data from employee_thai_names table
    op.execute("""
        UPDATE employees 
        SET thai_name = (
            SELECT eth.thai_name 
            FROM employee_thai_names eth 
            WHERE employees.badge_number = eth.badge_number
        ),
        job_role_id = (
            SELECT eth.job_role_id 
            FROM employee_thai_names eth 
            WHERE employees.badge_number = eth.badge_number
        ),
        is_hidden = COALESCE((
            SELECT eth.is_hidden 
            FROM employee_thai_names eth 
            WHERE employees.badge_number = eth.badge_number
        ), 0),
        display_name = COALESCE((
            SELECT eth.thai_name 
            FROM employee_thai_names eth 
            WHERE employees.badge_number = eth.badge_number
        ), 'พนักงาน ' || employees.badge_number)
        WHERE EXISTS (
            SELECT 1 FROM employee_thai_names eth 
            WHERE employees.badge_number = eth.badge_number
        )
    """)
    
    # Step 4: Insert employees that only exist in employee_thai_names (orphaned records)
    op.execute("""
        INSERT INTO employees (badge_number, english_name, thai_name, display_name, job_role_id, is_active, is_hidden, created_at, updated_at)
        SELECT 
            eth.badge_number,
            NULL as english_name,
            eth.thai_name,
            COALESCE(eth.thai_name, 'พนักงาน ' || eth.badge_number) as display_name,
            eth.job_role_id,
            eth.is_active,
            eth.is_hidden,
            eth.created_at,
            eth.updated_at
        FROM employee_thai_names eth
        WHERE NOT EXISTS (
            SELECT 1 FROM employees e 
            WHERE e.badge_number = eth.badge_number
        )
    """)
    
    # Step 5: Make badge_number and display_name NOT NULL now that data is migrated
    op.alter_column('employees', 'badge_number', nullable=False)
    op.alter_column('employees', 'display_name', nullable=False)
    
    # Step 6: Create unique index on badge_number
    op.create_index(op.f('ix_employees_badge_number'), 'employees', ['badge_number'], unique=True)
    
    # Step 7: Create foreign key to job_roles
    op.create_foreign_key(None, 'employees', 'job_roles', ['job_role_id'], ['id'])
    
    # Step 8: Update attendance_records table
    op.add_column('attendance_records', sa.Column('employee_badge_number', sa.String(length=50), nullable=True))  # Temporary nullable
    
    # Copy employee_id to employee_badge_number
    op.execute("""
        UPDATE attendance_records 
        SET employee_badge_number = employee_id
    """)
    
    # Make employee_badge_number NOT NULL
    op.alter_column('attendance_records', 'employee_badge_number', nullable=False)
    
    # Drop old foreign key and create new one
    op.drop_constraint(None, 'attendance_records', type_='foreignkey')
    op.create_foreign_key(None, 'attendance_records', 'employees', ['employee_badge_number'], ['badge_number'])
    
    # Step 9: Clean up old columns and tables
    op.drop_column('attendance_records', 'employee_id')
    op.drop_index('ix_employees_employee_id', table_name='employees')
    op.drop_column('employees', 'name')
    op.drop_column('employees', 'employee_id')
    
    # Step 10: Drop employee_thai_names table
    op.drop_index('ix_employee_thai_names_badge_number', table_name='employee_thai_names')
    op.drop_index('ix_employee_thai_names_id', table_name='employee_thai_names')
    op.drop_table('employee_thai_names')
    
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('employees', sa.Column('employee_id', sa.VARCHAR(length=50), nullable=False))
    op.add_column('employees', sa.Column('name', sa.VARCHAR(length=100), nullable=False))
    op.drop_constraint(None, 'employees', type_='foreignkey')
    op.drop_index(op.f('ix_employees_badge_number'), table_name='employees')
    op.create_index('ix_employees_employee_id', 'employees', ['employee_id'], unique=False)
    op.drop_column('employees', 'is_hidden')
    op.drop_column('employees', 'job_role_id')
    op.drop_column('employees', 'display_name')
    op.drop_column('employees', 'thai_name')
    op.drop_column('employees', 'english_name')
    op.drop_column('employees', 'badge_number')
    op.add_column('attendance_records', sa.Column('employee_id', sa.VARCHAR(length=50), nullable=False))
    op.drop_constraint(None, 'attendance_records', type_='foreignkey')
    op.create_foreign_key(None, 'attendance_records', 'employees', ['employee_id'], ['employee_id'])
    op.drop_column('attendance_records', 'employee_badge_number')
    op.create_table('employee_thai_names',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('badge_number', sa.VARCHAR(length=50), nullable=False),
    sa.Column('thai_name', sa.VARCHAR(length=100), nullable=False),
    sa.Column('job_role_id', sa.INTEGER(), nullable=True),
    sa.Column('is_active', sa.BOOLEAN(), nullable=True),
    sa.Column('is_hidden', sa.BOOLEAN(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), nullable=True),
    sa.Column('updated_at', sa.DATETIME(), nullable=True),
    sa.ForeignKeyConstraint(['job_role_id'], ['job_roles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_employee_thai_names_id', 'employee_thai_names', ['id'], unique=False)
    op.create_index('ix_employee_thai_names_badge_number', 'employee_thai_names', ['badge_number'], unique=False)
    # ### end Alembic commands ###
