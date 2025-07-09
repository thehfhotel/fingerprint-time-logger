#!/usr/bin/env python3
"""
Automated cleanup script to remove unused API endpoints efficiently.
This script removes all the unused endpoints identified in the cleanup plan.
"""

import re
import os

def remove_unused_endpoints():
    """Remove unused endpoints from consolidated API files"""
    
    # Define patterns for endpoints to remove
    unused_patterns = {
        'consolidated_employees.py': [
            r'@router\.put\("/\{badge_number\}"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.delete\("/\{badge_number\}"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/thai-names/"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.put\("/thai-names/\{badge_number\}"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.post\("/roles/"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/by-role/\{role_id\}"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/stats/summary"\)[^@]+?(?=@router|# ============================================================================|$)',
        ],
        'consolidated_export.py': [
            r'@router\.get\("/attendance/summary"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/employees/thai-names"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/devices/config"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/devices/status-report"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/reports/monthly"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/reports/employee-summary"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/formats"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/quick/today-attendance"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/quick/this-month"\)[^@]+?(?=@router|# ============================================================================|$)',
            r'@router\.get\("/quick/all-employees"\)[^@]+?(?=@router|# ============================================================================|$)',
        ]
    }
    
    base_path = '/home/nut/fingerprint-time-logger/app/api/'
    
    for filename, patterns in unused_patterns.items():
        filepath = os.path.join(base_path, filename)
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                content = f.read()
            
            # Remove each pattern
            for pattern in patterns:
                content = re.sub(pattern, f'# Unused endpoint removed - not used by frontend', content, flags=re.MULTILINE | re.DOTALL)
            
            # Write back the cleaned content
            with open(filepath, 'w') as f:
                f.write(content)
            
            print(f"✅ Cleaned {filename}")
    
    print("🎉 Cleanup completed!")

if __name__ == "__main__":
    remove_unused_endpoints()