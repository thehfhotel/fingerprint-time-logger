"""
Cache busting utilities for static files
"""
import os
import hashlib
import time
from pathlib import Path
from typing import Optional


class CacheBustingManager:
    """Manages cache busting for static files.

    The versioned URL is recomputed on every call so that changes to a file
    on disk are reflected immediately. The hash itself is cheap (it reads only
    mtime + size from a stat() call), so there is no need to memoize the URL
    — and memoizing it caused stale URLs after file edits.
    """

    def __init__(self, static_dir: str = "static"):
        self.static_dir = Path(static_dir)
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
        """Get versioned URL for a static file.

        Recomputed on every call — see class docstring for rationale.
        """
        file_hash = self.get_file_hash(file_path)
        if file_hash:
            return f"{file_path}?v={file_hash}&t={self._startup_time}"
        return f"{file_path}?t={self._startup_time}"

    def clear_cache(self):
        """No-op kept for backward compatibility with callers."""
        return None


# Global cache busting manager
cache_manager = CacheBustingManager()