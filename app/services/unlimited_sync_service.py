"""
Stub for removed unlimited sync service - minimal implementation
"""

class UnlimitedSyncService:
    """Minimal unlimited sync service stub"""
    
    def __init__(self):
        pass
    
    def start_unlimited_sync(self):
        return {"status": "disabled", "message": "Use simplified sync instead"}
    
    def stop_unlimited_sync(self):
        return {"status": "stopped"}
    
    def get_sync_status(self):
        return {"running": False, "records_synced": 0}

class SyncConfiguration:
    """Minimal sync configuration stub"""
    
    def __init__(self, **kwargs):
        pass

class SyncMetrics:
    """Minimal sync metrics stub"""
    
    def __init__(self):
        pass
    
    def get_metrics(self):
        return {"total_synced": 0, "errors": 0}

class ProcessingStrategy:
    """Minimal processing strategy stub"""
    
    def __init__(self, **kwargs):
        pass

class SyncStrategy:
    """Minimal sync strategy stub"""
    
    def __init__(self, **kwargs):
        pass

# Stub functions
def sync_device_full_historical(device_id, config=None):
    """Stub for full historical sync"""
    return {"status": "disabled", "message": "Use simplified sync instead"}

def sync_device_incremental(device_id, config=None):
    """Stub for incremental sync"""
    return {"status": "disabled", "message": "Use simplified sync instead"}