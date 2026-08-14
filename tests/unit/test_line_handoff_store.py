"""Unit tests for the same-browser hand-off ticket store.

The store (app/services/line_handoff_store.py) is what holds the invariant the
whole hand-off exists for:

    completing a LINE login must only ever yield a session to the browser that
    STARTED that specific flow.

These tests exercise that at the store level — cookie binding, single use,
expiry, the fixation IP check, the two-poller race and the capacity ceilings.
The end-to-end proof through the real endpoints lives in
tests/integration/test_line_handoff_flow.py.
"""
import time

import pytest

from app.services import line_handoff_store as store


IP = "203.0.113.10"


@pytest.fixture(autouse=True)
def _reset_store():
    store.reset_state()
    yield
    store.reset_state()


@pytest.fixture
def handoff_enabled(monkeypatch):
    """Turn the feature on with instant TTLs so nothing waits on a clock."""
    monkeypatch.setenv("LINE_SAME_BROWSER_HANDOFF", "true")
    monkeypatch.setenv("LINE_HANDOFF_WAIT_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("LINE_HANDOFF_WAIT_TICK_SECONDS", "0.02")
    yield


def _new(inner_hint="oidc:inner-ticket", client_ip=IP):
    ticket = store.create_ticket(inner_hint=inner_hint, client_ip=client_ip)
    assert ticket is not None
    return ticket


def _resolve(ticket_id, *, client_ip=IP, line_user_id="Uline0001"):
    return store.resolve_ticket(
        ticket_id,
        line_user_id=line_user_id,
        display_name="LINE Name",
        picture_url="",
        client_ip=client_ip,
    )


# ============================================================================
# Feature gate
# ============================================================================

class TestFeatureGate:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("LINE_SAME_BROWSER_HANDOFF", raising=False)
        assert store.is_enabled() is False

    def test_only_explicit_truthy_values_enable_it(self, monkeypatch):
        for value in ("true", "TRUE", "1", "yes"):
            monkeypatch.setenv("LINE_SAME_BROWSER_HANDOFF", value)
            assert store.is_enabled() is True, value
        for value in ("false", "0", "no", "", "maybe"):
            monkeypatch.setenv("LINE_SAME_BROWSER_HANDOFF", value)
            assert store.is_enabled() is False, value


# ============================================================================
# Happy path + cookie shape
# ============================================================================

class TestHappyPath:
    def test_resolve_then_claim_returns_the_parked_identity(self, handoff_enabled):
        ticket = _new()
        assert _resolve(ticket.ticket_id) == store.RESOLVE_OK

        claimed = store.take_resolved(ticket.cookie_value)
        assert claimed is not None
        assert claimed["line_user_id"] == "Uline0001"
        assert claimed["inner_hint"] == "oidc:inner-ticket"

    def test_pending_ticket_is_not_claimable(self, handoff_enabled):
        ticket = _new()
        assert store.peek(ticket.cookie_value) == "pending"
        assert store.take_resolved(ticket.cookie_value) is None
        # Still there — the long-poll keeps watching it.
        assert store.peek(ticket.cookie_value) == "pending"

    def test_cookie_carries_both_halves_and_the_id_is_not_the_secret(
        self, handoff_enabled
    ):
        ticket = _new()
        assert ticket.cookie_value.startswith(f"{ticket.ticket_id}.")
        holder_secret = ticket.cookie_value[len(ticket.ticket_id) + 1:]
        assert holder_secret
        assert holder_secret != ticket.ticket_id
        # Both halves are long enough that guessing is not the attack surface.
        assert len(ticket.ticket_id) >= 24
        assert len(holder_secret) >= 32

    def test_tickets_are_unique(self, handoff_enabled):
        ids = {_new().ticket_id for _ in range(50)}
        assert len(ids) == 50


# ============================================================================
# THE LOAD-BEARING ONE — knowing the ticket id buys nothing
# ============================================================================

class TestTicketIdAloneIsUseless:
    """Threat 1 (observe) and threat 2 (guess), at the store level.

    The ticket id is the half of the secret that travels the LINE round trip.
    An attacker who shoulder-surfs it, finds it in a log, or simply guesses one
    must gain NOTHING, because releasing the session needs the holder secret
    that never left the originating browser's HttpOnly cookie jar.
    """

    def test_correct_ticket_id_with_a_forged_secret_gets_nothing(
        self, handoff_enabled
    ):
        ticket = _new()
        assert _resolve(ticket.ticket_id) == store.RESOLVE_OK

        forged = f"{ticket.ticket_id}.not-the-holder-secret"
        assert store.peek(forged) is None
        assert store.take_resolved(forged) is None

        # And the real owner is untouched by the attempt.
        assert store.take_resolved(ticket.cookie_value) is not None

    def test_correct_ticket_id_with_no_secret_at_all_gets_nothing(
        self, handoff_enabled
    ):
        ticket = _new()
        _resolve(ticket.ticket_id)
        for attempt in (ticket.ticket_id, f"{ticket.ticket_id}.", ".secret", "", None):
            assert store.peek(attempt) is None, attempt
            assert store.take_resolved(attempt) is None, attempt

    def test_a_wrong_secret_is_indistinguishable_from_an_unknown_ticket(
        self, handoff_enabled
    ):
        """No oracle: a brute-forcer must not be able to tell a real ticket id
        with a bad secret from an id that never existed."""
        ticket = _new()
        _resolve(ticket.ticket_id)

        real_id_bad_secret = store.peek(f"{ticket.ticket_id}.wrong")
        made_up = store.peek("totally-made-up-ticket.wrong")
        assert real_id_bad_secret is None
        assert made_up is None

    def test_another_browsers_cookie_cannot_claim_this_ticket(self, handoff_enabled):
        """Two concurrent flows: each cookie may only ever open its own ticket."""
        victim = _new()
        attacker = _new()
        assert _resolve(victim.ticket_id) == store.RESOLVE_OK

        assert store.take_resolved(attacker.cookie_value) is None
        claimed = store.take_resolved(victim.cookie_value)
        assert claimed is not None


# ============================================================================
# Single use + race between two pollers
# ============================================================================

class TestSingleUse:
    def test_claim_is_single_use(self, handoff_enabled):
        ticket = _new()
        _resolve(ticket.ticket_id)

        assert store.take_resolved(ticket.cookie_value) is not None
        assert store.take_resolved(ticket.cookie_value) is None
        assert store.peek(ticket.cookie_value) is None

    def test_two_pollers_sharing_the_cookie_deliver_once(self, handoff_enabled):
        """Threat 4. Two tabs of the SAME browser share the cookie, so both can
        authenticate — but only one may walk away with the identity, or one
        LINE completion would mint two sessions."""
        ticket = _new()
        _resolve(ticket.ticket_id)

        results = [
            store.take_resolved(ticket.cookie_value),
            store.take_resolved(ticket.cookie_value),
        ]
        assert sum(1 for r in results if r is not None) == 1

    def test_a_second_line_completion_cannot_overwrite_the_first(
        self, handoff_enabled
    ):
        ticket = _new()
        assert _resolve(ticket.ticket_id, line_user_id="Ufirst") == store.RESOLVE_OK
        assert _resolve(ticket.ticket_id, line_user_id="Usecond") == store.RESOLVE_ALREADY

        claimed = store.take_resolved(ticket.cookie_value)
        assert claimed["line_user_id"] == "Ufirst"

    def test_resolving_a_consumed_ticket_is_unknown(self, handoff_enabled):
        ticket = _new()
        _resolve(ticket.ticket_id)
        store.take_resolved(ticket.cookie_value)
        assert _resolve(ticket.ticket_id) == store.RESOLVE_UNKNOWN


# ============================================================================
# Fixation — the IP binding on the LINE leg
# ============================================================================

class TestFixationBinding:
    """Threat 3. An attacker plants a ticket on their own device and phishes a
    victim into completing a LINE login onto it. The cookie cannot help — the
    attacker legitimately holds their own cookie — so the LINE leg is bound to
    the client IP that started the flow."""

    def test_completion_from_a_different_ip_is_refused(self, handoff_enabled):
        ticket = _new(client_ip="198.51.100.7")  # attacker's device
        outcome = _resolve(ticket.ticket_id, client_ip="203.0.113.99")  # victim
        assert outcome == store.RESOLVE_IP_MISMATCH

    def test_a_refused_completion_parks_nothing(self, handoff_enabled):
        """The attacker's polling tab must find the ticket still empty — the
        victim's identity is discarded, never held for collection."""
        ticket = _new(client_ip="198.51.100.7")
        _resolve(ticket.ticket_id, client_ip="203.0.113.99")

        assert store.take_resolved(ticket.cookie_value) is None
        assert store.peek(ticket.cookie_value) == "pending"

    def test_the_real_user_can_still_complete_afterwards(self, handoff_enabled):
        """A refusal leaves the ticket pending, so a genuine user whose first
        attempt tripped the check is not locked out of their own flow."""
        ticket = _new(client_ip="198.51.100.7")
        _resolve(ticket.ticket_id, client_ip="203.0.113.99")

        assert _resolve(ticket.ticket_id, client_ip="198.51.100.7") == store.RESOLVE_OK
        assert store.take_resolved(ticket.cookie_value) is not None

    def test_same_ip_completion_is_accepted(self, handoff_enabled):
        """The legitimate hand-off is same-phone: Safari and LINE's in-app
        browser share one egress IP seconds apart."""
        ticket = _new(client_ip="198.51.100.7")
        assert _resolve(ticket.ticket_id, client_ip="198.51.100.7") == store.RESOLVE_OK


# ============================================================================
# Expiry / abandonment
# ============================================================================

class TestExpiry:
    def test_expired_ticket_cannot_be_claimed(self, handoff_enabled, monkeypatch):
        monkeypatch.setenv("LINE_HANDOFF_TICKET_TTL_SECONDS", "0.05")
        ticket = _new()
        _resolve(ticket.ticket_id)

        time.sleep(0.08)
        assert store.peek(ticket.cookie_value) is None
        assert store.take_resolved(ticket.cookie_value) is None

    def test_expired_ticket_cannot_be_resolved(self, handoff_enabled, monkeypatch):
        monkeypatch.setenv("LINE_HANDOFF_TICKET_TTL_SECONDS", "0.05")
        ticket = _new()

        time.sleep(0.08)
        assert _resolve(ticket.ticket_id) == store.RESOLVE_UNKNOWN

    def test_expired_tickets_are_pruned_from_the_store(
        self, handoff_enabled, monkeypatch
    ):
        monkeypatch.setenv("LINE_HANDOFF_TICKET_TTL_SECONDS", "0.05")
        for _ in range(5):
            _new()
        time.sleep(0.08)

        monkeypatch.setenv("LINE_HANDOFF_TICKET_TTL_SECONDS", "300")
        fresh = _new()
        # The prune runs on create; only the fresh ticket should survive.
        assert store.peek(fresh.cookie_value) == "pending"
        assert len(store._tickets) == 1

    def test_ttl_default_fits_inside_the_oidc_login_ticket_ttl(self, monkeypatch):
        """A hand-off that outlived its inner OIDC login ticket would dead-end
        on retry, so the budget must stay the shorter of the two."""
        from app.services import oidc_service

        monkeypatch.delenv("LINE_HANDOFF_TICKET_TTL_SECONDS", raising=False)
        assert store.ticket_ttl_seconds() < oidc_service.LOGIN_TICKET_TTL_SECONDS


# ============================================================================
# Capacity ceilings
# ============================================================================

class TestCeilings:
    def test_store_refuses_beyond_the_ticket_ceiling(self, handoff_enabled, monkeypatch):
        monkeypatch.setattr(store, "MAX_TICKETS", 3)
        assert all(_new() for _ in range(3))
        assert store.create_ticket(inner_hint="oidc:x", client_ip=IP) is None

    def test_waiter_slots_are_bounded_and_returned(self, handoff_enabled, monkeypatch):
        monkeypatch.setattr(store, "MAX_CONCURRENT_WAITERS", 2)
        assert store.try_acquire_waiter() is True
        assert store.try_acquire_waiter() is True
        assert store.try_acquire_waiter() is False
        assert store.active_waiters() == 2

        store.release_waiter()
        assert store.try_acquire_waiter() is True

    def test_release_never_goes_negative(self, handoff_enabled):
        store.release_waiter()
        store.release_waiter()
        assert store.active_waiters() == 0
