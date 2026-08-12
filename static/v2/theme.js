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
  // Palette: HF One — warm neutrals, burgundy primary, gold accent, semantic
  // success/warning/error. This is a MIRROR of the estate's served token file
  // https://erp.thehfhotel.org/shell/hf.css (canonical text:
  // /Users/nut/HF/HF-erp/design/HF-ONE.md). Do NOT invent colors here — propose
  // additions in HF-ONE.md first, then copy the value across byte-for-byte.
  //
  // Mapping to the --hf-* custom properties, so the two files can be diffed:
  //   ink-50  = --hf-shell          ink-100 = --hf-panel-tint
  //   ink-200 = --hf-border         ink-300 = --hf-border-strong
  //   ink-400 = --hf-text-muted     ink-500 = --hf-text-muted
  //   ink-900 = --hf-text           brand-* = --hf-brand-*   gold-* = --hf-gold-*
  //   good-500 = --hf-success  warn-500 = --hf-warning  bad-500 = --hf-error
  // (ink-600/700/800 are local interpolations between text-muted and text;
  //  the *-50/100/600/700 tint+shade steps on good/warn/bad are likewise local
  //  derivations of the one semantic token each — they exist so a status well
  //  can be built without inventing raw hex inside a page.)
  const THEME = {
    colors: {
      // Surfaces (warm neutrals, not Tailwind slate/gray)
      ink: {
        50:  "#FAF9F7",
        100: "#F4F1ED",
        200: "#E8E4DF",
        300: "#CFC9C1",
        // ink-400 was #ABA299 — 2.51:1 on white, which fails WCAG AA for the
        // ~34 places it carries real Thai copy. It is now an ALIAS of
        // --hf-text-muted (4.74:1 on white, 4.50:1 on the ink-50 shell) so
        // every existing `text-ink-400` becomes legible without touching a
        // page. New code: use ink-500 for muted text and ink-300 for hairlines
        // that must read; there is no legitimate lighter text shade.
        400: "#7A7268",
        500: "#7A7268",
        600: "#5C554C",
        700: "#443E37",
        800: "#332D27",
        900: "#26221E",
      },
      // Primary (HF One burgundy) — the full hf.css ramp, byte-matched.
      brand: {
        50:  "#FBEAEA",
        100: "#F5C9C9",
        200: "#E9A3A3",
        300: "#C76060",
        400: "#A83030",
        500: "#8B0000",
        600: "#7A0000",
        700: "#6B1212",
        800: "#4F0E0E",
        900: "#3B0A0A",
      },
      // Accent (HF One gold) — jewellery only: hairlines, the active mark,
      // ONE highlight per screen. Never a surface, never body text below 700.
      gold: {
        50:  "#FBF6E9",
        100: "#F6EACB",
        300: "#E7C97F",
        500: "#D9A441",
        600: "#B98730",
        700: "#93691F",
      },
      // Semantic
      good: { 50: "#EAF6EF", 100: "#D3E7DC", 500: "#2F855A", 600: "#256B47", 700: "#1D5438" },
      warn: { 50: "#FBF3E1", 100: "#F6EACB", 500: "#B7791F", 600: "#93691F", 700: "#7A4F15" },
      bad:  { 50: "#FBEAEA", 100: "#F5C6C6", 500: "#C53030", 600: "#9B2626", 700: "#7F1F1F" },
      off:  { 50: "#FAF9F7", 100: "#F4F1ED", 500: "#ABA299", 600: "#7A7268" },
    },
    fontFamily: {
      sans: ['Sarabun', '"Noto Sans Thai"', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
    },
    boxShadow: {
      // Contract values: --hf-shadow-card / --hf-shadow-popover.
      card: "0 1px 2px rgb(38 34 30 / 0.06)",
      popover: "0 8px 24px rgb(38 34 30 / 0.14)",
      // Local extra: the lift used on hover for clickable cards. Same warm
      // shadow base, no colored glow.
      soft: "0 4px 16px rgba(38, 34, 30, 0.06)",
    },
    keyframes: {
      slideInTop: {
        "0%":   { opacity: "0", transform: "translateY(-8px)" },
        "100%": { opacity: "1", transform: "translateY(0)" },
      },
      pulseHighlight: {
        "0%":   { backgroundColor: "rgba(139, 0, 0, 0.10)" },
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

  /**
   * Relative-time string in THAI ("เมื่อครู่", "3 นาทีที่แล้ว").
   * Callers concatenate it into Thai sentences (live.html: "ลงเวลาล่าสุด " +
   * relTime(...)), so it must never return English.
   */
  function relTime(utcIso, nowMs) {
    const d = _parseUtc(utcIso);
    if (!d) return "—";
    const now = nowMs || Date.now();
    const diff = Math.max(0, Math.round((now - d.getTime()) / 1000));
    if (diff < 5) return "เมื่อครู่";
    if (diff < 60) return `${diff} วินาทีที่แล้ว`;
    const m = Math.floor(diff / 60);
    if (m < 60) return `${m} นาทีที่แล้ว`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} ชั่วโมงที่แล้ว`;
    const days = Math.floor(h / 24);
    return `${days} วันที่แล้ว`;
  }

  // ---------- Calendar helpers (string-in / string-out, TZ-proof) ----------
  // Every v2 page does date maths on the "YYYY-MM-DD" string, parsed as UTC,
  // so a browser in any timezone lands on the same day. Never use
  // `new Date(iso)` without the Date.UTC dance, and never `toISOString()` on a
  // local-constructed Date — that is how off-by-one-day bugs get in.

  function _pad2(n) {
    return String(n).padStart(2, "0");
  }

  /**
   * Shift a "YYYY-MM-DD" string by n days (n may be negative).
   * addDays("2026-03-01", -1) -> "2026-02-28"
   */
  function addDays(ymd, n) {
    const [y, m, d] = String(ymd).split("-").map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d));
    dt.setUTCDate(dt.getUTCDate() + Number(n || 0));
    return `${dt.getUTCFullYear()}-${_pad2(dt.getUTCMonth() + 1)}-${_pad2(dt.getUTCDate())}`;
  }

  /**
   * Shift a month by n months. This is MONTH navigation, not date maths: the
   * result is always anchored at the start of the month, and the input SHAPE
   * is preserved so both call styles in v2 keep working.
   *   addMonths("2026-05", 1)      -> "2026-06"
   *   addMonths("2026-05-01", -1)  -> "2026-04-01"
   *   addMonths("2026-05-31", 1)   -> "2026-06-01"   (never overflows to Jul)
   */
  function addMonths(ymd, n) {
    const s = String(ymd);
    const [y, m] = s.split("-").map(Number);
    const dt = new Date(Date.UTC(y, m - 1 + Number(n || 0), 1));
    const head = `${dt.getUTCFullYear()}-${_pad2(dt.getUTCMonth() + 1)}`;
    return s.length > 7 ? `${head}-01` : head;
  }

  // Thai month names — hand-rolled rather than Intl because the staff label
  // periods with the Buddhist year (พ.ศ. = ค.ศ. + 543) and Intl's th-TH
  // "numeric" year renders the Gregorian one under the default calendar.
  const MONTH_TH = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน",
    "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม",
    "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
  ];

  /**
   * Thai month + Buddhist year label for a "YYYY-MM" or "YYYY-MM-DD" string.
   * monthLabelTH("2026-05") -> "พฤษภาคม 2569"
   */
  function monthLabelTH(ymd) {
    const [y, m] = String(ymd).split("-").map(Number);
    if (!y || !m || m < 1 || m > 12) return "—";
    return `${MONTH_TH[m - 1]} ${y + 543}`;
  }

  // Two weekday index conventions coexist in this app — mixing them silently
  // rotates a whole calendar, so the arrays are named after their index base.
  //
  //   DOW_TH          Mon-first (index 0 = Monday). Matches Python's
  //                   date.weekday() and the backend `work_days` / `dow`
  //                   fields. Use for anything that came out of the API.
  //   WEEKDAY_TH      Sun-first (index 0 = Sunday). Matches JS getUTCDay().
  //   WEEKDAY_TH_SHORT  Sun-first, 1–2 character form for grid headers.
  //
  // Need a Mon-first FULL name? WEEKDAY_TH[(monIndex + 1) % 7].
  const DOW_TH = ["จ", "อ", "พ", "พฤ", "ศ", "ส", "อา"];
  const WEEKDAY_TH = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์"];
  const WEEKDAY_TH_SHORT = ["อา", "จ", "อ", "พ", "พฤ", "ศ", "ส"];

  /**
   * Convert a JS weekday (Sun=0 … Sat=6, i.e. getUTCDay()) to the backend's
   * Python weekday (Mon=0 … Sun=6) — the index DOW_TH and `work_days` use.
   * Also accepts a "YYYY-MM-DD" string for convenience.
   *   isoWeekday(0) -> 6      isoWeekday("2026-05-15") -> 4 (Friday)
   */
  function isoWeekday(jsDay) {
    if (typeof jsDay === "string") {
      const [y, m, d] = jsDay.split("-").map(Number);
      return (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
    }
    return ((Number(jsDay) % 7) + 6) % 7;
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
    // Time
    bangkokTime,
    bangkokDate,
    relTime,
    // Calendar
    addDays,
    addMonths,
    monthLabelTH,
    isoWeekday,
    MONTH_TH,
    DOW_TH,
    WEEKDAY_TH,
    WEEKDAY_TH_SHORT,
    // Data + rendering
    apiFetch,
    initials,
    avatarColor,
    reducedMotion,
    escapeHtml,
  };
})();
