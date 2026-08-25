#!/usr/bin/env node
/**
 * The walk's self-test: mockcore + vite + walk.mjs, wired together and torn down.
 *
 * Proves the HARNESS, not the product: every station of `qa/walk.mjs` must go green against
 * `qa/mockcore.mjs` — including a real advance, because the mock's second scene appears ~20s
 * in — so that when a live walk fails, the failure is evidence about the cockpit and not
 * about the walk. Run it after touching the walk, the shell's stations, or the wire schemas:
 *
 *   pnpm qa:selftest
 */

import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const glassDir = join(here, "..");
const VITE_PORT = 4181;
const CORE_PORT = 43991;
const pageOrigin = `http://127.0.0.1:${VITE_PORT}`;
const coreUrl = `http://127.0.0.1:${CORE_PORT}`;

const children = [];
function run(command, args, env = {}) {
  const child = spawn(command, args, {
    cwd: glassDir,
    env: { ...process.env, ...env },
    stdio: ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  child.stdout.on("data", (chunk) => process.stdout.write(chunk));
  child.stderr.on("data", (chunk) => process.stderr.write(chunk));
  return child;
}

async function waitForHttp(url, timeoutMs) {
  const untilAt = Date.now() + timeoutMs;
  while (Date.now() < untilAt) {
    try {
      await fetch(url);
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 400));
    }
  }
  throw new Error(`nothing answered at ${url} within ${timeoutMs}ms`);
}

let exitCode = 1;
try {
  run("node", [join(here, "mockcore.mjs"), "--port", String(CORE_PORT), "--origin", pageOrigin]);
  await waitForHttp(`${coreUrl}/api/v1/glass/scenes`, 8_000);

  run("pnpm", ["exec", "vite", "--host", "127.0.0.1", "--port", String(VITE_PORT), "--strictPort"], {
    VITE_JOSHI_LIVE_SURFACE: "1",
    VITE_JOSHI_CORE_URL: coreUrl,
    VITE_JOSHI_LAUNCH_SCENE_ID: "scene-live-walkmock00000000000000000000001",
  });
  await waitForHttp(pageOrigin, 20_000);

  const walk = run("node", [join(here, "walk.mjs")], {
    JOSHI_GLASS_URL: pageOrigin,
    JOSHI_PAIRING_CODE: "JOSHI-TEST-TEST-0000-0000-0000-0000-0000-0000",
    JOSHI_WALK_ADVANCE_WAIT_MS: "40000",
  });
  exitCode = await new Promise((resolve) => walk.on("exit", (code) => resolve(code ?? 1)));
} catch (error) {
  console.error(`selftest: ${String(error)}`);
  exitCode = 1;
} finally {
  for (const child of children) child.kill("SIGTERM");
}
console.log(exitCode === 0 ? "selftest PASSED — the walk is trustworthy" : "selftest FAILED — fix the walk before trusting a live run");
process.exit(exitCode);
