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
    # Widens /hk to EVERY branch in HK_BRANCHES for the holder, instead of the
    # single location derived from their Employee.location. Owner decision
    # 2026-08-17 ("admin can pick location"): location enforcement pins each
    # maid to her own property, which is right for maids and wrong for whoever
    # supervises both. Grant-based on purpose — no badge is hardcoded anywhere.
    #
    # It carries NO Employee Hub button, and that is safe by construction:
    # MENU_GRANT_APP_IDS is derived from MENU_BUTTONS, so staff_oa_menu treats
    # this grant as menu-irrelevant — same variant, same menu name, same
    # signature, no re-render, no re-link. Granted ALONE (without
    # `housekeeping`) it resolves to the empty base, i.e. no menu at all, so it
    # is not a back door to the maid menu.
    ("housekeeping_admin", "Housekeeping Admin (all locations)"),
    # Read-only viewer on the SAME /hk room-status board the maids write to.
    # new-hotel's hk_access middleware admits either grant; `reception` sees
    # the board and is refused the write verbs (403 on POST .../cleaning and
    # POST .../linen-shortage), while `housekeeping` keeps full access and an
    # identity holding both is full. Registration here is load-bearing, not
    # bookkeeping: admin_employees.py rejects any app_id outside this catalog
    # with a 400, so an unregistered grant cannot be saved at all.
    #
    # Unlike housekeeping_admin, this one DOES carry an Employee Hub button
    # (สถานะห้อง, staff_oa_menu) — so granting it re-provisions the holder's
    # rich menu, and an employee holding it alone gets a real one-tile menu
    # rather than resolving to the empty base.
    ("reception", "Reception (room status, read-only)"),
    # Every active employee submits expenses — default-granted at onboarding.
    # Cloudflare Access on reimbursement.thehfhotel.org checks the `apps`
    # claim for it ('HF ID grant: reimbursement'), and the office NFC
    # terminal's /reader/claim flow requires it too (403 not_authorized
    # otherwise). Added 2026-07 when the app's own LINE login was retired.
    ("reimbursement", "Reimbursement"),
]

# Apps granted automatically when an admin approves a pending onboarding.
DEFAULT_GRANTED_APP_IDS: Tuple[str, ...] = ("rooms", "portal", "reimbursement")

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
