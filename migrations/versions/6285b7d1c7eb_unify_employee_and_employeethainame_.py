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
    
    # SQLite-compatible migration using table recreation approach
    # Step 1: Create new employees_new table with unified structure
    op.execute("""
        CREATE TABLE employees_new (
            id INTEGER PRIMARY KEY,
            badge_number VARCHAR(50) NOT NULL UNIQUE,
            english_name VARCHAR(100),
            thai_name VARCHAR(100),
            display_name VARCHAR(100) NOT NULL,
            department VARCHAR(100),
            position VARCHAR(100),
            job_role_id INTEGER,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            is_hidden BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_role_id) REFERENCES job_roles(id)
        )
    """)
    
    # Step 2: Migrate data from employees table
    op.execute("""
        INSERT INTO employees_new (
            id, badge_number, english_name, display_name, department, position, 
            is_active, is_hidden, created_at, updated_at
        )
        SELECT 
            id,
            employee_id as badge_number,
            name as english_name,
            name as display_name,
            department,
            position,
            is_active,
            0 as is_hidden,
            created_at,
            updated_at
        FROM employees
    """)
    
    # Step 3: Merge data from employee_thai_names table
    op.execute("""
        UPDATE employees_new 
        SET thai_name = (
            SELECT eth.thai_name 
            FROM employee_thai_names eth 
            WHERE employees_new.badge_number = eth.badge_number
        ),
        job_role_id = (
            SELECT eth.job_role_id 
            FROM employee_thai_names eth 
            WHERE employees_new.badge_number = eth.badge_number
        ),
        is_hidden = COALESCE((
            SELECT eth.is_hidden 
            FROM employee_thai_names eth 
            WHERE employees_new.badge_number = eth.badge_number
        ), 0),
        display_name = COALESCE((
            SELECT eth.thai_name 
            FROM employee_thai_names eth 
            WHERE employees_new.badge_number = eth.badge_number
        ), 'พนักงาน ' || employees_new.badge_number)
        WHERE EXISTS (
            SELECT 1 FROM employee_thai_names eth 
            WHERE employees_new.badge_number = eth.badge_number
        )
    """)
    
    # Step 4: Insert employees that only exist in employee_thai_names (orphaned records)
    op.execute("""
        INSERT INTO employees_new (
            badge_number, english_name, thai_name, display_name, job_role_id, 
            is_active, is_hidden, created_at, updated_at
        )
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
            SELECT 1 FROM employees_new e 
            WHERE e.badge_number = eth.badge_number
        )
    """)
    
    # Step 5: Create new attendance_records table with updated FK
    op.execute("""
        CREATE TABLE attendance_records_new (
            id INTEGER PRIMARY KEY,
            employee_badge_number VARCHAR(50) NOT NULL,
            device_id INTEGER NOT NULL,
            timestamp DATETIME NOT NULL,
            punch_type INTEGER NOT NULL,
            status INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            sync_status VARCHAR(20) DEFAULT 'synced',
            local_id VARCHAR(36),
            created_locally BOOLEAN DEFAULT 0,
            validation_status VARCHAR(20) DEFAULT 'unvalidated',
            lateness_minutes INTEGER,
            early_minutes INTEGER,
            expected_time TIME,
            schedule_type VARCHAR(20),
            validation_message TEXT,
            validated_at DATETIME,
            FOREIGN KEY (employee_badge_number) REFERENCES employees_new(badge_number),
            FOREIGN KEY (device_id) REFERENCES devices(id)
        )
    """)
    
    # Step 6: Migrate attendance records data
    op.execute("""
        INSERT INTO attendance_records_new (
            id, employee_badge_number, device_id, timestamp, punch_type, status,
            created_at, sync_status, local_id, created_locally, validation_status,
            lateness_minutes, early_minutes, expected_time, schedule_type,
            validation_message, validated_at
        )
        SELECT 
            id, employee_id as employee_badge_number, device_id, timestamp, punch_type, status,
            created_at, sync_status, local_id, created_locally, validation_status,
            lateness_minutes, early_minutes, expected_time, schedule_type,
            validation_message, validated_at
        FROM attendance_records
    """)
    
    # Step 7: Drop old tables and rename new ones
    op.drop_table('attendance_records')
    op.drop_table('employees')
    op.drop_table('employee_thai_names')
    
    op.execute("ALTER TABLE employees_new RENAME TO employees")
    op.execute("ALTER TABLE attendance_records_new RENAME TO attendance_records")
    
    # Step 8: Create indexes
    op.create_index(op.f('ix_employees_id'), 'employees', ['id'], unique=False)
    op.create_index(op.f('ix_employees_badge_number'), 'employees', ['badge_number'], unique=True)
    op.create_index(op.f('ix_attendance_records_id'), 'attendance_records', ['id'], unique=False)
    op.create_index(op.f('ix_attendance_records_timestamp'), 'attendance_records', ['timestamp'], unique=False)
    
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
