"""Housekeeping room-check escalation — who is on duty, and the LINE push.

The HF ID half of new-hotel's ADR 0008 ("Room signals over chat; LINE as door
and escalation valve, never the pipe"). new-hotel owns the room signals; when a
ขอเช็คห้อง (room_check) signal sits unacked for 2 minutes its scheduler calls
``POST /api/private/reader/hk-escalate`` here, because **HF ID owns attendance**
and is therefore the only system that can answer "who is physically working at
this branch right now".

Two responsibilities, kept apart so the hard one is testable without HTTP:

* :func:`on_duty_maids` — the ON-DUTY MAID rule (new-hotel CONTEXT.md glossary),
  a pure-ish query over Employee + AttendanceRecord + Device.
* :func:`escalate` — resolve, then multicast ONE canned Thai text to those
  maids' LINE user ids over the staff OA channel.

Quota discipline (ADR 0008 §Decision 3) lives on BOTH sides: new-hotel pushes
at most once per signal and stops at a monthly cap; this module never invents a
recipient — nobody on duty means NO push and no fallback, because the desk
phoning is the accepted (pre-existing) failure mode, and a broadcast to
off-shift maids would be metered spend for nothing.

No emojis, ever — the staff OA's messages are Thai operational text (same rule
as staff_oa_service / staff_oa_menu).
"""

from __future__ import annotations

import logging
from datetime import datetime, time as time_type, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.models import AttendanceRecord, Device, Employee
from app.services import staff_oa_service
from app.utils.timezone import BANGKOK_TZ

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The vocabulary this endpoint speaks (mirrors new-hotel; do not widen loosely)
# ---------------------------------------------------------------------------

#: branch code (the wire value new-hotel sends) -> devices.name of that
#: branch's fingerprint device. The DEVICE is what decides a maid's branch for
#: the day — see the "On-duty maid" glossary entry: a maid covering the other
#: property is on-duty THERE, beating her stored Employee.location home branch.
BRANCH_DEVICE_NAMES: Dict[str, str] = {
    "HF": "HF",
    "HF_VILLE": "HF Ville",
}

#: The one role that may ever receive a housekeeping escalation.
MAID_ROLE = "housekeeping"

#: Device punch codes that mean "arrived". Widened to include 255 (unspecified)
#: on 2026-09-01 after measuring prod: for housekeeping-role maids, 255 is ~62%
#: of the last 30 days' punches (139 of 223) — a strict {0} would miss most
#: real shifts and every escalation would silently answer nobody_on_duty. Any
#: presence punch at the branch device opens the shift; only an EXPLICIT
#: check-out (1) closes it. The residual cost is over-notifying a maid whose
#: leaving punch recorded as 255 — for a rare guest-waiting escalation, the
#: over-inclusive failure is the safe one.
CHECK_IN_PUNCH_TYPES = frozenset({0, 255})
#: Device punch codes that mean "went home". Only an explicit check-out closes
#: a shift; an unspecified (255) last punch leaves the maid on duty.
CHECK_OUT_PUNCH_TYPES = frozenset({1})

#: The canned escalation text. ONE line of Thai, then the deep link on its own
#: line. Nothing else is ever interpolated (see :func:`build_message`).
MESSAGE_TEMPLATE = "ขอเช็คห้อง {room_no} ยังไม่มีคนรับ กรุณากดรับในเมนูแม่บ้าน"

#: Conservative caps on the two caller-supplied fields. Over-cap is REJECTED by
#: the route rather than truncated: a truncated room number is a *wrong* room
#: number, which is worse than a failed escalation the caller retries.
ROOM_NO_MAX_CHARS = 16
URL_MAX_CHARS = 300


# ---------------------------------------------------------------------------
# Bangkok "today"
# ---------------------------------------------------------------------------

def bangkok_day_bounds_utc(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """[start, end) of the current Bangkok calendar day as NAIVE UTC datetimes.

    AttendanceRecord.timestamp is stored naive-UTC (see zk_session's
    ``_bangkok_to_utc``), so the day window has to be expressed the same way.
    ``now`` is injectable purely so tests can pin the day edge.
    """
    if now is None:
        now = datetime.now(BANGKOK_TZ)
    elif now.tzinfo is None:
        # A naive value is Bangkok wall-clock by this module's convention.
        now = now.replace(tzinfo=BANGKOK_TZ)
    today_bkk = now.astimezone(BANGKOK_TZ).date()
    start_bkk = datetime.combine(today_bkk, time_type.min, tzinfo=BANGKOK_TZ)
    end_bkk = start_bkk + timedelta(days=1)
    return (
        start_bkk.astimezone(timezone.utc).replace(tzinfo=None),
        end_bkk.astimezone(timezone.utc).replace(tzinfo=None),
    )


# ---------------------------------------------------------------------------
# The ON-DUTY MAID rule
# ---------------------------------------------------------------------------

def branch_device_name(branch: str) -> Optional[str]:
    """``devices.name`` for a branch code, or None when the code is unknown."""
    return BRANCH_DEVICE_NAMES.get(branch)


def on_duty_maids(
    db: Session, branch: str, *, now: Optional[datetime] = None
) -> List[Employee]:
    """Maids physically working at ``branch`` right now, LINE-reachable.

    The glossary rule, clause by clause (new-hotel CONTEXT.md, "On-duty maid"):

    1. ``role == 'housekeeping'`` — the employment role, and
    2. ``is_active`` — not an ex-employee, and
    3. ``line_user_id`` set — an unreachable maid is not an audience, and
    4. a CHECK-IN punch TODAY (Bangkok day) on a device named for THIS branch —
       the day's punch device decides her branch, beating ``Employee.location``
       entirely (a maid covering the other property is on-duty THERE), and
    5. her LAST punch today ON ANY DEVICE is not a check-out — she has not gone
       home. Deliberately any-device: a maid who checked in at HF and clocked
       out at HF Ville is off shift, not "still on duty at HF".

    Returns employees ordered by badge for a deterministic recipient list; an
    unknown branch code returns [] rather than raising (the route validates the
    code first, so reaching here with a bad one is a caller bug, not a push).
    """
    device_name = branch_device_name(branch)
    if device_name is None:
        return []

    day_start_utc, day_end_utc = bangkok_day_bounds_utc(now)

    branch_device_ids = [
        device_id
        for (device_id,) in db.query(Device.id).filter(Device.name == device_name).all()
    ]
    if not branch_device_ids:
        # No device row for this branch: nobody can have clocked in there.
        logger.warning(
            "hk-escalate: no device named %r for branch %s — nobody on duty",
            device_name, branch,
        )
        return []

    candidates = (
        db.query(Employee)
        .filter(
            Employee.role == MAID_ROLE,
            Employee.is_active.is_(True),
            Employee.line_user_id.isnot(None),
            Employee.line_user_id != "",
        )
        .order_by(Employee.badge_number.asc())
        .all()
    )
    if not candidates:
        return []

    badges = [employee.badge_number for employee in candidates]
    punches = (
        db.query(
            AttendanceRecord.employee_badge_number,
            AttendanceRecord.device_id,
            AttendanceRecord.punch_type,
            AttendanceRecord.timestamp,
            AttendanceRecord.id,
        )
        .filter(
            AttendanceRecord.employee_badge_number.in_(badges),
            AttendanceRecord.timestamp >= day_start_utc,
            AttendanceRecord.timestamp < day_end_utc,
        )
        .order_by(AttendanceRecord.timestamp.asc(), AttendanceRecord.id.asc())
        .all()
    )

    branch_device_id_set = set(branch_device_ids)
    checked_in_here: Dict[str, bool] = {}
    last_punch_type: Dict[str, int] = {}
    for badge, device_id, punch_type, _timestamp, _row_id in punches:
        if device_id in branch_device_id_set and punch_type in CHECK_IN_PUNCH_TYPES:
            checked_in_here[badge] = True
        # Rows arrive ascending, so the last write wins = the day's last punch.
        last_punch_type[badge] = punch_type

    return [
        employee
        for employee in candidates
        if checked_in_here.get(employee.badge_number)
        and last_punch_type.get(employee.badge_number) not in CHECK_OUT_PUNCH_TYPES
    ]


# ---------------------------------------------------------------------------
# The message
# ---------------------------------------------------------------------------

def build_message(room_no: str, url: str) -> str:
    """The canned Thai escalation text plus the deep link on its own line.

    The sentence is OURS; only ``room_no`` and ``url`` come from the caller, and
    both are re-clamped here (defence in depth — the route already validates
    them) so no code path can grow a third interpolation slot by accident.
    """
    safe_room_no = room_no.strip()[:ROOM_NO_MAX_CHARS]
    safe_url = url.strip()[:URL_MAX_CHARS]
    return MESSAGE_TEMPLATE.format(room_no=safe_room_no) + "\n" + safe_url


# ---------------------------------------------------------------------------
# The push
# ---------------------------------------------------------------------------

def escalate(
    db: Session,
    *,
    branch: str,
    room_no: str,
    url: str,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    """Resolve on-duty maids for ``branch`` and multicast the escalation.

    Returns the wire contract: ``{"sent", "recipients", "reason"?}``.

    Nobody on duty is a VALID, terminal outcome — ``{"sent": False,
    "recipients": 0, "reason": "nobody_on_duty"}`` with NO push and NO fallback
    audience (ADR 0008: the desk phones instead). The caller treats the 200 as
    "escalation attempted, do not try this signal again".

    A LINE failure propagates (``StaffOaApiError`` / ``requests`` exception) so
    the route can answer non-2xx and new-hotel retries on its next tick.
    """
    recipients = on_duty_maids(db, branch, now=now)
    if not recipients:
        logger.info(
            "hk-escalate: no on-duty maid at branch=%s for room %s — no push",
            branch, room_no,
        )
        return {"sent": False, "recipients": 0, "reason": "nobody_on_duty"}

    line_user_ids: Sequence[str] = [employee.line_user_id for employee in recipients]
    staff_oa_service.multicast_text_message(line_user_ids, build_message(room_no, url))
    logger.info(
        "hk-escalate: pushed room-check escalation branch=%s room=%s to %d maid(s)",
        branch, room_no, len(line_user_ids),
    )
    return {"sent": True, "recipients": len(line_user_ids)}
