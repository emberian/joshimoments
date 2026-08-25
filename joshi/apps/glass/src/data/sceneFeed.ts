import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";
import { z } from "zod";

import { glassPairingSession, type MemoryOnlyPairingSession } from "../security/pairing";

/**
 * The scene feed: the local core's list of immutable scenes, newest first.
 *
 * This is a list of facts, not a mutable pointer. The core never changes which scene this cockpit
 * is bound to; the feed only lets the cockpit *learn* that a newer scene exists so the operator
 * can choose to advance. Each row carries the evidence watermark it was cut at
 * (`cutoffCommitSeq`), and the core mints a new scene only when the followed source actually
 * delivered new observations — so a newer row always means new evidence, never a re-render.
 *
 * `catalog` states whether the core could actually look at the source catalog on its last
 * attempt. It is separate from the scene list on purpose: an unreachable catalog must never read
 * as an empty feed.
 */
const wireU64 = z.string().regex(/^(?:0|[1-9]\d*)$/, "must be a non-negative integer string");

const sceneFeedEntrySchema = z.object({
  sceneId: z.string().min(1),
  derivedAt: z.string().min(1),
  cutoffCommitSeq: wireU64,
  subjectCount: wireU64,
  observationCount: wireU64,
  viewDigest: z.string().regex(/^sha256:[0-9a-f]{64}$/),
  // The derivation version that produced this scene's bytes; null when the core's ledger
  // predates version recording. Mirrored from `SceneFeedEntryWire` in
  // `apps/core/src/live_follow.rs` — this schema is strict, so a wire field it does not name
  // fails the WHOLE feed. That exact failure shipped once: the core added
  // `derivationVersion`/`retiredReason` and every poll of a live feed failed parse, which the
  // shell could only report as "scene feed unreachable" — the cockpit sat on its launch scene
  // looking like a photograph while newer scenes accumulated unseen.
  derivationVersion: z.string().min(1).nullable(),
  // A retired scene is a listed historical fact whose bytes an older derivation produced and
  // did not retain: no route serves it any more, so it must never be offered as an advance
  // target. `retiredReason` is stated only on retired rows.
  sceneRetention: z.enum(["durable", "served_not_yet_durable", "retired"]),
  retiredReason: z.string().min(1).nullable(),
}).strict();

const sceneFeedSchema = z.object({
  contract: z.literal("joshi.core.scene_feed"),
  schemaVersion: z.literal(1),
  authority: z.literal("read_only_no_execution"),
  sourceId: z.string().min(1),
  scenes: z.array(sceneFeedEntrySchema),
  catalog: z.object({
    outcome: z.enum(["mounted", "not_yet_polled_since_restart", "advanced", "unchanged", "unreachable"]),
    lastContactAt: z.string().nullable(),
    detail: z.string().nullable(),
    basisCommitSeq: wireU64,
  }).strict(),
}).strict();

export type SceneFeedEntry = z.infer<typeof sceneFeedEntrySchema>;
export type SceneFeedV1 = z.infer<typeof sceneFeedSchema>;

export const MAX_SCENE_FEED_BYTES = 256 * 1024;

export function parseSceneFeedV1(value: unknown): SceneFeedV1 {
  return sceneFeedSchema.parse(value);
}

/** A core that serves one mounted scene and follows nothing: the feed route states its absence. */
export type SceneFeedAbsent = { absent: true };

export class LoopbackSceneFeedSource {
  private readonly baseUrl: URL;
  private readonly pairingSession: MemoryOnlyPairingSession;

  constructor(baseUrl: string, pairingSession: MemoryOnlyPairingSession = glassPairingSession) {
    const parsed = new URL(baseUrl);
    const loopbackHosts = new Set(["127.0.0.1", "localhost", "[::1]"]);
    if (parsed.protocol !== "http:" || !loopbackHosts.has(parsed.hostname)) {
      throw new Error("glass core URL must be an explicit HTTP loopback address");
    }
    this.baseUrl = parsed;
    this.pairingSession = pairingSession;
  }

  async load(signal?: AbortSignal): Promise<SceneFeedV1 | SceneFeedAbsent> {
    const url = new URL("/api/v1/glass/scenes", this.baseUrl);
    const headers: Record<string, string> = { Accept: "application/json" };
    if (this.pairingSession.paired()) {
      headers["X-Joshi-Pairing-Token"] = this.pairingSession.authorizationHeader("cockpit_read");
    }
    const response = await fetch(url, {
      ...(signal ? { signal } : {}),
      credentials: "omit",
      cache: "no-store",
      headers,
    });
    if (response.status === 404) {
      // A single-scene core: no feed is mounted, and no newer scene will ever exist there.
      return { absent: true };
    }
    if (!response.ok) throw new Error(`scene feed request failed (${response.status})`);
    const declaredLength = response.headers.get("Content-Length");
    if (declaredLength !== null && Number(declaredLength) > MAX_SCENE_FEED_BYTES) {
      throw new Error("scene feed exceeds the browser response bound");
    }
    const body = await response.text();
    if (body.length > MAX_SCENE_FEED_BYTES) {
      throw new Error("scene feed exceeds the browser response bound");
    }
    const wireError = validateJsonWithoutDuplicateKeys(body, false);
    if (wireError !== undefined) throw new Error(`invalid scene feed JSON: ${wireError}`);
    return parseSceneFeedV1(JSON.parse(body));
  }
}
