#!/usr/bin/env node
/**
 * The parity walk: the browser harness the primary agent drives BEFORE Ember ever sits down.
 *
 * It pairs against a running core + Glass, then walks the exact stations of a live session —
 * board → coin page → hold → journal → advance — screenshotting each one, and exits nonzero
 * when any station is missing, any console error fires, or any request fails outside the
 * feature-detected absence classes (venue readouts, the presentation witness, a single-scene
 * core's absent feed). NORTH_STAR.md: she does QA willingly, but never as the first person to
 * discover a wall.
 *
 * HONESTY OF THE WALK ITSELF: this walk records real operator acts (a hold, a hold note, a
 * journal entry) into the live catalog. Every act it writes names itself as harness output in
 * its own words — the hold gets an immediate note saying it is not an operator pick, and the
 * journal entry says it is a harness walk — so the selection instrument and any later reader
 * can exclude them by their stated provenance instead of guessing.
 *
 * Run:
 *   JOSHI_GLASS_URL=http://127.0.0.1:4173 \
 *   JOSHI_PAIRING_CODE_FILE=/path/to/pairing-code \
 *   node qa/walk.mjs
 *
 * Flags/env:
 *   --url / JOSHI_GLASS_URL              Glass origin (the vite dev server). Required.
 *   --code / JOSHI_PAIRING_CODE          one-time pairing code (JOSHI-…). One of code/code-file.
 *   --code-file / JOSHI_PAIRING_CODE_FILE  file the launcher wrote with --pairing-code-file.
 *       After a successful pairing the file is DELETED (unless --keep-code-file): the launcher
 *       treats a consumed-and-deleted file as a request to issue a fresh code, so a human can
 *       pair next without ferrying stderr.
 *   --shots / JOSHI_WALK_SHOTS           screenshot directory (default qa/shots/<utc-stamp>).
 *   --headed                             watch it run.
 */

import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const argv = process.argv.slice(2);
function flag(name) {
  const index = argv.indexOf(name);
  return index >= 0 && index + 1 < argv.length ? argv[index + 1] : null;
}
const has = (name) => argv.includes(name);

const glassUrl = flag("--url") ?? process.env.JOSHI_GLASS_URL ?? null;
const codeInline = flag("--code") ?? process.env.JOSHI_PAIRING_CODE ?? null;
const codeFile = flag("--code-file") ?? process.env.JOSHI_PAIRING_CODE_FILE ?? null;
const keepCodeFile = has("--keep-code-file");
const headed = has("--headed");
const stamp = new Date().toISOString().replaceAll(":", "-").slice(0, 19) + "Z";
const here = dirname(fileURLToPath(import.meta.url));
const shotsDir = flag("--shots") ?? process.env.JOSHI_WALK_SHOTS ?? join(here, "shots", stamp);

if (!glassUrl) {
  console.error("walk: no Glass URL. Pass --url or JOSHI_GLASS_URL (the vite dev server origin).");
  process.exit(2);
}
const glassOrigin = new URL(glassUrl).origin;
if (!codeInline && !codeFile) {
  console.error("walk: no pairing code. Pass --code/JOSHI_PAIRING_CODE or --code-file/JOSHI_PAIRING_CODE_FILE.");
  process.exit(2);
}

mkdirSync(shotsDir, { recursive: true });

/** Failed responses that are feature-detected stated absences, never walk failures. */
function absenceClass(url, status) {
  const path = new URL(url).pathname;
  if (path.startsWith("/api/v1/glass/venue-readouts/") && status >= 400 && status < 500) {
    return "venue readout absence (stated by the core, rendered as absence)";
  }
  if (path.startsWith("/api/v1/presentation/") && (status === 404 || status === 405)) {
    return "presentation witness not mounted (stated absence)";
  }
  if (path === "/api/v1/glass/scenes" && status === 404) {
    return "single-scene core: no feed mounted (stated absence)";
  }
  if (path.startsWith("/api/v1/glass/scenes/") && (status === 404 || status === 405)) {
    return "candidate slice / historical scene absent (older core, or a render-bound candidate)";
  }
  return null;
}

const violations = [];
const absences = [];
const stations = [];

function note(station, ok, detail) {
  stations.push({ station, ok, detail });
  console.log(`${ok ? "ok " : "FAIL"}  ${station}${detail ? ` — ${detail}` : ""}`);
}

const browser = await chromium.launch({ headless: !headed });
const context = await browser.newContext({ viewport: { width: 1560, height: 980 } });
const page = await context.newPage();

/** Paths whose 4xx answers are feature-detected absences; used to declassify console echoes. */
const ABSENCE_PATH_PREFIXES = ["/api/v1/glass/venue-readouts/", "/api/v1/presentation/", "/api/v1/glass/scenes"];

page.on("console", (message) => {
  if (message.type() !== "error") return;
  // Chrome echoes every failed network response into the console. The response handler below
  // already classifies those precisely (status + path); counting the echo again would turn a
  // stated absence into a walk failure, so network echoes on absence-class paths are skipped.
  const location = message.location()?.url ?? "";
  if (/^Failed to load resource/.test(message.text())
    && ABSENCE_PATH_PREFIXES.some((prefix) => { try { return new URL(location).pathname.startsWith(prefix); } catch { return false; } })) {
    return;
  }
  violations.push({ kind: "console_error", detail: `${message.text()}${location ? ` (${location})` : ""}` });
});
page.on("pageerror", (error) => {
  violations.push({ kind: "page_error", detail: String(error) });
});
page.on("response", (response) => {
  const status = response.status();
  if (status < 400) return;
  const url = response.url();
  if (new URL(url).origin !== glassOrigin) return;
  const absence = absenceClass(url, status);
  if (absence) absences.push({ url: new URL(url).pathname, status, absence });
  else violations.push({ kind: "failed_request", detail: `${status} ${new URL(url).pathname}` });
});
page.on("requestfailed", (request) => {
  const failure = request.failure()?.errorText ?? "";
  // Aborts are the client's own AbortControllers doing their job.
  if (failure.includes("ERR_ABORTED")) return;
  violations.push({ kind: "request_failed", detail: `${failure} ${new URL(request.url()).pathname}` });
});

async function shot(name) {
  await page.screenshot({ path: join(shotsDir, name), fullPage: false });
}

let exitCode = 0;
try {
  // ── Station 0: the pairing gate ────────────────────────────────────────────────────────
  await page.goto(glassUrl, { waitUntil: "domcontentloaded" });
  const codeInput = page.getByLabel(/one-time pairing code/i);
  await codeInput.waitFor({ timeout: 15_000 });
  await shot("00-pairing-gate.png");
  const code = (codeInline ?? readFileSync(codeFile, "utf8")).trim();
  await codeInput.fill(code);
  await page.getByRole("button", { name: /pair locally/i }).click();
  note("pair", true, "code submitted");

  // ── Station 1: the board ───────────────────────────────────────────────────────────────
  const board = page.getByRole("region", { name: /hunt board/i });
  await board.waitFor({ timeout: 20_000 });
  await page.locator("[data-candidate-id]").first().waitFor({ timeout: 20_000 });
  const rowCount = await page.locator("[data-candidate-id]").count();
  if (codeFile && !keepCodeFile) {
    // Consumed: delete so the launcher reissues a fresh code for the human on its next tick.
    try { rmSync(codeFile); } catch { /* already gone is fine */ }
  }
  await shot("01-board.png");
  note("board", true, `${rowCount} rows mounted`);

  // Walk the selection a little the way she would.
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await page.keyboard.press("k");

  // ── Station 2: the coin page, one click from a row ─────────────────────────────────────
  await page.locator("[data-candidate-id]").first().click();
  await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 15_000 });
  await page.getByRole("heading", { name: /venue & instruments/i }).waitFor({ timeout: 15_000 });
  await page.getByRole("heading", { name: /chart and knowability/i }).waitFor({ timeout: 15_000 });
  const coinTitle = (await page.getByRole("heading", { level: 1 }).first().textContent())?.trim();
  // Let the chart's lazy chunk land and the venue answer (or its stated absence) settle.
  await page.waitForTimeout(1_500);
  await shot("02-coin-page.png");
  note("coin page", true, coinTitle ?? "");

  // ── Station 3: hold, then immediately mark the hold as harness output ──────────────────
  await page.keyboard.press(";");
  const rail = page.getByRole("region", { name: /held coins/i });
  await rail.waitFor({ timeout: 15_000 });
  await rail.getByRole("heading", { level: 3 }).first().waitFor({ timeout: 15_000 });
  await rail.getByText(/add a note/i).first().click();
  await rail.getByRole("textbox").first().fill(
    "Automated parity walk (apps/glass/qa/walk.mjs). This hold is harness output, not an operator pick.",
  );
  await rail.getByRole("button", { name: /append note/i }).first().click();
  await shot("03-held.png");
  note("hold", true, "held + provenance note appended");

  // ── Station 4: the journal ─────────────────────────────────────────────────────────────
  await page.getByRole("button", { name: /^journal$/i }).click();
  const journalWords = page.locator("#journal-entry-words");
  await journalWords.waitFor({ timeout: 15_000 });
  const walkEntry = `Automated parity walk at ${stamp} (apps/glass/qa/walk.mjs); not operator words.`;
  await journalWords.fill(walkEntry);
  await page.getByRole("button", { name: /append journal entry/i }).click();
  await page.getByText("Automated parity walk at", { exact: false }).first().waitFor({ timeout: 15_000 });
  await shot("04-journal.png");
  note("journal", true, "entry appended and visible");

  // ── Station 5: advance, when a newer scene exists ──────────────────────────────────────
  await page.keyboard.press("'");
  await board.waitFor({ timeout: 15_000 });
  const sessionScene = () => page.locator(".operational-session-bar").getByText(/^Scene /).textContent();
  const advancePill = page.getByRole("button", { name: /advance/i }).first();
  // Scenes only advance when the followed source actually delivered new observations, so a
  // bounded wait is honest: long enough to catch a keeper mid-cadence plus the 20s feed poll,
  // short enough that a genuinely quiet market ends the walk as a stated absence.
  const advanceWaitMs = Number(process.env.JOSHI_WALK_ADVANCE_WAIT_MS ?? "45000");
  const waitUntil = Date.now() + advanceWaitMs;
  while (Date.now() < waitUntil && !(await advancePill.isVisible().catch(() => false))) {
    await page.waitForTimeout(2_000);
  }
  if (await advancePill.isVisible().catch(() => false)) {
    const before = await sessionScene().catch(() => null);
    await advancePill.click();
    await page.waitForTimeout(2_000);
    const after = await sessionScene().catch(() => null);
    await shot("05-advance.png");
    if (before !== null && after !== null && before !== after) {
      note("advance", true, `${before} -> ${after}`);
    } else {
      note("advance", false, `scene label did not change (${before} -> ${after})`);
      exitCode = 1;
    }
  } else {
    await shot("05-advance-absent.png");
    // A quiet feed is a fact, not a failure: scenes advance only when the source delivered
    // new observations. The report states the absence; the primary decides whether to wait.
    note("advance", true, "no newer scene existed during the walk (stated absence, not a failure)");
  }
} catch (error) {
  violations.push({ kind: "walk_error", detail: String(error) });
  await shot("99-failure.png").catch(() => {});
  exitCode = 1;
}

if (violations.length > 0) exitCode = 1;

const report = {
  walkedAt: stamp,
  glassUrl,
  stations,
  absencesStated: absences,
  violations,
  shots: shotsDir,
};
writeFileSync(join(shotsDir, "report.json"), JSON.stringify(report, null, 2));

console.log("");
if (absences.length > 0) {
  console.log("stated absences (feature-detected, not failures):");
  for (const absence of absences) console.log(`  ${absence.status} ${absence.url} — ${absence.absence}`);
}
if (violations.length > 0) {
  console.log("VIOLATIONS:");
  for (const violation of violations) console.log(`  [${violation.kind}] ${violation.detail}`);
}
console.log(`\nscreenshots + report.json in ${shotsDir}`);
console.log(exitCode === 0 ? "walk PASSED" : "walk FAILED");

await browser.close();
process.exit(exitCode);
