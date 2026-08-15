/**
 * Safety and honesty guards on the browser bundle.
 *
 * REWRITTEN 2026-08-14. The previous version asserted on UI COPY — "browser observes",
 * "PANIC PREVIEW", "Exit rules", "CANNOT EXECUTE" — which prose-locked a specific
 * rendering. When the UI was rebuilt as an observability console those four assertions
 * failed while every safety property still held, i.e. the test reported danger where
 * there was only a rewrite. A guard that fires on wording rather than behaviour trains
 * people to ignore it.
 *
 * What is asserted here instead:
 *   1. NEGATIVES on the money path — no key material, no signing, no write verbs. These
 *      are the properties worth failing a build over, and they are all preserved verbatim
 *      from the original file.
 *   2. STRUCTURE — the endpoints the console actually reads, and that it reads them.
 *   3. The two honesty invariants this codebase paid for: absence must not render as
 *      zero, and a cost basis must never be seeded from a market value.
 */

import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const APP = fileURLToPath(new URL("../app/", import.meta.url));

async function walk(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await walk(full)));
    else if (/\.(tsx?|jsx?)$/.test(entry.name)) out.push(full);
  }
  return out;
}

/** Every source file under app/, so a new view cannot silently escape these guards. */
async function appSource() {
  const files = await walk(APP);
  const chunks = await Promise.all(files.map((f) => readFile(f, "utf8")));
  return chunks.join("\n");
}

test("builds", async () => {
  const html = await readFile(new URL("../dist/index.html", import.meta.url), "utf8");
  assert.match(html, /<title>[^<]+<\/title>/i);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("no key material or signing anywhere in browser code", async () => {
  const page = await appSource();
  // The single most important property in the repo: the signer lives in the sentinel,
  // behind three gates, and nothing in a browser bundle may reach it.
  assert.doesNotMatch(
    page,
    /helius_api_key|secret_key|private_key|bot_token|signedTransaction|keypair/i,
  );
  assert.doesNotMatch(page, /\/execute|\/panic"/);
});

/**
 * The write allowlist. Two entries, and the second was added deliberately on 2026-08-15
 * when the coin explorer landed — a guard that gets edited to make a build pass is worth
 * nothing, so the reasoning is written down here rather than in a commit message.
 *
 * `/api/policies` — reaches the SENTINEL, the process that holds the signing key. A policy
 *   write is a rule into config.yaml; the sentinel reads it on its own cycle and decides
 *   for itself. It is the only thing the browser may put into that process.
 *
 * `/hunch` and `/hunch/zap` — reach the PAPER DESK on a different port (8790), which by
 *   construction holds no key, has no RPC client and no broadcast path, and answers
 *   `can_execute: false` on every health response. They append one row each to
 *   state/hunches.jsonl and state/zaps.jsonl. They are write paths into a process that
 *   CANNOT EXECUTE — which is the whole reason `shitcoims_paperdesk` is not part of the
 *   sentinel. `/hunch/zap` is a paper exit: it records an intention the desk acts on in
 *   its own book, and it signs nothing.
 *
 * The property being defended is unchanged: no write verb may reach a route that a signing
 * process consumes. Widening this list again requires the same argument.
 */
const ALLOWED_WRITE_TARGETS = [
  /\/api\/policies/,
  /HUNCH_PATH|["'`]\/hunch["'`]/,
  /ZAP_PATH|["'`]\/hunch\/zap["'`]/,
];

test("writes are confined to the policy endpoint and the keyless hunch tape", async () => {
  const page = await appSource();
  // NOT "no writes" — editing a policy is a legitimate operator action, and so is recording
  // a hunch. The property that matters is that neither can become an execution trigger, a
  // panic, or a queue that a signing process consumes. So every write verb must sit in a
  // fetch whose URL is on the allowlist above.
  const writes = [...page.matchAll(/fetch\(([\s\S]{0,400}?)method:\s*["'](POST|PUT|PATCH|DELETE)["']/g)];
  assert.ok(writes.length > 0, "expected at least the policy editor to write");
  for (const [, between, verb] of writes) {
    assert.ok(
      ALLOWED_WRITE_TARGETS.some((allowed) => allowed.test(between)),
      `a ${verb} targets something that is neither /api/policies nor /hunch — that is a new write path out of the browser: ${JSON.stringify(between.slice(0, 120))}`,
    );
  }
  assert.doesNotMatch(page, /fetch\([^)]*\/(panic|execute)/);
});

test("the hunch write path is the literal it claims to be", async () => {
  // The allowlist above accepts the CONSTANT `HUNCH_PATH` because that is how the client
  // spells its own route. That indirection is only safe while the constant is the route it
  // names, so pin it: a HUNCH_PATH quietly repointed at the sentinel would otherwise walk
  // straight through the guard.
  const client = await readFile(new URL("../app/lib/hunch.ts", import.meta.url), "utf8");
  assert.match(client, /export const HUNCH_PATH = "\/hunch";/);
  assert.match(client, /export const ZAP_PATH = "\/hunch\/zap";/);
  assert.doesNotMatch(client, /8787|\/api\//);
});

test("the zap has no confirmation gate", async () => {
  // Doctrine, and the operator asked for it by name: arming is ceremony, stopping is
  // instant. A confirm dialog on the exit path would measure the dialog instead of the
  // operator, and a decorative undo would lie about a row that is already fsynced. This
  // guard fails if either ever appears near the zap.
  const view = await readFile(new URL("../app/views/explorer.tsx", import.meta.url), "utf8");
  assert.match(view, /postZap/);
  assert.doesNotMatch(view, /window\.confirm|confirmZap|"Are you sure"|undoZap/i);
});

test("the two processes keep two ports", async () => {
  // 8787 holds the key. 8790 (paperdesk glass) cannot sign anything. The dev proxy is the
  // one place those two could be collapsed into one origin by a one-line edit, so both are
  // asserted — and /hunch is asserted NOT to point at 8787 under any spelling.
  const config = await readFile(new URL("../vite.config.ts", import.meta.url), "utf8");
  assert.match(config, /"\/api":\s*"http:\/\/127\.0\.0\.1:8787"/);
  assert.match(config, /"\/hunch":\s*"http:\/\/127\.0\.0\.1:8790"/);
  assert.doesNotMatch(config, /"\/hunch":\s*"[^"]*:8787"/);
});

test("no raw HTML injection", async () => {
  const page = await appSource();
  assert.doesNotMatch(page, /dangerouslySetInnerHTML/);
});

test("reads the endpoints it claims to read", async () => {
  const page = await appSource();
  for (const route of [
    "/api/snapshot",
    "/api/events",
    "/api/trades",
    "/api/performance",
    "/hunch/coins",
    "/hunch/health",
    "/hunch/resolve",
    "/hunch/readout",
    "/hunch/tape",
  ]) {
    assert.match(page, new RegExp(route.replace(/\//g, "\\/")));
  }
});

test("a cost basis is never seeded from a market value", async () => {
  const page = await appSource();
  // The -7.47 SOL mechanism: stamping a basis from the current exit quote makes PnL
  // start at 0% by construction, so a stop fires that far below wherever the coin had
  // already fallen. The rebuilt console makes this a compile error by keeping basis out
  // of the draft type; this guard catches a regression that reintroduces the field.
  assert.doesNotMatch(page, /cost_basis_sol:\s*(quoted|exitSol|bag\.exit_sol|Number\(exitSol)/);
});

test("absence is not rendered as zero", async () => {
  const page = await appSource();
  // Distinguishing "not measured" from "measured zero" is the honesty invariant the
  // netmap, the LP report and the tape all enforce; the console must not flatten it.
  assert.match(page, /unobserved|not watching|never|—/i);
});
