import { validate as validateJsonWithoutDuplicateKeys } from "json-dup-key-validator";

import {
  assertAnyReceiptMatchesCommand,
  canonicalOperatorCommand,
  commandReceiptSchema,
  digestOperatorCommand,
  digestOperatorPayload,
  operatorCommandSchema,
  type CommandReceipt,
  type OperatorCommand,
} from "./contract";
import { glassPairingSession, PairingSessionRejectedError, type MemoryOnlyPairingSession } from "../security/pairing";

export const MAX_OPERATOR_COMMAND_BYTES = 64 * 1024;
export const MAX_OPERATOR_RECEIPT_BYTES = 64 * 1024;

export class RetryableCommandError extends Error {
  readonly retryable = true;
}

export interface OperatorCommandSink {
  readonly kind: "offline_fixture" | "loopback";
  appendCommand(command: OperatorCommand, signal?: AbortSignal): Promise<CommandReceipt>;
}

async function readBoundedUtf8(response: Response): Promise<string> {
  const declaredLength = response.headers.get("Content-Length");
  if (declaredLength !== null && Number(declaredLength) > MAX_OPERATOR_RECEIPT_BYTES) {
    throw new Error("operator receipt exceeds the browser response bound");
  }
  const reader = response.body?.getReader();
  if (!reader) {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > MAX_OPERATOR_RECEIPT_BYTES) throw new Error("operator receipt exceeds the browser response bound");
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  }

  const decoder = new TextDecoder("utf-8", { fatal: true });
  let body = "";
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_OPERATOR_RECEIPT_BYTES) {
      await reader.cancel("operator receipt response bound exceeded");
      throw new Error("operator receipt exceeds the browser response bound");
    }
    body += decoder.decode(value, { stream: true });
  }
  return body + decoder.decode();
}

function parseUntrustedReceipt(body: string): CommandReceipt {
  const wireError = validateJsonWithoutDuplicateKeys(body, false);
  if (wireError !== undefined) throw new Error(`invalid operator receipt JSON: ${wireError}`);
  const decoded = JSON.parse(body, (key, value: unknown) => {
    if (key === "__proto__" || key === "constructor" || key === "prototype") {
      throw new Error(`forbidden operator receipt JSON key: ${key}`);
    }
    return value;
  }) as unknown;
  return commandReceiptSchema.parse(decoded);
}

export class OfflineFixtureOperatorSink implements OperatorCommandSink {
  readonly kind = "offline_fixture" as const;
  readonly attemptBodies: string[] = [];
  private online = true;
  private nextCommit = 1_001n;
  private readonly byIdempotency = new Map<string, { commandDigest: string; receipt: CommandReceipt }>();
  private readonly byCommandId = new Map<string, string>();

  setOnline(online: boolean): void {
    this.online = online;
  }

  async appendCommand(commandInput: OperatorCommand, signal?: AbortSignal): Promise<CommandReceipt> {
    if (signal?.aborted) throw new DOMException("Command append aborted", "AbortError");
    const command = operatorCommandSchema.parse(commandInput);
    const body = canonicalOperatorCommand(command);
    this.attemptBodies.push(body);
    if (new TextEncoder().encode(body).byteLength > MAX_OPERATOR_COMMAND_BYTES) {
      throw new Error("operator command exceeds the browser request bound");
    }
    if (!this.online) throw new RetryableCommandError("offline fixture command sink is disconnected");

    const commandDigest = digestOperatorCommand(command);
    const existingIdempotency = this.byIdempotency.get(command.idempotencyKey);
    if (existingIdempotency) {
      if (existingIdempotency.commandDigest !== commandDigest) {
        throw new Error("operator command idempotency conflict: retry body changed");
      }
      const receipt = { ...existingIdempotency.receipt, status: "idempotent" as const };
      assertAnyReceiptMatchesCommand(receipt, command);
      return structuredClone(receipt);
    }
    const existingCommandDigest = this.byCommandId.get(command.commandId);
    if (existingCommandDigest && existingCommandDigest !== commandDigest) {
      throw new Error("operator command identity conflict: command body changed");
    }

    const receipt = commandReceiptSchema.parse({
      contract: "joshi.store.command_receipt",
      schemaVersion: command.schemaVersion,
      catalogId: "offline-fixture-catalog",
      catalogSchema: "joshi.catalog.v1",
      batchId: `batch:${command.commandId}`,
      commandId: command.commandId,
      commandPayloadDigest: digestOperatorPayload(command),
      commandDigest,
      scene: command.scene,
      ...(command.schemaVersion === 2 ? {
        presentation: command.presentation,
        cockpitPublication: command.cockpitPublication,
      } : {}),
      commitSeq: this.nextCommit.toString(),
      status: "accepted",
    });
    this.nextCommit += 1n;
    this.byIdempotency.set(command.idempotencyKey, { commandDigest, receipt });
    this.byCommandId.set(command.commandId, commandDigest);
    assertAnyReceiptMatchesCommand(receipt, command);
    return structuredClone(receipt);
  }
}

export class LoopbackOperatorSink implements OperatorCommandSink {
  readonly kind = "loopback" as const;
  private readonly baseUrl: URL;
  private readonly pairingSession: MemoryOnlyPairingSession;

  constructor(baseUrl: string, pairingSession: MemoryOnlyPairingSession = glassPairingSession, requireSameOrigin = false) {
    const parsed = new URL(baseUrl);
    const loopbackHosts = new Set(["127.0.0.1", "localhost", "[::1]"]);
    if (parsed.protocol !== "http:" || !loopbackHosts.has(parsed.hostname)) {
      throw new Error("operator core URL must be an explicit HTTP loopback address");
    }
    if (requireSameOrigin && parsed.origin !== window.location.origin) {
      throw new Error("operational operator transport must use the exact page origin");
    }
    this.baseUrl = parsed;
    this.pairingSession = pairingSession;
  }

  async appendCommand(commandInput: OperatorCommand, signal?: AbortSignal): Promise<CommandReceipt> {
    const command = operatorCommandSchema.parse(commandInput);
    const body = canonicalOperatorCommand(command);
    if (new TextEncoder().encode(body).byteLength > MAX_OPERATOR_COMMAND_BYTES) {
      throw new Error("operator command exceeds the browser request bound");
    }

    let response: Response;
    try {
      response = await fetch(new URL("/api/v1/operator/commands", this.baseUrl), {
        method: "POST",
        ...(signal ? { signal } : {}),
        credentials: "omit",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Joshi-Pairing-Token": this.pairingSession.authorizationHeader("operator_evidence_write"),
        },
        body,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new RetryableCommandError(error instanceof Error ? error.message : "operator command transport failed");
    }
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        this.pairingSession.clear();
        throw new PairingSessionRejectedError("Local session expired or was revoked; pair again.");
      }
      if (response.status === 408 || response.status === 425 || response.status === 429 || response.status >= 500) {
        throw new RetryableCommandError(`operator command append is retryable (${response.status})`);
      }
      throw new Error(`operator command append failed (${response.status})`);
    }

    const receipt = parseUntrustedReceipt(await readBoundedUtf8(response));
    assertAnyReceiptMatchesCommand(receipt, command);
    return receipt;
  }
}

export function configuredOperatorSink(): OperatorCommandSink {
  const loopbackUrl = import.meta.env.VITE_JOSHI_CORE_URL as string | undefined;
  return loopbackUrl ? new LoopbackOperatorSink(loopbackUrl) : new OfflineFixtureOperatorSink();
}
