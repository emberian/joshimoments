import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";
import { z } from "zod";

/**
 * Exact browser mirror of the narrow `MemoryOccurrence::OperatorAct` wire family.
 *
 * This is deliberately separate from the older operator-command UI vocabulary.  The browser may
 * retain these canonical bytes, but cannot treat them as a durable scientific-memory occurrence
 * or a research admission.  Those claims require the private store receipt described in
 * `06_SCIENTIFIC_MEMORY.md`.
 */

const identity = z.string().min(1).max(255).refine(
  (value) => value.trim() === value && !/[\u0000-\u001f\u007f]/.test(value),
  "must be a bounded, unpadded identity without control characters",
);
const text = z.string().min(1).max(16 * 1024).refine(
  (value) => !/[\u0000-\u001f\u007f]/.test(value),
  "must not contain control characters",
);
const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/, "must be a lowercase SHA-256 digest");
const canonicalU64 = z.string().regex(/^(?:0|[1-9]\d*)$/, "must be a canonical decimal u64 string")
  .refine((value) => BigInt(value) <= 18_446_744_073_709_551_615n, "must fit u64");
const positiveCanonicalU64 = canonicalU64.refine((value) => value !== "0", "must be a positive decimal u64 string");

const sceneRef = z.object({
  sceneId: identity,
  sceneDigest: digest,
  // CatalogCommitSeq: intentionally a distinct field/schema from LogicalSessionTick.
  catalogCutoff: positiveCanonicalU64,
}).strict();

const sceneBinding = z.discriminatedUnion("status", [
  z.object({ status: z.literal("committed"), value: sceneRef }).strict(),
  z.object({ status: z.literal("missing"), value: z.object({ reason: text }).strict() }).strict(),
]);

const presentationOccurrence = z.object({
  occurrenceId: identity,
  presentationId: identity,
  scene: sceneRef,
  renderDigest: digest,
  viewport: text,
  focus: text,
  occurredAt: positiveCanonicalU64,
}).strict();

const presentationGap = z.object({
  gapId: text,
  scene: sceneRef.nullable(),
  reason: z.enum(["not_mounted", "capture_failed", "navigation_unknown", "restart", "unavailable"]),
  detectedAt: positiveCanonicalU64,
}).strict();

const presentationBinding = z.discriminatedUnion("status", [
  z.object({ status: z.literal("occurrence"), value: presentationOccurrence }).strict(),
  z.object({ status: z.literal("gap"), value: presentationGap }).strict(),
]);

const actKind = z.union([
  z.enum([
    "notice",
    "inspect",
    "compare",
    "mark",
    "watch_flat",
    "arm_shadow",
    "declare_take_some",
    "declare_keep_remainder",
    "zap_intent",
    "declare_reentry",
    "declare_close",
    "correct",
  ]),
  z.object({ external_manual_execution_escape: z.object({ reason: text }).strict() }).strict(),
]);

const assertion = z.object({
  assertionId: identity,
  disposition: z.discriminatedUnion("kind", [
    z.object({ kind: z.literal("verbatim"), value: z.object({ text }).strict() }).strict(),
    z.object({ kind: z.literal("opaque"), value: z.object({ tokenDigest: digest }).strict() }).strict(),
    z.object({ kind: z.literal("cannot_articulate") }).strict(),
  ]),
}).strict();

export const operatorActOccurrenceSchema = z.object({
  kind: z.literal("operator_act"),
  value: z.object({
    actId: identity,
    sessionId: identity,
    // LogicalSessionTick: never compare or substitute this with catalogCutoff.
    occurredAt: positiveCanonicalU64,
    scene: sceneBinding,
    presentation: presentationBinding,
    kind: actKind,
    subject: text.nullable(),
    assertion: assertion.nullable(),
  }).strict().superRefine((act, context) => {
    if (act.presentation.status === "occurrence" && act.presentation.value.occurredAt > act.occurredAt) {
      context.addIssue({ code: "custom", message: "presentation cannot occur after its operator act", path: ["presentation", "value", "occurredAt"] });
    }
    if (act.scene.status === "committed") {
      const presentationScene = act.presentation.status === "occurrence"
        ? act.presentation.value.scene
        : act.presentation.value.scene;
      if (presentationScene && (presentationScene.sceneId !== act.scene.value.sceneId
        || presentationScene.sceneDigest !== act.scene.value.sceneDigest
        || presentationScene.catalogCutoff !== act.scene.value.catalogCutoff)) {
        context.addIssue({ code: "custom", message: "scene and presentation must close to the same committed scene", path: ["presentation"] });
      }
    }
  }),
}).strict();

export type OperatorActOccurrence = z.infer<typeof operatorActOccurrenceSchema>;

function decodeNoDuplicateJson(bytes: Uint8Array): unknown {
  const raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  const duplicateError = validateJsonWithoutDuplicateKeys(raw, false);
  if (duplicateError !== undefined) throw new Error(`invalid scientific-memory JSON: ${duplicateError}`);
  return JSON.parse(raw, (key, value: unknown) => {
    if (key === "__proto__" || key === "constructor" || key === "prototype") {
      throw new Error(`forbidden scientific-memory JSON key: ${key}`);
    }
    return value;
  }) as unknown;
}

/** Returns canonical serde-compatible UTF-8 bytes after strict structural validation. */
export function canonicalOperatorActBytes(input: OperatorActOccurrence): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(operatorActOccurrenceSchema.parse(input)));
}

/**
 * Refuses duplicate keys, invalid/ambiguous u64 strings, noncanonical timestamps, and any byte
 * representation that is not the exact canonical Rust/serde object ordering.
 */
export function parseCanonicalOperatorActBytes(bytes: Uint8Array): OperatorActOccurrence {
  const parsed = operatorActOccurrenceSchema.parse(decodeNoDuplicateJson(bytes));
  const canonical = canonicalOperatorActBytes(parsed);
  if (canonical.byteLength !== bytes.byteLength || canonical.some((value, index) => value !== bytes[index])) {
    throw new Error("scientific-memory OperatorAct bytes are not canonical");
  }
  return parsed;
}

export function digestOperatorActBytes(bytes: Uint8Array): `sha256:${string}` {
  // Parsing first makes a digest useless as a substitute for exact canonical act bytes.
  parseCanonicalOperatorActBytes(bytes);
  return `sha256:${bytesToHex(sha256(bytes))}`;
}
