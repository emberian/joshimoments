import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { GlassSnapshotV1 } from "../contract/v1";
import {
  exactUtcNow,
  digestOperatorCommand,
  operatorCommandSchema,
  type CommandReceipt,
  type OperatorCommand,
  type OperatorCommandKind,
} from "./contract";
import { RetryableCommandError, type OperatorCommandSink } from "./client";
import {
  commandFromPending,
  IndexedDbPendingOperatorCommandQueue,
  MemoryPendingOperatorCommandQueue,
  pendingOperatorCommand,
  type PendingOperatorCommandQueue,
} from "./pendingQueue";

export type OperatorIntent = {
  commandKind: OperatorCommandKind;
  subject: { kind: string; key: string };
  payload: unknown;
  label: string;
};

export type JournalStatus = "retaining_local" | "submitting" | "queued" | "committed" | "rejected";

export type JournalEntry = {
  command: OperatorCommand;
  label: string;
  status: JournalStatus;
  receipt: CommandReceipt | null;
  error: string | null;
  pendingEnqueuedAt: string;
  pendingRepairRequiredAt: string;
};

export type PresentationCompleteBinding = {
  presentation: { presentationId: string; presentationDigest: string; assignmentId: string };
  cockpitPublication: { cockpitPublicationId: string; cockpitPublicationDigest: string };
};

let fixtureSessionCounter = 0;

function opaqueId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.().replaceAll("-", "");
  if (random) return `${prefix}-${random}`;
  fixtureSessionCounter += 1;
  return `${prefix}-fixture-${fixtureSessionCounter}`;
}

export function monotonicNanoseconds(nowMilliseconds: number = performance.now()): string {
  if (!Number.isFinite(nowMilliseconds) || nowMilliseconds < 0) {
    throw new Error("browser monotonic clock must be a finite non-negative millisecond value");
  }
  const sampledMicroseconds = Math.floor(nowMilliseconds * 1_000);
  if (!Number.isSafeInteger(sampledMicroseconds)) {
    throw new Error("browser monotonic clock exceeds exact microsecond sampling range");
  }
  return (BigInt(sampledMicroseconds) * 1_000n).toString();
}

function buildCommand(
  intent: OperatorIntent,
  snapshot: GlassSnapshotV1,
  clientSessionId: string,
  clockId: string,
  sequence: bigint,
  binding: PresentationCompleteBinding | null,
): OperatorCommand {
  return operatorCommandSchema.parse({
    contract: "joshi.operator.command",
    schemaVersion: binding ? 2 : 1,
    commandId: opaqueId("command"),
    idempotencyKey: opaqueId("retry"),
    clientSessionId,
    clientCommandSeq: sequence.toString(),
    scene: {
      sceneId: snapshot.view.sceneId,
      viewDigest: snapshot.snapshotDigest,
    },
    issuedAt: exactUtcNow(),
    clientClock: {
      clockId,
      monotonicNs: monotonicNanoseconds(),
    },
    ...(binding ?? {}),
    commandKind: intent.commandKind,
    subject: intent.subject,
    payload: intent.payload,
    authorityClass: "evidence_only",
    effectCeiling: "observe_only",
  });
}

export function useOperatorJournal(
  sink: OperatorCommandSink,
  snapshot: GlassSnapshotV1 | null,
  binding: PresentationCompleteBinding | null = null,
  requirePresentationComplete = false,
  pendingQueue?: PendingOperatorCommandQueue,
) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const entriesRef = useRef(entries);
  const activeAttempts = useRef(new Set<string>());
  const sequence = useRef(0n);
  const clientSessionId = useRef(opaqueId("glass-session")).current;
  const clockId = useRef(opaqueId("browser-clock")).current;
  const queue = useRef(pendingQueue ?? (sink.kind === "loopback"
    ? new IndexedDbPendingOperatorCommandQueue()
    : new MemoryPendingOperatorCommandQueue())).current;
  const [pendingReadbackError, setPendingReadbackError] = useState<string | null>(null);

  useEffect(() => { entriesRef.current = entries; }, [entries]);

  const attempt = useCallback(async (entry: JournalEntry) => {
    const commandId = entry.command.commandId;
    if (activeAttempts.current.has(commandId)) return;
    activeAttempts.current.add(commandId);
    setEntries((current) => current.map((item) => item.command.commandId === commandId
      ? { ...item, status: "submitting", error: null }
      : item));
    try {
      const receipt = await sink.appendCommand(entry.command);
      let cleanupError: string | null = null;
      try {
        await queue.acknowledge(entry.command.commandId, digestOperatorCommand(entry.command));
      } catch (error) {
        cleanupError = error instanceof Error ? error.message : "Pending command cache cleanup failed after ACK.";
      }
      setEntries((current) => current.map((item) => item.command.commandId === commandId
        ? { ...item, status: "committed", receipt, error: cleanupError }
        : item));
    } catch (error) {
      const retryable = error instanceof RetryableCommandError;
      setEntries((current) => current.map((item) => item.command.commandId === commandId
        ? {
            ...item,
            status: retryable ? "queued" : "rejected",
            error: error instanceof Error ? error.message : "Unknown command append failure",
          }
        : item));
    } finally {
      activeAttempts.current.delete(commandId);
    }
  }, [queue, sink]);

  useEffect(() => {
    let active = true;
    void queue.list().then((pending) => {
      if (!active) return;
      setEntries((current) => {
        const known = new Set(current.map((entry) => entry.command.commandId));
        const recovered = pending
          .filter((entry) => !known.has(entry.commandId))
          .map((entry): JournalEntry => {
            const command = commandFromPending(entry);
            const payload = command.payload as { context?: { uiLabel?: string } };
            return {
              command,
              label: payload.context?.uiLabel ?? command.commandKind,
              status: "queued",
              receipt: null,
              error: command.clientSessionId === clientSessionId
                ? "Recovered exact pending bytes; retry is available."
                : "Recovered from an earlier browser session; retained locally and available for explicit exact-byte recovery after pairing.",
              pendingEnqueuedAt: entry.enqueuedAt,
              pendingRepairRequiredAt: entry.expiresAt,
            };
          });
        return recovered.length === 0 ? current : [...recovered, ...current];
      });
    }).catch((error: unknown) => {
      if (active) setPendingReadbackError(error instanceof Error ? error.message : "Pending operator-command readback failed.");
    });
    return () => { active = false; };
  }, [clientSessionId, queue]);

  const record = useCallback((intent: OperatorIntent) => {
    if (!snapshot) throw new Error("cannot record an operator command before a verified scene loads");
    if (requirePresentationComplete && !binding) throw new Error("cannot record before the presentation and cockpit publication are durably bound");
    sequence.current += 1n;
    const command = buildCommand(intent, snapshot, clientSessionId, clockId, sequence.current, binding);
    const pending = pendingOperatorCommand(command);
    const entry: JournalEntry = {
      command,
      label: intent.label,
      status: "retaining_local",
      receipt: null,
      error: null,
      pendingEnqueuedAt: pending.enqueuedAt,
      pendingRepairRequiredAt: pending.expiresAt,
    };
    setEntries((current) => [...current, entry]);
    void queue.append(pending).then(() => attempt(entry)).catch((error: unknown) => {
      setEntries((current) => current.map((item) => item.command.commandId === command.commandId
        ? {
            ...item,
            status: "rejected",
            error: `Local pending retention failed; no server append was attempted: ${error instanceof Error ? error.message : "unknown retention failure"}`,
          }
        : item));
    });
    return command.commandId;
  }, [attempt, binding, clientSessionId, clockId, queue, requirePresentationComplete, snapshot]);

  const retry = useCallback((commandId: string) => {
    const entry = entriesRef.current.find((item) => item.command.commandId === commandId);
    if (!entry || (entry.status !== "queued" && entry.status !== "rejected")) return;
    // A freshly paired core may recover an earlier browser session by receiving these exact
    // canonical bytes. The command/session identity is never rewritten or rebound.
    void attempt(entry);
  }, [attempt]);

  useEffect(() => {
    const onOnline = () => {
      for (const entry of entriesRef.current) {
        if (entry.status === "queued" && entry.command.clientSessionId === clientSessionId) void attempt(entry);
      }
    };
    window.addEventListener("online", onOnline);
    return () => window.removeEventListener("online", onOnline);
  }, [attempt, clientSessionId]);

  const compensate = useCallback((entry: JournalEntry, reason: string, context: unknown) => {
    if (entry.status !== "committed" || entry.command.commandKind === "compensate_command") return;
    record({
      commandKind: "compensate_command",
      subject: entry.command.subject,
      label: `Undo ${entry.label}`,
      payload: {
        context,
        compensatesCommandId: entry.command.commandId,
        reason,
      },
    });
  }, [record]);

  const sceneEntries = useMemo(
    () => snapshot ? entries.filter((entry) => entry.command.scene.sceneId === snapshot.view.sceneId) : [],
    [entries, snapshot],
  );
  const compensatedIds = useMemo(() => new Set(sceneEntries
    .filter((entry) => entry.status === "committed" && entry.command.commandKind === "compensate_command")
    .map((entry) => entry.command.payload)
    .filter((payload): payload is Extract<OperatorCommand, { commandKind: "compensate_command" }>["payload"] => "compensatesCommandId" in payload)
    .map((payload) => payload.compensatesCommandId)), [sceneEntries]);

  return {
    clientSessionId,
    entries,
    sceneEntries,
    compensatedIds,
    pendingReadbackError,
    record,
    retry,
    compensate,
  };
}
