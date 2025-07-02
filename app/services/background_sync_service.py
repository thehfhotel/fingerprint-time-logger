"""
Stub for removed background sync service - minimal implementation
"""

class SyncWorkerConfig:
    """Stub sync worker config"""
    def __init__(self, **kwargs):
        pass

def get_sync_service():
    """Return stub sync service"""
    return BackgroundSyncService()

class BackgroundSyncService:
    """Minimal background sync service stub"""
    
    def __init__(self):
        pass
    
    def start(self):
        pass
    
    def stop(self):
        pass
    
    def get_status(self):
        return {"running": False, "last_sync": None}
    
    def force_sync(self):
        return {"success": True, "message": "Use simplified device service instead"}