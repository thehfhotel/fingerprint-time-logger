"""
Unit tests for the estate manager directory (app/services/manager_directory.py).

The admin allowlist is no longer six emails hardcoded in source: it tracks the
HF Portal's live "HF Managers" tier via GET /portal-api/directory/managers, with
the old in-code list kept as the floor. These tests pin the resolution layering,
the fail-closed behaviour of every failure mode, and the properties that make
the guard hot path safe (no network I/O, no partial reads).

No test here touches the network: ``manager_directory._http_get`` is the single
seam for the one HTTP call in the module, and the autouse fixture replaces it
with a raiser so a test that forgets to install a fake fails loudly instead of
dialing out.
"""
import threading
import time

import pytest

from app.services import cf_access_service, manager_directory

PROTECTED = manager_directory.PROTECTED_ADMIN  # admin-1@example.invalid
OTHER_MANAGER = "admin-3@example.invalid"          # in the in-code floor
NEW_MANAGER = "newly.promoted@thehfhotel.org"  # only ever in the live directory
OUTSIDER = "admin-7@example.invalid"   # employee-tier shared mailbox


class _FakeResponse:
    """Minimal stand-in for requests.Response — status_code + json()."""

    def __init__(self, status_code=200, payload=None, json_raises=None):
        self.status_code = status_code
        self._payload = payload
        self._json_raises = json_raises

    def json(self):
        if self._json_raises is not None:
            raise self._json_raises
        return self._payload


def _directory_returning(*emails, status_code=200, key="managers"):
    """A fake _http_get that answers with a directory payload and records calls."""
    calls = []

    def fake_get(url, headers, timeout):
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return _FakeResponse(status_code=status_code, payload={key: list(emails)})

    fake_get.calls = calls
    return fake_get


def _raising(exc):
    def fake_get(url, headers, timeout):
        raise exc

    return fake_get


@pytest.fixture(autouse=True)
def isolated_directory(monkeypatch):
    """
    Every test starts with no snapshot, no refresher thread, a clean env, and
    the network seam wired to explode.
    """
    manager_directory.reset_for_tests()
    monkeypatch.delenv("CF_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("PORTAL_DIRECTORY_TOKEN", raising=False)
    monkeypatch.delenv("PORTAL_DIRECTORY_URL", raising=False)

    def _no_network(*args, **kwargs):
        raise AssertionError("test attempted real network I/O")

    monkeypatch.setattr(manager_directory, "_http_get", _no_network)
    yield
    manager_directory.reset_for_tests()


@pytest.fixture
def token_set(monkeypatch):
    monkeypatch.setenv("PORTAL_DIRECTORY_TOKEN", "test-directory-token")


# ── 1. layering ───────────────────────────────────────────────────────────────
class TestLayering:
    """Directory 200 wins; failures keep last-known-good; never-fetched uses the floor."""

    def test_live_directory_replaces_the_floor(self, monkeypatch, token_set):
        monkeypatch.setattr(
            manager_directory, "_http_get", _directory_returning(PROTECTED, NEW_MANAGER)
        )

        assert manager_directory._refresh_once() is True

        # Promoted by the portal, never in the in-code list — now an admin.
        assert manager_directory.is_admin_email(NEW_MANAGER) is True
        # In the in-code floor but dropped from the live tier — no longer an admin.
        assert manager_directory.is_admin_email(OTHER_MANAGER) is False

    def test_failed_refresh_keeps_last_known_good(self, monkeypatch, token_set):
        monkeypatch.setattr(
            manager_directory, "_http_get", _directory_returning(PROTECTED, NEW_MANAGER)
        )
        assert manager_directory._refresh_once() is True

        for failure in (
            _directory_returning(status_code=503),
            _directory_returning(status_code=401),
            _raising(TimeoutError("read timed out")),
            _raising(OSError("connection refused")),
        ):
            monkeypatch.setattr(manager_directory, "_http_get", failure)
            assert manager_directory._refresh_once() is False
            assert manager_directory.is_admin_email(NEW_MANAGER) is True
            assert manager_directory.is_admin_email(OTHER_MANAGER) is False

    def test_malformed_body_keeps_last_known_good(self, monkeypatch, token_set):
        monkeypatch.setattr(
            manager_directory, "_http_get", _directory_returning(PROTECTED, NEW_MANAGER)
        )
        assert manager_directory._refresh_once() is True

        def not_json(url, headers, timeout):
            return _FakeResponse(status_code=200, json_raises=ValueError("not json"))

        monkeypatch.setattr(manager_directory, "_http_get", not_json)
        assert manager_directory._refresh_once() is False
        assert manager_directory.is_admin_email(NEW_MANAGER) is True

        # 200 whose body has no managers list at all.
        monkeypatch.setattr(
            manager_directory, "_http_get", _directory_returning(PROTECTED, key="admins")
        )
        assert manager_directory._refresh_once() is False
        assert manager_directory.is_admin_email(NEW_MANAGER) is True

    def test_never_fetched_falls_back_to_cf_admin_emails(self, monkeypatch):
        monkeypatch.setenv("CF_ADMIN_EMAILS", f"{OUTSIDER},{NEW_MANAGER}")

        assert manager_directory.live_snapshot() is None
        assert manager_directory.is_admin_email(OUTSIDER) is True
        assert manager_directory.is_admin_email(NEW_MANAGER) is True
        assert manager_directory.is_admin_email(OTHER_MANAGER) is False

    def test_never_fetched_and_no_env_falls_back_to_static_floor(self):
        assert manager_directory.live_snapshot() is None
        for email in manager_directory.STATIC_ADMIN_EMAILS:
            assert manager_directory.is_admin_email(email) is True
        assert manager_directory.is_admin_email(OUTSIDER) is False
        assert manager_directory.is_admin_email(NEW_MANAGER) is False

    def test_live_snapshot_outranks_cf_admin_emails(self, monkeypatch, token_set):
        """CF_ADMIN_EMAILS is the FLOOR — a live directory answer supersedes it."""
        monkeypatch.setenv("CF_ADMIN_EMAILS", OUTSIDER)
        monkeypatch.setattr(
            manager_directory, "_http_get", _directory_returning(PROTECTED, NEW_MANAGER)
        )
        assert manager_directory._refresh_once() is True

        assert manager_directory.is_admin_email(NEW_MANAGER) is True
        assert manager_directory.is_admin_email(OUTSIDER) is False

    def test_request_carries_bearer_token_url_and_short_timeout(self, monkeypatch, token_set):
        fake = _directory_returning(PROTECTED)
        monkeypatch.setattr(manager_directory, "_http_get", fake)

        manager_directory._refresh_once()

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["url"] == manager_directory.DEFAULT_DIRECTORY_URL
        assert call["headers"]["Authorization"] == "Bearer test-directory-token"
        assert call["timeout"] == manager_directory.DIRECTORY_TIMEOUT_SECONDS
        assert call["timeout"] <= 2.0

    def test_portal_directory_url_env_overrides_the_default(self, monkeypatch, token_set):
        monkeypatch.setenv("PORTAL_DIRECTORY_URL", "http://localhost:9999/portal-api/directory/managers")
        fake = _directory_returning(PROTECTED)
        monkeypatch.setattr(manager_directory, "_http_get", fake)

        manager_directory._refresh_once()

        assert fake.calls[0]["url"] == "http://localhost:9999/portal-api/directory/managers"


# ── 2. the protected owner is admitted in every state ─────────────────────────
class TestProtectedOwnerBreakGlass:
    """
    PROTECTED_ADMIN is the break-glass path back in. A directory that omits him
    — a bad membership edit, a portal regression, a half-applied tier change —
    must never lock the owner out of the console that repairs it. Mirrors the
    portal's own PROTECTED_MANAGER convention.
    """

    def test_admitted_when_every_layer_is_dark(self):
        assert manager_directory.live_snapshot() is None
        assert manager_directory.directory_enabled() is False
        assert manager_directory.is_admin_email(PROTECTED) is True

    def test_admitted_when_directory_response_omits_him(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(NEW_MANAGER))
        assert manager_directory._refresh_once() is True

        assert PROTECTED not in manager_directory.live_snapshot()
        assert manager_directory.is_admin_email(PROTECTED) is True

    def test_admitted_when_directory_is_unreachable(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _raising(OSError("connection refused")))
        manager_directory._refresh_once()

        assert manager_directory.is_admin_email(PROTECTED) is True

    def test_admitted_when_directory_401s_or_503s(self, monkeypatch, token_set):
        for status in (401, 503, 500):
            monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(status_code=status))
            manager_directory._refresh_once()
            assert manager_directory.is_admin_email(PROTECTED) is True

    def test_admitted_when_directory_returns_an_empty_list(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning())
        manager_directory._refresh_once()

        assert manager_directory.is_admin_email(PROTECTED) is True

    def test_admitted_through_the_cf_access_service_delegate(self):
        """The guard callers use goes through the same floor."""
        assert cf_access_service._is_allowlisted_admin_email(PROTECTED) is True

    def test_explicit_cf_admin_emails_stays_the_operator_manual_control(self, monkeypatch):
        """
        DELIBERATE CARVE-OUT, unchanged from pre-directory behaviour: an
        explicit CF_ADMIN_EMAILS replaces the floor wholesale, protected owner
        included. That knob is a local act by someone already on the host (it
        is not even plumbed through docker-compose), not a state a remote
        directory edit or a portal regression can put this app into — so it is
        not a lockout path this break-glass needs to defend against, and
        tests/unit/test_cf_access_service.py pins exactly this contract.
        """
        monkeypatch.setenv("CF_ADMIN_EMAILS", OUTSIDER)

        assert manager_directory.is_admin_email(PROTECTED) is False
        assert manager_directory.is_admin_email(OUTSIDER) is True

    def test_but_the_live_directory_still_protects_him_over_that_override(self, monkeypatch, token_set):
        monkeypatch.setenv("CF_ADMIN_EMAILS", OUTSIDER)
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(NEW_MANAGER))
        assert manager_directory._refresh_once() is True

        assert manager_directory.is_admin_email(PROTECTED) is True


# ── 3. dormancy ───────────────────────────────────────────────────────────────
class TestDormancy:
    """Empty env = feature off. Behaviour must be identical to pre-directory."""

    def test_no_token_means_zero_network_calls(self):
        # The autouse fixture wires _http_get to raise, so any call would fail
        # the test. This exercises the hot path many times over.
        for email in (PROTECTED, OTHER_MANAGER, OUTSIDER, NEW_MANAGER):
            manager_directory.is_admin_email(email)

        assert manager_directory.directory_enabled() is False
        assert manager_directory.live_snapshot() is None

    def test_no_token_means_no_refresher_thread(self):
        manager_directory.is_admin_email(PROTECTED)

        running = [t.name for t in threading.enumerate()]
        assert "manager-directory-refresh" not in running

    def test_refresh_once_is_a_no_op_without_a_token(self):
        assert manager_directory._refresh_once() is False
        assert manager_directory.live_snapshot() is None

    def test_dormant_verdicts_match_the_pre_directory_allowlist(self):
        """The exact allowlist the app shipped with, unchanged."""
        legacy_allowlist = {
            "admin-2@example.invalid",
            "admin-1@example.invalid",
            "admin-3@example.invalid",
            "admin-4@example.invalid",
            "admin-5@example.invalid",
            "admin-6@example.invalid",
        }
        assert set(manager_directory.STATIC_ADMIN_EMAILS) == legacy_allowlist

        for email in legacy_allowlist:
            assert manager_directory.is_admin_email(email) is True
            assert cf_access_service._is_allowlisted_admin_email(email) is True
        for email in (OUTSIDER, NEW_MANAGER, "attacker@example.com", ""):
            assert manager_directory.is_admin_email(email) is False
            assert cf_access_service._is_allowlisted_admin_email(email) is False


# ── 4. an empty 200 is ignored ────────────────────────────────────────────────
class TestEmptyDirectoryResponseIsIgnored:
    """
    The portal 503s rather than serving an empty list, so a 200 with zero
    managers can only be a regression there. Accepting it would revoke every
    manager at once — defence in depth against exactly that.
    """

    def test_empty_list_does_not_replace_a_live_snapshot(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(PROTECTED, NEW_MANAGER))
        assert manager_directory._refresh_once() is True

        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning())
        assert manager_directory._refresh_once() is False

        assert manager_directory.live_snapshot() == frozenset({PROTECTED, NEW_MANAGER})
        assert manager_directory.is_admin_email(NEW_MANAGER) is True

    def test_empty_list_does_not_create_a_snapshot_from_the_floor_state(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning())

        assert manager_directory._refresh_once() is False
        assert manager_directory.live_snapshot() is None
        # Still the floor, so every in-code manager keeps working.
        assert manager_directory.is_admin_email(OTHER_MANAGER) is True

    def test_list_of_only_blanks_is_treated_as_empty(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning("", "   ", None))

        assert manager_directory._refresh_once() is False
        assert manager_directory.live_snapshot() is None
        assert manager_directory.is_admin_email(OTHER_MANAGER) is True


# ── 5. case-insensitivity and whitespace ──────────────────────────────────────
class TestNormalization:
    def test_lookup_is_case_insensitive_and_trims_whitespace(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(NEW_MANAGER))
        manager_directory._refresh_once()

        assert manager_directory.is_admin_email(NEW_MANAGER.upper()) is True
        assert manager_directory.is_admin_email(f"  {NEW_MANAGER}  ") is True
        assert manager_directory.is_admin_email(f"\t{NEW_MANAGER.title()}\n") is True

    def test_directory_entries_are_normalized_on_ingest(self, monkeypatch, token_set):
        monkeypatch.setattr(
            manager_directory, "_http_get", _directory_returning("  NEWLY.Promoted@THEHFHOTEL.org  ")
        )
        manager_directory._refresh_once()

        assert manager_directory.live_snapshot() == frozenset({NEW_MANAGER})
        assert manager_directory.is_admin_email(NEW_MANAGER) is True

    def test_floor_entries_are_normalized(self, monkeypatch):
        monkeypatch.setenv("CF_ADMIN_EMAILS", f"  {NEW_MANAGER.upper()} , , {OUTSIDER}  ")

        assert manager_directory.is_admin_email(NEW_MANAGER) is True
        assert manager_directory.is_admin_email(OUTSIDER) is True
        assert manager_directory.is_admin_email("") is False

    def test_protected_owner_matches_case_insensitively(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(NEW_MANAGER))
        manager_directory._refresh_once()

        assert manager_directory.is_admin_email("admin-9@example.invalid") is True
        assert manager_directory.is_admin_email(f" {PROTECTED} ") is True

    def test_non_string_and_empty_input_is_rejected_not_crashed(self):
        for bad in (None, "", "   ", 42, object()):
            assert manager_directory.is_admin_email(bad) is False


# ── 6. atomic swap ────────────────────────────────────────────────────────────
class TestAtomicSwap:
    """
    The hot path reads a module-level frozenset with no lock. A refresh must
    therefore swap in a whole new immutable set, never mutate in place — a
    reader mid-refresh sees either the old set or the new one, never a partial
    or half-built one (which would silently drop admins for a few microseconds).
    """

    def test_reader_never_observes_a_partial_set(self, monkeypatch, token_set):
        set_a = frozenset({PROTECTED, OTHER_MANAGER} | {f"a{i}@example.com" for i in range(200)})
        set_b = frozenset({PROTECTED, NEW_MANAGER} | {f"b{i}@example.com" for i in range(200)})
        payloads = [sorted(set_a), sorted(set_b)]
        stop = threading.Event()
        observed = []
        errors = []

        def flipping_get(url, headers, timeout):
            # Alternate between two disjoint-ish complete lists as fast as
            # the reader can look.
            payloads.append(payloads.pop(0))
            return _FakeResponse(status_code=200, payload={"managers": payloads[0]})

        monkeypatch.setattr(manager_directory, "_http_get", flipping_get)

        def refresher():
            try:
                while not stop.is_set():
                    manager_directory._refresh_once()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        thread = threading.Thread(target=refresher, name="test-refresher", daemon=True)
        thread.start()
        try:
            deadline = time.time() + 0.5
            while time.time() < deadline:
                snapshot = manager_directory.live_snapshot()
                observed.append(snapshot)
                # The owner is admitted at every single instant of the swap.
                assert manager_directory.is_admin_email(PROTECTED) is True
        finally:
            stop.set()
            thread.join(timeout=5.0)

        assert not errors
        assert len(observed) > 100, "reader did not sample often enough to be meaningful"
        # Every sample is a COMPLETE set: None (pre-first-refresh), or exactly
        # one of the two published lists. Never a subset of either.
        for snapshot in observed:
            assert snapshot in (None, set_a, set_b)
        # And the refresher really did flip it (otherwise this proves nothing).
        assert set_a in observed and set_b in observed

    def test_swap_replaces_rather_than_mutates(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(PROTECTED, OTHER_MANAGER))
        manager_directory._refresh_once()
        first = manager_directory.live_snapshot()

        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(PROTECTED, NEW_MANAGER))
        manager_directory._refresh_once()
        second = manager_directory.live_snapshot()

        assert isinstance(first, frozenset) and isinstance(second, frozenset)
        assert first is not second
        # The set a reader was holding is unchanged by the refresh.
        assert first == frozenset({PROTECTED, OTHER_MANAGER})


# ── logging hygiene ───────────────────────────────────────────────────────────
class TestFailureLoggingIsNotChatty:
    """
    Estate alerting rule: only page on confirmed failures, suppress transient
    blips, pair failures with recovery notices. A portal that is down for an
    hour must not write a warning every 60s.
    """

    def test_repeated_identical_failures_log_once(self, monkeypatch, token_set, caplog):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(status_code=503))

        with caplog.at_level("WARNING", logger=manager_directory.logger.name):
            for _ in range(5):
                manager_directory._refresh_once()

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1

    def test_recovery_is_announced(self, monkeypatch, token_set, caplog):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(status_code=503))
        manager_directory._refresh_once()

        with caplog.at_level("INFO", logger=manager_directory.logger.name):
            monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(PROTECTED, NEW_MANAGER))
            manager_directory._refresh_once()

        assert any("recovered" in r.getMessage() for r in caplog.records)


# ── the refresher thread ──────────────────────────────────────────────────────
class TestBackgroundRefresher:
    def test_first_use_starts_the_refresher_and_the_snapshot_lands(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(PROTECTED, NEW_MANAGER))

        # The very first call must not block on HTTP — it answers from the
        # floor while the refresher works.
        manager_directory.is_admin_email(PROTECTED)

        deadline = time.time() + 5.0
        while manager_directory.live_snapshot() is None and time.time() < deadline:
            time.sleep(0.01)

        assert manager_directory.live_snapshot() == frozenset({PROTECTED, NEW_MANAGER})
        assert manager_directory.is_admin_email(NEW_MANAGER) is True

    def test_refresher_is_a_daemon_thread(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(PROTECTED))

        manager_directory.is_admin_email(PROTECTED)

        threads = [t for t in threading.enumerate() if t.name == "manager-directory-refresh"]
        assert len(threads) == 1
        assert threads[0].daemon is True

    def test_only_one_refresher_is_ever_started(self, monkeypatch, token_set):
        monkeypatch.setattr(manager_directory, "_http_get", _directory_returning(PROTECTED))

        for _ in range(50):
            manager_directory.is_admin_email(PROTECTED)

        threads = [t for t in threading.enumerate() if t.name == "manager-directory-refresh"]
        assert len(threads) == 1
