"""
Stub for removed attendance calendar service - minimal implementation
"""

class AttendanceCalendarService:
    """Minimal attendance calendar service stub"""
    
    def __init__(self):
        pass
    
    def get_calendar_data(self, year, month):
        return {
            "year": year,
            "month": month,
            "employees": [],
            "holidays": [],
            "weekends": []
        }
    
    def get_calendar_config(self):
        return {
            "violation_threshold_minutes": 15,
            "status_colors": {
                "perfect": "#22c55e",
                "minor_issue": "#eab308",
                "violation": "#ef4444",
                "absent": "#9ca3af",
                "non_working": "#3b82f6"
            }
        }