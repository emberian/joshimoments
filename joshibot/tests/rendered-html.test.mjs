import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

async function appSource() {
  const files = [
    "app/page.tsx",
    "app/views/overview.tsx",
    "app/views/positions.tsx",
    "app/views/markets.tsx",
    "app/views/intelligence.tsx",
    "app/views/history.tsx",
    "app/views/performance.tsx",
    "app/lib/api.ts",
    "app/lib/intelligence.ts",
  ];
  const chunks = await Promise.all(files.map((file) => readFile(new URL(`../${file}`, import.meta.url), "utf8")));
  return chunks.join("\n");
}

test("builds the shitcoims sentinel cockpit", async () => {
  const html = await readFile(new URL("../dist/index.html", import.meta.url), "utf8");
  assert.match(html, /<title>shitcoims Sentinel<\/title>/i);
  assert.match(html, /og\.png/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
  const assets = await readdir(new URL("../dist/assets/", import.meta.url));
  assert.ok(assets.some((name) => name.endsWith(".js")));
  assert.ok(assets.some((name) => name.endsWith(".css")));
});

test("keeps keys and execution out of browser code", async () => {
  const page = await appSource();
  assert.doesNotMatch(page, /helius_api_key|secret_key|signedTransaction|\/execute|\/panic"/);
  assert.match(page, /\/api\/snapshot/);
  assert.match(page, /browser observes/i);
});

test("keeps the intelligence plane read-only and epistemically explicit", async () => {
  const page = await appSource();
  assert.match(page, /127\.0\.0\.1:8788\/api/);
  assert.match(page, /\/intelligence\/feed\?limit=50/);
  assert.match(page, /fact/);
  assert.match(page, /claim/);
  assert.match(page, /speculation/);
  assert.match(page, /CANNOT EXECUTE/);
  assert.match(page, /Contradicting evidence/i);
  assert.match(page, /X \/ APIFY TAPE/);
  assert.match(page, /Cashtags stay labels/);
  assert.match(page, /KOL BOARD/);
  assert.match(page, /watched handles/);
  assert.match(page, /watched_handle/);
  assert.doesNotMatch(page, /dangerouslySetInnerHTML|raw_payload|private_key|bot_token/);
});

test("renders an observe-only panic preview", async () => {
  const page = await appSource();
  assert.match(page, /PANIC PREVIEW/);
  assert.match(page, /Nothing was sold/i);
  assert.match(page, /gates/);
  assert.match(page, /CANNOT EXECUTE/);
  assert.match(page, /dry-run lock/);
  assert.match(page, /gate_failures/);
  assert.doesNotMatch(page, /method:\s*["']POST["']|fetch\([^)]*\/panic|fetch\([^)]*\/execute/);
});

test("exposes policy editor and market history surfaces", async () => {
  const page = await appSource();
  assert.match(page, /Exit rules/);
  assert.match(page, /\/api\/policies/);
  assert.match(page, /\/api\/candles/);
  assert.match(page, /\/api\/performance/);
  assert.match(page, /History \/ candles/);
  assert.match(page, /Desk statistics/);
});
