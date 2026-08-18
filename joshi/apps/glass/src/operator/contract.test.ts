import { describe, expect, it } from "vitest";

import {
  assertReceiptMatchesCommand,
  assertAnyReceiptMatchesCommand,
  commandReceiptV2Schema,
  commandReceiptV1Schema,
  digestOperatorCommand,
  digestOperatorPayload,
  chartInstant,
  operatorCommandV1Schema,
  operatorCommandV2Schema,
  type OperatorCommandV1,
  type OperatorCommandV2,
} from "./contract";
import {
  GOLDEN_OPERATOR_COMMAND_V1_DIGEST,
  GOLDEN_OPERATOR_COMMAND_V1_JSON,
  GOLDEN_OPERATOR_PAYLOAD_V1_DIGEST,
  GOLDEN_OPERATOR_PAYLOAD_V1_JSON,
  GOLDEN_OPERATOR_COMMAND_V2_DIGEST,
  GOLDEN_OPERATOR_COMMAND_V2_JSON,
} from "./golden";

export function validOperatorCommand(): OperatorCommandV1 {
  return operatorCommandV1Schema.parse({
    contract: "joshi.operator.command",
    schemaVersion: 1,
    commandId: "command-test-1",
    idempotencyKey: "retry-test-1",
    clientSessionId: "session-test-1",
    clientCommandSeq: "1",
    scene: {
      sceneId: "scene-test-1",
      viewDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    },
    issuedAt: "2026-08-16T18:42:18.123456Z",
    clientClock: { clockId: "browser-clock-test", monotonicNs: "99123" },
    commandKind: "record_disposition",
    subject: { kind: "candidate", key: "radon" },
    payload: {
      context: {
        uiLabel: "Record disposition",
        uiLabelVersion: "1",
        confidencePpm: "800000",
        urgency: "high",
        whyNow: "The tape changed.",
        note: "Might send; retain attention.",
      },
      disposition: "crackle then runner, provisional",
      provisional: true,
    },
    authorityClass: "evidence_only",
    effectCeiling: "observe_only",
  });
}

export function validOperatorCommandV2(): OperatorCommandV2 {
  const v1 = validOperatorCommand();
  return operatorCommandV2Schema.parse({
    ...v1,
    schemaVersion: 2,
    presentation: {
      presentationId: "presentation-test-1",
      presentationDigest: `sha256:${"b".repeat(64)}`,
      assignmentId: "assignment-test-1",
    },
    cockpitPublication: {
      cockpitPublicationId: "cockpit-test-1",
      cockpitPublicationDigest: `sha256:${"c".repeat(64)}`,
    },
  });
}

function validReceipt(command = validOperatorCommand()) {
  return commandReceiptV1Schema.parse({
    contract: "joshi.store.command_receipt",
    schemaVersion: 1,
    catalogId: "catalog-test",
    catalogSchema: "joshi.catalog.v1",
    batchId: "batch-test-1",
    commandId: command.commandId,
    commandPayloadDigest: digestOperatorPayload(command),
    commandDigest: digestOperatorCommand(command),
    scene: command.scene,
    commitSeq: "43",
    status: "accepted",
  });
}

describe("operator evidence command contract", () => {
  it("binds scene, subject, clocks, semantic payload, and zero authority", () => {
    const command = validOperatorCommand();
    expect(command.authorityClass).toBe("evidence_only");
    expect(command.effectCeiling).toBe("observe_only");
    expect(digestOperatorCommand(command)).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(() => assertReceiptMatchesCommand(validReceipt(command), command)).not.toThrow();
  });

  it("rejects unknown and economic-effect fields inside strict kind payloads", () => {
    const command = structuredClone(validOperatorCommand()) as unknown as Record<string, unknown>;
    const payload = command.payload as Record<string, unknown>;
    payload.quantityAtoms = "100";
    payload.slippageBps = "50";
    payload.transaction = "serialized-transaction";
    expect(() => operatorCommandV1Schema.parse(command)).toThrow();

    const outer = structuredClone(validOperatorCommand()) as unknown as Record<string, unknown>;
    outer.signer = "wallet";
    expect(() => operatorCommandV1Schema.parse(outer)).toThrow();

    const unsupportedKind = { ...structuredClone(validOperatorCommand()), commandKind: "buy_now", payload: {} };
    expect(() => operatorCommandV1Schema.parse(unsupportedKind)).toThrow();
  });

  it("makes a scene change alter the full command digest without changing the payload digest", () => {
    const first = validOperatorCommand();
    const second = operatorCommandV1Schema.parse({
      ...structuredClone(first),
      scene: {
        sceneId: "scene-test-2",
        viewDigest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      },
    });
    expect(digestOperatorPayload(second)).toBe(digestOperatorPayload(first));
    expect(digestOperatorCommand(second)).not.toBe(digestOperatorCommand(first));
  });

  it("rejects unit-ambiguous chart values and reversed semantic ranges", () => {
    const base = validOperatorCommand();
    const badPoint = {
      ...base,
      commandKind: "record_annotation",
      payload: {
        context: base.payload.context,
        annotationId: "annotation-1",
        chart: {
          candidateId: "radon",
          seriesId: "observed-price-sol",
          anchor: {
            anchorKind: "point",
            sampleId: "radon:1786905720",
            at: "2026-08-16T18:42:00.000000Z",
            priceSol: "0.1",
          },
        },
      },
    };
    expect(() => operatorCommandV1Schema.parse(badPoint)).toThrow();

    const reversedRange = {
      ...base,
      commandKind: "record_annotation",
      payload: {
        context: base.payload.context,
        annotationId: "annotation-2",
        chart: {
          candidateId: "radon",
          seriesId: "observed-price-sol",
          anchor: {
            anchorKind: "range",
            startSampleId: "radon:2",
            endSampleId: "radon:1",
            startAt: "2026-08-16T18:42:02.000000Z",
            endAt: "2026-08-16T18:42:01.000000Z",
          },
        },
      },
    };
    expect(() => operatorCommandV1Schema.parse(reversedRange)).toThrow(/ordered/i);
  });

  it("requires interview source-command references to be a canonical set", () => {
    const base = validOperatorCommand();
    const interview = {
      ...base,
      commandKind: "link_interview",
      payload: {
        context: base.payload.context,
        interviewId: "interview-1",
        timing: "later",
        outcomeVisibility: "hidden",
        episodeRef: { episodeId: "episode-1" },
        sourceCommandIds: ["command-b", "command-a"],
      },
    };
    expect(() => operatorCommandV1Schema.parse(interview)).toThrow(/canonical ASCII order/i);
    expect(() => operatorCommandV1Schema.parse({
      ...interview,
      payload: { ...interview.payload, sourceCommandIds: ["command-a", "command-a"] },
    })).toThrow(/unique/i);
    expect(() => operatorCommandV1Schema.parse({
      ...interview,
      payload: { ...interview.payload, sourceCommandIds: ["command-a", "command-b"] },
    })).not.toThrow();
  });

  it("rejects wrong-scene and wrong-digest receipts", () => {
    const command = validOperatorCommand();
    const wrongScene = { ...validReceipt(command), scene: { ...command.scene, sceneId: "scene-wrong" } };
    expect(() => assertReceiptMatchesCommand(commandReceiptV1Schema.parse(wrongScene), command)).toThrow(/scene/i);
    const wrongDigest = { ...validReceipt(command), commandDigest: "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff" };
    expect(() => assertReceiptMatchesCommand(commandReceiptV1Schema.parse(wrongDigest), command)).toThrow(/command digest/i);
  });

  it("pins exact TypeScript/Rust command and payload bytes", () => {
    const command = operatorCommandV1Schema.parse(JSON.parse(GOLDEN_OPERATOR_COMMAND_V1_JSON) as unknown);
    expect(JSON.stringify(command)).toBe(GOLDEN_OPERATOR_COMMAND_V1_JSON);
    expect(JSON.stringify(command.payload)).toBe(GOLDEN_OPERATOR_PAYLOAD_V1_JSON);
    expect(digestOperatorPayload(command)).toBe(GOLDEN_OPERATOR_PAYLOAD_V1_DIGEST);
    expect(digestOperatorCommand(command)).toBe(GOLDEN_OPERATOR_COMMAND_V1_DIGEST);
  });

  it("pins the exact presentation-complete V2 command and rejects incomplete receipts", () => {
    const command = operatorCommandV2Schema.parse(JSON.parse(GOLDEN_OPERATOR_COMMAND_V2_JSON) as unknown);
    expect(JSON.stringify(command)).toBe(GOLDEN_OPERATOR_COMMAND_V2_JSON);
    expect(digestOperatorCommand(command)).toBe(GOLDEN_OPERATOR_COMMAND_V2_DIGEST);
    expect(digestOperatorPayload(command)).toBe(GOLDEN_OPERATOR_PAYLOAD_V1_DIGEST);
    const receipt = commandReceiptV2Schema.parse({
      contract: "joshi.store.command_receipt",
      schemaVersion: 2,
      catalogId: "catalog-test",
      catalogSchema: "joshi.catalog.v1",
      batchId: "batch-test-2",
      commandId: command.commandId,
      commandPayloadDigest: digestOperatorPayload(command),
      commandDigest: digestOperatorCommand(command),
      scene: command.scene,
      presentation: command.presentation,
      cockpitPublication: command.cockpitPublication,
      commitSeq: "44",
      status: "accepted",
    });
    expect(() => assertAnyReceiptMatchesCommand(receipt, command)).not.toThrow();
    expect(() => commandReceiptV2Schema.parse({ ...receipt, presentation: undefined })).toThrow();
    expect(() => assertAnyReceiptMatchesCommand({ ...receipt, cockpitPublication: { ...receipt.cockpitPublication, cockpitPublicationId: "wrong" } }, command)).toThrow(/publication/i);
  });

  it.each([
    "2023-02-29T18:42:18.123456Z",
    "2026-02-30T18:42:18.123456Z",
    "2026-02-31T18:42:18.123456Z",
    "2026-13-01T18:42:18.123456Z",
    "2026-01-00T18:42:18.123456Z",
  ])("rejects impossible operator calendar date %s", (timestamp) => {
    const invalid = { ...structuredClone(validOperatorCommand()), issuedAt: timestamp };
    expect(() => operatorCommandV1Schema.parse(invalid)).toThrow(/calendar timestamp/i);
  });

  it("accepts a leap-day operator timestamp with all six microdigits intact", () => {
    const valid = { ...structuredClone(validOperatorCommand()), issuedAt: "2024-02-29T23:59:59.654321Z" };
    expect(operatorCommandV1Schema.parse(valid).issuedAt).toBe("2024-02-29T23:59:59.654321Z");
  });

  it("converts only checked Unix seconds into an exact semantic chart instant", () => {
    expect(chartInstant("253402300799")).toBe("9999-12-31T23:59:59.000000Z");
    expect(() => chartInstant("18446744073709551615")).toThrow(/must not exceed/i);
  });
});
