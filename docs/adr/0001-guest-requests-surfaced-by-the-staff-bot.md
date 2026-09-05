# 0001. Guest requests are surfaced by the staff bot

Date: 2026-09-05
Status: Accepted

## Context

Guest-feedback (`feedback.thehfhotel.org`) collects guest requests on a
public site and needs to reach staff on LINE. LINE allows exactly **one
Official Account per group chat**, and the staff LINE group already hosts
the Employee Hub OA (this repo, `app/services/staff_oa_service.py`) — so
guest-feedback cannot be invited into that group with an OA of its own.

Two earlier revisions of guest-feedback's `docs/CONTRACTS.md` §15 tried to
route around that constraint from guest-feedback's side:

- **rev 1**: guest-feedback held its own LINE channel credentials and posted
  directly.
- **rev 2**: this webhook (`app/api/staff_oa.py`) relayed LINE group and 1:1
  events to guest-feedback, fire-and-forget, reduced to ids only
  (`group_event_forward_payload` / `forward_group_events*`, PR #28/#30).
  guest-feedback then replied into the group using the staff OA's own
  channel access token — a second sender holding this app's credentials, and
  a race for a single-use reply token that had to be arbitrated in this
  webhook (`HandledEvent.claims_reply_token`).

Both put a second service in a position to speak as "HF ภายใน", or to hold
its credentials. rev 2 also left the 1:1 preview permanently degraded: the
staff bot answers every 1:1 text message it receives, so it claimed nearly
every 1:1 reply token before the relay could use it (documented as a known
limitation, never resolved).

## Decision

Exactly **one** service ever speaks as the "HF ภายใน" Official Account: the
Employee Hub bot in this repo (`app/services/staff_bot.py`). guest-feedback
holds no LINE token, never replies, never pushes — it is a **queue with two
internal endpoints** (`GET /api/internal/line/pending`,
`POST /api/internal/line/delivered`) that this bot reads and confirms
(`app/services/guest_feedback_client.py`), guest-feedback docs/CONTRACTS.md
§15 rev 3.

Consequences of "one responder":

1. **No credential duplication.** guest-feedback never sees a LINE channel
   secret or access token; the shared secret is a plain reader token
   (`GUEST_FEEDBACK_READER_SECRET`), the same shape as
   `HOUSEKEEPING_STAFF_BOT_TOKEN`.
2. **No reply-token race.** There is only one consumer of a webhook event's
   reply token again, so `HandledEvent.claims_reply_token` and the
   `withhold_reply_token` arbitration this rev 2 needed are gone along with
   the relay itself.
3. **The command follows the digest's shape exactly.** `คำขอลูกค้า` (words:
   `คำขอ` / `คำขอลูกค้า` / `guest requests`; postback `cmd=requests`; a
   palette button) renders guest-feedback's own pre-formatted text and fails
   closed with one fixed Thai line — no new pattern for staff to learn.
4. **A group auto-offer, not just an ask.** Because the bot itself now knows
   whether requests are pending, plain group chatter (not just a summon) can
   surface them the moment one exists — cached 10 s per chat so it does not
   turn every message into an outbound read.
5. **1:1 stays a preview.** A 1:1 reply renders the identical list but never
   calls `confirm_delivered` — only a group/room reply, once LINE has
   accepted it, marks rows delivered. A person checking privately must never
   consume rows the group still needs to see.
6. **The rev 2 forwarder is fully retired**: `group_event_forward_payload`,
   `forward_group_events`, `forward_group_events_in_background`, the
   forwarding block in `app/api/staff_oa.py`, and `GUEST_FEEDBACK_LINE_URL` /
   `GUEST_FEEDBACK_LINE_SECRET` are deleted, replaced by
   `GUEST_FEEDBACK_BASE_URL` / `GUEST_FEEDBACK_READER_SECRET`.

## Consequences

- guest-feedback carries no outbound LINE dependency at all; a LINE incident
  cannot take its own UI down, and rotating this app's LINE credentials never
  touches guest-feedback.
- The staff bot's existing fail-closed and privacy rules (one fixed Thai line
  per failure mode; never log guest text) extend unchanged to guest requests.
- The known 1:1-reply-token limitation from rev 2 is moot: there is no second
  sender left to starve of tokens.
