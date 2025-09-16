"""
Cache busting utilities for static files
"""
import os
import hashlib
import time
from pathlib import Path
from typing import Dict, Optional


class CacheBustingManager:
    """Manages cache busting for static files"""
    
    def __init__(self, static_dir: str = "static"):
        self.static_dir = Path(static_dir)
        self._cache: Dict[str, str] = {}
        self._startup_time = str(int(time.time()))
    
    def get_file_hash(self, file_path: str) -> Optional[str]:
        """Generate hash for a file for cache busting"""
        full_path = self.static_dir / file_path
        if not full_path.exists():
            return None
        
        # Use file modification time + size for fast cache busting
        try:
            stat = full_path.stat()
            content = f"{stat.st_mtime}:{stat.st_size}"
            return hashlib.md5(content.encode()).hexdigest()[:8]
        except Exception:
            return self._startup_time
    
    def get_versioned_url(self, file_path: str) -> str:
        """Get versioned URL for a static file"""
        if file_path in self._cache:
            return self._cache[file_path]
        
        file_hash = self.get_file_hash(file_path)
        if file_hash:
            versioned_url = f"{file_path}?v={file_hash}&t={self._startup_time}"
        else:
            versioned_url = f"{file_path}?t={self._startup_time}"
        
        self._cache[file_path] = versioned_url
        return versioned_url
    
    def clear_cache(self):
        """Clear the cache to force regeneration"""
        self._cache.clear()


# Global cache busting manager
cache_manager = CacheBustingManager()