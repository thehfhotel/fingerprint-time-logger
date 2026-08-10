#!/usr/bin/env node
/**
 * Full-page screenshot helper for the local fingerprint-time-logger dev
 * server (see scripts/dev/run_local.sh). Lets a UI agent self-inspect a
 * page's rendered output without a human in the loop.
 *
 * Usage:
 *   node scripts/dev/shot.mjs <url> <output.png> [width] [height]
 *
 * Examples:
 *   node scripts/dev/shot.mjs http://localhost:5055/fingerprintlogs/v2/ /tmp/v2-index.png
 *   node scripts/dev/shot.mjs http://localhost:5055/fingerprintlogs/v2/monthly /tmp/monthly.png 1600 1000
 *
 * Notes:
 *   - static/v2/*.html load Tailwind from https://cdn.tailwindcss.com and
 *     the estate hf-bar kit from https://erp.thehfhotel.org/shell/hf-bar.js
 *     — both need real network access. Offline, pages render unstyled
 *     (no Tailwind) and without the top nav bar (no hf-bar), but still
 *     screenshot fine — it's just ugly, not broken.
 *   - Waits for "networkidle" (falls back to "load" on timeout) then a
 *     short settle delay for client-side fetch()+render before capturing.
 *
 * Requires: `npm install` inside scripts/dev/ once (installs Playwright +
 * downloads its browser binary; the repo has no other Node/Playwright
 * setup — tests/e2e/ uses the Python pytest-playwright package instead).
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";

function usageAndExit(msg) {
  if (msg) console.error(`Error: ${msg}\n`);
  console.error(
    "Usage: node shot.mjs <url> <output.png> [width] [height]"
  );
  process.exit(1);
}

const [, , url, outPath, widthArg, heightArg] = process.argv;
if (!url || !outPath) usageAndExit("url and output.png path are required");

let parsedUrl;
try {
  parsedUrl = new URL(url);
} catch {
  usageAndExit(`not a valid URL: ${url}`);
}

const width = widthArg ? parseInt(widthArg, 10) : 1440;
const height = heightArg ? parseInt(heightArg, 10) : 900;
if (!Number.isFinite(width) || !Number.isFinite(height)) {
  usageAndExit("width/height must be numbers");
}

async function main() {
  await mkdir(dirname(outPath), { recursive: true }).catch(() => {});

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width, height } });

  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  let httpStatus = null;
  try {
    const response = await page.goto(parsedUrl.toString(), {
      waitUntil: "networkidle",
      timeout: 15000,
    });
    httpStatus = response ? response.status() : null;
  } catch (err) {
    console.error(`networkidle wait timed out/failed (${err.message}); falling back to "load"`);
    try {
      const response = await page.goto(parsedUrl.toString(), {
        waitUntil: "load",
        timeout: 15000,
      });
      httpStatus = response ? response.status() : null;
    } catch (err2) {
      await browser.close();
      console.error(`FAILED to load ${url}: ${err2.message}`);
      process.exit(1);
    }
  }

  // Let client-side fetch() calls (attendance/employees/shifts JSON) settle
  // and re-render after the initial page load event.
  await page.waitForTimeout(1200);

  await page.screenshot({ path: outPath, fullPage: true });
  await browser.close();

  console.log(`Saved screenshot: ${outPath}`);
  console.log(`HTTP status: ${httpStatus}`);
  if (consoleErrors.length) {
    console.log(`Console errors/warnings captured (${consoleErrors.length}):`);
    for (const line of consoleErrors.slice(0, 20)) console.log(`  - ${line}`);
  } else {
    console.log("No console errors captured.");
  }
}

main().catch((err) => {
  console.error("shot.mjs crashed:", err);
  process.exit(1);
});
