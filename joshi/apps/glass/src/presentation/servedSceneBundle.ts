import type { GlassSnapshotV1 } from "../contract/v1";
import {
  explorationBundleV1Schema,
  type ExplorationBundleV1,
  type PresentationViewKind,
} from "./contract";

/**
 * The exploration bundle for a scene JOSHI actually served.
 *
 * The hypothesis lab is a fixed eight-view frame: `explorationBundleV1Schema` requires exactly
 * eight panels, one per view kind, so the frame cannot be shortened to say "there is nothing to
 * explore here". This module satisfies that frame the only honest way available -- every panel is
 * present, and every panel is empty -- because JOSHI has no derivation that turns a served Glass
 * view into wallet flow, caller-response kernels, liquidity susceptibility, or cluster topology.
 *
 * Nothing here reads a number. Every value below is copied from the snapshot or is fixed text
 * about the absence itself. The one source artifact is the served view: its digest is the digest
 * the browser independently recomputed and checked in `parseGlassSnapshotV1`, so a reader can
 * verify it. `sourceArtifacts` would be empty if the contract allowed it; it requires at least
 * one entry, so the entry names the bytes this bundle is a function of rather than inventing a
 * provenance the scene does not have.
 */

/** Panel frames, in the ASCII `panelId` order the bundle contract requires. */
const PANEL_FRAMES: ReadonlyArray<{
  panelId: string;
  viewKind: PresentationViewKind;
  title: string;
  question: string;
}> = [
  {
    panelId: "lab-attention-arrival",
    viewKind: "attention_arrival",
    title: "Attention arrival",
    question: "Which audiences arrived, through which observed surfaces, and how incomplete is the window?",
  },
  {
    panelId: "lab-caller-response",
    viewKind: "caller_response_kernel",
    title: "Caller response kernel",
    question: "How did marked wallet arrival, signed flow, liquidity, and attention unfold after an observed callout?",
  },
  {
    panelId: "lab-field-bundle",
    viewKind: "field_bundle",
    title: "Coupled field bundle",
    question: "Where do flow, attention, topology, liquidity, and lifecycle agree—and where do they refuse to collapse?",
  },
  {
    panelId: "lab-lifecycle-topology",
    viewKind: "lifecycle_topology",
    title: "Lifecycle and topology",
    question: "Which market, community, venue, and inferred-cohort transitions coexist at this evidence cut?",
  },
  {
    panelId: "lab-liquidity-resilience",
    viewKind: "liquidity_susceptibility_resilience",
    title: "Liquidity susceptibility and resilience",
    question: "How does response change with marked size, reserve geometry, venue state, and subsequent opposing flow?",
  },
  {
    panelId: "lab-marked-orders",
    viewKind: "marked_order_timing_size",
    title: "Marked order timing and size",
    question: "Where did exact observed swaps land relative to operator, social, and lifecycle marks?",
  },
  {
    panelId: "lab-pvp-churn",
    viewKind: "pvp_compression_churn",
    title: "PvP compression and churn",
    question: "Which directed actors or venues exchange flow, and how quickly do relationships reverse or dissipate?",
  },
  {
    panelId: "lab-wallet-cluster-flow",
    viewKind: "wallet_cluster_flow",
    title: "Wallet and cluster flow",
    question: "Which wallet actions does the current evidence cut support, and which competing cluster hypotheses could explain their topology?",
  },
];

/**
 * One boundary, identical on every panel, because the boundary is the same fact on every panel:
 * this evidence cut produced no row for this view. It is deliberately not a per-panel narrative,
 * since a narrative is where an unearned claim gets in.
 */
const EMPTY_PANEL_BOUNDARY = "The served scene bytes produced no signal, relation, or mark "
  + "for this view.";

/**
 * Builds the exact exploration bundle for one served snapshot.
 *
 * Deterministic: the same snapshot always produces byte-identical bundle bytes, so re-rendering a
 * scene re-derives the same bundle digest rather than a new artifact identity.
 */
export function explorationBundleForServedScene(snapshot: GlassSnapshotV1): ExplorationBundleV1 {
  const availableAt = snapshot.view.asOf.renderedAt;
  return explorationBundleV1Schema.parse({
    contract: "joshi.presentation.exploration_bundle",
    schemaVersion: 1,
    bundleId: `served-scene-${snapshot.view.sceneId}`,
    scene: { sceneId: snapshot.view.sceneId, viewDigest: snapshot.snapshotDigest },
    generatedAt: availableAt,
    claim: "descriptive_noncausal",
    sourceArtifacts: [{
      // The served Glass view itself, under the digest the browser recomputed and checked.
      artifactId: `scene:${snapshot.view.sceneId}`,
      contract: "joshi.glass.view",
      artifactDigest: snapshot.snapshotDigest,
      availableAt,
      coverageBinding: "verified_scene_cut",
      // The browser observed these exact bytes. It does not know whether the scene is durable
      // yet -- a mounted live surface is served from memory until an act retains it -- so no
      // admission is claimed.
      admissionStatus: "observed_unaccepted",
    }],
    panels: PANEL_FRAMES.map((frame) => ({
      panelId: frame.panelId,
      viewKind: frame.viewKind,
      title: frame.title,
      question: frame.question,
      claimBoundary: EMPTY_PANEL_BOUNDARY,
      // No row exists, so no evidence class is established for this panel. `uncertain` is the
      // least-committing member the contract offers; it has no "absent" member.
      evidenceClass: "uncertain",
      signals: [],
      relations: [],
      marks: [],
    })),
  });
}
