import { validate as validateNoDuplicateJson } from "json-dup-key-validator";
import { isSafeNumber, parse as parseLossless } from "lossless-json";
import { BATCH_SCHEMA, LOOPBACK_SINK } from "./constants";
import {
  type AcquisitionEnvelope,
  type CaptureBatch,
  type CoverageGap,
  captureBatchSchema,
  type DurableReceipt,
  durableReceiptSchema,
} from "./contracts";
import { sha256Utf8 } from "./hash";

export interface QueuedAcquisition {
  approxBytes: number;
  envelope: AcquisitionEnvelope;
}
export interface QueuedGap {
  approxBytes: number;
  gap: CoverageGap;
}

export type SinkBatch = CaptureBatch;

export interface CatalogBinding {
  catalogId: string;
  catalogSchema: "joshi.sqlite.v5";
}

export interface SinkResult {
  ok: boolean;
  retryAfterMs: number | null;
  error: string | null;
  receipt: DurableReceipt | null;
}

export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

function parseRetryAfter(value: string | null, now: number): number | null {
  if (value === null) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1_000;
  const date = Date.parse(value);
  return Number.isNaN(date) ? null : Math.max(0, date - now);
}

function idsEqual(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function sortedDistinct(values: readonly string[]): string[] {
  return [...new Set(values)].sort();
}

function rejectDangerousStructure(value: unknown): void {
  if (Array.isArray(value)) {
    for (const item of value) rejectDangerousStructure(item);
    return;
  }
  if (value === null || typeof value !== "object") return;
  if (Object.getPrototypeOf(value) !== Object.prototype) {
    throw new Error("receipt contains a nonstandard object prototype");
  }
  for (const [key, child] of Object.entries(value)) {
    if (key === "__proto__" || key === "prototype" || key === "constructor") {
      throw new Error("receipt contains a dangerous object key");
    }
    rejectDangerousStructure(child);
  }
}

function parseReceipt(text: string): unknown {
  const duplicateError = validateNoDuplicateJson(text, false);
  if (duplicateError !== undefined) throw new SyntaxError(duplicateError);
  const value = parseLossless(text, null, {
    parseNumber: (lexeme) => {
      if (!isSafeNumber(lexeme, { approx: false })) {
        throw new SyntaxError("receipt contains an unsafe JSON numeric token");
      }
      return Number(lexeme);
    },
    onDuplicateKey: ({ key }) => {
      throw new SyntaxError(`receipt contains duplicate key: ${key}`);
    },
  });
  rejectDangerousStructure(value);
  return value;
}

export async function buildSinkBatch(
  acquisitions: readonly AcquisitionEnvelope[],
  gaps: readonly CoverageGap[],
  producer: SinkBatch["producer"],
  batchId = crypto.randomUUID(),
): Promise<SinkBatch> {
  const material = {
    contract: BATCH_SCHEMA,
    schemaVersion: 1 as const,
    batchId,
    producer,
    acquisitions: [...acquisitions],
    gaps: [...gaps],
  };
  return captureBatchSchema.parse({
    ...material,
    batchDigest: await sha256Utf8(JSON.stringify(material)),
  });
}

function validateReceipt(
  receipt: DurableReceipt,
  batch: SinkBatch,
  binding: CatalogBinding,
): string | null {
  if (receipt.catalogId !== binding.catalogId || receipt.catalogSchema !== binding.catalogSchema) {
    return "receipt catalog binding mismatch";
  }
  if (receipt.ingressBatchId !== batch.batchId) return "receipt ingress batch ID mismatch";
  if (receipt.ingressBatchDigest !== batch.batchDigest) {
    return "receipt ingress batch digest mismatch";
  }
  if (receipt.fromCommitSeq !== receipt.throughCommitSeq) return "receipt V1 commit range mismatch";
  const acquisitionIds = sortedDistinct(batch.acquisitions.map((item) => item.acquisitionId));
  const gapIds = sortedDistinct(batch.gaps.map((item) => item.gapId));
  if (receipt.acquisitionCount !== String(acquisitionIds.length)) {
    return "receipt acquisition count mismatch";
  }
  if (receipt.gapCount !== String(gapIds.length)) return "receipt gap count mismatch";
  if (!idsEqual(receipt.committedAcquisitionIds, acquisitionIds)) {
    return "receipt acquisition IDs mismatch";
  }
  if (!idsEqual(receipt.committedGapIds, gapIds)) return "receipt gap IDs mismatch";
  return null;
}

export class LoopbackSink {
  constructor(
    readonly fetcher: FetchLike,
    readonly binding: CatalogBinding | null,
    readonly url: typeof LOOPBACK_SINK = LOOPBACK_SINK,
  ) {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1" || parsed.port !== "43119") {
      throw new Error("loopback sink must remain on the pinned 127.0.0.1:43119 boundary");
    }
  }

  async send(batch: SinkBatch, now = new Date()): Promise<SinkResult> {
    if (this.binding === null) {
      return {
        ok: false,
        retryAfterMs: null,
        error: "loopback catalog is not locally paired; refusing ambiguous acknowledgement",
        receipt: null,
      };
    }
    try {
      const response = await this.fetcher(this.url, {
        method: "POST",
        body: JSON.stringify(batch),
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        referrerPolicy: "no-referrer",
        signal: AbortSignal.timeout(2_000),
        headers: {
          "Content-Type": "application/json",
          "X-Joshi-Companion-Schema": BATCH_SCHEMA,
          "X-Joshi-Batch-Digest": batch.batchDigest,
        },
      });
      if (!response.ok) {
        return {
          ok: false,
          retryAfterMs: parseRetryAfter(response.headers.get("Retry-After"), now.getTime()),
          error: `loopback sink returned HTTP ${response.status}`,
          receipt: null,
        };
      }
      const declared = Number(response.headers.get("Content-Length"));
      if (Number.isFinite(declared) && declared > 64 * 1024) {
        return { ok: false, retryAfterMs: null, error: "receipt body is too large", receipt: null };
      }
      const text = await response.text();
      if (new TextEncoder().encode(text).byteLength > 64 * 1024) {
        return { ok: false, retryAfterMs: null, error: "receipt body is too large", receipt: null };
      }
      let value: unknown;
      try {
        value = parseReceipt(text);
      } catch {
        return {
          ok: false,
          retryAfterMs: null,
          error: "2xx response lacks a JSON receipt",
          receipt: null,
        };
      }
      const parsed = durableReceiptSchema.safeParse(value);
      if (!parsed.success) {
        return {
          ok: false,
          retryAfterMs: null,
          error: "2xx response has an invalid receipt",
          receipt: null,
        };
      }
      const receiptError = validateReceipt(parsed.data, batch, this.binding);
      if (receiptError !== null) {
        return { ok: false, retryAfterMs: null, error: receiptError, receipt: null };
      }
      return { ok: true, retryAfterMs: null, error: null, receipt: parsed.data };
    } catch (error) {
      return {
        ok: false,
        retryAfterMs: null,
        error: error instanceof Error ? error.message : "loopback sink request failed",
        receipt: null,
      };
    }
  }
}
