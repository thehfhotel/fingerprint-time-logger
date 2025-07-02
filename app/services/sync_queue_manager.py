"""
Stub for removed sync queue manager - minimal implementation
"""

from enum import Enum

class SyncOperationType(Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"

class SyncQueueManager:
    """Minimal sync queue manager stub"""
    
    def __init__(self):
        self._queue = []
    
    def add_operation(self, operation_type, table_name, record_id, payload=None):
        pass  # No-op for simplified system
    
    def process_queue(self):
        return {"processed": 0, "failed": 0}
    
    def get_queue_status(self):
        return {"pending": 0, "processing": 0, "failed": 0}
    
    def clear_queue(self):
        pass