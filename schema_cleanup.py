#!/usr/bin/env python3
"""
Script to remove unused schema classes from schemas.py
"""

import re

def remove_unused_schemas():
    """Remove unused schema classes efficiently"""
    
    filepath = '/home/nut/fingerprint-time-logger/app/schemas/schemas.py'
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Schema classes to remove
    schemas_to_remove = [
        'BulkValidationResponse',
        'LateEmployeeInfo', 
        'LateEmployeeReportResponse',
        'DailyPunctualityStats',
        'PunctualitySummary',
        'PunctualityReportResponse',
        'CalendarFilters',
        'CalendarConfigResponse',
        'HolidayResponse',
        'CalendarStatisticsResponse',
        'EmployeeDayDetailResponse',
        'MonthlyCalendarResponse',
        'TimeCheckConfigBase',
        'TimeCheckConfigCreate',
        'TimeCheckConfigUpdate',
        'TimeCheckConfigResponse',
        'EmployeeScheduleInfo',
        'JobRoleWithSchedule',
        'EmployeeRoleAssignmentResponse',
        'BulkRoleAssignmentRequest',
    ]
    
    # Remove each schema class
    for schema_name in schemas_to_remove:
        # Pattern to match entire class definition
        pattern = rf'class {schema_name}.*?(?=\n\n(?:class|\# |$)|\Z)'
        replacement = f'# {schema_name} schema removed - not used by application'
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # Remove enum classes that are no longer needed
    enum_classes = ['AttendanceStatusEnum', 'HolidayTypeEnum']
    for enum_name in enum_classes:
        pattern = rf'class {enum_name}.*?(?=\n\n(?:class|\# |$)|\Z)'
        content = re.sub(pattern, f'# {enum_name} enum removed - not used by application', content, flags=re.DOTALL)
    
    # Clean up any orphaned imports or references
    # Remove sync-related schemas that are no longer needed
    sync_schemas = ['SyncLogBase', 'SyncLog', 'SyncRequest', 'SyncResponse']
    for schema_name in sync_schemas:
        pattern = rf'class {schema_name}.*?(?=\n\n(?:class|\# |$)|\Z)'
        content = re.sub(pattern, f'# {schema_name} schema removed - not used by application', content, flags=re.DOTALL)
    
    with open(filepath, 'w') as f:
        f.write(content)
    
    print("✅ Removed unused schema classes from schemas.py")

if __name__ == "__main__":
    remove_unused_schemas()