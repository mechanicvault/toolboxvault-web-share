#!/usr/bin/env node
/**
 * Menu-fit tripwire — Sweep Wave D, lane D1 ("Idea 1").
 *
 * The rule this enforces: at phone width, EVERY menu on EVERY main
 * page fits on the screen. Menus clipping off the edge used to be
 * found by a yearly manual census; this pass makes it a standing
 * build property instead — run it before a release, and any menu
 * that renders even one pixel outside the viewport fails the run
 * (exit 1) with a per-page, per-menu table and a screenshot of
 * each offender.
 *
 * What it does, against a LOCALLY SERVED build of the site (the
 * shared wave stack: API on 8105 + serve.mjs on 4275, production
 * CSP verbatim, EMAIL_PROVIDER=dev):
 *   1. Signs in as the seat(s) given by env (never committed).
 *   2. Visits every main page that carries menus (see PAGES),
 *      resolving detail-page ids live from the API so it works
 *      against any seeded stack.
 *   3. At 390px width, clicks every menu trigger on the page —
 *      anything with aria-haspopup="menu", plus the header
 *      notifications bell (aria-haspopup="dialog" → .tv-bell-pop) —
 *      in three phases: the page as it lands, each tab's panel,
 *      and Customize/edit mode (where the "+ Add" block menus
 *      live).
 *      measures the opened menu's bounding box, and FAILS if any
 *      part renders outside the viewport. Menus that open but
 *      render empty are failures too. Expanders INSIDE an open
 *      menu (the gear menu's tree toggles) are opened and the
 *      grown menu re-measured. One refinement, deliberately: a
 *      menu that starts below the fold but scrolls fully into
 *      view (an in-flow menu inside a widget) is reachable, not
 *      clipped, and passes — the defect family is the overlay
 *      menu that NO scroll can bring on screen.
 *   4. Spot-checks desktop width (1280px) on a subset of pages.
 *   5. Prints the table; screenshots offenders into TBV_SHOTS_DIR.
 *
 * Deliberate exclusions (not menus in the clipping sense):
 *   - native <select> dropdowns — the OS renders them, they
 *     cannot leave the screen;
 *   - the date-picker popup and modal dialogs — dialogs, not
 *     menus; the notifications PANEL is included because it is
 *     the header cluster's dropdown in everything but role name.
 *
 * Env:
 *   TBV_BASE_URL     web origin      (default http://127.0.0.1:4275)
 *   TBV_API_URL      api origin      (default http://127.0.0.1:8105)
 *   TBV_EMAIL / TBV_PASSWORD         owner seat (required, app mode)
 *   TBV_ADMIN_EMAIL / TBV_ADMIN_PASSWORD   optional god seat → Admin pages
 *   TBV_RUNG_EMAIL / TBV_RUNG_PASSWORD     optional downloads-tier seat
 *   TBV_SHOTS_DIR    offender screenshots (default ./menu-fit-shots)
 *   TBV_REPORT       optional path for a JSON copy of the table
 *   TBV_FIXTURE_URL  fixture mode: skip login, run the generic
 *                    discovery against this one page only. Used to
 *                    prove the tripwire can fail (see the lane's
 *                    rig/fixture-server.mjs).
 *   TBV_ONLY         comma-separated page names — run only those
 *                    pages (debugging / quick re-checks).
 *   TBV_CHROME       chromium executable (default: newest
 *                    ~/.cache/ms-playwright/chromium-*)
 *   TBV_PLAYWRIGHT_HOME  module dir whose package.json resolves
 *                    playwright-core (default
 *                    /home/hatch/workspace/mobile-repro) — the wave
 *                    rigs' browser machinery; no new framework.
 *
 * Usage (from frontend/):
 *   npm run check:menu-fit
 * Exit codes: 0 = every menu fits · 1 = offender(s) found ·
 * 2 = the pass itself could not run (bad env / stack down).
 */
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.env.TBV_BASE_URL || "http://127.0.0.1:4275";
const API = process.env.TBV_API_URL || "http://127.0.0.1:8105";
const FIXTURE_URL = process.env.TBV_FIXTURE_URL || "";
const SHOTS = process.env.TBV_SHOTS_DIR || path.resolve("menu-fit-shots");
const PHONE = { width: 390, height: 844 };
const DESKTOP = { width: 1280, height: 900 };
const TOL = 1; // px of sub-pixel slack; anything beyond is reported

function loadChromium() {
  const homes = [
    process.env.TBV_PLAYWRIGHT_HOME,
    "/home/hatch/workspace/mobile-repro",
    process.cwd(),
  ].filter(Boolean);
  for (const home of homes) {
    try {
      const req = createRequire(path.join(home, "package.json"));
      return req("playwright-core").chromium;
    } catch { /* try next */ }
  }
  throw new Error("playwright-core not resolvable — set TBV_PLAYWRIGHT_HOME");
}
function chromePath() {
  if (process.env.TBV_CHROME) return process.env.TBV_CHROME;
  const root = path.join(os.homedir(), ".cache", "ms-playwright");
  const dirs = fs.readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort();
  if (!dirs.length) throw new Error(`no chromium under ${root} — set TBV_CHROME`);
  return path.join(root, dirs[dirs.length - 1], "chrome-linux", "chrome");
}

function curlJson(method, url, body, tok) {
  const args = ["-s", "-X", method, url, "-H", "Content-Type: application/json"];
  if (tok) args.push("-H", `Authorization: Bearer ${tok}`);
  if (body !== undefined) args.push("-d", "@-");
  const out = execFileSync("curl", args, {
    input: body !== undefined ? JSON.stringify(body) : undefined,
  }).toString();
  try { return JSON.parse(out); } catch { return null; }
}
function login(email, password) {
  const auth = curlJson("POST", `${API}/api/core/login`, { email, password });
  if (!auth || !auth.access_token) {
    console.error(`menu-fit — login failed for ${email} (stack up? seat seeded?)`);
    process.exit(2);
  }
  return auth.access_token;
}

/* Detail-page ids, discovered live from the API (any seeded stack). */
function discoverIds(tok) {
  const pick = (list, pred) => {
    const arr = Array.isArray(list) ? list : list?.items || list?.files || [];
    const hit = arr.find(pred || (() => true));
    return hit ? hit.id : null;
  };
  const tools = curlJson("GET", `${API}/api/inventory?limit=50`, undefined, tok);
  const claims = curlJson("GET", `${API}/api/claims`, undefined, tok);
  const disaster = curlJson("GET", `${API}/api/disaster-claims`, undefined, tok);
  const companies = curlJson("GET", `${API}/api/dealers/companies`, undefined, tok);
  const trucks = curlJson("GET", `${API}/api/truck-accounts/accounts`, undefined, tok);
  const prints = curlJson("GET", `${API}/api/prints/files`, undefined, tok);
  return {
    tool: pick(tools),
    claim: pick(claims),
    disaster: pick(disaster),
    dealer: pick(companies, (c) => c.owner_id) || pick(companies),
    truck: pick(trucks),
    print: pick(prints),
  };
}

const withId = (tpl, id) => (id ? tpl.replace("{id}", id) : null);
function ownerPages(ids) {
  return [
    ["Home", "/"],
    ["Inventory list", "/inventory"],
    ["Inventory item", withId("/inventory/{id}", ids.tool)],
    ["Dealers list", "/dealers"],
    ["Dealer page", withId("/dealers/{id}", ids.dealer)],
    ["Borrowing", "/borrowing"],
    ["Repairs list", "/repairs"],
    ["Repair claim", withId("/claims/{id}", ids.claim)],
    ["Disaster Claims", "/disaster-claims"],
    ["Disaster claim", withId("/disaster-claims/{id}", ids.disaster)],
    ["Shared Tools", "/shared-tools"],
    ["Truck Accounts", "/truck-accounts"],
    ["Truck account", withId("/truck-accounts/{id}", ids.truck)],
    ["Flyers", "/flyers"],
    ["Downloads", "/downloads"],
    ["3D Prints", "/3dprints"],
    ["Print listing", withId("/3dprints/{id}", ids.print)],
    ["Feedback", "/feedback"],
    ["Help", "/help"],
    ["Forum", "/forum"],
    ["Settings", "/settings"],
    ["Notifications", "/notifications"],
    ["Tool Expansion", "/tool-expansion"],
    ["Reports", "/reports"],
  ];
}
const ADMIN_PAGES = [
  ["Admin home", "/admin"],
  ["Admin Users", "/admin/users"],
  ["Admin Modules", "/admin/modules"],
  ["Admin Announcements", "/admin/announcements"],
  ["Admin Settings", "/admin/settings"],
  ["Admin Audit", "/admin/audit"],
];
const RUNG_PAGES = [
  ["Home (rung)", "/"],
  ["Downloads (rung)", "/downloads"],
  ["3D Prints (rung)", "/3dprints"],
];
/* Desktop spot-check subset (page names from the owner census). */
const DESKTOP_SPOT = new Set(["Home", "Inventory list", "Settings", "Admin home"]);

/* ---------- in-page helpers ---------- */
const POPUP_SEL = '[role="menu"], .tv-bell-pop';
const TRIGGER_SEL = '[aria-haspopup="menu"]';
const BELL_SEL = '[aria-haspopup="dialog"].tv-bell-btn, .tv-bell-btn[aria-haspopup]';

async function visiblePopups(page) {
  return page.evaluate((sel) => {
    const vw = window.innerWidth, vh = window.innerHeight;
    const els = [...document.querySelectorAll(sel)].filter((el) => {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.display !== "none" && cs.visibility !== "hidden";
    });
    return els.map((el) => {
      const snap = () => {
        const r = el.getBoundingClientRect();
        return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
      };
      const first = snap();
      // Reachability: an in-flow menu below the fold is not
      // clipped — the page scrolls and the whole menu can be
      // brought on screen. A fixed/overlay menu that starts
      // off-screen stays off-screen after the scroll attempt.
      // Only the second case is the defect this tripwire guards.
      let after = first;
      if (first.left < 0 || first.top < 0 || first.right > vw || first.bottom > vh) {
        el.scrollIntoView({ block: "nearest", inline: "nearest" });
        after = snap();
      }
      const items = el.querySelectorAll('[role="menuitem"], button, a, li').length;
      return {
        cls: el.getAttribute("class") || el.tagName,
        ...first, vw, vh, items,
        text: (el.textContent || "").trim().length,
        scrolled: { ...after },
      };
    });
  }, POPUP_SEL);
}

function judge(box) {
  const offOf = (b) => ({
    left: Math.max(0, -b.left),
    top: Math.max(0, -b.top),
    right: Math.max(0, b.right - box.vw),
    bottom: Math.max(0, b.bottom - box.vh),
  });
  const worstOf = (o) => Math.max(o.left, o.top, o.right, o.bottom);
  if (box.items === 0 && box.text === 0) return { result: "EMPTY", off: offOf(box), worst: 0 };
  const off = offOf(box);
  if (worstOf(off) <= TOL) return { result: "fits", off, worst: 0 };
  const offAfter = offOf(box.scrolled);
  if (worstOf(offAfter) <= TOL) return { result: "fits", off, worst: 0, viaScroll: true };
  return { result: "OFF-SCREEN", off: offAfter, worst: worstOf(offAfter) };
}
const offText = (off) =>
  ["left", "top", "right", "bottom"]
    .filter((k) => off[k] > TOL)
    .map((k) => `${k} ${off[k].toFixed(1)}px`)
    .join(", ");

const rows = [];
function record(seat, pageName, menu, width, box, verdict) {
  rows.push({ seat, page: pageName, menu, width, result: verdict.result, detail: verdict.result === "fits" ? `${Math.round(box.width)}×${Math.round(box.height)}${verdict.viaScroll ? " (in-flow, scrolls into view)" : ""}` : verdict.result === "EMPTY" ? "opened, no items/text" : offText(verdict.off) });
  return verdict.result !== "fits";
}

async function openAndMeasure(page, trigger, seat, pageName, label, width, shotsDir, slug) {
  let failed = false;
  await trigger.scrollIntoViewIfNeeded().catch(() => {});
  await trigger.click({ timeout: 8000 });
  await page.waitForTimeout(500);
  let popups = await visiblePopups(page);
  if (!popups.length) {
    // Some menus mount a tick late; one retry wait before judging.
    await page.waitForTimeout(600);
    popups = await visiblePopups(page);
  }
  if (!popups.length) {
    rows.push({ seat, page: pageName, menu: label, width, result: "NO-OPEN", detail: "trigger clicked, no menu appeared" });
    return true;
  }
  for (const box of popups) {
    const verdict = judge(box);
    if (record(seat, pageName, label, width, box, verdict)) {
      failed = true;
      if (shotsDir) {
        const file = path.join(shotsDir, `${slug}.png`);
        await page.screenshot({ path: file }).catch(() => {});
        rows[rows.length - 1].shot = path.basename(file);
      }
    }
    // Expanders inside the open menu (gear tree toggles etc.):
    // open each and re-measure the grown menu.
    const expanders = page.locator(`:is(${POPUP_SEL}) [aria-expanded="false"]`);
    const n = await expanders.count().catch(() => 0);
    for (let i = 0; i < Math.min(n, 6); i++) {
      await expanders.nth(i).click().catch(() => {});
      await page.waitForTimeout(350);
      const grown = await visiblePopups(page);
      for (const g of grown) {
        const v2 = judge(g);
        const wasFailed = record(seat, pageName, `${label} (expanded)`, width, g, v2);
        if (wasFailed) {
          failed = true;
          if (shotsDir) {
            const file = path.join(shotsDir, `${slug}-expanded.png`);
            await page.screenshot({ path: file }).catch(() => {});
            rows[rows.length - 1].shot = path.basename(file);
          }
        }
      }
    }
  }
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(200);
  if ((await visiblePopups(page)).length) {
    await trigger.click({ timeout: 3000 }).catch(() => {});
    await page.waitForTimeout(200);
    await page.mouse.click(8, 8).catch(() => {});
    await page.waitForTimeout(150);
  }
  return failed;
}

const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

async function runPage(browser, tok, seatName, pageName, pagePath, viewport, opts = {}) {
  const ctx = await browser.newContext({ viewport });
  if (tok) await ctx.addInitScript((t) => localStorage.setItem("tv-token", t), tok);
  const page = await ctx.newPage();
  let failed = false;
  try {
    await page.goto(`${BASE}${pagePath}`, { waitUntil: "load", timeout: 60000 }).catch(() => {});
    // Menus mount after the page's data lands (list rows, widget
    // blocks) — wait for the network to quiet, capped, then settle.
    await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(700);

    // The rail is chrome, not a page menu: measure it once, on Home.
    if (opts.rail) {
      const rail = await page.evaluate(() => {
        const el = document.querySelector(".tv-rail");
        if (!el) return null;
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return null;
        return { cls: "tv-rail", left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height, vw: window.innerWidth, vh: window.innerHeight, items: el.querySelectorAll("a, button").length, text: (el.textContent || "").trim().length, scrolled: { left: r.left, top: r.top, right: r.right, bottom: r.bottom } };
      });
      if (rail) {
        const v = judge(rail);
        if (record(seatName, pageName, "rail (nav panel)", viewport.width, rail, v)) {
          failed = true;
          const file = path.join(SHOTS, `${slugify(seatName)}-rail-${viewport.width}.png`);
          await page.screenshot({ path: file }).catch(() => {});
          rows[rows.length - 1].shot = path.basename(file);
        }
      }
    }

    // Trigger discovery, in phases: the page as it lands, then
    // each tab's panel, then Customize/edit mode (the "+ Add"
    // block menus live there). Triggers are stamped with a
    // data-tw-id so a menu is measured once per page no matter
    // how many phases re-scan the DOM. Header-chrome triggers
    // are measured on the first page of a seat+width only, so
    // the table isn't flooded with repeats.
    const measured = new Set();
    const labelCounts = new Map();
    const scanTriggers = () =>
      page.evaluate(() => {
        const inHeader = (el) => !!el.closest("header, .tv-header, .tv-topbar");
        window.__twCounter = window.__twCounter || 0;
        return [...document.querySelectorAll('[aria-haspopup="menu"], .tv-bell-btn')].map((el) => {
          if (!el.dataset.twId) el.dataset.twId = `tw${++window.__twCounter}`;
          return {
            id: el.dataset.twId,
            header: inHeader(el),
            label: (el.getAttribute("aria-label") || el.textContent || "menu").trim().replace(/\s+/g, " ").slice(0, 44) || "menu",
          };
        });
      });
    const discover = async (phasePageName) => {
      const metas = await scanTriggers();
      for (const meta of metas) {
        if (meta.header && !opts.header) continue;
        if (measured.has(meta.id)) continue;
        const trigger = page.locator(`[data-tw-id="${meta.id}"]`).first();
        if (!(await trigger.isVisible().catch(() => false))) continue; // a later phase may reveal it
        const seen = labelCounts.get(meta.label) || 0;
        if (seen >= 12) { measured.add(meta.id); continue; } // per-label instance cap
        labelCounts.set(meta.label, seen + 1);
        measured.add(meta.id);
        const label = seen > 0 ? `${meta.label} #${seen + 1}` : meta.label;
        const slug = `${slugify(seatName)}-${slugify(phasePageName)}-${slugify(meta.label)}${seen ? `-${seen + 1}` : ""}-${viewport.width}`;
        try {
          if (await openAndMeasure(page, trigger, seatName, phasePageName, label, viewport.width, SHOTS, slug)) failed = true;
        } catch (err) {
          rows.push({ seat: seatName, page: phasePageName, menu: label, width: viewport.width, result: "ERROR", detail: String(err.message || err).slice(0, 90) });
          failed = true;
          await page.keyboard.press("Escape").catch(() => {});
        }
      }
    };

    await discover(pageName);

    // Tab panels: menus that only exist on a non-default tab.
    const tabs = page.locator('[role="tab"]');
    const nTabs = await tabs.count().catch(() => 0);
    for (let t = 0; t < Math.min(nTabs, 8); t++) {
      const tab = tabs.nth(t);
      if ((await tab.getAttribute("aria-selected").catch(() => null)) === "true") continue;
      const tabName = (((await tab.textContent().catch(() => "")) || "").trim().replace(/\s+/g, " ").slice(0, 24)) || `tab ${t + 1}`;
      const urlBefore = page.url();
      await tab.click({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(650);
      await discover(`${pageName} · ${tabName} tab`);
      if (page.url() !== urlBefore) break; // the "tab" navigated — its page is a census row of its own
    }

    // Customize/edit mode: the "+ Add" block menus live there.
    const cust = page.locator("button").filter({ hasText: /^\s*customize\s*$/i }).first();
    if ((await cust.count().catch(() => 0)) && (await cust.isVisible().catch(() => false))) {
      await cust.click({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(800);
      await discover(`${pageName} · Customize`);
      const done = page.locator("button").filter({ hasText: /^\s*(done|finish|close|save layout)\s*$/i }).first();
      if (await done.count().catch(() => 0)) await done.click({ timeout: 3000 }).catch(() => {});
      else await cust.click({ timeout: 3000 }).catch(() => {});
      await page.waitForTimeout(400);
    }

    if (!rows.some((r) => r.page === pageName && r.seat === seatName && r.width === viewport.width)) {
      rows.push({ seat: seatName, page: pageName, menu: "(no menu triggers found)", width: viewport.width, result: "—", detail: "page carries no menus" });
    }
    console.error(`menu-fit · ${seatName} ${pageName} @${viewport.width}: ${measured.size} trigger(s) measured, ${nTabs} tab(s) walked`);
  } finally {
    await ctx.close();
  }
  return failed;
}

/* ---------- main ---------- */
fs.mkdirSync(SHOTS, { recursive: true });
const chromium = loadChromium();
const browser = await chromium.launch({ executablePath: chromePath(), args: ["--no-first-run"] });
let failed = false;
try {
  if (FIXTURE_URL) {
    const ctx = await browser.newContext({ viewport: PHONE });
    const page = await ctx.newPage();
    await page.goto(FIXTURE_URL, { waitUntil: "networkidle", timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(500);
    const all = page.locator(TRIGGER_SEL);
    const total = await all.count();
    if (!total) { console.error("menu-fit — fixture page has no menu triggers"); process.exit(2); }
    for (let i = 0; i < total; i++) {
      const trigger = all.nth(i);
      const label = ((await trigger.getAttribute("aria-label")) || (await trigger.textContent()) || "menu").trim().slice(0, 44);
      if (await openAndMeasure(page, trigger, "fixture", "Fixture page", label, PHONE.width, SHOTS, `fixture-${i}-${PHONE.width}`)) failed = true;
    }
    await ctx.close();
  } else {
    if (!process.env.TBV_EMAIL || !process.env.TBV_PASSWORD) {
      console.error("menu-fit — TBV_EMAIL / TBV_PASSWORD are required (seat credentials from env, never committed)");
      process.exit(2);
    }
    const seats = [];
    const ownerTok = login(process.env.TBV_EMAIL, process.env.TBV_PASSWORD);
    seats.push({ name: "owner", tok: ownerTok, pages: ownerPages(discoverIds(ownerTok)) });
    if (process.env.TBV_ADMIN_EMAIL && process.env.TBV_ADMIN_PASSWORD) {
      const tok = login(process.env.TBV_ADMIN_EMAIL, process.env.TBV_ADMIN_PASSWORD);
      seats.push({ name: "admin", tok, pages: ADMIN_PAGES });
    }
    if (process.env.TBV_RUNG_EMAIL && process.env.TBV_RUNG_PASSWORD) {
      const tok = login(process.env.TBV_RUNG_EMAIL, process.env.TBV_RUNG_PASSWORD);
      seats.push({ name: "rung", tok, pages: RUNG_PAGES });
    }
    for (const seat of seats) {
      if (process.env.TBV_ONLY) {
        const only = new Set(process.env.TBV_ONLY.split(",").map((s) => s.trim()));
        seat.pages = seat.pages.filter(([name]) => only.has(name));
      }
      let firstPage = true;
      for (const [pageName, pagePath] of seat.pages) {
        if (!pagePath) {
          rows.push({ seat: seat.name, page: pageName, menu: "(detail id not seeded)", width: PHONE.width, result: "SKIP", detail: "no fixture row on this stack" });
          continue;
        }
        if (await runPage(browser, seat.tok, seat.name, pageName, pagePath, PHONE, { header: firstPage, rail: firstPage })) failed = true;
        firstPage = false;
      }
      // Desktop spot-checks.
      for (const [pageName, pagePath] of seat.pages) {
        if (!pagePath || !DESKTOP_SPOT.has(pageName)) continue;
        if (await runPage(browser, seat.tok, seat.name, pageName, pagePath, DESKTOP, { header: pageName === "Home" || (seat.name === "admin" && pageName === "Admin home") })) failed = true;
      }
    }
  }
} finally {
  await browser.close();
}

/* ---------- report ---------- */
const w = (s, n) => String(s ?? "").padEnd(n).slice(0, n);
console.log(`\nmenu-fit tripwire — ${FIXTURE_URL ? `fixture ${FIXTURE_URL}` : BASE} — viewport widths 390 (+1280 spot-check)`);
console.log(`${w("SEAT", 8)} ${w("PAGE", 34)} ${w("MENU", 46)} ${w("W", 5)} ${w("RESULT", 11)} DETAIL`);
for (const r of rows) {
  console.log(`${w(r.seat, 8)} ${w(r.page, 34)} ${w(r.menu, 46)} ${w(r.width, 5)} ${w(r.result, 11)} ${r.detail}${r.shot ? `  [shot: ${r.shot}]` : ""}`);
}
const bad = rows.filter((r) => ["OFF-SCREEN", "EMPTY", "NO-OPEN", "ERROR"].includes(r.result));
const checked = rows.filter((r) => r.result === "fits").length;
console.log(`\nmenu-fit — ${checked} menu(s) fit, ${bad.length} offender(s), ${rows.length} row(s) total.`);
if (process.env.TBV_REPORT) fs.writeFileSync(process.env.TBV_REPORT, JSON.stringify({ base: BASE, rows }, null, 2));
if (bad.length) {
  console.error("menu-fit — FAIL: menu(s) off-screen / empty / unopenable above. Screenshots in " + SHOTS);
  process.exit(1);
}
console.log("menu-fit — OK: every menu fits.");
