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
    expect(mockSnapshot.snapshotDigest).toBe("sha256:113580ef81f3e748181b84fbe43a09f401c073ce6be9cd14e98f5dfa46035397");
    const goldenView = JSON.parse(GOLDEN_VIEW_V1_JSON) as typeof view;
    expect(new TextDecoder().decode(canonicalGlassViewBytes(goldenView))).toBe(GOLDEN_VIEW_V1_JSON);
    expect(digestGlassView(goldenView)).toBe(GOLDEN_VIEW_V1_DIGEST);
  });
});

describe("parity-density seam fields (PARITY_DENSITY_SEAM.md)", () => {
  const seamFields = {
    imageUri: "https://example.invalid/art/coin.png",
    description: "One thesis line.",
    replyCount: "412",
    athMarketCapUsd: "241000.55",
    athAtUnixMs: "1786904520000",
    createdAtUnixMs: "1786900595000",
    lastTradeAtUnixMs: "1786904521000",
    graduated: false,
    verified: true,
    nsfw: false,
    currentlyLive: true,
    flow: [
      { window: "5m" as const, volumeSol: "2.1", volumeUsd: "410.00", txns: "18", traders: "11", serverTsUnixMs: "1786904520000" },
      { window: "24h" as const, volumeSol: "120.5", volumeUsd: "23100.00", txns: "1180", serverTsUnixMs: "1786904520000" },
    ],
    chainId: "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
  };

  function withSeam(mutate?: (candidate: Record<string, unknown>) => void): GlassViewV1 {
    const view = structuredClone(mockSnapshot.view) as unknown as {
      payload: { candidates: Array<Record<string, unknown>> };
    };
    const candidate = view.payload.candidates.find((item) => item.id === "lilypad");
    if (!candidate) throw new Error("bare fixture candidate missing");
    Object.assign(candidate, structuredClone(seamFields));
    mutate?.(candidate);
    return view as unknown as GlassViewV1;
  }

  it("accepts every seam field and serializes them at the canonical position: after candles, in seam order", () => {
    const parsed = glassViewV1Schema.parse(withSeam());
    const candidate = parsed.payload.candidates.find((item) => item.id === "lilypad");
    if (!candidate) throw new Error("parsed candidate missing");
    expect(candidate.flow?.[1]?.traders).toBeUndefined();
    // The byte-order contract with the Rust derivation: whatever order a producer writes,
    // the canonical bytes carry these keys after `candles`, in exactly this order.
    const keys = Object.keys(candidate);
    expect(keys.slice(keys.indexOf("candles"))).toEqual([
      "candles", "imageUri", "description", "replyCount", "athMarketCapUsd", "athAtUnixMs",
      "createdAtUnixMs", "lastTradeAtUnixMs", "graduated", "verified", "nsfw", "currentlyLive",
      "flow", "chainId",
    ]);
  });

  it("still accepts the golden views that predate the seam: every field is optional", () => {
    // The pinned-digest golden test above is the byte-level proof; this is the direct claim.
    expect(glassViewV1Schema.safeParse(structuredClone(mockSnapshot.view)).success).toBe(true);
  });

  it("accepts a flow window that omits its trade and trader counts: omitted counters are absences", () => {
    // The live derivation omits `txns`/`traders` keys when the movers document states none
    // (live_surface.rs skips None); the consumer renders a dash, never a zero.
    const view = withSeam((candidate) => {
      const first = (candidate.flow as Array<Record<string, unknown>>)[0]!;
      delete first.txns;
      delete first.traders;
    });
    expect(glassViewV1Schema.safeParse(view).success).toBe(true);
  });

  it("refuses a duplicated flow window: two claims about one window is a producer defect", () => {
    const invalid = withSeam((candidate) => {
      (candidate.flow as Array<{ window: string }>).push({
        ...structuredClone(seamFields.flow[0]!),
      });
    });
    expect(() => glassViewV1Schema.parse(invalid)).toThrow(/must not repeat a flow window/i);
  });

  it("refuses an unknown flow window rather than guessing what it spans", () => {
    const invalid = withSeam((candidate) => {
      (candidate.flow as Array<{ window: string }>)[0]!.window = "6h";
    });
    expect(glassViewV1Schema.safeParse(invalid).success).toBe(false);
  });

  it("refuses an empty flow array: absent movers is an omitted field, not an empty claim", () => {
    const invalid = withSeam((candidate) => {
      candidate.flow = [];
    });
    expect(glassViewV1Schema.safeParse(invalid).success).toBe(false);
  });

  it("refuses binary-number money and counters in the seam fields", () => {
    for (const [field, value] of [["athMarketCapUsd", 241000.55], ["replyCount", 412]] as const) {
      const invalid = withSeam((candidate) => {
        candidate[field] = value;
      });
      expect(glassViewV1Schema.safeParse(invalid).success).toBe(false);
    }
  });

  it("refuses an empty description and an empty imageUri: absent is omitted, never an empty string", () => {
    for (const field of ["description", "imageUri"] as const) {
      const invalid = withSeam((candidate) => {
        candidate[field] = "";
      });
      expect(glassViewV1Schema.safeParse(invalid).success).toBe(false);
    }
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
