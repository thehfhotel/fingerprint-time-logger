"""Helper for turning the opaque require_admin_auth identity into a safe,
human-readable label for audit fields (employee_app_grants.granted_by,
application_logs entries, etc).

app.api.admin_auth.resolve_admin_identity returns either:
  - "cf-access:<email>" for a verified Cloudflare Access admin, or
  - the raw passcode session token for a passcode-authenticated admin.

The raw session token must NEVER be persisted (it's a live credential) —
so anything that isn't a cf-access identity collapses to a generic label.
"""

_CF_ACCESS_PREFIX = "cf-access:"
_GENERIC_ADMIN_LABEL = "admin"


def admin_actor_label(identity: str) -> str:
    """Safe, storable label for an authenticated admin identity.

    Returns the email for a CF Access identity, or a generic "admin" label
    for a passcode session (never the raw session token).
    """
    if identity and identity.startswith(_CF_ACCESS_PREFIX):
        return identity[len(_CF_ACCESS_PREFIX):]
    return _GENERIC_ADMIN_LABEL
