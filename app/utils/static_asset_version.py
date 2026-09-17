"""
Per-deploy version stamp for ``/fingerprintlogs/static/**`` asset URLs.

PROBLEM (verified in production): the app serves those assets with
``Cache-Control: no-store``, but the edge in front of it (nginx/Cloudflare)
ignores that and caches by URL — rewriting the response to
``public, max-age=14400, immutable`` — so after every deploy, v2 pages can
keep running the PREVIOUS nav.js/theme.js/leave-sync-ui.js for up to 4
hours. ``Cache-Control`` at the app layer can't fix that; the fix has to
change the URL itself on every deploy, so each release gets a cache key the
edge has never seen.

``asset_version()`` picks that stamp once per process (memoized — it does
env/hash work that has no reason to repeat on every request) and
``version_static_urls()`` is the pure, regex-based function that stamps it
onto every not-yet-versioned static asset URL in a page's HTML.
"""
import hashlib
import os
import re
import time
from functools import lru_cache

# A commit sha (full 40-char or an abbreviated one CI might pass) — anything
# else (unset, "unknown", a placeholder) falls through to the process-start
# fallback below.
_HEX_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


@lru_cache(maxsize=1)
def asset_version() -> str:
    """The version stamp used for every static asset URL this process serves.

    ``HF_DEPLOY_COMMIT[:12]`` when it is set and looks like a real hex
    commit sha (production CI sets this per deploy — see
    app/api/deployment_ready.py). Otherwise a short fallback derived from
    this process's start time, so even a local/dev run without the env var
    gets a fresh stamp on every restart. Memoized: computed once per
    process, not on every request.
    """
    commit = os.getenv("HF_DEPLOY_COMMIT", "").strip().lower()
    if commit and _HEX_SHA_RE.match(commit):
        return commit[:12]
    fallback_seed = f"{time.time()}:{os.getpid()}"
    # Not a security hash — just a short, process-stable fingerprint for
    # cache-busting. usedforsecurity=False keeps FIPS-mode/Bandit (B324) happy.
    return hashlib.md5(fallback_seed.encode(), usedforsecurity=False).hexdigest()[:12]


# Matches src="/fingerprintlogs/static/…" or href="/fingerprintlogs/static/…"
# attribute values that carry NO query string yet. A URL that already has a
# "?" (already versioned, or otherwise parameterized) is left alone by
# construction — the character class excludes "?". This also means a
# relative "static/…" (or "/static/…") string built inside an inline
# document.write(...) call on the legacy dashboard pages is never touched:
# those are JS template-literal text, not src=""/href="" attribute values,
# and in this codebase they already carry their own "?v=" query string.
_ASSET_ATTR_RE = re.compile(
    r'(?P<attr>\b(?:src|href)=")'
    r'(?P<url>/fingerprintlogs/static/[^"?]*)'
    r'(?P<close>")'
)


def version_static_urls(html: str, version: str) -> str:
    """Append ``?v=<version>`` to every unversioned static asset URL.

    Pure function, deterministic for a given ``(html, version)`` pair —
    regex-based, no I/O. Only ``src="…"``/``href="…"`` attribute values
    that point at ``/fingerprintlogs/static/`` and have no query string yet
    are touched; everything else (already-versioned URLs, relative or
    external URLs, non-attribute text) passes through unchanged, so a
    second stamping pass is a no-op for anything this already touched.
    """
    def _stamp(match: "re.Match[str]") -> str:
        return f"{match.group('attr')}{match.group('url')}?v={version}{match.group('close')}"

    return _ASSET_ATTR_RE.sub(_stamp, html)
