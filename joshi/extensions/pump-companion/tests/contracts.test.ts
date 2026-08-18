import { describe, expect, it } from "vitest";

import {
  BRIDGE_PROTOCOL,
  REQUEST_FINGERPRINT_CONTRACT,
  SOURCE_CLOCK_CONTRACT,
} from "../src/constants";
import { pageResponseAcquisitionSchema, sourceTimestampSchema } from "../src/contracts";

describe("source timestamp boundary", () => {
  it.each([
    "2024-02-29T23:59:59.999Z",
    "2000-02-29T00:00:00.000Z",
    "1900-02-28T12:30:45.123Z",
    "2026-04-30T00:00:00.000Z",
  ])("accepts a real Gregorian millisecond UTC instant: %s", (value) => {
    expect(sourceTimestampSchema.safeParse(value).success).toBe(true);
  });

  it.each([
    "0000-01-01T00:00:00.000Z",
    "2026-00-01T00:00:00.000Z",
    "2026-13-01T00:00:00.000Z",
    "2026-01-00T00:00:00.000Z",
    "2026-02-31T00:00:00.000Z",
    "2025-02-29T00:00:00.000Z",
    "1900-02-29T00:00:00.000Z",
    "2026-04-31T00:00:00.000Z",
    "2026-01-01T24:00:00.000Z",
    "2026-01-01T00:60:00.000Z",
    "2026-01-01T00:00:60.000Z",
    "2026-01-01T00:00:00.00Z",
    "2026-01-01T00:00:00.000+00:00",
  ])("rejects an impossible or noncanonical instant: %s", (value) => {
    expect(sourceTimestampSchema.safeParse(value).success).toBe(false);
  });

  it("rejects an impossible date in a page-delivered response acquisition", () => {
    const result = pageResponseAcquisitionSchema.safeParse({
      protocol: BRIDGE_PROTOCOL,
      kind: "response-acquisition",
      acquisitionId: "10000000-0000-4000-8000-000000000001",
      pageInstanceId: "20000000-0000-4000-8000-000000000001",
      routeId: "callout-recent",
      sourceOrigin: "https://frontend-api-v3.pump.fun",
      sourcePath: "/callout/recent",
      pagePath: "/",
      capturedAt: "2026-02-31T00:00:00.000Z",
      sourceClockContract: SOURCE_CLOCK_CONTRACT,
      sequence: "1",
      requestFingerprint: `sha256:${"1".repeat(64)}`,
      requestFingerprintContract: REQUEST_FINGERPRINT_CONTRACT,
      requestProjectionCompleteness: "complete",
      responseBlobId: `sha256:${"2".repeat(64)}`,
      responseBytes: "2",
      responseBoundary: "fetch-response-decoded-body-bytes",
      mediaType: "application/json",
      bodyBase64: "e30=",
    });
    expect(result.success).toBe(false);
  });
});
