import {
  presentationPolicyV1Schema,
  type PresentationPolicyV1,
  type PresentationViewKind,
} from "./contract";

/**
 * The authored presentation plans Glass can run: panel order, salience, and the stated hypothesis
 * each one is testing.
 *
 * These are plans, not evidence. Nothing here is an observation, a number, or a claim about a
 * market -- a policy decides what is shown and in what order, and the hypothesis renders labelled
 * as a hypothesis. That is why they may reach a live session, and it is why they no longer live in
 * a module named `fixtures`, where their presence made a genuinely authored dataset look routine.
 */
const OUTCOMES: PresentationPolicyV1["outcomes"] = [
  { measure: "attention_cost", authority: "operator_report", note: "Ask whether the representation reduced or increased cognitive work." },
  { measure: "decision_latency", authority: "event_timestamps", note: "Derive from exact scene and gesture clocks; never ask Ember to run a stopwatch." },
  { measure: "missed_opportunity", authority: "choice_set_analysis", note: "Assess retrospectively against the exact served and visible alternatives." },
  { measure: "overtrading", authority: "episode_analysis", note: "Assess only after episode actions are reconciled; display changes are not trades." },
  { measure: "pnl", authority: "reconciled_accounting_projection", note: "Link a versioned accounting projection; Glass never computes PnL." },
  { measure: "regret", authority: "operator_report", note: "Keep contemporaneous and outcome-aware reports distinct." },
];

const SHELL_ORDER = [
  "attention-feed",
  "coin-workbench",
  "hypothesis-lab",
  "operator-panel",
  "episode-rail",
  "source-provenance",
];

const makePolicy = (
  policyId: string,
  title: string,
  hypothesis: string,
  primaryView: PresentationViewKind,
  salienceItems: Array<{ itemId: string; value: "ambient" | "normal" | "prominent" | "urgent" }>,
): PresentationPolicyV1 => presentationPolicyV1Schema.parse({
  contract: "joshi.presentation.policy",
  schemaVersion: 1,
  policyId,
  policyVersion: "1",
  title,
  hypothesis,
  assignmentMode: "operator_selected",
  primaryView,
  panelOrder: SHELL_ORDER,
  salience: [...salienceItems].sort((a, b) => a.itemId < b.itemId ? -1 : 1),
  visibleOverlays: ["derived", "inferred", "observed", "uncertain"],
  safetyRules: {
    neverOmitItemIds: ["episode-rail", "source-provenance"],
    liveRandomization: "forbidden",
    informationPolicy: "preserve_rich_information",
  },
  outcomes: OUTCOMES,
});

export const presentationPolicies = [
  makePolicy(
    "policy-coupled-fields-v1",
    "Coupled field bundle",
    "Keeping flow, attention, topology, liquidity, and lifecycle together may expose disagreement that a scalar score would erase.",
    "field_bundle",
    [{ itemId: "hypothesis-lab", value: "prominent" }, { itemId: "source-provenance", value: "normal" }],
  ),
  makePolicy(
    "policy-flow-first-v1",
    "Flow before story",
    "Putting exact wallet and venue flow before cluster or social interpretation may reduce hollow-motion entries without withholding the social field.",
    "wallet_cluster_flow",
    [{ itemId: "hypothesis-lab", value: "prominent" }, { itemId: "source-provenance", value: "prominent" }],
  ),
  makePolicy(
    "policy-social-first-v1",
    "Arrival before return",
    "Showing callout occurrence, audience arrival, and competing events before price response may improve recognition of social transitions without implying causality.",
    "attention_arrival",
    [{ itemId: "attention-feed", value: "prominent" }, { itemId: "hypothesis-lab", value: "prominent" }],
  ),
].sort((a, b) => a.policyId < b.policyId ? -1 : 1);

export const defaultPresentationPolicy = presentationPolicies.find((policy) => policy.policyId === "policy-flow-first-v1") ?? presentationPolicies[0]!;
