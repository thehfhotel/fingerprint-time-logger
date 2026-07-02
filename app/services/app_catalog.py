"""App catalog for the employee app-grants feature (2026-07).

A small, static list for now — promote to a table if/when apps need to be
added without a deploy. Each entry is (app_id, display_name).
"""
from typing import List, Optional, Tuple

APP_CATALOG: List[Tuple[str, str]] = [
    ("rooms", "Room Daily Report"),
    ("portal", "HF Portal"),
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
