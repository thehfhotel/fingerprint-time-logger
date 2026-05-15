"""
Comprehensive tests for cache busting utility module
Tests cache management, file hashing, and URL versioning functionality

NOTE: most of this file probes internal attributes (`_cache`,
`_cache_clear`, etc.) that no longer exist on CacheBustingManager — the
module was simplified to use the git-hash-stamped URL pattern you can
see in static/*.html, so the in-memory cache layer was removed. The
public-surface tests (versioned_url output format, startup_time format)
still pass; the internal-attribute tests are skipped at fixture level
to keep CI honest about what coverage we actually have. Rewriting the
remaining tests against the new internals is parked as a follow-up.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, Mock
import hashlib
import time

from app.utils.cache_busting import CacheBustingManager, cache_manager


def _has_attr(*names):
    """Skip helper — true only if the manager exposes all named attrs."""
    mgr = CacheBustingManager()
    return all(hasattr(mgr, n) for n in names)


_HAS_CACHE_INTERNALS = _has_attr("_cache")


class TestCacheBustingManager:
    """Test CacheBustingManager class functionality"""

    def test_manager_initialization(self):
        """Test manager initialization with default and custom paths.

        The in-memory ``_cache`` dict was removed when this module was
        simplified to use a single startup-time stamp (see
        app/utils/cache_busting.py:20) — check the public surface only.
        """
        manager = CacheBustingManager()
        assert manager.static_dir == Path("static")
        assert manager._startup_time is not None
        assert isinstance(manager._startup_time, str)

        custom_manager = CacheBustingManager("custom/static")
        assert custom_manager.static_dir == Path("custom/static")

    def test_initialization_startup_time_format(self):
        """Test startup time is valid timestamp format"""
        manager = CacheBustingManager()
        startup_time = int(manager._startup_time)
        # Should be a valid Unix timestamp (reasonable range)
        assert startup_time > 1000000000  # After 2001
        assert startup_time < 3000000000  # Before 2065

    @pytest.mark.skipif(
        not _HAS_CACHE_INTERNALS,
        reason="In-memory _cache dict was removed in the cache_busting simplification."
    )
    def test_cache_initialization_empty(self):
        manager = CacheBustingManager()
        assert manager._cache == {}


class TestFileHashing:
    """Test file hashing functionality"""

    def test_get_file_hash_existing_file(self):
        """Test hash generation for existing files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Create test file
            test_file = Path(temp_dir) / "test.css"
            test_file.write_text("body { color: red; }")

            # Get hash
            file_hash = manager.get_file_hash("test.css")

            assert file_hash is not None
            assert isinstance(file_hash, str)
            assert len(file_hash) == 8  # MD5 hash truncated to 8 chars

            # Hash should be consistent for same file
            second_hash = manager.get_file_hash("test.css")
            assert file_hash == second_hash

    def test_get_file_hash_nonexistent_file(self):
        """Test hash generation for non-existent files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Try to get hash for non-existent file
            file_hash = manager.get_file_hash("nonexistent.css")
            assert file_hash is None

    def test_file_hash_changes_with_modification(self):
        """Test hash changes when file is modified"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Create and get initial hash
            test_file = Path(temp_dir) / "test.css"
            test_file.write_text("body { color: red; }")
            initial_hash = manager.get_file_hash("test.css")

            # Modify file (need to wait to ensure different mtime)
            time.sleep(0.1)
            test_file.write_text("body { color: blue; }")

            # Hash should change
            new_hash = manager.get_file_hash("test.css")
            assert new_hash != initial_hash

    def test_file_hash_based_on_mtime_and_size(self):
        """Test hash is based on modification time and size"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            test_file = Path(temp_dir) / "test.css"
            test_file.write_text("test content")

            # Mock file stats
            with patch.object(Path, 'stat') as mock_stat:
                mock_stat.return_value = Mock(st_mtime=1234567890, st_size=100)

                file_hash = manager.get_file_hash("test.css")
                expected_content = "1234567890:100"
                expected_hash = hashlib.md5(expected_content.encode()).hexdigest()[:8]
                assert file_hash == expected_hash

    def test_file_hash_exception_fallback(self):
        """Test fallback to startup time when file operations fail"""
        manager = CacheBustingManager()

        # Mock Path.stat to raise exception
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'stat', side_effect=PermissionError("Access denied")):

            file_hash = manager.get_file_hash("test.css")
            assert file_hash == manager._startup_time


class TestVersionedUrls:
    """Test versioned URL generation"""

    def test_get_versioned_url_existing_file(self):
        """Test versioned URL generation for existing files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Create test file
            test_file = Path(temp_dir) / "style.css"
            test_file.write_text("body { font-size: 16px; }")

            versioned_url = manager.get_versioned_url("style.css")

            assert versioned_url.startswith("style.css?v=")
            assert "&t=" in versioned_url
            assert versioned_url.endswith(manager._startup_time)

    def test_get_versioned_url_nonexistent_file(self):
        """Test versioned URL for non-existent files uses timestamp only"""
        manager = CacheBustingManager()

        versioned_url = manager.get_versioned_url("missing.css")

        assert versioned_url == f"missing.css?t={manager._startup_time}"
        assert "?v=" not in versioned_url

    @pytest.mark.skipif(
        not _HAS_CACHE_INTERNALS,
        reason="In-memory _cache dict removed in simplification."
    )
    def test_versioned_url_caching(self):
        """Test that versioned URLs are cached"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            test_file = Path(temp_dir) / "cached.css"
            test_file.write_text("body { margin: 0; }")

            url1 = manager.get_versioned_url("cached.css")
            assert "cached.css" in manager._cache

            url2 = manager.get_versioned_url("cached.css")
            assert url1 == url2
            assert manager._cache["cached.css"] == url1

    def test_versioned_url_format_with_hash(self):
        """Test versioned URL format includes both hash and timestamp"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            test_file = Path(temp_dir) / "format.css"
            test_file.write_text("body { padding: 10px; }")

            versioned_url = manager.get_versioned_url("format.css")

            # Should have format: filename?v=hash&t=timestamp
            assert "format.css?v=" in versioned_url
            assert "&t=" in versioned_url

            # Extract and verify parts
            parts = versioned_url.split("?v=")[1].split("&t=")
            hash_part = parts[0]
            timestamp_part = parts[1]

            assert len(hash_part) == 8
            assert timestamp_part == manager._startup_time

    def test_versioned_url_format_without_hash(self):
        """Test versioned URL format for non-existent files"""
        manager = CacheBustingManager()

        versioned_url = manager.get_versioned_url("missing.css")

        # Should have format: filename?t=timestamp
        assert versioned_url == f"missing.css?t={manager._startup_time}"
        assert "?v=" not in versioned_url


@pytest.mark.skipif(
    not _HAS_CACHE_INTERNALS,
    reason="In-memory _cache dict removed; see module-level NOTE."
)
class TestCacheManagement:
    """Test cache management functionality"""

    def test_clear_cache(self):
        """Test cache clearing functionality"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Create test files and populate cache
            test_file1 = Path(temp_dir) / "test1.css"
            test_file2 = Path(temp_dir) / "test2.js"
            test_file1.write_text("css content")
            test_file2.write_text("js content")

            # Generate URLs to populate cache
            manager.get_versioned_url("test1.css")
            manager.get_versioned_url("test2.js")

            assert len(manager._cache) == 2

            # Clear cache
            manager.clear_cache()
            assert len(manager._cache) == 0

    def test_cache_persistence_across_calls(self):
        """Test cache persists across multiple calls"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            test_file = Path(temp_dir) / "persistent.css"
            test_file.write_text("test content")

            # Make multiple calls
            url1 = manager.get_versioned_url("persistent.css")
            url2 = manager.get_versioned_url("persistent.css")
            url3 = manager.get_versioned_url("persistent.css")

            # All should be identical
            assert url1 == url2 == url3
            assert len(manager._cache) == 1

    def test_cache_separate_entries_different_files(self):
        """Test cache maintains separate entries for different files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Create multiple test files
            files = ["style1.css", "style2.css", "script.js"]
            for filename in files:
                test_file = Path(temp_dir) / filename
                test_file.write_text(f"content for {filename}")

            # Generate URLs
            urls = {}
            for filename in files:
                urls[filename] = manager.get_versioned_url(filename)

            # Should have separate cache entries
            assert len(manager._cache) == 3
            for filename in files:
                assert filename in manager._cache
                assert manager._cache[filename] == urls[filename]


class TestGlobalCacheManager:
    """Test global cache manager instance"""

    def test_global_manager_exists(self):
        """Test global cache manager is available"""
        from app.utils.cache_busting import cache_manager

        assert cache_manager is not None
        assert isinstance(cache_manager, CacheBustingManager)

    def test_global_manager_default_static_dir(self):
        """Test global manager uses default static directory"""
        assert cache_manager.static_dir == Path("static")

    def test_global_manager_functionality(self):
        """Test global manager has working functionality"""
        versioned_url = cache_manager.get_versioned_url("nonexistent.css")
        assert isinstance(versioned_url, str)

        # The _cache/clear_cache surface was removed in the simplification;
        # gate behind feature detection so legacy and current both pass.
        if hasattr(cache_manager, "clear_cache") and hasattr(cache_manager, "_cache"):
            cache_manager.clear_cache()
            assert len(cache_manager._cache) == 0


class TestEdgeCases:
    """Test edge cases and error conditions"""

    def test_empty_file_path(self):
        """Test handling of empty file paths"""
        manager = CacheBustingManager()

        # Empty string - may still get hash if "static" dir exists
        versioned_url = manager.get_versioned_url("")
        # Should at least have timestamp parameter
        assert f"t={manager._startup_time}" in versioned_url

    def test_relative_paths(self):
        """Test handling of relative paths with subdirectories"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Create subdirectory and file
            sub_dir = Path(temp_dir) / "css"
            sub_dir.mkdir()
            test_file = sub_dir / "style.css"
            test_file.write_text("nested css content")

            versioned_url = manager.get_versioned_url("css/style.css")
            assert "css/style.css?v=" in versioned_url

    def test_special_characters_in_filename(self):
        """Test handling of special characters in filenames"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Create file with spaces and special chars (where filesystem allows)
            test_file = Path(temp_dir) / "my-style_v1.2.css"
            test_file.write_text("special filename content")

            versioned_url = manager.get_versioned_url("my-style_v1.2.css")
            assert "my-style_v1.2.css?v=" in versioned_url

    def test_very_large_file(self):
        """Test hash generation for large files (tests performance)"""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = CacheBustingManager(temp_dir)

            # Create larger file
            test_file = Path(temp_dir) / "large.css"
            content = "body { margin: 0; }\n" * 1000  # 1000 lines
            test_file.write_text(content)

            file_hash = manager.get_file_hash("large.css")
            assert file_hash is not None
            assert len(file_hash) == 8