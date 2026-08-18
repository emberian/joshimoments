import { afterEach, describe, expect, it, vi } from "vitest";

import { mockSnapshots } from "../data/mockSnapshot";
import { digestPresentationScene, presentationEventV1Schema } from "./contract";
import { OfflineFixturePresentationSink } from "./client";
import { LoopbackPresentationSink } from "./client";
import { buildPresentationScene, defaultPresentationPolicy, explorationBundleFor } from "./fixtures";
import { MemoryOnlyPairingSession } from "../security/pairing";

afterEach(() => vi.unstubAllGlobals());

function fixture() {
  const snapshot = mockSnapshots.witnessed;
  const bundle = explorationBundleFor(snapshot);
  const scene = buildPresentationScene(snapshot, bundle, defaultPresentationPolicy, {
    presentationId: "presentation-client-test",
    idempotencyKey: "presentation-client-retry",
    assignmentId: "manual-assignment-client-test",
    clientSessionId: "presentation-client-session",
    presentationSeq: "1",
    capturedAt: "2026-08-16T18:42:15.000000Z",
    clockId: "presentation-client-clock",
    monotonicNs: "1000000",
  });
  return { bundle, scene };
}

describe("presentation receipt boundary", () => {
  it("returns exact scene and event receipts only after fixture commit", async () => {
    const sink = new OfflineFixturePresentationSink();
    const { bundle, scene } = fixture();
    const sceneReceipt = await sink.appendScene(scene, defaultPresentationPolicy, bundle);
    expect(sceneReceipt.presentationDigest).toBe(digestPresentationScene(scene));
    expect(sceneReceipt.assignmentId).toBe(scene.policy.assignmentId);

    const event = presentationEventV1Schema.parse({
      contract: "joshi.presentation.event",
      schemaVersion: 1,
      eventId: "presentation-event-client-test",
      idempotencyKey: "presentation-event-client-retry",
      clientSessionId: scene.clientSessionId,
      presentationEventSeq: "1",
      presentation: { presentationId: scene.presentationId, presentationDigest: sceneReceipt.presentationDigest },
      scene: scene.scene,
      subject: { kind: "control", key: "evidence-inferred" },
      occurredAt: "2026-08-16T18:42:16.000000Z",
      clientClock: { clockId: "presentation-client-clock", monotonicNs: "2000000" },
      eventKind: "control_changed",
      payload: { controlKind: "toggle", controlId: "evidence-inferred", previousValue: "true", nextValue: "false" },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    const eventReceipt = await sink.appendEvent(event);
    expect(eventReceipt.presentation.presentationDigest).toBe(sceneReceipt.presentationDigest);
    expect(eventReceipt.commitSeq).toBe("8002");
  });

  it("is idempotent for exact retries and conflicts on changed same-ID bodies", async () => {
    const sink = new OfflineFixturePresentationSink();
    const { bundle, scene } = fixture();
    const accepted = await sink.appendScene(scene, defaultPresentationPolicy, bundle);
    const retried = await sink.appendScene(scene, defaultPresentationPolicy, bundle);
    expect(accepted.status).toBe("accepted");
    expect(retried.status).toBe("idempotent");
    expect(retried.commitSeq).toBe(accepted.commitSeq);
    expect(sink.sceneAttemptBodies[1]).toBe(sink.sceneAttemptBodies[0]);

    const changed = structuredClone(scene);
    changed.manifest.filters[0]!.value = "observed";
    await expect(sink.appendScene(changed, defaultPresentationPolicy, bundle)).rejects.toThrow(/idempotency conflict/i);
  });

  it("rejects an event before the exact presentation scene is committed", async () => {
    const sink = new OfflineFixturePresentationSink();
    const { scene } = fixture();
    const event = presentationEventV1Schema.parse({
      contract: "joshi.presentation.event",
      schemaVersion: 1,
      eventId: "orphan-event",
      idempotencyKey: "orphan-event-retry",
      clientSessionId: scene.clientSessionId,
      presentationEventSeq: "1",
      presentation: { presentationId: scene.presentationId, presentationDigest: digestPresentationScene(scene) },
      scene: scene.scene,
      subject: { kind: "panel", key: "hypothesis-lab" },
      occurredAt: "2026-08-16T18:42:16.000000Z",
      clientClock: { clockId: "presentation-client-clock", monotonicNs: "2000000" },
      eventKind: "visibility_started",
      payload: { reason: "initial_reveal" },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    await expect(sink.appendEvent(event)).rejects.toThrow(/uncommitted or mismatched/i);
  });

  it("posts a composite exact admission with memory-only pairing and fails unpaired before fetch", async () => {
    const { bundle, scene } = fixture();
    const fixtureSink = new OfflineFixturePresentationSink();
    const receipt = await fixtureSink.appendScene(scene, defaultPresentationPolicy, bundle);
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const pairing = new MemoryOnlyPairingSession();
    pairing.pair("c".repeat(64));
    await new LoopbackPresentationSink("http://127.0.0.1:8787", pairing).appendScene(scene, defaultPresentationPolicy, bundle);
    const request = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(request?.headers).toEqual(expect.objectContaining({ "X-Joshi-Pairing-Token": "c".repeat(64) }));
    expect(JSON.parse(String(request?.body))).toMatchObject({
      contract: "joshi.presentation.scene_admission",
      policy: { policyId: defaultPresentationPolicy.policyId },
      explorationBundle: { bundleId: bundle.bundleId },
      scene: { presentationId: scene.presentationId },
    });

    fetchMock.mockClear();
    await expect(new LoopbackPresentationSink("http://127.0.0.1:8787", new MemoryOnlyPairingSession()).appendScene(scene, defaultPresentationPolicy, bundle)).rejects.toThrow(/not paired/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
