#!/usr/bin/env python3
"""
Script to remove remaining unused models from models.py
"""

import re

def remove_unused_models():
    """Remove remaining unused models efficiently"""
    
    filepath = '/home/nut/fingerprint-time-logger/app/models/models.py'
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Models to remove (class name -> replacement comment)
    models_to_remove = {
        'ErrorEvent': 'ErrorEvent model removed - not used by application',
        'WorkSchedule': 'WorkSchedule model removed - not used by application',
        'WorkShift': 'WorkShift model removed - not used by application', 
        'EmployeeMonthlySchedule': 'EmployeeMonthlySchedule model removed - not used by application',
        'ReceptionShiftAssignment': 'ReceptionShiftAssignment model removed - not used by application',
        'TimeCheckConfig': 'TimeCheckConfig model removed - not used by application',
        'DailyAttendanceSummary': 'DailyAttendanceSummary model removed - not used by application',
        'Holiday': 'Holiday model removed - not used by application',
        'MonthlyAttendanceStats': 'MonthlyAttendanceStats model removed - not used by application',
    }
    
    # Remove each model class
    for model_name, replacement in models_to_remove.items():
        # Pattern to match entire class definition
        pattern = rf'class {model_name}.*?(?=\n\n(?:class|\# |$)|\Z)'
        content = re.sub(pattern, f'# {replacement}', content, flags=re.DOTALL)
    
    # Remove enum classes that are no longer needed
    enum_classes = ['AttendanceStatus', 'HolidayType']
    for enum_name in enum_classes:
        pattern = rf'class {enum_name}.*?(?=\n\n(?:class|\# |$)|\Z)'
        content = re.sub(pattern, f'# {enum_name} enum removed - not used by application', content, flags=re.DOTALL)
    
    # Clean up any relationships in JobRole model that reference deleted models
    content = re.sub(
        r'work_schedules = relationship\("WorkSchedule".*?\)',
        '# work_schedules relationship removed - WorkSchedule model deleted',
        content
    )
    
    # Clean up any other relationships that might reference deleted models
    content = re.sub(
        r'employees = relationship\("Employee".*?work_schedules.*?\)',
        'employees = relationship("Employee", back_populates="job_role")',
        content
    )
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("✅ Removed unused models from models.py")

if __name__ == "__main__":
    remove_unused_models()