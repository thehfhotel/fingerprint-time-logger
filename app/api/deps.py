"""
Defense-in-depth auth dependency for the consolidated /api/private/*
routers that carry NO in-app auth at all (attendance, devices, employees,
system, shifts, leaves — see app/main_unified.py's ``include_router``
calls for each). Their only protection has ever been edge-side
Cloudflare Access on erp.thehfhotel.org (the ONE Access app that fronts
both /fingerprintlogs* and /api/private*, tier "staff" — see
hf-erp/infra/cloudflare/hostnames.json's erp.thehfhotel.org entry and
gate-erp-api-private.ts). That edge-only posture is exactly why
publishing id.thehfhotel.org with access:"none" (the SAME backend
process on a different hostname) briefly served these routers with zero
authentication — full roster, attendance history, and the ZKTeco device
password, plus unauthenticated write routes — until closed at the edge
2026-08-14 (see hf-erp/infra/cloudflare/gate-hfid-host.ts's docstring for
the measured exposure).

``require_cf_access`` below is the in-app half of that fix: a router
that depends on it rejects any request that does not carry a
fully-verified Cloudflare Access JWT, so a future ungated hostname
pointing at this same process gets 401 instead of the live data these
routers serve.

DELIBERATELY NOT app.api.admin_auth.require_admin_auth
------------------------------------------------------
require_admin_auth ALSO requires the verified identity to be on the
admin/manager allowlist (app.services.cf_access_service._is_allowlisted_
admin_email). That is the wrong shape here: the Access app fronting
/fingerprintlogs* + /api/private* is tier "staff", not "managers" —
it legitimately admits non-admin identities. Two independent pieces of
evidence in THIS repo confirm real, live non-admin traffic against these
exact routers:

  1. tests/unit/test_admin_auth_cf_access.py's NON_ADMIN_EMAIL /
     tests/unit/test_cf_access_service.py's EMPLOYEE_EMAIL stand in for a
     real HF shared mailbox (the reception-1 kiosk identity per hf-erp's
     hostnames.json) that these same Access apps admit but that must
     never get admin auto-login — the test files use a clearly-fake
     placeholder address, kept out of MANAGER_ADMIN_EMAILS, rather than
     the real one.
  2. app/main_unified.py's own page guards encode a two-tier split:
     serve_admin_page() (the /v2/employees, /v2/system, /v2/terminals
     pages) requires an admin identity, while serve_html_with_cache_
     control() (the /v2/live, /v2/by-date, /v2/monthly, /v2/shifts-admin
     pages — which fetch() these exact routers) does not — "Same
     Cloudflare Access posture as the rest of /fingerprintlogs/* —
     protected upstream, not at the FastAPI layer" (see e.g.
     serve_v2_shifts_admin's docstring). Gating these routers to
     admin-only would 401 every one of those already-legitimate,
     non-admin staff/kiosk sessions on a live dashboard.

require_cf_access matches the routers' actual designed audience:
anyone who passed the ONE staff-tier Access app in front of them, admin
or not — not specifically an admin. It is strictly additive versus
today (currently: zero check at all) for every consumer, admin and
non-admin alike.

NOT wired to cf_access_service.is_cf_auto_login_enabled()
-----------------------------------------------------------
That flag is documented as a kill switch for the UNRELATED admin
auto-login / passcode-skip convenience (app/api/admin_auth.py). Reusing
it here would mean flipping CF_AUTO_LOGIN=false to disable that
convenience also disables this defense-in-depth layer — an operational
trap for a security-critical check. require_cf_access always fully
verifies the token; there is no separate kill switch.
"""
import logging
from typing import Optional

from fastapi import HTTPException, Request, status

from app.services.cf_access_service import verify_cf_access

logger = logging.getLogger(__name__)


def _extract_cf_access_token(request: Request) -> Optional[str]:
    """Pull the Cloudflare Access JWT off the request.

    Checks the header Cloudflare's edge injects on every proxied request
    to a gated hostname first, then the cookie the Access UI sets
    client-side — same two sources app.services.cf_access_service checks
    for the admin auto-login path. Duplicated here (rather than imported)
    because that module's extractor is prefixed ``_`` — module-private by
    this codebase's convention — and the two-line extraction is cheap to
    keep independent of that module's internals.
    """
    header_token = request.headers.get("Cf-Access-Jwt-Assertion")
    if header_token:
        return header_token
    return request.cookies.get("CF_Authorization")


async def require_cf_access(request: Request) -> str:
    """FastAPI dependency: require a fully-verified Cloudflare Access
    identity — admin or not.

    Returns the verified email on success. Raises 401 when the token is
    missing, malformed, expired, or fails signature/issuer/audience
    verification. Verification itself (RS256 against Cloudflare's
    published JWKS; never trusts header presence alone — the container's
    port is LAN-reachable and bypasses Cloudflare's edge entirely) is
    delegated to cf_access_service.verify_cf_access, the same primitive
    the admin auto-login path already relies on.
    """
    token = _extract_cf_access_token(request)
    email = verify_cf_access(token) if token else None
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: valid Cloudflare Access session required",
        )
    return email
