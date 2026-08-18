import { parse as parseLossless } from "lossless-json";

import { ACQUISITION_SCHEMA, GAP_SCHEMA, SOURCE_CLOCK_CONTRACT } from "./constants";
import type {
  AcquisitionEnvelope,
  CaptureConfig,
  CoverageGap,
  FieldValue,
  NormalizedRecord,
  PageGapObservation,
  PageResponseAcquisition,
} from "./contracts";
import { base64ToBytes, sha256Id } from "./hash";
import { normalizedFieldAllowlist, normalizeResponse } from "./normalize";
import { matchCaptureRoute } from "./policy";

export interface AcquisitionFactoryOptions {
  allowRaw: boolean;
  receivedAt?: Date;
}

const ALLOWED_FIELDS = new Set<string>(normalizedFieldAllowlist);
const BEARER_VALUE = /\bBearer\s+[A-Za-z0-9._~+/-]{12,}={0,2}\b/gi;
const JWT_VALUE = /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g;

function scrubString(value: string, key: string): string {
  let scrubbed = value
    .replace(BEARER_VALUE, "[REDACTED_BEARER]")
    .replace(JWT_VALUE, "[REDACTED_JWT]");
  if ((key.endsWith("_uri") || key.endsWith("Url")) && scrubbed.startsWith("http")) {
    try {
      const url = new URL(scrubbed);
      scrubbed = `${url.origin}${url.pathname}`;
    } catch {
      return "[INVALID_URL]";
    }
  }
  return scrubbed;
}

function scrubFieldValue(value: FieldValue, key: string): FieldValue {
  if (value.encoding === "utf8") {
    return { ...value, value: scrubString(value.value, key) };
  }
  if (value.encoding === "utf8-list") {
    return { ...value, value: value.value.map((item) => scrubString(item, key)) };
  }
  return value;
}

function boundaryRecord(record: NormalizedRecord): NormalizedRecord {
  const fields: Record<string, FieldValue> = {};
  for (const [key, value] of Object.entries(record.fields)) {
    if (ALLOWED_FIELDS.has(key)) fields[key] = scrubFieldValue(value, key);
  }
  return { ...record, fields };
}

export async function acquisitionFromPageResponse(
  observation: PageResponseAcquisition,
  config: CaptureConfig,
  options: AcquisitionFactoryOptions,
): Promise<AcquisitionEnvelope | null> {
  const route = matchCaptureRoute(`${observation.sourceOrigin}${observation.sourcePath}`, config);
  if (route === null || route.id !== observation.routeId || !config.captureEnabled) return null;

  const bytes = base64ToBytes(observation.bodyBase64);
  if (String(bytes.byteLength) !== observation.responseBytes) {
    throw new Error("response byte count does not match captured bytes");
  }
  const responseBlobId = await sha256Id(bytes);
  if (responseBlobId !== observation.responseBlobId) {
    throw new Error("response blob hash does not match captured bytes");
  }

  let parsed: unknown;
  let parseDisposition: AcquisitionEnvelope["parseDisposition"] = "parsed";
  let sourceRecordCount = 0;
  let omittedRecordCount = 0;
  let records: NormalizedRecord[] = [];
  try {
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    parsed = parseLossless(text);
    const normalized = normalizeResponse(route, observation.sourcePath, parsed);
    records = normalized.records.map(boundaryRecord);
    sourceRecordCount = normalized.sourceRecordCount;
    omittedRecordCount = normalized.omittedRecordCount;
    if (records.length === 0) parseDisposition = "no-projectable-records";
  } catch {
    parsed = undefined;
    parseDisposition = "invalid-json";
  }

  const envelope: AcquisitionEnvelope = {
    schema: ACQUISITION_SCHEMA,
    acquisitionId: observation.acquisitionId,
    sourceId: "pump-companion",
    acquisitionKind: "http-response",
    transportKind: "browser-fetch",
    trust: "page-delivered-untrusted",
    contractVersion: "pump-companion-admission.v1",
    routeId: observation.routeId,
    sourceOrigin: observation.sourceOrigin,
    sourcePath: observation.sourcePath,
    pagePath: observation.pagePath,
    pageInstanceId: observation.pageInstanceId,
    capturedAt: observation.capturedAt,
    receivedAt: (options.receivedAt ?? new Date()).toISOString(),
    sourceClockContract: SOURCE_CLOCK_CONTRACT,
    sequence: observation.sequence,
    requestFingerprint: observation.requestFingerprint,
    requestFingerprintContract: observation.requestFingerprintContract,
    requestProjectionCompleteness: observation.requestProjectionCompleteness,
    responseBlobId,
    responseBytes: observation.responseBytes,
    responseBoundary: observation.responseBoundary,
    mediaType: observation.mediaType,
    parseDisposition,
    sourceRecordCount: String(sourceRecordCount),
    emittedRecordCount: String(records.length),
    omittedRecordCount: String(omittedRecordCount),
    records,
    fidelity: "lossy-normalized-attestation",
    evidenceDisposition: "not-admissible-as-exact-observation",
    fidelityGap: {
      reason: "exact-source-bytes-withheld-by-user-setting",
      effect: "normalized assertions cannot be independently verified by the store",
    },
  };
  if (options.allowRaw && config.rawCaptureEnabled) {
    envelope.fidelity = "exact-private-response-bytes";
    envelope.evidenceDisposition = "candidate-exact-private-observation";
    envelope.fidelityGap = undefined;
    envelope.exactPayload = {
      bodyBase64: observation.bodyBase64,
      blobId: responseBlobId,
      bytes: observation.responseBytes,
      boundary: observation.responseBoundary,
      protectionClass: "authenticated-private-source-evidence",
      retentionClass: "local-explicit-raw-opt-in",
      transferEncoding: "base64",
    };
  }
  return envelope;
}

interface GapOptions {
  reason: CoverageGap["reason"];
  lastAcceptedSequence: string | null;
  detectedAt?: Date;
  responseBlobId?: string | null;
  droppedRecords?: string | null;
  droppedBytes?: string | null;
}

type GapSource = PageResponseAcquisition | PageGapObservation | AcquisitionEnvelope;

export function scopedGapFrom(source: GapSource, options: GapOptions): CoverageGap {
  return {
    schema: GAP_SCHEMA,
    gapId: crypto.randomUUID(),
    sourceId: "pump-companion",
    routeId: source.routeId,
    sourceOrigin: source.sourceOrigin,
    sourcePath: source.sourcePath,
    pagePath: source.pagePath,
    pageInstanceId: source.pageInstanceId,
    acquisitionId: source.acquisitionId,
    requestFingerprint: source.requestFingerprint,
    responseBlobId:
      options.responseBlobId === undefined
        ? "responseBlobId" in source
          ? source.responseBlobId
          : null
        : (options.responseBlobId as CoverageGap["responseBlobId"]),
    reason: options.reason,
    sequenceStart: source.sequence,
    sequenceEnd: source.sequence,
    lastAcceptedSequence: options.lastAcceptedSequence,
    firstResumedSequence: null,
    capturedAtStart: source.capturedAt,
    capturedAtEnd: source.capturedAt,
    detectedAt: (options.detectedAt ?? new Date()).toISOString(),
    sourceClockContract: SOURCE_CLOCK_CONTRACT,
    droppedAcquisitions: "1",
    droppedRecords: options.droppedRecords ?? null,
    droppedBytes: options.droppedBytes ?? null,
  };
}

export function approximateEnvelopeBytes(envelope: AcquisitionEnvelope | CoverageGap): number {
  return new TextEncoder().encode(JSON.stringify(envelope)).byteLength;
}
