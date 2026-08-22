import { mockSnapshots } from "../data/mockSnapshot";
import { explorationBundleFor } from "../presentation/fixtures";
import { defaultPresentationPolicy } from "../presentation/policies";
import { digestExplorationBundle, digestPresentationPolicy } from "../presentation/contract";
import {
  cockpitLaunchEnvelopeV1Schema,
  cockpitLaunchV1Schema,
  cockpitPublicationIndexV1Schema,
  digestCockpitLaunch,
  digestDurableCockpitPublication,
  digestEpisodeLaunchRegistration,
  digestEpisodeProtocolRegistration,
  durableCockpitPublicationV1Schema,
  episodeLaunchReceiptV1Schema,
  episodeLaunchRegistrationV1Schema,
  episodeProtocolReceiptV1Schema,
  episodeProtocolRegistrationV1Schema,
  sessionLaunchV1Schema,
  type CockpitLaunchEnvelopeV1,
  type CockpitPublicationIndexV1,
  type SessionLaunchV1,
} from "./contract";

const fixtureDigest = `sha256:${"5".repeat(64)}`;
const snapshot = structuredClone(mockSnapshots.witnessed);
const bundle = explorationBundleFor(snapshot);

const durableDraft = durableCockpitPublicationV1Schema.parse({
  contract: "joshi.cockpit_publication",
  schemaVersion: 1,
  catalogId: "offline-fixture-catalog",
  catalogSchema: "joshi.catalog.v1",
  batchId: "cockpit-fixture-batch-1",
  cockpitPublicationId: "cockpit-fixture-witnessed-20260816",
  sceneId: snapshot.view.sceneId,
  projectionPublicationId: "projection-fixture-20260816",
  projectionPublicationDigest: fixtureDigest,
  resultDigest: `sha256:${"6".repeat(64)}`,
  artifactDigest: `sha256:${"7".repeat(64)}`,
  manifestDigest: `sha256:${"8".repeat(64)}`,
  queryPolicy: "fixture-explicit-cut",
  commitSeq: "8000",
  supersedesCockpitPublicationId: null,
  authority: "read_only_no_execution",
  cockpitPublicationDigest: `sha256:${"0".repeat(64)}`,
});
const durablePublication = durableCockpitPublicationV1Schema.parse({
  ...durableDraft,
  cockpitPublicationDigest: digestDurableCockpitPublication(durableDraft),
});

const launch = cockpitLaunchV1Schema.parse({
  contract: "joshi.glass.cockpit_launch",
  schemaVersion: 1,
  launchId: "glass-launch-fixture-witnessed-20260816",
  publishedAt: "2026-08-16T18:42:16.000000Z",
  title: "Fixture witnessed cockpit — RADON attention cut",
  cockpitPublication: durablePublication,
  snapshot,
  presentationPolicy: defaultPresentationPolicy,
  explorationBundle: bundle,
  replayCockpitPublications: [],
  freshness: "stale",
  freshnessNote: "Deterministic offline test fixture. Never a production freshness claim.",
  authority: "read_only_no_execution",
});

export const fixtureCockpitLaunch: CockpitLaunchEnvelopeV1 = cockpitLaunchEnvelopeV1Schema.parse({
  contract: "joshi.glass.cockpit_launch_envelope",
  schemaVersion: 1,
  launchDigest: digestCockpitLaunch(launch),
  launch,
});

export const fixtureCockpitIndex: CockpitPublicationIndexV1 = cockpitPublicationIndexV1Schema.parse({
  contract: "joshi.glass.cockpit_publication_index",
  schemaVersion: 1,
  generatedAt: "2026-08-16T18:42:16.000000Z",
  publications: [{
    cockpitPublicationId: durablePublication.cockpitPublicationId,
    cockpitPublicationDigest: durablePublication.cockpitPublicationDigest,
    title: launch.title,
    publishedAt: launch.publishedAt,
    mode: snapshot.view.mode,
    scene: { sceneId: snapshot.view.sceneId, viewDigest: snapshot.snapshotDigest },
    freshness: launch.freshness,
    supersedesCockpitPublicationId: durablePublication.supersedesCockpitPublicationId,
  }],
  selection: "explicit_only_no_latest_pointer",
  authority: "read_only_no_execution",
});

export const fixtureEpisodeProtocol = episodeProtocolRegistrationV1Schema.parse({
  contract: "joshi.episode.protocol_registration",
  schemaVersion: 1,
  protocolRegistrationId: "episode-protocol-fixture-1",
  protocolDefinitionId: "episode-protocol-definition-fixture",
  protocolRevision: "1",
  buildDigest: `sha256:${"a".repeat(64)}`,
  configurationDigest: `sha256:${"b".repeat(64)}`,
  budgetDigest: `sha256:${"c".repeat(64)}`,
  privacyDigest: `sha256:${"d".repeat(64)}`,
  durationUs: "1800000000",
  warmupOffsetUs: "300000000",
  choiceDeadlineOffsetUs: "1080000000",
  outcomeHorizonOffsetUs: "3600000000",
  knowledgeDeadlineOffsetUs: "4500000000",
  authority: "read_only_no_execution",
});

export const fixtureEpisodeProtocolReceipt = episodeProtocolReceiptV1Schema.parse({
  contract: "joshi.store.episode_protocol_receipt",
  schemaVersion: 1,
  catalogId: "offline-fixture-catalog",
  catalogSchema: "joshi.catalog.v1",
  batchId: "episode-protocol-fixture-batch-1",
  protocolRegistrationId: fixtureEpisodeProtocol.protocolRegistrationId,
  protocolDefinitionId: fixtureEpisodeProtocol.protocolDefinitionId,
  protocolRevision: fixtureEpisodeProtocol.protocolRevision,
  protocolDigest: digestEpisodeProtocolRegistration(fixtureEpisodeProtocol),
  commitSeq: "7980",
  committedAt: "2026-08-17T17:58:00.000000Z",
  authority: "read_only_no_execution",
  status: "accepted",
});

const fixtureEpisodeRegistration = episodeLaunchRegistrationV1Schema.parse({
  contract: "joshi.episode.launch_registration",
  schemaVersion: 1,
  launchId: "episode-launch-fixture-1",
  protocolRegistrationId: "episode-protocol-fixture-1",
  prospectiveSessionId: "prospective-session-fixture-1",
  protocolDigest: fixtureEpisodeProtocolReceipt.protocolDigest,
  t0: "2026-08-17T18:00:00.000000Z",
  catalogCutoffCommitSeq: "7999",
  sourceReceipts: [{
    receiptId: "source-receipt-fixture-1",
    receiptDigest: `sha256:${"2".repeat(64)}`,
    throughCommitSeq: "7990",
    originatedAt: "2026-08-17T17:59:00.000000Z",
  }],
  census: { artifactId: "census-fixture-1", artifactDigest: `sha256:${"3".repeat(64)}` },
  hotScopeIntents: [{ artifactId: "hot-scope-fixture-1", artifactDigest: `sha256:${"4".repeat(64)}` }],
  projection: {
    publicationId: durablePublication.projectionPublicationId,
    publicationDigest: durablePublication.projectionPublicationDigest,
  },
  cockpit: {
    publicationId: durablePublication.cockpitPublicationId,
    publicationDigest: durablePublication.cockpitPublicationDigest,
  },
  scene: {
    sceneId: snapshot.view.sceneId,
    viewDigest: snapshot.snapshotDigest,
    capturedCommitSeq: "7970",
    sceneReceiptDigest: `sha256:${"7".repeat(64)}`,
    asOfDigest: `sha256:${"5".repeat(64)}`,
    choiceUniverseDigest: `sha256:${"6".repeat(64)}`,
    authorityClass: "evidence_only",
    effectCeiling: "observe_only",
  },
  asOfDigest: `sha256:${"5".repeat(64)}`,
  choiceUniverseDigest: `sha256:${"6".repeat(64)}`,
  choiceMembers: [
    { subjectId: "crashius", choiceUniverseDigest: `sha256:${"6".repeat(64)}`, membershipDigest: `sha256:${"8".repeat(64)}` },
    { subjectId: "earthcoin", choiceUniverseDigest: `sha256:${"6".repeat(64)}`, membershipDigest: `sha256:${"9".repeat(64)}` },
    { subjectId: "radon", choiceUniverseDigest: `sha256:${"6".repeat(64)}`, membershipDigest: `sha256:${"a".repeat(64)}` },
  ],
  presentation: {
    policyId: defaultPresentationPolicy.policyId,
    policyDigest: digestPresentationPolicy(defaultPresentationPolicy),
    bundleId: bundle.bundleId,
    bundleDigest: digestExplorationBundle(bundle),
    assignmentId: "presentation-assignment-fixture-1",
  },
  reservedPresentationId: "presentation-fixture-reserved-1",
  reservedHotDecisionId: "hot-decision-fixture-reserved-1",
  reservedHotIntentId: "hot-intent-fixture-reserved-1",
  reservedCommandId: "command-fixture-reserved-1",
  reservedCommandIdempotencyKey: "command-fixture-retry-reserved-1",
  reservedOutcomeId: "outcome-fixture-reserved-1",
  reservedInterviewId: "interview-fixture-reserved-1",
  reservedExportRequestId: "export-fixture-reserved-1",
  reservedAnalysisRunId: "analysis-fixture-reserved-1",
  reservedArtifactImportId: "artifact-import-fixture-reserved-1",
  nominationContract: "joshi.operator.prospective_nomination",
  abstentionContract: "joshi.operator.explicit_abstention",
  outcomeContract: "joshi.episode.outcome.v1",
  interviewContract: "joshi.episode.interview.v1",
  exportContract: "joshi.episode.export.v1",
  authority: "read_only_no_execution",
});

export const fixtureSessionLaunch: SessionLaunchV1 = sessionLaunchV1Schema.parse({
  contract: "joshi.glass.session_launch",
  schemaVersion: 1,
  protocol: fixtureEpisodeProtocol,
  protocolReceipt: fixtureEpisodeProtocolReceipt,
  registration: fixtureEpisodeRegistration,
  receipt: episodeLaunchReceiptV1Schema.parse({
    contract: "joshi.store.episode_launch_receipt",
    schemaVersion: 1,
    catalogId: "offline-fixture-catalog",
    catalogSchema: "joshi.catalog.v1",
    batchId: "episode-launch-fixture-batch-1",
    launchId: fixtureEpisodeRegistration.launchId,
    launchDigest: digestEpisodeLaunchRegistration(fixtureEpisodeRegistration),
    protocolRegistrationId: fixtureEpisodeRegistration.protocolRegistrationId,
    prospectiveSessionId: fixtureEpisodeRegistration.prospectiveSessionId,
    protocolDigest: fixtureEpisodeRegistration.protocolDigest,
    cockpitPublicationId: fixtureEpisodeRegistration.cockpit.publicationId,
    cockpitPublicationDigest: fixtureEpisodeRegistration.cockpit.publicationDigest,
    scene: fixtureEpisodeRegistration.scene,
    catalogCutoffCommitSeq: fixtureEpisodeRegistration.catalogCutoffCommitSeq,
    commitSeq: "8000",
    committedAt: "2026-08-17T17:59:30.000000Z",
    authority: "read_only_no_execution",
    status: "accepted",
  }),
});
