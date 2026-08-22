import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SOURCE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * A module whose name says it holds authored data. Importing one from a module that can run in a
 * live session is how authored numbers reach a screen that reads as real: on 2026-08-21 the live
 * cockpit rendered a fixture's wallet-flow figures because `data/client.ts` pulled
 * `explorationBundleFor` out of `presentation/fixtures`.
 */
const AUTHORED_MODULE = /(^|\/)(fixtures?|golden|mock[A-Za-z0-9]*)$/i;

/**
 * One entry per *symbol* that crosses into production, not one per module edge.
 *
 * Module granularity is not enough, and that is the lesson of the defect this guard exists for:
 * `data/client.ts` already imported `presentation/fixtures` legitimately for a presentation
 * policy, so a module-level allowlist would have said nothing when a fixture *bundle builder*
 * started crossing the same edge. Every symbol needs its own justification a reader can check.
 * Shrink this list; never grow it without a reason, and "it was already like that" is not one.
 */
const ALLOWED = new Map<string, string>([
  [
    "data/client.ts -> data/mockSnapshot :: mockSnapshots",
    "OfflineFixtureDataSource is the fixture source; serving the fixture is its whole job.",
  ],
  [
    "App.tsx -> presentation/fixtures :: explorationBundleFor",
    "Reached only on the offline_fixture branch of presentationMaterials. A loopback source must "
      + "never reach it; servedSceneBundle.ts is the live path.",
  ],
  [
    "operational/fixtures.ts -> data/mockSnapshot :: mockSnapshots",
    "A fixture module composing fixtures; imported only by tests.",
  ],
  [
    "operational/fixtures.ts -> presentation/fixtures :: explorationBundleFor",
    "A fixture module composing fixtures; imported only by tests.",
  ],
]);

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry) || /\.d\.ts$/.test(entry)) return [];
    return [path];
  });
}

/** Every `from "./x"` edge in one file, expanded to one record per imported symbol. */
function authoredEdges(file: string): string[] {
  const text = readFileSync(file, "utf8");
  const from = relative(SOURCE_ROOT, file).replaceAll("\\", "/");
  const edges: string[] = [];
  for (const match of text.matchAll(/import\s+([\s\S]*?)\s+from\s+"(\.[^"]*)"/g)) {
    const clause = match[1];
    const specifier = match[2];
    if (clause === undefined || specifier === undefined) continue;
    const target = relative(SOURCE_ROOT, resolve(dirname(file), specifier)).replaceAll("\\", "/");
    if (!AUTHORED_MODULE.test(target)) continue;
    // `import type { … }` carries no value into the bundle and cannot render a number.
    if (/^type\b/.test(clause.trim())) continue;
    const braced = /\{([\s\S]*)\}/.exec(clause);
    const symbols = braced?.[1] === undefined
      ? [clause.trim()]
      : braced[1].split(",")
          .map((part) => part.trim())
          .filter((part) => part.length > 0 && !part.startsWith("type "))
          .map((part) => part.split(/\s+as\s+/)[0]?.trim() ?? part);
    for (const symbol of symbols) edges.push(`${from} -> ${target} :: ${symbol}`);
  }
  return edges;
}

function liveEdges(): string[] {
  return sourceFiles(SOURCE_ROOT).flatMap(authoredEdges).sort();
}

describe("authored-data symbols stay out of production imports", () => {
  it("lets no unjustified symbol cross from a fixture, golden, or mock module into production", () => {
    expect(liveEdges().filter((edge) => !ALLOWED.has(edge))).toEqual([]);
  });

  it("keeps the allowlist honest by failing on an entry that no longer exists", () => {
    const live = new Set(liveEdges());
    expect([...ALLOWED.keys()].filter((edge) => !live.has(edge))).toEqual([]);
  });
});
