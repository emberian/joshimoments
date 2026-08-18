import { describe, expect, it } from "vitest";
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { fixtureCockpitLaunch, fixtureCockpitIndex } from "./fixtures";
import {
  canonicalDurableCockpitPublicationPreimage,
  assertEpisodeLaunchReceipt,
  assertProspectiveNominationReceipt,
  cockpitPublicationIndexV1Schema,
  digestDurableCockpitPublication,
  digestEpisodeLaunchRegistration,
  durableCockpitPublicationV1Schema,
  episodeLaunchReceiptV1Schema,
  episodeLaunchRegistrationV1Schema,
  explicitAbstentionCommandV1Schema,
  digestProspectiveNomination,
  prospectiveNominationCommandV1Schema,
  prospectiveNominationReceiptV1Schema,
  pairingExchangeV1Schema,
  pairingSessionV1Schema,
  parseCockpitLaunchEnvelope,
  sessionLaunchV1Schema,
} from "./contract";
import {
  GOLDEN_DURABLE_COCKPIT_PREIMAGE_V1_JSON,
  GOLDEN_DURABLE_COCKPIT_V1_BYTES,
  GOLDEN_DURABLE_COCKPIT_V1_DIGEST,
  GOLDEN_DURABLE_COCKPIT_V1_JSON,
  GOLDEN_PROSPECTIVE_NOMINATION_RECEIPT_V1_DIGEST,
  GOLDEN_PROSPECTIVE_NOMINATION_RECEIPT_V1_JSON,
  GOLDEN_PROSPECTIVE_NOMINATION_V1_DIGEST,
  GOLDEN_PROSPECTIVE_NOMINATION_V1_JSON,
  GOLDEN_EPISODE_LAUNCH_V1_DIGEST,
  GOLDEN_EPISODE_PROTOCOL_V1_DIGEST,
  GOLDEN_SESSION_LAUNCH_V1_DIGEST,
} from "./golden";

function digestExact(value: string): string {
  return `sha256:${bytesToHex(sha256(new TextEncoder().encode(value)))}`;
}

describe("operational Glass exact contracts", () => {
  it("pins the exact Rust ordinary pairing request and response bytes", () => {
    const request = readFileSync(resolve(process.cwd(), "../../fixtures/pairing/exchange_request_v1.json"), "utf8").trimEnd();
    const response = readFileSync(resolve(process.cwd(), "../../fixtures/pairing/exchange_response_v1.json"), "utf8").trimEnd();
    expect(JSON.stringify(pairingExchangeV1Schema.parse(JSON.parse(request) as unknown))).toBe(request);
    expect(JSON.stringify(pairingSessionV1Schema.parse(JSON.parse(response) as unknown))).toBe(response);
  });

  it("pins the exact Rust durable cockpit publication bytes and digest preimage", () => {
    const durable = durableCockpitPublicationV1Schema.parse(JSON.parse(GOLDEN_DURABLE_COCKPIT_V1_JSON) as unknown);
    expect(JSON.stringify(durable)).toBe(GOLDEN_DURABLE_COCKPIT_V1_JSON);
    expect(new TextEncoder().encode(JSON.stringify(durable))).toHaveLength(GOLDEN_DURABLE_COCKPIT_V1_BYTES);
    expect(canonicalDurableCockpitPublicationPreimage(durable)).toBe(GOLDEN_DURABLE_COCKPIT_PREIMAGE_V1_JSON);
    expect(digestDurableCockpitPublication(durable)).toBe(GOLDEN_DURABLE_COCKPIT_V1_DIGEST);
  });

  it("pins the exact Rust prospective nomination request and receipt bytes", () => {
    const nomination = prospectiveNominationCommandV1Schema.parse(JSON.parse(GOLDEN_PROSPECTIVE_NOMINATION_V1_JSON) as unknown);
    const receipt = prospectiveNominationReceiptV1Schema.parse(JSON.parse(GOLDEN_PROSPECTIVE_NOMINATION_RECEIPT_V1_JSON) as unknown);
    expect(JSON.stringify(nomination)).toBe(GOLDEN_PROSPECTIVE_NOMINATION_V1_JSON);
    expect(JSON.stringify(receipt)).toBe(GOLDEN_PROSPECTIVE_NOMINATION_RECEIPT_V1_JSON);
    expect(digestProspectiveNomination(nomination)).toBe(GOLDEN_PROSPECTIVE_NOMINATION_V1_DIGEST);
    expect(digestExact(JSON.stringify(receipt))).toBe(GOLDEN_PROSPECTIVE_NOMINATION_RECEIPT_V1_DIGEST);
    expect(() => assertProspectiveNominationReceipt(nomination, receipt)).not.toThrow();
  });

  it("pins the exact Rust protocol, launch registration, and no-index session envelope bytes", () => {
    const exactEnvelope = readFileSync(
      resolve(process.cwd(), "../../fixtures/operational/session_launch_v1.json"),
      "utf8",
    ).trimEnd();
    const envelope = sessionLaunchV1Schema.parse(JSON.parse(exactEnvelope) as unknown);
    const exactProtocol = JSON.stringify(envelope.protocol);
    const exactLaunch = JSON.stringify(envelope.registration);
    expect(JSON.stringify(envelope)).toBe(exactEnvelope);
    expect(digestExact(exactProtocol)).toBe(GOLDEN_EPISODE_PROTOCOL_V1_DIGEST);
    expect(envelope.protocolReceipt.protocolDigest).toBe(GOLDEN_EPISODE_PROTOCOL_V1_DIGEST);
    expect(digestExact(exactLaunch)).toBe(GOLDEN_EPISODE_LAUNCH_V1_DIGEST);
    expect(envelope.receipt.launchDigest).toBe(GOLDEN_EPISODE_LAUNCH_V1_DIGEST);
    expect(digestExact(exactEnvelope)).toBe(GOLDEN_SESSION_LAUNCH_V1_DIGEST);
  });

  it("keeps the Glass launch envelope distinct and closes it to durable publication and scene truth", () => {
    expect(parseCockpitLaunchEnvelope(fixtureCockpitLaunch)).toEqual(fixtureCockpitLaunch);
    const substitutedPublication = structuredClone(fixtureCockpitLaunch);
    substitutedPublication.launch.cockpitPublication.cockpitPublicationDigest = `sha256:${"f".repeat(64)}`;
    expect(() => parseCockpitLaunchEnvelope(substitutedPublication)).toThrow(/durable cockpit publication digest/i);

    const substitutedScene = structuredClone(fixtureCockpitLaunch) as unknown as { launch: { cockpitPublication: { sceneId: string } } };
    substitutedScene.launch.cockpitPublication.sceneId = "scene-substituted";
    expect(() => parseCockpitLaunchEnvelope(substitutedScene)).toThrow(/scene/i);
  });

  it("rejects mutable-latest index semantics, duplicate IDs, and unknown session scope", () => {
    expect(cockpitPublicationIndexV1Schema.parse(fixtureCockpitIndex).selection).toBe("explicit_only_no_latest_pointer");
    expect(() => cockpitPublicationIndexV1Schema.parse({ ...fixtureCockpitIndex, selection: "latest" })).toThrow();
    expect(() => cockpitPublicationIndexV1Schema.parse({
      ...fixtureCockpitIndex,
      publications: [...fixtureCockpitIndex.publications, ...fixtureCockpitIndex.publications],
    })).toThrow(/sorted/i);
    expect(() => pairingSessionV1Schema.parse({
      contract: "joshi.pairing.session",
      schemaVersion: 1,
      sessionId: "session-test",
      origin: window.location.origin,
      epoch: "1",
      expiresAt: "2026-08-18T00:00:00.000000Z",
      scopes: ["cockpit_read", "operator_evidence_write", "presentation_evidence_write", "trade"],
      authority: "read_only_no_execution",
      capability: "jpc1_" + "a".repeat(64),
    })).toThrow();
  });

  it("closes a prospective launch receipt and keeps explicit abstention separate and evidence-only", () => {
    const registration = episodeLaunchRegistrationV1Schema.parse({
      contract: "joshi.episode.launch_registration",
      schemaVersion: 1,
      launchId: "launch-registered-1",
      protocolRegistrationId: "protocol-registration-1",
      prospectiveSessionId: "prospective-session-1",
      protocolDigest: `sha256:${"1".repeat(64)}`,
      t0: "2026-08-17T12:00:00.000000Z",
      catalogCutoffCommitSeq: "90",
      sourceReceipts: [
        { receiptId: "receipt-a", receiptDigest: `sha256:${"a".repeat(64)}`, throughCommitSeq: "80", originatedAt: "2026-08-17T11:58:00.000000Z" },
        { receiptId: "receipt-b", receiptDigest: `sha256:${"b".repeat(64)}`, throughCommitSeq: "89", originatedAt: "2026-08-17T11:59:00.000000Z" },
      ],
      census: { artifactId: "census-1", artifactDigest: `sha256:${"2".repeat(64)}` },
      hotScopeIntents: [{ artifactId: "hot-a", artifactDigest: `sha256:${"c".repeat(64)}` }],
      projection: { publicationId: "projection-1", publicationDigest: `sha256:${"3".repeat(64)}` },
      cockpit: { publicationId: "cockpit-1", publicationDigest: `sha256:${"4".repeat(64)}` },
      scene: {
        sceneId: "scene-1",
        viewDigest: `sha256:${"5".repeat(64)}`,
        capturedCommitSeq: "89",
        sceneReceiptDigest: `sha256:${"8".repeat(64)}`,
        asOfDigest: `sha256:${"d".repeat(64)}`,
        choiceUniverseDigest: `sha256:${"e".repeat(64)}`,
        authorityClass: "evidence_only",
        effectCeiling: "observe_only",
      },
      asOfDigest: `sha256:${"d".repeat(64)}`,
      choiceUniverseDigest: `sha256:${"e".repeat(64)}`,
      choiceMembers: [{ subjectId: "radon", choiceUniverseDigest: `sha256:${"e".repeat(64)}`, membershipDigest: `sha256:${"f".repeat(64)}` }],
      presentation: {
        policyId: "policy-1",
        policyDigest: `sha256:${"6".repeat(64)}`,
        bundleId: "bundle-1",
        bundleDigest: `sha256:${"7".repeat(64)}`,
        assignmentId: "assignment-1",
      },
      reservedPresentationId: "presentation-reserved-1",
      reservedHotDecisionId: "hot-decision-reserved-1",
      reservedHotIntentId: "hot-intent-reserved-1",
      reservedCommandId: "command-reserved-1",
      reservedCommandIdempotencyKey: "command-retry-reserved-1",
      reservedOutcomeId: "outcome-reserved-1",
      reservedInterviewId: "interview-reserved-1",
      reservedExportRequestId: "export-reserved-1",
      reservedAnalysisRunId: "analysis-reserved-1",
      reservedArtifactImportId: "artifact-import-reserved-1",
      nominationContract: "joshi.operator.prospective_nomination",
      abstentionContract: "joshi.operator.explicit_abstention",
      outcomeContract: "joshi.episode.outcome.v1",
      interviewContract: "joshi.episode.interview.v1",
      exportContract: "joshi.episode.export.v1",
      authority: "read_only_no_execution",
    });
    const receipt = episodeLaunchReceiptV1Schema.parse({
      contract: "joshi.store.episode_launch_receipt",
      schemaVersion: 1,
      catalogId: "catalog-1",
      catalogSchema: "joshi.sqlite.v7",
      batchId: "batch-launch-1",
      launchId: registration.launchId,
      launchDigest: digestEpisodeLaunchRegistration(registration),
      protocolRegistrationId: registration.protocolRegistrationId,
      prospectiveSessionId: registration.prospectiveSessionId,
      protocolDigest: registration.protocolDigest,
      cockpitPublicationId: registration.cockpit.publicationId,
      cockpitPublicationDigest: registration.cockpit.publicationDigest,
      scene: registration.scene,
      catalogCutoffCommitSeq: registration.catalogCutoffCommitSeq,
      commitSeq: "91",
      committedAt: "2026-08-17T11:59:30.000000Z",
      authority: "read_only_no_execution",
      status: "accepted",
    });
    expect(() => assertEpisodeLaunchReceipt(registration, receipt)).not.toThrow();
    expect(() => assertEpisodeLaunchReceipt(registration, { ...receipt, cockpitPublicationId: "cockpit-other" })).toThrow(/registration/i);

    const abstention = explicitAbstentionCommandV1Schema.parse({
      contract: "joshi.operator.explicit_abstention",
      schemaVersion: 1,
      abstentionId: registration.reservedCommandId,
      idempotencyKey: registration.reservedCommandIdempotencyKey,
      episodeLaunchId: registration.launchId,
      clientSessionId: "session-1",
      clientCommandSeq: "1",
      cockpitPublicationId: registration.cockpit.publicationId,
      scene: { sceneId: registration.scene.sceneId, viewDigest: registration.scene.viewDigest },
      presentation: { presentationId: registration.reservedPresentationId, presentationDigest: `sha256:${"9".repeat(64)}` },
      assignmentId: registration.presentation.assignmentId,
      asOfDigest: registration.asOfDigest,
      choiceUniverseDigest: registration.choiceUniverseDigest,
      decisionDeadline: "2026-08-17T12:06:00.000000Z",
      reason: "insufficient_evidence",
      issuedAt: "2026-08-17T12:05:59.999999Z",
      clientClock: { clockId: "clock-1", monotonicNs: "999000" },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    expect(abstention).not.toHaveProperty("quantity");
    expect(() => explicitAbstentionCommandV1Schema.parse({ ...abstention, reason: "did_not_click" })).toThrow();
    expect(() => explicitAbstentionCommandV1Schema.parse({ ...abstention, issuedAt: "2026-08-17T12:06:00.000001Z" })).toThrow(/deadline/i);
    expect(() => explicitAbstentionCommandV1Schema.parse({ ...abstention, issuedAt: abstention.decisionDeadline })).toThrow(/deadline/i);

    const nomination = prospectiveNominationCommandV1Schema.parse({
      contract: "joshi.operator.prospective_nomination",
      schemaVersion: 1,
      nominationId: registration.reservedCommandId,
      idempotencyKey: registration.reservedCommandIdempotencyKey,
      episodeLaunchId: registration.launchId,
      clientSessionId: "session-1",
      clientCommandSeq: "1",
      subject: registration.choiceMembers[0],
      cockpitPublicationId: registration.cockpit.publicationId,
      scene: { sceneId: registration.scene.sceneId, viewDigest: registration.scene.viewDigest },
      presentation: { presentationId: registration.reservedPresentationId, presentationDigest: `sha256:${"9".repeat(64)}` },
      assignmentId: registration.presentation.assignmentId,
      asOfDigest: registration.asOfDigest,
      choiceUniverseDigest: registration.choiceUniverseDigest,
      decisionDeadline: "2026-08-17T12:06:00.000000Z",
      issuedAt: "2026-08-17T12:05:59.999999Z",
      clientClock: { clockId: "clock-2", monotonicNs: "1000000" },
      authorityClass: "evidence_only",
      effectCeiling: "observe_only",
    });
    const nominationReceipt = prospectiveNominationReceiptV1Schema.parse({
      contract: "joshi.store.prospective_nomination_receipt",
      schemaVersion: 1,
      catalogId: "catalog-1",
      catalogSchema: "joshi.sqlite.v7",
      batchId: "batch-nomination-1",
      nominationId: nomination.nominationId,
      episodeLaunchId: nomination.episodeLaunchId,
      subject: nomination.subject,
      scene: nomination.scene,
      presentation: nomination.presentation,
      choiceUniverseDigest: nomination.choiceUniverseDigest,
      nominationDigest: digestProspectiveNomination(nomination),
      commitSeq: "92",
      status: "accepted",
    });
    expect(() => assertProspectiveNominationReceipt(nomination, nominationReceipt)).not.toThrow();
    expect(() => prospectiveNominationCommandV1Schema.parse({ ...nomination, subject: { ...nomination.subject, choiceUniverseDigest: `sha256:${"0".repeat(64)}` } })).toThrow(/universe/i);
    expect(() => assertProspectiveNominationReceipt(nomination, { ...nominationReceipt, subject: { ...nomination.subject, membershipDigest: `sha256:${"0".repeat(64)}` } })).toThrow(/exact command/i);
  });
});
