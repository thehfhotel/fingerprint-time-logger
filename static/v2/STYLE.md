# v2 page style contract

The single template for every `static/v2/*.html` page. Copy from **this file**,
never from a neighbouring page — the existing pages carry a pre-migration
indigo/slate `<style>` block that looks correct (its comments even claim HF
tokens) and will silently propagate if you copy it. See
[Do not do this](#do-not-do-this) at the bottom.

Upstream contract: `HF-erp/design/HF-ONE.md`, tokens served at
`https://erp.thehfhotel.org/shell/hf.css`. `static/v2/theme.js` is this app's
byte-for-byte mirror of those tokens. **Every color you write must come from a
Tailwind class backed by `theme.js`.** If you need a shade that does not exist,
it goes into HF-ONE.md first, then theme.js — never inline into a page.

---

## 1. The page skeleton

Head order is not decorative — Tailwind's Play CDN reads `tailwind.config`
synchronously after it parses, so `theme.js` **must** load before the config
block, and the config block must precede any markup.

```html
<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="color-scheme" content="light" />
  <meta name="theme-color" content="#4F0E0E" />
  <title>{ชื่อหน้า} — ระบบบันทึกเวลา</title>

  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;500;600;700&display=swap" rel="stylesheet" />

  <script src="https://cdn.tailwindcss.com"></script>
  <script src="/fingerprintlogs/static/v2/theme.js"></script>
  <!-- Shared navigation — renders BOTH navs. Every page, no exceptions. -->
  <script defer src="/fingerprintlogs/static/v2/nav.js"></script>
  <!-- ws.js ONLY on pages that consume the live socket -->
  <script src="/fingerprintlogs/static/v2/ws.js"></script>

  <script>
    tailwind.config = {
      theme: { extend: window.V2.THEME },
      safelist: [
        /* avatarColor() — assembled in JS, invisible to the scanner */
        "bg-brand-100", "text-brand-700",
        "bg-good-100",  "text-good-700",
        "bg-warn-100",  "text-warn-700",
        "bg-bad-100",   "text-bad-700",
        "bg-ink-200",   "text-ink-700",
        /* status pills built in JS */
        "bg-off-100",   "text-off-600",
        "bg-good-500",  "bg-warn-500", "bg-bad-500", "bg-ink-300",
        "animate-pulse",
        /* …plus every other class YOUR page concatenates into an HTML string */
      ],
    };
  </script>

  <style>
    /* Belt-and-braces: the CDN applies fontFamily only after theme.js parses. */
    html, body { font-family: 'Sarabun', 'Noto Sans Thai', system-ui, -apple-system, sans-serif; }
    /* HF One body type: 14px / 1.6 (Thai needs the tall leading).
       Set on BODY, never on <html> — Tailwind's spacing scale is rem-based and
       rescaling the root font-size shrinks every p-*/gap-* on the page. */
    body { font-size: 0.875rem; line-height: 1.6; }

    /* --- paste section 4 (chips / tabs / pills / buttons) here --- */
  </style>
</head>
<body class="min-h-screen bg-ink-50 text-ink-900 antialiased">

  <!-- The ONLY nav markup a page carries. See section 2. -->
  <nav id="v2nav" data-page="monthly"></nav>

  <!-- <main> -->

  <!-- LAST element before </body>, non-negotiable -->
  <script defer src="https://erp.thehfhotel.org/shell/hf-bar.js"
          data-app="Attendance" data-module="people"></script>
</body>
</html>
```

Rules baked into the above:

- `<html lang="th">`. Every user-facing string is Thai. Employees are LINE-only:
  no email field, no Google button, ever.
- `viewport-fit=cover` is required — the mobile bottom nav's safe-area padding
  does nothing without it.
- `theme-color` is `#4F0E0E` (`brand-800`, the band colour).
- Page `<title>` is Thai with an em-dash: `รายงานรายเดือน — ระบบบันทึกเวลา`.
  Do not put "เวอร์ชัน 2" in a title or an eyebrow — that is an internal
  migration label, not product copy.
- The hf-bar script is the **last** element in `<body>` on every page, always
  `data-app="Attendance" data-module="people"`. It prepends itself in normal
  flow and pushes content down: no `100vh` or `calc(100vh - …)` layouts.
- No emoji. Anywhere. Use an inline stroke-width-2 SVG or a Thai word.

### `<main>` container

```html
<main class="mx-auto max-w-5xl px-4 pt-5 pb-28 md:px-5 md:pt-8 md:pb-12">
```

`pb-28` reserves room for the fixed bottom nav — keep it even on desktop-wide
pages. Widths in use: `max-w-3xl` feed-style single column, `max-w-5xl` normal
report/table page, `max-w-7xl` wide grid, `w-full` only for a full-bleed
calendar grid.

`nav.js` **reads the `max-w-*` (or `w-full`) class off this `<main>`** and
applies the same width to both nav rails, so they line up with the content
without you repeating the value. Put the width class on `<main>` itself, not on
an inner wrapper. If the page has no `<main>`, or you need a different rail
width, pass `data-width="max-w-5xl"` on the nav placeholder.

### Page header

```html
<header class="mb-5 md:mb-7">
  <p class="text-xs font-semibold tracking-wide text-brand-600">รายงาน</p>
  <h1 class="mt-1 text-xl font-bold tracking-tight text-ink-900">รายงานรายเดือน</h1>
  <p class="mt-1 text-sm text-ink-500">สรุปการมาทำงานรายเดือนสำหรับทำเงินเดือน</p>
</header>
```

Titles are `text-xl` (20px) — the contract's cap. Do **not** use
`text-2xl md:text-3xl`; hierarchy comes from weight, not size. The eyebrow gets
`font-semibold tracking-wide`, never `uppercase tracking-[0.18em]`: `uppercase`
is a no-op on Thai and wide letter-spacing tears Thai vowel/tone marks off their
consonant clusters.

---

## 2. Navigation contract

Navigation is **shared code, not page markup**. Both navs are rendered by
`static/v2/nav.js` from one destination array. A page never hand-rolls a nav,
never copies nav markup from a neighbour, and never restyles one.

### 2a. The mechanism — one placeholder, one script

In `<head>`, next to `theme.js`:

```html
<script defer src="/fingerprintlogs/static/v2/nav.js"></script>
```

In `<body>`, immediately before `<main>`:

```html
<nav id="v2nav" data-page="monthly"></nav>
```

That is the whole page-side contract. `nav.js` then:

- turns the placeholder itself into the **desktop top nav** (`md:block`), and
- appends the **mobile bottom bar** and its **เมนู sheet** to `<body>` (both
  `fixed` + `md:hidden`, so they shift nothing).

`nav.js` also reserves the desktop nav's height in CSS, so its deferred
injection cannot push the page down under the reader. It exits silently if the
placeholder is absent — a page without it simply has no nav, which is a bug.

**Asset URLs are stamped server-side, per deploy — never hand-write `?v=`.**
`serve_html_with_cache_control` (app/main_unified.py) rewrites every
`/fingerprintlogs/static/**` `src=`/`href=` in a page's HTML to carry this
release's `?v=<deploy>` (app/utils/static_asset_version.py) before it ever
reaches the browser, because the edge in front of us caches those URLs by
URL for hours regardless of our `no-store` header. A page's own `<script
src="/fingerprintlogs/static/v2/nav.js">` needs no query string in the
source file — it gets one at serve time. `nav.js` reads that stamp back off
its own `<script>` tag and forwards it onto the `leave-sync-ui.js` it
injects, so a script written into the DOM after load still gets a fresh
cache key too.

`data-page` is the destination **id**, one of:

`index` · `live` · `monthly` · `shifts-admin` · `leaves` · `employees` ·
`system` · `terminals`

A page that is not itself a destination declares its **section** instead:
`by-date` resolves to `monthly`, which is then highlighted with
`aria-current="true"` (the section that contains you) rather than
`aria-current="page"` (the page you are on). Add new aliases to the `ALIASES`
map in `nav.js`, never by hand-marking a link.

### 2b. The destinations — single source of truth

Defined once, in `nav.js`. Never re-typed into a page.

| Label | href | desktop nav | bottom bar | เมนู sheet |
|---|---|:---:|:---:|:---:|
| หน้าหลัก | `/fingerprintlogs/v2/` | yes | — | yes |
| ดูสด | `/fingerprintlogs/v2/live` | yes | yes | yes |
| รายงาน | `/fingerprintlogs/v2/monthly` | yes | yes | yes |
| จัดกะ | `/fingerprintlogs/v2/shifts-admin` | yes | yes | yes |
| วันลา · วันหยุด | `/fingerprintlogs/v2/leaves` | yes | — | yes |
| พนักงาน | `/fingerprintlogs/v2/employees` | yes | yes | yes |
| ระบบ | `/fingerprintlogs/v2/system` | yes | — | yes |
| จุดสแกน QR | `/fingerprintlogs/v2/terminals` | — | — | yes |

**Terminals is NOT in the top nav.** It is reached from the ระบบ page, from a
card on the index hub, and from the sheet.

Eight tabs do not fit a 390px phone — that is ~55px per cell, which truncates
Thai labels and breaks the 44px touch target. So the bar carries the **four
workhorse pages plus a fifth เมนู cell**, and everything is one tap away in the
sheet.

Pages that need to build their own link list (the index hub, the ระบบ page's
link to terminals) can read `window.V2NAV.DESTINATIONS` — `{ id, label, href,
icon }`, same order as the table — instead of re-typing hrefs.

### 2c. What it renders — desktop (`md`+)

```html
<nav id="v2nav" aria-label="เมนูหลัก" class="hidden border-b border-ink-200 bg-white md:block">
  <div class="mx-auto flex items-center gap-1 px-5 py-2 max-w-5xl">
    <a href="/fingerprintlogs/v2/"
       class="rounded-lg px-3 py-1.5 text-sm font-medium text-ink-600 hover:bg-ink-100 hover:text-ink-900">หน้าหลัก</a>
    <!-- the CURRENT page's link instead reads: -->
    <a href="/fingerprintlogs/v2/monthly" aria-current="page"
       class="rounded-lg bg-brand-50 px-3 py-1.5 text-sm font-semibold text-brand-700 ring-1 ring-brand-200">รายงาน</a>
    …
  </div>
</nav>
```

The active item is `brand-50` fill + `brand-700` text + `ring-1 ring-brand-200`
+ `aria-current="page"` — the contract's sidebar-active pattern flattened to a
top bar. The `max-w-*` comes from your `<main>` (section 1).

### 2d. What it renders — mobile bar (`<md`), five cells

```html
<nav id="v2nav-bar" aria-label="เมนูล่าง"
     class="fixed inset-x-0 bottom-0 z-20 border-t border-ink-200 bg-white/95 backdrop-blur md:hidden"
     style="padding-bottom: env(safe-area-inset-bottom);">
  <div class="mx-auto grid grid-cols-5 max-w-5xl">
    <a href="/fingerprintlogs/v2/live"
       class="flex min-h-[56px] flex-col items-center justify-center gap-0.5 py-2 text-xs font-medium text-ink-500 hover:text-ink-800">
      <svg …stroke-width="2" class="h-5 w-5">…</svg><span>ดูสด</span>
    </a>
    …
    <button type="button" id="v2nav-menu-btn"
            aria-haspopup="dialog" aria-expanded="false" aria-controls="v2nav-sheet"
            class="flex min-h-[56px] flex-col items-center justify-center gap-0.5 py-2 …">
      <svg …class="h-5 w-5">…</svg><span>เมนู</span>
    </button>
  </div>
</nav>
```

- Icons are inline `stroke-width="2"` SVG. Never an emoji, never an icon font.
- Active cell: `text-brand-700 font-semibold` + `aria-current="page"`.
- **No gold in the bar.** Gold stays reserved for the in-page active-tab
  underline (see the gold budget in section 4).
- On หน้าหลัก / ระบบ / จุดสแกน QR — pages with no cell of their own — the
  **เมนู cell** carries the active mark instead, so the bar is never blank.

### 2e. What it renders — the เมนู sheet

Overlay `fixed inset-0 z-30 bg-ink-900/40`; panel `fixed inset-x-0 bottom-0
z-40 rounded-t-2xl bg-white max-h-[80vh] overflow-y-auto overscroll-contain`,
safe-area padding, `role="dialog" aria-modal="true" aria-label="เมนู"`. A
decorative drag handle, then all eight destinations as rows:

```html
<a href="/fingerprintlogs/v2/live"
   class="flex min-h-[48px] items-center gap-3 px-5 text-sm font-medium text-ink-700 hover:bg-ink-50">
  <svg …class="h-5 w-5">…</svg><span>ดูสด</span>
</a>
<!-- current page row: -->
<a href="/fingerprintlogs/v2/monthly" aria-current="page"
   class="flex min-h-[48px] items-center gap-3 px-5 text-sm font-semibold bg-brand-50 text-brand-700">…</a>
```

Behaviour, all handled by `nav.js`: the panel slides `translateY(100%) → 0` over
200ms ease-out and the overlay fades over 150ms (both **instant** under
`prefers-reduced-motion: reduce`); opening focuses the first row and locks body
scroll; Tab/Shift-Tab wrap inside the sheet; Escape, an overlay click, or
choosing a destination closes it and returns focus to the เมนู button;
`aria-expanded` mirrors the state; crossing the `md` breakpoint closes it.

`window.V2NAV.openMenu()` / `closeMenu()` exist if a page needs to drive it.

### 2f. Rules for pages

- **Ship the placeholder + the script tag. Both. Every page.** A page whose only
  nav is `hidden md:block` strands phone users with no way out but the back
  button.
- Keep `pb-28` on `<main>` — the bar is fixed and would otherwise sit on the
  last row of content.
- Do **not** put nav classes in your `safelist`, restyle `#v2nav*`, or add a
  second bottom nav / a competing fixed footer.
- **z-index ladder — do not collide:** `z-20` mobile bar, `z-30` sheet overlay,
  `z-40` sheet. A page's own overlay must be `z-30` or higher to clear the bar;
  a full-screen sheet (section 5a) sits at `z-40`.
- hf-bar (the 44px estate band) is app-switching chrome in normal flow at the
  very top; this nav is page navigation. They never overlap and neither
  duplicates the other. Do not add app links to the page nav.
- Every interactive element in either nav is >= 44px below `md`. If you add a
  destination, check the 390px width — a sixth bar cell is not an option, it
  goes in the sheet.

Any in-page tab strip must be `flex gap-1 overflow-x-auto` (long Thai tab labels
overflow a plain `flex` on a phone).

---

## 3. The loading / error / empty trio

Every data pane owns all three plus its content node, toggled by `hidden` from a
`hideAllPanes()` / `showLoading()` / `showError()` / `showEmpty()` / `showData()`
quartet. Panel shell for all of them:
`rounded-xl border border-ink-200 bg-white shadow-card`.

```html
<!-- LOADING -->
<div id="paneLoading" class="rounded-xl border border-ink-200 bg-white px-6 py-12 text-center shadow-card">
  <div class="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-ink-200 border-t-brand-500"></div>
  <p class="mt-3 text-sm text-ink-500">กำลังโหลด…</p>
</div>

<!-- ERROR -->
<div id="paneError" class="hidden rounded-xl border border-bad-100 bg-bad-50 px-4 py-3 text-sm text-bad-700">
  <span id="paneErrorText">ไม่สามารถโหลดข้อมูลได้</span>
  <button id="paneRetry" type="button"
          class="ml-2 font-semibold underline underline-offset-2 hover:text-bad-600">ลองใหม่</button>
</div>

<!-- EMPTY -->
<div id="paneEmpty" class="hidden rounded-xl border border-ink-200 bg-white px-6 py-16 text-center shadow-card">
  <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-600">
    <svg …class="h-6 w-6">…</svg>
  </div>
  <p class="text-sm font-medium text-ink-700">ยังไม่มีข้อมูลในช่วงที่เลือก</p>
  <p class="mt-1 text-xs text-ink-500">ลองเปลี่ยนวันที่หรือสาขา</p>
</div>
```

Copy rules:

- Error text always ends with the cause: `+ " (" + (err.status || "เครือข่าย") + ")"`.
- A `404` means the endpoint is not deployed on this server — say so rather than
  showing a generic failure: `ยังไม่มีหน้า{ชื่อ}บนเซิร์ฟเวอร์นี้`.
- The empty headline changes with the cause: no data at all vs. no match for the
  current filter. Both name the next action.
- Mutations do not use this trio. They use an inline per-control status:
  disable the control → `กำลังบันทึก…` → `บันทึกแล้ว` (auto-clear after 1.8s)
  or `บันทึกไม่สำเร็จ ({status})`, re-enabled in `finally`. No toasts.

---

## 4. Component CSS — paste this, delete the indigo

This block **replaces** the `.chip` / `.loc-chip` / `.tab` / `.view-on` /
`.wd-pill` / `pulseHighlight` rules in the existing pages. Every value here is a
`theme.js` token; the hex is repeated in a comment so a reviewer can diff it
against `hf.css`.

```css
/* ---------- Filter / branch chip (pill, JS toggles .chip-on) ---------- */
.chip {
  display: inline-flex; align-items: center; gap: .375rem;
  border-radius: 9999px;
  padding: .3125rem .75rem;
  font-size: .8125rem; line-height: 1.25rem; font-weight: 500;
  border: 1px solid #E8E4DF;          /* ink-200  --hf-border */
  background: #FFFFFF;                /* --hf-panel */
  color: #5C554C;                     /* ink-600 */
  cursor: pointer;
  transition: background-color .12s ease, border-color .12s ease, color .12s ease;
}
.chip:hover { border-color: #CFC9C1; background: #FAF9F7; }  /* ink-300 / ink-50 */
.chip.chip-on {
  border-color: #E9A3A3;              /* brand-200 */
  background: #FBEAEA;                /* brand-50 */
  color: #6B1212;                     /* brand-700 — 10.5:1 */
  font-weight: 600;
}

/* ---------- Underlined tab (JS toggles .tab-on) — GOLD active mark ------- */
.tab {
  padding: .5rem .75rem;
  font-size: .875rem; font-weight: 500;
  color: #5C554C;                     /* ink-600 */
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;                /* sit on the strip's hairline */
  white-space: nowrap;
  background: none; cursor: pointer;
}
.tab:hover { color: #26221E; }        /* ink-900 */
.tab.tab-on {
  color: #6B1212;                     /* brand-700 */
  font-weight: 600;
  border-bottom-color: #D9A441;       /* gold-500 — the one gold mark */
}

/* ---------- Segmented view toggle (JS toggles .view-on) ---------------- */
.seg {
  padding: .375rem .875rem;
  font-size: .8125rem; font-weight: 500;
  color: #5C554C;                     /* ink-600 */
  background: transparent;
  border-radius: 6px;                 /* --hf-radius-sm */
  cursor: pointer;
}
.seg:hover { background: #F4F1ED; }   /* ink-100  --hf-panel-tint */
.seg.view-on {
  background: #8B0000;                /* brand-500 — filled, white text 10:1 */
  color: #FFFFFF;
  font-weight: 600;
}

/* ---------- Weekday toggle pill (JS toggles .wd-on) -------------------- */
.wd-pill {
  width: 2.25rem; height: 2.25rem;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 9999px;
  font-size: .8125rem; font-weight: 600;
  border: 1px solid #E8E4DF;          /* ink-200 */
  background: #FFFFFF; color: #5C554C;
  cursor: pointer;
}
.wd-pill:hover { border-color: #CFC9C1; }
.wd-pill.wd-on {
  border-color: #8B0000;              /* brand-500 */
  background: #8B0000;
  color: #FFFFFF;
}

/* ---------- Focus: brand-500 at 40%, never a colored glow -------------- */
.chip:focus-visible, .tab:focus-visible, .seg:focus-visible,
.wd-pill:focus-visible, .btn-primary:focus-visible, .btn-secondary:focus-visible {
  outline: 2px solid rgba(139, 0, 0, .40);   /* brand-500 / 40% */
  outline-offset: 2px;
}

/* ---------- Live-feed row flash (burgundy, not indigo) ----------------- */
@keyframes slideInTop {
  0%   { opacity: 0; transform: translateY(-8px); }
  100% { opacity: 1; transform: translateY(0); }
}
@keyframes pulseHighlight {
  0%   { background-color: rgba(139, 0, 0, .10); }  /* brand-500 @ 10% */
  100% { background-color: rgba(255, 255, 255, 0); }
}
@media (prefers-reduced-motion: reduce) {
  .v2-row-new { animation: none !important; }
}
```

### Primary button — filled `brand-500`

v2 has no filled burgundy today; every "primary" is a `brand-50` tint, so a
Save button reads the same weight as a filter chip. That stops here. **One**
filled primary per form/section; everything else is secondary.

```css
.btn-primary {
  display: inline-flex; align-items: center; justify-content: center; gap: .375rem;
  min-height: 2.5rem;
  padding: .5rem .875rem;
  border-radius: 8px;                 /* --hf-radius */
  font-size: .875rem; font-weight: 600;
  background: #8B0000;                /* brand-500 */
  border: 1px solid #8B0000;
  color: #FFFFFF;                     /* 10.0:1 */
  cursor: pointer;
  transition: background-color .12s ease, border-color .12s ease;
}
.btn-primary:hover   { background: #7A0000; border-color: #7A0000; }  /* brand-600 */
.btn-primary:active  { background: #6B1212; border-color: #6B1212; }  /* brand-700 */
.btn-primary:disabled{ background: #E8E4DF; border-color: #E8E4DF; color: #7A7268; cursor: not-allowed; }

.btn-secondary {
  /* same box as .btn-primary */
  background: #FFFFFF;
  border: 1px solid #CFC9C1;          /* --hf-border-strong */
  color: #332D27;                     /* ink-800 */
  font-weight: 500;
}
.btn-secondary:hover { background: #FAF9F7; border-color: #7A7268; }

.btn-danger {
  /* same box as .btn-primary */
  background: #C53030; border: 1px solid #C53030; color: #FFFFFF;  /* bad-500, 5.5:1 */
}
.btn-danger:hover { background: #9B2626; border-color: #9B2626; }
```

Button copy says what happens: `บันทึกกะ`, `เพิ่มพนักงาน`, `ลบวันลา` — never
"ตกลง" alone.

### Gold — use it sparingly

Gold is jewellery, not paint. The **only** sanctioned uses on a v2 page:

1. The active tab's 2px underline (`gold-500`, in `.tab-on` above).
2. A 2px `gold-500` tick on the right edge of an active vertical nav item, if a
   page grows a sidebar.
3. **One** highlight per screen — the single cell/row/number the page exists to
   draw the eye to (e.g. today's column in the month grid). A `gold-300`
   hairline or a `gold-100` fill, once.

Never: gold as a panel or button background, gold body text lighter than
`gold-700` (`#93691F` is the first shade that passes AA on white), gold on
gold, or two gold highlights on the same screen. The band's own hairline
already spends most of the estate's gold budget.

### Other surface rules

- Panel: `rounded-xl border border-ink-200 bg-white shadow-card` — `rounded-xl`
  is 12px = `--hf-radius-lg`. Not `rounded-2xl` (16px). Buttons/inputs/chips
  ride `rounded-lg` (8px) or `rounded-full`.
- Table: header row `bg-ink-100` (`--hf-panel-tint`), body `text-[13px]`,
  zebra `odd:bg-ink-50/60`, numbers `tabular-nums`, sticky heads stick to their
  own `overflow-auto` container (never to the viewport — the band is in flow).
- Inputs/selects: `border border-ink-300` (`--hf-border-strong`) on white,
  `rounded-lg`, `h-10`, `focus-visible:outline-2 focus-visible:outline-[rgba(139,0,0,.40)]`
  or Tailwind `focus-visible:ring-2 focus-visible:ring-brand-500/40`.
- Status is never colour alone: dot **plus** Thai word.
  `good`=ตรงเวลา/มาทำงาน, `warn`=สาย/รอ, `bad`=ขาด, `off`=หยุด/ลา.
- Shadows: `shadow-card` on panels, `shadow-popover` on menus/dropdowns,
  `shadow-soft` only as a hover lift on clickable cards. No colored glows.
- `off-500` (`#ABA299`) is a fill/dot colour only — for "หยุด" text use
  `text-off-600`.

---

## 5. Responsive patterns — desktop UI on a phone

Two named patterns. **Copy them verbatim**; they are the agreed mobile
treatment for the two shapes that break at 390px. This wave is presentation
only: the desktop behaviour of every page must stay byte-for-byte what it is
today — you are adding a phone treatment, not redesigning the page.

### 5a. MODAL-TO-SHEET — a centred dialog becomes a full-screen sheet

A centred `max-w-lg` card is fine at 1440px and unusable at 390px: it lands
mid-viewport, the keyboard covers its footer, and the Save button drifts below
the fold. Below `md` the same dialog becomes a full-screen sheet — sticky
header, scrolling body, sticky footer — so the primary action is always visible
and always thumb-reachable.

One dialog, two layouts, no duplicated markup:

```html
<!-- OVERLAY: md+ only. Below md the sheet is opaque and full-bleed, so an
     overlay behind it would just cost a paint. -->
<div id="dlgOverlay" class="fixed inset-0 z-30 hidden bg-ink-900/40 md:block"></div>

<!-- PANEL -->
<div id="dlg" role="dialog" aria-modal="true" aria-labelledby="dlgTitle"
     class="fixed inset-0 z-40 flex flex-col bg-white
            md:inset-auto md:left-1/2 md:top-1/2 md:max-h-[85vh] md:w-full md:max-w-lg
            md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-xl md:border md:border-ink-200 md:shadow-popover">

  <!-- STICKY HEADER: title + a 44px close target -->
  <header class="sticky top-0 z-10 flex items-center gap-3 border-b border-ink-200 bg-white px-4 py-3 md:px-5">
    <h2 id="dlgTitle" class="flex-1 text-base font-semibold text-ink-900">แก้ไขกะ</h2>
    <button type="button" id="dlgClose" aria-label="ปิด"
            class="-mr-2 flex h-11 w-11 items-center justify-center rounded-lg text-ink-600 hover:bg-ink-100 hover:text-ink-900">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" aria-hidden="true" class="h-5 w-5">
        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button>
  </header>

  <!-- SCROLLABLE BODY: the ONLY scrolling region -->
  <div class="flex-1 overflow-y-auto overscroll-contain px-4 py-4 md:px-5">
    …fields…
  </div>

  <!-- STICKY FOOTER: exactly ONE filled primary -->
  <footer class="sticky bottom-0 flex items-center justify-end gap-2 border-t border-ink-200 bg-white px-4 py-3 md:px-5"
          style="padding-bottom: calc(env(safe-area-inset-bottom) + 0.75rem);">
    <button type="button" class="btn-secondary">ยกเลิก</button>
    <button type="button" class="btn-primary">บันทึกกะ</button>
  </footer>
</div>
```

Rules:

- **`flex flex-col` on the panel, `flex-1 overflow-y-auto` on the body.** Not
  `max-h` + `overflow` on the panel: with a sticky footer that produces a
  double scrollbar, and on iOS the footer detaches while the keyboard is up.
- **The footer holds one filled `.btn-primary`.** Destructive actions
  (`.btn-danger`) go at the far left of the footer, never next to Save.
- Full-width buttons on a phone if there is only one action:
  `w-full md:w-auto`.
- Same a11y as the nav sheet: `role="dialog" aria-modal="true"` + a label,
  focus the first field (or the close button) on open, Escape closes, focus
  returns to whatever opened it, `document.body.style.overflow = "hidden"`
  while open. Trap Tab inside the panel.
- `z-40` — above the mobile nav bar (`z-20`) and its overlay (`z-30`), so the
  nav cannot be tapped through an open dialog.
- Motion: fade+scale at `md`+, `translateY(100%) → 0` over 200ms below it, and
  **instant** under `prefers-reduced-motion: reduce`. Gate on `V2.reducedMotion()`.
- Copy: the title names the record (`แก้ไขกะ — สมชาย`), the primary names the
  action (`บันทึกกะ`), never `ตกลง`.

### 5b. WIDE-TABLE — a many-column table on a 390px screen

Two legitimate answers. Pick with this test:

> **Is the row a comparison, or a record?**
> Scanning one column down many rows (a month grid, times per day, per-employee
> totals) is a **comparison** → keep the table, scroll it horizontally with a
> sticky first column. Reading one row across (a single employee, a single
> device, a single leave request) is a **record** → cards.

Never both on the same pane, and never a horizontally scrolling *page* — the
`<body>` must never scroll sideways.

**Option A — horizontal scroll + sticky first column** (the default for grids
and reports)

```html
<!-- The scroll container is the panel itself; the table is free to be wider. -->
<div class="overflow-x-auto rounded-xl border border-ink-200 bg-white shadow-card">
  <table class="w-full min-w-[52rem] border-collapse text-[13px]">
    <thead class="bg-ink-100">
      <tr>
        <!-- sticky first column: OPAQUE background, or rows bleed through on iOS Safari -->
        <th class="sticky left-0 z-10 bg-ink-100 px-3 py-2 text-left font-semibold text-ink-700">พนักงาน</th>
        <th class="px-3 py-2 text-right font-semibold text-ink-700 tabular-nums">1</th>
        …
      </tr>
    </thead>
    <tbody>
      <tr class="odd:bg-ink-50/60">
        <th scope="row" class="sticky left-0 z-10 bg-white px-3 py-2 text-left font-medium text-ink-900">สมชาย</th>
        <td class="px-3 py-2 text-right tabular-nums">08:02</td>
        …
      </tr>
    </tbody>
  </table>
</div>
```

- **The sticky cell's background must be opaque and must be set on the cell
  itself** (`bg-white` / `bg-ink-100`), on both the `th` and the `td`/`th` in
  the body. A transparent sticky cell, or a background inherited from the row,
  lets the scrolling columns show straight through it on iOS Safari. This is
  the single most common way this pattern ships broken.
- Zebra + sticky fight each other: `odd:bg-ink-50/60` on the row does not paint
  the sticky cell. Either drop zebra on that column or repeat the tint on the
  sticky cell (`odd:bg-ink-50` on the cell too).
- `min-w-[…]` on the `<table>` is what forces the scroll; without it the table
  squeezes into 390px and every Thai name wraps to four lines.
- The container scrolls, **not the page**: `overflow-x-auto` lives on the panel
  div, never on `<body>` or `<main>`.
- Sticky table heads stick to this container, never to the viewport — hf-bar is
  in normal flow (section 1).
- Give the container `tabindex="0"` and an `aria-label` so it is keyboard
  scrollable, and keep numbers `tabular-nums` so columns line up while scrolling.

**Option B — card per row** (the default for lists of records)

```html
<!-- Table at md+, cards below. Same data, rendered once into two templates. -->
<div class="hidden md:block">…the table…</div>

<ul class="space-y-2 md:hidden">
  <li class="rounded-xl border border-ink-200 bg-white p-3 shadow-card">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="truncate text-sm font-semibold text-ink-900">สมชาย ใจดี</p>
        <p class="mt-0.5 text-xs text-ink-500">ต้อนรับ · R001</p>
      </div>
      <span class="inline-flex shrink-0 items-center gap-1 rounded-full bg-good-100 px-2 py-0.5 text-xs font-medium text-good-700">
        <span class="h-1.5 w-1.5 rounded-full bg-good-500"></span>ตรงเวลา
      </span>
    </div>
    <dl class="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
      <div class="flex justify-between"><dt class="text-ink-500">เข้า</dt><dd class="font-medium tabular-nums">08:02</dd></div>
      <div class="flex justify-between"><dt class="text-ink-500">ออก</dt><dd class="font-medium tabular-nums">17:10</dd></div>
    </dl>
  </li>
</ul>
```

- Card headline = the one field that identifies the record; 2–4 supporting
  fields as `dt`/`dd` pairs. If you need more than four, it is a comparison —
  use Option A.
- Status keeps its dot **plus** its Thai word (section 4). Colour alone is not
  a status.
- Row actions become one tap target per card, `min-h-[44px]`.
- Render both from **one** data pass — two independent renderers drift, and the
  phone one is the one nobody looks at again.

---

## 6. Shared helpers (`window.V2`) — do not re-implement

There are three shared JS files and no bundler: **`theme.js`** (tokens +
helpers, below), **`nav.js`** (both navs — section 2, no page-facing API beyond
the placeholder and `window.V2NAV`), and **`ws.js`** (the live socket, only on
pages that consume it). Anything four pages would otherwise copy belongs in
`theme.js`. Currently exported:

**Frozen — behaviour must not change:**

| Helper | Notes |
|---|---|
| `apiFetch(path, opts)` | `credentials:"same-origin"`, `Accept: application/json`, throws an `Error` carrying `.status` and `.body` on non-2xx, auto-parses JSON by content-type. Every read and write goes through it. |
| `bangkokDate(d?)` | today (or `d`) as `YYYY-MM-DD`, Bangkok-local. Never `new Date().toISOString()`. |
| `bangkokTime(utcIso)` | `HH:mm` Bangkok. Backend timestamps are naive-UTC; the parser force-appends `Z`. |
| `escapeHtml(s)` | mandatory around every value interpolated into an HTML string. |
| `initials(name)` / `avatarColor(key)` | avatar glyph + deterministic `bg-*/text-*` pair (must be in the safelist). |
| `reducedMotion()` | gate every animation on it. |

**Added for the migration:**

| Helper | Contract |
|---|---|
| `addDays(ymd, n)` | `"2026-03-01", -1` → `"2026-02-28"`. String in, string out, parsed as UTC. |
| `addMonths(ymd, n)` | Month navigation, always anchored at the month start, input shape preserved: `"2026-05"`→`"2026-06"`, `"2026-05-01"`→`"2026-06-01"`. Never overflows (`"2026-05-31", 1` → `"2026-06-01"`). |
| `monthLabelTH(ymd)` | Thai month + **Buddhist** year: `"2026-05"` → `"พฤษภาคม 2569"`. Hand-rolled, because Intl's `th-TH` numeric year renders the Gregorian one. |
| `MONTH_TH` | 12 Thai month names, index 0 = มกราคม. |
| `DOW_TH` | `["จ","อ","พ","พฤ","ศ","ส","อา"]` — **Mon-first**, index 0 = Monday. Matches Python `weekday()` and the API's `work_days`/`dow`. |
| `WEEKDAY_TH` | Sun-first full names, index 0 = อาทิตย์. Matches JS `getUTCDay()`. Mon-first full name = `WEEKDAY_TH[(i+1)%7]`. |
| `WEEKDAY_TH_SHORT` | Sun-first 1–2 char form for grid headers. |
| `isoWeekday(jsDay)` | JS day (Sun=0) → backend day (Mon=0). Also accepts a `"YYYY-MM-DD"` string. |
| `relTime(utcIso)` | **Thai**: `เมื่อครู่`, `3 นาทีที่แล้ว`, `2 ชั่วโมงที่แล้ว`. Safe to concatenate into Thai sentences. |

Mixing the two weekday bases silently rotates an entire calendar — always name
which one a variable holds.

### `ws.js` (`window.V2WS`) — live socket

```js
const stop = V2WS.connectWS({
  onPunch: (punch, summary) => { /* punch = TOP-LEVEL broadcast object */ },
  onStatus: (s) => { /* { connected: bool, code?: number } */ },
});
```

`punch` is `{ badge_number, display_name, timestamp, punch_type, synced_records,
message }` — verified against `app/services/zk_session.py::_broadcast_realtime`.
The dashboard summary rides in the message's `data` key and is handed over as
the **second** argument (`null` when the backend's summary refresh failed).
Ignore it unless you need it. Only `type === "attendance_realtime"` is
dispatched; `pong` and the import-progress types are dropped.

---

## 7. Backend contract

No backend changes in this migration. Every page consumes the existing
`/api/private/*` endpoints with the same method, path and body v1 used. If you
believe an endpoint is missing, report it — do not add or patch one.

There is no auth UI in v2 and no 401/403 branch: Cloudflare Access gates
`/fingerprintlogs/*` and `/api/private/*` at the edge, and `apiFetch` just rides
the cookie. An expired session surfaces as an ordinary network error in the
error pane.

---

## Do not do this

Grep your page for these before you call it done. Every one of them is currently
live somewhere in `static/v2/` and every one is wrong.

**Banned raw colours** (Tailwind's default indigo/slate ramps — the
pre-migration palette). Several are sitting behind comments that claim `brand-*`
/ `ink-*`; the comment is the lie, the value is the bug.

| Value | What it actually is | Use instead |
|---|---|---|
| `rgb(67 56 202)` | indigo-700 | `#6B1212` brand-700 |
| `rgb(99 102 241)` | indigo-500 | `#8B0000` brand-500 |
| `rgb(238 242 255)` | indigo-50 | `#FBEAEA` brand-50 |
| `rgb(199 210 254)` | indigo-200 | `#E9A3A3` brand-200 |
| `rgba(99, 102, 241, 0.10)` | indigo row flash | `rgba(139, 0, 0, .10)` |
| `rgb(226 232 240)` | slate-200 | `#E8E4DF` ink-200 |
| `rgb(203 213 225)` | slate-300 | `#CFC9C1` ink-300 |
| `rgb(71 85 105)` | slate-600 | `#5C554C` ink-600 |
| `rgb(248 250 252)` | slate-50 | `#FAF9F7` ink-50 |
| `rgb(241 245 249)` | slate-100 | `#F4F1ED` ink-100 |
| `rgba(15, 23, 42, .06)` | slate-900 shadow | `rgb(38 34 30 / 0.06)` |
| `#ABA299` as text | old ink-400, 2.5:1 — fails AA | `text-ink-500` |
| `#2C5282` as a link | `--hf-info`, a notice colour | `text-brand-500` |
| any `rgba(59, 130, 246, …)` glow | blue focus glow | brand-500 at 40%, no glow |

Also do not:

- Use any Tailwind `slate-*` / `gray-*` / `indigo-*` / `blue-*` utility class.
  The warm ramps are `ink-*` and `brand-*`.
- Write a raw hex/rgb for a colour that has a token. Section 4 is the only place
  raw hex belongs, because those rules cannot be expressed as utilities. (The
  focus rule inside `nav.js` is the one other sanctioned copy of
  `rgba(139,0,0,.40)` — a shared kit must carry its own focus ring.)
- Ship `text-2xl`/`text-3xl` page titles, or `uppercase tracking-[0.18em]` on
  Thai text.
- Set `html { font-size: 14px }` — it rescales every rem-based spacing utility.
- Hand-roll nav markup, or copy a nav out of a neighbouring page. The whole nav
  is `<nav id="v2nav" data-page="…"></nav>` + the `nav.js` tag (section 2).
  A page missing either one, or missing `pb-28` on `<main>`, is not done.
- Let `<body>` scroll horizontally. A wide table scrolls inside its own
  `overflow-x-auto` container (section 5b).
- Ship a centred `max-w-lg` modal as the phone treatment — below `md` it becomes
  a full-screen sheet (section 5a).
- Ship a tint (`bg-brand-50`) as the primary action — the primary is filled
  `brand-500`.
- Use gold as a fill, or twice on one screen.
- Add a second `<script>` for a different design kit, or move the hf-bar tag off
  the last line.
- Put an emoji in copy, a comment, or a commit message.
- Add an email or Google field to any employee-facing flow. Employees are
  LINE-only.
- Assemble a `bg-*`/`text-*` class inside a JS string without adding it to the
  page's `safelist` — it will silently render unstyled.
