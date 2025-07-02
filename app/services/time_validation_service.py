"""
Stub for removed time validation service - minimal implementation
"""

class TimeValidationService:
    """Minimal time validation service stub"""
    
    def __init__(self):
        pass
    
    def validate_attendance_record(self, record):
        return {"status": "valid", "message": "Basic validation passed"}
    
    def get_validation_config(self):
        return {
            "warning_threshold_minutes": 15,
            "late_threshold_minutes": 30,
            "early_departure_threshold_minutes": 15
        }