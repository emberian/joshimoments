import { describe, expect, it } from "vitest";

import {
  canonicalGlassViewBytes,
  digestGlassView,
  glassSnapshotV1Schema,
  glassViewV1Schema,
  parseGlassSnapshotV1,
  type GlassViewV1,
} from "./v1";
import { mockSnapshot } from "../data/mockSnapshot";
import {
  ABSENCE_GOLDEN_VIEW_V1_DIGEST,
  ABSENCE_GOLDEN_VIEW_V1_JSON,
  GOLDEN_VIEW_V1_DIGEST,
  GOLDEN_VIEW_V1_JSON,
} from "./golden";

describe("glass snapshot v1 contract", () => {
  it("accepts one digest-bound immutable witnessed view", () => {
    const parsed = parseGlassSnapshotV1(mockSnapshot);
    expect(parsed.contract).toBe("joshi.glass.snapshot");
    expect(parsed.view.contract).toBe("joshi.glass.view");
    expect(parsed.view.mode).toBe("witnessed");
    expect(parsed.view.basisSceneId).toBeNull();
    expect(parsed.snapshotDigest).toBe(digestGlassView(parsed.view));
    expect(new TextDecoder().decode(canonicalGlassViewBytes(parsed.view))).toBe(JSON.stringify(parsed.view));
  });

  it("rejects binary-number money at the browser boundary", () => {
    const invalid = structuredClone(mockSnapshot) as unknown as {
      view: { payload: { candidates: Array<{ metrics: { priceSol: unknown } }> } };
    };
    const candidate = invalid.view.payload.candidates[0];
    if (!candidate) throw new Error("fixture candidate missing");
    candidate.metrics.priceSol = 0.00000004;
    expect(glassSnapshotV1Schema.safeParse(invalid).success).toBe(false);
  });

  it("fails closed when any hashed view field changes", () => {
    const tampered = structuredClone(mockSnapshot);
    const candidate = tampered.view.payload.candidates.find((item) => item.id === "radon");
    if (!candidate) throw new Error("RADON fixture candidate missing");
    candidate.metrics.marketCapUsd = "999999999.00";
    expect(() => parseGlassSnapshotV1(tampered)).toThrow(/digest mismatch/i);
  });

  it("recursively rejects unknown unhashed fields", () => {
    const invalid = structuredClone(mockSnapshot) as unknown as {
      view: { payload: { candidates: Array<{ metrics: Record<string, unknown> }> } };
    };
    const candidate = invalid.view.payload.candidates[0];
    if (!candidate) throw new Error("fixture candidate missing");
    candidate.metrics.futureOutcome = "must not be stripped";
    expect(() => parseGlassSnapshotV1(invalid)).toThrow(/unrecognized key/i);
  });

  it("rejects duplicate canonical identities and non-ASCII identity ordering", () => {
    const duplicate = structuredClone(mockSnapshot);
    const first = duplicate.view.payload.candidates[0];
    if (!first) throw new Error("fixture candidate missing");
    duplicate.view.payload.candidates.splice(1, 0, structuredClone(first));
    expect(() => parseGlassSnapshotV1(duplicate)).toThrow(/sorted by identity/i);

    const nonAscii = structuredClone(mockSnapshot);
    const candidate = nonAscii.view.payload.candidates[0];
    if (!candidate) throw new Error("fixture candidate missing");
    candidate.id = "éclair";
    expect(() => parseGlassSnapshotV1(nonAscii)).toThrow(/ASCII identity/i);
  });

  it.each([
    "2026-08-16T18:42:15.000Z",
    "2026-08-16T18:42:15.0000000Z",
    "2026-08-16T18:42:15.000000+00:00",
  ])("rejects non-canonical timestamp %s instead of rounding it", (timestamp) => {
    const invalid = structuredClone(mockSnapshot);
    invalid.view.asOf.renderedAt = timestamp;
    expect(() => parseGlassSnapshotV1(invalid)).toThrow(/six fractional digits/i);
  });

  it.each([
    "2023-02-29T18:42:15.000000Z",
    "2026-02-30T18:42:15.000000Z",
    "2026-02-31T18:42:15.000000Z",
    "2026-13-01T18:42:15.000000Z",
    "2026-01-00T18:42:15.000000Z",
  ])("rejects impossible snapshot calendar date %s", (timestamp) => {
    const invalidView = structuredClone(mockSnapshot.view);
    invalidView.asOf.renderedAt = timestamp;
    expect(() => glassViewV1Schema.parse(invalidView)).toThrow(/calendar timestamp/i);
  });

  it("accepts a leap-day snapshot timestamp without millisecond round-trip loss", () => {
    const validView = structuredClone(mockSnapshot.view);
    validView.asOf.renderedAt = "2024-02-29T23:59:59.123456Z";
    expect(glassViewV1Schema.parse(validView).asOf.renderedAt).toBe("2024-02-29T23:59:59.123456Z");
  });

  it.each(["253402300800", "18446744073709551615"])("rejects out-of-calendar candle Unix second %s", (timeUnix) => {
    const invalidView = structuredClone(mockSnapshot.view);
    const candle = invalidView.payload.candidates[0]?.candles[0];
    if (!candle) throw new Error("fixture candle missing");
    candle.timeUnix = timeUnix;
    expect(() => glassViewV1Schema.parse(invalidView)).toThrow(/must not exceed supported Unix second/i);
  });

  it("binds a stable canonical byte/digest golden for the Rust boundary", () => {
    const view = mockSnapshot.view;
    expect(mockSnapshot.snapshotDigest).toBe("sha256:e62064294708ff8c0470d49c561fccde7bc0146aa2be1d86651e6f5f3d7766a3");
    const goldenView = JSON.parse(GOLDEN_VIEW_V1_JSON) as typeof view;
    expect(new TextDecoder().decode(canonicalGlassViewBytes(goldenView))).toBe(GOLDEN_VIEW_V1_JSON);
    expect(digestGlassView(goldenView)).toBe(GOLDEN_VIEW_V1_DIGEST);
  });
});

describe("absence is expressible", () => {
  it("accepts a view whose every widened field is null, at the exact published digest", () => {
    const view = JSON.parse(ABSENCE_GOLDEN_VIEW_V1_JSON) as GlassViewV1;
    const parsed = glassViewV1Schema.parse(view);
    expect(new TextDecoder().decode(canonicalGlassViewBytes(parsed))).toBe(ABSENCE_GOLDEN_VIEW_V1_JSON);
    expect(digestGlassView(parsed)).toBe(ABSENCE_GOLDEN_VIEW_V1_DIGEST);

    const candidate = parsed.payload.candidates[0];
    expect(candidate?.symbol).toBeNull();
    expect(candidate?.name).toBeNull();
    expect(candidate?.lastObservedAt).toBeNull();
    expect(candidate?.rank).toBeNull();
    expect(candidate?.watched).toBeNull();
    expect(candidate?.evidence[0]?.evidenceClass).toBe("unknown");
    expect(parsed.payload.sources[0]?.status).toBe("unknown");
    const accounting = parsed.payload.episodes[0]?.accounting;
    expect(accounting?.realizedNetSol).toBeNull();
    expect(accounting?.currentExposureSol).toBeNull();
    expect(accounting?.totalSpentSol).toBeNull();
    expect(accounting?.totalProceedsSol).toBeNull();
    expect(parsed.payload.episodes[0]?.clips[0]?.realizedNetSol).toBeNull();
  });

  it("still refuses an empty string where absence must be null", () => {
    const view = JSON.parse(ABSENCE_GOLDEN_VIEW_V1_JSON) as GlassViewV1;
    const candidate = view.payload.candidates[0];
    if (candidate) candidate.symbol = "";
    expect(() => glassViewV1Schema.parse(view)).toThrow();
  });

  it("still refuses a single bar, the rule the rest of this widening was held to", () => {
    const view = JSON.parse(ABSENCE_GOLDEN_VIEW_V1_JSON) as GlassViewV1;
    const candidate = view.payload.candidates[0];
    if (candidate) {
      candidate.candles = [{
        timeUnix: "1786905720", knownAt: "2026-08-16T18:42:02.000000Z",
        open: "0.000000001", high: "0.000000002", low: "0.000000001",
        close: "0.000000002", volumeTokens: "100",
      }];
    }
    expect(() => glassViewV1Schema.parse(view)).toThrow();
  });
});
