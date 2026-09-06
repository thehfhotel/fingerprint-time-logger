"""HF ภายใน — the staff LINE bot: command router, rendering, debounce.

The Employee Hub's Official Account is now also a BOT. It is summoned in the
all-staff LINE group (HF Family) or talked to 1:1, and it answers with the
open แจ้งซ่อม digest that the housekeeping app owns. This module is everything
between the webhook and the reply: the summon grammar, the command router,
the Flex palette, the digest text, and the debounce state machine.

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
   reply goes out after 15 s of quiet in a group (2 s in 1:1), and at the
   latest 45 s after the first trigger — LINE's reply tokens are short
   lived, so the cap is not optional. Two commands in one burst coalesce
   into ONE reply carrying both messages.
3. DISCARD BEFORE LOGGING. The webhook sees all of HF Family's traffic.
   Non-command chat is dropped without a log line of any kind, and a command
   logs only the event type, the source type and the chat id — never the
   message text, never a photo, never who said it. That is a privacy
   commitment to staff, enforced at the top of :func:`handle_event`.

PHASE 2 (2026-09-05) adds the SLOT DIGEST: four daily Bangkok windows in which
the งานค้าง digest is posted into a GROUP exactly once, piggybacking on
whatever the humans were already saying so it still rides a free reply token.
It is the one thing here that waits — SLOT_QUIET_SECONDS of quiet, so it never
races reception's report burst — and the one thing that keeps state in the
database (``staff_bot_slot_marks``), because "once per slot" has to survive a
restart. A window nobody talks in is skipped, and a window in which
housekeeping is dark posts NOTHING: a scheduled message must never spam an
error line into HF Family. See "Slot digest" below and hf-erp ADR 0007.

PLAIN THAI, NO EMOJI, in every bot-facing string (house rule, same as
staff_oa_menu / hk_escalation_service). Anything human-typed that reaches a
message goes through :func:`strip_pictographs` first.

FAIL CLOSED: with HOUSEKEEPING_STAFF_BOT_TOKEN unset the digest read is dark
and the bot says one fixed Thai line rather than guessing or going quiet
(see app/services/housekeeping_client.py). The same rule covers the guest
requests read: with either GUEST_FEEDBACK_BASE_URL or
GUEST_FEEDBACK_READER_SECRET unset, คำขอลูกค้า answers its own fixed Thai line
(see app/services/guest_feedback_client.py).

GUEST REQUESTS (คำขอลูกค้า): since guest-feedback docs/CONTRACTS.md §15 rev 3
("the Employee Hub bot is the ONLY responder"), this bot is also the sole
sender for guest requests raised on the public feedback site. It reads and
confirms them from guest-feedback (never holds them, never owns a queue) and
answers only with reply tokens, exactly like the housekeeping digest above.
A group message — summoned or not — auto-offers the pending list when one
exists; a 1:1 request renders the identical text as a PREVIEW and never
confirms delivery, so pending rows are not silently consumed by someone
checking privately.

TESTABILITY: :class:`ReplyDebouncer` is a pure state machine — an injectable
clock, an injectable scheduler, no I/O, no timers — so the debounce rules are
unit tested without waiting a single real second.
:class:`AsyncioBotDispatcher` is the thin adapter that gives it a real loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
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
PALETTE_REQUESTS_BUTTON_LABEL = "คำขอลูกค้า"
PALETTE_REQUESTS_BUTTON_DISPLAY_TEXT = "คำขอลูกค้า"

# Housekeeping dark, unreachable, or refusing. ONE fixed line: staff get a
# plain Thai sentence, never a status code and never silence.
DIGEST_UNAVAILABLE_TEXT = "ระบบงานซ่อมยังไม่เชื่อมต่อ ลองใหม่อีกครั้งภายหลัง"

# Guest-feedback dark, unreachable, or refusing — the same fail-closed rule
# as the digest above, one fixed Thai line.
REQUESTS_UNAVAILABLE_TEXT = "ยังอ่านคำขอลูกค้าไม่ได้ค่ะ ลองใหม่อีกครั้ง"
# Reachable, but nothing is waiting.
REQUESTS_NONE_TEXT = "ยังไม่มีคำขอที่รอส่งค่ะ"

# How long a "no pending guest requests" (or "yes") answer from guest-feedback
# is trusted before asking again, per chat — group chatter must not hammer
# the endpoint on every single message.
REQUESTS_AUTO_TRIGGER_CACHE_SECONDS = 10.0

THAI_MONTH_ABBREVIATIONS = (
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.",
)


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

# "น้องคะ" / "น้อง ครับ" ... — the summon in a group chat. Anchored at the
# start and the particle is REQUIRED, which is what keeps ordinary chat about
# a น้อง (e.g. "น้องเอาข้าวไหม") from waking the bot.
SUMMON_PATTERN = re.compile(r"^น้อง\s*(?:คะ|ค่ะ|ครับ|คับ)")

COMMAND_PALETTE = "palette"
COMMAND_DIGEST = "digest"
COMMAND_ONBOARDING = "onboarding"
COMMAND_REQUESTS = "requests"

# Phase 2. NOT a command anybody can type: it is filed by the slot rules
# below when the bot decides this group's window is due. It renders the same
# digest as COMMAND_DIGEST, under a "สรุปงานซ่อมค้างประจำรอบ..." line.
COMMAND_SLOT_DIGEST = "slot_digest"

# Words that run the digest directly, with or without a summon in front.
DIGEST_WORDS = frozenset({"งานค้าง", "งานซ่อมค้าง", "แจ้งซ่อมค้าง"})

# Words that ask for the guest-requests list directly.
REQUEST_WORDS = frozenset({"คำขอ", "คำขอลูกค้า", "guest requests"})

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

def _strip_self_mentions(text: str, message: Dict) -> Optional[str]:
    """Remove the bot's own @-mention spans, or None when it was not mentioned.

    LINE gives each mentionee an ``index``/``length`` into the message text,
    and marks the bot's own mention with ``isSelf``. Spans are removed back to
    front so earlier indices stay valid.
    """
    mention = message.get("mention")
    if not isinstance(mention, dict):
        return None
    mentionees = mention.get("mentionees")
    if not isinstance(mentionees, list):
        return None

    spans = []
    for mentionee in mentionees:
        if not isinstance(mentionee, dict) or not mentionee.get("isSelf"):
            continue
        index = mentionee.get("index")
        length = mentionee.get("length")
        if isinstance(index, int) and isinstance(length, int) and length >= 0:
            spans.append((index, length))
    if not spans:
        return None

    remainder = text
    for index, length in sorted(spans, reverse=True):
        remainder = remainder[:index] + remainder[index + length:]
    return remainder.strip()


def summon_remainder(text: str, message: Optional[Dict] = None) -> Optional[str]:
    """What the summoner said AFTER summoning, or None if this was not a summon.

    Two ways to summon in a group: the น้อง + particle opener, or an
    @-mention of the bot. An empty string means "summoned, said nothing
    else" — which is a palette, not a miss, so the caller must distinguish
    ``""`` from ``None``.
    """
    stripped = (text or "").strip()
    match = SUMMON_PATTERN.match(stripped)
    if match:
        return stripped[match.end():].strip()
    if isinstance(message, dict):
        return _strip_self_mentions(text or "", message)
    return None


def command_for_words(words: str) -> str:
    """Map what was said to a command. Anything unrecognised opens the palette."""
    stripped = words.strip()
    if stripped in REQUEST_WORDS:
        return COMMAND_REQUESTS
    if stripped in DIGEST_WORDS:
        return COMMAND_DIGEST
    return COMMAND_PALETTE


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
    # Which slot (if any) this event falls in. Groups only: rooms and 1:1
    # chats have no slot digest at all.
    slot_ref = (
        slot_ref_for_event(chat_key, event.get("timestamp"))
        if source_type == "group" else None
    )

    if event_type == "join":
        # Learn the group id — the ONLY thing this event is good for, and the
        # one time the bot writes an id into the log on purpose (the rollout
        # needs it). Logged by the caller; nothing is answered.
        return None

    if event_type == "postback":
        if not chat_key or not reply_token:
            return None
        command = _postback_command(event.get("postback"))
        if command is None:
            return None
        return RoutedCommand(
            chat_key=chat_key, command=command, reply_token=reply_token,
            quiet_seconds=quiet_seconds_for(source_type),
            event_type="postback", source_type=source_type,
            slot_ref=slot_ref,
        )

    if event_type != "message":
        return None
    if not chat_key or not reply_token:
        return None

    message = event.get("message")
    if not isinstance(message, dict) or message.get("type") != "text":
        # A photo/sticker/anything else is still a message in this chat, so
        # it restarts the quiet timer — it just never becomes a command.
        return RoutedMessage(chat_key=chat_key, reply_token=reply_token)

    text = message.get("text") or ""

    if source_type == "user":
        # 1:1. Reads are open but the bot only talks to people it knows; a
        # stranger gets the onboarding pointer instead of a menu.
        if not is_known_user(chat_key):
            return RoutedCommand(
                chat_key=chat_key, command=COMMAND_ONBOARDING,
                reply_token=reply_token,
                quiet_seconds=quiet_seconds_for(source_type),
                event_type="message", source_type=source_type,
            )
        return RoutedCommand(
            chat_key=chat_key, command=command_for_words(text),
            reply_token=reply_token,
            quiet_seconds=quiet_seconds_for(source_type),
            event_type="message", source_type=source_type,
        )

    # Group / room: only a summon is a command. Everything else is staff
    # talking to each other and is discarded (it may still refresh a pending
    # reply, which needs no knowledge of what was said).
    remainder = summon_remainder(text, message)
    if remainder is None:
        return RoutedMessage(chat_key=chat_key, reply_token=reply_token)
    return RoutedCommand(
        chat_key=chat_key,
        command=COMMAND_PALETTE if remainder == "" else command_for_words(remainder),
        reply_token=reply_token,
        quiet_seconds=quiet_seconds_for(source_type),
        event_type="message", source_type=source_type,
        slot_ref=slot_ref,
    )


def _postback_command(postback) -> Optional[str]:
    """``cmd=palette`` / ``cmd=digest`` / ``cmd=requests`` out of a postback's
    urlencoded data."""
    if not isinstance(postback, dict):
        return None
    data = postback.get("data")
    if not isinstance(data, str) or not data:
        return None
    values = parse_qs(data).get("cmd") or []
    command = values[0] if values else ""
    if command in (COMMAND_PALETTE, COMMAND_DIGEST, COMMAND_REQUESTS):
        return command
    return None


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


def render_slot_digest(slot_id: str, payload: Optional[Dict]) -> Optional[str]:
    """The slot digest text, or None when there is nothing to post.

    None is the whole of the "housekeeping is dark" rule: a digest somebody
    ASKED for says "ระบบงานซ่อมยังไม่เชื่อมต่อ ..." (they are owed an answer),
    but a scheduled post nobody asked for stays silent rather than dropping an
    error line into HF Family every window. The caller deletes the slot mark
    when this returns None, so the window re-triggers on the next message.
    """
    slot = SLOTS_BY_ID.get(slot_id or "")
    if slot is None or not isinstance(payload, dict):
        return None
    return (
        SLOT_DIGEST_PREFIX.format(label=slot.label)
        + "\n\n"
        + render_digest(payload)
    )


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


def render_requests(payload: Optional[Dict]) -> str:
    """The คำขอลูกค้า text for the guest-feedback pending JSON.

    ``None`` (either env unset, timeout, non-2xx, malformed body — see
    guest_feedback_client.fetch_pending) renders the one fixed Thai line:
    staff are told the read failed, never given a status code and never left
    guessing at silence. A reachable read with nothing waiting gets its own
    plain line; otherwise guest-feedback's own ``text`` (already formatted,
    already Thai) is printed as-is — this bot does not reshape it.
    """
    if payload is None:
        return REQUESTS_UNAVAILABLE_TEXT
    if _as_int(payload.get("count")) <= 0:
        return REQUESTS_NONE_TEXT
    text = payload.get("text")
    return text if isinstance(text, str) else REQUESTS_UNAVAILABLE_TEXT


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
                text = render_slot_digest(slot_id, payload)
                if text is not None:
                    messages.append({"type": "text", "text": text})
                    slot_included = True
                    continue
                if COMMAND_DIGEST not in wanted:
                    continue  # scheduled + dark: say nothing at all
            messages.append({"type": "text", "text": render_digest(payload)})
        elif command == COMMAND_REQUESTS and command in wanted:
            payload = guest_feedback_client.fetch_pending()
            messages.append({"type": "text", "text": render_requests(payload)})
            if confirmed_request_ids is not None:
                confirmed_request_ids.extend(_request_ids(payload))
    return BuiltReply(messages[:MAX_REPLY_MESSAGES], slot_included, digest_available)


def build_messages(
    commands: Sequence[str],
    confirmed_request_ids: Optional[List[str]] = None,
    slot_id: Optional[str] = None,
) -> List[Dict]:
    """The message objects for one coalesced reply, in canonical order.

    ``confirmed_request_ids`` stays the SECOND positional parameter (the
    guest-requests call shape); ``slot_id`` selects the slot digest prefix.
    """
    return build_reply(commands, slot_id, confirmed_request_ids).messages


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
    # from. Used only to gate the guest-requests delivery confirm: a group or
    # room reply confirms, a 1:1 reply is a preview and never does.
    source_type: str = ""

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
    ) -> PendingReply:
        """Record a command: create or MERGE INTO this chat's pending reply."""
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

    def submit_command(self, command: RoutedCommand) -> None:
        self.debouncer.note_command(
            command.chat_key, command.command, command.reply_token,
            quiet_seconds=command.quiet_seconds,
            slot_ref=command.slot_ref,
            source_type=command.source_type,
        )

    def submit_message(self, chat_key: str, reply_token: str) -> bool:
        return bool(self.debouncer.note_message(chat_key, reply_token))

    def submit_slot_digest(self, ref: SlotRef, reply_token: str, trigger: str) -> None:
        """File this group's slot digest, to go out after the chat settles."""
        pending = self.debouncer.note_command(
            ref[0], COMMAND_SLOT_DIGEST, reply_token,
            quiet_seconds=SLOT_QUIET_SECONDS, slot_ref=ref,
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
            for pending in self.debouncer.pop_due():
                await self._reply(pending)

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
                request_ids,
            )
        except Exception as exc:  # noqa: BLE001 — a reply must never crash the loop
            logger.warning("staff-bot could not build a reply: %s", exc)
            if owns_mark:
                await self._drop_mark(slot_ref, "send_failed")
            return

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
        # for a group/room: a 1:1 คำขอลูกค้า answer is a preview and must
        # never consume the rows it showed (guest-feedback docs/CONTRACTS.md
        # §15 rev 3).
        if (
            COMMAND_REQUESTS in pending.commands
            and request_ids
            and pending.source_type in ("group", "room")
        ):
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


class PendingRequestsGate:
    """Caches "does guest-feedback have pending guest requests" per chat.

    Group chatter of any kind is a candidate to auto-offer คำขอลูกค้า into
    (guest-feedback docs/CONTRACTS.md §15 rev 3), but every ordinary message
    checking guest-feedback would hammer it. A TTL cache keyed by chat_key
    answers from the last real check for
    :data:`REQUESTS_AUTO_TRIGGER_CACHE_SECONDS`, injectable clock so tests
    need not sleep.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = REQUESTS_AUTO_TRIGGER_CACHE_SECONDS,
        fetch: Callable[[], Optional[Dict]] = guest_feedback_client.fetch_pending,
    ):
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._fetch = fetch
        self._cache: Dict[str, tuple] = {}  # chat_key -> (expires_at, has_pending)

    def has_pending(self, chat_key: str) -> bool:
        now = self._clock()
        cached = self._cache.get(chat_key)
        if cached is not None and cached[0] > now:
            return cached[1]
        payload = self._fetch()
        has_pending = isinstance(payload, dict) and _as_int(payload.get("count")) > 0
        self._cache[chat_key] = (now + self._ttl_seconds, has_pending)
        return has_pending


_requests_gate = PendingRequestsGate()


def get_requests_gate() -> PendingRequestsGate:
    """The process-wide guest-requests cache (a seam tests replace wholesale)."""
    return _requests_gate


def _maybe_upgrade_to_requests(routed: RoutedMessage, event: Dict) -> Routed:
    """A non-summon GROUP/ROOM message becomes COMMAND_REQUESTS when guest-
    feedback has something pending — a summon is untouched (it never reaches
    here as a RoutedMessage) and a 1:1 never reaches here at all (route_event
    always turns a 1:1 text message into a command)."""
    source = event.get("source")
    source_type = (source or {}).get("type") or ""
    if source_type not in ("group", "room"):
        return routed
    if not get_requests_gate().has_pending(routed.chat_key):
        return routed
    return RoutedCommand(
        chat_key=routed.chat_key,
        command=COMMAND_REQUESTS,
        reply_token=routed.reply_token,
        quiet_seconds=quiet_seconds_for(source_type),
        event_type=event.get("type") or "message",
        source_type=source_type,
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

    Groups only — a room or a 1:1 has no slot digest — and text only: a photo
    or a sticker refreshes a pending reply (that is ``routed``'s job) but is
    not the kind of traffic a scheduled post rides in on. Nothing here reads,
    keeps or logs what was said; the message is a heartbeat and a sender id,
    which is all rule 3 needs.
    """
    source = event.get("source")
    if not isinstance(source, dict) or source.get("type") != "group":
        return False
    if event.get("type") != "message":
        return False
    message = event.get("message")
    if not isinstance(message, dict) or message.get("type") != "text":
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


def handle_event_detail(event: Dict, db: Session) -> HandledEvent:
    """Route ONE webhook event into the debouncer.

    The privacy rule lives here: nothing is logged until an event has been
    recognised as a command, and then only its type, its source type and the
    chat id — never text, never a photo, never the speaker. The one piece of
    I/O route_event itself may not do — checking guest-feedback for pending
    คำขอลูกค้า so plain group chat can auto-offer them — happens here, right
    after routing, so route_event stays pure.
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

    routed = route_event(event, lambda user_id: is_linked_employee(db, user_id))
    if routed is None:
        return _NOT_HANDLED

    dispatcher = get_dispatcher()
    filed = False
    if isinstance(routed, RoutedMessage):
        # Ordinary group chat is still the bot's cue for the SLOT digest: the
        # message is discarded (nothing about it is read, kept or logged), but
        # its clock and its sender decide whether this window is now due.
        filed = _maybe_file_slot_digest(event, routed, db, dispatcher)
        # ...and, independently, the moment to auto-offer pending guest
        # requests (ADR 0001): a plain message may become a command here. A
        # slot filed above coalesces into that command's immediate reply.
        routed = _maybe_upgrade_to_requests(routed, event)
    if isinstance(routed, RoutedMessage):
        refreshed = bool(dispatcher.submit_message(routed.chat_key, routed.reply_token))
        return HandledEvent(
            command=False, claims_reply_token=refreshed or filed,
        )

    logger.info(
        "staff-bot command: event=%s source=%s chat=%s",
        routed.event_type, routed.source_type, routed.chat_key,
    )
    dispatcher.submit_command(routed)
    return HandledEvent(command=True, claims_reply_token=True)


def handle_event(event: Dict, db: Session) -> bool:
    """Route ONE webhook event into the debouncer. Returns True for commands."""
    return handle_event_detail(event, db).command
