import { describe, expect, it } from "vitest";

import {
  BRIDGE_PROTOCOL,
  REQUEST_FINGERPRINT_CONTRACT,
  SOURCE_CLOCK_CONTRACT,
} from "../src/constants";
import { DEFAULT_CAPTURE_CONFIG, type PageResponseAcquisition } from "../src/contracts";
import { bytesToBase64, sha256Id } from "../src/hash";
import { acquisitionFromPageResponse, scopedGapFrom } from "../src/pipeline";

const config = {
  ...DEFAULT_CAPTURE_CONFIG,
  captureEnabled: true,
  rawCaptureEnabled: true,
};

async function pageResponse(
  acquisitionId: string,
  bodyText = '{"callouts":[{"id":"a","content":"Bearer abcdefghijklmnopqrstuvwxyz","marketCap":900719925474099312345}]}',
): Promise<PageResponseAcquisition> {
  const bytes = new TextEncoder().encode(bodyText);
  return {
    protocol: BRIDGE_PROTOCOL,
    kind: "response-acquisition",
    acquisitionId,
    pageInstanceId: "20000000-0000-4000-8000-000000000001",
    routeId: "callout-recent",
    sourceOrigin: "https://frontend-api-v3.pump.fun",
    sourcePath: "/callout/recent",
    pagePath: "/",
    requestedAt: "2026-08-16T11:59:59.990Z",
    capturedAt: "2026-08-16T12:00:00.000Z",
    sourceClockContract: SOURCE_CLOCK_CONTRACT,
    sequence: "3",
    requestFingerprint: `sha256:${"1".repeat(64)}`,
    requestFingerprintContract: REQUEST_FINGERPRINT_CONTRACT,
    requestProjectionCompleteness: "complete",
    parityRequestFingerprint: `sha256:${"4".repeat(64)}`,
    parityRequestFingerprintContract: "pump-parity-request-projection.v2",
    parityProjectionCompleteness: "complete",
    visibleFilterFingerprint: `sha256:${"5".repeat(64)}`,
    cursorInFingerprint: null,
    paginationKind: "page_token",
    pageOrdinal: "0",
    responseBlobId: await sha256Id(bytes),
    responseBytes: String(bytes.byteLength),
    responseStatus: 200,
    bodyReadAt: "2026-08-16T12:00:00.001Z",
    responseBoundary: "fetch-response-decoded-body-bytes",
    mediaType: "application/json",
    bodyBase64: bytesToBase64(bytes),
  };
}

describe("page-to-core acquisition boundary", () => {
  it("requires capture and matching route policy", async () => {
    const observation = await pageResponse("10000000-0000-4000-8000-000000000001");
    await expect(
      acquisitionFromPageResponse(observation, DEFAULT_CAPTURE_CONFIG, { allowRaw: true }),
    ).resolves.toBeNull();
  });

  it("hash-verifies exact response bytes then parses numeric lexemes losslessly", async () => {
    const observation = await pageResponse("10000000-0000-4000-8000-000000000001");
    const envelope = await acquisitionFromPageResponse(observation, config, {
      allowRaw: true,
      receivedAt: new Date("2026-08-16T12:00:01.000Z"),
    });
    expect(envelope?.acquisitionId).toBe(observation.acquisitionId);
    expect(envelope?.records).toHaveLength(1);
    expect(envelope?.records[0]?.ordinal).toBe("0");
    expect(envelope?.records[0]?.fields.marketCap).toEqual({
      encoding: "json-number-lexeme",
      value: "900719925474099312345",
    });
    expect(envelope?.records[0]?.fields.content).toEqual({
      encoding: "utf8",
      value: "[REDACTED_BEARER]",
    });
    expect(envelope?.exactPayload?.blobId).toBe(observation.responseBlobId);
    expect(envelope?.exactPayload?.bodyBase64).toBe(observation.bodyBase64);
    expect(envelope?.exactPayload?.protectionClass).toBe("authenticated-private-source-evidence");
  });

  it("does not collapse equal content acquired on distinct occasions", async () => {
    const first = await acquisitionFromPageResponse(
      await pageResponse("10000000-0000-4000-8000-000000000001"),
      config,
      { allowRaw: false },
    );
    const second = await acquisitionFromPageResponse(
      await pageResponse("10000000-0000-4000-8000-000000000002"),
      config,
      { allowRaw: false },
    );
    expect(first?.responseBlobId).toBe(second?.responseBlobId);
    expect(first?.acquisitionId).not.toBe(second?.acquisitionId);
  });

  it("turns a queue rejection into a route/time/sequence-scoped gap", async () => {
    const source = await pageResponse("10000000-0000-4000-8000-000000000003");
    const gap = scopedGapFrom(source, {
      reason: "queue-full",
      lastAcceptedSequence: "2",
      droppedRecords: "4",
      droppedBytes: "1234",
    });
    expect(gap).toMatchObject({
      routeId: "callout-recent",
      pageInstanceId: source.pageInstanceId,
      sequenceStart: "3",
      sequenceEnd: "3",
      lastAcceptedSequence: "2",
      firstResumedSequence: null,
      droppedAcquisitions: "1",
      droppedRecords: "4",
    });
  });
});
