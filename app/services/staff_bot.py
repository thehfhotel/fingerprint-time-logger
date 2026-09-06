"""HF ภายใน — the staff LINE bot: command router, rendering, debounce.

The Employee Hub's Official Account is now also a BOT. In the all-staff LINE
group (HF Family) it is a REPORT-ONLY heartbeat with ONE command carve-out —
an explicit @mention that files a แจ้งซ่อม ticket (see policy note below); a
1:1 chat gets every command — palette, digest, guest feedback, ticket intake,
status. This module is everything between the webhook and the reply: the
command router, the Flex palette, the digest/report text, and the debounce
state machine.

DESIGN AUTHORITY: hf-erp ADR "The staff bot answers only with reply tokens;
LINE meters pushes per recipient" (2026-09-05). Three of its rules are load
bearing here and must survive every future edit:

1. REPLIES ONLY, NEVER A PUSH. LINE counts a push per RECIPIENT — one push
   into a 17-person group is 17 metered messages, and this OA's whole
   allowance is 300/month. Every outbound message in this feature rides a
   webhook reply token, which is free at any chat size. Nothing in this
   module may ever call push/multicast/broadcast/narrowcast. The only
   metered sender in this app stays the bounded housekeeping escalation
   (app/services/hk_escalation_service.py).
2. NEVER RACE A HUMAN BURST. Staff type in bursts; a bot that answers the
   first line talks over the next four. So a command does not reply
   immediately: it opens a PENDING entry, and every later message in that
   chat refreshes the entry's reply token and restarts the quiet timer. The
   reply goes out after 15 s of quiet for a scheduled slot report (2 s for a
   1:1 command), and at the latest 45 s after the first trigger — LINE's
   reply tokens are short lived, so the cap is not optional. Two commands in
   one burst coalesce into ONE reply carrying both messages.
3. DISCARD BEFORE LOGGING. The webhook sees all of HF Family's traffic.
   Non-command chat is dropped without a log line of any kind, and a command
   logs only the event type, the source type and the chat id — never the
   message text, never a photo, never who said it. That is a privacy
   commitment to staff, enforced at the top of :func:`handle_event`.

GROUP/ROOM SOURCES ARE REPORT-ONLY (owner policy, 2026-09-06 — "command
through chat is considered spam in HF Family group... feedback is not
considered spam... feedback should be consolidated and report in reporting
style not chat style"), WITH ONE EXPLICIT COMMAND CARVE-OUT (owner, 2026-09-06
evening — "HF Family should be able to get mention and act to create new
maintenance ticket still"). A group or room still never answers an ordinary
command: text (summoned or bare, any word), a postback from an old
confirmation bubble, and media are never turned into a command, never
buffered as a ticket claim on their own, never acknowledged — see
:func:`route_event`, which returns a plain :class:`RoutedMessage` (never a
:class:`RoutedCommand`) for ordinary group/room text and media, and ``None``
for a group/room postback. The ONE exception: an explicit @-mention of the
bot (``message.mention.mentionees[]`` carrying ``isSelf: true``) whose
remainder — the mention span stripped, LINE's own UTF-16 code-unit offsets
converted safely (:func:`_strip_utf16_span`) — is แจ้งซ่อม (bare or with a
room/symptom) routes as :data:`COMMAND_REPORT`, exactly like the 1:1 form:
same parser, same identity/NOT_LINKED gate, same photo buffer (buffered again
for group/room senders so a mention just after a photo burst can still claim
it) and 2-minute attach window — only the confirmation reply differs, a
compact TEXT line (:func:`build_group_confirmation_text`) rather than the
Flex bubble with (dead, ignored-in-a-group) postback buttons, pointing the
reporter at the 1:1 chat for anything else. Any OTHER mention remainder
(empty, งานค้าง, anything else) is ignored exactly like unmentioned chat. The
ONLY things a group or room ever hear from this bot are the SLOT REPORT below
and this one ticket confirmation/NOT_LINKED/parse-error line. Every other
command, ticket edit and preview in this module stays 1:1 only.

PHASE 2 (2026-09-05) adds the SLOT REPORT: four daily Bangkok windows in which
a report is posted into a GROUP exactly once, piggybacking on whatever the
humans were already saying (any message counts as the heartbeat — text,
sticker, photo, video; report-only groups never read what was said) so it
still rides a free reply token. It is the one thing here that waits —
SLOT_QUIET_SECONDS of quiet, so it never races reception's report burst — and
the one thing that keeps state in the database (``staff_bot_slot_marks``),
because "once per slot" has to survive a restart. A window nobody talks in is
skipped. Consolidated 2026-09-06 (owner: "feedback should be consolidated and
report in reporting style"): the report carries TWO sections — (a) the
existing งานค้าง maintenance digest, (b) pending guest feedback, rendered as
one line per item (:func:`render_feedback_section`) rather than chat prose —
either section is simply omitted when its own source is dark/unreachable or
has nothing to say, and the whole report posts nothing only when BOTH are
empty, so a scheduled message never spams an error line into HF Family but
also never drops real content it does have. See "Slot digest" below and
hf-erp ADR 0007.

PHASE 3 (2026-09-06) adds TICKET INTAKE, 1:1 only: a linked employee types
แจ้งซ่อม <room/area> <symptom> and the bot creates a work order in
housekeeping over the internal door (app/services/housekeeping_client.py),
replies a confirmation bubble at once, and uploads any photos the sender sent
in the same burst in the BACKGROUND (never blocking the reply). Postbacks on
that bubble (fixcat/setcat/toggleurgent/addphoto/cancel/switchprop) let the
reporter (or a `reception`-grant holder) edit or cancel while housekeeping
still allows it. A photo is NEVER downloaded unless it is tied to a ticket —
either claimed at creation (buffered message ids only, 90 s TTL, no bytes, no
log) or received while that ticket's attach window is open (120 s, refreshed
per photo, hard capped at 5 min). See docs/EMPLOYEE_HUB_SETUP.md and hf-erp
docs/staff-bot-plan.md ("Locked interface (phases 3 and 4)").

PHASE 4 (2026-09-06) adds STATUS, 1:1 only: งานของฉัน (palette button or the
bare word) answers a Flex carousel of the tapper's own active tickets (<= 10,
newest first, each with เพิ่มรูป/ยกเลิก buttons riding the phase-3 postbacks),
or one plain-text line when there are none or housekeeping is dark. 'สถานะ
<id>' / 'งาน <id>' answers the same ticket as one bubble, gated exactly like
the edit postbacks (reporter or a `reception`-grant holder) with its own 404
line — this is a READ, and never changes a ticket's status; that stays on
the reception board in every phase.

PHASE 5 (2026-09-06 evening) reopens ONE command in the group: the @mention
แจ้งซ่อม carve-out described above. It reuses phase 3's parser, identity gate,
photo buffer and attach window verbatim (:func:`_create_ticket` branches only
on ``action.source_type`` for which confirmation message to send) — nothing
about ticket creation itself is group-specific, only that a mention is now
how a group message can BECOME a COMMAND_REPORT at all (see
:func:`route_event`), and that its reply is deliberately lean (rule 3 of the
owner's message: no Flex buttons, since a group postback stays ignored).

PLAIN THAI, NO EMOJI, in every bot-facing string (house rule, same as
staff_oa_menu / hk_escalation_service). Anything human-typed that reaches a
message goes through :func:`strip_pictographs` first.

FAIL CLOSED: with HOUSEKEEPING_STAFF_BOT_TOKEN unset the digest read is dark
and the bot says one fixed Thai line rather than guessing or going quiet
(see app/services/housekeeping_client.py). The same rule covers the guest
feedback read: with either GUEST_FEEDBACK_BASE_URL or
GUEST_FEEDBACK_READER_SECRET unset, ความคิดเห็นลูกค้า answers its own fixed
Thai line (see app/services/guest_feedback_client.py).

GUEST FEEDBACK (ความคิดเห็นลูกค้า): since guest-feedback docs/CONTRACTS.md
§15 rev 3 ("the Employee Hub bot is the ONLY responder"), this bot is also
the sole sender for guest feedback raised on the public feedback site.
Rev 3.1 (2026-09-06) widened the queue from requests-only to every guest
submission — praise, issue and request alike, tagged ``kind`` and
``urgent`` in the pending JSON. It reads and confirms feedback from
guest-feedback (never holds it, never owns a queue) and answers only with
reply tokens, exactly like the housekeeping digest above. Consolidated into
the slot report (2026-09-06, see above) rather than chat-triggered: there is
no more group auto-offer on plain chatter — the ONLY place a group ever sees
pending feedback is section (b) of its own scheduled slot report, after
which the carried ids are confirmed delivered. A 1:1 ความคิดเห็นลูกค้า renders
the identical report-style section as a PREVIEW and never confirms delivery,
so pending rows are not silently consumed by someone checking privately.

TESTABILITY: :class:`ReplyDebouncer` is a pure state machine — an injectable
clock, an injectable scheduler, no I/O, no timers — so the debounce rules are
unit tested without waiting a single real second.
:class:`AsyncioBotDispatcher` is the thin adapter that gives it a real loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple, Union
from urllib.parse import parse_qs

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import database
from app.models.models import Employee, EmployeeAppGrant, StaffBotSlotMark
from app.services import guest_feedback_client, housekeeping_client, staff_oa_service
from app.utils.timezone import BANGKOK_TZ

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bot-facing strings (plain Thai, no emoji — house rule)
# ---------------------------------------------------------------------------

# The one short reply an unrecognised LINE account gets, in a 1:1 chat and on
# a follow event alike. Defined here because the bot is now the main sender of
# it; app/api/staff_oa.py re-exports the name so the follow path (and its
# tests) are unchanged.
ONBOARDING_REPLY_TEXT = (
    "ยินดีต้อนรับสู่ HF Employee Hub\n"
    "บัญชี LINE นี้ยังไม่ได้เชื่อมกับทะเบียนพนักงาน "
    "กรุณาสแกน QR บนป้ายพนักงาน (Q-badge) ของคุณ หรือเปิด "
    "https://erp.thehfhotel.org/qr-checkin/onboard "
    "เพื่อเชื่อมบัญชี แล้วเมนูเครื่องมือของคุณจะปรากฏที่นี่"
)

PALETTE_ALT_TEXT = "เมนู HF ภายใน"
PALETTE_TITLE = "HF ภายใน"
PALETTE_BODY = "มีอะไรให้ช่วยคะ"
PALETTE_BUTTON_LABEL = "งานค้าง แจ้งซ่อม"
PALETTE_BUTTON_DISPLAY_TEXT = "งานค้าง"
PALETTE_REQUESTS_BUTTON_LABEL = "ความคิดเห็นลูกค้า"
PALETTE_REQUESTS_BUTTON_DISPLAY_TEXT = "ความคิดเห็นลูกค้า"
# Phase 3/4 additions to the same palette bubble (existing two buttons kept).
PALETTE_REPORT_BUTTON_LABEL = "แจ้งซ่อมใหม่"
PALETTE_REPORT_BUTTON_DISPLAY_TEXT = "แจ้งซ่อมใหม่"
PALETTE_MINE_BUTTON_LABEL = "งานของฉัน"
PALETTE_MINE_BUTTON_DISPLAY_TEXT = "งานของฉัน"

# Housekeeping dark, unreachable, or refusing. ONE fixed line: staff get a
# plain Thai sentence, never a status code and never silence.
DIGEST_UNAVAILABLE_TEXT = "ระบบงานซ่อมยังไม่เชื่อมต่อ ลองใหม่อีกครั้งภายหลัง"
# The identical fixed line for a phase-3 write (create/edit/cancel/photo) —
# same fail-closed rule, same text, a separate name because the two features
# are allowed to drift apart later.
TICKET_UNAVAILABLE_TEXT = "ระบบแจ้งซ่อมยังไม่เชื่อมต่อ ลองใหม่อีกครั้งภายหลัง"

# A sender with no ACTIVE Employee.line_user_id tries to แจ้งซ่อม (or tap a
# ticket postback): free reply, group and 1:1 alike, never a silent drop.
NOT_LINKED_TEXT = "ยังไม่รู้จักบัญชีนี้ค่ะ กรุณาเชื่อมบัญชี LINE กับ HF ID ก่อนแจ้งซ่อม"

# A tapper who is neither the reporter nor a `reception`-grant holder tries
# to edit/cancel/add a photo to somebody else's ticket.
EDIT_FORBIDDEN_TEXT = "แก้ได้เฉพาะผู้แจ้งค่ะ"

# แจ้งซ่อมใหม่ (palette button / cmd=report_help): a one-line how-to. The
# group copy repeats the summon so it reads like something to paste back;
# the 1:1 copy drops it (no summon needed in a 1:1 chat).
REPORT_HELP_GROUP_TEXT = (
    "พิมพ์ น้องคะ แจ้งซ่อม <เลขห้อง> <อาการ> แล้วส่งรูปตามมาได้เลยค่ะ "
    "เช่น น้องคะ แจ้งซ่อม 204 แอร์ไม่เย็น ด่วน"
)
REPORT_HELP_DIRECT_TEXT = (
    "พิมพ์ แจ้งซ่อม <เลขห้อง> <อาการ> แล้วส่งรูปตามมาได้เลยค่ะ "
    "เช่น แจ้งซ่อม 204 แอร์ไม่เย็น ด่วน"
)

# งานของฉัน (palette button / text, phase 4): the tapper's own open tickets,
# reachable only with a resolved identity (see NOT_LINKED_TEXT above).
MINE_EMPTY_TEXT = "ไม่มีงานแจ้งซ่อมที่ค้างอยู่ค่ะ"
MINE_ALT_TEXT = "งานของฉัน"

# 'สถานะ <id>' / 'งาน <id>' (phase 4): a lookup gated the same way as the
# edit postbacks (reporter or `reception`), never a status CHANGE.
STATUS_FORBIDDEN_TEXT = "ดูได้เฉพาะงานของตัวเองค่ะ"
STATUS_NOT_FOUND_FMT = "ไม่พบงาน #{id} ค่ะ"

# Updated 2026-09-06 (reply-to-media): a bare quote-less เพิ่มรูป/postback now
# invites a video as well as a photo.
ADDPHOTO_PROMPT_FMT = "ส่งรูปหรือวิดีโอมาได้เลยค่ะ (ภายใน 2 นาที) #{id}"
CANCEL_SUCCESS_FMT = "ยกเลิก #{id} แล้วค่ะ"
FIXCAT_PROMPT_FMT = "เลือกหมวดใหม่ของ #{id}"

# The @mention report exception's confirmation (owner, 2026-09-06 evening): a
# compact TEXT reply, not the Flex bubble with buttons — group postbacks stay
# ignored, so buttons there would be dead. See build_group_confirmation_text.
GROUP_CONFIRMATION_FOLLOWUP_TEXT = "แก้ไขหรือดูสถานะได้ในแชทส่วนตัวกับ HF ภายใน"

# VIDEO (2026-09-06). message.type == "video" is buffered/claimed/attached
# exactly like an image; the one difference is LINE's server-side transcode,
# which must finish before the bytes are downloadable at all.
VIDEO_TRANSCODE_WAIT_SECONDS = 90.0
VIDEO_BYTES_MAX = 60 * 1024 * 1024
# A video's transcode can outlive a 60 s-ish LINE reply token. Past this many
# seconds of an IN-WINDOW video event, the "processing" line is filed on that
# event's own (about-to-expire) token instead of waiting for the real outcome
# — the eventual real ack is then silent, see AsyncioBotDispatcher.
VIDEO_ACK_DEADLINE_SECONDS = 40.0

VIDEO_TRANSCODE_FAILED_FMT = "วิดีโอประมวลผลไม่สำเร็จ ลองส่งใหม่อีกครั้งค่ะ (#{id})"
VIDEO_OVERSIZE_FMT = "วิดีโอใหญ่เกินไป (สูงสุด 60 MB) (#{id})"
VIDEO_PROCESSING_FMT = "วิดีโอกำลังประมวลผล จะแนบให้เมื่อพร้อมค่ะ (#{id})"

# Guest-feedback dark, unreachable, or refusing — the same fail-closed rule
# as the digest above, one fixed Thai line.
REQUESTS_UNAVAILABLE_TEXT = "ยังอ่านความคิดเห็นลูกค้าไม่ได้ค่ะ ลองใหม่อีกครั้ง"
# Reachable, but nothing is waiting.
REQUESTS_NONE_TEXT = "ยังไม่มีความคิดเห็นใหม่ค่ะ"

# ความคิดเห็นลูกค้า report section (b, 2026-09-06 consolidation): header,
# per-item line format, kind labels, the branch short form (matches
# guest-feedback's own src/shared/locations.ts branchShort), the display cap
# and how a comment/tags line is trimmed.
FEEDBACK_SECTION_HEADER_FMT = "ความคิดเห็นลูกค้า ({n} รายการ)"
FEEDBACK_KIND_LABELS: Dict[str, str] = {
    "praise": "คำชม", "issue": "ปัญหา", "request": "คำขอ",
}
FEEDBACK_BRANCH_LABELS: Dict[str, str] = {"hf": "HF", "hfville": "HF Ville"}
FEEDBACK_SECTION_LINE_CAP = 15
FEEDBACK_LINE_TEXT_MAX_CHARS = 80

THAI_MONTH_ABBREVIATIONS = (
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
)


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

COMMAND_PALETTE = "palette"
COMMAND_DIGEST = "digest"
COMMAND_ONBOARDING = "onboarding"
COMMAND_REQUESTS = "requests"

# Phase 2. NOT a command anybody can type: it is filed by the slot rules
# below when the bot decides this group's window is due. It renders the same
# digest as COMMAND_DIGEST, under a "สรุปงานซ่อมค้างประจำรอบ..." line.
COMMAND_SLOT_DIGEST = "slot_digest"

# Phase 3 — ticket intake. Each of these carries per-invocation data (order
# id, category, the แจ้งซ่อม text, the sender's resolved identity) on the
# RoutedCommand itself rather than through the plain command-word table
# below, because — unlike palette/digest/requests — no two calls to these
# render the same reply. See ReplyDebouncer.note_command's ``action`` param
# and PendingReply.actions.
COMMAND_REPORT = "report"
COMMAND_REPORT_HELP = "report_help"
# Phase 4 — the tapper's own open tickets as a Flex carousel.
COMMAND_MINE = "mine"
COMMAND_FIXCAT = "fixcat"
COMMAND_SETCAT = "setcat"
COMMAND_TOGGLEURGENT = "toggleurgent"
COMMAND_ADDPHOTO = "addphoto"
COMMAND_CANCEL = "cancel"
COMMAND_SWITCHPROP = "switchprop"
# Phase 4 — 'สถานะ <id>' / 'งาน <id>': one ticket's bubble, gated the same
# way as the edit postbacks (reporter or `reception`). A text command only
# (no palette button, no postback in normal use) but it still carries an
# order id, so it lives in TICKET_ORDER_POSTBACKS too — see _parse_postback.
COMMAND_STATUS = "status"
# Photo acknowledgements (owner request 2026-09-06). NOT typed by anybody and
# never routed by route_event: it is filed by AsyncioBotDispatcher._reply's
# background upload tasks via ReplyDebouncer.note_photo_ack, which stashes a
# small {order_id: {attached, total, failed}} payload on the PendingReply
# rather than a RoutedCommand (unlike every command above, no two acks in the
# same order ever look alike, and there is no sender identity to resolve).
COMMAND_PHOTO_ACK = "photo_ack"

TICKET_COMMANDS = frozenset({
    COMMAND_REPORT, COMMAND_REPORT_HELP, COMMAND_MINE,
    COMMAND_FIXCAT, COMMAND_SETCAT, COMMAND_TOGGLEURGENT,
    COMMAND_ADDPHOTO, COMMAND_CANCEL, COMMAND_SWITCHPROP,
    COMMAND_STATUS,
})
# Ticket commands that name an existing order (everything above except the
# three that never carry an id: report/report_help/mine).
TICKET_ORDER_POSTBACKS = frozenset({
    COMMAND_FIXCAT, COMMAND_SETCAT, COMMAND_TOGGLEURGENT,
    COMMAND_ADDPHOTO, COMMAND_CANCEL, COMMAND_SWITCHPROP,
    COMMAND_STATUS,
})

# Words that run the digest directly, with or without a summon in front.
DIGEST_WORDS = frozenset({"งานค้าง", "งานซ่อมค้าง", "แจ้งซ่อมค้าง"})

# Words that ask for the guest-feedback list directly — the queue is
# kind-agnostic (praise, issue and request alike), so words for any of the
# three kinds all resolve to the same command. Matched as the WHOLE remainder
# (group, after the summon) or the WHOLE message text (1:1) — see
# command_for_words — never as a substring, so e.g. "feedback" inside
# ordinary chatter ("ขอบคุณสำหรับ feedback นะ") is not a command.
REQUEST_WORDS = frozenset({
    "คำขอ", "คำขอลูกค้า", "guest requests",
    "ความคิดเห็น", "ฟีดแบค", "feedback",
})

# แจ้งซ่อม is a PREFIX command (the room/symptom follows); the others above
# are exact words. Checked only after the exact-word tables above, so
# "แจ้งซ่อมค้าง" (a digest word that happens to start with this prefix) is
# never mistaken for a report.
REPORT_WORD = "แจ้งซ่อม"
# งานของฉัน is exact, bare (no prefix) — phase 4's carousel.
MINE_WORD = "งานของฉัน"

# 'สถานะ <id>' / 'งาน <id>' (phase 4) — a strict "word, one space, digits"
# match, not a prefix, so ordinary chat starting with งาน (a very common
# Thai word) is never mistaken for this command. Checked after the exact
# words above (so งานของฉัน / งานค้าง / แจ้งซ่อมค้าง always win first) and
# before the แจ้งซ่อม prefix.
_STATUS_WORD_PATTERN = re.compile(r"^(?:สถานะ|งาน)\s+(\d{1,10})$")

# 'เพิ่มรูป <id>' / 'เพิ่มรูป #<id>' (reply-to-media, 2026-09-06) — bare in a
# group/room (no summon needed, same footing as แจ้งซ่อม's bare form) and in
# 1:1, and after a summon. A strict whole-string match, like the สถานะ/งาน
# pattern above, so it is never mistaken for ordinary chat.
_ADDPHOTO_WORD_PATTERN = re.compile(r"^เพิ่มรูป\s*#?(\d{1,10})$")

# Canonical order of the message objects in one coalesced reply.
COMMAND_ORDER = (COMMAND_ONBOARDING, COMMAND_PALETTE, COMMAND_DIGEST, COMMAND_REQUESTS)

# LINE's cap on message objects per reply.
MAX_REPLY_MESSAGES = 5
# LINE's cap on a text message.
MAX_MESSAGE_CHARS = 5000


# ---------------------------------------------------------------------------
# Debounce timings (module level so a test can shorten them)
# ---------------------------------------------------------------------------

# Commands (a summon, a command word, a palette tap) are answered at once —
# the owner's rule (2026-09-05): "15 seconds of quiet is for scheduled
# reports, not for the command reply". The wait-for-quiet machinery below
# stays for the phase 2 slot digest, which piggybacks on reception's report
# burst and must never race it.
COMMAND_QUIET_SECONDS = 0.0
SLOT_QUIET_SECONDS = 15.0
MAX_WAIT_SECONDS = 45.0
# Photo acknowledgements (owner request 2026-09-06, phase 3 addendum): several
# images from one send arrive as separate webhook events a couple of seconds
# apart, so the ack line waits this long for quiet before going out — capped,
# like every other pending reply, by MAX_WAIT_SECONDS above.
PHOTO_ACK_QUIET_SECONDS = 3.0
# The drain loop never sleeps longer than this in one go, so a command that
# lands in ANOTHER chat with a nearer deadline is at most this late.
DRAIN_SLICE_SECONDS = 1.0


def quiet_seconds_for(source_type: str) -> float:
    """Quiet time before a COMMAND reply — zero everywhere, see above."""
    del source_type  # one rule for groups, rooms and 1:1
    return COMMAND_QUIET_SECONDS


# ---------------------------------------------------------------------------
# Slot digest — the four daily windows (phase 2)
# ---------------------------------------------------------------------------

# Inclusive start, EXCLUSIVE end, Bangkok wall clock. 09:59:59 is still the
# morning slot; 10:00:00 is no slot at all. The windows are the owner's
# (2026-09-05): they sit where reception is already reporting.
@dataclass(frozen=True)
class Slot:
    """One daily window: ``[start, end)`` in Bangkok local time."""

    slot_id: str
    label: str
    start_second: int   # seconds from Bangkok midnight, inclusive
    end_second: int     # seconds from Bangkok midnight, exclusive

    @property
    def late_second(self) -> int:
        """When rule (b) opens: the last LATE_TRIGGER_SECONDS of the window."""
        return self.end_second - LATE_TRIGGER_SECONDS


def _hm(hour: int, minute: int = 0) -> int:
    return hour * 3600 + minute * 60


# The last stretch of a window in which ANY message triggers the digest —
# including one from a sender with no userId (LINE for PC), who can never be
# resolved to a reception grant. Without this a quiet-until-late window would
# be skipped even though the group is plainly awake.
LATE_TRIGGER_SECONDS = 30 * 60

SLOTS: Tuple[Slot, ...] = (
    Slot("morning", "เช้า", _hm(6), _hm(10)),
    Slot("noon", "เที่ยง", _hm(12), _hm(14)),
    Slot("afternoon", "บ่าย", _hm(14, 30), _hm(16, 30)),
    Slot("night", "ค่ำ", _hm(19, 30), _hm(21, 30)),
)

SLOTS_BY_ID: Dict[str, Slot] = {slot.slot_id: slot for slot in SLOTS}

# The one line that tells the group this digest arrived on a schedule rather
# than because somebody asked. Plain Thai, no emoji, like everything else.
SLOT_DIGEST_PREFIX = "สรุปงานซ่อมค้างประจำรอบ{label}"

# The app grant whose holder's first message opens a slot: reception is the
# one role reliably at a screen in every window, and their report burst is
# exactly the traffic this digest is meant to ride.
RECEPTION_APP_ID = "reception"

TRIGGER_RECEPTION = "reception"
TRIGGER_LATE = "late"
# Not a trigger anybody can cause on purpose: the mark a plain งานค้าง command
# leaves behind when its digest lands inside an unmarked window, so the slot
# does not post a near-duplicate a minute later.
TRIGGER_COMMAND = "command"

STATE_PENDING = "pending"
STATE_SENT = "sent"

# A 'pending' older than this was filed by a process that died mid-debounce:
# nothing will ever send it, so it is deleted and the window re-opens. Chosen
# above MAX_WAIT_SECONDS (45 s) with room to spare — a live pending can never
# be this old.
STALE_PENDING_SECONDS = 120.0

# (group_id, bkk_date, slot_id) — the primary key of a slot mark, carried on a
# pending reply so the send outcome knows which row to promote or delete.
SlotRef = Tuple[str, str, str]


def bangkok_moment(timestamp_ms) -> Optional[datetime]:
    """LINE's event ``timestamp`` (epoch ms, UTC) as Bangkok local time.

    None for anything that is not a usable epoch — an event we cannot place on
    the clock is an event that cannot open a slot.
    """
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc).astimezone(
            BANGKOK_TZ
        )
    except (OverflowError, OSError, ValueError):
        return None


def _second_of_day(moment: datetime) -> int:
    return moment.hour * 3600 + moment.minute * 60 + moment.second


def slot_for_moment(moment: Optional[datetime]) -> Optional[Slot]:
    """The slot this Bangkok datetime falls in, or None between windows."""
    if moment is None:
        return None
    second = _second_of_day(moment)
    for slot in SLOTS:
        if slot.start_second <= second < slot.end_second:
            return slot
    return None


def slot_ref_for_event(group_id: str, timestamp_ms) -> Optional[SlotRef]:
    """``(group_id, 'YYYY-MM-DD', slot_id)`` for an event, or None.

    The date is the BANGKOK calendar date of the event, never UTC's — a
    19:30-21:30 window would otherwise straddle two dates every night.
    """
    if not group_id:
        return None
    moment = bangkok_moment(timestamp_ms)
    slot = slot_for_moment(moment)
    if slot is None:
        return None
    return (group_id, moment.strftime("%Y-%m-%d"), slot.slot_id)


# ---------------------------------------------------------------------------
# Text hygiene
# ---------------------------------------------------------------------------

# Pictographs, dingbats, variation selectors and the ZWJ that glues emoji
# sequences together. Human-typed text (a แจ้งซ่อม detail) is the only thing
# that can carry them into a bot message, and the house rule is that bot
# messages are plain Thai operational text.
_PICTOGRAPH_PATTERN = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emoticons, pictographs, transport, symbols
    "\U0001FB00-\U0001FBFF"   # legacy computing symbols
    "\u2300-\u23FF"           # misc technical (watch, hourglass, keycaps)
    "\u2460-\u24FF"           # enclosed alphanumerics (the circled M etc.)
    "\u25A0-\u27BF"           # geometric shapes, misc symbols, dingbats
    "\u2B00-\u2BFF"           # misc symbols and arrows
    "\u2122\u2139\u3030\u303D\u3297\u3299\u00A9\u00AE"
    "\uFE0F"                  # variation selector-16 (emoji presentation)
    "\u200D"                  # zero-width joiner (glues emoji sequences)
    "\u20E3"                  # combining enclosing keycap
    "]+"
)


def strip_pictographs(text: Optional[str]) -> str:
    """Remove emoji/pictographs and collapse the whitespace they leave."""
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", _PICTOGRAPH_PATTERN.sub("", text)).strip()


# ---------------------------------------------------------------------------
# Summon grammar
# ---------------------------------------------------------------------------

def _word_command(words: str) -> Tuple[str, str, Optional[int]]:
    """(command, report_text, order_id) for a stripped remainder of speech.

    Exact-word commands (digest/requests/mine) are checked before the
    สถานะ/งาน <id> match and the แจ้งซ่อม PREFIX check, so "แจ้งซ่อมค้าง" (a
    digest word that happens to start with the report prefix) and
    "งานของฉัน" (which happens to start with งาน) are never mistaken for
    something else. ``report_text`` is only ever non-empty for
    :data:`COMMAND_REPORT`; ``order_id`` only ever set for
    :data:`COMMAND_STATUS` — every other command ignores both.
    """
    stripped = words.strip()
    if stripped in REQUEST_WORDS:
        return COMMAND_REQUESTS, "", None
    if stripped in DIGEST_WORDS:
        return COMMAND_DIGEST, "", None
    if stripped == MINE_WORD:
        return COMMAND_MINE, "", None
    status_match = _STATUS_WORD_PATTERN.match(stripped)
    if status_match:
        return COMMAND_STATUS, "", int(status_match.group(1))
    addphoto_match = _ADDPHOTO_WORD_PATTERN.match(stripped)
    if addphoto_match:
        return COMMAND_ADDPHOTO, "", int(addphoto_match.group(1))
    if stripped == REPORT_WORD or stripped.startswith(REPORT_WORD):
        return COMMAND_REPORT, stripped[len(REPORT_WORD):].strip(), None
    return COMMAND_PALETTE, "", None


def command_for_words(words: str) -> str:
    """Map what was said to a command. Anything unrecognised opens the palette."""
    return _word_command(words)[0]


# ---------------------------------------------------------------------------
# Ticket categories (phase 3)
# ---------------------------------------------------------------------------

CATEGORY_AIRCON = "aircon"
CATEGORY_TV = "tv"
CATEGORY_PLUMBING = "plumbing"
CATEGORY_ELECTRIC = "electric"
CATEGORY_FURNITURE = "furniture"
CATEGORY_OTHER = "other"

# Priority order for both keyword matching (first match wins) and the fixcat
# quick-reply chips.
CATEGORY_ORDER: Tuple[str, ...] = (
    CATEGORY_AIRCON, CATEGORY_TV, CATEGORY_PLUMBING,
    CATEGORY_ELECTRIC, CATEGORY_FURNITURE, CATEGORY_OTHER,
)
CATEGORY_SET = frozenset(CATEGORY_ORDER)

CATEGORY_LABELS: Dict[str, str] = {
    CATEGORY_AIRCON: "แอร์",
    CATEGORY_TV: "ทีวี",
    CATEGORY_PLUMBING: "ประปา",
    CATEGORY_ELECTRIC: "ไฟฟ้า",
    CATEGORY_FURNITURE: "เฟอร์นิเจอร์",
    CATEGORY_OTHER: "อื่นๆ",
}

# Keyword -> category, checked in this exact priority order (first category
# with a hit wins) — the owner's list, verbatim.
_CATEGORY_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (CATEGORY_AIRCON, ("แอร์", "aircon", "คอมเพรสเซอร์")),
    (CATEGORY_TV, ("ทีวี", "tv", "รีโมท")),
    (CATEGORY_PLUMBING, ("น้ำ", "ท่อ", "ฝักบัว", "ชักโครก", "ส้วม", "อ่าง", "ก๊อก", "รั่ว", "ตัน", "ประปา")),
    (CATEGORY_ELECTRIC, ("ไฟ", "หลอด", "ปลั๊ก", "สวิตช์", "สวิทช์", "ไฟฟ้า", "เบรกเกอร์")),
    (CATEGORY_FURNITURE, ("เตียง", "ตู้", "เก้าอี้", "โต๊ะ", "ผ้าม่าน", "ประตู", "ลิ้นชัก", "กระจก", "เฟอร์นิเจอร์")),
)


def categorize(text: str) -> str:
    """The first category (in priority order) whose keyword appears in text."""
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return CATEGORY_OTHER


# Area word -> common_area value, checked in this order (first hit wins).
_AREA_KEYWORDS: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("ล็อบบี้", "ล็อบบี", "lobby"), "lobby"),
    (("ทางเดิน", "โถง"), "corridor"),
    (("สระ",), "pool"),
    (("ครัว",), "kitchen"),
    (("ซักรีด", "ซักผ้า"), "laundry"),
    (("ด้านนอก", "ข้างนอก", "ลานจอด", "ที่จอดรถ", "สวน"), "outside"),
)


def _detect_area(text: str) -> Optional[str]:
    for keywords, area in _AREA_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return area
    return None


# A bare 3-4 digit token, optionally preceded by ห้อง — "204", "1204" and
# "ห้อง 204" all match; \b on both ends means a run of 5+ digits never
# matches a 3-4 digit substring of itself.
# No \b: Thai letters are \w too, so "ห้อง204แอร์เสีย" (a plausible fat-finger
# LINE message) has no word boundary around 204. Digit look-arounds instead.
_ROOM_TOKEN_PATTERN = re.compile(r"(?:ห้อง\s*)?(?<!\d)(\d{3,4})(?!\d)")

PARSE_ERROR_NO_ROOM_TEXT = (
    "ยังไม่รู้ว่าห้องไหนค่ะ พิมพ์ใหม่พร้อมเลขห้อง เช่น แจ้งซ่อม 204 แอร์ไม่เย็น"
)

# The two location_kind values housekeeping's work-order route accepts
# (housekeeping's LOCATION_KINDS enum is ["room", "common"] — verified
# against src/shared/types.ts / api.ts's isLocationKind in the
# housekeeping-phase34 worktree), paired with the field that carries the
# value (room_no / common_area).
LOCATION_KIND_ROOM = "room"
LOCATION_KIND_COMMON_AREA = "common"

_DETAIL_MAX_CHARS = 200


@dataclass(frozen=True)
class ReportDraft:
    """A parsed แจ้งซ่อม message, ready for housekeeping_client.create_work_order."""

    location_kind: str
    room_no: Optional[str] = None
    common_area: Optional[str] = None
    category: str = CATEGORY_OTHER
    urgent: bool = False
    detail_text: Optional[str] = None


@dataclass(frozen=True)
class ParseError:
    """แจ้งซ่อม text with neither a room number nor a recognised area word."""

    message: str = PARSE_ERROR_NO_ROOM_TEXT


def parse_report(text: str) -> Union[ReportDraft, ParseError]:
    """The text after แจ้งซ่อม -> a :class:`ReportDraft`, or a Thai
    :class:`ParseError` when no room and no area can be found.

    Room wins over area when both could apply (a room number is the more
    specific signal). ``urgent`` and ``category`` are read off the FULL
    original text; ``detail_text`` is the text with only the room token (and
    its optional ห้อง prefix) removed, pictographs stripped, collapsed
    whitespace, capped at 200 chars — empty after all that becomes None.
    """
    original = text or ""

    match = _ROOM_TOKEN_PATTERN.search(original)
    room_no: Optional[str] = None
    remainder = original
    if match:
        room_no = match.group(1)
        remainder = original[:match.start()] + original[match.end():]

    common_area: Optional[str] = None
    if room_no is None:
        common_area = _detect_area(original)
        if common_area is None:
            return ParseError()

    detail_text = strip_pictographs(remainder)
    if len(detail_text) > _DETAIL_MAX_CHARS:
        detail_text = detail_text[:_DETAIL_MAX_CHARS]

    return ReportDraft(
        location_kind=LOCATION_KIND_ROOM if room_no is not None else LOCATION_KIND_COMMON_AREA,
        room_no=room_no,
        common_area=common_area,
        category=categorize(original),
        urgent="ด่วน" in original,
        detail_text=detail_text or None,
    )


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoutedCommand:
    """A command to answer, once the chat goes quiet."""

    chat_key: str
    command: str
    reply_token: str
    quiet_seconds: float
    event_type: str
    source_type: str
    # The slot mark this reply may promote to 'sent' — set for a slot digest
    # (the mark it filed) and for a plain command in a group that lands inside
    # an open window (rule 7: a งานค้าง answer covers the slot, so the slot
    # must not post a near-duplicate afterwards). None everywhere else.
    slot_ref: Optional[SlotRef] = None

    # --- phase 3 (ticket intake) additions -----------------------------
    # The SENDER's LINE userId — chat_key already IS this in a 1:1, but a
    # group/room command needs it separately to key the photo buffer/attach
    # window and to resolve identity. "" for anything phase 1/2 never
    # populated it for (never read outside TICKET_COMMANDS).
    user_id: str = ""
    # แจ้งซ่อม's free text (COMMAND_REPORT only); postback's id=/cat=; a
    # text-typed 'สถานะ <id>' / 'งาน <id>' (COMMAND_STATUS) sets order_id the
    # same way a postback would.
    report_text: str = ""
    order_id: Optional[int] = None
    category: Optional[str] = None
    # Reply-to-media (2026-09-06): the LINE message id this event QUOTED
    # (``message.quotedMessageId``), or "" when it was not a reply. Only ever
    # meaningful on COMMAND_REPORT and COMMAND_ADDPHOTO — see
    # _create_ticket/_addphoto_with_quote.
    quoted_message_id: str = ""
    # Resolved once, at route time (handle_event_detail has the db session;
    # by the time a debounced reply fires — up to 45 s later — that session
    # is long closed). identity_known False means NOT_LINKED_TEXT is the
    # whole of the reply; badge/display_name/property/is_reception are only
    # meaningful when it is True. Defaults suit every non-ticket command,
    # which never looks at these fields at all.
    identity_known: bool = True
    badge: str = ""
    display_name: str = ""
    property: str = ""
    is_reception: bool = False


@dataclass(frozen=True)
class RoutedMessage:
    """Not a command — it only refreshes a pending reply's token/timer.

    Deliberately carries no text and no sender: this is what the bot is
    allowed to know about ordinary staff chat.
    """

    chat_key: str
    reply_token: str


Routed = Union[RoutedCommand, RoutedMessage]


def _chat_key(source: Dict) -> str:
    """The debounce key: groupId / roomId, or the userId in a 1:1 chat."""
    source_type = source.get("type")
    if source_type == "group":
        return source.get("groupId") or ""
    if source_type == "room":
        return source.get("roomId") or ""
    return source.get("userId") or ""


# Group/room @mention exception (owner, 2026-09-06 evening): a self-mention
# lets a group message become the one command carve-out, COMMAND_REPORT.
def _self_mention_span(message: Dict) -> Optional[Tuple[int, int]]:
    """The (index, length) of the bot's OWN mention in a text message's
    ``mention.mentionees[]`` (LINE's ``isSelf: true`` flag), or None when
    there is none — no mention object, an empty/malformed mentionees list, or
    no entry with ``isSelf`` true. Both numbers are LINE's own UTF-16 CODE
    UNIT offsets (see :func:`_strip_utf16_span`), never Python string
    indices. The first isSelf entry wins; LINE never sends more than one."""
    mention = message.get("mention")
    if not isinstance(mention, dict):
        return None
    mentionees = mention.get("mentionees")
    if not isinstance(mentionees, list):
        return None
    for mentionee in mentionees:
        if not isinstance(mentionee, dict) or mentionee.get("isSelf") is not True:
            continue
        index, length = mentionee.get("index"), mentionee.get("length")
        if isinstance(index, int) and isinstance(length, int) and index >= 0 and length >= 0:
            return index, length
    return None


def _strip_utf16_span(text: str, index: int, length: int) -> str:
    """``text`` with the UTF-16 code-unit span ``[index, index+length)``
    removed — the mention itself, leaving the words around it.

    LINE's mention ``index``/``length`` count UTF-16 CODE UNITS, not Python
    characters: a supplementary-plane character (many emoji) is ONE Python
    character but TWO UTF-16 units, so a plain ``text[:index] + text[index+length:]``
    slice drifts as soon as such a character appears anywhere before the
    mention. Round-tripping through UTF-16LE bytes (a fixed 2 bytes per code
    unit, surrogate pairs included) keeps the offsets exact regardless of
    what came before. A span LINE never actually sends (out of range,
    reversed) leaves the text unchanged rather than raising or mangling it.
    """
    units = text.encode("utf-16-le")
    start, end = index * 2, (index + length) * 2
    if start < 0 or end > len(units) or start > end:
        return text
    try:
        return (units[:start] + units[end:]).decode("utf-16-le")
    except UnicodeDecodeError:
        return text


def route_event(
    event: Dict,
    is_known_user: Callable[[str], bool],
) -> Optional[Routed]:
    """Decide what ONE webhook event means. Pure: no I/O, no logging.

    Returns a :class:`RoutedCommand` (answer this), a :class:`RoutedMessage`
    (chat noise that still refreshes a pending reply) or None (ignore, and do
    not log).
    """
    if not isinstance(event, dict):
        return None
    source = event.get("source")
    if not isinstance(source, dict):
        return None
    source_type = source.get("type") or ""
    chat_key = _chat_key(source)
    event_type = event.get("type")
    reply_token = event.get("replyToken") or ""

    if event_type == "join":
        # Learn the group id — the ONLY thing this event is good for, and the
        # one time the bot writes an id into the log on purpose (the rollout
        # needs it). Logged by the caller; nothing is answered.
        return None

    sender_user_id = source.get("userId") or ""

    if event_type == "postback":
        if not chat_key or not reply_token:
            return None
        if source_type in ("group", "room"):
            # GROUP/ROOM SOURCES ARE REPORT-ONLY (owner policy 2026-09-06): a
            # postback from an old confirmation bubble is never turned into a
            # command there any more — see handle_event_detail for the DEBUG
            # log this drop produces.
            return None
        parsed = _parse_postback(event.get("postback"))
        if parsed is None:
            return None
        return RoutedCommand(
            chat_key=chat_key, command=parsed.command, reply_token=reply_token,
            quiet_seconds=quiet_seconds_for(source_type),
            event_type="postback", source_type=source_type,
            user_id=sender_user_id,
            order_id=parsed.order_id, category=parsed.category,
        )

    if event_type != "message":
        return None
    if not chat_key or not reply_token:
        return None

    message = event.get("message")

    if source_type in ("group", "room"):
        # GROUP/ROOM SOURCES ARE REPORT-ONLY (owner policy 2026-09-06: "command
        # through chat is considered spam") — WITH ONE EXCEPTION (owner,
        # 2026-09-06 evening: "HF Family should be able to get mention and act
        # to create new maintenance ticket still"). An explicit @-mention of
        # the bot (``message.mention.mentionees[]`` carries ``isSelf: true``)
        # whose remainder — the mention span stripped — is แจ้งซ่อม (bare or
        # with a room/symptom) is routed as COMMAND_REPORT, exactly like the
        # 1:1 form. Any other mention remainder (empty, งานค้าง, anything
        # else) and every non-mentioned message — text (summoned or bare, any
        # word) or media alike — stay a plain RoutedMessage: only a candidate
        # for the slot heartbeat (_maybe_file_slot_digest, driven by
        # handle_event_detail from this same RoutedMessage), never a command.
        # See handle_event_detail for the DEBUG log a non-command produces.
        if isinstance(message, dict) and message.get("type") == "text":
            span = _self_mention_span(message)
            if span is not None:
                remainder = _strip_utf16_span(message.get("text") or "", *span).strip()
                if remainder == REPORT_WORD or remainder.startswith(REPORT_WORD):
                    return RoutedCommand(
                        chat_key=chat_key, command=COMMAND_REPORT,
                        reply_token=reply_token,
                        quiet_seconds=quiet_seconds_for(source_type),
                        event_type="message", source_type=source_type,
                        user_id=sender_user_id,
                        report_text=remainder[len(REPORT_WORD):].strip(),
                        quoted_message_id=message.get("quotedMessageId") or "",
                    )
        return RoutedMessage(chat_key=chat_key, reply_token=reply_token)

    if not isinstance(message, dict) or message.get("type") != "text":
        # A photo/sticker/anything else is still a message in this chat, so
        # it restarts the quiet timer — it just never becomes a command.
        return RoutedMessage(chat_key=chat_key, reply_token=reply_token)

    text = message.get("text") or ""
    # Reply-to-media (2026-09-06): LINE carries the quoted message's id here
    # when this text event was a reply to an earlier message. "" when it was
    # not a reply — see RoutedCommand.quoted_message_id.
    quoted_message_id = message.get("quotedMessageId") or ""

    # 1:1 only from here (group/room already returned above). Reads are open
    # but the bot only talks to people it knows; a stranger gets the
    # onboarding pointer instead of a menu.
    if not is_known_user(chat_key):
        return RoutedCommand(
            chat_key=chat_key, command=COMMAND_ONBOARDING,
            reply_token=reply_token,
            quiet_seconds=quiet_seconds_for(source_type),
            event_type="message", source_type=source_type,
        )
    command, report_text, order_id = _word_command(text)
    return RoutedCommand(
        chat_key=chat_key, command=command,
        reply_token=reply_token,
        quiet_seconds=quiet_seconds_for(source_type),
        event_type="message", source_type=source_type,
        user_id=chat_key, report_text=report_text, order_id=order_id,
        quoted_message_id=quoted_message_id,
    )


@dataclass(frozen=True)
class _ParsedPostback:
    command: str
    order_id: Optional[int] = None
    category: Optional[str] = None


# Every postback ``cmd=`` value the bot understands. An unlisted value (or a
# malformed id/cat on one that needs it) is ignored outright — the same
# "unrecognised postback is silence, not an error" rule phase 1 already had.
_KNOWN_POSTBACK_COMMANDS = frozenset({
    COMMAND_PALETTE, COMMAND_DIGEST, COMMAND_REQUESTS,
}) | TICKET_COMMANDS


def _parse_postback(postback) -> Optional[_ParsedPostback]:
    """``cmd=...`` (+ ``id=``/``cat=`` for the ticket ones) out of a
    postback's urlencoded data."""
    if not isinstance(postback, dict):
        return None
    data = postback.get("data")
    if not isinstance(data, str) or not data:
        return None
    values = parse_qs(data)
    command = (values.get("cmd") or [""])[0]
    if command not in _KNOWN_POSTBACK_COMMANDS:
        return None

    order_id: Optional[int] = None
    if "id" in values:
        raw_id = (values.get("id") or [""])[0]
        try:
            order_id = int(raw_id)
        except (TypeError, ValueError):
            return None
    if command in TICKET_ORDER_POSTBACKS and order_id is None:
        return None

    category: Optional[str] = None
    if "cat" in values:
        raw_category = (values.get("cat") or [""])[0]
        if raw_category not in CATEGORY_SET:
            return None
        category = raw_category
    if command == COMMAND_SETCAT and category is None:
        return None

    return _ParsedPostback(command=command, order_id=order_id, category=category)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def palette_message() -> Dict:
    """The Flex palette bubble: one title, one line, one button."""
    return {
        "type": "flex",
        "altText": PALETTE_ALT_TEXT,
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": PALETTE_TITLE,
                     "weight": "bold", "size": "lg"},
                ],
            },
            "body": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {"type": "text", "text": PALETTE_BODY, "wrap": True},
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical",
                "contents": [
                    {
                        "type": "button", "style": "primary",
                        "action": {
                            "type": "postback",
                            "label": PALETTE_BUTTON_LABEL,
                            "data": f"cmd={COMMAND_DIGEST}",
                            "displayText": PALETTE_BUTTON_DISPLAY_TEXT,
                        },
                    },
                    {
                        "type": "button", "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": PALETTE_REQUESTS_BUTTON_LABEL,
                            "data": f"cmd={COMMAND_REQUESTS}",
                            "displayText": PALETTE_REQUESTS_BUTTON_DISPLAY_TEXT,
                        },
                    },
                    {
                        "type": "button", "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": PALETTE_REPORT_BUTTON_LABEL,
                            "data": f"cmd={COMMAND_REPORT_HELP}",
                            "displayText": PALETTE_REPORT_BUTTON_DISPLAY_TEXT,
                        },
                    },
                    {
                        "type": "button", "style": "secondary",
                        "action": {
                            "type": "postback",
                            "label": PALETTE_MINE_BUTTON_LABEL,
                            "data": f"cmd={COMMAND_MINE}",
                            "displayText": PALETTE_MINE_BUTTON_DISPLAY_TEXT,
                        },
                    },
                ],
            },
        },
    }


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_generated_at(raw) -> Optional[datetime]:
    """Housekeeping's ``generatedAt`` as a Bangkok-local datetime, or None."""
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BANGKOK_TZ)
    return parsed.astimezone(BANGKOK_TZ)


def format_stamp(moment: datetime) -> str:
    """'5 ก.ย. 15:10' — the Thai date/time stamp every digest carries."""
    month = THAI_MONTH_ABBREVIATIONS[moment.month - 1]
    return f"{moment.day} {month} {moment:%H:%M}"


def _age_text(age_days: int) -> str:
    return "วันนี้" if age_days <= 0 else f"{age_days} วัน"


def _order_line(order: Dict) -> str:
    location = strip_pictographs(order.get("location"))
    category = strip_pictographs(order.get("category"))
    detail = strip_pictographs(order.get("detail")) or category
    status_label = strip_pictographs(order.get("statusLabel"))
    head = " ".join(part for part in (location, category) if part)
    prefix = "ด่วน " if order.get("urgent") else ""
    parts = [part for part in (head, detail, _age_text(_as_int(order.get("ageDays"))), status_label) if part]
    return prefix + " · ".join(parts)


def _fit(lines: List[str]) -> str:
    """Join lines, dropping trailing rows rather than overrunning LINE's cap."""
    text = "\n".join(lines)
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    suffix = "\nแสดงไม่ครบ"
    kept = list(lines)
    while kept and len("\n".join(kept)) + len(suffix) > MAX_MESSAGE_CHARS:
        kept.pop()
    return "\n".join(kept) + suffix


def render_digest(payload: Optional[Dict], now: Optional[datetime] = None) -> str:
    """The งานซ่อมค้าง digest text for the housekeeping JSON.

    ``None`` (dark token, timeout, 401/503, malformed body — see
    housekeeping_client.fetch_digest) renders the one fixed Thai line: staff
    are told the system is not connected, never given a status code and never
    left guessing at silence.
    """
    if not isinstance(payload, dict):
        return DIGEST_UNAVAILABLE_TEXT

    properties = payload.get("properties")
    if not isinstance(properties, list):
        properties = []
    properties = [item for item in properties if isinstance(item, dict)]

    moment = (
        _parse_generated_at(payload.get("generatedAt"))
        or (now.astimezone(BANGKOK_TZ) if now else datetime.now(BANGKOK_TZ))
    )
    stamp = format_stamp(moment)

    total = sum(_as_int(item.get("openCount")) for item in properties)
    if total <= 0:
        return f"ไม่มีงานซ่อมค้าง ({stamp})"

    lines: List[str] = [f"งานซ่อมค้าง {total} งาน ({stamp})"]
    for item in properties:
        open_count = _as_int(item.get("openCount"))
        if open_count <= 0:
            # A property with nothing open is left out entirely; a digest that
            # listed "HF Ville (0)" every time would train people to skim.
            continue
        label = strip_pictographs(item.get("label")) or str(item.get("property") or "")
        lines.append("")
        lines.append(f"{label} ({open_count})")
        orders = item.get("orders")
        if isinstance(orders, list):
            for order in orders:
                if isinstance(order, dict):
                    lines.append(_order_line(order))
        truncated = _as_int(item.get("truncated"))
        if truncated > 0:
            lines.append(f"และอีก {truncated} งาน")
    return _fit(lines)


def _feedback_kind_label(kind) -> str:
    """praise/issue/request -> Thai label; any other kind -> its raw value
    (guest-feedback contract §15.7: "map any other kind to its raw value")."""
    if isinstance(kind, str) and kind in FEEDBACK_KIND_LABELS:
        return FEEDBACK_KIND_LABELS[kind]
    return str(kind) if kind is not None else ""


def _feedback_branch_label(branch) -> str:
    """hf/hfville -> "HF"/"HF Ville" (matches guest-feedback's own
    src/shared/locations.ts branchShort); any other value -> itself."""
    if isinstance(branch, str) and branch in FEEDBACK_BRANCH_LABELS:
        return FEEDBACK_BRANCH_LABELS[branch]
    return branch if isinstance(branch, str) else ""


def _feedback_short_text(item: Dict) -> str:
    """The tag words and the guest's own comment, pictographs stripped and
    capped at :data:`FEEDBACK_LINE_TEXT_MAX_CHARS` — the item's ``tagsTh``
    (already Thai-labelled by guest-feedback) joined by ", ", plus an
    optional quoted comment, mirroring guest-feedback's own itemLine
    (src/server/line.ts) without the branch/location/time it already carries
    elsewhere in this line."""
    tags = item.get("tagsTh")
    tags_text = ", ".join(t for t in tags if isinstance(t, str)) if isinstance(tags, list) else ""
    comment = item.get("comment")
    comment_text = comment.strip() if isinstance(comment, str) else ""
    if tags_text and comment_text:
        combined = f'{tags_text} — "{comment_text}"'
    else:
        combined = tags_text or comment_text
    combined = strip_pictographs(combined)
    return combined[:FEEDBACK_LINE_TEXT_MAX_CHARS]


def _feedback_item_line(item: Dict) -> str:
    """'<ด่วน ><kind label> · <branch/room or area> · <short text>' — one
    pending guest-feedback row (§15.7 rev 3.1 consolidation, 2026-09-06)."""
    kind_label = _feedback_kind_label(item.get("kind"))
    branch_label = _feedback_branch_label(item.get("branch"))
    location = item.get("locationLabelTh")
    location_text = " ".join(
        part for part in (branch_label, location if isinstance(location, str) else "") if part
    )
    short_text = _feedback_short_text(item)
    line = " · ".join(part for part in (kind_label, location_text, short_text) if part)
    return f"ด่วน {line}" if item.get("urgent") else line


def render_feedback_section(payload: Optional[Dict]) -> Optional[str]:
    """Section (b) of the report — 'ความคิดเห็นลูกค้า (n รายการ)' plus one line
    per pending item, capped at :data:`FEEDBACK_SECTION_LINE_CAP` lines then
    'และอีก m รายการ' — or None when there is nothing to show: guest-feedback
    dark/unreachable (``payload`` not a dict) or reachable with zero pending.
    None is a real answer here, not a miss: :func:`render_slot_digest` omits
    the section entirely on it (a scheduled report must not carry a "none"
    line), while :func:`render_requests` (the 1:1 preview) maps it to its own
    fixed unavailable/none text instead.
    """
    if not isinstance(payload, dict):
        return None
    count = _as_int(payload.get("count"))
    if count <= 0:
        return None
    raw_items = payload.get("items")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    shown = items[:FEEDBACK_SECTION_LINE_CAP]
    lines = [FEEDBACK_SECTION_HEADER_FMT.format(n=count)]
    lines.extend(_feedback_item_line(item) for item in shown)
    remaining = count - len(shown)
    if remaining > 0:
        lines.append(f"และอีก {remaining} รายการ")
    return "\n".join(lines)


def render_slot_digest(
    slot_id: str, payload: Optional[Dict], feedback_payload: Optional[Dict] = None,
) -> Optional[str]:
    """The slot REPORT text (consolidated 2026-09-06), or None when there is
    nothing to post.

    Two sections, either or both present: (a) the existing maintenance
    digest, unchanged text, under the "สรุปงานซ่อมค้างประจำรอบ..." line — only
    when housekeeping actually answered; (b) :func:`render_feedback_section`
    — only when guest-feedback has something pending. Housekeeping dark AND
    feedback dark/empty is the only case with nothing at all to say: None is
    the whole of that rule — a digest somebody ASKED for says
    "ระบบงานซ่อมยังไม่เชื่อมต่อ ..." (they are owed an answer), but a scheduled
    post nobody asked for stays silent rather than dropping an error line
    into HF Family every window; a scheduled post that DOES have real content
    (feedback pending even while housekeeping is dark) must still go out,
    with only the section that has something to say. The caller deletes the
    slot mark when this returns None, so the window re-triggers on the next
    message. The combined text is still capped at LINE's message limit via
    :func:`_fit`, same as the maintenance section always was on its own.
    """
    slot = SLOTS_BY_ID.get(slot_id or "")
    if slot is None:
        return None
    sections: List[str] = []
    if isinstance(payload, dict):
        sections.append(SLOT_DIGEST_PREFIX.format(label=slot.label) + "\n\n" + render_digest(payload))
    feedback_section = render_feedback_section(feedback_payload)
    if feedback_section is not None:
        sections.append(feedback_section)
    if not sections:
        return None
    return _fit("\n\n".join(sections).split("\n"))


# ---------------------------------------------------------------------------
# Identity (phase 3) — resolved once, at route time, onto the RoutedCommand
# ---------------------------------------------------------------------------

# Employee.location -> housekeeping's property code. Unset/unrecognised
# location defaults to "hf" (the switchprop button gets it to hfville from
# there if that is wrong for this sender).
_PROPERTY_FOR_LOCATION: Dict[str, str] = {"HF": "hf", "HF_VILLE": "hfville"}


@dataclass(frozen=True)
class EmployeeIdentity:
    badge: str
    display_name: str
    property: str


def resolve_employee_identity(db: Session, line_user_id: str) -> Optional[EmployeeIdentity]:
    """The ACTIVE employee behind this LINE account, or None (a stranger)."""
    if not line_user_id:
        return None
    employee = (
        db.query(Employee)
        .filter(Employee.line_user_id == line_user_id, Employee.is_active == True)  # noqa: E712
        .first()
    )
    if employee is None:
        return None
    return EmployeeIdentity(
        badge=employee.badge_number,
        display_name=employee.display_name,
        property=_PROPERTY_FOR_LOCATION.get(employee.location or "", "hf"),
    )


# ---------------------------------------------------------------------------
# Photo buffer + attach window (phase 3) — in-process only, no DB, no bytes
# ---------------------------------------------------------------------------

# Buffered as message ids ONLY (never downloaded) for this long; a ticket
# created after this claims nothing from an older photo.
PHOTO_BUFFER_TTL_SECONDS = 90.0
# create_work_order claims at most this many buffered photos.
PHOTO_BUFFER_MAX_CLAIM = 6
# An addphoto/create attach window: this long, refreshed by each photo it
# lets through, but never past the hard cap below.
ATTACH_WINDOW_SECONDS = 120.0
ATTACH_WINDOW_HARD_CAP_SECONDS = 300.0
# Photos-first (owner request 2026-09-06): the confirmation bubble waits for
# the just-claimed batch's uploads, bounded by this many seconds, before the
# reply goes out — see AsyncioBotDispatcher._await_claimed_uploads. Never
# extended past the reporting command's own reply-token life.
CLAIMED_UPLOAD_WAIT_SECONDS = 10.0


@dataclass(frozen=True)
class _BufferedPhoto:
    message_id: str
    at: float  # the injectable clock's reading when it arrived
    kind: str = "image"  # "image" | "video" (2026-09-06)


class PhotoBuffer:
    """Per-(chat_key, LINE userId) buffered image message ids.

    NOT bytes, not logged, and never read except by a ticket that claims
    them within :data:`PHOTO_BUFFER_TTL_SECONDS`. A non-linked sender's
    photos are never even offered to :meth:`add` — see
    :func:`_maybe_handle_photo` — so this class does not need to know about
    identity at all.

    ``add`` runs on the asyncio event-loop thread (from the webhook
    handler) while ``claim`` runs inside ``_create_ticket``, which executes
    on a real worker thread via ``asyncio.to_thread(build_reply, ...)``.
    Both are non-atomic read-modify-write sequences over the same
    per-(chat_key, user_id) slot, so a plain dict would let a photo arrive
    mid-claim and either be silently dropped or resurface against a later,
    unrelated ticket. A ``threading.Lock`` (not ``asyncio.Lock`` — the two
    callers are on different OS threads, not just different coroutines)
    serializes the whole read-modify-write on each call.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 ttl_seconds: float = PHOTO_BUFFER_TTL_SECONDS):
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._store: Dict[Tuple[str, str], List[_BufferedPhoto]] = {}
        self._lock = threading.Lock()

    def add(self, chat_key: str, user_id: str, message_id: str, kind: str = "image") -> None:
        key = (chat_key, user_id)
        with self._lock:
            now = self._clock()
            fresh = [p for p in self._store.get(key, []) if now - p.at <= self._ttl_seconds]
            fresh.append(_BufferedPhoto(message_id=message_id, at=now, kind=kind))
            self._store[key] = fresh

    def claim(self, chat_key: str, user_id: str,
              max_count: int = PHOTO_BUFFER_MAX_CLAIM) -> List[str]:
        """Pop up to ``max_count`` still-fresh buffered ids, oldest first.

        Ids only — see :meth:`claim_detailed` for the (id, kind) pairs a
        caller that needs to tell photos from videos apart (ticket creation)
        should use instead. Kept exactly as it was (plain id list) so every
        caller and test that only ever cared about ids is unaffected.
        """
        return [message_id for message_id, _kind in self.claim_detailed(chat_key, user_id, max_count)]

    def claim_detailed(self, chat_key: str, user_id: str,
                        max_count: int = PHOTO_BUFFER_MAX_CLAIM) -> List[Tuple[str, str]]:
        """Pop up to ``max_count`` still-fresh buffered (id, kind) pairs,
        oldest first — kind is "image" or "video"."""
        key = (chat_key, user_id)
        with self._lock:
            now = self._clock()
            fresh = [p for p in self._store.pop(key, []) if now - p.at <= self._ttl_seconds]
            return [(p.message_id, p.kind) for p in fresh[:max_count]]


@dataclass
class _AttachWindow:
    order_id: int
    expires_at: float
    hard_cap_at: float


class AttachWindowStore:
    """Per-(chat_key, LINE userId): which order id a just-arrived photo
    should attach to, and until when.

    ``open``/``refresh`` (from ``_create_ticket``, on the worker thread
    behind ``asyncio.to_thread(build_reply, ...)``) and ``active_order``
    (from the event-loop-thread webhook handler) each read-modify-write the
    same per-(chat_key, user_id) slot, so this needs the same
    ``threading.Lock`` protection as :class:`PhotoBuffer` and for the same
    reason — the two callers are genuinely different OS threads."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 window_seconds: float = ATTACH_WINDOW_SECONDS,
                 hard_cap_seconds: float = ATTACH_WINDOW_HARD_CAP_SECONDS):
        self._clock = clock
        self._window_seconds = window_seconds
        self._hard_cap_seconds = hard_cap_seconds
        self._store: Dict[Tuple[str, str], _AttachWindow] = {}
        self._lock = threading.Lock()

    def open(self, chat_key: str, user_id: str, order_id: int) -> None:
        """Open (or extend) the window for this order. Re-opening for the
        SAME order id extends the expiry without resetting the hard cap;
        opening for a DIFFERENT order id starts both clocks over."""
        with self._lock:
            self._open_locked(chat_key, user_id, order_id)

    def _open_locked(self, chat_key: str, user_id: str, order_id: int) -> None:
        key = (chat_key, user_id)
        now = self._clock()
        existing = self._store.get(key)
        if existing is not None and existing.order_id == order_id:
            hard_cap_at = existing.hard_cap_at
        else:
            hard_cap_at = now + self._hard_cap_seconds
        self._store[key] = _AttachWindow(
            order_id=order_id,
            expires_at=min(now + self._window_seconds, hard_cap_at),
            hard_cap_at=hard_cap_at,
        )

    def active_order(self, chat_key: str, user_id: str) -> Optional[int]:
        """The order id a photo now should attach to, or None (closed/expired)."""
        key = (chat_key, user_id)
        with self._lock:
            window = self._store.get(key)
            if window is None:
                return None
            now = self._clock()
            if now >= window.expires_at or now >= window.hard_cap_at:
                self._store.pop(key, None)
                return None
            return window.order_id

    def refresh(self, chat_key: str, user_id: str) -> Optional[int]:
        """A photo just arrived: extend the window (respecting the hard cap)
        and return the order id it belongs to, or None if none is open."""
        key = (chat_key, user_id)
        with self._lock:
            now = self._clock()
            window = self._store.get(key)
            if window is None:
                return None
            if now >= window.expires_at or now >= window.hard_cap_at:
                self._store.pop(key, None)
                return None
            order_id = window.order_id
            self._open_locked(chat_key, user_id, order_id)
            return order_id


_photo_buffer = PhotoBuffer()
_attach_windows = AttachWindowStore()


def get_photo_buffer() -> PhotoBuffer:
    """The process-wide photo buffer (a seam tests replace wholesale)."""
    return _photo_buffer


def get_attach_windows() -> AttachWindowStore:
    """The process-wide attach-window store (a seam tests replace wholesale)."""
    return _attach_windows


# ---------------------------------------------------------------------------
# Ticket rendering (phase 3)
# ---------------------------------------------------------------------------

def _flex_row(label: str, value: str) -> Dict:
    return {
        "type": "box", "layout": "baseline",
        "contents": [
            {"type": "text", "text": label, "size": "sm", "color": "#8C8C8C", "flex": 2},
            {"type": "text", "text": value, "size": "sm", "wrap": True, "flex": 5},
        ],
    }


def _postback_button(label: str, data: str, style: str = "secondary") -> Dict:
    return {
        "type": "button", "style": style,
        "action": {"type": "postback", "label": label, "data": data, "displayText": label},
    }


def _media_counts_text(photo_count: int, video_count: int) -> str:
    """'รูป k รูป · วิดีโอ v คลิป' — the settled counts row shared by the
    งานของฉัน/สถานะ bubble (:func:`_mine_bubble`) and, via
    :func:`_claimed_photo_line`, the confirmation bubble once a claimed
    batch's uploads have resolved. Omits a zero part; 'ยังไม่มีรูป' when both
    are zero (video support, 2026-09-06 — images and videos are counted
    separately everywhere)."""
    parts: List[str] = []
    if photo_count > 0:
        parts.append(f"รูป {photo_count} รูป")
    if video_count > 0:
        parts.append(f"วิดีโอ {video_count} คลิป")
    return " · ".join(parts) if parts else "ยังไม่มีรูป"


def _claiming_line(photo_count: int, video_count: int) -> str:
    """The confirmation bubble's 'รูป' row for a batch CLAIMED but not yet
    uploaded — 'กำลังแนบ 2 รูป', 'กำลังแนบ 1 คลิป', 'กำลังแนบ 2 รูป 1 คลิป', or
    'ยังไม่มีรูป' when nothing was claimed."""
    parts: List[str] = []
    if photo_count > 0:
        parts.append(f"{photo_count} รูป")
    if video_count > 0:
        parts.append(f"{video_count} คลิป")
    return f"กำลังแนบ {' '.join(parts)}" if parts else "ยังไม่มีรูป"


def _media_row_label(video_count: int) -> str:
    """The bubble/mine row label (cleanup, 2026-09-06 review): 'ไฟล์' when any
    video is present, else the original 'รูป'."""
    return "ไฟล์" if video_count > 0 else "รูป"


def build_confirmation_bubble(order: Dict, photo_count: int, video_count: int = 0) -> Dict:
    """The 'รับเรื่องแล้ว #N' Flex bubble, for a create OR any later edit.

    ``order`` is an OrderView (housekeeping already computed propertyLabel/
    location/categoryLabel — this function never re-derives them). Human text
    fields are stripped of pictographs on the way in, same as the digest.
    ``photo_count``/``video_count`` are the just-CLAIMED (not yet uploaded)
    counts at ticket creation; see :func:`_patch_confirmation_photo_line` for
    the settled-outcome rewrite once those uploads resolve.
    """
    order_id = order.get("id")
    title = f"รับเรื่องแล้ว #{order_id}"
    urgent = bool(order.get("urgent"))
    urgency_text = "ด่วน" if urgent else "ปกติ"
    toggle_label = "ไม่ด่วน" if urgent else "ด่วน"
    detail = strip_pictographs(order.get("detailText")) or "-"
    photo_line = _claiming_line(photo_count, video_count)

    return {
        "type": "flex",
        "altText": title,
        "contents": {
            "type": "bubble",
            "header": {
                "type": "box", "layout": "vertical",
                "contents": [{"type": "text", "text": title, "weight": "bold", "size": "lg"}],
            },
            "body": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": [
                    _flex_row("สาขา", strip_pictographs(order.get("propertyLabel"))),
                    _flex_row("ที่", strip_pictographs(order.get("location"))),
                    _flex_row("หมวด", strip_pictographs(order.get("categoryLabel"))),
                    {
                        "type": "text", "text": urgency_text, "size": "sm", "weight": "bold",
                        "color": "#D64545" if urgent else "#8C8C8C",
                    },
                    _flex_row("รายละเอียด", detail),
                    _flex_row("ผู้แจ้ง", strip_pictographs(order.get("reporterName"))),
                    _flex_row(_media_row_label(video_count), photo_line),
                ],
            },
            "footer": {
                "type": "box", "layout": "vertical", "spacing": "sm",
                "contents": [
                    _postback_button("แก้หมวด", f"cmd={COMMAND_FIXCAT}&id={order_id}"),
                    _postback_button(toggle_label, f"cmd={COMMAND_TOGGLEURGENT}&id={order_id}"),
                    _postback_button("เพิ่มรูป", f"cmd={COMMAND_ADDPHOTO}&id={order_id}"),
                    _postback_button("ยกเลิก", f"cmd={COMMAND_CANCEL}&id={order_id}"),
                    _postback_button("สลับสาขา", f"cmd={COMMAND_SWITCHPROP}&id={order_id}"),
                ],
            },
        },
    }


def _claimed_photo_line(
    photo_completed: int, photo_failed: int, photo_running: int,
    video_completed: int = 0, video_failed: int = 0, video_running: int = 0,
) -> str:
    """The confirmation bubble's 'รูป' row once the claimed batch's uploads
    have resolved (rule B) — completed/still-running/failed counts as of the
    bounded CLAIMED_UPLOAD_WAIT_SECONDS wait in AsyncioBotDispatcher._reply,
    photos and videos counted separately (video support, 2026-09-06).
    build_confirmation_bubble's OWN "กำลังแนบ..." (claimed-but-not-yet-
    uploaded) text is what every SYNCHRONOUS caller of build_reply/
    build_messages still sees — this only ever runs from that async wait, and
    only patches the message in place afterwards. A still-running count that
    is PURELY photos keeps the original "...N รูป" wording (unchanged from
    before video support); any video in the mix says "...N ไฟล์".
    """
    parts: List[str] = []
    if photo_completed > 0:
        parts.append(f"รูป {photo_completed} รูป")
    if video_completed > 0:
        parts.append(f"วิดีโอ {video_completed} คลิป")
    still_running = photo_running + video_running
    if still_running > 0:
        if photo_running > 0 and video_running == 0:
            parts.append(f"กำลังแนบอีก {photo_running} รูป")
        else:
            parts.append(f"กำลังแนบอีก {still_running} ไฟล์")
    if photo_failed > 0:
        parts.append(f"แนบไม่สำเร็จ {photo_failed} รูป")
    if video_failed > 0:
        parts.append(f"แนบวิดีโอไม่สำเร็จ {video_failed} คลิป")
    return " ".join(parts) if parts else "ยังไม่มีรูป"


def _patch_confirmation_photo_line(
    message: Dict,
    photo_completed: int, photo_failed: int, photo_running: int,
    video_completed: int = 0, video_failed: int = 0, video_running: int = 0,
) -> None:
    """Rewrite a just-built confirmation bubble's 'รูป' row in place (rule B).

    The row is always the last body item build_confirmation_bubble lays down
    (see its ``_flex_row(_media_row_label(...), photo_line)`` call) —
    defensive about shape regardless, since a malformed message here must
    never crash a reply. The row's LABEL is also rewritten here (not only its
    value): a quoted attachment's kind is not known until this settles, so a
    quote that turns out to be a video must still end up under 'ไฟล์', not
    the 'รูป' label the claiming-time render guessed.
    """
    try:
        rows = message["contents"]["body"]["contents"]
        video_seen = video_completed + video_failed + video_running > 0
        rows[-1]["contents"][0]["text"] = _media_row_label(1 if video_seen else 0)
        rows[-1]["contents"][1]["text"] = _claimed_photo_line(
            photo_completed, photo_failed, photo_running,
            video_completed, video_failed, video_running,
        )
    except (KeyError, IndexError, TypeError):
        pass


def build_group_confirmation_text(order: Dict, photo_count: int, video_count: int = 0) -> Dict:
    """The @mention report exception's confirmation (owner, 2026-09-06
    evening) — a compact TEXT message, not :func:`build_confirmation_bubble`'s
    Flex bubble: group postback buttons are dead (group postbacks stay
    ignored), so a report filed by mention gets one lean line plus a pointer
    to the 1:1 chat for anything else.

    ``order`` is the same OrderView build_confirmation_bubble takes (human
    text fields stripped of pictographs here too). ``photo_count``/
    ``video_count`` are the just-CLAIMED counts at creation, same as the
    bubble's; the photos-first bounded wait (CLAIMED_UPLOAD_WAIT_SECONDS)
    still applies before this ever reaches LINE, so what a mention-reporter
    actually sees is the settled outcome — see
    :func:`_patch_group_confirmation_text`, which rebuilds this text
    wholesale once that wait resolves rather than patching a value in place
    (there is no Flex row to index into here).
    """
    order_id = order.get("id")
    urgency_text = "ด่วน" if order.get("urgent") else "ปกติ"
    headline = " · ".join(part for part in (
        f"รับเรื่องแล้ว #{order_id}",
        strip_pictographs(order.get("propertyLabel")),
        strip_pictographs(order.get("location")),
        strip_pictographs(order.get("categoryLabel")),
        urgency_text,
        _media_counts_text(photo_count, video_count),
    ) if part)
    return {"type": "text", "text": headline + "\n" + GROUP_CONFIRMATION_FOLLOWUP_TEXT}


def _patch_group_confirmation_text(
    message: Dict, order: Dict,
    photo_completed: int, photo_failed: int, photo_running: int,
    video_completed: int = 0, video_failed: int = 0, video_running: int = 0,
) -> None:
    """Rewrite a just-built group confirmation text with the real, settled
    media counts (rule B, same bounded wait as the 1:1 bubble).
    ``photo_failed``/``photo_running``/``video_failed``/``video_running`` are
    accepted (same signature as :func:`_patch_confirmation_photo_line`) but
    otherwise unused: this lean line only ever shows what actually attached,
    same spirit as
    rule 3's "keep it lean" (a failure or a still-running upload is visible
    in full in the reporter's own 1:1 chat, which this line already points
    at). Rebuilds the whole text via :func:`build_group_confirmation_text`
    rather than patching a substring in place — there is no stable delimiter
    to patch around once photo AND video counts can each be present or not.
    """
    try:
        message["text"] = build_group_confirmation_text(
            order, photo_count=photo_completed, video_count=video_completed,
        )["text"]
    except (KeyError, TypeError):
        pass


def _render_photo_ack_text(order_id, info: Dict) -> Optional[str]:
    """One photo-ack text object's content for one order (rule A), or None
    when there is nothing to say (should not happen — an entry is only ever
    created alongside a success, a failure or a specific video note).

    Photos and videos are counted (and worded) separately, 2026-09-06:
    ``attached``/``failed`` stay the PHOTO counts (unchanged keys, so a
    photo-only ack's dict shape is exactly what it always was);
    ``video_attached``/``video_failed`` are the video counts. ``total`` —
    photoCount + videoCount from the most recent upload response — is
    rendered once, as "(รวม T ไฟล์)", after whichever attach line(s) apply.
    ``notes`` carries specific, already-Thai one-off lines (a video's
    transcode-failed/oversize reason, or the "still processing" line filed at
    the VIDEO_ACK_DEADLINE_SECONDS mark) verbatim.
    """
    photo_attached = _as_int(info.get("attached"))
    photo_failed = _as_int(info.get("failed"))
    video_attached = _as_int(info.get("video_attached"))
    video_failed = _as_int(info.get("video_failed"))
    total = info.get("total")
    lines: List[str] = []

    attach_parts: List[str] = []
    if photo_attached > 0:
        attach_parts.append(f"แนบรูปเข้า #{order_id} แล้ว {photo_attached} รูป")
    if video_attached > 0:
        attach_parts.append(f"แนบวิดีโอเข้า #{order_id} แล้ว {video_attached} คลิป")
    if attach_parts:
        line = " ".join(attach_parts)
        if isinstance(total, int) and total > 0:
            line += f" (รวม {total} ไฟล์)"
        lines.append(line)

    if photo_failed > 0:
        lines.append(f"แนบรูปไม่สำเร็จ {photo_failed} รูป ลองส่งใหม่อีกครั้งค่ะ (#{order_id})")
    if video_failed > 0:
        lines.append(f"แนบวิดีโอไม่สำเร็จ {video_failed} คลิป ลองส่งใหม่อีกครั้งค่ะ (#{order_id})")
    lines.extend(info.get("notes") or [])
    return "\n".join(lines) if lines else None


def build_category_chip_message(order_id: int) -> Dict:
    """แก้หมวด's reply: a text carrying quick-reply chips for the six
    categories, each a cmd=setcat&id=N&cat=X postback."""
    return {
        "type": "text",
        "text": FIXCAT_PROMPT_FMT.format(id=order_id),
        "quickReply": {
            "items": [
                {
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": CATEGORY_LABELS[category],
                        "data": f"cmd={COMMAND_SETCAT}&id={order_id}&cat={category}",
                        "displayText": CATEGORY_LABELS[category],
                    },
                }
                for category in CATEGORY_ORDER
            ],
        },
    }


def _authorized_for_order(action: "RoutedCommand", order: Dict) -> bool:
    """The reporter, or anybody holding the `reception` grant — nobody else."""
    if action.is_reception:
        return True
    return bool(action.badge) and action.badge == order.get("reporterBadge")


@dataclass(frozen=True)
class PendingUpload:
    """One ticket's just-claimed photos (photos-first, rule B, 2026-09-06):
    downloaded and uploaded from AsyncioBotDispatcher._reply, which waits up
    to CLAIMED_UPLOAD_WAIT_SECONDS for them before the confirmation bubble
    goes out, patching the bubble's photo row with the real outcome.

    ``message_index`` is this upload's confirmation bubble's position in the
    reply's message list (set by build_reply — the bubble _create_ticket
    returns is always the sole message for a successful report action, so it
    is always the message just appended), letting ``_reply`` find and patch
    it in place. None for anything build_reply cannot place (should not
    happen for a real ticket creation, but the patch step checks anyway).
    """

    order_id: int
    message_ids: List[str]
    actor_badge: str = ""
    message_index: Optional[int] = None
    # (2026-09-06) message_id -> "image" | "video" | "quoted" ("quoted": a
    # reply-to-media id whose kind is not known until its content is fetched
    # — see AsyncioBotDispatcher._do_upload). Missing keys default to
    # "image" — every existing caller that never populates this field
    # (nothing but plain buffered photos) behaves exactly as before.
    kinds: Dict[str, str] = field(default_factory=dict)
    # Which patch function _reply runs once the bounded wait resolves —
    # "bubble" (default, every 1:1 report/edit): message_index names a Flex
    # confirmation bubble, patched via _patch_confirmation_photo_line.
    # "addphoto_ack": a plain text ack (เพิ่มรูป-with-quote — see
    # _addphoto_with_quote), patched via _patch_addphoto_ack_text.
    # "group_confirmation" (the @mention report exception, 2026-09-06
    # evening): the compact group text, patched via
    # _patch_group_confirmation_text — see ``group_order`` below.
    patch_kind: str = "bubble"
    # The OrderView a "group_confirmation" patch rebuilds its text from
    # (build_group_confirmation_text needs the order fields, not just
    # counts — there is no Flex row to index into and patch in place). Unused
    # for every other patch_kind.
    group_order: Optional[Dict] = None


def _create_ticket(action: "RoutedCommand") -> Tuple[List[Dict], Optional[PendingUpload]]:
    """แจ้งซ่อม (1:1) OR its group/room @mention exception (owner, 2026-09-06
    evening, rule 3a): same parse/create/claim logic either way — only the
    confirmation MESSAGE differs, a Flex bubble with edit buttons in 1:1
    (:func:`build_confirmation_bubble`) versus a compact text pointing back
    at the 1:1 chat in a group/room (:func:`build_group_confirmation_text`,
    group postback buttons are dead there)."""
    is_group = action.source_type in ("group", "room")
    draft = parse_report(action.report_text)
    if isinstance(draft, ParseError):
        return [{"type": "text", "text": draft.message}], None

    payload: Dict = {
        "property": action.property or "hf",
        "location_kind": draft.location_kind,
        "category": draft.category,
        "urgent": draft.urgent,
        "reporter": {"badge": action.badge, "name": action.display_name},
        "source": "line-bot",
    }
    if draft.room_no:
        payload["room_no"] = draft.room_no
    if draft.common_area:
        payload["common_area"] = draft.common_area
    if draft.detail_text:
        payload["detail_text"] = draft.detail_text

    result = housekeeping_client.create_work_order(payload)
    if result is None:
        return [{"type": "text", "text": TICKET_UNAVAILABLE_TEXT}], None
    if "error" in result:
        return [{"type": "text", "text": result["error"]}], None

    order = result.get("order") or {}
    order_id = order.get("id")
    claimed: List[str] = []
    kinds: Dict[str, str] = {}
    photo_count = 0
    video_count = 0
    upload: Optional[PendingUpload] = None
    if isinstance(order_id, int):
        for message_id, kind in get_photo_buffer().claim_detailed(action.chat_key, action.user_id):
            claimed.append(message_id)
            kinds[message_id] = kind
            if kind == "video":
                video_count += 1
            else:
                photo_count += 1
        if action.quoted_message_id:
            # Reply-to-media (2026-09-06): whoever originally sent the
            # quoted message, attached to THIS new ticket. Its kind is not
            # known until fetched — counted as a photo for this pre-upload
            # display only; the bubble is repatched with the real kind once
            # the bounded wait resolves.
            claimed.append(action.quoted_message_id)
            kinds[action.quoted_message_id] = "quoted"
            photo_count += 1
        get_attach_windows().open(action.chat_key, action.user_id, order_id)
        logger.info(
            "staff-bot ticket created: chat=%s order=%s photos=%s",
            action.chat_key, order_id, len(claimed),
        )
        if claimed:
            upload = PendingUpload(
                order_id=order_id, message_ids=claimed, actor_badge=action.badge, kinds=kinds,
                patch_kind="group_confirmation" if is_group else "bubble",
                group_order=order if is_group else None,
            )
    if is_group:
        return [build_group_confirmation_text(order, photo_count=photo_count, video_count=video_count)], upload
    return [build_confirmation_bubble(order, photo_count=photo_count, video_count=video_count)], upload


def _cancel_ticket(action: "RoutedCommand") -> Tuple[List[Dict], None]:
    result = housekeeping_client.cancel_work_order(
        action.order_id, {"badge": action.badge, "name": action.display_name},
    )
    if result is None:
        return [{"type": "text", "text": TICKET_UNAVAILABLE_TEXT}], None
    if "error" in result:
        return [{"type": "text", "text": result["error"]}], None
    logger.info("staff-bot ticket cancelled: order=%s", action.order_id)
    return [{"type": "text", "text": CANCEL_SUCCESS_FMT.format(id=action.order_id)}], None


def _patch_ticket(action: "RoutedCommand", order: Dict) -> Tuple[List[Dict], None]:
    if action.command == COMMAND_SETCAT:
        field_name, fields = "category", {"category": action.category}
    elif action.command == COMMAND_TOGGLEURGENT:
        field_name, fields = "urgent", {"urgent": not bool(order.get("urgent"))}
    else:  # COMMAND_SWITCHPROP
        field_name = "property"
        fields = {"property": "hfville" if order.get("property") == "hf" else "hf"}

    result = housekeeping_client.patch_work_order(
        action.order_id, fields, {"badge": action.badge, "name": action.display_name},
    )
    if result is None:
        return [{"type": "text", "text": TICKET_UNAVAILABLE_TEXT}], None
    if "error" in result:
        return [{"type": "text", "text": result["error"]}], None
    logger.info("staff-bot ticket edited: order=%s field=%s", action.order_id, field_name)
    new_order = result.get("order") or {}
    bubble = build_confirmation_bubble(
        new_order,
        photo_count=_as_int(new_order.get("photoCount")),
        video_count=_as_int(new_order.get("videoCount")),
    )
    return [bubble], None


def _mine_bubble(order: Dict) -> Dict:
    """One ticket's row-bubble for the งานของฉัน carousel AND the สถานะ/งาน
    <id> single lookup — same content, same layout, one definition."""
    order_id = order.get("id")
    location = strip_pictographs(order.get("location"))
    title = f"#{order_id} · {location}" if location else f"#{order_id}"
    return {
        "type": "bubble",
        "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical",
            "contents": [{"type": "text", "text": title, "weight": "bold",
                          "size": "md", "wrap": True}],
        },
        "body": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                _flex_row("หมวด", strip_pictographs(order.get("categoryLabel"))),
                _flex_row("สถานะ", strip_pictographs(order.get("statusLabel"))),
                _flex_row("อายุ", _age_text(_as_int(order.get("ageDays")))),
                _flex_row(
                    _media_row_label(_as_int(order.get("videoCount"))),
                    _media_counts_text(
                        _as_int(order.get("photoCount")), _as_int(order.get("videoCount")),
                    ),
                ),
            ],
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                _postback_button("เพิ่มรูป", f"cmd={COMMAND_ADDPHOTO}&id={order_id}"),
                _postback_button("ยกเลิก", f"cmd={COMMAND_CANCEL}&id={order_id}"),
            ],
        },
    }


def _list_mine(action: "RoutedCommand") -> Tuple[List[Dict], None]:
    """cmd=mine / งานของฉัน: the tapper's own active tickets, newest first,
    as one Flex carousel (<= 10 bubbles). Empty and dark are both a single
    plain-text line, never silence and never an error."""
    result = housekeeping_client.list_work_orders(action.badge, active=True, limit=10)
    if result is None:
        return [{"type": "text", "text": TICKET_UNAVAILABLE_TEXT}], None
    if "error" in result:
        return [{"type": "text", "text": result["error"]}], None
    raw_orders = result.get("orders")
    orders = [o for o in raw_orders if isinstance(o, dict)][:10] if isinstance(raw_orders, list) else []
    if not orders:
        return [{"type": "text", "text": MINE_EMPTY_TEXT}], None
    return [{
        "type": "flex",
        "altText": MINE_ALT_TEXT,
        "contents": {"type": "carousel", "contents": [_mine_bubble(o) for o in orders]},
    }], None


def _status_lookup(action: "RoutedCommand") -> Tuple[List[Dict], None]:
    """'สถานะ <id>' / 'งาน <id>': one ticket's bubble, gated exactly like the
    edit postbacks (reporter or `reception`) — a read, never a status
    CHANGE. 404 and "not your ticket" get their own fixed lines rather than
    housekeeping's edit-flavoured error text."""
    fetched = housekeeping_client.get_work_order(action.order_id)
    if fetched is None:
        return [{"type": "text", "text": TICKET_UNAVAILABLE_TEXT}], None
    if "error" in fetched:
        return [{"type": "text", "text": STATUS_NOT_FOUND_FMT.format(id=action.order_id)}], None
    order = fetched.get("order") or {}
    if not _authorized_for_order(action, order):
        return [{"type": "text", "text": STATUS_FORBIDDEN_TEXT}], None
    return [{
        "type": "flex",
        "altText": f"งาน #{action.order_id}",
        "contents": _mine_bubble(order),
    }], None


def _build_ticket_messages(action: "RoutedCommand") -> Tuple[List[Dict], Optional[PendingUpload]]:
    """One ticket action -> the message object(s) for it, plus any photos to
    upload in the background. Runs inside asyncio.to_thread, same as the
    digest/requests fetches above — I/O here is fine."""
    if action.command == COMMAND_REPORT_HELP:
        text = REPORT_HELP_GROUP_TEXT if action.source_type in ("group", "room") else REPORT_HELP_DIRECT_TEXT
        return [{"type": "text", "text": text}], None

    if not action.identity_known:
        return [{"type": "text", "text": NOT_LINKED_TEXT}], None

    if action.command == COMMAND_REPORT:
        return _create_ticket(action)
    if action.command == COMMAND_MINE:
        return _list_mine(action)
    if action.command == COMMAND_STATUS:
        return _status_lookup(action)

    # Every remaining ticket command names an existing order — fetch it once
    # (to know the reporter, for authorization) before doing anything else.
    fetched = housekeeping_client.get_work_order(action.order_id)
    if fetched is None:
        return [{"type": "text", "text": TICKET_UNAVAILABLE_TEXT}], None
    if "error" in fetched:
        return [{"type": "text", "text": fetched["error"]}], None
    order = fetched.get("order") or {}
    if not _authorized_for_order(action, order):
        return [{"type": "text", "text": EDIT_FORBIDDEN_TEXT}], None

    if action.command == COMMAND_FIXCAT:
        return [build_category_chip_message(action.order_id)], None
    if action.command == COMMAND_ADDPHOTO:
        if action.quoted_message_id:
            return _addphoto_with_quote(action)
        get_attach_windows().open(action.chat_key, action.user_id, action.order_id)
        return [{"type": "text", "text": ADDPHOTO_PROMPT_FMT.format(id=action.order_id)}], None
    if action.command == COMMAND_CANCEL:
        return _cancel_ticket(action)
    return _patch_ticket(action, order)  # setcat / toggleurgent / switchprop


def _addphoto_with_quote(action: "RoutedCommand") -> Tuple[List[Dict], Optional[PendingUpload]]:
    """เพิ่มรูป #N as a REPLY to an earlier message (reply-to-media,
    2026-09-06): the quoted media is fetched and attached the same way a
    claimed-at-creation batch is (rule B) — a bounded CLAIMED_UPLOAD_WAIT_SECONDS
    wait, then the reply is patched with the real ack line. Authorization
    (reporter or `reception`) is already checked by the caller before this
    runs, same as every other order-naming ticket command.
    """
    placeholder = {"type": "text", "text": ADDPHOTO_PROMPT_FMT.format(id=action.order_id)}
    upload = PendingUpload(
        order_id=action.order_id,
        message_ids=[action.quoted_message_id],
        actor_badge=action.badge,
        kinds={action.quoted_message_id: "quoted"},
        message_index=0,
        patch_kind="addphoto_ack",
    )
    return [placeholder], upload


def _patch_addphoto_ack_text(
    message: Dict, order_id,
    photo_completed: int, photo_failed: int, photo_running: int,
    video_completed: int = 0, video_failed: int = 0, video_running: int = 0,
) -> None:
    """Rewrite เพิ่มรูป-with-quote's placeholder text with the real outcome,
    once its single quoted attachment's bounded wait resolves. Reuses
    :func:`_render_photo_ack_text`'s wording (the same "แนบรูปเข้า/แนบวิดีโอเข้า/
    แนบ...ไม่สำเร็จ" lines rule A uses) so a quoted attach and an in-window
    attach read identically. Still running past the bounded wait (should be
    rare — a single item almost always resolves well inside
    CLAIMED_UPLOAD_WAIT_SECONDS) leaves the original prompt line in place
    rather than showing nothing.
    """
    if photo_completed > 0 or video_completed > 0 or photo_failed > 0 or video_failed > 0:
        text = _render_photo_ack_text(order_id, {
            "attached": photo_completed, "failed": photo_failed,
            "video_attached": video_completed, "video_failed": video_failed,
            "total": None,
        })
        if text:
            try:
                message["text"] = text
            except TypeError:
                pass


@dataclass(frozen=True)
class BuiltReply:
    """The message objects for one reply, plus what became of the slot digest.

    ``slot_digest_included`` is False when a slot digest was asked for and
    housekeeping had nothing to give — the caller needs to tell that apart
    from a successful post, because only one of the two leaves a mark.
    ``digest_available`` is False when the reply carries the fixed "not
    connected" line instead of real rows, which is NOT a digest this window
    can be considered to have had.
    """

    messages: List[Dict]
    slot_digest_included: bool = False
    digest_available: bool = False
    # Phase 3: photos claimed by a ticket created in THIS reply, to be
    # downloaded and uploaded in the background once LINE accepts the reply
    # that carries the confirmation bubble.
    pending_uploads: List[PendingUpload] = field(default_factory=list)


def render_requests(payload: Optional[Dict]) -> str:
    """The 1:1 ความคิดเห็นลูกค้า PREVIEW: the same report-style section (b)
    text (header + lines) :func:`render_slot_digest` carries in a group,
    built from guest-feedback's pending JSON (praise, issue and request
    alike — the queue is kind-agnostic) rather than guest-feedback's own
    chat-style ``text`` (2026-09-06 consolidation).

    Not a dict (either env unset, timeout, non-2xx, malformed body — see
    guest_feedback_client.fetch_pending) renders the one fixed Thai line:
    staff are told the read failed, never given a status code and never left
    guessing at silence. A reachable read with nothing waiting gets its own
    plain line. This is a PREVIEW — the caller never confirms delivery for it
    (see AsyncioBotDispatcher._reply's group/room-only confirm gate).
    """
    if not isinstance(payload, dict):
        return REQUESTS_UNAVAILABLE_TEXT
    if _as_int(payload.get("count")) <= 0:
        return REQUESTS_NONE_TEXT
    section = render_feedback_section(payload)
    return section if section is not None else REQUESTS_UNAVAILABLE_TEXT


def _request_ids(payload: Optional[Dict]) -> List[str]:
    """The feedback ids in a pending payload, for the delivery confirm."""
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [
        str(item["id"]) for item in items
        if isinstance(item, dict) and item.get("id") is not None
    ]


def build_reply(
    commands: Sequence[str],
    slot_id: Optional[str] = None,
    confirmed_request_ids: Optional[List[str]] = None,
    actions: Sequence["RoutedCommand"] = (),
    photo_acks: Optional[Dict] = None,
) -> BuiltReply:
    """Build ONE coalesced reply, in canonical order.

    At most one digest object per reply: a slot digest and a plain digest in
    the same burst are the same rows twice over. The slot digest takes the
    digest position and carries the "สรุปงานซ่อมค้างประจำรอบ..." line; the
    plain digest is dropped — UNLESS housekeeping is dark, in which case the
    slot digest renders nothing and a digest somebody actually typed still
    gets its fixed Thai "not connected" line. A palette asked for in the same
    burst always rides along.

    ``confirmed_request_ids`` — when given, the ids of a :data:`COMMAND_REQUESTS`
    reply's fetched rows are appended to it, so the caller
    (:meth:`AsyncioBotDispatcher._reply`) can confirm delivery with
    guest-feedback after LINE accepts the reply.

    ``photo_acks`` (rule A, 2026-09-06) — ``{order_id: {attached, failed,
    total}}`` filed by ``ReplyDebouncer.note_photo_ack`` for photos that
    attached silently while an order's attach window was open. Rendered right
    after the COMMAND_ORDER messages above, one text object per order id, in
    insertion order — same canonical position as the digest/requests objects,
    before any ticket ``actions`` below.

    ``actions`` (phases 3/4) — the RoutedCommand for each ticket action
    (report/report_help/mine/status/fixcat/setcat/toggleurgent/addphoto/
    cancel/switchprop) in this burst, rendered AFTER the COMMAND_ORDER messages
    above and in the order they were noted. Unlike the fixed commands, no
    two of these ever render the same reply, so each carries its own data
    rather than a shared string in ``commands``.
    """
    wanted = set(commands)
    messages: List[Dict] = []
    slot_included = False
    digest_available = False
    for command in COMMAND_ORDER:
        if command == COMMAND_ONBOARDING and command in wanted:
            messages.append({"type": "text", "text": ONBOARDING_REPLY_TEXT})
        elif command == COMMAND_PALETTE and command in wanted:
            messages.append(palette_message())
        elif command == COMMAND_DIGEST:
            # The digest position, shared by both digest kinds. One fetch:
            # the two would otherwise disagree with each other in the same
            # reply, and it is a network round trip inside a reply token's
            # lifetime.
            if COMMAND_SLOT_DIGEST not in wanted and COMMAND_DIGEST not in wanted:
                continue
            payload = housekeeping_client.fetch_digest()
            digest_available = isinstance(payload, dict)
            if COMMAND_SLOT_DIGEST in wanted:
                # Guest feedback consolidated into the slot report
                # (2026-09-06): fetched only for the SLOT digest, never for a
                # plain typed/tapped งานค้าง — see render_slot_digest.
                feedback_payload = guest_feedback_client.fetch_pending()
                text = render_slot_digest(slot_id, payload, feedback_payload)
                if text is not None:
                    messages.append({"type": "text", "text": text})
                    slot_included = True
                    if confirmed_request_ids is not None:
                        confirmed_request_ids.extend(_request_ids(feedback_payload))
                    continue
                if COMMAND_DIGEST not in wanted:
                    continue  # scheduled + nothing at all to say: stay silent
            messages.append({"type": "text", "text": render_digest(payload)})
        elif command == COMMAND_REQUESTS and command in wanted:
            payload = guest_feedback_client.fetch_pending()
            messages.append({"type": "text", "text": render_requests(payload)})
            if confirmed_request_ids is not None:
                confirmed_request_ids.extend(_request_ids(payload))

    for order_id, info in (photo_acks or {}).items():
        text = _render_photo_ack_text(order_id, info)
        if text:
            messages.append({"type": "text", "text": text})

    pending_uploads: List[PendingUpload] = []
    for action in actions:
        message_index = len(messages)
        action_messages, upload = _build_ticket_messages(action)
        messages.extend(action_messages)
        if upload is not None:
            # The bubble _create_ticket returns is always the sole message on
            # a successful create, so it landed exactly at message_index —
            # see PendingUpload.message_index and _reply's use of it.
            pending_uploads.append(replace(
                upload, message_index=message_index if action_messages else None,
            ))

    return BuiltReply(messages[:MAX_REPLY_MESSAGES], slot_included, digest_available, pending_uploads)


def build_messages(
    commands: Sequence[str],
    confirmed_request_ids: Optional[List[str]] = None,
    slot_id: Optional[str] = None,
    actions: Sequence["RoutedCommand"] = (),
    photo_acks: Optional[Dict] = None,
) -> List[Dict]:
    """The message objects for one coalesced reply, in canonical order.

    ``confirmed_request_ids`` stays the SECOND positional parameter (the
    guest-feedback call shape); ``slot_id`` selects the slot digest prefix.
    """
    return build_reply(commands, slot_id, confirmed_request_ids, actions, photo_acks).messages


# ---------------------------------------------------------------------------
# Debounce state machine (pure: injectable clock + scheduler, no I/O)
# ---------------------------------------------------------------------------

@dataclass
class PendingReply:
    """One chat's not-yet-sent reply."""

    chat_key: str
    commands: Set[str] = field(default_factory=set)
    reply_token: str = ""
    first_at: float = 0.0
    last_at: float = 0.0
    quiet_seconds: float = COMMAND_QUIET_SECONDS
    # The slot mark this reply will promote to 'sent' (or delete) once the
    # send outcome is known. See RoutedCommand.slot_ref.
    slot_ref: Optional[SlotRef] = None
    # What opened that slot (reception|late), carried only so the mark can be
    # rewritten faithfully in the corner where its row went missing.
    slot_trigger: str = TRIGGER_COMMAND
    # "group" / "room" / "user" — which the first command in this burst came
    # from. Used only to gate the guest-feedback delivery confirm: a group or
    # room reply confirms, a 1:1 reply is a preview and never does.
    source_type: str = ""
    # Phase 3: the RoutedCommand for each ticket action noted in this burst,
    # in arrival order — see build_reply's ``actions`` parameter. A plain
    # command word never appends here; only TICKET_COMMANDS do.
    actions: List["RoutedCommand"] = field(default_factory=list)
    # Photo acknowledgements (rule A, 2026-09-06): order_id -> {"attached",
    # "failed", "total"}, accumulated by ReplyDebouncer.note_photo_ack across
    # every photo that finishes uploading while this reply is pending. See
    # build_reply's ``photo_acks`` parameter.
    photo_acks: Dict[int, Dict] = field(default_factory=dict)

    def deadline(self, max_wait_seconds: float) -> float:
        """Quiet-timer deadline, capped so the reply token cannot expire."""
        return min(self.last_at + self.quiet_seconds,
                   self.first_at + max_wait_seconds)


class ReplyDebouncer:
    """Per-chat "wait for quiet, then answer once" state machine.

    No timers, no threads, no I/O: it holds pending entries and answers
    :meth:`next_delay` / :meth:`pop_due`. The optional ``scheduler`` is called
    with the number of seconds until the next deadline whenever that could
    have changed, which is how the asyncio adapter learns it should wake up.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        scheduler: Optional[Callable[[float], None]] = None,
        max_wait_seconds: float = MAX_WAIT_SECONDS,
    ):
        self._clock = clock
        self._scheduler = scheduler
        self._max_wait_seconds = max_wait_seconds
        self._pending: Dict[str, PendingReply] = {}

    # -- inputs ------------------------------------------------------------
    def note_command(
        self,
        chat_key: str,
        command: str,
        reply_token: str,
        quiet_seconds: float = COMMAND_QUIET_SECONDS,
        slot_ref: Optional[SlotRef] = None,
        source_type: str = "",
        action: Optional["RoutedCommand"] = None,
    ) -> PendingReply:
        """Record a command: create or MERGE INTO this chat's pending reply.

        ``action`` (phase 3) — the full RoutedCommand for a ticket command,
        appended to ``pending.actions`` so build_reply can render it with its
        own data later. None for every non-ticket command.
        """
        now = self._clock()
        pending = self._pending.get(chat_key)
        if pending is None:
            pending = PendingReply(
                chat_key=chat_key, first_at=now, quiet_seconds=quiet_seconds,
            )
            self._pending[chat_key] = pending
        pending.commands.add(command)
        pending.reply_token = reply_token
        pending.last_at = now
        # The IMPATIENT one wins. A slot digest waits 15 s for the group to
        # settle, but a command typed while it waits is answered at once (0 s)
        # — and the reply it triggers carries the slot digest with it, which is
        # why the two coalesce instead of racing.
        pending.quiet_seconds = min(pending.quiet_seconds, quiet_seconds)
        if slot_ref is not None:
            pending.slot_ref = slot_ref
        if source_type:
            pending.source_type = source_type
        if action is not None:
            pending.actions.append(action)
        self._notify()
        return pending

    def note_photo_ack(
        self,
        chat_key: str,
        reply_token: str,
        order_id: int,
        kind: str = "image",
        attached: int = 0,
        failed: int = 0,
        total: Optional[int] = None,
        note: Optional[str] = None,
        quiet_seconds: float = PHOTO_ACK_QUIET_SECONDS,
    ) -> PendingReply:
        """Record one photo (or video, 2026-09-06)'s finished upload for the
        ack line (rule A): create or MERGE INTO this chat's pending reply
        exactly like :meth:`note_command` — same impatient-quiet-wins rule (a
        command arriving meanwhile wins the minimum quiet and the ack rides
        along in that reply), same "newest token wins" rule (so the LAST
        photo to finish in a burst is what actually gets spent).

        Counts accumulate per order id across every photo/video that finishes
        while this reply is still pending; ``total`` — the upload's own
        photoCount + videoCount — overwrites rather than accumulates, so it
        always reflects the most recent known total, per the owner's "total
        from the last upload" rule.

        ``kind="image"`` (the default, and every call site before video
        support) increments the original ``attached``/``failed`` keys
        UNCHANGED — a photo-only order's entry is exactly the same dict shape
        it always was. ``kind="video"`` increments separate
        ``video_attached``/``video_failed`` keys instead, added to the entry
        only once a video actually touches it. ``note`` (a video's specific
        transcode-failed/oversize/still-processing line, already Thai and
        already formatted) is appended verbatim rather than counted, so it
        renders as its own line instead of inflating a generic count.
        """
        now = self._clock()
        pending = self._pending.get(chat_key)
        if pending is None:
            pending = PendingReply(
                chat_key=chat_key, first_at=now, quiet_seconds=quiet_seconds,
            )
            self._pending[chat_key] = pending
        pending.commands.add(COMMAND_PHOTO_ACK)
        pending.reply_token = reply_token
        pending.last_at = now
        pending.quiet_seconds = min(pending.quiet_seconds, quiet_seconds)
        entry = pending.photo_acks.setdefault(order_id, {"attached": 0, "failed": 0, "total": None})
        if kind == "video":
            entry["video_attached"] = entry.get("video_attached", 0) + attached
            entry["video_failed"] = entry.get("video_failed", 0) + failed
        else:
            entry["attached"] += attached
            entry["failed"] += failed
        if total is not None:
            entry["total"] = total
        if note:
            entry.setdefault("notes", []).append(note)
        self._notify()
        return pending

    def note_message(self, chat_key: str, reply_token: str) -> bool:
        """Any other message in the chat: newest token, quiet timer restarted.

        Never CREATES a pending entry — ordinary chat the bot was not asked
        about must leave no trace at all. Returns True when a pending entry
        existed and now holds this token, i.e. the bot has CLAIMED it (see
        :func:`handle_event_detail`).
        """
        pending = self._pending.get(chat_key)
        if pending is None:
            return False
        if reply_token:
            pending.reply_token = reply_token
        pending.last_at = self._clock()
        self._notify()
        return True

    # -- outputs -----------------------------------------------------------
    def pending_for(self, chat_key: str) -> Optional[PendingReply]:
        return self._pending.get(chat_key)

    def next_delay(self) -> Optional[float]:
        """Seconds until the earliest deadline (0 if due), None if idle."""
        if not self._pending:
            return None
        now = self._clock()
        earliest = min(
            pending.deadline(self._max_wait_seconds)
            for pending in self._pending.values()
        )
        return max(0.0, earliest - now)

    def pop_due(self) -> List[PendingReply]:
        """Remove and return every pending reply whose deadline has arrived."""
        now = self._clock()
        due = [
            pending for pending in self._pending.values()
            if pending.deadline(self._max_wait_seconds) <= now
        ]
        for pending in due:
            self._pending.pop(pending.chat_key, None)
        return due

    def _notify(self) -> None:
        if self._scheduler is None:
            return
        delay = self.next_delay()
        if delay is not None:
            self._scheduler(delay)


# ---------------------------------------------------------------------------
# Slot marks — the only persistent state the bot keeps
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    """Naive UTC, the storage convention everywhere in this repo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def find_slot_mark(db: Session, ref: SlotRef) -> Optional[StaffBotSlotMark]:
    """The mark for one (group, Bangkok date, slot), or None."""
    group_id, bkk_date, slot_id = ref
    return (
        db.query(StaffBotSlotMark)
        .filter(
            StaffBotSlotMark.group_id == group_id,
            StaffBotSlotMark.bkk_date == bkk_date,
            StaffBotSlotMark.slot == slot_id,
        )
        .first()
    )


def _delete_mark(db: Session, mark: StaffBotSlotMark, ref: SlotRef, reason: str) -> None:
    db.delete(mark)
    db.commit()
    logger.info(
        "staff-bot slot dropped: group=%s date=%s slot=%s reason=%s",
        ref[0], ref[1], ref[2], reason,
    )


def has_reception_grant(db: Session, line_user_id: str) -> bool:
    """Whether this LINE account is an ACTIVE employee holding `reception`.

    One query: line_user_id -> badge_number -> EmployeeAppGrant. The same
    fact staff_oa_service.grants_for_badge answers, without the intermediate
    round trip and without loading grants nobody asked about.
    """
    if not line_user_id:
        return False
    return (
        db.query(EmployeeAppGrant.id)
        .join(Employee, Employee.badge_number == EmployeeAppGrant.employee_badge_number)
        .filter(
            Employee.line_user_id == line_user_id,
            Employee.is_active == True,  # noqa: E712
            EmployeeAppGrant.app_id == RECEPTION_APP_ID,
        )
        .first()
        is not None
    )


def evaluate_slot_trigger(
    db: Session,
    group_id: str,
    timestamp_ms,
    sender_user_id: str,
) -> Optional[Tuple[SlotRef, str]]:
    """Should this non-command group message open its slot? Rule 3 of phase 2.

    Returns ``(slot_ref, trigger)`` when the digest should be filed, else
    None. Order matters and is the owner's:

      a. an unmarked slot + a message from a `reception` grant holder — the
         report burst this digest is designed to ride;
      b. otherwise an unmarked slot in its last 30 minutes + ANY message,
         including one from a sender LINE gives us no userId for (LINE for
         PC), because a window about to close is worth more than a perfect
         attribution;
      c. otherwise nothing — the group's chat is none of the bot's business.

    A 'pending' mark older than STALE_PENDING_SECONDS belonged to a process
    that died mid-debounce; it is deleted here (and the window re-opens)
    before any of the above is applied.
    """
    ref = slot_ref_for_event(group_id, timestamp_ms)
    if ref is None:
        return None

    mark = find_slot_mark(db, ref)
    if mark is not None:
        if mark.state == STATE_PENDING and _is_stale(mark):
            _delete_mark(db, mark, ref, "stale")
        else:
            return None  # already filed or already sent: once per slot

    if has_reception_grant(db, sender_user_id):
        return ref, TRIGGER_RECEPTION

    moment = bangkok_moment(timestamp_ms)
    slot = SLOTS_BY_ID[ref[2]]
    if moment is not None and _second_of_day(moment) >= slot.late_second:
        return ref, TRIGGER_LATE
    return None


def _is_stale(mark: StaffBotSlotMark) -> bool:
    filed_at = mark.filed_at
    if not isinstance(filed_at, datetime):
        return True  # no idea when it was filed: do not let it wedge the slot
    return (_utcnow() - filed_at) > timedelta(seconds=STALE_PENDING_SECONDS)


def file_slot_mark(db: Session, ref: SlotRef, trigger: str) -> bool:
    """Reserve the slot: write the 'pending' mark. False if somebody beat us.

    The UNIQUE(group_id, bkk_date, slot) index is the real guard — two webhook
    deliveries can be in flight at once — so a collision here is a normal
    outcome, not an error: the other one owns the slot.
    """
    group_id, bkk_date, slot_id = ref
    mark = StaffBotSlotMark(
        group_id=group_id, bkk_date=bkk_date, slot=slot_id,
        state=STATE_PENDING, filed_at=_utcnow(), trigger=trigger,
    )
    db.add(mark)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.debug("staff-bot slot already filed by another delivery")
        return False
    logger.info(
        "staff-bot slot filed: group=%s date=%s slot=%s trigger=%s",
        group_id, bkk_date, slot_id, trigger,
    )
    return True


def mark_slot_sent(db: Session, ref: SlotRef, trigger: str = TRIGGER_COMMAND) -> None:
    """The digest for this slot went out: promote (or write) the 'sent' mark.

    ``trigger`` is only used when there is no row yet — the case where a plain
    งานค้าง command answered inside an unmarked window and thereby covered the
    slot (rule 7), so no scheduled near-duplicate follows it.
    """
    group_id, bkk_date, slot_id = ref
    mark = find_slot_mark(db, ref)
    if mark is None:
        mark = StaffBotSlotMark(
            group_id=group_id, bkk_date=bkk_date, slot=slot_id,
            filed_at=_utcnow(), trigger=trigger,
        )
        db.add(mark)
    mark.state = STATE_SENT
    mark.sent_at = _utcnow()
    db.commit()
    logger.info(
        "staff-bot slot sent: group=%s date=%s slot=%s",
        group_id, bkk_date, slot_id,
    )


def drop_slot_mark(db: Session, ref: SlotRef, reason: str) -> None:
    """Nothing was posted after all: delete the mark so the window re-opens."""
    mark = find_slot_mark(db, ref)
    if mark is None:
        return
    _delete_mark(db, mark, ref, reason)


def _in_own_session(action: Callable[[Session], None]) -> None:
    """Run one short mark write on a session of our own.

    A pending reply outlives the request that filed it by up to 45 s, so the
    request-scoped session from ``Depends(get_db)`` is long closed by the time
    the send outcome is known. Same shape as staff_oa_provision: open, write,
    close — and never raise into the drain loop, because a bookkeeping failure
    must not cost the group its digest.
    """
    db = database.SessionLocal()
    try:
        action(db)
    except Exception as exc:  # noqa: BLE001 — bookkeeping, not the message
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("staff-bot could not record a slot mark: %s", exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# asyncio adapter — the only part that touches a loop or the network
# ---------------------------------------------------------------------------

class AsyncioBotDispatcher:
    """Runs :class:`ReplyDebouncer` on the request's event loop.

    Thin on purpose. The webhook returns 200 to LINE immediately; a single
    drain task sleeps until the next deadline, then sends. The blocking LINE
    and housekeeping calls go through ``asyncio.to_thread`` so they never
    block the loop that is serving other requests.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.debouncer = ReplyDebouncer(clock=clock, scheduler=self._wake)
        self._task: Optional[asyncio.Task] = None
        # Phase 3 background photo uploads (fire-and-forget, but kept
        # referenced so they are not garbage-collected mid-flight — the
        # standard asyncio gotcha with detached tasks).
        self._background_tasks: Set[asyncio.Task] = set()

    def submit_command(self, command: RoutedCommand) -> None:
        self.debouncer.note_command(
            command.chat_key, command.command, command.reply_token,
            quiet_seconds=command.quiet_seconds,
            slot_ref=command.slot_ref,
            source_type=command.source_type,
            action=command if command.command in TICKET_COMMANDS else None,
        )

    def spawn_photo_upload(
        self, order_id: int, message_id: str, actor_badge: str,
        chat_key: str = "", reply_token: str = "", kind: str = "image",
    ) -> None:
        """Download + upload ONE claimed/attached photo (or video, 2026-09-06),
        off the request path.

        Used for a photo/video that arrives while an attach window is already
        open (silent attach, see ``_maybe_handle_photo``) — ``chat_key`` and
        ``reply_token`` there are the photo EVENT's own (rule A, 2026-09-06):
        once the upload resolves, an ack is filed with THAT token via
        :meth:`ReplyDebouncer.note_photo_ack`. The claimed-at-creation batch
        (rule B) does NOT go through this method any more — see
        ``_await_claimed_uploads``, which waits on it before the confirmation
        bubble is sent, so a buffered photo never had a token of its own to
        ack with in the first place.

        ``kind="video"`` routes through :meth:`_upload_video_with_deadline`
        instead of the plain path, because a video's LINE-side transcode can
        outlive this event's reply token (VIDEO_ACK_DEADLINE_SECONDS).

        A missing event loop (a script, a sync test) is a silent no-op: there
        is nowhere to run this in the background, and a photo that never got
        claimed via an open loop was never going to be attached synchronously
        either.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if kind == "video":
            task = loop.create_task(
                self._upload_video_with_deadline(order_id, message_id, actor_badge, chat_key, reply_token)
            )
        else:
            task = loop.create_task(
                self._upload_one_photo(order_id, message_id, actor_badge, chat_key, reply_token, kind=kind)
            )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _do_upload(
        self, order_id: int, message_id: str, actor_badge: str, kind: str = "image",
    ) -> Tuple[Optional[Dict], Optional[str], str]:
        """Download + upload ONE photo/video. Returns ``(result, reason,
        resolved_kind)``:

        - ``result`` — the upload's own JSON body (carrying ``photoCount``/
          ``videoCount``) on success; None on any failure.
        - ``reason`` — None on success, else one of "download", "upload",
          "transcode" (video only) or "oversize" (video only).
        - ``resolved_kind`` — "image" or "video". For ``kind="image"``/
          ``"video"`` this just echoes back; for ``kind="quoted"``
          (reply-to-media, 2026-09-06 — a quoted message whose type is not
          known ahead of time) it is determined from the fetched
          Content-Type, defaulting to "image" when that cannot be told
          either (an unrecognised/failed fetch — counted as a plain photo
          failure, same wording as any other failed attach).

        Never raises, so one bad photo/video cannot take the loop or a
        pending reply down with it.

        VIDEO (kind="video"): LINE must finish server-side transcoding before
        the bytes are downloadable at all, so this waits for that first
        (staff_oa_service.wait_for_transcoding, bounded by
        VIDEO_TRANSCODE_WAIT_SECONDS), then downloads capped at
        VIDEO_BYTES_MAX. Deviation from a literal reading of the spec: LINE's
        transcoding-status endpoint is only meaningful for a message LINE
        itself flagged as needing transcoding, so a QUOTED message (kind=
        "quoted", where the type is not known up front) is fetched directly
        without a transcoding wait — if LINE has not finished processing it
        yet, the plain fetch fails and the attach is counted as a generic
        failure rather than the specific "still processing" line. This is
        documented in the deviations list.
        """
        if kind == "video":
            transcoded = await asyncio.to_thread(
                staff_oa_service.wait_for_transcoding, message_id, VIDEO_TRANSCODE_WAIT_SECONDS,
            )
            if not transcoded:
                logger.warning("staff-bot photo failed: order=%s reason=transcode", order_id)
                return None, "transcode", "video"
            try:
                fetched = await asyncio.to_thread(
                    staff_oa_service.fetch_message_content, message_id, VIDEO_BYTES_MAX,
                )
            except staff_oa_service.ContentTooLarge:
                logger.warning("staff-bot photo failed: order=%s reason=oversize", order_id)
                return None, "oversize", "video"
            if fetched is None:
                logger.warning("staff-bot photo failed: order=%s reason=download", order_id)
                return None, "download", "video"
            data, content_type = fetched
            mime = content_type if content_type in ("video/mp4", "video/quicktime") else "video/mp4"
            resolved_kind = "video"
        elif kind == "quoted":
            # Cleanup (2026-09-06 review): a quoted message's kind is not
            # known ahead of the fetch, so it is fetched capped at
            # VIDEO_BYTES_MAX — never unbounded — same as a declared video.
            try:
                fetched = await asyncio.to_thread(
                    staff_oa_service.fetch_message_content, message_id, VIDEO_BYTES_MAX,
                )
            except staff_oa_service.ContentTooLarge:
                logger.warning("staff-bot photo failed: order=%s reason=oversize", order_id)
                return None, "oversize", "video"
            if fetched is None:
                logger.warning("staff-bot photo failed: order=%s reason=download", order_id)
                return None, "download", "image"
            data, content_type = fetched
            content_type = content_type or ""
            if content_type.startswith("video/"):
                mime = content_type if content_type in ("video/mp4", "video/quicktime") else "video/mp4"
                resolved_kind = "video"
            elif content_type.startswith("image/"):
                mime = content_type
                resolved_kind = "image"
            else:
                # Quoted content that is neither image/* nor video/* (a
                # quoted text message, LINE answering 4xx, etc.) — a plain
                # failed attach, same as any other download miss.
                logger.warning("staff-bot photo failed: order=%s reason=download", order_id)
                return None, "download", "image"
        else:
            fetched = await asyncio.to_thread(staff_oa_service.fetch_message_content, message_id)
            if fetched is None:
                logger.warning("staff-bot photo failed: order=%s reason=download", order_id)
                return None, "download", "image"
            data, content_type = fetched
            mime = content_type or "image/jpeg"
            resolved_kind = "image"

        result = await asyncio.to_thread(
            housekeeping_client.upload_photo, order_id, data, mime, actor_badge
        )
        if result is None or "error" in result:
            logger.warning("staff-bot photo failed: order=%s reason=upload", order_id)
            return None, "upload", resolved_kind
        logger.info("staff-bot photo attached: order=%s", order_id)
        return result, None, resolved_kind

    async def _upload_one_photo(
        self, order_id: int, message_id: str, actor_badge: str,
        chat_key: str = "", reply_token: str = "", kind: str = "image",
    ) -> Tuple[bool, str]:
        """One attach-window photo/video (rule A) OR one claimed-batch item
        (rule B, called without chat_key/reply_token — no ack of its own):
        upload it, then — since this runs as an awaited-to_thread coroutine
        on a loop TASK, never on a worker thread — file its ack directly, on
        the event loop, exactly like noting any other command. Returns
        ``(success, resolved_kind)``, for callers (the claimed batch's
        bounded wait) that need to know the outcome without an ack ever
        being filed for it.

        A video-specific failure (transcode/oversize) files its own note
        line instead of the generic count (see note_photo_ack); any other
        video failure ("other" in the spec) counts as a plain video failure,
        the video-worded parallel of the existing photo failure line — see
        the deviations list for why this is worded for video rather than
        reusing the photo string verbatim.
        """
        result, reason, resolved_kind = await self._do_upload(order_id, message_id, actor_badge, kind=kind)
        success = result is not None
        if chat_key and reply_token:
            total: Optional[int] = None
            note: Optional[str] = None
            failed = 0 if success else 1
            if success and isinstance(result, dict):
                total = _as_int(result.get("photoCount")) + _as_int(result.get("videoCount"))
            elif not success and resolved_kind == "video":
                if reason == "transcode":
                    note = VIDEO_TRANSCODE_FAILED_FMT.format(id=order_id)
                    failed = 0
                elif reason == "oversize":
                    note = VIDEO_OVERSIZE_FMT.format(id=order_id)
                    failed = 0
            self.debouncer.note_photo_ack(
                chat_key, reply_token, order_id, kind=resolved_kind,
                attached=1 if success else 0,
                failed=failed,
                total=total,
                note=note,
                quiet_seconds=PHOTO_ACK_QUIET_SECONDS,
            )
        return success, resolved_kind

    async def _upload_video_with_deadline(
        self, order_id: int, message_id: str, actor_badge: str,
        chat_key: str, reply_token: str,
    ) -> None:
        """An IN-WINDOW video (rule A): a transcode can outlive this event's
        (roughly 60 s-ish) reply token, so this races the upload against
        VIDEO_ACK_DEADLINE_SECONDS. Still running at the deadline: file the
        "กำลังประมวลผล" note now, on this about-to-expire token, and let the
        upload keep going in the background — its eventual real outcome is
        SILENT (no further ack; a later reply token was never reserved for
        it). Finishes within the deadline: file the normal ack right away, on
        this same token, exactly like any other in-window attach.
        """
        loop = asyncio.get_running_loop()
        upload_task = loop.create_task(
            self._do_upload(order_id, message_id, actor_badge, kind="video")
        )
        self._background_tasks.add(upload_task)
        upload_task.add_done_callback(self._background_tasks.discard)
        try:
            result, reason, _resolved_kind = await asyncio.wait_for(
                asyncio.shield(upload_task), timeout=VIDEO_ACK_DEADLINE_SECONDS,
            )
        except asyncio.TimeoutError:
            self.debouncer.note_photo_ack(
                chat_key, reply_token, order_id, kind="video",
                note=VIDEO_PROCESSING_FMT.format(id=order_id),
                quiet_seconds=PHOTO_ACK_QUIET_SECONDS,
            )
            return

        success = result is not None
        total: Optional[int] = None
        note: Optional[str] = None
        failed = 0 if success else 1
        if success and isinstance(result, dict):
            total = _as_int(result.get("photoCount")) + _as_int(result.get("videoCount"))
        elif not success:
            if reason == "transcode":
                note = VIDEO_TRANSCODE_FAILED_FMT.format(id=order_id)
                failed = 0
            elif reason == "oversize":
                note = VIDEO_OVERSIZE_FMT.format(id=order_id)
                failed = 0
        self.debouncer.note_photo_ack(
            chat_key, reply_token, order_id, kind="video",
            attached=1 if success else 0,
            failed=failed,
            total=total,
            note=note,
            quiet_seconds=PHOTO_ACK_QUIET_SECONDS,
        )

    async def _await_claimed_uploads(
        self, upload: "PendingUpload",
    ) -> Tuple[int, int, int, int, int, int]:
        """Rule B (photos-first, 2026-09-06): start the claimed batch's
        uploads as real loop tasks and wait up to CLAIMED_UPLOAD_WAIT_SECONDS
        for them, then return ``(photo_completed, photo_failed, photo_running,
        video_completed, video_failed, video_running)`` as of that moment —
        photos and videos counted separately (video support, 2026-09-06).
        ``asyncio.shield`` keeps a timeout from cancelling the tasks
        themselves — one still running at the timeout keeps going in the
        background exactly like any other spawned upload (a video's transcode
        wait, VIDEO_TRANSCODE_WAIT_SECONDS, routinely outlives this bounded
        wait, CLAIMED_UPLOAD_WAIT_SECONDS), it simply produces no ack when it
        eventually finishes (a buffered photo/video never had a reply token
        of its own — see spawn_photo_upload's docstring)."""
        loop = asyncio.get_running_loop()
        tasks: List[Tuple[asyncio.Task, str]] = []
        for message_id in upload.message_ids:
            declared_kind = (upload.kinds or {}).get(message_id, "image")
            task = loop.create_task(
                self._upload_one_photo(upload.order_id, message_id, upload.actor_badge, kind=declared_kind)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            tasks.append((task, declared_kind))
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(asyncio.shield(t) for t, _ in tasks), return_exceptions=True),
                    timeout=CLAIMED_UPLOAD_WAIT_SECONDS,
                )
            except asyncio.TimeoutError:
                pass

        photo_completed = photo_failed = photo_running = 0
        video_completed = video_failed = video_running = 0
        for task, declared_kind in tasks:
            if task.done() and not task.cancelled() and task.exception() is None:
                success, resolved_kind = task.result()
                bucket_kind = resolved_kind or declared_kind
                if bucket_kind == "video":
                    if success:
                        video_completed += 1
                    else:
                        video_failed += 1
                else:
                    if success:
                        photo_completed += 1
                    else:
                        photo_failed += 1
            elif task.done() and not task.cancelled():
                # An exception escaped _upload_one_photo — should not happen,
                # but stay defensive: count it as a failure of its declared
                # kind rather than crash the wait.
                if declared_kind == "video":
                    video_failed += 1
                else:
                    photo_failed += 1
            else:
                if declared_kind == "video":
                    video_running += 1
                else:
                    photo_running += 1
        return photo_completed, photo_failed, photo_running, video_completed, video_failed, video_running

    def submit_message(self, chat_key: str, reply_token: str) -> bool:
        return bool(self.debouncer.note_message(chat_key, reply_token))

    def submit_slot_digest(self, ref: SlotRef, reply_token: str, trigger: str) -> None:
        """File this group's slot digest, to go out after the chat settles.

        ``source_type="group"`` (a slot digest is structurally always a
        group's own — rooms and 1:1 chats have no slot digest at all) is what
        lets the guest-feedback confirm-delivered gate in :meth:`_reply` fire
        for a slot report that carried section (b), same as it always has for
        a group/room reply.
        """
        pending = self.debouncer.note_command(
            ref[0], COMMAND_SLOT_DIGEST, reply_token,
            quiet_seconds=SLOT_QUIET_SECONDS, slot_ref=ref, source_type="group",
        )
        pending.slot_trigger = trigger

    # -- internals ---------------------------------------------------------
    def _wake(self, delay: float) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (a script, a sync test): the state machine still holds
            # the pending entry, it simply will not be drained here.
            logger.debug("staff-bot has no running event loop to drain on")
            return
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._drain())

    async def _drain(self) -> None:
        while True:
            delay = self.debouncer.next_delay()
            if delay is None:
                return
            # Never sleep the whole delay in one go: a command landing in a
            # DIFFERENT chat with a nearer deadline would otherwise wait for
            # this one's timer.
            await asyncio.sleep(min(delay, DRAIN_SLICE_SECONDS))
            due = self.debouncer.pop_due()
            if not due:
                continue
            # Rule B (photos-first) can make _reply block for up to
            # CLAIMED_UPLOAD_WAIT_SECONDS while it waits on ITS OWN pending's
            # claimed-photo uploads. pop_due() can return entries for
            # DIFFERENT chats in the same tick (their deadlines only need to
            # fall within DRAIN_SLICE_SECONDS of each other, e.g. two groups
            # reporting around the same time) — awaiting them one at a time
            # would let one chat's photo wait sit in front of another chat's
            # reply and risk expiring that unrelated reply token. Run every
            # due entry concurrently instead; return_exceptions isolates them
            # so one chat's failure can never cancel or take down another's.
            results = await asyncio.gather(
                *(self._reply(pending) for pending in due), return_exceptions=True
            )
            for pending, result in zip(due, results):
                if isinstance(result, BaseException):
                    logger.warning(
                        "staff-bot reply task failed: chat=%s exc=%s",
                        pending.chat_key, result,
                    )

    async def _reply(self, pending: PendingReply) -> None:
        # A slot digest is the only pending that owns a database row, and the
        # row's fate is decided here — the one place where the send outcome is
        # known. Sent: promote to 'sent'. Anything else at all: delete it, so
        # the next qualifying message in the same window tries again.
        slot_ref = pending.slot_ref
        owns_mark = slot_ref is not None and COMMAND_SLOT_DIGEST in pending.commands

        if not staff_oa_service.is_enabled():
            # Fail closed. The webhook already answers 503 while the OA
            # credentials are missing, so this is unreachable in production —
            # but a pending reply outlives the request that filed it, and a
            # send attempt against a dark channel must never leave this
            # process.
            logger.debug("staff-bot reply skipped: the staff OA is dark")
            if owns_mark:
                await self._drop_mark(slot_ref, "send_failed")
            return
        request_ids: List[str] = []
        try:
            built = await asyncio.to_thread(
                build_reply, pending.commands, slot_ref[2] if slot_ref else None,
                request_ids, pending.actions, pending.photo_acks,
            )
        except Exception as exc:  # noqa: BLE001 — a reply must never crash the loop
            logger.warning("staff-bot could not build a reply: %s", exc)
            if owns_mark:
                await self._drop_mark(slot_ref, "send_failed")
            return

        # The ticket (if any) already exists in housekeeping and its photos
        # are already claimed out of the buffer by the time build_reply
        # returns, regardless of whether the LINE reply below succeeds — so
        # they are uploaded either way rather than lost. Rule B (photos-first,
        # 2026-09-06): WAIT for them, bounded, so the confirmation bubble
        # already in ``built.messages`` can be patched with the real outcome
        # before it goes out — never before ticket creation and never past
        # CLAIMED_UPLOAD_WAIT_SECONDS, so this stays inside the reporting
        # command's own reply-token life.
        for upload in built.pending_uploads:
            counts = await self._await_claimed_uploads(upload)
            if upload.message_index is not None and upload.message_index < len(built.messages):
                message = built.messages[upload.message_index]
                if upload.patch_kind == "group_confirmation":
                    _patch_group_confirmation_text(message, upload.group_order or {}, *counts)
                elif upload.patch_kind == "addphoto_ack":
                    _patch_addphoto_ack_text(message, upload.order_id, *counts)
                else:
                    _patch_confirmation_photo_line(message, *counts)

        if owns_mark and not built.slot_digest_included:
            # Housekeeping was dark or unreachable: the scheduled post says
            # nothing (never an error line into the group) and the slot
            # re-opens. Anything else in the burst — a palette, a digest
            # somebody actually typed — still goes out below.
            await self._drop_mark(slot_ref, "housekeeping_dark")
            owns_mark = False

        if not built.messages or not pending.reply_token:
            if owns_mark:
                await self._drop_mark(slot_ref, "send_failed")
            return
        try:
            await asyncio.to_thread(
                staff_oa_service.reply_messages, pending.reply_token, built.messages
            )
        except Exception as exc:  # noqa: BLE001 — LINE hiccup, not our problem
            logger.warning("staff-bot reply failed: %s", exc)
            if owns_mark:
                await self._drop_mark(slot_ref, "send_failed")
            return

        if owns_mark:
            await self._mark_sent(slot_ref, trigger=pending.slot_trigger)
        elif (
            slot_ref is not None
            and COMMAND_DIGEST in pending.commands
            and built.digest_available
        ):
            # Rule 7: a งานค้าง answer that landed inside an open window IS
            # this slot's digest. Mark it so the slot does not post a
            # near-duplicate a few minutes later. Only when it carried REAL
            # rows — the "ระบบงานซ่อมยังไม่เชื่อมต่อ" line told the group
            # nothing, and a window that saw only that is still owed a digest.
            await self._mark_sent(slot_ref, trigger=TRIGGER_COMMAND)

        # Confirm delivery only once LINE has ACCEPTED the reply, and only
        # for a group/room: a 1:1 ความคิดเห็นลูกค้า preview must never consume
        # the rows it showed (guest-feedback docs/CONTRACTS.md §15 rev 3).
        # ``request_ids`` is populated by build_reply in exactly two places —
        # COMMAND_REQUESTS (always source_type "user" now: report-only groups
        # never route that command any more) and COMMAND_SLOT_DIGEST's
        # section (b) (always source_type "group", see submit_slot_digest) —
        # so the source-type check alone is what decides "preview or real
        # delivery" for both.
        if request_ids and pending.source_type in ("group", "room"):
            await asyncio.to_thread(
                guest_feedback_client.confirm_delivered, request_ids
            )

    async def _mark_sent(self, ref: SlotRef, trigger: str) -> None:
        await asyncio.to_thread(
            _in_own_session, lambda db: mark_slot_sent(db, ref, trigger)
        )

    async def _drop_mark(self, ref: SlotRef, reason: str) -> None:
        await asyncio.to_thread(
            _in_own_session, lambda db: drop_slot_mark(db, ref, reason)
        )


_dispatcher = AsyncioBotDispatcher()


def get_dispatcher() -> AsyncioBotDispatcher:
    """The process-wide dispatcher (a seam tests replace wholesale)."""
    return _dispatcher


# ---------------------------------------------------------------------------
# Webhook entry point
# ---------------------------------------------------------------------------

def is_linked_employee(db: Session, line_user_id: str) -> bool:
    """Whether this LINE account maps to an ACTIVE employee."""
    if not line_user_id:
        return False
    return (
        db.query(Employee)
        .filter(
            Employee.line_user_id == line_user_id,
            Employee.is_active == True,  # noqa: E712
        )
        .first()
        is not None
    )


@dataclass(frozen=True)
class HandledEvent:
    """What the bot did with one webhook event.

    ``command`` — the event was a command and a reply is now pending.
    ``claims_reply_token`` — the bot intends to spend THIS event's reply
    token (it is a command, or the chat already had a reply pending and the
    token was refreshed to this newer one). A LINE reply token is single-use.
    """

    command: bool
    claims_reply_token: bool


_NOT_HANDLED = HandledEvent(command=False, claims_reply_token=False)


def _maybe_file_slot_digest(
    event: Dict,
    routed: RoutedMessage,
    db: Session,
    dispatcher,
) -> bool:
    """File the slot digest if this group message opens a window. Rule 3.

    Groups only — a room or a 1:1 has no slot digest. ANY message kind counts
    as the human heartbeat a scheduled post rides in on: text, sticker, photo,
    video, location (owner rule 2026-09-06: "stickers should count"). Nothing
    here reads, keeps or logs what was sent; the event is a timestamp and a
    sender id, which is all rule 3 needs. Commands never reach this function.
    """
    source = event.get("source")
    if not isinstance(source, dict) or source.get("type") != "group":
        return False
    if event.get("type") != "message":
        return False
    if not isinstance(event.get("message"), dict):
        return False
    if not routed.reply_token:
        return False

    triggered = evaluate_slot_trigger(
        db, routed.chat_key, event.get("timestamp"), source.get("userId") or "",
    )
    if triggered is None:
        return False
    ref, trigger = triggered
    if not file_slot_mark(db, ref, trigger):
        return False
    dispatcher.submit_slot_digest(ref, routed.reply_token, trigger)
    return True


def _maybe_handle_photo(
    event: Dict,
    routed: RoutedMessage,
    db: Session,
    dispatcher,
) -> None:
    """Buffer or silently attach one image OR video message (video support
    2026-09-06). Phase 3's core privacy rule: a photo is NEVER downloaded
    unless it is already tied to a ticket.

    A non-linked sender's photo is ignored outright — not buffered, not
    logged, not counted, no ack (rule A never applies to it: no order, no
    fetch). A linked sender's photo either attaches silently (an attach
    window is open for them in this chat: schedule the download+upload in the
    background using THIS photo event's own reply token, so the ack rule A
    adds files against it once the upload resolves) or is buffered as a bare
    message id (no bytes) for later claiming by a ticket created within
    :data:`PHOTO_BUFFER_TTL_SECONDS`.
    """
    message = event.get("message")
    message_type = message.get("type") if isinstance(message, dict) else None
    if message_type not in ("image", "video"):
        return
    kind = "video" if message_type == "video" else "image"
    source = event.get("source")
    user_id = (source or {}).get("userId") or ""
    if not user_id:
        return  # LINE gives no userId for some senders; nobody to attribute to
    identity = resolve_employee_identity(db, user_id)
    if identity is None:
        return
    message_id = message.get("id")
    if not isinstance(message_id, str) or not message_id:
        return

    order_id = get_attach_windows().refresh(routed.chat_key, user_id)
    if order_id is not None:
        dispatcher.spawn_photo_upload(
            order_id, message_id, identity.badge,
            chat_key=routed.chat_key, reply_token=routed.reply_token,
            kind=kind,
        )
        return
    get_photo_buffer().add(routed.chat_key, user_id, message_id, kind=kind)


def _enrich_ticket_command(routed: RoutedCommand, db: Session) -> RoutedCommand:
    """Resolve the sender's identity onto a ticket RoutedCommand, at route
    time — the request's ``db`` session is long closed by the time a
    debounced reply actually fires (up to 45 s later, see PendingReply)."""
    identity = resolve_employee_identity(db, routed.user_id)
    is_reception = bool(routed.user_id) and has_reception_grant(db, routed.user_id)
    if identity is None:
        return replace(routed, identity_known=False, is_reception=is_reception)
    return replace(
        routed,
        identity_known=True,
        badge=identity.badge,
        display_name=identity.display_name,
        property=identity.property,
        is_reception=is_reception,
    )


def handle_event_detail(event: Dict, db: Session) -> HandledEvent:
    """Route ONE webhook event into the debouncer.

    The privacy rule lives here: nothing is logged until an event has been
    recognised as a command, and then only its type, its source type and the
    chat id — never text, never a photo, never the speaker.

    GROUP/ROOM SOURCES ARE REPORT-ONLY (owner policy 2026-09-06: "command
    through chat is considered spam in HF Family group"), WITH ONE EXCEPTION —
    the @mention report carve-out (owner, 2026-09-06 evening) — that
    route_event already resolves into a RoutedCommand of its own; this
    function's only remaining group/room-specific job for an ordinary
    RoutedMessage is the DEBUG-only ignored-event log (never INFO: a group/
    room is never told anything about a command it tried). The photo buffer/
    attach-window path (``_maybe_handle_photo``) now runs for group/room
    messages too, exactly like 1:1 (rule 2, 2026-09-06 evening): a linked
    sender's photo/video is buffered (ids only, never downloaded) so a
    mention-report just after it can still claim it, and attaches silently
    once a mention-report's attach window is open.
    """
    if not isinstance(event, dict):
        return _NOT_HANDLED

    delivery_context = event.get("deliveryContext")
    if isinstance(delivery_context, dict) and delivery_context.get("isRedelivery"):
        # LINE re-sends a delivery it believes failed. Answering twice would
        # double-post into HF Family, so redeliveries are dropped outright.
        return _NOT_HANDLED

    if event.get("type") == "join":
        source = event.get("source")
        group_id = source.get("groupId") if isinstance(source, dict) else None
        if group_id:
            logger.info("staff-bot joined group %s", group_id)
        return _NOT_HANDLED

    source = event.get("source")
    source_type = source.get("type") if isinstance(source, dict) else ""
    event_type = event.get("type")

    routed = route_event(event, lambda user_id: is_linked_employee(db, user_id))
    if routed is None:
        if source_type in ("group", "room") and event_type == "postback":
            logger.debug(
                "staff-bot group ignored: type=postback chat=%s",
                _chat_key(source) if isinstance(source, dict) else "",
            )
        return _NOT_HANDLED

    dispatcher = get_dispatcher()
    filed = False
    if isinstance(routed, RoutedMessage):
        # Ordinary group chat is still the bot's cue for the SLOT digest: the
        # message is discarded (nothing about it is read, kept or logged), but
        # its clock and its sender decide whether this window is now due.
        filed = _maybe_file_slot_digest(event, routed, db, dispatcher)
        if source_type in ("group", "room"):
            # Report-only, still — never logged at INFO; a group/room is
            # never told anything about a command it tried.
            logger.debug(
                "staff-bot group ignored: type=message chat=%s", routed.chat_key,
            )
        # An image/video from a linked sender either attaches silently (an
        # open attach window — 1:1 always, group/room since the mention
        # carve-out) or joins the photo buffer — never downloaded here.
        _maybe_handle_photo(event, routed, db, dispatcher)
        refreshed = bool(dispatcher.submit_message(routed.chat_key, routed.reply_token))
        return HandledEvent(
            command=False, claims_reply_token=refreshed or filed,
        )

    if routed.command in TICKET_COMMANDS:
        # Ticket commands need the sender's identity/reception-grant, resolved
        # here (while ``db`` is still open) rather than at reply time.
        routed = _enrich_ticket_command(routed, db)

    logger.info(
        "staff-bot command: event=%s source=%s chat=%s",
        routed.event_type, routed.source_type, routed.chat_key,
    )
    dispatcher.submit_command(routed)
    return HandledEvent(command=True, claims_reply_token=True)


def handle_event(event: Dict, db: Session) -> bool:
    """Route ONE webhook event into the debouncer. Returns True for commands."""
    return handle_event_detail(event, db).command
