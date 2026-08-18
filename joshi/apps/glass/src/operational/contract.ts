import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { z } from "zod";

import { exactUtcInstantSchema } from "../contract/instant";
import { glassSnapshotV1Schema, parseGlassSnapshotV1 } from "../contract/v1";
import {
  digestExplorationBundle,
  digestPresentationPolicy,
  explorationBundleV1Schema,
  presentationPolicyV1Schema,
} from "../presentation/contract";
import { OPERATIONAL_SESSION_SCOPES } from "../security/pairing";

const asciiIdentity = z.string().min(1).max(512).regex(/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/);
const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const exactText = (maximum: number) => z.string().min(1).max(maximum).refine((value) => value === value.trim(), "must not have surrounding whitespace");
const wireU64 = z.string().regex(/^(?:0|[1-9][0-9]*)$/);

const sceneReference = z.object({ sceneId: asciiIdentity, viewDigest: digest }).strict();
const durableSceneReference = z.object({
  sceneId: asciiIdentity,
  viewDigest: digest,
  capturedCommitSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  sceneReceiptDigest: digest,
  asOfDigest: digest,
  choiceUniverseDigest: digest,
  authorityClass: z.literal("evidence_only"),
  effectCeiling: z.literal("observe_only"),
}).strict();
const presentationReference = z.object({ presentationId: asciiIdentity, presentationDigest: digest }).strict();

export const pairingExchangeV1Schema = z.object({
  contract: z.literal("joshi.pairing.exchange"),
  schemaVersion: z.literal(1),
  oneTimeCode: z.string().min(6).max(128).regex(/^[A-Za-z0-9-]+$/),
}).strict();

export const pairingSessionV1Schema = z.object({
  contract: z.literal("joshi.pairing.session"),
  schemaVersion: z.literal(1),
  sessionId: asciiIdentity,
  expiresAt: exactUtcInstantSchema,
  scopes: z.tuple([
    z.literal(OPERATIONAL_SESSION_SCOPES[0]),
    z.literal(OPERATIONAL_SESSION_SCOPES[1]),
    z.literal(OPERATIONAL_SESSION_SCOPES[2]),
    z.literal(OPERATIONAL_SESSION_SCOPES[3]),
  ]),
  authority: z.literal("read_only_no_execution"),
  capability: z.string().min(32).max(512).regex(/^[A-Za-z0-9._~-]+$/),
}).strict();

const artifactReference = z.object({ artifactId: asciiIdentity, artifactDigest: digest }).strict();
const publicationReference = z.object({ publicationId: asciiIdentity, publicationDigest: digest }).strict();
const durableReceiptReference = z.object({
  receiptId: asciiIdentity,
  receiptDigest: digest,
  throughCommitSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  originatedAt: exactUtcInstantSchema,
}).strict();
const presentationPlanReference = z.object({
  policyId: asciiIdentity,
  policyDigest: digest,
  bundleId: asciiIdentity,
  bundleDigest: digest,
  assignmentId: asciiIdentity,
}).strict();
const prospectiveChoiceMember = z.object({
  subjectId: asciiIdentity,
  choiceUniverseDigest: digest,
  membershipDigest: digest,
}).strict();

export const episodeProtocolRegistrationV1Schema = z.object({
  contract: z.literal("joshi.episode.protocol_registration"),
  schemaVersion: z.literal(1),
  protocolRegistrationId: asciiIdentity,
  protocolDefinitionId: asciiIdentity,
  protocolRevision: wireU64.refine((value) => value !== "0", "must be positive"),
  buildDigest: digest,
  configurationDigest: digest,
  budgetDigest: digest,
  privacyDigest: digest,
  durationUs: wireU64,
  warmupOffsetUs: wireU64,
  choiceDeadlineOffsetUs: wireU64,
  outcomeHorizonOffsetUs: wireU64,
  knowledgeDeadlineOffsetUs: wireU64,
  authority: z.literal("read_only_no_execution"),
}).strict().superRefine((protocol, refinement) => {
  const duration = BigInt(protocol.durationUs);
  const warmup = BigInt(protocol.warmupOffsetUs);
  const choice = BigInt(protocol.choiceDeadlineOffsetUs);
  const outcome = BigInt(protocol.outcomeHorizonOffsetUs);
  const knowledge = BigInt(protocol.knowledgeDeadlineOffsetUs);
  if (duration < 1_800_000_000n || duration > 5_400_000_000n || duration % 60_000_000n !== 0n
    || warmup !== 300_000_000n || choice !== duration * 3n / 5n
    || outcome !== duration + 1_800_000_000n || knowledge !== outcome + 900_000_000n) {
    refinement.addIssue({ code: "custom", message: "protocol does not use the frozen duration/deadline formulas" });
  }
});

export const episodeProtocolReceiptV1Schema = z.object({
  contract: z.literal("joshi.store.episode_protocol_receipt"),
  schemaVersion: z.literal(1),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  protocolRegistrationId: asciiIdentity,
  protocolDefinitionId: asciiIdentity,
  protocolRevision: wireU64.refine((value) => value !== "0", "must be positive"),
  protocolDigest: digest,
  commitSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  committedAt: exactUtcInstantSchema,
  authority: z.literal("read_only_no_execution"),
  status: z.enum(["accepted", "idempotent"]),
}).strict();

export const episodeLaunchRegistrationV1Schema = z.object({
  contract: z.literal("joshi.episode.launch_registration"),
  schemaVersion: z.literal(1),
  launchId: asciiIdentity,
  protocolRegistrationId: asciiIdentity,
  prospectiveSessionId: asciiIdentity,
  protocolDigest: digest,
  t0: exactUtcInstantSchema,
  catalogCutoffCommitSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  sourceReceipts: z.array(durableReceiptReference).min(1),
  census: artifactReference,
  hotScopeIntents: z.array(artifactReference),
  projection: publicationReference,
  cockpit: publicationReference,
  scene: durableSceneReference,
  asOfDigest: digest,
  choiceUniverseDigest: digest,
  choiceMembers: z.array(prospectiveChoiceMember).min(1),
  presentation: presentationPlanReference,
  reservedPresentationId: asciiIdentity,
  reservedHotDecisionId: asciiIdentity,
  reservedHotIntentId: asciiIdentity,
  reservedCommandId: asciiIdentity,
  reservedCommandIdempotencyKey: asciiIdentity,
  reservedOutcomeId: asciiIdentity,
  reservedInterviewId: asciiIdentity,
  reservedExportRequestId: asciiIdentity,
  reservedAnalysisRunId: asciiIdentity,
  reservedArtifactImportId: asciiIdentity,
  nominationContract: z.literal("joshi.operator.prospective_nomination"),
  abstentionContract: z.literal("joshi.operator.explicit_abstention"),
  outcomeContract: asciiIdentity,
  interviewContract: asciiIdentity,
  exportContract: asciiIdentity,
  authority: z.literal("read_only_no_execution"),
}).strict().superRefine((launch, refinement) => {
  for (let index = 1; index < launch.sourceReceipts.length; index += 1) {
    if (launch.sourceReceipts[index - 1]!.receiptId >= launch.sourceReceipts[index]!.receiptId) {
      refinement.addIssue({ code: "custom", message: "source receipts must be strictly receipt-ID sorted", path: ["sourceReceipts", index] });
    }
  }
  for (const [index, receipt] of launch.sourceReceipts.entries()) {
    if (BigInt(receipt.throughCommitSeq) > BigInt(launch.catalogCutoffCommitSeq)) {
      refinement.addIssue({ code: "custom", message: "source receipt exceeds launch catalog cutoff", path: ["sourceReceipts", index, "throughCommitSeq"] });
    }
  }
  for (let index = 1; index < launch.hotScopeIntents.length; index += 1) {
    if (launch.hotScopeIntents[index - 1]!.artifactId >= launch.hotScopeIntents[index]!.artifactId) {
      refinement.addIssue({ code: "custom", message: "hot-scope intents must be strictly artifact-ID sorted", path: ["hotScopeIntents", index] });
    }
  }
  for (let index = 0; index < launch.choiceMembers.length; index += 1) {
    const member = launch.choiceMembers[index]!;
    if (member.choiceUniverseDigest !== launch.choiceUniverseDigest) {
      refinement.addIssue({ code: "custom", message: "choice member must echo the exact launch universe digest", path: ["choiceMembers", index, "choiceUniverseDigest"] });
    }
    if (index > 0 && launch.choiceMembers[index - 1]!.subjectId >= member.subjectId) {
      refinement.addIssue({ code: "custom", message: "choice members must be strictly subject-ID sorted", path: ["choiceMembers", index] });
    }
  }
  if (launch.asOfDigest !== launch.scene.asOfDigest
    || launch.choiceUniverseDigest !== launch.scene.choiceUniverseDigest) {
    refinement.addIssue({ code: "custom", message: "launch as-of and choice universe must close to the durable scene", path: ["scene"] });
  }
});

export const episodeLaunchReceiptV1Schema = z.object({
  contract: z.literal("joshi.store.episode_launch_receipt"),
  schemaVersion: z.literal(1),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  launchId: asciiIdentity,
  launchDigest: digest,
  protocolRegistrationId: asciiIdentity,
  prospectiveSessionId: asciiIdentity,
  protocolDigest: digest,
  cockpitPublicationId: asciiIdentity,
  cockpitPublicationDigest: digest,
  scene: durableSceneReference,
  catalogCutoffCommitSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  commitSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  committedAt: exactUtcInstantSchema,
  authority: z.literal("read_only_no_execution"),
  status: z.enum(["accepted", "idempotent"]),
}).strict().superRefine((receipt, refinement) => {
  if (BigInt(receipt.catalogCutoffCommitSeq) >= BigInt(receipt.commitSeq)) {
    refinement.addIssue({ code: "custom", message: "launch cutoff must precede receipt commit", path: ["commitSeq"] });
  }
});

export const sessionLaunchV1Schema = z.object({
  contract: z.literal("joshi.glass.session_launch"),
  schemaVersion: z.literal(1),
  protocol: episodeProtocolRegistrationV1Schema,
  protocolReceipt: episodeProtocolReceiptV1Schema,
  registration: episodeLaunchRegistrationV1Schema,
  receipt: episodeLaunchReceiptV1Schema,
}).strict().superRefine((sessionLaunch, refinement) => {
  try {
    assertEpisodeProtocolReceipt(sessionLaunch.protocol, sessionLaunch.protocolReceipt);
    assertEpisodeLaunchReceipt(sessionLaunch.registration, sessionLaunch.receipt);
    if (sessionLaunch.registration.protocolRegistrationId !== sessionLaunch.protocol.protocolRegistrationId
      || sessionLaunch.registration.protocolDigest !== sessionLaunch.protocolReceipt.protocolDigest
      || sessionLaunch.registration.sourceReceipts.some((receipt) => receipt.originatedAt <= sessionLaunch.protocolReceipt.committedAt)) {
      throw new Error("session launch does not close protocol receipt and post-registration source receipts");
    }
  } catch (cause) {
    refinement.addIssue({ code: "custom", message: cause instanceof Error ? cause.message : "session launch receipt mismatch", path: ["receipt"] });
  }
});

export const explicitAbstentionCommandV1Schema = z.object({
  contract: z.literal("joshi.operator.explicit_abstention"),
  schemaVersion: z.literal(1),
  abstentionId: asciiIdentity,
  idempotencyKey: asciiIdentity,
  episodeLaunchId: asciiIdentity,
  clientSessionId: asciiIdentity,
  clientCommandSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  cockpitPublicationId: asciiIdentity,
  scene: sceneReference,
  presentation: presentationReference,
  assignmentId: asciiIdentity,
  asOfDigest: digest,
  choiceUniverseDigest: digest,
  decisionDeadline: exactUtcInstantSchema,
  reason: z.enum(["no_acceptable_candidate", "insufficient_evidence", "risk_boundary", "attention_limit"]),
  issuedAt: exactUtcInstantSchema,
  clientClock: z.object({ clockId: asciiIdentity, monotonicNs: wireU64 }).strict(),
  authorityClass: z.literal("evidence_only"),
  effectCeiling: z.literal("observe_only"),
}).strict().superRefine((command, refinement) => {
  if (command.issuedAt >= command.decisionDeadline) refinement.addIssue({ code: "custom", message: "abstention was issued at or after its preregistered deadline", path: ["issuedAt"] });
});

export const explicitAbstentionReceiptV1Schema = z.object({
  contract: z.literal("joshi.store.explicit_abstention_receipt"),
  schemaVersion: z.literal(1),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  abstentionId: asciiIdentity,
  episodeLaunchId: asciiIdentity,
  scene: sceneReference,
  presentation: presentationReference,
  choiceUniverseDigest: digest,
  abstentionDigest: digest,
  commitSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  status: z.enum(["accepted", "idempotent"]),
}).strict();

const prospectiveNominationSubject = prospectiveChoiceMember;

export const prospectiveNominationCommandV1Schema = z.object({
  contract: z.literal("joshi.operator.prospective_nomination"),
  schemaVersion: z.literal(1),
  nominationId: asciiIdentity,
  idempotencyKey: asciiIdentity,
  episodeLaunchId: asciiIdentity,
  clientSessionId: asciiIdentity,
  clientCommandSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  subject: prospectiveNominationSubject,
  cockpitPublicationId: asciiIdentity,
  scene: sceneReference,
  presentation: presentationReference,
  assignmentId: asciiIdentity,
  asOfDigest: digest,
  choiceUniverseDigest: digest,
  decisionDeadline: exactUtcInstantSchema,
  issuedAt: exactUtcInstantSchema,
  clientClock: z.object({ clockId: asciiIdentity, monotonicNs: wireU64 }).strict(),
  authorityClass: z.literal("evidence_only"),
  effectCeiling: z.literal("observe_only"),
}).strict().superRefine((command, refinement) => {
  if (command.subject.choiceUniverseDigest !== command.choiceUniverseDigest) {
    refinement.addIssue({ code: "custom", message: "nomination subject must belong to the exact command choice universe", path: ["subject", "choiceUniverseDigest"] });
  }
  if (command.issuedAt >= command.decisionDeadline) {
    refinement.addIssue({ code: "custom", message: "nomination was issued at or after its preregistered deadline", path: ["issuedAt"] });
  }
});

export const prospectiveNominationReceiptV1Schema = z.object({
  contract: z.literal("joshi.store.prospective_nomination_receipt"),
  schemaVersion: z.literal(1),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  nominationId: asciiIdentity,
  episodeLaunchId: asciiIdentity,
  subject: prospectiveNominationSubject,
  scene: sceneReference,
  presentation: presentationReference,
  choiceUniverseDigest: digest,
  nominationDigest: digest,
  commitSeq: wireU64.refine((value) => value !== "0", "must be positive"),
  status: z.enum(["accepted", "idempotent"]),
}).strict();

const replayReference = z.object({
  mode: z.enum(["witnessed", "knowledge_cutoff", "retrospective"]),
  cockpitPublicationId: asciiIdentity,
  cockpitPublicationDigest: digest,
  scene: sceneReference,
}).strict();

export const durableCockpitPublicationV1Schema = z.object({
  contract: z.literal("joshi.cockpit_publication"),
  schemaVersion: z.literal(1),
  catalogId: asciiIdentity,
  catalogSchema: asciiIdentity,
  batchId: asciiIdentity,
  cockpitPublicationId: asciiIdentity,
  sceneId: asciiIdentity,
  projectionPublicationId: asciiIdentity,
  projectionPublicationDigest: digest,
  resultDigest: digest,
  artifactDigest: digest,
  manifestDigest: digest,
  queryPolicy: asciiIdentity,
  commitSeq: z.string().regex(/^(?:0|[1-9][0-9]*)$/),
  supersedesCockpitPublicationId: asciiIdentity.nullable(),
  authority: z.literal("read_only_no_execution"),
  cockpitPublicationDigest: digest,
}).strict();

export const cockpitLaunchV1Schema = z.object({
  contract: z.literal("joshi.glass.cockpit_launch"),
  schemaVersion: z.literal(1),
  launchId: asciiIdentity,
  publishedAt: exactUtcInstantSchema,
  title: exactText(160),
  cockpitPublication: durableCockpitPublicationV1Schema,
  snapshot: glassSnapshotV1Schema,
  presentationPolicy: presentationPolicyV1Schema,
  explorationBundle: explorationBundleV1Schema,
  replayCockpitPublications: z.array(replayReference).max(3),
  freshness: z.enum(["fresh", "stale", "degraded"]),
  freshnessNote: exactText(500),
  authority: z.literal("read_only_no_execution"),
}).strict().superRefine((launch, refinement) => {
  const expectedScene = launch.snapshot.view.sceneId;
  const expectedDigest = launch.snapshot.snapshotDigest;
  if (launch.cockpitPublication.sceneId !== expectedScene) {
    refinement.addIssue({ code: "custom", message: "durable cockpit publication scene must close to the exact launch snapshot", path: ["cockpitPublication", "sceneId"] });
  }
  if (launch.explorationBundle.scene.sceneId !== expectedScene || launch.explorationBundle.scene.viewDigest !== expectedDigest) {
    refinement.addIssue({ code: "custom", message: "launch bundle must share the snapshot evidence cut", path: ["explorationBundle", "scene"] });
  }
  const modes = launch.replayCockpitPublications.map((reference) => reference.mode);
  if (new Set(modes).size !== modes.length) {
    refinement.addIssue({ code: "custom", message: "replay cockpit publication modes must be unique", path: ["replayCockpitPublications"] });
  }
  if (launch.replayCockpitPublications.some((reference, index) => index > 0 && modes[index - 1]! >= reference.mode)) {
    refinement.addIssue({ code: "custom", message: "replay cockpit publications must be strictly ASCII sorted by mode", path: ["replayCockpitPublications"] });
  }
});

export const cockpitLaunchEnvelopeV1Schema = z.object({
  contract: z.literal("joshi.glass.cockpit_launch_envelope"),
  schemaVersion: z.literal(1),
  launchDigest: digest,
  launch: cockpitLaunchV1Schema,
}).strict();

export const cockpitPublicationSummaryV1Schema = z.object({
  cockpitPublicationId: asciiIdentity,
  cockpitPublicationDigest: digest,
  title: exactText(160),
  publishedAt: exactUtcInstantSchema,
  mode: z.enum(["witnessed", "knowledge_cutoff", "retrospective"]),
  scene: sceneReference,
  freshness: z.enum(["fresh", "stale", "degraded"]),
  supersedesCockpitPublicationId: asciiIdentity.nullable(),
}).strict();

export const cockpitPublicationIndexV1Schema = z.object({
  contract: z.literal("joshi.glass.cockpit_publication_index"),
  schemaVersion: z.literal(1),
  generatedAt: exactUtcInstantSchema,
  publications: z.array(cockpitPublicationSummaryV1Schema).max(500),
  selection: z.literal("explicit_only_no_latest_pointer"),
  authority: z.literal("read_only_no_execution"),
}).strict().superRefine((index, refinement) => {
  for (let offset = 1; offset < index.publications.length; offset += 1) {
    const before = index.publications[offset - 1];
    const current = index.publications[offset];
    if (before && current && before.cockpitPublicationId >= current.cockpitPublicationId) {
      refinement.addIssue({ code: "custom", message: "publication index must be strictly ASCII sorted by immutable ID", path: ["publications", offset] });
    }
  }
});

export type PairingExchangeV1 = z.infer<typeof pairingExchangeV1Schema>;
export type PairingSessionV1 = z.infer<typeof pairingSessionV1Schema>;
export type EpisodeProtocolRegistrationV1 = z.infer<typeof episodeProtocolRegistrationV1Schema>;
export type EpisodeProtocolReceiptV1 = z.infer<typeof episodeProtocolReceiptV1Schema>;
export type EpisodeLaunchRegistrationV1 = z.infer<typeof episodeLaunchRegistrationV1Schema>;
export type EpisodeLaunchReceiptV1 = z.infer<typeof episodeLaunchReceiptV1Schema>;
export type SessionLaunchV1 = z.infer<typeof sessionLaunchV1Schema>;
export type ExplicitAbstentionCommandV1 = z.infer<typeof explicitAbstentionCommandV1Schema>;
export type ExplicitAbstentionReceiptV1 = z.infer<typeof explicitAbstentionReceiptV1Schema>;
export type ProspectiveNominationCommandV1 = z.infer<typeof prospectiveNominationCommandV1Schema>;
export type ProspectiveNominationReceiptV1 = z.infer<typeof prospectiveNominationReceiptV1Schema>;
export type DurableCockpitPublicationV1 = z.infer<typeof durableCockpitPublicationV1Schema>;
export type CockpitLaunchV1 = z.infer<typeof cockpitLaunchV1Schema>;
export type CockpitLaunchEnvelopeV1 = z.infer<typeof cockpitLaunchEnvelopeV1Schema>;
export type CockpitPublicationIndexV1 = z.infer<typeof cockpitPublicationIndexV1Schema>;

const encoder = new TextEncoder();

function digestText(value: string): string {
  return `sha256:${bytesToHex(sha256(encoder.encode(value)))}`;
}

export function canonicalDurableCockpitPublicationPreimage(value: DurableCockpitPublicationV1): string {
  const parsed = durableCockpitPublicationV1Schema.parse(value);
  const { cockpitPublicationDigest: _digest, ...preimage } = parsed;
  return JSON.stringify(preimage);
}

export function digestDurableCockpitPublication(value: DurableCockpitPublicationV1): string {
  return digestText(canonicalDurableCockpitPublicationPreimage(value));
}

export function canonicalCockpitLaunch(value: CockpitLaunchV1): string {
  return JSON.stringify(cockpitLaunchV1Schema.parse(value));
}

export function digestCockpitLaunch(value: CockpitLaunchV1): string {
  return digestText(canonicalCockpitLaunch(value));
}

export function canonicalEpisodeProtocolRegistration(value: EpisodeProtocolRegistrationV1): string {
  return JSON.stringify(episodeProtocolRegistrationV1Schema.parse(value));
}

export function digestEpisodeProtocolRegistration(value: EpisodeProtocolRegistrationV1): string {
  return digestText(canonicalEpisodeProtocolRegistration(value));
}

export function canonicalEpisodeLaunchRegistration(value: EpisodeLaunchRegistrationV1): string {
  return JSON.stringify(episodeLaunchRegistrationV1Schema.parse(value));
}

export function digestEpisodeLaunchRegistration(value: EpisodeLaunchRegistrationV1): string {
  return digestText(canonicalEpisodeLaunchRegistration(value));
}

export function canonicalExplicitAbstention(value: ExplicitAbstentionCommandV1): string {
  return JSON.stringify(explicitAbstentionCommandV1Schema.parse(value));
}

export function digestExplicitAbstention(value: ExplicitAbstentionCommandV1): string {
  return digestText(canonicalExplicitAbstention(value));
}

export function canonicalProspectiveNomination(value: ProspectiveNominationCommandV1): string {
  return JSON.stringify(prospectiveNominationCommandV1Schema.parse(value));
}

export function digestProspectiveNomination(value: ProspectiveNominationCommandV1): string {
  return digestText(canonicalProspectiveNomination(value));
}

export function addExactUtcMicroseconds(instant: string, offsetUs: string): string {
  const parsed = exactUtcInstantSchema.parse(instant);
  const offset = wireU64.parse(offsetUs);
  const fractional = parsed.slice(20, 26);
  const milliseconds = Date.parse(`${parsed.slice(0, 20)}${fractional.slice(0, 3)}Z`);
  if (!Number.isSafeInteger(milliseconds)) throw new Error("UTC instant milliseconds are not exactly representable");
  const totalUs = BigInt(milliseconds) * 1_000n + BigInt(fractional.slice(3)) + BigInt(offset);
  const nextMilliseconds = totalUs / 1_000n;
  if (nextMilliseconds > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error("UTC instant addition exceeds the supported calendar");
  const suffix = (totalUs % 1_000n).toString().padStart(3, "0");
  return exactUtcInstantSchema.parse(new Date(Number(nextMilliseconds)).toISOString().replace(/\.(\d{3})Z$/, `.$1${suffix}Z`));
}

export function decisionDeadlineFor(
  protocol: EpisodeProtocolRegistrationV1,
  launch: EpisodeLaunchRegistrationV1,
): string {
  if (protocol.protocolRegistrationId !== launch.protocolRegistrationId) throw new Error("launch protocol registration mismatch");
  return addExactUtcMicroseconds(launch.t0, protocol.choiceDeadlineOffsetUs);
}

export function warmupEndsAt(
  protocol: EpisodeProtocolRegistrationV1,
  launch: EpisodeLaunchRegistrationV1,
): string {
  if (protocol.protocolRegistrationId !== launch.protocolRegistrationId) throw new Error("launch protocol registration mismatch");
  return addExactUtcMicroseconds(launch.t0, protocol.warmupOffsetUs);
}

export function parseCockpitLaunchEnvelope(value: unknown): CockpitLaunchEnvelopeV1 {
  const envelope = cockpitLaunchEnvelopeV1Schema.parse(value);
  parseGlassSnapshotV1(envelope.launch.snapshot);
  if (envelope.launch.cockpitPublication.cockpitPublicationDigest !== digestDurableCockpitPublication(envelope.launch.cockpitPublication)) {
    throw new Error("durable cockpit publication digest mismatch");
  }
  if (envelope.launchDigest !== digestCockpitLaunch(envelope.launch)) {
    throw new Error("Glass cockpit launch digest mismatch");
  }
  if (envelope.launch.presentationPolicy.policyId.length === 0 || digestPresentationPolicy(envelope.launch.presentationPolicy).length === 0) {
    throw new Error("cockpit presentation policy is invalid");
  }
  if (digestExplorationBundle(envelope.launch.explorationBundle).length === 0) {
    throw new Error("cockpit exploration bundle is invalid");
  }
  return envelope;
}

export function assertEpisodeLaunchReceipt(
  registration: EpisodeLaunchRegistrationV1,
  receipt: EpisodeLaunchReceiptV1,
): void {
  if (registration.launchId !== receipt.launchId
    || receipt.launchDigest !== digestEpisodeLaunchRegistration(registration)
    || registration.protocolRegistrationId !== receipt.protocolRegistrationId
    || registration.prospectiveSessionId !== receipt.prospectiveSessionId
    || registration.protocolDigest !== receipt.protocolDigest
    || registration.cockpit.publicationId !== receipt.cockpitPublicationId
    || registration.cockpit.publicationDigest !== receipt.cockpitPublicationDigest
    || JSON.stringify(registration.scene) !== JSON.stringify(receipt.scene)
    || registration.catalogCutoffCommitSeq !== receipt.catalogCutoffCommitSeq
    || receipt.committedAt >= registration.t0) {
    throw new Error("episode launch receipt does not close to the exact registration");
  }
}

export function assertEpisodeProtocolReceipt(
  protocol: EpisodeProtocolRegistrationV1,
  receipt: EpisodeProtocolReceiptV1,
): void {
  if (receipt.protocolRegistrationId !== protocol.protocolRegistrationId
    || receipt.protocolDefinitionId !== protocol.protocolDefinitionId
    || receipt.protocolRevision !== protocol.protocolRevision
    || receipt.protocolDigest !== digestEpisodeProtocolRegistration(protocol)) {
    throw new Error("episode protocol receipt does not close exact registration bytes");
  }
}

export function assertExplicitAbstentionReceipt(
  command: ExplicitAbstentionCommandV1,
  receipt: ExplicitAbstentionReceiptV1,
): void {
  if (receipt.abstentionId !== command.abstentionId
    || receipt.episodeLaunchId !== command.episodeLaunchId
    || receipt.scene.sceneId !== command.scene.sceneId
    || receipt.scene.viewDigest !== command.scene.viewDigest
    || receipt.presentation.presentationId !== command.presentation.presentationId
    || receipt.presentation.presentationDigest !== command.presentation.presentationDigest
    || receipt.choiceUniverseDigest !== command.choiceUniverseDigest
    || receipt.abstentionDigest !== digestExplicitAbstention(command)) {
    throw new Error("explicit abstention receipt does not close exact command bytes");
  }
}

export function assertProspectiveNominationReceipt(
  command: ProspectiveNominationCommandV1,
  receipt: ProspectiveNominationReceiptV1,
): void {
  if (receipt.nominationId !== command.nominationId
    || receipt.episodeLaunchId !== command.episodeLaunchId
    || receipt.subject.subjectId !== command.subject.subjectId
    || receipt.subject.choiceUniverseDigest !== command.subject.choiceUniverseDigest
    || receipt.subject.membershipDigest !== command.subject.membershipDigest
    || receipt.scene.sceneId !== command.scene.sceneId
    || receipt.scene.viewDigest !== command.scene.viewDigest
    || receipt.presentation.presentationId !== command.presentation.presentationId
    || receipt.presentation.presentationDigest !== command.presentation.presentationDigest
    || receipt.choiceUniverseDigest !== command.choiceUniverseDigest
    || receipt.nominationDigest !== digestProspectiveNomination(command)) {
    throw new Error("prospective nomination receipt does not close exact command bytes");
  }
}
