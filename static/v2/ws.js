/**
 * v2 WebSocket wrapper.
 *
 * The legacy adapter at /static/js/websocket-adapter.js depends on a global
 * `appConfig` loader that the v2 pages don't include — so rather than pull
 * in that surface, this module re-implements the same connection pattern
 * (path, protocol, exponential backoff) in ~70 lines, scoped to the message
 * types v2 cares about.
 *
 *   const stop = V2WS.connectWS({
 *     // type === "attendance_realtime".
 *     //   punch   = the TOP-LEVEL broadcast object:
 *     //             { badge_number, display_name, timestamp, punch_type, … }
 *     //   summary = the dashboard summary dict that rides in `.data`,
 *     //             or null when the backend's summary refresh failed.
 *     //             Optional — ignore the 2nd arg if you don't need it.
 *     onPunch:  (punch, summary) => { ... },
 *     onStatus: (s) => { ... },   // { connected: bool, code?: number }
 *   });
 *   // later: stop();
 */
(function () {
  "use strict";

  const PING_INTERVAL_MS = 30000;
  const MIN_BACKOFF_MS = 1000;
  const MAX_BACKOFF_MS = 30000;

  function wsUrl() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    // Pages live under /fingerprintlogs/v2/* — WS is /fingerprintlogs/ws.
    const basePath = window.location.pathname.startsWith("/fingerprintlogs")
      ? "/fingerprintlogs"
      : "";
    return `${proto}//${window.location.host}${basePath}/ws`;
  }

  function connectWS(handlers) {
    const onPunch = (handlers && handlers.onPunch) || function () {};
    const onStatus = (handlers && handlers.onStatus) || function () {};

    let ws = null;
    let stopped = false;
    let attempt = 0;
    let pingTimer = null;
    let reconnectTimer = null;

    function clearTimers() {
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    }

    function scheduleReconnect() {
      if (stopped) return;
      attempt += 1;
      const delay = Math.min(
        MAX_BACKOFF_MS,
        MIN_BACKOFF_MS * Math.pow(2, attempt - 1)
      );
      reconnectTimer = setTimeout(open, delay);
    }

    function open() {
      if (stopped) return;
      try {
        ws = new WebSocket(wsUrl());
      } catch (e) {
        console.error("[v2 ws] construct failed", e);
        scheduleReconnect();
        return;
      }

      ws.onopen = function () {
        attempt = 0;
        onStatus({ connected: true });
        // Lightweight keepalive — the backend echoes pongs.
        pingTimer = setInterval(function () {
          if (ws && ws.readyState === WebSocket.OPEN) {
            try { ws.send(JSON.stringify({ type: "ping" })); } catch (_) {}
          }
        }, PING_INTERVAL_MS);
      };

      ws.onmessage = function (evt) {
        let msg;
        try { msg = JSON.parse(evt.data); }
        catch (_) { return; }

        // Broadcast shape — verified against app/services/zk_session.py
        // (_broadcast_realtime, ~line 483):
        //
        //   { type: "attendance_realtime",
        //     badge_number, display_name, timestamp, punch_type,   <- TOP level
        //     data: <dashboard summary dict | null>,               <- NOT the punch
        //     synced_records: 1, message: "บันทึกใหม่: …" }
        //
        // The punch fields are at the TOP level; `data` carries the dashboard
        // summary (and is null when the summary refresh throws). An earlier
        // version of this file unwrapped `msg.data` and handed the summary to
        // onPunch, so `p.timestamp` was undefined and live.html silently
        // dropped every realtime row — the feed looked connected and never
        // updated. Pass the message itself; the summary rides second.
        const type = msg && msg.type;

        if (type === "attendance_realtime") {
          onPunch(msg, (msg && msg.data) || null);
        } else if (type === "pong") {
          // ignore
        } else {
          // Anything else (auto_import_update, manual_import_update, etc.) is
          // out of scope for v2 — log at debug level only.
          // console.debug("[v2 ws] ignored", type);
        }
      };

      ws.onerror = function (e) {
        // Most errors are followed by onclose; let close handle reconnect.
        console.warn("[v2 ws] error", e && e.message ? e.message : e);
      };

      ws.onclose = function (evt) {
        clearTimers();
        onStatus({ connected: false, code: evt && evt.code });
        scheduleReconnect();
      };
    }

    open();

    return function stop() {
      stopped = true;
      clearTimers();
      if (ws) {
        try { ws.close(); } catch (_) {}
        ws = null;
      }
    };
  }

  window.V2WS = { connectWS };
})();
