import { z } from "zod";

import {
  ACQUISITION_SCHEMA,
  BATCH_SCHEMA,
  BRIDGE_PROTOCOL,
  GAP_SCHEMA,
  MAX_SOURCE_BODY_BYTES,
  PARITY_REQUEST_FINGERPRINT_CONTRACT,
  RECEIPT_SCHEMA,
  REQUEST_FINGERPRINT_CONTRACT,
  SOURCE_CLOCK_CONTRACT,
} from "./constants";

export const originIdSchema = z.enum(["pump-frontend", "coin-communities", "pump-profile"]);
export type OriginId = z.infer<typeof originIdSchema>;

export const captureConfigSchema = z
  .object({
    captureEnabled: z.boolean(),
    rawCaptureEnabled: z.boolean(),
    origins: z.record(originIdSchema, z.boolean()),
  })
  .strict();
export type CaptureConfig = z.infer<typeof captureConfigSchema>;

export const DEFAULT_CAPTURE_CONFIG: CaptureConfig = {
  captureEnabled: false,
  rawCaptureEnabled: false,
  origins: {
    "pump-frontend": true,
    "coin-communities": true,
    "pump-profile": false,
  },
};

export const routeIdSchema = z.enum([
  "coin-v2",
  "callout-recent",
  "callout-mint",
  "following",
  "community",
  "community-messages",
  "community-callouts",
  "community-feed",
  "profile-community",
]);
export type RouteId = z.infer<typeof routeIdSchema>;

const wireU64Schema = z
  .string()
  .regex(/^(?:0|[1-9][0-9]*)$/)
  .max(20)
  .refine((value) => BigInt(value) <= 18_446_744_073_709_551_615n, "value exceeds u64::MAX");
const sha256IdSchema = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const SOURCE_TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})Z$/;

/** Strict source-native millisecond UTC accepted across the untrusted page boundary. */
export function isValidSourceTimestamp(value: string): boolean {
  const match = SOURCE_TIMESTAMP_PATTERN.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match;
  if (
    yearText === undefined ||
    monthText === undefined ||
    dayText === undefined ||
    hourText === undefined ||
    minuteText === undefined ||
    secondText === undefined
  ) {
    return false;
  }
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (year < 1 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) {
    return false;
  }
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthDays = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const maximumDay = monthDays[month - 1];
  return maximumDay !== undefined && day >= 1 && day <= maximumDay;
}

export const sourceTimestampSchema = z
  .string()
  .regex(SOURCE_TIMESTAMP_PATTERN)
  .refine(isValidSourceTimestamp, "timestamp is not a real Gregorian UTC millisecond instant");
const jsonNumberLexemeSchema = z
  .string()
  .regex(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/)
  .max(1_024);

export const fieldValueSchema = z.discriminatedUnion("encoding", [
  z.object({ encoding: z.literal("utf8"), value: z.string() }).strict(),
  z.object({ encoding: z.literal("json-number-lexeme"), value: jsonNumberLexemeSchema }).strict(),
  z.object({ encoding: z.literal("boolean"), value: z.boolean() }).strict(),
  z.object({ encoding: z.literal("null"), value: z.null() }).strict(),
  z.object({ encoding: z.literal("utf8-list"), value: z.array(z.string()).max(100) }).strict(),
]);
export type FieldValue = z.infer<typeof fieldValueSchema>;

export const normalizedRecordSchema = z
  .object({
    ordinal: wireU64Schema,
    kind: z.string().min(1).max(80),
    naturalKey: z.string().min(1).max(512),
    fields: z.record(z.string().max(80), fieldValueSchema),
  })
  .strict();
export type NormalizedRecord = z.infer<typeof normalizedRecordSchema>;

export const exactPayloadSchema = z
  .object({
    bodyBase64: z.string().max(Math.ceil(MAX_SOURCE_BODY_BYTES / 3) * 4 + 8),
    blobId: sha256IdSchema,
    bytes: wireU64Schema,
    boundary: z.literal("fetch-response-decoded-body-bytes"),
    protectionClass: z.literal("authenticated-private-source-evidence"),
    retentionClass: z.literal("local-explicit-raw-opt-in"),
    transferEncoding: z.literal("base64"),
  })
  .strict();
export type ExactPayload = z.infer<typeof exactPayloadSchema>;

const pageScopeSchema = z
  .object({
    protocol: z.literal(BRIDGE_PROTOCOL),
    acquisitionId: z.string().uuid(),
    pageInstanceId: z.string().uuid(),
    routeId: routeIdSchema,
    sourceOrigin: z.string().url().max(200),
    sourcePath: z.string().startsWith("/").max(2_000),
    pagePath: z.string().startsWith("/").max(2_000),
    capturedAt: sourceTimestampSchema,
    requestedAt: sourceTimestampSchema,
    sourceClockContract: z.literal(SOURCE_CLOCK_CONTRACT),
    sequence: wireU64Schema,
    requestFingerprint: sha256IdSchema,
    requestFingerprintContract: z.literal(REQUEST_FINGERPRINT_CONTRACT),
    requestProjectionCompleteness: z.enum(["complete", "partial-query"]),
    parityRequestFingerprint: sha256IdSchema,
    parityRequestFingerprintContract: z.literal(PARITY_REQUEST_FINGERPRINT_CONTRACT),
    parityProjectionCompleteness: z.enum(["complete", "partial-query"]),
    visibleFilterFingerprint: sha256IdSchema,
    cursorInFingerprint: sha256IdSchema.nullable(),
    paginationKind: z.string().min(1).max(64),
    pageOrdinal: wireU64Schema,
  })
  .strict();

export const pageResponseAcquisitionSchema = pageScopeSchema.extend({
  kind: z.literal("response-acquisition"),
  responseBlobId: sha256IdSchema,
  responseBytes: wireU64Schema,
  responseStatus: z.number().int().min(200).max(299),
  bodyReadAt: sourceTimestampSchema,
  responseBoundary: z.literal("fetch-response-decoded-body-bytes"),
  mediaType: z.literal("application/json"),
  bodyBase64: z.string().max(Math.ceil(MAX_SOURCE_BODY_BYTES / 3) * 4 + 8),
});
export type PageResponseAcquisition = z.infer<typeof pageResponseAcquisitionSchema>;

export const pageGapObservationSchema = pageScopeSchema.extend({
  kind: z.literal("capture-gap"),
  reason: z.enum(["source-body-too-large", "source-body-read-failed"]),
  responseBytes: wireU64Schema.nullable(),
});
export type PageGapObservation = z.infer<typeof pageGapObservationSchema>;

export const pageObservationSchema = z.discriminatedUnion("kind", [
  pageResponseAcquisitionSchema,
  pageGapObservationSchema,
]);
export type PageObservation = z.infer<typeof pageObservationSchema>;

export const parityCandidateSchema = z
  .object({
    contract: z.literal("joshi.pump_api.parity_input.v2"),
    pairId: z.string().min(1).max(128),
    sourceAcquisitionId: z.string().min(1).max(256),
    source: z.literal("pump_companion"),
    routeId: z.string().min(1).max(80),
    catalogVersion: z.string().min(1).max(128),
    requestFingerprint: sha256IdSchema,
    requestFingerprintContract: z.literal(PARITY_REQUEST_FINGERPRINT_CONTRACT),
    requestProjectionCompleteness: z.enum(["complete", "partial-query"]),
    visibleFilterFingerprint: sha256IdSchema,
    cursorInFingerprint: sha256IdSchema.nullable(),
    paginationKind: z.string().min(1).max(64),
    pageOrdinal: wireU64Schema,
    sessionClass: z.enum(["public", "ordinary_authenticated", "unknown"]),
    sessionOccurrenceId: sha256IdSchema,
    authDisposition: z.enum([
      "not_required_public",
      "ordinary_session_accepted",
      "session_rejected",
      "challenge_or_signature_required",
      "unknown",
    ]),
    comparisonBoundary: z.literal("fetch_response_decoded_body_bytes"),
    startedAt: z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/),
    receivedAt: z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/),
    httpStatus: z.number().int().min(200).max(299),
    bodyBase64: z.string().max(Math.ceil(MAX_SOURCE_BODY_BYTES / 3) * 4 + 8),
    byteLength: wireU64Schema,
    blobId: sha256IdSchema,
    renderedOrderDigest: sha256IdSchema.nullable(),
  })
  .strict();
export type ParityCandidate = z.infer<typeof parityCandidateSchema>;

export const pageConfigMessageSchema = z
  .object({
    protocol: z.literal(BRIDGE_PROTOCOL),
    kind: z.literal("capture-config"),
    leaseUntilEpochMs: z.number().int().positive(),
    config: captureConfigSchema,
  })
  .strict();
export type PageConfigMessage = z.infer<typeof pageConfigMessageSchema>;

export const acquisitionEnvelopeSchema = z
  .object({
    schema: z.literal(ACQUISITION_SCHEMA),
    acquisitionId: z.string().uuid(),
    sourceId: z.literal("pump-companion"),
    acquisitionKind: z.literal("http-response"),
    transportKind: z.literal("browser-fetch"),
    trust: z.literal("page-delivered-untrusted"),
    contractVersion: z.literal("pump-companion-admission.v1"),
    routeId: routeIdSchema,
    sourceOrigin: z.string().url(),
    sourcePath: z.string().startsWith("/"),
    pagePath: z.string().startsWith("/"),
    pageInstanceId: z.string().uuid(),
    capturedAt: sourceTimestampSchema,
    receivedAt: sourceTimestampSchema,
    sourceClockContract: z.literal(SOURCE_CLOCK_CONTRACT),
    sequence: wireU64Schema,
    requestFingerprint: sha256IdSchema,
    requestFingerprintContract: z.literal(REQUEST_FINGERPRINT_CONTRACT),
    requestProjectionCompleteness: z.enum(["complete", "partial-query"]),
    responseBlobId: sha256IdSchema,
    responseBytes: wireU64Schema,
    responseBoundary: z.literal("fetch-response-decoded-body-bytes"),
    mediaType: z.literal("application/json"),
    parseDisposition: z.enum(["parsed", "invalid-json", "no-projectable-records"]),
    sourceRecordCount: wireU64Schema,
    emittedRecordCount: wireU64Schema,
    omittedRecordCount: wireU64Schema,
    records: z.array(normalizedRecordSchema).max(100),
    fidelity: z.enum(["lossy-normalized-attestation", "exact-private-response-bytes"]),
    evidenceDisposition: z.enum([
      "not-admissible-as-exact-observation",
      "candidate-exact-private-observation",
    ]),
    fidelityGap: z
      .object({
        reason: z.literal("exact-source-bytes-withheld-by-user-setting"),
        effect: z.literal("normalized assertions cannot be independently verified by the store"),
      })
      .strict()
      .optional(),
    exactPayload: exactPayloadSchema.optional(),
  })
  .strict()
  .superRefine((value, context) => {
    const exact = value.fidelity === "exact-private-response-bytes";
    if (exact !== (value.exactPayload !== undefined)) {
      context.addIssue({ code: "custom", message: "exact fidelity and exact payload must agree" });
    }
    if (exact !== (value.evidenceDisposition === "candidate-exact-private-observation")) {
      context.addIssue({
        code: "custom",
        message: "exact fidelity and evidence disposition must agree",
      });
    }
    if (exact === (value.fidelityGap !== undefined)) {
      context.addIssue({
        code: "custom",
        message: "lossy fidelity requires exactly one named gap",
      });
    }
  });
export type AcquisitionEnvelope = z.infer<typeof acquisitionEnvelopeSchema>;

export const coverageGapSchema = z
  .object({
    schema: z.literal(GAP_SCHEMA),
    gapId: z.string().uuid(),
    sourceId: z.literal("pump-companion"),
    routeId: routeIdSchema,
    sourceOrigin: z.string().url(),
    sourcePath: z.string().startsWith("/"),
    pagePath: z.string().startsWith("/"),
    pageInstanceId: z.string().uuid(),
    acquisitionId: z.string().uuid(),
    requestFingerprint: sha256IdSchema,
    responseBlobId: sha256IdSchema.nullable(),
    reason: z.enum([
      "source-body-too-large",
      "source-body-read-failed",
      "boundary-validation-failed",
      "item-too-large",
      "queue-full",
    ]),
    sequenceStart: wireU64Schema,
    sequenceEnd: wireU64Schema,
    lastAcceptedSequence: wireU64Schema.nullable(),
    firstResumedSequence: wireU64Schema.nullable(),
    capturedAtStart: sourceTimestampSchema,
    capturedAtEnd: sourceTimestampSchema,
    detectedAt: sourceTimestampSchema,
    sourceClockContract: z.literal(SOURCE_CLOCK_CONTRACT),
    droppedAcquisitions: wireU64Schema,
    droppedRecords: wireU64Schema.nullable(),
    droppedBytes: wireU64Schema.nullable(),
  })
  .strict();
export type CoverageGap = z.infer<typeof coverageGapSchema>;

export const captureBatchSchema = z
  .object({
    contract: z.literal(BATCH_SCHEMA),
    schemaVersion: z.literal(1),
    batchId: z.string().uuid(),
    batchDigest: sha256IdSchema,
    producer: z
      .object({
        adapter: z.literal("pump-companion"),
        adapterVersion: z.string().min(1).max(64),
        installationId: z.string().uuid(),
        extensionSessionId: z.string().uuid(),
      })
      .strict(),
    acquisitions: z.array(acquisitionEnvelopeSchema).max(25),
    gaps: z.array(coverageGapSchema).max(25),
  })
  .strict();
export type CaptureBatch = z.infer<typeof captureBatchSchema>;

export const durableReceiptSchema = z
  .object({
    contract: z.literal(RECEIPT_SCHEMA),
    schemaVersion: z.literal(1),
    catalogId: z.string().min(1).max(256),
    catalogSchema: z.string().min(1).max(256),
    ingressBatchId: z.string().uuid(),
    ingressBatchDigest: sha256IdSchema,
    status: z.enum(["accepted", "idempotent"]),
    fromCommitSeq: wireU64Schema,
    throughCommitSeq: wireU64Schema,
    durableBatchId: z.string().min(1).max(256),
    durableBatchDigest: sha256IdSchema,
    storeAdmissionDigest: sha256IdSchema,
    acquisitionCount: wireU64Schema,
    gapCount: wireU64Schema,
    committedAcquisitionIds: z.array(z.string().uuid()).max(100),
    committedGapIds: z.array(z.string().uuid()).max(100),
  })
  .strict();
export type DurableReceipt = z.infer<typeof durableReceiptSchema>;

export type SinkHealth = "paused" | "idle" | "healthy" | "backpressure" | "error";

export interface CompanionState {
  config: CaptureConfig;
  health: SinkHealth;
  queueDepth: number;
  queueBytes: number;
  gapDepth: number;
  accepted: number;
  delivered: number;
  dropped: number;
  rejectedMessages: number;
  lastCaptureAt: string | null;
  lastDeliveryAt: string | null;
  lastError: string | null;
}

export const runtimeRequestSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("get-config") }),
  z.object({ kind: z.literal("get-state") }),
  z.object({ kind: z.literal("set-capture-enabled"), enabled: z.boolean() }),
  z.object({ kind: z.literal("set-raw-capture-enabled"), enabled: z.boolean() }),
  z.object({
    kind: z.literal("set-origin-enabled"),
    originId: originIdSchema,
    enabled: z.boolean(),
  }),
  z.object({ kind: z.literal("ingest-page-observation"), observation: z.unknown() }),
  z.object({ kind: z.literal("flush-now") }),
]);
export type RuntimeRequest = z.infer<typeof runtimeRequestSchema>;

export type RuntimeResponse =
  | { ok: true; config?: CaptureConfig; state?: CompanionState }
  | { ok: false; error: string };
