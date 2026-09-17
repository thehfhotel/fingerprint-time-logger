/**
 * v2 shared navigation — desktop top nav + mobile bottom bar + "เมนู" sheet.
 *
 * Each page carries ONE placeholder and ONE script tag:
 *
 *   <nav id="v2nav" data-page="monthly"></nav>
 *   <script defer src="/fingerprintlogs/static/v2/nav.js"></script>
 *
 * `data-page` is the destination id (see DESTINATIONS below). This file
 * renders BOTH navs from that one array, so the vocabulary lives in exactly
 * one place: add or rename a destination here and every page follows.
 *
 * Layout notes:
 *   - The placeholder element itself BECOMES the desktop nav (`md:block`).
 *     Its height is reserved by CSS injected at the top of this file, so the
 *     late (deferred) injection cannot shift the page.
 *   - The mobile bar and the sheet are appended to <body> and are `fixed`,
 *     so they shift nothing either. `main` already carries `pb-28` for the bar.
 *   - hf-bar (the 44px estate band) sits in normal flow at the very top and is
 *     app-switching chrome. This file is page navigation and never touches it.
 *
 * Colors come from Tailwind classes backed by theme.js. The only CSS written
 * here is structural (reserve height, transform/opacity motion) — no color.
 */
(function () {
  "use strict";

  var BASE = "/fingerprintlogs/v2/";

  // ---------- Icons (inline stroke-width-2 SVG — never an emoji, never a font) ----------
  function icon(paths) {
    return (
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true" focusable="false" class="h-5 w-5">' +
      paths +
      "</svg>"
    );
  }

  var ICONS = {
    home: icon('<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.8V21h14V9.8"/><path d="M9.5 21v-6h5v6"/>'),
    live: icon('<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>'),
    report: icon('<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>'),
    shifts: icon('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/>'),
    people: icon('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
    system: icon('<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>'),
    qr: icon('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3z"/><path d="M20 14v3"/><path d="M14 20h7"/>'),
    menu: icon('<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/>'),
  };

  // ---------- The vocabulary — SINGLE SOURCE OF TRUTH ----------
  // `bar`    : shows as one of the four workhorse cells in the mobile bar.
  // `topNav` : shows in the desktop nav (terminals deliberately does not —
  //            it is reached from the ระบบ page and the index hub card).
  // Every destination appears in the sheet, in this order.
  var DESTINATIONS = [
    { id: "index",        label: "หน้าหลัก",   href: BASE,                icon: ICONS.home,   bar: false, topNav: true },
    { id: "live",         label: "ดูสด",       href: BASE + "live",       icon: ICONS.live,   bar: true,  topNav: true },
    { id: "monthly",      label: "รายงาน",     href: BASE + "monthly",    icon: ICONS.report, bar: true,  topNav: true },
    { id: "shifts-admin", label: "จัดกะ",      href: BASE + "shifts-admin", icon: ICONS.shifts, bar: true, topNav: true },
    { id: "employees",    label: "พนักงาน",    href: BASE + "employees",  icon: ICONS.people, bar: true,  topNav: true },
    { id: "system",       label: "ระบบ",       href: BASE + "system",     icon: ICONS.system, bar: false, topNav: true },
    { id: "terminals",    label: "จุดสแกน QR", href: BASE + "terminals",  icon: ICONS.qr,     bar: false, topNav: false },
  ];

  // Pages that are not themselves a destination but live "under" one. The nav
  // highlights the parent WITHOUT claiming aria-current="page" (it is not the
  // current page — it is the section the current page belongs to).
  var ALIASES = { "": "index", home: "index", "by-date": "monthly", index: "index" };

  // ---------- Class vocabulary (all tokens from theme.js) ----------
  var C = {
    deskWrap: "hidden border-b border-ink-200 bg-white md:block",
    deskRow: "mx-auto flex items-center gap-1 px-5 py-2",
    deskLink: "rounded-lg px-3 py-1.5 text-sm font-medium text-ink-600 hover:bg-ink-100 hover:text-ink-900",
    deskLinkOn: "rounded-lg bg-brand-50 px-3 py-1.5 text-sm font-semibold text-brand-700 ring-1 ring-brand-200",

    bar: "fixed inset-x-0 bottom-0 z-20 border-t border-ink-200 bg-white/95 backdrop-blur md:hidden",
    barRow: "mx-auto grid grid-cols-5",
    cell: "flex min-h-[56px] flex-col items-center justify-center gap-0.5 py-2 text-xs font-medium text-ink-500 hover:text-ink-800",
    cellOn: "flex min-h-[56px] flex-col items-center justify-center gap-0.5 py-2 text-xs font-semibold text-brand-700",

    overlay: "fixed inset-0 z-30 bg-ink-900/40 md:hidden",
    sheet:
      "fixed inset-x-0 bottom-0 z-40 max-h-[80vh] overflow-y-auto overscroll-contain " +
      "rounded-t-2xl bg-white shadow-popover md:hidden",
    grip: "mx-auto mt-3 mb-2 h-1 w-10 rounded-full bg-ink-200",
    row: "flex min-h-[48px] items-center gap-3 px-5 text-sm font-medium text-ink-700 hover:bg-ink-50",
    rowOn: "flex min-h-[48px] items-center gap-3 px-5 text-sm font-semibold bg-brand-50 text-brand-700",
  };

  // ---------- Structural CSS (no color — colors are Tailwind tokens) ----------
  // Reserving the desktop nav's height means a slow/late parse of this file
  // cannot push the page down under the reader. The sheet's motion lives here
  // rather than in utility classes so the very first open animates correctly
  // even before the Tailwind CDN has JIT-compiled a newly injected class.
  //
  // The focus rule is the ONE place raw rgb belongs here: it is the contract's
  // focus treatment (brand-500 at 40%, no colored glow) and the kit must carry
  // it itself — a page's own `a:focus-visible` rule is not guaranteed to reach
  // elements this file appends to <body>.
  var CSS =
    "@media (min-width:768px){#v2nav{min-height:49px}}" +
    "#v2nav a:focus-visible,#v2nav-bar a:focus-visible," +
    "#v2nav-bar button:focus-visible,#v2nav-sheet a:focus-visible{" +
    "outline:2px solid rgba(139,0,0,.40);outline-offset:-2px}" + // brand-500 / 40%
    "#v2nav a:focus-visible{outline-offset:2px}" +
    "#v2nav-overlay{opacity:0;transition:opacity 150ms ease-out}" +
    '#v2nav-overlay[data-open="1"]{opacity:1}' +
    "#v2nav-sheet{transform:translateY(100%);transition:transform 200ms ease-out}" +
    '#v2nav-sheet[data-open="1"]{transform:translateY(0)}' +
    "@media (prefers-reduced-motion:reduce){" +
    "#v2nav-overlay,#v2nav-sheet{transition:none}}";

  function injectCss() {
    if (document.getElementById("v2nav-css")) return;
    var s = document.createElement("style");
    s.id = "v2nav-css";
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  // ---------- Helpers ----------

  /**
   * The page's content width, so the nav rails line up with <main>.
   * Priority: data-width on the placeholder -> the max-w-* class on <main>
   * -> max-w-5xl (the contract's default report width).
   */
  function contentWidth(mount) {
    var explicit = mount.getAttribute("data-width");
    if (explicit) return explicit;
    var main = document.querySelector("main");
    if (main) {
      var hit = String(main.className).match(/(?:^|\s)(max-w-[\w[\].%-]+|w-full)(?:\s|$)/);
      if (hit) return hit[1];
    }
    return "max-w-5xl";
  }

  /** Resolve data-page to { id, exact } — exact drives aria-current="page". */
  function resolveActive(mount) {
    var raw = (mount.getAttribute("data-page") || "").trim();
    for (var i = 0; i < DESTINATIONS.length; i++) {
      if (DESTINATIONS[i].id === raw) return { id: raw, exact: true };
    }
    var alias = ALIASES[raw];
    if (alias) return { id: alias, exact: raw === alias };
    return { id: null, exact: false };
  }

  function currentAttr(isActive, exact) {
    if (!isActive) return "";
    // aria-current="page" only when this IS the page. A parent section that
    // merely contains the current page gets "true" — highlighted, not lying.
    return exact ? ' aria-current="page"' : ' aria-current="true"';
  }

  // ---------- Render ----------

  function renderDesktop(mount, width, active) {
    mount.className = C.deskWrap;
    if (!mount.getAttribute("aria-label")) mount.setAttribute("aria-label", "เมนูหลัก");

    var links = "";
    for (var i = 0; i < DESTINATIONS.length; i++) {
      var d = DESTINATIONS[i];
      if (d.topNav === false) continue;
      var on = d.id === active.id;
      links +=
        '<a href="' + d.href + '"' + currentAttr(on, active.exact) +
        ' class="' + (on ? C.deskLinkOn : C.deskLink) + '">' + d.label + "</a>";
    }
    mount.innerHTML = '<div class="' + C.deskRow + " " + width + '">' + links + "</div>";
  }

  function renderBar(width, active) {
    var barDests = DESTINATIONS.filter(function (d) { return d.bar; });
    // When the current page is not one of the four workhorse cells (หน้าหลัก /
    // ระบบ / จุดสแกน QR), the เมนู cell carries the active mark instead — an
    // unmarked bar reads as broken.
    var menuIsActive = !barDests.some(function (d) { return d.id === active.id; });

    var cells = "";
    for (var i = 0; i < barDests.length; i++) {
      var d = barDests[i];
      var on = d.id === active.id;
      cells +=
        '<a href="' + d.href + '"' + currentAttr(on, active.exact) +
        ' class="' + (on ? C.cellOn : C.cell) + '">' + d.icon + "<span>" + d.label + "</span></a>";
    }
    cells +=
      '<button type="button" id="v2nav-menu-btn" aria-haspopup="dialog" aria-expanded="false" ' +
      'aria-controls="v2nav-sheet" class="' + (menuIsActive ? C.cellOn : C.cell) + '">' +
      ICONS.menu + "<span>เมนู</span></button>";

    var nav = document.createElement("nav");
    nav.id = "v2nav-bar";
    nav.className = C.bar;
    nav.setAttribute("aria-label", "เมนูล่าง");
    nav.style.paddingBottom = "env(safe-area-inset-bottom)";
    nav.innerHTML = '<div class="' + C.barRow + " " + width + '">' + cells + "</div>";
    return nav;
  }

  function renderSheet(active) {
    var rows = "";
    for (var i = 0; i < DESTINATIONS.length; i++) {
      var d = DESTINATIONS[i];
      var on = d.id === active.id;
      rows +=
        '<a href="' + d.href + '"' + currentAttr(on, active.exact) +
        ' class="' + (on ? C.rowOn : C.row) + '">' + d.icon + "<span>" + d.label + "</span></a>";
    }

    var overlay = document.createElement("div");
    overlay.id = "v2nav-overlay";
    overlay.className = C.overlay;
    overlay.hidden = true;

    var sheet = document.createElement("div");
    sheet.id = "v2nav-sheet";
    sheet.className = C.sheet;
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-label", "เมนู");
    sheet.hidden = true;
    sheet.style.paddingBottom = "calc(env(safe-area-inset-bottom) + 0.75rem)";
    sheet.innerHTML =
      '<div class="' + C.grip + '" aria-hidden="true"></div>' +
      '<div class="pb-2">' + rows + "</div>";

    return { overlay: overlay, sheet: sheet };
  }

  // ---------- Sheet behaviour ----------

  function wireSheet(btn, overlay, sheet) {
    var open = false;
    var savedOverflow = "";
    var closeTimer = null;

    function focusables() {
      return Array.prototype.slice
        .call(sheet.querySelectorAll('a[href],button:not([disabled])'))
        .filter(function (el) { return el.offsetParent !== null || el === document.activeElement; });
    }

    function reduced() {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    }

    function openSheet() {
      if (open) return;
      open = true;
      if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }

      overlay.hidden = false;
      sheet.hidden = false;
      savedOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      btn.setAttribute("aria-expanded", "true");

      // Force a reflow so the from-state is committed before the to-state,
      // otherwise the browser collapses both into one frame and nothing moves.
      void sheet.offsetHeight;
      overlay.setAttribute("data-open", "1");
      sheet.setAttribute("data-open", "1");

      var first = focusables()[0];
      if (first) first.focus();
    }

    function closeSheet(restoreFocus) {
      if (!open) return;
      open = false;
      overlay.removeAttribute("data-open");
      sheet.removeAttribute("data-open");
      btn.setAttribute("aria-expanded", "false");
      document.body.style.overflow = savedOverflow;

      if (restoreFocus !== false) btn.focus();

      var hide = function () {
        overlay.hidden = true;
        sheet.hidden = true;
        closeTimer = null;
      };
      if (reduced()) hide();
      else closeTimer = setTimeout(hide, 220);
    }

    btn.addEventListener("click", function () {
      if (open) closeSheet(); else openSheet();
    });

    overlay.addEventListener("click", function () { closeSheet(); });

    // Let a destination tap close the sheet immediately — on a same-page link
    // no navigation happens and the sheet would otherwise stay up.
    sheet.addEventListener("click", function (e) {
      if (e.target && e.target.closest && e.target.closest("a[href]")) closeSheet(false);
    });

    document.addEventListener("keydown", function (e) {
      if (!open) return;
      if (e.key === "Escape" || e.key === "Esc") {
        e.preventDefault();
        closeSheet();
        return;
      }
      if (e.key !== "Tab") return;
      var items = focusables();
      if (!items.length) return;
      var first = items[0];
      var last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || !sheet.contains(document.activeElement))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });

    // Resizing past the md breakpoint hides the bar; a sheet left open there
    // would trap focus in an invisible dialog.
    if (window.matchMedia) {
      var mq = window.matchMedia("(min-width: 768px)");
      var onChange = function (e) { if (e.matches) closeSheet(false); };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    }

    return { open: openSheet, close: closeSheet, isOpen: function () { return open; } };
  }

  // Business-page enhancements are loaded only on the two leave-aware pages.
  // Keeping the source in one shared file prevents shifts-admin and monthly
  // from drifting into different leave labels/half-day behavior.
  function loadPageEnhancement(mount) {
    var page = (mount.getAttribute("data-page") || "").trim();
    if (page !== "shifts-admin" && page !== "monthly") return;
    if (document.querySelector('script[data-v2-leave-sync="1"]')) return;
    var script = document.createElement("script");
    script.src = BASE + "leave-sync-ui.js";
    script.async = false;
    script.setAttribute("data-v2-leave-sync", "1");
    document.head.appendChild(script);
  }

  // ---------- Boot ----------

  function build() {
    var mount = document.getElementById("v2nav");
    if (!mount || mount.getAttribute("data-v2nav-ready") === "1") return;
    mount.setAttribute("data-v2nav-ready", "1");

    injectCss();

    var width = contentWidth(mount);
    var active = resolveActive(mount);

    renderDesktop(mount, width, active);

    var bar = renderBar(width, active);
    var parts = renderSheet(active);
    document.body.appendChild(bar);
    document.body.appendChild(parts.overlay);
    document.body.appendChild(parts.sheet);

    var api = wireSheet(
      bar.querySelector("#v2nav-menu-btn"),
      parts.overlay,
      parts.sheet
    );

    window.V2NAV = {
      DESTINATIONS: DESTINATIONS.map(function (d) {
        return { id: d.id, label: d.label, href: d.href, icon: d.icon };
      }),
      activeId: active.id,
      openMenu: api.open,
      closeMenu: api.close,
    };

    loadPageEnhancement(mount);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();
