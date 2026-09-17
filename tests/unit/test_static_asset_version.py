"""
Tests for app/utils/static_asset_version.py — the per-deploy cache-busting
stamp for /fingerprintlogs/static/** asset URLs (see that module's docstring
for the production bug this fixes: an edge cache in front of the app caches
those URLs for hours, ignoring our no-store header).
"""
import pytest

from app.utils.static_asset_version import asset_version, version_static_urls


@pytest.fixture(autouse=True)
def _clear_asset_version_cache():
    """asset_version() is memoized (lru_cache) — clear it around every test
    so monkeypatched env vars actually take effect, and again afterwards so
    later tests/modules don't inherit a stamp from this file."""
    asset_version.cache_clear()
    yield
    asset_version.cache_clear()


class TestVersionStaticUrls:
    def test_stamps_src_attribute(self):
        html = '<script src="/fingerprintlogs/static/v2/nav.js"></script>'
        out = version_static_urls(html, "abc123")
        assert out == '<script src="/fingerprintlogs/static/v2/nav.js?v=abc123"></script>'

    def test_stamps_href_attribute(self):
        html = '<link rel="stylesheet" href="/fingerprintlogs/static/css/base.css">'
        out = version_static_urls(html, "abc123")
        assert 'href="/fingerprintlogs/static/css/base.css?v=abc123"' in out

    def test_stamps_multiple_urls_independently(self):
        html = (
            '<script src="/fingerprintlogs/static/v2/theme.js"></script>'
            '<script defer src="/fingerprintlogs/static/v2/nav.js"></script>'
        )
        out = version_static_urls(html, "deadbeef1234")
        assert 'src="/fingerprintlogs/static/v2/theme.js?v=deadbeef1234"' in out
        assert 'src="/fingerprintlogs/static/v2/nav.js?v=deadbeef1234"' in out

    def test_leaves_already_versioned_urls_untouched(self):
        html = '<script src="/fingerprintlogs/static/v2/nav.js?v=old123"></script>'
        out = version_static_urls(html, "new456")
        assert out == html

    def test_leaves_relative_static_urls_untouched(self):
        """Legacy dashboard pages build these inside document.write(...)
        template strings, already carrying their own ?v= — never rewritten,
        and never matched even without a query string since they aren't
        under /fingerprintlogs/static/."""
        html = '<script src="static/js/config.js"></script>'
        out = version_static_urls(html, "abc123")
        assert out == html

    def test_leaves_external_urls_untouched(self):
        html = '<script src="https://cdn.tailwindcss.com"></script>'
        out = version_static_urls(html, "abc123")
        assert out == html

    def test_idempotent_second_stamp_is_a_no_op(self):
        html = '<script src="/fingerprintlogs/static/v2/nav.js"></script>'
        once = version_static_urls(html, "abc123")
        twice = version_static_urls(once, "abc123")
        assert once == twice

    def test_second_stamp_with_different_version_does_not_override(self):
        """Once a URL carries a query string (from any stamping pass) it is
        left alone — the version in the URL is whatever the FIRST stamp
        wrote, by design (an already-versioned URL is never re-versioned)."""
        html = '<script src="/fingerprintlogs/static/v2/nav.js"></script>'
        once = version_static_urls(html, "abc123")
        twice = version_static_urls(once, "xyz789")
        assert once == twice
        assert "v=abc123" in twice
        assert "v=xyz789" not in twice


class TestAssetVersion:
    def test_uses_hf_deploy_commit_prefix_when_set(self, monkeypatch):
        monkeypatch.setenv("HF_DEPLOY_COMMIT", "1234567890abcdef1234567890abcdef12345678")
        assert asset_version() == "1234567890ab"

    def test_ignores_non_hex_hf_deploy_commit(self, monkeypatch):
        monkeypatch.setenv("HF_DEPLOY_COMMIT", "not-a-real-sha")
        version = asset_version()
        assert version != "not-a-real-sha"
        assert version  # still produces a usable fallback stamp

    def test_fallback_is_stable_within_a_process(self, monkeypatch):
        monkeypatch.delenv("HF_DEPLOY_COMMIT", raising=False)
        first = asset_version()
        second = asset_version()
        assert first == second

    def test_fallback_used_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("HF_DEPLOY_COMMIT", raising=False)
        version = asset_version()
        assert version
        assert isinstance(version, str)
