import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { z } from "zod";

import { exactUnixSecondsSchema, exactUtcInstantSchema } from "./instant";

const exactDecimal = z
  .string()
  .regex(/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/, "must be an exact base-10 decimal string");
const integerString = z.string().regex(/^-?(?:0|[1-9]\d*)$/, "must be an integer string");
const wireU64 = z.string().regex(/^(?:0|[1-9]\d*)$/, "must be a non-negative integer string");
const instant = exactUtcInstantSchema;
const sha256Digest = z.string().regex(/^sha256:[0-9a-f]{64}$/, "must be a lowercase SHA-256 digest");
const stableIdentity = z
  .string()
  .regex(/^[A-Za-z0-9][A-Za-z0-9._:-]*$/, "must be a non-empty canonical ASCII identity");
const cursorSubject = z
  .string()
  .regex(/^[\x21-\x7e]+$/, "must be a non-empty canonical ASCII cursor subject");

function sortedBy<T>(
  values: T[],
  identity: (value: T) => string,
  context: z.core.$RefinementCtx<T[]>,
): void {
  for (let index = 1; index < values.length; index += 1) {
    const before = values[index - 1];
    const current = values[index];
    if (before && current && identity(before) >= identity(current)) {
      context.addIssue({
        code: "custom",
        message: "must be strictly sorted by identity with no duplicates",
        path: [index],
      });
    }
  }
}

function sortedArray<T extends z.ZodType>(schema: T, identity: (value: z.infer<T>) => string) {
  return z.array(schema).superRefine((values, context) => sortedBy(values, identity, context));
}

export const evidenceClassSchema = z.enum([
  "observed",
  "derived",
  "attested",
  "interpreted",
]);

export const evidenceRefSchema = z.object({
  id: stableIdentity,
  sourceId: stableIdentity,
  field: z.string().min(1),
  evidenceClass: evidenceClassSchema,
  observedAt: instant.nullable(),
  ingestedAt: instant,
  knownAt: instant,
  status: z.enum(["available", "stale", "gap", "conflicting", "unobserved"]),
  note: z.string().min(1),
}).strict();

export const sourceHealthSchema = z.object({
  id: stableIdentity,
  label: z.string().min(1),
  status: z.enum(["fresh", "degraded", "gap", "fixture"]),
  lastObservedAt: instant.nullable(),
  lastIngestedAt: instant.nullable(),
  coverage: z.string().min(1),
  note: z.string().min(1),
}).strict();

export const candleSchema = z.object({
  timeUnix: exactUnixSecondsSchema,
  knownAt: instant,
  open: exactDecimal,
  high: exactDecimal,
  low: exactDecimal,
  close: exactDecimal,
  volumeTokens: exactDecimal,
}).strict();

export const candidateSchema = z.object({
  id: stableIdentity,
  mint: z.string().min(16),
  symbol: z.string().min(1),
  name: z.string().min(1),
  board: z.enum(["new", "trending", "live", "callouts", "watch"]),
  lifecycle: z.enum(["bonding", "migrating", "graduated", "unknown"]),
  firstKnownAt: instant,
  lastObservedAt: instant,
  rank: wireU64,
  metrics: z.object({
    priceSol: exactDecimal.nullable(),
    marketCapUsd: exactDecimal.nullable(),
    change5mBps: integerString.nullable(),
    ageSeconds: wireU64.nullable(),
    activity: z.enum(["quiet", "building", "two_sided", "bursting", "unknown"]),
    quoteSizeSol: exactDecimal.nullable(),
    executableExitSol: exactDecimal.nullable(),
  }).strict(),
  attentionReason: z.string().min(1),
  socialSummary: z.string().min(1),
  tags: z.array(z.string().min(1)),
  watched: z.boolean(),
  episodeId: z.string().min(1).nullable(),
  evidence: sortedArray(evidenceRefSchema, (value) => value.id).min(1),
  // Empty is legal and means "no price series was observed for this mint". A single bar is not:
  // one point implies an interval it does not have. Bars are never invented to fill the shape.
  candles: z.array(candleSchema).refine((value) => value.length !== 1, "must be empty or contain at least two samples"),
}).strict();

export const socialEventSchema = z.object({
  id: stableIdentity,
  candidateId: stableIdentity,
  eventAt: instant,
  knownAt: instant,
  kind: z.enum(["post", "reply", "callout", "claim", "community", "gap"]),
  author: z.string().min(1).nullable(),
  text: z.string().min(1),
  evidence: evidenceRefSchema,
}).strict();

export const episodeSchema = z.object({
  id: stableIdentity,
  candidateId: stableIdentity,
  state: z.enum(["exposed", "watching_flat", "pending_observation", "resolved"]),
  disposition: z.string().min(1),
  latestNote: z.string().min(1),
  openedAt: instant,
  lastChangedAt: instant,
  accounting: z.object({
    totalSpentSol: exactDecimal,
    totalProceedsSol: exactDecimal,
    realizedNetSol: exactDecimal,
    remainingCostBasisSol: exactDecimal.nullable(),
    executableLiquidationSol: exactDecimal.nullable(),
    currentExposureSol: exactDecimal,
  }).strict(),
  clips: sortedArray(
    z.object({
      id: stableIdentity,
      label: z.string().min(1),
      openedAt: instant,
      closedAt: instant.nullable(),
      realizedNetSol: exactDecimal,
    }).strict(),
    (value) => value.id,
  ),
  nextAttention: z.string().min(1),
}).strict();

export const replayModeSchema = z.enum(["witnessed", "knowledge_cutoff", "retrospective"]);

export const asOfVectorSchema = z.object({
  catalogCommit: wireU64,
  sources: sortedArray(
    z.object({
      sourceId: stableIdentity,
      deliveredThrough: wireU64,
      cursors: sortedArray(
        z.object({
          family: stableIdentity,
          subject: cursorSubject.nullable(),
          cursorKind: stableIdentity,
          value: z.string().min(1),
          advancedThrough: wireU64,
        }).strict(),
        (cursor) => `${cursor.family}\u0000${cursor.subject ?? ""}\u0000${cursor.cursorKind}`,
      ),
      receivedThrough: instant.nullable(),
    }).strict().superRefine((source, context) => {
      source.cursors.forEach((cursor, index) => {
        if (BigInt(cursor.advancedThrough) > BigInt(source.deliveredThrough)) {
          context.addIssue({ code: "custom", message: "scoped cursor cannot advance beyond source delivery", path: ["cursors", index, "advancedThrough"] });
        }
      });
    }),
    (value) => value.sourceId,
  ),
  chain: z
    .object({
      cluster: z.string().min(1),
      slot: wireU64,
      finality: z.string().min(1),
    }).strict()
    .nullable(),
  projections: sortedArray(
    z.object({
      name: stableIdentity,
      version: z.string().min(1),
      stateDigest: sha256Digest,
    }).strict(),
    (value) => value.name,
  ),
  renderedAt: instant,
}).strict().superRefine((asOf, context) => {
  const catalogCommit = BigInt(asOf.catalogCommit);
  asOf.sources.forEach((source, index) => {
    if (BigInt(source.deliveredThrough) > catalogCommit) {
      context.addIssue({ code: "custom", message: "source delivery cannot exceed the catalog cutoff", path: ["sources", index, "deliveredThrough"] });
    }
  });
});

export const glassPayloadV1Schema = z.object({
  sources: sortedArray(sourceHealthSchema, (value) => value.id).min(1),
  candidates: sortedArray(candidateSchema, (value) => value.id).min(1),
  episodes: sortedArray(episodeSchema, (value) => value.id),
  socialEvents: sortedArray(socialEventSchema, (value) => value.id),
}).strict();

export const glassViewV1Schema = z
  .object({
    contract: z.literal("joshi.glass.view"),
    schemaVersion: z.literal(1),
    mode: replayModeSchema,
    sceneId: stableIdentity,
    basisSceneId: stableIdentity.nullable(),
    asOf: asOfVectorSchema,
    payload: glassPayloadV1Schema,
  }).strict()
  .superRefine((view, context) => {
    if (view.mode === "witnessed" && view.basisSceneId !== null) {
      context.addIssue({ code: "custom", message: "witnessed view cannot have a basis scene", path: ["basisSceneId"] });
    }
    if (view.mode !== "witnessed" && view.basisSceneId === null) {
      context.addIssue({ code: "custom", message: "recomputed view must name its witnessed basis scene", path: ["basisSceneId"] });
    }
    const deliveredSources = view.asOf.sources.map((source) => source.sourceId);
    const payloadSources = view.payload.sources.map((source) => source.id);
    if (JSON.stringify(deliveredSources) !== JSON.stringify(payloadSources)) {
      context.addIssue({ code: "custom", message: "payload source health must exactly match as-of source watermarks", path: ["payload", "sources"] });
    }
    const candidateIds = new Set(view.payload.candidates.map((candidate) => candidate.id));
    const episodeIds = new Set(view.payload.episodes.map((episode) => episode.id));
    view.payload.candidates.forEach((candidate, index) => {
      if (candidate.episodeId !== null && !episodeIds.has(candidate.episodeId)) {
        context.addIssue({ code: "custom", message: "candidate references an episode absent from this view", path: ["payload", "candidates", index, "episodeId"] });
      }
    });
    view.payload.episodes.forEach((episode, index) => {
      if (!candidateIds.has(episode.candidateId)) {
        context.addIssue({ code: "custom", message: "episode references a candidate absent from this view", path: ["payload", "episodes", index, "candidateId"] });
      }
    });
    view.payload.socialEvents.forEach((event, index) => {
      if (!candidateIds.has(event.candidateId)) {
        context.addIssue({ code: "custom", message: "social event references a candidate absent from this view", path: ["payload", "socialEvents", index, "candidateId"] });
      }
    });
  });

export const glassSnapshotV1Schema = z.object({
  contract: z.literal("joshi.glass.snapshot"),
  schemaVersion: z.literal(1),
  snapshotDigest: sha256Digest,
  transport: z.enum(["offline_fixture", "loopback"]),
  recordingAuthority: z.literal("read_record_replay_only"),
  view: glassViewV1Schema,
}).strict();

export type EvidenceClass = z.infer<typeof evidenceClassSchema>;
export type EvidenceRef = z.infer<typeof evidenceRefSchema>;
export type SourceHealth = z.infer<typeof sourceHealthSchema>;
export type Candle = z.infer<typeof candleSchema>;
export type Candidate = z.infer<typeof candidateSchema>;
export type SocialEvent = z.infer<typeof socialEventSchema>;
export type Episode = z.infer<typeof episodeSchema>;
export type ReplayMode = z.infer<typeof replayModeSchema>;
export type AsOfVector = z.infer<typeof asOfVectorSchema>;
export type GlassPayloadV1 = z.infer<typeof glassPayloadV1Schema>;
export type GlassViewV1 = z.infer<typeof glassViewV1Schema>;
export type GlassSnapshotV1 = z.infer<typeof glassSnapshotV1Schema>;

/**
 * Canonical glass-view encoding v1: schema-ordered object keys, identity-sorted arrays, no
 * insignificant whitespace, encoded as UTF-8. Rust scene `view_bytes` must contain these exact
 * bytes and declare the inner contract/version above.
 */
export function canonicalGlassViewBytes(view: GlassViewV1): Uint8Array {
  const parsed = glassViewV1Schema.parse(view);
  return new TextEncoder().encode(JSON.stringify(parsed));
}

export function digestGlassView(view: GlassViewV1): `sha256:${string}` {
  return `sha256:${bytesToHex(sha256(canonicalGlassViewBytes(view)))}`;
}

export function parseGlassSnapshotV1(value: unknown): GlassSnapshotV1 {
  const parsed = glassSnapshotV1Schema.parse(value);
  const actual = digestGlassView(parsed.view);
  if (actual !== parsed.snapshotDigest) {
    throw new Error(`glass snapshot digest mismatch: expected ${parsed.snapshotDigest}, computed ${actual}`);
  }
  return parsed;
}
