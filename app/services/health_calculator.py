"""
Stub for removed health calculator - minimal implementation
"""

class HealthCalculator:
    """Minimal health calculator stub"""
    
    def __init__(self):
        pass
    
    def calculate_health(self, device_id):
        return {"status": "healthy", "score": 100}
    
    def get_health_metrics(self):
        return {"overall_health": 100, "devices_online": 1}