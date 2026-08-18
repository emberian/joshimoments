import { describe, expect, it } from "vitest";

import {
  BRIDGE_PROTOCOL,
  REQUEST_FINGERPRINT_CONTRACT,
  SOURCE_CLOCK_CONTRACT,
} from "../src/constants";
import type { PageResponseAcquisition } from "../src/contracts";
import { bytesToBase64, sha256Id } from "../src/hash";
import { parityCandidateFromPageResponse } from "../src/parity";

async function observation(): Promise<PageResponseAcquisition> {
  const bytes = new TextEncoder().encode('[{"mint":"MintA"}]');
  return {
    protocol: BRIDGE_PROTOCOL,
    kind: "response-acquisition",
    acquisitionId: "40000000-0000-4000-8000-000000000011",
    pageInstanceId: "50000000-0000-4000-8000-000000000011",
    routeId: "coin-v2",
    sourceOrigin: "https://frontend-api-v3.pump.fun",
    sourcePath: "/coins-v2/MintA111111111111111111111111111111111111",
    pagePath: "/coin/MintA111111111111111111111111111111111111",
    requestedAt: "2026-08-17T12:00:00.000Z",
    capturedAt: "2026-08-17T12:00:00.012Z",
    sourceClockContract: SOURCE_CLOCK_CONTRACT,
    sequence: "7",
    requestFingerprint: `sha256:${"1".repeat(64)}`,
    requestFingerprintContract: REQUEST_FINGERPRINT_CONTRACT,
    requestProjectionCompleteness: "complete",
    parityRequestFingerprint: `sha256:${"2".repeat(64)}`,
    parityRequestFingerprintContract: "pump-parity-request-projection.v2",
    parityProjectionCompleteness: "complete",
    visibleFilterFingerprint: `sha256:${"3".repeat(64)}`,
    cursorInFingerprint: null,
    paginationKind: "none",
    pageOrdinal: "0",
    responseBlobId: await sha256Id(bytes),
    responseBytes: String(bytes.byteLength),
    responseStatus: 200,
    bodyReadAt: "2026-08-17T12:00:00.014Z",
    responseBoundary: "fetch-response-decoded-body-bytes",
    mediaType: "application/json",
    bodyBase64: bytesToBase64(bytes),
  };
}

const handoff = {
  pairId: "pair-ember-present-1",
  catalogVersion: "joshi.pump_api.catalog.2026-08-16.v1",
  sessionClass: "ordinary_authenticated" as const,
  sessionOccurrenceId: `sha256:${"4".repeat(64)}`,
  authDisposition: "ordinary_session_accepted" as const,
  rawCaptureEnabled: true,
};

describe("bounded parity handoff", () => {
  it("exports exact raw-on bytes and non-secret V2 pairing context", async () => {
    const input = await parityCandidateFromPageResponse(await observation(), handoff);
    expect(input).toMatchObject({
      contract: "joshi.pump_api.parity_input.v2",
      source: "pump_companion",
      routeId: "coin_exact",
      startedAt: "2026-08-17T12:00:00.000000Z",
      receivedAt: "2026-08-17T12:00:00.014000Z",
      renderedOrderDigest: null,
    });
    expect(JSON.stringify(input)).not.toMatch(/cookie|authorization|bearer/i);
  });

  it("refuses raw-off, incomplete request state, and changed response bytes", async () => {
    const source = await observation();
    await expect(
      parityCandidateFromPageResponse(source, { ...handoff, rawCaptureEnabled: false }),
    ).rejects.toThrow("raw-on");
    await expect(
      parityCandidateFromPageResponse(
        { ...source, parityProjectionCompleteness: "partial-query" },
        handoff,
      ),
    ).rejects.toThrow("incomplete");
    await expect(
      parityCandidateFromPageResponse({ ...source, bodyBase64: "e30=" }, handoff),
    ).rejects.toThrow("closure mismatch");
    await expect(
      parityCandidateFromPageResponse(
        { ...source, bodyReadAt: "2026-08-17T11:59:59.999Z" },
        handoff,
      ),
    ).rejects.toThrow("not causal");
  });
});
