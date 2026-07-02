"""Unit tests for app.services.admin_identity — turning the opaque
require_admin_auth identity into a safe, storable audit label.
"""
from app.services.admin_identity import admin_actor_label


def test_cf_access_identity_returns_email():
    assert admin_actor_label("cf-access:admin-1@example.invalid") == "admin-1@example.invalid"


def test_passcode_session_token_returns_generic_label():
    """The raw session token must never be persisted."""
    assert admin_actor_label("some-opaque-session-token-value") == "admin"


def test_empty_identity_returns_generic_label():
    assert admin_actor_label("") == "admin"
