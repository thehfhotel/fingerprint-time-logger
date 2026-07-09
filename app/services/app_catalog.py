"""App catalog for the employee app-grants feature (2026-07).

A small, static list for now — promote to a table if/when apps need to be
added without a deploy. Each entry is (app_id, display_name).
"""
from typing import List, Optional, Tuple

APP_CATALOG: List[Tuple[str, str]] = [
    ("rooms", "Room Daily Report"),
    ("portal", "HF Portal"),
    # Deliberately NOT in DEFAULT_GRANTED_APP_IDS — payroll is granted
    # per-person (Cloudflare Access checks the `apps` claim for it).
    ("payroll", "Payroll"),
    # Per-person like payroll (Cloudflare Access already carries an
    # 'HF ID grant: ota' policy on ota.thehfhotel.org). Also reveals the
    # OTA Desk button on the Employee Hub Role Menu (staff_oa_menu).
    ("ota", "OTA Desk"),
    # Per-person like payroll — reveals the maids' Housekeeping button on
    # the Employee Hub Role Menu (staff_oa_menu). The maid-facing surface
    # itself is employee-login plan Phase 4 (hotel.thehfhotel.org/hk).
    ("housekeeping", "Housekeeping"),
]

# Apps granted automatically when an admin approves a pending onboarding.
DEFAULT_GRANTED_APP_IDS: Tuple[str, ...] = ("rooms", "portal")

_VALID_APP_IDS = {app_id for app_id, _ in APP_CATALOG}


def is_valid_app_id(app_id: str) -> bool:
    """Whether app_id exists in the catalog."""
    return app_id in _VALID_APP_IDS


def app_display_name(app_id: str) -> Optional[str]:
    """Look up an app's display name, or None if unknown."""
    for catalog_app_id, name in APP_CATALOG:
        if catalog_app_id == app_id:
            return name
    return None
