import { useCallback, useEffect, useRef, useState } from "react";

import type { GlassSnapshotV1 } from "../contract/v1";
import { exactUtcNow } from "../operator/contract";
import { monotonicNanoseconds } from "../operator/useOperatorJournal";
import {
  presentationEventV1Schema,
  type ExplorationBundleV1,
  type PresentationEventReceiptV1,
  type PresentationEventV1,
  type PresentationPolicyV1,
  type PresentationSceneReceiptV1,
  type PresentationSceneV1,
} from "./contract";
import { PresentationUnavailableError, type PresentationSink } from "./client";
import { buildPresentationScene } from "./manifest";

export type PresentationEventIntent = PresentationEventV1 extends infer Event
  ? Event extends PresentationEventV1
    ? Pick<Event, "eventKind" | "subject" | "payload">
    : never
  : never;

type PresentationStatus = "idle" | "staging" | "witnessed" | "gap";

let fixtureIdentity = 0;

function opaqueId(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.().replaceAll("-", "");
  if (random) return `${prefix}-${random}`;
  fixtureIdentity += 1;
  return `${prefix}-fixture-${fixtureIdentity}`;
}

export function usePresentationWitness(
  sink: PresentationSink,
  snapshot: GlassSnapshotV1 | null,
  bundle: ExplorationBundleV1 | null,
  policy: PresentationPolicyV1,
  reservedIdentity: { presentationId: string; assignmentId: string } | null = null,
) {
  const [status, setStatus] = useState<PresentationStatus>("idle");
  const [scene, setScene] = useState<PresentationSceneV1 | null>(null);
  const [receipt, setReceipt] = useState<PresentationSceneReceiptV1 | null>(null);
  const [error, setError] = useState<string | null>(null);
  /**
   * True when the gap exists because the paired core mounts no presentation-witness route at
   * all — a structural absence of the instrument, to be stated quietly — as opposed to a real
   * append failure over a mounted route, which stays an alert.
   */
  const [unavailable, setUnavailable] = useState(false);
  const [eventReceipts, setEventReceipts] = useState<PresentationEventReceiptV1[]>([]);
  const [eventGap, setEventGap] = useState<string | null>(null);
  const sceneSequence = useRef(0n);
  const eventSequence = useRef(0n);
  const eventTail = useRef<Promise<void>>(Promise.resolve());
  const eventBlocked = useRef(false);
  const clientSessionId = useRef(opaqueId("presentation-session")).current;
  const clockId = useRef(opaqueId("presentation-clock")).current;

  useEffect(() => {
    if (!snapshot || !bundle) {
      setStatus("idle");
      setScene(null);
      setReceipt(null);
      return;
    }
    const controller = new AbortController();
    sceneSequence.current += 1n;
    eventSequence.current = 0n;
    eventTail.current = Promise.resolve();
    eventBlocked.current = false;
    const nextScene = buildPresentationScene(snapshot, bundle, policy, {
      presentationId: reservedIdentity?.presentationId ?? opaqueId("presentation"),
      idempotencyKey: opaqueId("presentation-retry"),
      assignmentId: reservedIdentity?.assignmentId ?? opaqueId("presentation-assignment"),
      clientSessionId,
      presentationSeq: sceneSequence.current.toString(),
      capturedAt: exactUtcNow(),
      clockId,
      monotonicNs: monotonicNanoseconds(),
    });
    setScene(nextScene);
    setReceipt(null);
    setEventReceipts([]);
    setError(null);
    setEventGap(null);
    setUnavailable(false);
    setStatus("staging");
    sink.appendScene(nextScene, policy, bundle, controller.signal)
      .then((nextReceipt) => {
        if (!controller.signal.aborted) {
          setReceipt(nextReceipt);
          setStatus("witnessed");
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setUnavailable(cause instanceof PresentationUnavailableError);
          setError(cause instanceof Error ? cause.message : "Unknown presentation-scene append failure");
          setStatus("gap");
        }
      });
    return () => controller.abort();
  }, [bundle, clientSessionId, clockId, policy, reservedIdentity?.assignmentId, reservedIdentity?.presentationId, sink, snapshot]);

  const admitPolicy = useCallback(async (nextPolicy: PresentationPolicyV1): Promise<boolean> => {
    if (!snapshot || !bundle || !scene || !receipt) {
      setEventGap("Cannot assign a presentation policy without an exact witnessed scene.");
      return false;
    }
    await eventTail.current;
    sceneSequence.current += 1n;
    const nextScene = buildPresentationScene(snapshot, bundle, nextPolicy, {
      presentationId: opaqueId("presentation"),
      idempotencyKey: opaqueId("presentation-retry"),
      assignmentId: opaqueId("presentation-assignment"),
      clientSessionId,
      presentationSeq: sceneSequence.current.toString(),
      capturedAt: exactUtcNow(),
      clockId,
      monotonicNs: monotonicNanoseconds(),
    });
    try {
      const nextReceipt = await sink.appendScene(nextScene, nextPolicy, bundle);
      eventSequence.current = 0n;
      eventTail.current = Promise.resolve();
      eventBlocked.current = false;
      setScene(nextScene);
      setReceipt(nextReceipt);
      setEventReceipts([]);
      setEventGap(null);
      setError(null);
      setStatus("witnessed");
      return true;
    } catch (cause) {
      setEventGap(cause instanceof Error ? cause.message : "Presentation policy assignment was not admitted.");
      return false;
    }
  }, [bundle, clientSessionId, clockId, receipt, scene, sink, snapshot]);

  const recordEvent = useCallback(async (intent: PresentationEventIntent): Promise<string | null> => {
    if (!scene || !receipt) {
      setEventGap("Presentation interaction occurred before the initial scene receipt.");
      return null;
    }
    eventSequence.current += 1n;
    const event = presentationEventV1Schema.parse({
      contract: "joshi.presentation.event",
      schemaVersion: 1,
      eventId: opaqueId("presentation-event"),
      idempotencyKey: opaqueId("presentation-event-retry"),
      clientSessionId,
      presentationEventSeq: eventSequence.current.toString(),
      presentation: {
        presentationId: scene.presentationId,
        presentationDigest: receipt.presentationDigest,
      },
      scene: scene.scene,
      subject: intent.subject,
      occurredAt: exactUtcNow(),
      clientClock: { clockId, monotonicNs: monotonicNanoseconds() },
      eventKind: intent.eventKind,
      payload: intent.payload,
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    let resolveResult!: (value: string | null) => void;
    const result = new Promise<string | null>((resolve) => { resolveResult = resolve; });
    const append = eventTail.current.then(async () => {
      if (eventBlocked.current) {
        resolveResult(null);
        return;
      }
      try {
        const eventReceipt = await sink.appendEvent(event);
        setEventReceipts((current) => [...current, eventReceipt]);
        resolveResult(event.eventId);
      } catch (cause) {
        eventBlocked.current = true;
        setEventGap(cause instanceof Error ? cause.message : "Unknown presentation-event append failure");
        resolveResult(null);
      }
    });
    eventTail.current = append.then(() => undefined, () => undefined);
    return result;
  }, [clientSessionId, clockId, receipt, scene, sink]);

  return {
    clientSessionId,
    status,
    scene,
    receipt,
    error,
    unavailable,
    eventReceipts,
    eventGap,
    recordEvent,
    admitPolicy,
  };
}
