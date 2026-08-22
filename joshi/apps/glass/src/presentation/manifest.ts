import type { GlassSnapshotV1 } from "../contract/v1";
import {
  presentationSceneV1Schema,
  type ExplorationBundleV1,
  type PresentationEvidenceClass,
  type PresentationPolicyV1,
  type PresentationSceneV1,
  type PresentationViewKind,
} from "./contract";
import { digestExplorationBundle, digestPresentationPolicy } from "./contract";

/**
 * Pure construction of a presentation manifest and scene from a policy, a bundle, and a snapshot.
 *
 * Every function here is a total function of its arguments. Nothing is authored data, nothing is a
 * fixture, and nothing is specific to any coin -- which is exactly why it should never have lived
 * in a module named `fixtures`, where an importer had no way to tell a pure builder apart from a
 * hardcoded dataset.
 */
const VIEW_ITEM_BY_KIND: Record<PresentationViewKind, string> = {
  attention_arrival: "lab-attention-arrival",
  caller_response_kernel: "lab-caller-response",
  field_bundle: "lab-field-bundle",
  lifecycle_topology: "lab-lifecycle-topology",
  liquidity_susceptibility_resilience: "lab-liquidity-resilience",
  marked_order_timing_size: "lab-marked-orders",
  pvp_compression_churn: "lab-pvp-churn",
  wallet_cluster_flow: "lab-wallet-cluster-flow",
};

export function presentationItemIdForView(kind: PresentationViewKind): string {
  return VIEW_ITEM_BY_KIND[kind];
}

const SHELL_ITEMS = ["attention-feed", "coin-workbench", "episode-rail", "hypothesis-lab", "operator-panel", "source-provenance"];
const OVERLAY_ITEMS = ["overlay-derived", "overlay-inferred", "overlay-observed", "overlay-uncertain"];
const VIEW_ITEMS = Object.values(VIEW_ITEM_BY_KIND).sort();

export function initialManifest(policy: PresentationPolicyV1): PresentationSceneV1["manifest"] {
  const primaryItem = VIEW_ITEM_BY_KIND[policy.primaryView];
  const eligibleItemIds = [...SHELL_ITEMS, ...OVERLAY_ITEMS, ...VIEW_ITEMS].sort();
  const items = eligibleItemIds.map((itemId) => {
    const isView = itemId.startsWith("lab-");
    const isOverlay = itemId.startsWith("overlay-");
    const isPrimary = itemId === primaryItem;
    const visible = !isView || isPrimary;
    const shellOrdinal = policy.panelOrder.indexOf(itemId);
    const viewOrdinal = VIEW_ITEMS.indexOf(itemId);
    const overlayOrdinal = OVERLAY_ITEMS.indexOf(itemId);
    const evidenceClass = (isOverlay ? itemId.replace("overlay-", "") : isView ? "mixed" : "observed") as PresentationEvidenceClass;
    return {
      itemId,
      itemKind: isOverlay ? "overlay" as const : isView ? "exploration_view" as const : "shell_panel" as const,
      placement: isOverlay ? "overlay" as const : itemId === "attention-feed" ? "left" as const : ["operator-panel", "episode-rail", "source-provenance"].includes(itemId) ? "right" as const : "center" as const,
      ordinal: String(isOverlay ? overlayOrdinal : shellOrdinal >= 0 ? shellOrdinal : 100 + viewOrdinal),
      visibility: visible ? "visible" as const : "omitted" as const,
      omissionReason: visible ? null : "policy" as const,
      salience: policy.salience.find((entry) => entry.itemId === itemId)?.value ?? "normal" as const,
      pinned: false,
      evidenceClass,
      safetyCritical: policy.safetyRules.neverOmitItemIds.includes(itemId),
    };
  });
  const selectedItemIds = items.filter((item) => item.visibility !== "omitted").map((item) => item.itemId);
  const plannedRenderItemIds = [...selectedItemIds];
  return {
    eligibleItemIds,
    selectedItemIds,
    plannedRenderItemIds,
    plannedInitialViewportItemIds: [],
    items,
    filters: [
      { filterId: "evidence-class", value: "all" },
      { filterId: "subject-scope", value: "scene-wide" },
    ],
    toggles: [
      { toggleId: "derived", state: true },
      { toggleId: "inferred", state: true },
      { toggleId: "observed", state: true },
      { toggleId: "text-equivalent", state: true },
      { toggleId: "uncertain", state: true },
    ],
    initialFocusItemId: null,
    comparisonItemIds: [],
  };
}

export function buildPresentationScene(
  snapshot: GlassSnapshotV1,
  bundle: ExplorationBundleV1,
  policy: PresentationPolicyV1,
  identity: {
    presentationId: string;
    idempotencyKey: string;
    assignmentId: string;
    clientSessionId: string;
    presentationSeq: string;
    capturedAt: string;
    clockId: string;
    monotonicNs: string;
  },
): PresentationSceneV1 {
  return presentationSceneV1Schema.parse({
    contract: "joshi.presentation.scene",
    schemaVersion: 1,
    presentationId: identity.presentationId,
    idempotencyKey: identity.idempotencyKey,
    clientSessionId: identity.clientSessionId,
    presentationSeq: identity.presentationSeq,
    scene: { sceneId: snapshot.view.sceneId, viewDigest: snapshot.snapshotDigest },
    policy: {
      policyId: policy.policyId,
      policyVersion: policy.policyVersion,
      assignmentId: identity.assignmentId,
      policyDigest: digestPresentationPolicy(policy),
    },
    artifacts: [{
      contract: bundle.contract,
      artifactId: bundle.bundleId,
      artifactDigest: digestExplorationBundle(bundle),
    }],
    manifest: initialManifest(policy),
    capturedAt: identity.capturedAt,
    clientClock: { clockId: identity.clockId, monotonicNs: identity.monotonicNs },
    authorityClass: "evidence_only",
    effectCeiling: "observe_only",
  });
}
