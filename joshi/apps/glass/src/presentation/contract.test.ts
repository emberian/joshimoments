import { describe, expect, it } from "vitest";

import { mockSnapshots } from "../data/mockSnapshot";
import {
  canonicalExplorationBundle,
  canonicalPresentationEvent,
  canonicalPresentationPolicy,
  canonicalPresentationScene,
  digestExplorationBundle,
  digestPresentationEvent,
  digestPresentationPolicy,
  digestPresentationScene,
  explorationBundleV1Schema,
  presentationEventReceiptV1Schema,
  presentationEventV1Schema,
  presentationPolicyV1Schema,
  presentationSceneReceiptV1Schema,
  presentationSceneV1Schema,
} from "./contract";
import { explorationBundleFor } from "./fixtures";
import { buildPresentationScene, initialManifest } from "./manifest";
import { defaultPresentationPolicy, presentationPolicies } from "./policies";
import {
  GOLDEN_EXPLORATION_BUNDLE_V1_BYTES,
  GOLDEN_EXPLORATION_BUNDLE_V1_DIGEST,
  GOLDEN_EXPLORATION_BUNDLE_V1_JSON,
  GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_BYTES,
  GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_DIGEST,
  GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_JSON,
  GOLDEN_PRESENTATION_EVENT_V1_BYTES,
  GOLDEN_PRESENTATION_EVENT_V1_DIGEST,
  GOLDEN_PRESENTATION_EVENT_V1_JSON,
  GOLDEN_PRESENTATION_POLICY_V1_BYTES,
  GOLDEN_PRESENTATION_POLICY_V1_DIGEST,
  GOLDEN_PRESENTATION_POLICY_V1_JSON,
  GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_BYTES,
  GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_DIGEST,
  GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_JSON,
  GOLDEN_PRESENTATION_SCENE_V1_BYTES,
  GOLDEN_PRESENTATION_SCENE_V1_DIGEST,
  GOLDEN_PRESENTATION_SCENE_V1_JSON,
} from "./golden";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

function sceneFixture() {
  const snapshot = mockSnapshots.witnessed;
  const bundle = explorationBundleFor(snapshot);
  const scene = buildPresentationScene(snapshot, bundle, defaultPresentationPolicy, {
    presentationId: "presentation-golden",
    idempotencyKey: "presentation-retry-golden",
    assignmentId: "manual-assignment-golden",
    clientSessionId: "presentation-session-golden",
    presentationSeq: "1",
    capturedAt: "2026-08-16T18:42:15.000000Z",
    clockId: "presentation-clock-golden",
    monotonicNs: "1000000",
  });
  return { snapshot, bundle, scene };
}

describe("presentation hypothesis contracts", () => {
  it("pins exact TypeScript reference policy, bundle, scene, interval-event, and receipt bytes", () => {
    const encoder = new TextEncoder();
    const wireDigest = (wire: string) => `sha256:${bytesToHex(sha256(encoder.encode(wire)))}`;
    const policy = presentationPolicyV1Schema.parse(JSON.parse(GOLDEN_PRESENTATION_POLICY_V1_JSON));
    const bundle = explorationBundleV1Schema.parse(JSON.parse(GOLDEN_EXPLORATION_BUNDLE_V1_JSON));
    const scene = presentationSceneV1Schema.parse(JSON.parse(GOLDEN_PRESENTATION_SCENE_V1_JSON));
    const event = presentationEventV1Schema.parse(JSON.parse(GOLDEN_PRESENTATION_EVENT_V1_JSON));
    const sceneReceipt = presentationSceneReceiptV1Schema.parse(JSON.parse(GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_JSON));
    const eventReceipt = presentationEventReceiptV1Schema.parse(JSON.parse(GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_JSON));

    expect(canonicalPresentationPolicy(policy)).toBe(GOLDEN_PRESENTATION_POLICY_V1_JSON);
    expect(digestPresentationPolicy(policy)).toBe(GOLDEN_PRESENTATION_POLICY_V1_DIGEST);
    expect(canonicalExplorationBundle(bundle)).toBe(GOLDEN_EXPLORATION_BUNDLE_V1_JSON);
    expect(digestExplorationBundle(bundle)).toBe(GOLDEN_EXPLORATION_BUNDLE_V1_DIGEST);
    expect(canonicalPresentationScene(scene)).toBe(GOLDEN_PRESENTATION_SCENE_V1_JSON);
    expect(digestPresentationScene(scene)).toBe(GOLDEN_PRESENTATION_SCENE_V1_DIGEST);
    expect(canonicalPresentationEvent(event)).toBe(GOLDEN_PRESENTATION_EVENT_V1_JSON);
    expect(digestPresentationEvent(event)).toBe(GOLDEN_PRESENTATION_EVENT_V1_DIGEST);
    expect(JSON.stringify(sceneReceipt)).toBe(GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_JSON);
    expect(wireDigest(GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_JSON)).toBe(GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_DIGEST);
    expect(JSON.stringify(eventReceipt)).toBe(GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_JSON);
    expect(wireDigest(GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_JSON)).toBe(GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_DIGEST);
    expect([
      encoder.encode(GOLDEN_PRESENTATION_POLICY_V1_JSON).byteLength,
      encoder.encode(GOLDEN_EXPLORATION_BUNDLE_V1_JSON).byteLength,
      encoder.encode(GOLDEN_PRESENTATION_SCENE_V1_JSON).byteLength,
      encoder.encode(GOLDEN_PRESENTATION_EVENT_V1_JSON).byteLength,
      encoder.encode(GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_JSON).byteLength,
      encoder.encode(GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_JSON).byteLength,
    ]).toEqual([
      GOLDEN_PRESENTATION_POLICY_V1_BYTES,
      GOLDEN_EXPLORATION_BUNDLE_V1_BYTES,
      GOLDEN_PRESENTATION_SCENE_V1_BYTES,
      GOLDEN_PRESENTATION_EVENT_V1_BYTES,
      GOLDEN_PRESENTATION_SCENE_RECEIPT_V1_BYTES,
      GOLDEN_PRESENTATION_EVENT_RECEIPT_V1_BYTES,
    ]);
  });

  it("makes every policy operator-selected, information-preserving, and complete over named outcomes", () => {
    for (const policy of presentationPolicies) {
      expect(presentationPolicyV1Schema.parse(policy).assignmentMode).toBe("operator_selected");
      expect(policy.safetyRules).toEqual(expect.objectContaining({
        liveRandomization: "forbidden",
        informationPolicy: "preserve_rich_information",
      }));
      expect(policy.outcomes.map((outcome) => outcome.measure).sort()).toEqual([
        "attention_cost",
        "decision_latency",
        "missed_opportunity",
        "overtrading",
        "pnl",
        "regret",
      ]);
    }
  });

  it("requires a concrete manual assignment and binds the exact evidence scene and artifacts", () => {
    const { bundle, scene, snapshot } = sceneFixture();
    expect(scene.policy.assignmentId).toBe("manual-assignment-golden");
    expect(scene.scene).toEqual({ sceneId: snapshot.view.sceneId, viewDigest: snapshot.snapshotDigest });
    expect(bundle.scene).toEqual(scene.scene);
    expect(scene.artifacts).toHaveLength(1);
    expect(scene.artifacts[0]?.artifactId).toBe(bundle.bundleId);
  });

  it("rejects dangling or future-available analytical lineage", () => {
    const { bundle } = sceneFixture();
    const dangling = structuredClone(bundle);
    const firstSignal = dangling.panels[0]?.signals[0];
    expect(firstSignal).toBeDefined();
    if (!firstSignal) return;
    firstSignal.lineage.sourceRef = "missing-artifact";
    expect(() => explorationBundleV1Schema.parse(dangling)).toThrow(/sourceRef/i);

    const future = structuredClone(bundle);
    const firstArtifact = future.sourceArtifacts[0];
    expect(firstArtifact).toBeDefined();
    if (!firstArtifact) return;
    firstArtifact.availableAt = "2026-08-16T18:42:16.000000Z";
    expect(() => explorationBundleV1Schema.parse(future)).toThrow(/after bundle generation|availability/i);
  });

  it("enforces selected/planned-render/viewport closure and never permits safety-critical omission", () => {
    const manifest = initialManifest(defaultPresentationPolicy);
    const outsideRendered = structuredClone(manifest);
    outsideRendered.plannedInitialViewportItemIds = ["lab-caller-response"];
    expect(() => presentationSceneV1Schema.shape.manifest.parse(outsideRendered)).toThrow(/viewport.*planned/i);

    const unsafe = structuredClone(manifest);
    const source = unsafe.items.find((item) => item.itemId === "source-provenance");
    expect(source).toBeDefined();
    if (!source) return;
    source.visibility = "omitted";
    source.omissionReason = "policy";
    unsafe.plannedRenderItemIds = unsafe.plannedRenderItemIds.filter((item) => item !== "source-provenance");
    expect(() => presentationSceneV1Schema.shape.manifest.parse(unsafe)).toThrow(/safety-critical/i);
  });

  it("binds ordering, salience, toggles, filters, and omissions in the presentation digest", () => {
    const { scene } = sceneFixture();
    const baseline = digestPresentationScene(scene);
    const mutations = [
      (value: typeof scene) => { value.manifest.items[0]!.ordinal = "90"; },
      (value: typeof scene) => { value.manifest.items[0]!.salience = "urgent"; },
      (value: typeof scene) => { value.manifest.toggles[0]!.state = !value.manifest.toggles[0]!.state; },
      (value: typeof scene) => { value.manifest.filters[0]!.value = "observed"; },
      (value: typeof scene) => {
        const item = value.manifest.items.find((candidate) => candidate.itemId === "lab-caller-response");
        if (item) item.omissionReason = "operator_filter";
      },
    ];
    for (const mutate of mutations) {
      const changed = structuredClone(scene);
      mutate(changed);
      expect(digestPresentationScene(changed)).not.toBe(baseline);
    }
  });

  it("records focus/dwell as interval occurrences and rejects aggregate attention claims", () => {
    const { scene } = sceneFixture();
    const event = {
      contract: "joshi.presentation.event",
      schemaVersion: 1,
      eventId: "event-focus-start",
      idempotencyKey: "event-retry-focus-start",
      clientSessionId: scene.clientSessionId,
      presentationEventSeq: "1",
      presentation: { presentationId: scene.presentationId, presentationDigest: digestPresentationScene(scene) },
      scene: scene.scene,
      subject: { kind: "panel", key: "lab-wallet-cluster-flow" },
      occurredAt: "2026-08-16T18:42:15.100000Z",
      clientClock: { clockId: "presentation-clock-golden", monotonicNs: "1100000" },
      eventKind: "focus_started",
      payload: { reason: "initial_reveal" },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    } as const;
    expect(presentationEventV1Schema.parse(event).eventKind).toBe("focus_started");
    expect(() => presentationEventV1Schema.parse({ ...event, dwellMilliseconds: "100" })).toThrow();
  });

  it("does not accept client-side PnL truth in usefulness evidence", () => {
    const { scene } = sceneFixture();
    const base = {
      contract: "joshi.presentation.event",
      schemaVersion: 1,
      eventId: "event-usefulness",
      idempotencyKey: "event-retry-usefulness",
      clientSessionId: scene.clientSessionId,
      presentationEventSeq: "2",
      presentation: { presentationId: scene.presentationId, presentationDigest: digestPresentationScene(scene) },
      scene: scene.scene,
      subject: { kind: "presentation", key: "hypothesis-lab" },
      occurredAt: "2026-08-16T18:42:16.000000Z",
      clientClock: { clockId: "presentation-clock-golden", monotonicNs: "2000000" },
      eventKind: "usefulness_reported",
      payload: {
        usefulness: "helpful",
        decisionLatency: "faster",
        attentionCost: "lower",
        overtrading: "unknown",
        regret: "unknown",
        missedOpportunity: "unknown",
        pnl: { status: "awaiting_reconciled_projection", projectionDigest: null, valueSol: "1.0" },
        note: null,
      },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    };
    expect(() => presentationEventV1Schema.parse(base)).toThrow();
  });

  it("rejects unknown receipt keys and assignment mismatches", () => {
    const { scene } = sceneFixture();
    const receipt = {
      contract: "joshi.store.presentation_scene_receipt",
      schemaVersion: 1,
      catalogId: "fixture-catalog",
      catalogSchema: "joshi.catalog.v1",
      batchId: "batch-presentation-golden",
      presentationId: scene.presentationId,
      idempotencyKey: scene.idempotencyKey,
      assignmentId: scene.policy.assignmentId,
      scene: scene.scene,
      policyDigest: scene.policy.policyDigest,
      presentationDigest: digestPresentationScene(scene),
      commitSeq: "1",
      status: "accepted",
    } as const;
    expect(presentationSceneReceiptV1Schema.parse(receipt).assignmentId).toBe("manual-assignment-golden");
    expect(() => presentationSceneReceiptV1Schema.parse({ ...receipt, hiddenOutcome: true })).toThrow();
  });
});
