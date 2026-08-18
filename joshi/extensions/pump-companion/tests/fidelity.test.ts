import { describe, expect, it } from "vitest";

import {
  BRIDGE_PROTOCOL,
  REQUEST_FINGERPRINT_CONTRACT,
  SOURCE_CLOCK_CONTRACT,
} from "../src/constants";
import { DEFAULT_CAPTURE_CONFIG, type PageResponseAcquisition } from "../src/contracts";
import { base64ToBytes, bytesToBase64, sha256Id } from "../src/hash";
import { acquisitionFromPageResponse } from "../src/pipeline";

async function source(): Promise<PageResponseAcquisition> {
  const bytes = new TextEncoder().encode(
    '{"callouts":[{"id":"private-session-item","marketCap":900719925474099312345}]}',
  );
  return {
    protocol: BRIDGE_PROTOCOL,
    kind: "response-acquisition",
    acquisitionId: "40000000-0000-4000-8000-000000000001",
    pageInstanceId: "50000000-0000-4000-8000-000000000001",
    routeId: "callout-recent",
    sourceOrigin: "https://frontend-api-v3.pump.fun",
    sourcePath: "/callout/recent",
    pagePath: "/",
    requestedAt: "2026-08-16T11:59:59.990Z",
    capturedAt: "2026-08-16T12:00:00.000Z",
    sourceClockContract: SOURCE_CLOCK_CONTRACT,
    sequence: "0",
    requestFingerprint: `sha256:${"3".repeat(64)}`,
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

describe("dual-fidelity contract", () => {
  it("marks default normalized-only capture as lossy and non-admissible exact evidence", async () => {
    const observation = await source();
    const envelope = await acquisitionFromPageResponse(
      observation,
      { ...DEFAULT_CAPTURE_CONFIG, captureEnabled: true },
      { allowRaw: true },
    );
    expect(envelope).toMatchObject({
      fidelity: "lossy-normalized-attestation",
      evidenceDisposition: "not-admissible-as-exact-observation",
      fidelityGap: { reason: "exact-source-bytes-withheld-by-user-setting" },
    });
    expect(envelope?.exactPayload).toBeUndefined();
  });

  it("raw opt-in carries unchanged exact bytes with digest/length agreement", async () => {
    const observation = await source();
    const envelope = await acquisitionFromPageResponse(
      observation,
      { ...DEFAULT_CAPTURE_CONFIG, captureEnabled: true, rawCaptureEnabled: true },
      { allowRaw: true },
    );
    expect(envelope).toMatchObject({
      fidelity: "exact-private-response-bytes",
      evidenceDisposition: "candidate-exact-private-observation",
      exactPayload: {
        protectionClass: "authenticated-private-source-evidence",
        retentionClass: "local-explicit-raw-opt-in",
      },
    });
    const payloadBytes = base64ToBytes(envelope?.exactPayload?.bodyBase64 ?? "");
    expect(String(payloadBytes.byteLength)).toBe(observation.responseBytes);
    expect(await sha256Id(payloadBytes)).toBe(observation.responseBlobId);
    expect(new TextDecoder().decode(payloadBytes)).toContain("900719925474099312345");
  });
});
