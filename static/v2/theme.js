/**
 * v2 shared theme + utilities.
 *
 * Each page does:
 *   <script src="/fingerprintlogs/static/v2/theme.js"></script>
 *   <script>tailwind.config = { theme: { extend: window.V2.THEME } }</script>
 *
 * Exposes window.V2 (a plain object — no module bundler needed).
 */
(function () {
  "use strict";

  // ---------- Tailwind theme extension ----------
  // Palette: slate background, indigo primary, semantic emerald/amber/rose.
  // Kept narrow on purpose — every utility class we use elsewhere can map here.
  const THEME = {
    colors: {
      // Surfaces
      ink: {
        50:  "#f8fafc",
        100: "#f1f5f9",
        200: "#e2e8f0",
        300: "#cbd5e1",
        400: "#94a3b8",
        500: "#64748b",
        600: "#475569",
        700: "#334155",
        800: "#1e293b",
        900: "#0f172a",
      },
      // Primary (indigo, slightly muted)
      brand: {
        50:  "#eef2ff",
        100: "#e0e7ff",
        200: "#c7d2fe",
        400: "#818cf8",
        500: "#6366f1",
        600: "#4f46e5",
        700: "#4338ca",
      },
      // Semantic
      good: { 50: "#ecfdf5", 100: "#d1fae5", 500: "#10b981", 600: "#059669", 700: "#047857" },
      warn: { 50: "#fffbeb", 100: "#fef3c7", 500: "#f59e0b", 600: "#d97706", 700: "#b45309" },
      bad:  { 50: "#fff1f2", 100: "#ffe4e6", 500: "#f43f5e", 600: "#e11d48", 700: "#be123c" },
      off:  { 50: "#f8fafc", 100: "#f1f5f9", 500: "#94a3b8", 600: "#64748b" },
    },
    fontFamily: {
      sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
    },
    boxShadow: {
      card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 3px rgba(15, 23, 42, 0.06)",
      soft: "0 4px 16px rgba(15, 23, 42, 0.06)",
    },
    keyframes: {
      slideInTop: {
        "0%":   { opacity: "0", transform: "translateY(-8px)" },
        "100%": { opacity: "1", transform: "translateY(0)" },
      },
      pulseHighlight: {
        "0%":   { backgroundColor: "rgba(99, 102, 241, 0.10)" },
        "100%": { backgroundColor: "rgba(255, 255, 255, 0)" },
      },
    },
    animation: {
      "slide-in-top": "slideInTop 240ms ease-out",
      "pulse-highlight": "pulseHighlight 1000ms ease-out",
    },
  };

  // ---------- Time helpers (Bangkok = UTC+7, no DST) ----------
  const BKK_TZ = "Asia/Bangkok";

  function _parseUtc(iso) {
    if (!iso) return null;
    // Backend sometimes returns naive ISO (no Z). Force-treat naive as UTC
    // because that's how AttendanceRecord.timestamp is stored.
    let s = String(iso);
    if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += "Z";
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }

  /** Format a UTC ISO timestamp to "HH:mm" Bangkok local time. */
  function bangkokTime(utcIso) {
    const d = _parseUtc(utcIso);
    if (!d) return "—";
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: BKK_TZ,
    }).format(d);
  }

  /** Today's date in YYYY-MM-DD, Bangkok-local. */
  function bangkokDate(d) {
    const now = d instanceof Date ? d : new Date();
    // sv-SE locale gives ISO-ish "YYYY-MM-DD HH:mm:ss"
    const parts = new Intl.DateTimeFormat("sv-SE", {
      timeZone: BKK_TZ,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(now);
    const y = parts.find(p => p.type === "year").value;
    const m = parts.find(p => p.type === "month").value;
    const day = parts.find(p => p.type === "day").value;
    return `${y}-${m}-${day}`;
  }

  /** Relative-time string ("12s ago", "3m ago", "2h ago"). */
  function relTime(utcIso, nowMs) {
    const d = _parseUtc(utcIso);
    if (!d) return "—";
    const now = nowMs || Date.now();
    const diff = Math.max(0, Math.round((now - d.getTime()) / 1000));
    if (diff < 5) return "just now";
    if (diff < 60) return `${diff}s ago`;
    const m = Math.floor(diff / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    const days = Math.floor(h / 24);
    return `${days}d ago`;
  }

  /**
   * fetch wrapper: same-origin credentials, JSON accept, throws on non-2xx.
   * `path` is appended to current origin (use absolute-from-root paths).
   */
  async function apiFetch(path, opts) {
    const init = Object.assign(
      {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      },
      opts || {}
    );
    const res = await fetch(path, init);
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      const err = new Error(`HTTP ${res.status} ${res.statusText}: ${path}`);
      err.status = res.status;
      err.body = text;
      throw err;
    }
    const ctype = res.headers.get("content-type") || "";
    if (ctype.includes("application/json")) return res.json();
    return res.text();
  }

  /** Initials from a display name ("Somchai J." -> "SJ"; falls back to "?"). */
  function initials(name) {
    if (!name) return "?";
    const parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return "?";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  /** Deterministic pastel accent for an avatar based on a key string. */
  function avatarColor(key) {
    const palette = [
      "bg-brand-100 text-brand-700",
      "bg-good-100 text-good-700",
      "bg-warn-100 text-warn-700",
      "bg-bad-100 text-bad-700",
      "bg-ink-200 text-ink-700",
    ];
    let h = 0;
    const s = String(key || "");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return palette[h % palette.length];
  }

  /** prefers-reduced-motion media query (reactive boolean getter). */
  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /** Escape HTML for safe innerHTML insertion. */
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  window.V2 = {
    THEME,
    bangkokTime,
    bangkokDate,
    relTime,
    apiFetch,
    initials,
    avatarColor,
    reducedMotion,
    escapeHtml,
  };
})();
