"""
Stub for removed cache service - minimal implementation
"""

class CacheService:
    """Minimal cache service stub"""
    
    def __init__(self):
        self._cache = {}
    
    def get(self, key: str):
        return self._cache.get(key)
    
    def set(self, key: str, value, ttl: int = 300):
        self._cache[key] = value
    
    def delete(self, key: str):
        self._cache.pop(key, None)
    
    def clear(self):
        self._cache.clear()
    
    def get_stats(self):
        return {"entries": len(self._cache)}