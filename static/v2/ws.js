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
 *     onPunch:  (p) => { ... },   // type === "attendance_realtime"
 *     onStatus: (s) => { ... },   // { connected: bool, reason?: string }
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

        // The backend's ConnectionManager sometimes nests payload under .data
        // (see legacy adapter). Normalize: prefer .data when both present.
        const type = msg && msg.type;
        const payload = (msg && msg.data) ? msg.data : msg;

        if (type === "attendance_realtime") {
          onPunch(payload);
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
