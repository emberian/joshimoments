import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { z } from "zod";

import { exactUtcInstantSchema } from "../contract/instant";

const asciiIdentity = z
  .string()
  .min(1)
  .max(512)
  .regex(/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/, "must be a canonical ASCII identity");
const exactText = (maximum: number) => z
  .string()
  .min(1)
  .max(maximum)
  .refine((value) => value === value.trim(), "must not have surrounding whitespace");
const wireU64 = z.string().regex(/^(?:0|[1-9][0-9]*)$/, "must be a non-negative integer string");
const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/, "must be a lowercase SHA-256 digest");
const instant = exactUtcInstantSchema;

function requireSortedUnique(
  values: string[],
  refinement: z.core.$RefinementCtx<unknown>,
  path: PropertyKey[],
): void {
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1];
    const current = values[index];
    if (previous !== undefined && current !== undefined && previous >= current) {
      refinement.addIssue({
        code: "custom",
        message: "must be strictly ASCII sorted with no duplicates",
        path: [...path, index],
      });
    }
  }
}

function sortedIdentities() {
  return z.array(asciiIdentity).superRefine((values, refinement) => requireSortedUnique(values, refinement, []));
}

function uniqueIdentities() {
  return z.array(asciiIdentity).superRefine((values, refinement) => {
    if (new Set(values).size !== values.length) {
      refinement.addIssue({ code: "custom", message: "must contain unique identities" });
    }
  });
}

const sceneReference = z.object({
  sceneId: asciiIdentity,
  viewDigest: digest,
}).strict();

const clientClock = z.object({
  clockId: asciiIdentity,
  monotonicNs: wireU64,
}).strict();

export const presentationEvidenceClassSchema = z.enum([
  "observed",
  "derived",
  "inferred",
  "uncertain",
  "mixed",
]);

export const presentationViewKindSchema = z.enum([
  "wallet_cluster_flow",
  "caller_response_kernel",
  "attention_arrival",
  "marked_order_timing_size",
  "liquidity_susceptibility_resilience",
  "pvp_compression_churn",
  "lifecycle_topology",
  "field_bundle",
]);

export const presentationOutcomeMeasureSchema = z.object({
  measure: z.enum([
    "decision_latency",
    "attention_cost",
    "overtrading",
    "regret",
    "missed_opportunity",
    "pnl",
  ]),
  authority: z.enum([
    "event_timestamps",
    "operator_report",
    "episode_analysis",
    "choice_set_analysis",
    "reconciled_accounting_projection",
  ]),
  note: exactText(500),
}).strict();

const salience = z.enum(["ambient", "normal", "prominent", "urgent"]);

export const presentationPolicyV1Schema = z.object({
  contract: z.literal("joshi.presentation.policy"),
  schemaVersion: z.literal(1),
  policyId: asciiIdentity,
  policyVersion: wireU64,
  title: exactText(120),
  hypothesis: exactText(1_200),
  assignmentMode: z.literal("operator_selected"),
  primaryView: presentationViewKindSchema,
  panelOrder: uniqueIdentities().min(1),
  salience: z.array(z.object({
    itemId: asciiIdentity,
    value: salience,
  }).strict()).superRefine((values, refinement) => {
    requireSortedUnique(values.map((value) => value.itemId), refinement, []);
  }),
  visibleOverlays: sortedIdentities(),
  safetyRules: z.object({
    neverOmitItemIds: sortedIdentities().min(1),
    liveRandomization: z.literal("forbidden"),
    informationPolicy: z.literal("preserve_rich_information"),
  }).strict(),
  outcomes: z.array(presentationOutcomeMeasureSchema).length(6).superRefine((values, refinement) => {
    requireSortedUnique(values.map((value) => value.measure), refinement, []);
  }),
}).strict().superRefine((policy, refinement) => {
  for (const safetyItem of policy.safetyRules.neverOmitItemIds) {
    if (!policy.panelOrder.includes(safetyItem)) {
      refinement.addIssue({ code: "custom", message: "safety item must be in panel order", path: ["safetyRules", "neverOmitItemIds"] });
    }
  }
});

const exactValue = z.object({
  value: exactText(240),
  unit: exactText(80).nullable(),
}).strict();

const lineage = z.object({
  evidenceClass: presentationEvidenceClassSchema.exclude(["mixed"]),
  epistemicLabel: z.enum([
    "protocol_fact",
    "provider_assertion",
    "first_party_statement",
    "operator_annotation",
    "derived_measure",
    "model_inference",
  ]),
  sourceRef: asciiIdentity,
  availableAt: instant,
  coverage: z.enum(["complete_for_scope", "partial", "gap", "unknown"]),
  uncertainty: exactText(800),
}).strict();

const fieldSignal = z.object({
  signalId: asciiIdentity,
  label: exactText(160),
  value: exactValue,
  interval: z.object({ lower: exactText(240), upper: exactText(240) }).strict().nullable(),
  support: exactText(300),
  lineage,
}).strict();

const fieldRelation = z.object({
  relationId: asciiIdentity,
  from: exactText(160),
  to: exactText(160),
  relation: exactText(160),
  direction: z.enum(["directed", "undirected", "bidirectional"]),
  value: exactValue.nullable(),
  alternative: exactText(500).nullable(),
  lineage,
}).strict();

const fieldMark = z.object({
  markId: asciiIdentity,
  at: instant,
  label: exactText(160),
  size: exactValue.nullable(),
  detail: exactText(500),
  lineage,
}).strict();

export const explorationPanelSchema = z.object({
  panelId: asciiIdentity,
  viewKind: presentationViewKindSchema,
  title: exactText(120),
  question: exactText(500),
  claimBoundary: exactText(800),
  evidenceClass: presentationEvidenceClassSchema,
  signals: z.array(fieldSignal).max(30),
  relations: z.array(fieldRelation).max(30),
  marks: z.array(fieldMark).max(30),
}).strict().superRefine((panel, refinement) => {
  requireSortedUnique(panel.signals.map((value) => value.signalId), refinement, ["signals"]);
  requireSortedUnique(panel.relations.map((value) => value.relationId), refinement, ["relations"]);
  requireSortedUnique(panel.marks.map((value) => value.markId), refinement, ["marks"]);
});

export const explorationBundleV1Schema = z.object({
  contract: z.literal("joshi.presentation.exploration_bundle"),
  schemaVersion: z.literal(1),
  bundleId: asciiIdentity,
  scene: sceneReference,
  generatedAt: instant,
  claim: z.enum(["descriptive_noncausal_fixture", "descriptive_noncausal"]),
  sourceArtifacts: z.array(z.object({
    artifactId: asciiIdentity,
    contract: asciiIdentity,
    artifactDigest: digest,
    availableAt: instant,
    coverageBinding: z.enum(["verified_scene_cut", "unverified_fixture"]),
    admissionStatus: z.enum(["accepted", "observed_unaccepted", "retracted", "fixture_unverified"]),
  }).strict()).min(1).superRefine((values, refinement) => {
    requireSortedUnique(values.map((value) => value.artifactId), refinement, []);
  }),
  panels: z.array(explorationPanelSchema).length(8),
}).strict().superRefine((bundle, refinement) => {
  requireSortedUnique(bundle.panels.map((value) => value.panelId), refinement, ["panels"]);
  const kinds = bundle.panels.map((panel) => panel.viewKind);
  if (new Set(kinds).size !== kinds.length) {
    refinement.addIssue({ code: "custom", message: "bundle must contain one panel per view kind", path: ["panels"] });
  }
  const artifacts = new Map(bundle.sourceArtifacts.map((artifact) => [artifact.artifactId, artifact]));
  for (const [index, artifact] of bundle.sourceArtifacts.entries()) {
    if (artifact.availableAt > bundle.generatedAt) {
      refinement.addIssue({ code: "custom", message: "source artifact cannot be available after bundle generation", path: ["sourceArtifacts", index, "availableAt"] });
    }
  }
  for (const [panelIndex, panel] of bundle.panels.entries()) {
    const lineages = [
      ...panel.signals.map((value) => value.lineage),
      ...panel.relations.map((value) => value.lineage),
      ...panel.marks.map((value) => value.lineage),
    ];
    for (const lineageValue of lineages) {
      const artifact = artifacts.get(lineageValue.sourceRef);
      if (!artifact) {
        refinement.addIssue({ code: "custom", message: "lineage sourceRef must close to a source artifact", path: ["panels", panelIndex] });
      } else if (lineageValue.availableAt !== artifact.availableAt) {
        refinement.addIssue({ code: "custom", message: "lineage availability must equal its source artifact availability", path: ["panels", panelIndex] });
      }
    }
  }
});

const policyReference = z.object({
  policyId: asciiIdentity,
  policyVersion: wireU64,
  assignmentId: asciiIdentity,
  policyDigest: digest,
}).strict();

const artifactReference = z.object({
  contract: asciiIdentity,
  artifactId: asciiIdentity,
  artifactDigest: digest,
}).strict();

const presentationItem = z.object({
  itemId: asciiIdentity,
  itemKind: z.enum(["shell_panel", "exploration_view", "overlay"]),
  placement: z.enum(["left", "center", "right", "overlay", "drawer"]),
  ordinal: wireU64,
  visibility: z.enum(["visible", "collapsed", "omitted"]),
  omissionReason: z.enum(["policy", "operator_filter", "unsupported", "unavailable_at_cut", "viewport_not_measured"]).nullable(),
  salience,
  pinned: z.boolean(),
  evidenceClass: presentationEvidenceClassSchema,
  safetyCritical: z.boolean(),
}).strict().superRefine((item, refinement) => {
  if ((item.visibility === "omitted") !== (item.omissionReason !== null)) {
    refinement.addIssue({ code: "custom", message: "only omitted items carry an omission reason", path: ["omissionReason"] });
  }
  if (item.safetyCritical && item.visibility === "omitted") {
    refinement.addIssue({ code: "custom", message: "safety-critical information cannot be omitted", path: ["visibility"] });
  }
});

const presentationManifest = z.object({
  eligibleItemIds: sortedIdentities().min(1),
  selectedItemIds: sortedIdentities(),
  plannedRenderItemIds: sortedIdentities(),
  plannedInitialViewportItemIds: sortedIdentities(),
  items: z.array(presentationItem).min(1).superRefine((values, refinement) => {
    requireSortedUnique(values.map((value) => value.itemId), refinement, []);
  }),
  filters: z.array(z.object({ filterId: asciiIdentity, value: exactText(240) }).strict()).superRefine((values, refinement) => {
    requireSortedUnique(values.map((value) => value.filterId), refinement, []);
  }),
  toggles: z.array(z.object({ toggleId: asciiIdentity, state: z.boolean() }).strict()).superRefine((values, refinement) => {
    requireSortedUnique(values.map((value) => value.toggleId), refinement, []);
  }),
  initialFocusItemId: asciiIdentity.nullable(),
  comparisonItemIds: sortedIdentities().max(3),
}).strict().superRefine((manifest, refinement) => {
  const eligible = new Set(manifest.eligibleItemIds);
  const selected = new Set(manifest.selectedItemIds);
  const plannedRender = new Set(manifest.plannedRenderItemIds);
  const itemMap = new Map(manifest.items.map((item) => [item.itemId, item]));
  if (itemMap.size !== eligible.size || [...eligible].some((id) => !itemMap.has(id))) {
    refinement.addIssue({ code: "custom", message: "items must exactly describe the eligible set", path: ["items"] });
  }
  for (const [field, values] of [
    ["selectedItemIds", manifest.selectedItemIds],
    ["plannedRenderItemIds", manifest.plannedRenderItemIds],
    ["plannedInitialViewportItemIds", manifest.plannedInitialViewportItemIds],
    ["comparisonItemIds", manifest.comparisonItemIds],
  ] as const) {
    if (values.some((id) => !eligible.has(id))) {
      refinement.addIssue({ code: "custom", message: "item must be eligible", path: [field] });
    }
  }
  if (manifest.selectedItemIds.some((id) => !eligible.has(id))) {
    refinement.addIssue({ code: "custom", message: "selected items must be eligible", path: ["selectedItemIds"] });
  }
  if (manifest.plannedRenderItemIds.some((id) => !selected.has(id))) {
    refinement.addIssue({ code: "custom", message: "planned render items must be selected", path: ["plannedRenderItemIds"] });
  }
  if (manifest.plannedInitialViewportItemIds.some((id) => !plannedRender.has(id))) {
    refinement.addIssue({ code: "custom", message: "planned viewport items must be planned for render", path: ["plannedInitialViewportItemIds"] });
  }
  if (manifest.comparisonItemIds.some((id) => !plannedRender.has(id))) {
    refinement.addIssue({ code: "custom", message: "compared items must be planned for render", path: ["comparisonItemIds"] });
  }
  if (manifest.initialFocusItemId !== null && !plannedRender.has(manifest.initialFocusItemId)) {
    refinement.addIssue({ code: "custom", message: "initial focus item must be planned for render", path: ["initialFocusItemId"] });
  }
  const placementOrdinals = manifest.items.map((item) => `${item.placement}\0${item.ordinal}`);
  if (new Set(placementOrdinals).size !== placementOrdinals.length) {
    refinement.addIssue({ code: "custom", message: "placement ordinals must be unique", path: ["items"] });
  }
  const expectedSelected = manifest.items.filter((item) => item.visibility !== "omitted").map((item) => item.itemId);
  if (JSON.stringify(expectedSelected) !== JSON.stringify(manifest.plannedRenderItemIds)) {
    refinement.addIssue({ code: "custom", message: "planned render IDs must exactly match non-omitted items", path: ["plannedRenderItemIds"] });
  }
  if (JSON.stringify(expectedSelected) !== JSON.stringify(manifest.selectedItemIds)) {
    refinement.addIssue({ code: "custom", message: "selected IDs must exactly match policy-selected non-omitted items", path: ["selectedItemIds"] });
  }
  const omittedWithoutReason = manifest.items.some((item) => item.visibility === "omitted" && item.omissionReason === null);
  if (omittedWithoutReason) {
    refinement.addIssue({ code: "custom", message: "every omitted eligible item needs a reason", path: ["items"] });
  }
});

export const presentationSceneV1Schema = z.object({
  contract: z.literal("joshi.presentation.scene"),
  schemaVersion: z.literal(1),
  presentationId: asciiIdentity,
  idempotencyKey: asciiIdentity,
  clientSessionId: asciiIdentity,
  presentationSeq: wireU64,
  scene: sceneReference,
  policy: policyReference,
  artifacts: z.array(artifactReference).min(1).superRefine((values, refinement) => {
    requireSortedUnique(values.map((value) => `${value.contract}\0${value.artifactId}`), refinement, []);
  }),
  manifest: presentationManifest,
  capturedAt: instant,
  clientClock,
  authorityClass: z.literal("evidence_only"),
  effectCeiling: z.literal("observe_only"),
}).strict();

export const presentationSceneAdmissionV1Schema = z.object({
  contract: z.literal("joshi.presentation.scene_admission"),
  schemaVersion: z.literal(1),
  policy: presentationPolicyV1Schema,
  explorationBundle: explorationBundleV1Schema,
  scene: presentationSceneV1Schema,
}).strict().superRefine((admission, refinement) => {
  if (
    admission.scene.policy.policyId !== admission.policy.policyId ||
    admission.scene.policy.policyVersion !== admission.policy.policyVersion ||
    admission.scene.policy.policyDigest !== digestPresentationPolicy(admission.policy)
  ) {
    refinement.addIssue({ code: "custom", message: "scene policy reference must close to the exact admitted policy", path: ["scene", "policy"] });
  }
  const bundleReference = admission.scene.artifacts.find((artifact) =>
    artifact.contract === admission.explorationBundle.contract &&
    artifact.artifactId === admission.explorationBundle.bundleId
  );
  if (!bundleReference || bundleReference.artifactDigest !== digestExplorationBundle(admission.explorationBundle)) {
    refinement.addIssue({ code: "custom", message: "scene artifact reference must close to the exact admitted exploration bundle", path: ["scene", "artifacts"] });
  }
  if (
    admission.explorationBundle.scene.sceneId !== admission.scene.scene.sceneId ||
    admission.explorationBundle.scene.viewDigest !== admission.scene.scene.viewDigest
  ) {
    refinement.addIssue({ code: "custom", message: "exploration bundle and presentation scene must share an evidence cut", path: ["explorationBundle", "scene"] });
  }
});

const presentationReference = z.object({
  presentationId: asciiIdentity,
  presentationDigest: digest,
}).strict();

const eventHead = {
  contract: z.literal("joshi.presentation.event"),
  schemaVersion: z.literal(1),
  eventId: asciiIdentity,
  idempotencyKey: asciiIdentity,
  clientSessionId: asciiIdentity,
  presentationEventSeq: wireU64,
  presentation: presentationReference,
  scene: sceneReference,
  subject: z.object({
    kind: z.enum(["panel", "overlay", "control", "presentation"]),
    key: asciiIdentity,
  }).strict(),
  occurredAt: instant,
  clientClock,
} as const;

const intervalPayload = z.object({
  reason: z.enum(["initial_reveal", "operator_navigation", "policy_change", "viewport_transition", "scene_close"]),
}).strict();

const controlPayload = z.object({
  controlKind: z.enum(["policy", "filter", "toggle", "pin", "comparison", "salience"]),
  controlId: asciiIdentity,
  previousValue: exactText(512),
  nextValue: exactText(512),
}).strict();

const usefulnessPayload = z.object({
  usefulness: z.enum(["helpful", "neutral", "harmful", "unknown"]),
  decisionLatency: z.enum(["faster", "unchanged", "slower", "unknown"]),
  attentionCost: z.enum(["lower", "unchanged", "higher", "unknown"]),
  overtrading: z.enum(["less", "unchanged", "more", "unknown"]),
  regret: z.enum(["present", "absent", "unknown"]),
  missedOpportunity: z.enum(["present", "absent", "unknown"]),
  pnl: z.object({
    status: z.enum(["not_assessed", "awaiting_reconciled_projection", "linked_reconciled_projection"]),
    projectionDigest: digest.nullable(),
  }).strict(),
  note: exactText(2_000).nullable(),
}).strict().superRefine((value, refinement) => {
  const linked = value.pnl.status === "linked_reconciled_projection";
  if (linked !== (value.pnl.projectionDigest !== null)) {
    refinement.addIssue({ code: "custom", message: "only linked reconciled PnL has a projection digest", path: ["pnl", "projectionDigest"] });
  }
});

function eventVariant<const Kind extends string, Payload extends z.ZodType>(kind: Kind, payload: Payload) {
  return z.object({
    ...eventHead,
    eventKind: z.literal(kind),
    payload,
    authorityClass: z.literal("evidence_only"),
    effectCeiling: z.literal("observe_only"),
  }).strict();
}

export const presentationEventV1Schema = z.discriminatedUnion("eventKind", [
  eventVariant("focus_started", intervalPayload),
  eventVariant("focus_ended", intervalPayload),
  eventVariant("visibility_started", intervalPayload),
  eventVariant("visibility_ended", intervalPayload),
  eventVariant("control_changed", controlPayload),
  eventVariant("voice_capture_hook", z.object({ actionId: asciiIdentity, transcript: z.null() }).strict()),
  eventVariant("usefulness_reported", usefulnessPayload),
]);

export const presentationSceneReceiptV1Schema = z.object({
  contract: z.literal("joshi.store.presentation_scene_receipt"),
  schemaVersion: z.literal(1),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  presentationId: asciiIdentity,
  idempotencyKey: asciiIdentity,
  assignmentId: asciiIdentity,
  scene: sceneReference,
  policyDigest: digest,
  presentationDigest: digest,
  commitSeq: wireU64,
  status: z.enum(["accepted", "idempotent"]),
}).strict();

export const presentationEventReceiptV1Schema = z.object({
  contract: z.literal("joshi.store.presentation_event_receipt"),
  schemaVersion: z.literal(1),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  eventId: asciiIdentity,
  presentation: presentationReference,
  scene: sceneReference,
  eventDigest: digest,
  commitSeq: wireU64,
  status: z.enum(["accepted", "idempotent"]),
}).strict();

export type PresentationPolicyV1 = z.infer<typeof presentationPolicyV1Schema>;
export type ExplorationBundleV1 = z.infer<typeof explorationBundleV1Schema>;
export type ExplorationPanel = z.infer<typeof explorationPanelSchema>;
export type PresentationSceneV1 = z.infer<typeof presentationSceneV1Schema>;
export type PresentationSceneAdmissionV1 = z.infer<typeof presentationSceneAdmissionV1Schema>;
export type PresentationEventV1 = z.infer<typeof presentationEventV1Schema>;
export type PresentationSceneReceiptV1 = z.infer<typeof presentationSceneReceiptV1Schema>;
export type PresentationEventReceiptV1 = z.infer<typeof presentationEventReceiptV1Schema>;
export type PresentationViewKind = z.infer<typeof presentationViewKindSchema>;
export type PresentationEvidenceClass = z.infer<typeof presentationEvidenceClassSchema>;

const encoder = new TextEncoder();

function digestText(value: string): string {
  return `sha256:${bytesToHex(sha256(encoder.encode(value)))}`;
}

export function canonicalPresentationPolicy(value: PresentationPolicyV1): string {
  return JSON.stringify(presentationPolicyV1Schema.parse(value));
}

export function digestPresentationPolicy(value: PresentationPolicyV1): string {
  return digestText(canonicalPresentationPolicy(value));
}

export function canonicalExplorationBundle(value: ExplorationBundleV1): string {
  return JSON.stringify(explorationBundleV1Schema.parse(value));
}

export function digestExplorationBundle(value: ExplorationBundleV1): string {
  return digestText(canonicalExplorationBundle(value));
}

export function canonicalPresentationScene(value: PresentationSceneV1): string {
  return JSON.stringify(presentationSceneV1Schema.parse(value));
}

export function canonicalPresentationSceneAdmission(
  value: PresentationSceneAdmissionV1,
): string {
  return JSON.stringify(presentationSceneAdmissionV1Schema.parse(value));
}

export function digestPresentationScene(value: PresentationSceneV1): string {
  return digestText(canonicalPresentationScene(value));
}

export function canonicalPresentationEvent(value: PresentationEventV1): string {
  return JSON.stringify(presentationEventV1Schema.parse(value));
}

export function digestPresentationEvent(value: PresentationEventV1): string {
  return digestText(canonicalPresentationEvent(value));
}

export function assertSceneReceipt(
  receipt: PresentationSceneReceiptV1,
  scene: PresentationSceneV1,
): void {
  if (receipt.presentationId !== scene.presentationId) throw new Error("presentation receipt identity mismatch");
  if (receipt.idempotencyKey !== scene.idempotencyKey) throw new Error("presentation receipt idempotency mismatch");
  if (receipt.assignmentId !== scene.policy.assignmentId) throw new Error("presentation receipt assignment mismatch");
  if (receipt.scene.sceneId !== scene.scene.sceneId || receipt.scene.viewDigest !== scene.scene.viewDigest) {
    throw new Error("presentation receipt evidence-cut mismatch");
  }
  if (receipt.policyDigest !== scene.policy.policyDigest) throw new Error("presentation receipt policy digest mismatch");
  if (receipt.presentationDigest !== digestPresentationScene(scene)) throw new Error("presentation receipt digest mismatch");
}

export function assertEventReceipt(
  receipt: PresentationEventReceiptV1,
  event: PresentationEventV1,
): void {
  if (receipt.eventId !== event.eventId) throw new Error("presentation event receipt identity mismatch");
  if (receipt.presentation.presentationId !== event.presentation.presentationId || receipt.presentation.presentationDigest !== event.presentation.presentationDigest) {
    throw new Error("presentation event receipt presentation mismatch");
  }
  if (receipt.scene.sceneId !== event.scene.sceneId || receipt.scene.viewDigest !== event.scene.viewDigest) {
    throw new Error("presentation event receipt evidence-cut mismatch");
  }
  if (receipt.eventDigest !== digestPresentationEvent(event)) throw new Error("presentation event receipt digest mismatch");
}
