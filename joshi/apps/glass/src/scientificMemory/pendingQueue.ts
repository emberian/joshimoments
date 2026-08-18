import { exactUtcInstantSchema } from "../contract/instant";
import {
  canonicalOperatorActBytes,
  digestOperatorActBytes,
  parseCanonicalOperatorActBytes,
  type OperatorActOccurrence,
} from "./contract";
import { z } from "zod";

const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const wireU64 = z.string().regex(/^(?:0|[1-9]\d*)$/);
const encoder = new TextEncoder();

export const MAX_PENDING_SCIENTIFIC_MEMORY_ACTS = 512;
export const MAX_PENDING_SCIENTIFIC_MEMORY_BYTES = 8 * 1024 * 1024;
export const MAX_PENDING_SCIENTIFIC_MEMORY_ACT_BYTES = 64 * 1024;

export const pendingScientificMemoryActV1Schema = z.object({
  contract: z.literal("joshi.glass.pending_scientific_memory_act"),
  schemaVersion: z.literal(1),
  actId: z.string().min(1).max(255),
  occurrenceDigest: digest,
  canonicalOccurrence: z.string().min(1).max(MAX_PENDING_SCIENTIFIC_MEMORY_ACT_BYTES),
  byteLength: wireU64,
  enqueuedAt: exactUtcInstantSchema,
  privacyClass: z.literal("app_private"),
  transportState: z.literal("pending_store_ack"),
}).strict().superRefine((pending, context) => {
  try {
    const bytes = encoder.encode(pending.canonicalOccurrence);
    const occurrence = parseCanonicalOperatorActBytes(bytes);
    if (occurrence.value.actId !== pending.actId) context.addIssue({ code: "custom", message: "act identity does not match canonical bytes", path: ["actId"] });
    if (digestOperatorActBytes(bytes) !== pending.occurrenceDigest) context.addIssue({ code: "custom", message: "act digest does not match canonical bytes", path: ["occurrenceDigest"] });
    if (BigInt(pending.byteLength) !== BigInt(bytes.byteLength)) context.addIssue({ code: "custom", message: "act byte length does not match canonical bytes", path: ["byteLength"] });
  } catch (error) {
    context.addIssue({ code: "custom", message: error instanceof Error ? error.message : "invalid cached act", path: ["canonicalOccurrence"] });
  }
});

export type PendingScientificMemoryActV1 = z.infer<typeof pendingScientificMemoryActV1Schema>;

function exactUtcNow(now = new Date()): string {
  return now.toISOString().replace(/\.(\d{3})Z$/, ".$1000Z");
}

export function pendingScientificMemoryAct(input: OperatorActOccurrence, now = new Date()): PendingScientificMemoryActV1 {
  const canonicalOccurrence = new TextDecoder().decode(canonicalOperatorActBytes(input));
  const bytes = encoder.encode(canonicalOccurrence);
  return pendingScientificMemoryActV1Schema.parse({
    contract: "joshi.glass.pending_scientific_memory_act",
    schemaVersion: 1,
    actId: input.value.actId,
    occurrenceDigest: digestOperatorActBytes(bytes),
    canonicalOccurrence,
    byteLength: bytes.byteLength.toString(),
    enqueuedAt: exactUtcNow(now),
    privacyClass: "app_private",
    transportState: "pending_store_ack",
  });
}

export interface PendingScientificMemoryActQueue {
  append(pending: PendingScientificMemoryActV1): Promise<void>;
  list(): Promise<PendingScientificMemoryActV1[]>;
  /** Only an exact private store ACK may remove a retained act. */
  acknowledge(actId: string, occurrenceDigest: string): Promise<void>;
}

function assertCapacity(current: PendingScientificMemoryActV1[], pending: PendingScientificMemoryActV1): void {
  const existing = current.find((entry) => entry.actId === pending.actId);
  if (existing) {
    if (existing.occurrenceDigest !== pending.occurrenceDigest || existing.canonicalOccurrence !== pending.canonicalOccurrence) {
      throw new Error("changed bytes reused an existing scientific-memory act ID");
    }
    return;
  }
  if (current.length >= MAX_PENDING_SCIENTIFIC_MEMORY_ACTS) throw new Error("pending scientific-memory act count limit reached");
  const bytes = current.reduce((total, entry) => total + Number(entry.byteLength), 0) + Number(pending.byteLength);
  if (!Number.isSafeInteger(bytes) || bytes > MAX_PENDING_SCIENTIFIC_MEMORY_BYTES) throw new Error("pending scientific-memory act byte limit reached");
}

export class MemoryPendingScientificMemoryActQueue implements PendingScientificMemoryActQueue {
  private readonly entries = new Map<string, PendingScientificMemoryActV1>();

  async append(input: PendingScientificMemoryActV1): Promise<void> {
    const pending = pendingScientificMemoryActV1Schema.parse(input);
    assertCapacity([...this.entries.values()], pending);
    this.entries.set(pending.actId, structuredClone(pending));
  }

  async list(): Promise<PendingScientificMemoryActV1[]> {
    return [...this.entries.values()].map((entry) => pendingScientificMemoryActV1Schema.parse(structuredClone(entry)))
      .sort((left, right) => left.enqueuedAt.localeCompare(right.enqueuedAt) || left.actId.localeCompare(right.actId));
  }

  async acknowledge(actId: string, occurrenceDigest: string): Promise<void> {
    const existing = this.entries.get(actId);
    if (!existing) return;
    if (existing.occurrenceDigest !== occurrenceDigest) throw new Error("store ACK digest does not match retained scientific-memory act bytes");
    this.entries.delete(actId);
  }
}

const DATABASE_NAME = "joshi-glass-pending-scientific-memory-acts-v1";
const STORE_NAME = "pending";

/**
 * Browser-local, strict-durability transport only.  It has no research-admission method and is
 * intentionally never a substitute for a store-owned act receipt.
 */
export class IndexedDbPendingScientificMemoryActQueue implements PendingScientificMemoryActQueue {
  private databasePromise: Promise<IDBDatabase> | null = null;

  async append(input: PendingScientificMemoryActV1): Promise<void> {
    const pending = pendingScientificMemoryActV1Schema.parse(input);
    const database = await this.database();
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite", { durability: "strict" });
      const store = transaction.objectStore(STORE_NAME);
      const request = store.getAll(undefined, MAX_PENDING_SCIENTIFIC_MEMORY_ACTS + 1);
      let failed = false;
      request.onerror = () => { failed = true; reject(request.error ?? new Error("scientific-memory pending inventory read failed")); };
      request.onsuccess = () => {
        try {
          const current = request.result.map((entry) => pendingScientificMemoryActV1Schema.parse(entry));
          if (current.length > MAX_PENDING_SCIENTIFIC_MEMORY_ACTS) throw new Error("pending scientific-memory act cache exceeds its count limit");
          assertCapacity(current, pending);
          if (!current.some((entry) => entry.actId === pending.actId)) store.add(pending);
        } catch (error) {
          failed = true;
          transaction.abort();
          reject(error);
        }
      };
      transaction.oncomplete = () => { if (!failed) resolve(); };
      transaction.onerror = () => { if (!failed) reject(transaction.error ?? new Error("scientific-memory pending retention failed")); };
      transaction.onabort = () => { if (!failed) reject(transaction.error ?? new Error("scientific-memory pending retention aborted")); };
    });
  }

  async list(): Promise<PendingScientificMemoryActV1[]> {
    const database = await this.database();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readonly");
      const request = transaction.objectStore(STORE_NAME).getAll(undefined, MAX_PENDING_SCIENTIFIC_MEMORY_ACTS + 1);
      request.onerror = () => reject(request.error ?? new Error("scientific-memory pending readback failed"));
      request.onsuccess = () => {
        try {
          if (request.result.length > MAX_PENDING_SCIENTIFIC_MEMORY_ACTS) throw new Error("pending scientific-memory act cache exceeds its count limit");
          resolve(request.result.map((entry) => pendingScientificMemoryActV1Schema.parse(entry))
            .sort((left, right) => left.enqueuedAt.localeCompare(right.enqueuedAt) || left.actId.localeCompare(right.actId)));
        } catch (error) {
          reject(error);
        }
      };
    });
  }

  async acknowledge(actId: string, occurrenceDigest: string): Promise<void> {
    const database = await this.database();
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite", { durability: "strict" });
      const store = transaction.objectStore(STORE_NAME);
      const request = store.get(actId);
      let failed = false;
      request.onerror = () => { failed = true; reject(request.error ?? new Error("scientific-memory ACK lookup failed")); };
      request.onsuccess = () => {
        if (request.result === undefined) return;
        try {
          const existing = pendingScientificMemoryActV1Schema.parse(request.result);
          if (existing.occurrenceDigest !== occurrenceDigest) throw new Error("store ACK digest does not match retained scientific-memory act bytes");
          store.delete(actId);
        } catch (error) {
          failed = true;
          transaction.abort();
          reject(error);
        }
      };
      transaction.oncomplete = () => { if (!failed) resolve(); };
      transaction.onerror = () => { if (!failed) reject(transaction.error ?? new Error("scientific-memory ACK cleanup failed")); };
      transaction.onabort = () => { if (!failed) reject(transaction.error ?? new Error("scientific-memory ACK cleanup aborted")); };
    });
  }

  private database(): Promise<IDBDatabase> {
    if (this.databasePromise) return this.databasePromise;
    if (!globalThis.indexedDB) return Promise.reject(new Error("IndexedDB is unavailable; scientific-memory pending retention is unavailable"));
    this.databasePromise = new Promise((resolve, reject) => {
      const request = globalThis.indexedDB.open(DATABASE_NAME, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME, { keyPath: "actId" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error("scientific-memory pending database open failed"));
      request.onblocked = () => reject(new Error("scientific-memory pending database upgrade is blocked"));
    });
    return this.databasePromise;
  }
}
