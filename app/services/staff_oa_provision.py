"""Automatic Employee Hub Role Menu provisioning (2026-08-14).

WHY THIS MODULE EXISTS
----------------------
Until now, ticking "Housekeeping" in the Employee Management UI committed a
row to ``employee_app_grants`` and did nothing else. The maid's LINE menu
only appeared after a human SSHed to the host and ran
``docker exec fingerprint-time-logger python scripts/staff_oa_sync.py
--apply``. The owner's requirement (2026-08-14) is that the grant alone is
enough: *"make it auto when housekeeping or new menu is granted then maids
or users see new LINE OA menu. should be seamless from admin perspective.
no need to run commands."*

The audience is 80+ year old maids. A maid who silently gets no menu will
not file a bug — she will just stop using the tool. So the failure mode
this module is designed around is SILENCE, not noise.

WHY NOT staff_oa_service.link_role_menu_for_line_user()
-------------------------------------------------------
That helper only LINKS a user to an ALREADY-DEPLOYED menu: it resolves the
variant through ``deployed_menu_ids_by_key()`` and, when the variant is
missing, logs "run scripts/staff_oa_sync.py --apply" and gives up. The
logic that CREATES a variant (render the PNG, POST /v2/bot/richmenu,
upload the image) lived ONLY in scripts/staff_oa_sync.py. A genuinely NEW
grant combination therefore had no menu to link to, which is exactly the
case an admin ticking a new checkbox produces. This module closes that gap:
it ensures the variant exists, then links.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
No menu deletion and no channel-default changes. Both are destructive,
CROSS-EMPLOYEE operations — the stale-menu sweep can delete a menu other
employees are still linked to mid-run, and the channel default is what
every un-linked follower sees. Those stay in the full sync
(scripts/staff_oa_sync.py), which reasons about the whole channel at once.
This path is strictly ADDITIVE and PER-USER: create-if-missing, link, or
unlink this one employee. That is what makes it safe to fire from an HTTP
handler and from an hourly job without a lock.

NEVER RAISES
------------
Every public function swallows its exceptions. This runs behind an admin's
save button and inside a scheduler job: LINE being down, slow, throttled or
misconfigured must NEVER fail or roll back the grant write. Same estate
rule as ~/HF/housekeeping's notify.ts — "a failed notification never fails
the user's request". The safety-net reconcile below is what converges a run
that was swallowed.
"""

import logging
from typing import List, Set

from app.core import database
from app.models.models import Employee
from app.services import staff_oa_images, staff_oa_menu, staff_oa_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-employee provisioning
# ---------------------------------------------------------------------------

def provision_for_badge(badge_number: str) -> None:
    """Make one employee's LINE Role Menu match their current grants.

    SYNCHRONOUS and blocking (``requests`` + PIL), by design: FastAPI runs a
    sync ``BackgroundTasks`` callable in a threadpool and APScheduler reaches
    it through ``asyncio.to_thread``, so the blocking LINE/PIL work never
    touches the event loop. This repo was bitten by exactly that failure
    earlier today — blocking LINE calls on the loop stalled /oidc/token — so
    keep this function sync and let the callers place it off-loop rather than
    making it ``async`` and awaiting blocking I/O.

    Never raises. Callers do not check a return value; the log is the record.
    """
    try:
        _provision(badge_number)
    except Exception:  # noqa: BLE001 — see NEVER RAISES in the module docstring
        # .exception() so the traceback survives: this is the only place a
        # LINE/PIL failure on this path is ever visible, and the admin who
        # triggered it has already been told their save succeeded (it did).
        logger.exception(
            "Employee Hub menu provisioning failed for badge=%s; the grant "
            "change itself is committed and unaffected. The hourly reconcile "
            "job will retry.", badge_number,
        )


def _provision(badge_number: str) -> None:
    """The real work — may raise; ``provision_for_badge`` is the guard."""
    # 1. Dark check. The whole Employee Hub ships dark until the staff OA
    #    exists and STAFF_OA_CHANNEL_* are delivered, so this is the normal
    #    state on dev machines and in CI: debug, not warning.
    if not staff_oa_service.is_enabled():
        logger.debug(
            "Staff OA is dark (STAFF_OA_CHANNEL_* unset) — skipping menu "
            "provisioning for badge=%s", badge_number,
        )
        return

    # 2. Our OWN database session. This runs AFTER the HTTP response has been
    #    sent, so the request-scoped session from Depends(get_db) is already
    #    closed. Read everything we need, then CLOSE before touching LINE:
    #    the LINE round-trips below can take tens of seconds (15s timeout per
    #    call, several calls), and holding an idle session open across them
    #    for no reason is how connection pools get exhausted.
    db = database.SessionLocal()
    try:
        employee = (
            db.query(Employee)
            .filter(Employee.badge_number == badge_number)
            .first()
        )

        # 3. Nothing to link for: unknown badge, deactivated employee (which
        #    includes a self-onboarded row still pending admin approval —
        #    those are created is_active=False), or no LINE account linked
        #    yet. The last one is NOT an error and is a routine onboarding
        #    order: the admin grants housekeeping while line_user_id is still
        #    None, and the employee links LINE afterwards. The link sites call
        #    this function again at that point (see app/api/line_auth.py and
        #    app/api/admin_onboarding.py), which is what makes grant-then-link
        #    work without anyone re-saving the grants.
        if employee is None:
            logger.info(
                "No employee %s — nothing to provision on the staff OA",
                badge_number,
            )
            return
        line_user_id = employee.line_user_id
        is_active = bool(employee.is_active)
        if not line_user_id:
            logger.info(
                "Employee %s has no linked LINE account yet — nothing to "
                "link; provisioning will run again when they link LINE",
                badge_number,
            )
            return

        # 4. Grants -> menu variant. grants_for_badge returns ALL grants; the
        #    menu model filters to the menu-relevant ones itself. Skipped for
        #    an inactive employee: their menu is revoked wholesale below, so
        #    their grants are irrelevant.
        grants = (
            staff_oa_service.grants_for_badge(db, badge_number)
            if is_active
            else set()
        )
    finally:
        db.close()

    # An inactive employee must LOSE their menu, not merely be skipped. Simply
    # returning would leave a departed or suspended maid holding live tiles
    # indefinitely: the event triggers never fire for her again, and the hourly
    # reconcile walks only ACTIVE employees, so nothing would ever converge it.
    # The tiles would still 403 at Cloudflare (the `apps` claim goes with the
    # grant), but a button that opens a block page is exactly the dead-end this
    # Hub keeps shedding — better she has no menu at all.
    #
    # Deliberately AFTER db.close(): every LINE round-trip in this module runs
    # with no session held (see the comment above the session block). Unlinking
    # is idempotent — LINE answers 404 when there is no link, which
    # unlink_rich_menu_from_user treats as success.
    if not is_active:
        staff_oa_service.unlink_rich_menu_from_user(line_user_id)
        logger.info(
            "Employee %s is inactive — unlinked their staff OA menu",
            badge_number,
        )
        return

    _provision_line_user(badge_number, line_user_id, grants)


def _provision_line_user(
    badge_number: str, line_user_id: str, grants: Set[str]
) -> None:
    """The LINE half: no database session is held while any of this runs."""
    key = staff_oa_menu.menu_key(grants)
    buttons = staff_oa_menu.buttons_for(grants)

    # 5. No buttons -> no menu, and ACTIVELY unlink. Since the Hub became a
    #    maid-only tool (see the MENU_BUTTONS comment in staff_oa_menu) the
    #    `base` variant is EMPTY by design: an employee with no
    #    menu-relevant grant must have NO menu, not a degraded one and not
    #    somebody else's. Unlinking rather than merely declining to link is
    #    the point of running on grant CHANGE: a demoted maid whose
    #    `housekeeping` grant was just revoked would otherwise keep maid
    #    tiles she no longer holds the grant for — buttons that now open a
    #    Cloudflare block page. A revocation has to be as automatic as a
    #    grant, or "seamless from admin perspective" only holds in one
    #    direction.
    if not buttons:
        staff_oa_service.unlink_rich_menu_from_user(line_user_id)
        logger.info(
            "Unlinked staff-hub menu for badge=%s (variant %r has no buttons "
            "— employee holds no menu-relevant grant)", badge_number, key,
        )
        return

    # 6. Over LINE's 6-button cap. menu_size() raises for anything outside
    #    1-6, and it is reached again (via menu_signature) from
    #    rich_menu_name() below, so catching it here is what keeps this
    #    function from raising on a grant combination LINE physically cannot
    #    render as one menu. Not a live case, but no longer comfortable
    #    insurance either: since รายงานแม่บ้าน (2026-09-02) the largest real
    #    variant, base+housekeeping+reception, is EXACTLY at LINE's cap of 6,
    #    so one more MenuButton row makes this branch real for the employees
    #    who hold both grants. Mirrors the same guard in
    #    scripts/staff_oa_sync.py, with the same disposition —
    #    unlink, because with base empty there is no menu to fall back to.
    try:
        staff_oa_menu.menu_size(len(buttons))
    except ValueError as exc:
        logger.warning(
            "Staff-hub variant %r for badge=%s needs %d buttons, over LINE's "
            "6-button cap (%s) — unlinking this employee's rich menu instead. "
            "Remove one of this variant's grants, or ship a >6-button layout.",
            key, badge_number, len(buttons), exc,
        )
        staff_oa_service.unlink_rich_menu_from_user(line_user_id)
        return

    # 7 + 8. Ensure the variant's menu exists, then link this user to it.
    rich_menu_id = _ensure_variant_menu(key, grants)
    staff_oa_service.link_rich_menu_to_user(line_user_id, rich_menu_id)
    logger.info(
        "Linked staff-hub menu %r (%s) to badge=%s",
        key, rich_menu_id, badge_number,
    )


def _ensure_variant_menu(key: str, grants: Set[str]) -> str:
    """Return the richMenuId for this variant, creating the menu if absent.

    ``rich_menu_name`` embeds a content signature over the buttons, URLs,
    layout and image style (``staffhub:<variant>:<sig>``), so an exact name
    match means an identical menu — that IS the idempotency key, the same one
    scripts/staff_oa_sync.py reuses. A changed button table mints a new name
    and therefore a new menu; the old one is left alone for the full sync's
    stale sweep to reclaim (deleting it here could yank a menu other
    employees are still linked to — see WHAT IT DELIBERATELY DOES NOT DO).
    """
    name = staff_oa_menu.rich_menu_name(grants)
    for menu in staff_oa_service.get_rich_menu_list():
        if menu.get("name") == name:
            logger.debug("Reusing deployed staff-hub menu %s", name)
            return menu["richMenuId"]

    # Render BEFORE creating. A PIL failure (missing font, bad glyph) then
    # leaves nothing behind on the channel at all, instead of an imageless
    # menu we would have to clean up.
    png_bytes = staff_oa_images.render_menu_image(staff_oa_menu.buttons_for(grants))
    rich_menu_id = staff_oa_service.create_rich_menu(
        staff_oa_menu.rich_menu_payload(grants)
    )
    try:
        staff_oa_service.upload_rich_menu_image(rich_menu_id, png_bytes)
    except Exception:
        # A rich menu with no image is UNUSABLE: LINE rejects linking it to a
        # user, so leaving it behind would poison every future run — the name
        # lookup above would find it, hand back its id, and the link would
        # fail forever. Delete it so the next attempt recreates it cleanly and
        # the retry CONVERGES rather than wedging. The delete is itself
        # best-effort: if it fails too, say so loudly (that is the one state
        # this path can leave that needs a human with the sync script) and
        # still re-raise the original upload error, which is the real cause.
        try:
            staff_oa_service.delete_rich_menu(rich_menu_id)
            logger.warning(
                "Image upload failed for staff-hub menu %s (%s) — deleted the "
                "imageless menu so the next run recreates it",
                name, rich_menu_id,
            )
        except Exception:  # noqa: BLE001 — never mask the upload failure
            logger.exception(
                "Image upload failed for staff-hub menu %s (%s) AND the "
                "cleanup delete failed — an imageless menu is left on the "
                "channel and will block linking this variant until it is "
                "removed (scripts/staff_oa_sync.py --apply sweeps it)",
                name, rich_menu_id,
            )
        raise

    logger.info(
        "Created staff-hub menu %s (%s, image %d bytes)",
        name, rich_menu_id, len(png_bytes),
    )
    return rich_menu_id


# ---------------------------------------------------------------------------
# Safety-net reconcile
# ---------------------------------------------------------------------------

def reconcile_all() -> None:
    """Run every active, LINE-linked employee through ``provision_for_badge``.

    The safety net behind the event-driven triggers, converging anything they
    missed: LINE down or throttled at grant time, a grant written straight
    into the database, a rich menu deleted by hand on the LINE console. It
    reaches the same per-employee code path, so it inherits the same
    guarantees — additive only, no deletions, no channel-default changes, and
    one employee's failure never stops the next one's.

    Blocking (it is the same synchronous path); the scheduler calls it
    through ``asyncio.to_thread``. Never raises.
    """
    try:
        if not staff_oa_service.is_enabled():
            logger.debug("Staff OA is dark — reconcile is a no-op")
            return

        badges = _linked_active_badges()
        if not badges:
            logger.debug("No active LINE-linked employees to reconcile")
            return

        logger.info("Reconciling staff-hub menus for %d employee(s)", len(badges))
        for badge_number in badges:
            # One employee's failure must never stop the next one's — a batch
            # is only worth more than a single call if a poison row cannot
            # wedge it. provision_for_badge already swallows its own
            # exceptions, so this is belt-and-braces; it is here anyway so
            # that the sweep's guarantee is LOCAL rather than a promise made
            # by another function that a later refactor could quietly break.
            try:
                provision_for_badge(badge_number)
            except Exception:  # noqa: BLE001 — keep sweeping
                logger.exception(
                    "Reconcile failed for badge=%s; continuing with the rest",
                    badge_number,
                )
    except Exception:  # noqa: BLE001 — must never throw into the scheduler
        logger.exception("Staff-hub menu reconcile failed")


def _linked_active_badges() -> List[str]:
    """Badges of every active employee with a linked LINE account.

    Its own short-lived session, closed before any LINE call happens, for the
    same reason ``_provision`` closes early: the sweep that follows can take
    minutes of network time.
    """
    db = database.SessionLocal()
    try:
        rows = (
            db.query(Employee.badge_number)
            .filter(
                Employee.line_user_id.isnot(None),
                Employee.is_active == True,  # noqa: E712
            )
            .all()
        )
        return [badge for (badge,) in rows]
    finally:
        db.close()
