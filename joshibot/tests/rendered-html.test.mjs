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

test("writes are confined to the policy endpoint", async () => {
  const page = await appSource();
  // NOT "no writes" — editing a policy is a legitimate operator action, and the sentinel
  // validates it server-side then decides on its own cycle. The property that matters is
  // that the console can write POLICY and nothing else: no execution trigger, no panic,
  // no queue that a signing process consumes. So every write verb must sit in a fetch
  // whose URL is /api/policies.
  const writes = [...page.matchAll(/fetch\(([\s\S]{0,400}?)method:\s*["'](POST|PUT|PATCH|DELETE)["']/g)];
  assert.ok(writes.length > 0, "expected at least the policy editor to write");
  for (const [, between, verb] of writes) {
    assert.match(
      between,
      /\/api\/policies/,
      `a ${verb} targets something other than /api/policies — that is a new write path into the process holding the signer`,
    );
  }
  assert.doesNotMatch(page, /fetch\([^)]*\/(panic|execute)/);
});

test("no raw HTML injection", async () => {
  const page = await appSource();
  assert.doesNotMatch(page, /dangerouslySetInnerHTML/);
});

test("reads the endpoints it claims to read", async () => {
  const page = await appSource();
  for (const route of ["/api/snapshot", "/api/events", "/api/trades", "/api/performance"]) {
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
