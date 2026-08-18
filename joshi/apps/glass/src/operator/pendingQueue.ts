import { z } from "zod";

import { exactUtcInstantSchema } from "../contract/instant";
import {
  canonicalOperatorCommand,
  digestOperatorCommand,
  operatorCommandSchema,
  type OperatorCommand,
} from "./contract";
import { MAX_OPERATOR_COMMAND_BYTES } from "./client";

const asciiIdentity = z.string().min(1).max(512).regex(/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/);
const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const wireU64 = z.string().regex(/^(?:0|[1-9][0-9]*)$/);

export const MAX_PENDING_OPERATOR_COMMANDS = 512;
export const MAX_PENDING_OPERATOR_BYTES = 8 * 1024 * 1024;
// This is a repair threshold, not a deletion deadline. Exact unacknowledged bytes remain until
// same-ID/digest core ACK; crossing the threshold makes recovery visibly urgent.
export const MAX_PENDING_OPERATOR_AGE_MS = 7 * 24 * 60 * 60 * 1_000;

export const pendingOperatorCommandV1Schema = z.object({
  contract: z.literal("joshi.glass.pending_operator_command"),
  schemaVersion: z.literal(1),
  commandId: asciiIdentity,
  commandDigest: digest,
  canonicalCommand: z.string().min(1).max(MAX_OPERATOR_COMMAND_BYTES),
  byteLength: wireU64,
  enqueuedAt: exactUtcInstantSchema,
  expiresAt: exactUtcInstantSchema,
  privacyClass: z.literal("app_private"),
  transportState: z.literal("pending_store_ack"),
}).strict().superRefine((pending, refinement) => {
  let command: OperatorCommand;
  try {
    command = operatorCommandSchema.parse(JSON.parse(pending.canonicalCommand) as unknown);
  } catch (error) {
    refinement.addIssue({ code: "custom", message: error instanceof Error ? error.message : "invalid cached operator command", path: ["canonicalCommand"] });
    return;
  }
  if (canonicalOperatorCommand(command) !== pending.canonicalCommand) {
    refinement.addIssue({ code: "custom", message: "cached operator command is not exact canonical bytes", path: ["canonicalCommand"] });
  }
  if (command.commandId !== pending.commandId || digestOperatorCommand(command) !== pending.commandDigest) {
    refinement.addIssue({ code: "custom", message: "cached operator command identity or digest mismatch", path: ["commandDigest"] });
  }
  const actualBytes = new TextEncoder().encode(pending.canonicalCommand).byteLength;
  if (actualBytes > MAX_OPERATOR_COMMAND_BYTES) {
    refinement.addIssue({ code: "custom", message: "cached operator command exceeds the per-command byte limit", path: ["canonicalCommand"] });
  }
  if (BigInt(pending.byteLength) !== BigInt(actualBytes)) {
    refinement.addIssue({ code: "custom", message: "cached operator command byte length mismatch", path: ["byteLength"] });
  }
  const enqueued = Date.parse(pending.enqueuedAt);
  const expires = Date.parse(pending.expiresAt);
  if (!(expires > enqueued) || expires - enqueued > MAX_PENDING_OPERATOR_AGE_MS) {
    refinement.addIssue({ code: "custom", message: "cached operator command repair threshold exceeds the fixed local envelope", path: ["expiresAt"] });
  }
});

export type PendingOperatorCommandV1 = z.infer<typeof pendingOperatorCommandV1Schema>;

export function pendingOperatorCommand(commandInput: OperatorCommand, now = new Date()): PendingOperatorCommandV1 {
  const command = operatorCommandSchema.parse(commandInput);
  const canonicalCommand = canonicalOperatorCommand(command);
  const expires = new Date(now.getTime() + MAX_PENDING_OPERATOR_AGE_MS);
  return pendingOperatorCommandV1Schema.parse({
    contract: "joshi.glass.pending_operator_command",
    schemaVersion: 1,
    commandId: command.commandId,
    commandDigest: digestOperatorCommand(command),
    canonicalCommand,
    byteLength: new TextEncoder().encode(canonicalCommand).byteLength.toString(),
    enqueuedAt: now.toISOString().replace(/\.(\d{3})Z$/, ".$1000Z"),
    expiresAt: expires.toISOString().replace(/\.(\d{3})Z$/, ".$1000Z"),
    privacyClass: "app_private",
    transportState: "pending_store_ack",
  });
}

export function commandFromPending(pendingInput: PendingOperatorCommandV1): OperatorCommand {
  const pending = pendingOperatorCommandV1Schema.parse(pendingInput);
  return operatorCommandSchema.parse(JSON.parse(pending.canonicalCommand) as unknown);
}

export interface PendingOperatorCommandQueue {
  append(pending: PendingOperatorCommandV1): Promise<void>;
  list(): Promise<PendingOperatorCommandV1[]>;
  acknowledge(commandId: string, commandDigest: string): Promise<void>;
}

function assertCapacity(current: PendingOperatorCommandV1[], pending: PendingOperatorCommandV1): void {
  const existing = current.find((entry) => entry.commandId === pending.commandId);
  if (existing) {
    if (existing.commandDigest !== pending.commandDigest || existing.canonicalCommand !== pending.canonicalCommand) {
      throw new Error("changed bytes reused an existing pending operator-command ID");
    }
    return;
  }
  if (current.length >= MAX_PENDING_OPERATOR_COMMANDS) throw new Error("pending operator-command count limit reached");
  const bytes = current.reduce((total, entry) => total + Number(entry.byteLength), 0) + Number(pending.byteLength);
  if (!Number.isSafeInteger(bytes) || bytes > MAX_PENDING_OPERATOR_BYTES) throw new Error("pending operator-command byte limit reached");
}

export class MemoryPendingOperatorCommandQueue implements PendingOperatorCommandQueue {
  private readonly entries = new Map<string, PendingOperatorCommandV1>();

  async append(input: PendingOperatorCommandV1): Promise<void> {
    const pending = pendingOperatorCommandV1Schema.parse(input);
    const current = [...this.entries.values()];
    assertCapacity(current, pending);
    this.entries.set(pending.commandId, structuredClone(pending));
  }

  async list(): Promise<PendingOperatorCommandV1[]> {
    return [...this.entries.values()]
      .map((entry) => pendingOperatorCommandV1Schema.parse(structuredClone(entry)))
      .sort((left, right) => left.enqueuedAt < right.enqueuedAt ? -1 : left.enqueuedAt > right.enqueuedAt ? 1 : left.commandId < right.commandId ? -1 : left.commandId > right.commandId ? 1 : 0);
  }

  async acknowledge(commandId: string, commandDigest: string): Promise<void> {
    const existing = this.entries.get(commandId);
    if (!existing) return;
    if (existing.commandDigest !== commandDigest) throw new Error("store ACK digest does not match pending operator-command bytes");
    this.entries.delete(commandId);
  }
}

const DATABASE_NAME = "joshi-glass-pending-operator-commands-v1";
const STORE_NAME = "pending";

export class IndexedDbPendingOperatorCommandQueue implements PendingOperatorCommandQueue {
  private databasePromise: Promise<IDBDatabase> | null = null;

  async append(input: PendingOperatorCommandV1): Promise<void> {
    const pending = pendingOperatorCommandV1Schema.parse(input);
    const database = await this.database();
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite", { durability: "strict" });
      const store = transaction.objectStore(STORE_NAME);
      const request = store.getAll(undefined, MAX_PENDING_OPERATOR_COMMANDS + 1);
      let failed = false;
      request.onerror = () => { failed = true; reject(request.error ?? new Error("pending operator-command inventory read failed")); };
      request.onsuccess = () => {
        try {
          const current = request.result.map((entry) => pendingOperatorCommandV1Schema.parse(entry));
          if (current.length > MAX_PENDING_OPERATOR_COMMANDS) throw new Error("pending operator-command cache exceeds its count limit");
          assertCapacity(current, pending);
          const existing = current.find((entry) => entry.commandId === pending.commandId);
          if (!existing) store.add(pending);
        } catch (error) {
          failed = true;
          transaction.abort();
          reject(error);
        }
      };
      transaction.oncomplete = () => { if (!failed) resolve(); };
      transaction.onerror = () => { if (!failed) reject(transaction.error ?? new Error("pending operator-command retention failed")); };
      transaction.onabort = () => { if (!failed) reject(transaction.error ?? new Error("pending operator-command retention aborted")); };
    });
  }

  async list(): Promise<PendingOperatorCommandV1[]> {
    const database = await this.database();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readonly");
      const request = transaction.objectStore(STORE_NAME).getAll(undefined, MAX_PENDING_OPERATOR_COMMANDS + 1);
      request.onerror = () => reject(request.error ?? new Error("pending operator-command readback failed"));
      request.onsuccess = () => {
        try {
          if (request.result.length > MAX_PENDING_OPERATOR_COMMANDS) throw new Error("pending operator-command cache exceeds its count limit");
          resolve(request.result
            .map((entry) => pendingOperatorCommandV1Schema.parse(entry))
            .sort((left, right) => left.enqueuedAt < right.enqueuedAt ? -1 : left.enqueuedAt > right.enqueuedAt ? 1 : left.commandId < right.commandId ? -1 : left.commandId > right.commandId ? 1 : 0));
        } catch (error) {
          reject(error);
        }
      };
    });
  }

  async acknowledge(commandId: string, commandDigest: string): Promise<void> {
    const database = await this.database();
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite", { durability: "strict" });
      const store = transaction.objectStore(STORE_NAME);
      const request = store.get(commandId);
      request.onerror = () => reject(request.error ?? new Error("pending operator-command ACK lookup failed"));
      request.onsuccess = () => {
        if (request.result === undefined) return;
        try {
          const existing = pendingOperatorCommandV1Schema.parse(request.result);
          if (existing.commandDigest !== commandDigest) throw new Error("store ACK digest does not match pending operator-command bytes");
          store.delete(commandId);
        } catch (error) {
          transaction.abort();
          reject(error);
        }
      };
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error ?? new Error("pending operator-command ACK cleanup failed"));
    });
  }

  private database(): Promise<IDBDatabase> {
    if (this.databasePromise) return this.databasePromise;
    if (!globalThis.indexedDB) return Promise.reject(new Error("IndexedDB is unavailable; pending operator-command retention is unavailable"));
    this.databasePromise = new Promise((resolve, reject) => {
      const request = globalThis.indexedDB.open(DATABASE_NAME, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE_NAME)) request.result.createObjectStore(STORE_NAME, { keyPath: "commandId" });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error("pending operator-command database open failed"));
      request.onblocked = () => reject(new Error("pending operator-command database upgrade is blocked"));
    });
    return this.databasePromise;
  }
}
