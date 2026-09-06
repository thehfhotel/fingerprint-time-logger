# Incident: ZK reader session evictions (2026-09-05)

Status: **root cause understood, mitigations shipped in `fix/zk-session-kick-alerting`; root network fix still open.**

## Symptom

Two Slack pages to `@winut.hf` in `#zk-time-sync` on 2026-09-05, each followed a few minutes later by a recovery message. As seen by the owner:

| Time (Bangkok) | Message |
|---|---|
| 09:02 | `✅ ZK Sync 1/1 OK ...` (daily heartbeat, drift 3.4s) |
| 16:17 | `🚨 ZK Sync 0/1 OK at 16:17 - Main Fingerprint Device: TCP packet invalid` (page, `@winut.hf`) |
| 16:22 | `✅ ZK Sync 1/1 OK at 16:22 - Main Fingerprint Device: ...` |
| 20:22 | `🚨 ZK Sync 0/1 OK at 20:22 - Main Fingerprint Device: TCP packet invalid` (page, `@winut.hf`) |
| 20:27 | `✅ ZK Sync 1/1 OK at 20:27 - Main Fingerprint Device: ...` |

Each page implied a full outage. The device journal shows something narrower: brief, repeated session evictions clustered around each page, not a continuous failure.

Note: every alert on 2026-09-05 fired under the OLD, pre-fix code — this PR's mitigations only deployed at the 20:32/20:42/20:58 restarts that night, after both episodes above had already happened. The old format paged on the *first* failed check (`🚨 ZK Sync 0/1 OK at HH:MM - ...`) and recovered with `✅ ZK Sync 1/1 OK at HH:MM - ...`, shown correctly in the table above. The NEW post-fix template strings shown elsewhere in this document (`🚨 ZK Sync FAILED N consecutive checks since HH:MM ...` / `✅ ZK Sync recovered at HH:MM after N failed checks ...`) are what WILL fire for a future incident under this PR's code — they are not what fired on 2026-09-05.

## Evidence

Container journal (`fingerprint-time-logger` on evergreen), `zk_session` / `background_scheduler` loggers, Bangkok local time. Full excerpt in the Appendix; source log is 497 lines covering 16:10–21:02 plus daily/weekly rollups.

### Episode 1 — 16:16:55 to ~16:20:47

- `16:16:55` `live_capture error (continuing): error('unpack requires a buffer of 8 bytes')` — the live-capture socket was cut mid-stream.
- Every reconnect attempt for the next ~4 minutes hit `ZKNetworkError('TCP packet invalid')` on the first real command (device accepts the TCP connect + `CMD_CONNECT` handshake, then drops the next packet) — visible on `catch_up`, `live_capture`, and `get_status_and_time`.
- `16:17:15` the 5-minute status/time job's own device call failed the same way → this is what triggered the Slack page at 16:17.
- `16:18:30` the 30-minute attendance import also failed: `[scheduler.import_attendance] catch_up failed: ZKNetworkError('TCP packet invalid')`.
- `16:19:35` a `catch_up` finally succeeds (`device_records=30617 new=0`) — condition partially clears.
- `16:20:00` one more eviction (`unpack requires a buffer of 8 bytes`), clears by `16:20:47`.
- `16:22:04` the 5-minute job succeeds cleanly → Slack recovery at 16:22.

### Episode 2 — 19:52:41 to ~20:29:40 (much longer, mostly hidden from Slack)

Evictions at `19:52:41`, `20:04:05`, `20:06:23`, `20:11:33`, `20:14:00`, `20:15:41`, `20:21:56`, `20:28:00` — eight instances of the same `unpack requires a buffer of 8 bytes` → `TCP packet invalid` → reconnect storm pattern, spanning ~40 minutes.

The 5-minute status job only *happened* to land on the device mid-eviction once, at `20:22:17` (`users fetch failed: ZKNetworkError('TCP packet invalid')`) → page at 20:22. Every other 5-minute tick (`19:57`, `20:02`, `20:07`, `20:12`, `20:17`, `20:27`) landed in a clean gap and reported `connected=True`. So Slack showed two isolated blips (16:xx and 20:22) while the underlying condition was active roughly 45 minutes total across the evening — the old alerting could not see the difference between "one probe glanced off the reader" and "sustained instability."

- `20:27:04` clean check → recovery message at 20:27.
- Record count: `30617` (16:xx) → `30619` (20:xx). No further growth through any eviction. Every `catch_up` after an eviction reports `new=0` — punches are not lost, they're recovered by the next successful catch-up.

### Log signatures and what they mean

| Line | Meaning |
|---|---|
| `[zk_session] live_capture error (continuing): error('unpack requires a buffer of 8 bytes')` | The live-capture socket read got a malformed/short reply — the device closed or repurposed the session out from under us. This is the eviction itself. |
| `[zk_session.stream] disconnect error: TCP packet invalid` | Our clean-disconnect attempt on the now-dead socket also fails, same root cause. |
| `[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')` | The reconnect landed inside the device's post-eviction confused state — TCP accepted, first command rejected. Retried automatically next cycle. |
| `[scheduler.import_attendance] catch_up failed: ZKNetworkError('TCP packet invalid')` / `[scheduler.refresh_status_and_time] ... users fetch failed` | A scheduled job's own device call landed during the window — this is what the old alerting saw as a bare failure. |
| `[zk_session.catch_up] device_records=N new=0 ...` | Confirms no data loss: the post-eviction re-read found nothing the DB didn't already have. |

### Probe reproductions (owner laptop → 192.168.100.209:4370)

| Probe | Time | Condition | Result |
|---|---|---|---|
| 1 | `21:00:02.18` connect+close (`nc -z 192.168.100.209 4370`) | fired while an import bulk read (`catch_up`) was in flight | `21:00:04.01` `catch_up failed: TCP packet invalid` + `disconnect error` in the container journal |
| 2 | `21:04:02.707` same bare connect+close | fired while the stream was idle (no ops queued) | `21:04:02.930` (223 ms later) `live_capture error: unpack requires a buffer of 8 bytes`; stream back up at `21:04:48` after catch-up |

**Conclusion**: any new TCP connection to `192.168.100.209:4370` evicts the active session — even a zero-byte port probe with no ZK protocol traffic at all. The device does not need a competing ZK client, just a second TCP client.

### History (journald since 2026-08-27, eviction/error lines per day)

| Day | Count | Note |
|---|---|---|
| Aug 28 | 5 | background rate |
| Aug 29 | 4 | background rate |
| Aug 30 | 3 | background rate |
| Aug 31 | 6 | background rate |
| Sep 1 | 120 | burst 01:32–02:07 (late-night dev/deploy session) |
| Sep 2 | 55 | burst, same pattern |
| Sep 3 | 0 | clean |
| Sep 4 | 0 | clean |
| Sep 5 | 138 | this incident (afternoon + evening) |

Bursts track periods of active development/deploy activity on the network, not a fixed clock time. Background rate is roughly 1 eviction/day even on quiet days.

## What was ruled out (and how)

| Candidate | Ruling | Evidence |
|---|---|---|
| Our code / deploy | Not the cause | Same image (`3febe8d`) ran clean for 3 days (Sep 3–4, 0 evictions); both episodes started well before tonight's deploys (20:32:09, 20:42:15, 20:58:30); PR CI never deploys (deploy job gates on push to `main`). |
| Owner's laptop as an unintentional second client | Not the cause | No Docker installed on it; no sockets to `:4370` at check time; tests run against a ZK simulator, not the real device. (The laptop *can* reach the device — it was used deliberately for probes 1 and 2.) |
| Other Claude sessions running today | Not the cause | Transcripts show only `docker exec ... python -c` probes against LINE/DNS/housekeeping containers; no `pyzk`, `nmap`, `arp-scan`, or device access anywhere. |
| evergreen host itself | Not the cause | No other container has `ZKTECO_HOST` set; no host cron/systemd timer/process talks to the device; ARP for `.209` stable at the ZKTeco MAC the whole time; every TCP connect from us completed a valid ZK handshake (rules out an IP conflict on `.209`). |
| Reception PC (front2, `.222`) | Not the cause | No ZK software installed; no sockets to the device at check time (checked 20:29). |
| HF Ville hosts | **Not verified** | SSH attempt timed out; owner declined a retry. Open item. |

## Identity of the external TCP client: **a monitoring container on evergreen**

Owner-confirmed 2026-09-06: a **monitoring container on evergreen** health-checks the ZK device by opening a TCP connection to `192.168.100.209:4370` on an interval. Because the reader allows only one session, each health check evicts the app's live-capture stream. The container runs intermittently, which is why evictions arrive in bursts (monitor up → evictions; monitor down → quiet, e.g. 2026-09-03/04 had zero) and why a sweep of evergreen on 2026-09-06 (~08:30, while it was down) found nothing connected to `:4370`.

The earlier "human opening a ZKTeco attendance app at shift changes" guess was **wrong** — nobody interacts with such an app. The shift-change *timing* was just when the monitor happened to be running. Ruled out along the way: the owner's laptop, other Claude/dev sessions, the reception PC, an HF Ville-side instance, and a network-wide scanner (see "What was ruled out").

## Alert behaviour: before vs. after

**Before** (production tonight): `SlackSyncNotifier` paged `@winut.hf` on the *first* failed 5-minute check, posted recovery on the next success, suppressed re-pages for 30 minutes, and heartbeated daily at 09:00. It never surfaced stream evictions at all — only a 5-minute job that happened to land on the device mid-eviction produced any signal, which is why two ~45-second-resolution events looked like two independent momentary blips instead of one 40-minute-wide condition.

**After** (this PR, `fix/zk-session-kick-alerting`):
- A page now requires **≥2 consecutive** failed 5-minute checks (not 1) — a single unlucky poll during a self-healing eviction no longer pages. Recovery message stays paired with an actual page; an unpaged single blip posts nothing to Slack (logged at INFO only).
- A new **non-paging "degraded" note** fires when **≥3 evictions** land in the trailing 60 minutes (rate-limited to once/hour), giving visibility into exactly the kind of extended, self-healing episode both of tonight's outages were, without waking anyone up.
- After an eviction the client now backs off before reconnecting (base 5 s, doubling to a 60 s cap while evictions keep recurring within 120 s of each other, resetting to base after a quiet gap) instead of retrying immediately — this reduces how often we're mid-reconnect exactly when a second client's probe lands, and avoids two clients ping-ponging the device's single session slot.
- `stream_kicks_last_hour` is now part of the cached `device_status`, so the eviction rate is visible without grepping the journal.

### The three new env vars

| Var | Type | Default | Meaning |
|---|---|---|---|
| `ZK_SYNC_PAGE_AFTER_FAILURES` | int | `2` | Consecutive failed 5-min checks before a paging Slack alert. |
| `ZK_KICK_BACKOFF_SECONDS` | float | `5.0` | Base wait after a live-capture eviction before reconnecting; doubles while evictions repeat within 120 s of each other, capped at 60 s; resets to base after a quiet gap. |
| `ZK_KICK_DEGRADED_THRESHOLD` | int | `3` | Evictions in the trailing 60 min that trigger a non-paging "degraded" Slack note (max once/hour). |

## Follow-ups (not in this PR)

1. **Network (the actual root fix)**: restrict TCP/4370 on `192.168.100.209` to evergreen (`192.168.100.228`) only, via switch/AP ACL or a firewall rule on the device's segment. Log drops so the external client can finally be identified.
2. **Fix the evergreen monitor (the real root cause)**: repoint the monitoring container's ZK health check away from a raw `:4370` connection to the app's cached status instead — the app exposes device health and `stream_kicks_last_hour` via `device_cache_service` (and its `/health` endpoint), refreshed every 5 minutes, so the monitor can report reader health without taking the reader's one session. This removes the eviction at source; the network ACL in item 1 then becomes a backstop.
3. Consider a cheaper post-eviction catch-up — today's re-sync re-reads the full ~30k-record device buffer on every single eviction, which is most of the ~45 s recovery cost.

**UPDATE 2026-09-06 — root cause found (supersedes the earlier "shift-change" guess).** Evictions continued past this writeup and past this PR's fix deploying, in bursts (21:14–21:30 on 2026-09-05, 07:08–07:39 on 2026-09-06) with quiet gaps between them and overnight. None fired a Slack page — the 5-minute check kept landing between bursts, exactly the under-reporting this PR's paging fix addresses, which confirms the degraded-note path (not the page path) is the right signal for this pattern. The owner then confirmed the cause: **a monitoring container on evergreen that health-checks the ZK device by connecting to `:4370` on an interval**. It was down when this session searched evergreen, which is why the search came up empty and why the bursts are intermittent (monitor up = evictions, monitor down = quiet). This supersedes the earlier guess of a human opening an attendance app — nobody interacts with one. Fix is follow-up #2 above.

---

## Appendix: curated evidence log excerpts

Verbatim excerpts from the container journal. Two windows plus the probe-1 context; full source is 497 lines.

```
----- container journal (Bangkok local time) 16:10:00-16:25:00, device/scheduler lines only -----
2026-09-05T16:12:00+07:00 INFO:apscheduler.executors.default:Running job "Refresh device status + time (and resync if drifted)
2026-09-05T16:12:04+07:00 INFO:app.services.zk_session:[zk_session.stream] streaming via live_capture
2026-09-05T16:16:55+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): error('unpack requires a buffer of 8 bytes')
2026-09-05T16:16:55+07:00 WARNING:app.services.zk_session:[zk_session.stream] disconnect error: TCP packet invalid
2026-09-05T16:16:55+07:00 INFO:app.services.zk_session:[zk_session.stream] connecting to 192.168.100.209:4370
2026-09-05T16:16:55+07:00 INFO:app.services.zk_session:[zk_session.stream] connected
2026-09-05T16:16:56+07:00 WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
2026-09-05T16:16:56+07:00 INFO:app.services.zk_session:[zk_session] streaming via live_capture
2026-09-05T16:16:56+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): ZKNetworkError('TCP packet invalid')
2026-09-05T16:16:56+07:00 WARNING:app.services.zk_session:[zk_session.stream] disconnect error: TCP packet invalid
2026-09-05T16:17:00+07:00 INFO:apscheduler.executors.default:Running job "Refresh device status + time (and resync if drifted)
2026-09-05T16:17:14+07:00 WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
2026-09-05T16:17:14+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): ZKNetworkError('TCP packet invalid')
2026-09-05T16:17:14+07:00 WARNING:app.services.zk_session:[zk_session.stream] disconnect error: TCP packet invalid
2026-09-05T16:17:15+07:00 INFO:app.services.zk_session:[zk_session.ops] connecting to 192.168.100.209:4370
2026-09-05T16:17:15+07:00 INFO:app.services.zk_session:[zk_session.ops] connected
2026-09-05T16:17:15+07:00 WARNING:app.services.zk_session:[zk_session.get_status_and_time] users fetch failed: ZKNetworkError('TCP packet invalid')
2026-09-05T16:17:15+07:00 WARNING:app.services.zk_session:[zk_session.ops] disconnect error: TCP packet invalid
2026-09-05T16:17:15+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] connected=True
2026-09-05T16:17:20+07:00 INFO:apscheduler.executors.default:Running job "Import attendance records
2026-09-05T16:18:01+07:00 INFO:app.services.zk_session:[zk_session.catch_up] device_records=30617 new=0 dedup_skipped=30153 sanity_skipped=464 unknown_badge=0 full=False
2026-09-05T16:18:01+07:00 INFO:app.services.zk_session:[zk_session] catch_up inserted=0
2026-09-05T16:18:30+07:00 ERROR:app.services.background_scheduler:[scheduler.import_attendance] catch_up failed: ZKNetworkError('TCP packet invalid')
2026-09-05T16:18:30+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): ZKNetworkError('TCP packet invalid')
2026-09-05T16:18:48+07:00 WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
2026-09-05T16:18:49+07:00 WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
2026-09-05T16:19:35+07:00 INFO:app.services.zk_session:[zk_session.catch_up] device_records=30617 new=0 dedup_skipped=30153 sanity_skipped=464 unknown_badge=0 full=False
2026-09-05T16:19:35+07:00 INFO:app.services.zk_session:[zk_session] catch_up inserted=0
2026-09-05T16:19:35+07:00 INFO:app.services.zk_session:[zk_session] streaming via live_capture
2026-09-05T16:20:00+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): error('unpack requires a buffer of 8 bytes')
2026-09-05T16:20:01+07:00 WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
2026-09-05T16:20:47+07:00 INFO:app.services.zk_session:[zk_session.catch_up] device_records=30617 new=0 dedup_skipped=30153 sanity_skipped=464 unknown_badge=0 full=False
2026-09-05T16:20:47+07:00 INFO:app.services.zk_session:[zk_session] catch_up inserted=0
2026-09-05T16:20:47+07:00 INFO:app.services.zk_session:[zk_session] streaming via live_capture
2026-09-05T16:22:00+07:00 INFO:apscheduler.executors.default:Running job "Refresh device status + time (and resync if drifted)
2026-09-05T16:22:04+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] connected=True
2026-09-05T16:22:04+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] drift=1.6s within tolerance — no resync

----- container journal (Bangkok local time) 19:50:00-20:00:00, device/scheduler lines only -----
2026-09-05T19:52:00+07:00 INFO:apscheduler.executors.default:Running job "Refresh device status + time (and resync if drifted)
2026-09-05T19:52:04+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] connected=True
2026-09-05T19:52:04+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] drift=2.8s within tolerance — no resync
2026-09-05T19:52:05+07:00 INFO:app.services.zk_session:[zk_session] streaming via live_capture
2026-09-05T19:52:41+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): error('unpack requires a buffer of 8 bytes')
2026-09-05T19:52:41+07:00 WARNING:app.services.zk_session:[zk_session.stream] disconnect error: TCP packet invalid
2026-09-05T19:52:41+07:00 WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
2026-09-05T19:52:41+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): ZKNetworkError('TCP packet invalid')
2026-09-05T19:52:59+07:00 WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
2026-09-05T19:52:59+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): ZKNetworkError('TCP packet invalid')
2026-09-05T19:53:00+07:00 WARNING:app.services.zk_session:[zk_session] catch_up failed (will retry next cycle): ZKNetworkError('TCP packet invalid')
2026-09-05T19:53:00+07:00 WARNING:app.services.zk_session:[zk_session] live_capture error (continuing): ZKNetworkError('TCP packet invalid')
2026-09-05T19:53:46+07:00 INFO:app.services.zk_session:[zk_session.catch_up] device_records=30619 new=0 dedup_skipped=30155 sanity_skipped=464 unknown_badge=0 full=False
2026-09-05T19:53:46+07:00 INFO:app.services.zk_session:[zk_session] catch_up inserted=0
2026-09-05T19:53:46+07:00 INFO:app.services.zk_session:[zk_session] streaming via live_capture
2026-09-05T19:57:00+07:00 INFO:apscheduler.executors.default:Running job "Refresh device status + time (and resync if drifted)
2026-09-05T19:57:04+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] connected=True
2026-09-05T19:57:04+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] drift=3.3s within tolerance — no resync

----- probe-1 context, container journal 20:57:00-21:02:00, device/scheduler lines only -----
2026-09-05T20:57:15+07:00 INFO:apscheduler.executors.default:Running job "Refresh device status + time (and resync if drifted)
2026-09-05T20:57:18+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] connected=True
2026-09-05T20:57:18+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] drift=2.9s within tolerance — no resync
2026-09-05T20:57:19+07:00 INFO:app.services.zk_session:[zk_session] streaming via live_capture
2026-09-05T20:58:30+07:00 INFO:app.services.zk_session:[zk_session] daemon thread started
2026-09-05T20:58:30+07:00 INFO:apscheduler.scheduler:Scheduler started
2026-09-05T20:58:30+07:00 INFO:app.services.background_scheduler:Background scheduler started: status+time (merged) every 5 min, attendance import every 30 min, drift tolerance 5.0s
2026-09-05T20:58:32+07:00 INFO:app.services.zk_session:[zk_session.stream] connecting to 192.168.100.209:4370
2026-09-05T20:58:32+07:00 INFO:app.services.zk_session:[zk_session.stream] connected
2026-09-05T20:58:50+07:00 INFO:apscheduler.executors.default:Running job "Import attendance records
2026-09-05T20:59:18+07:00 INFO:app.services.zk_session:[zk_session.catch_up] device_records=30619 new=0 dedup_skipped=30155 sanity_skipped=464 unknown_badge=0 full=False
2026-09-05T20:59:18+07:00 INFO:app.services.zk_session:[zk_session] catch_up inserted=0
2026-09-05T20:59:22+07:00 INFO:app.services.zk_session:[zk_session.ops] connecting to 192.168.100.209:4370
2026-09-05T20:59:22+07:00 INFO:app.services.zk_session:[zk_session.ops] connected
2026-09-05T20:59:24+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] connected=True
2026-09-05T20:59:24+07:00 INFO:app.services.background_scheduler:[scheduler.refresh_status_and_time] drift=3.1s within tolerance — no resync
2026-09-05T21:00:04+07:00 INFO:app.services.zk_session:[zk_session] drained 2 ops
2026-09-05T21:00:04+07:00 ERROR:app.services.background_scheduler:[scheduler.import_attendance] catch_up failed: ZKNetworkError('TCP packet invalid')
2026-09-05T21:00:04+07:00 WARNING:app.services.zk_session:[zk_session.ops] disconnect error: TCP packet invalid
2026-09-05T21:00:04+07:00 WARNING:app.services.background_scheduler:[scheduler.import_attendance] failed (ZKNetworkError('TCP packet invalid')); startup retry scheduled at 2026-09-05T21:03:04.010727
2026-09-05T21:00:04+07:00 INFO:app.services.zk_session:[zk_session.stream] connected
2026-09-05T21:00:04+07:00 INFO:app.services.zk_session:[zk_session] streaming via live_capture
```

(Probe 1 fired at `21:00:02.18` from the owner's laptop and is what produced the `21:00:04.01` `catch_up failed` line above; probe 2 fired at `21:04:02.707`, outside this excerpt window, producing `live_capture error: unpack requires a buffer of 8 bytes` at `21:04:02.930`.)
