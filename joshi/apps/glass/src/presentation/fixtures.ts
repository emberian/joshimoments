import type { GlassSnapshotV1 } from "../contract/v1";
import {
  explorationBundleV1Schema,
  type ExplorationBundleV1,
} from "./contract";

/**
 * The offline fixture exploration bundle: authored wallet-flow, attention, liquidity and topology
 * rows for the demonstration coin.
 *
 * THIS IS AUTHORED DATA. Every number below was written by hand and describes no real market. It
 * may only be reached from the offline fixture data source. A loopback or publication-backed
 * session must never render it: on 2026-08-21 it did, because a live code path imported it from
 * here, and roughly fifteen invented figures rendered behind a green "Observed" badge. The live
 * path is `servedSceneBundle.ts`.
 */
type Lineage = {
  evidenceClass: "observed" | "derived" | "inferred" | "uncertain";
  epistemicLabel: "protocol_fact" | "provider_assertion" | "first_party_statement" | "operator_annotation" | "derived_measure" | "model_inference";
  sourceRef: string;
  availableAt: string;
  coverage: "complete_for_scope" | "partial" | "gap" | "unknown";
  uncertainty: string;
};

function lineage(
  availableAt: string,
  evidenceClass: Lineage["evidenceClass"],
  epistemicLabel: Lineage["epistemicLabel"],
  sourceRef: string,
  coverage: Lineage["coverage"],
  uncertainty: string,
): Lineage {
  return { evidenceClass, epistemicLabel, sourceRef, availableAt, coverage, uncertainty };
}

function value(valueText: string, unit: string | null = null) {
  return { value: valueText, unit };
}

export function explorationBundleFor(snapshot: GlassSnapshotV1): ExplorationBundleV1 {
  const availableAt = snapshot.view.asOf.renderedAt;
  const observed = (sourceRef: string, uncertainty: string) => lineage(availableAt, "observed", "protocol_fact", sourceRef, "partial", uncertainty);
  const provider = (sourceRef: string, uncertainty: string) => lineage(availableAt, "observed", "provider_assertion", sourceRef, "partial", uncertainty);
  const derived = (sourceRef: string, uncertainty: string) => lineage(availableAt, "derived", "derived_measure", sourceRef, "partial", uncertainty);
  const inferred = (sourceRef: string, uncertainty: string) => lineage(availableAt, "inferred", "model_inference", sourceRef, "partial", uncertainty);
  const uncertain = (sourceRef: string, uncertainty: string) => lineage(availableAt, "uncertain", "model_inference", sourceRef, "unknown", uncertainty);

  const panels = [
      {
        panelId: "lab-attention-arrival",
        viewKind: "attention_arrival",
        title: "Attention arrival",
        question: "Which audiences arrived, through which observed surfaces, and how incomplete is the window?",
        claimBoundary: "Occurrence and arrival order are descriptive. Provider identity links and audience overlap are not causal impact.",
        evidenceClass: "mixed",
        signals: [
          { signalId: "arrival-observed-accounts", label: "Observed arriving accounts", value: value("18", "accounts"), interval: null, support: "Pump replies and callout fixture inside this scene cut", lineage: provider("attention:event:orbitfan", "Pump-only activity and deletions outside the collected window may be missing.") },
          { signalId: "arrival-overlap", label: "Sampled audience overlap", value: value("7/18", "observed accounts"), interval: null, support: "Numerator and denominator retained; sampled roots only", lineage: derived("attention:overlap:orbitfan", "Not a platform-wide audience estimate.") },
        ],
        relations: [
          { relationId: "arrival-callout-community", from: "CALL OUT OBSERVED", to: "community replies", relation: "followed in observed event order", direction: "directed", value: value("37", "seconds"), alternative: "Both may respond to an unobserved external event.", lineage: provider("attention:event:callout-1", "Event time is bounded by provider receipt time.") },
        ],
        marks: [
          { markId: "arrival-mark-callout", at: availableAt, label: "CALL OUT OBSERVED", size: null, detail: "Occurrence only; caller skill and future peak are not encoded.", lineage: provider("attention:event:callout-1", "Source may omit edits or deletions.") },
        ],
      },
      {
        panelId: "lab-caller-response",
        viewKind: "caller_response_kernel",
        title: "Caller response kernel",
        question: "How did marked wallet arrival, signed flow, liquidity, and attention unfold after an observed callout?",
        claimBoundary: "Descriptive, noncausal kernel fixture. Overlapping callouts, lifecycle, coverage, and competing events remain explicit.",
        evidenceClass: "derived",
        signals: [
          { signalId: "kernel-effective-support", label: "Effective support", value: value("11", "marked events"), interval: null, support: "14 events; overlap-adjusted ESS 11", lineage: derived("kernel:orbitfan:v1", "Small support; caller identity revisions can change the cohort.") },
          { signalId: "kernel-wallet-arrival", label: "Wallet arrival at +30–90s", value: value("1.7", "relative intensity"), interval: { lower: "1.1", upper: "2.6" }, support: "Bootstrap interval over marked event rows", lineage: inferred("kernel:orbitfan:v1", "Estimator output, not a probability of price increase.") },
        ],
        relations: [
          { relationId: "kernel-callout-wallet", from: "callout mark", to: "wallet arrival intensity", relation: "lagged response estimate", direction: "directed", value: value("+30..90", "seconds"), alternative: "Common news or board rank can drive both marks and arrival.", lineage: inferred("kernel:orbitfan:v1", "Noncausal fit with partial attention coverage.") },
        ],
        marks: [],
      },
      {
        panelId: "lab-field-bundle",
        viewKind: "field_bundle",
        title: "Coupled field bundle",
        question: "Where do flow, attention, topology, liquidity, and lifecycle agree—and where do they refuse to collapse?",
        claimBoundary: "This is deliberately not a pressure score. Each field keeps its unit, lineage, support, and contradictory alternatives.",
        evidenceClass: "mixed",
        signals: [
          { signalId: "field-attention", label: "Attention arrival", value: value("accelerating", null), interval: null, support: "Observed provider event order", lineage: provider("attention:arrival:orbitfan", "Audience coverage is partial.") },
          { signalId: "field-flow", label: "Signed wallet flow", value: value("two-sided", null), interval: null, support: "Observed swaps in hot scope", lineage: derived("wallet:flow:orbitfan", "Route and wallet coverage are incomplete.") },
          { signalId: "field-liquidity", label: "Liquidity susceptibility", value: value("high for marked size", null), interval: null, support: "Versioned reserve-geometry analysis", lineage: inferred("field:liquidity:orbitfan", "Not an executable quote and not stable across size.") },
          { signalId: "field-topology", label: "Cluster topology", value: value("contested", null), interval: null, support: "Two incompatible cluster hypotheses remain active", lineage: uncertain("wallet:cluster:orbitfan", "Shared funding does not prove shared control.") },
        ],
        relations: [],
        marks: [],
      },
      {
        panelId: "lab-lifecycle-topology",
        viewKind: "lifecycle_topology",
        title: "Lifecycle and topology",
        question: "Which market, community, venue, and inferred-cohort transitions coexist at this evidence cut?",
        claimBoundary: "Lifecycle transitions may overlap and be disputed. A candidate transition is not a forced phase or trading recommendation.",
        evidenceClass: "mixed",
        signals: [
          { signalId: "lifecycle-market", label: "Market lifecycle", value: value("bonding", null), interval: null, support: "Candidate state in immutable Glass view", lineage: observed("scene:candidate:orbitfan", "Venue state may lag the next chain slot.") },
          { signalId: "lifecycle-social", label: "Social transition candidate", value: value("audience arrival", null), interval: null, support: "Provider events and identity-version hypothesis", lineage: inferred("attention:territory:orbitfan", "Represented-person participation remains unverified.") },
        ],
        relations: [
          { relationId: "lifecycle-community-venue", from: "community aggregation", to: "bonding venue", relation: "co-occurs inside scene", direction: "undirected", value: null, alternative: "The apparent community can fragment before venue migration.", lineage: uncertain("topology:orbitfan:v1", "Territory memberships are overlapping and revisable.") },
        ],
        marks: [],
      },
      {
        panelId: "lab-liquidity-resilience",
        viewKind: "liquidity_susceptibility_resilience",
        title: "Liquidity susceptibility and resilience",
        question: "How does response change with marked size, reserve geometry, venue state, and subsequent opposing flow?",
        claimBoundary: "These descriptive geometry fields are neither executable quotes nor a timeless liquidity score.",
        evidenceClass: "derived",
        signals: [
          { signalId: "liquidity-recovery", label: "Observed displacement recovery", value: value("43", "percent by 90s"), interval: { lower: "19", upper: "68" }, support: "Six size-matched marks", lineage: inferred("field:resilience:orbitfan", "Recovery may be regime change, arbitrage, or attention exit rather than refill.") },
          { signalId: "liquidity-susceptibility", label: "Reserve-geometry susceptibility", value: value("2.4", "relative at 0.15 SOL mark"), interval: null, support: "Exact reserve state projected at marked—not executable—size", lineage: derived("field:susceptibility:orbitfan", "Quote fees and route competition are excluded.") },
        ],
        relations: [],
        marks: [],
      },
      {
        panelId: "lab-marked-orders",
        viewKind: "marked_order_timing_size",
        title: "Marked order timing and size",
        question: "Where did exact observed swaps land relative to operator, social, and lifecycle marks?",
        claimBoundary: "These are unverified fixture observations with exact atom strings. Production may call them facts only after canonicality, finality, and coverage admission; they never identify intent, ownership, or Ember's fills.",
        evidenceClass: "observed",
        signals: [],
        relations: [],
        marks: [
          { markId: "order-mark-1", at: availableAt, label: "observed swap", size: value("150000000", "lamports"), detail: "wallet …7kQ → ORBITFAN on bonding venue", lineage: observed("chain:signature:fixture-1", "Finalized fixture observation; routed attribution is partial.") },
          { markId: "order-mark-2", at: availableAt, label: "observed swap", size: value("42000000", "lamports"), detail: "wallet …2mP → ORBITFAN in same-tx bundle", lineage: observed("chain:signature:fixture-2", "Same transaction is fact; common control is not.") },
        ],
      },
      {
        panelId: "lab-pvp-churn",
        viewKind: "pvp_compression_churn",
        title: "PvP compression and churn",
        question: "Which directed actors or venues exchange flow, and how quickly do relationships reverse or dissipate?",
        claimBoundary: "Antisymmetric flow remains dyadic and directional. 'Drain', 'vamp', and coordination labels are hypotheses, not identities.",
        evidenceClass: "mixed",
        signals: [
          { signalId: "pvp-churn", label: "Actor-edge churn", value: value("5/12", "edges changed in 2m"), interval: null, support: "Observed actor–mint swap edges in hot scope", lineage: derived("pvp:orbitfan:epoch-4", "Uncovered routes can make edges appear to vanish.") },
        ],
        relations: [
          { relationId: "pvp-host-clone", from: "host cohort hypothesis A", to: "clone cohort hypothesis B", relation: "net directed flow", direction: "directed", value: value("-84000000", "lamports"), alternative: "Independent wallets may be reacting to the same price path.", lineage: inferred("pvp:orbitfan:epoch-4", "Cluster memberships are versioned hypotheses.") },
        ],
        marks: [],
      },
      {
        panelId: "lab-wallet-cluster-flow",
        viewKind: "wallet_cluster_flow",
        title: "Wallet and cluster flow",
        question: "Which wallet actions does the current evidence cut support, and which competing cluster hypotheses could explain their topology?",
        claimBoundary: "Admitted wallet addresses and swaps may become protocol facts; this fixture remains unverified. Funding links and cluster membership never establish identity or coordination by themselves.",
        evidenceClass: "mixed",
        signals: [
          { signalId: "wallet-gross-in", label: "Observed gross in", value: value("384000000", "lamports"), interval: null, support: "Hot-scope finalized swaps only", lineage: observed("wallet:mint:orbitfan", "Not full-market flow; provider gaps remain explicit.") },
          { signalId: "wallet-hypothesis-confidence", label: "Cluster hypothesis A confidence", value: value("620000", "ppm"), interval: null, support: "Shared funding plus temporal co-trading", lineage: inferred("cluster-hypothesis:orbitfan:a:v3", "Alternative: launch-route batching without shared operator.") },
        ],
        relations: [
          { relationId: "wallet-funding", from: "wallet …7kQ", to: "wallet …2mP", relation: "funding transfer observed", direction: "directed", value: value("900000000", "lamports"), alternative: "A transfer does not prove common control.", lineage: observed("chain:signature:funding-fixture", "Origin before collection start is unknown.") },
        ],
        marks: [],
      },
    ];
  const sourceRefs = new Set<string>();
  for (const panel of panels) {
    for (const signal of panel.signals) sourceRefs.add(signal.lineage.sourceRef);
    for (const relation of panel.relations) sourceRefs.add(relation.lineage.sourceRef);
    for (const mark of panel.marks) sourceRefs.add(mark.lineage.sourceRef);
  }
  const sourceArtifacts = [...sourceRefs].sort().map((sourceRef, index) => ({
    artifactId: sourceRef,
    contract: "joshi.fixture.source_artifact",
    artifactDigest: `sha256:${(index + 1).toString(16).padStart(64, "0")}`,
    availableAt,
    coverageBinding: "unverified_fixture",
    admissionStatus: "fixture_unverified",
  }));

  return explorationBundleV1Schema.parse({
    contract: "joshi.presentation.exploration_bundle",
    schemaVersion: 1,
    bundleId: `exploration-${snapshot.view.sceneId}`,
    scene: { sceneId: snapshot.view.sceneId, viewDigest: snapshot.snapshotDigest },
    generatedAt: availableAt,
    claim: "descriptive_noncausal_fixture",
    sourceArtifacts,
    panels,
  });
}
