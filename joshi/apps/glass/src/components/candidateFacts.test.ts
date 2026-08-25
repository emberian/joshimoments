import { describe, expect, it } from "vitest";

import type { Candidate } from "../contract/v1";
import { athProgress, chainReading, flowFor, loadableImageUri, providerClaimTitle, trueAgeSeconds } from "./candidateFacts";

function candidate(overrides: Partial<Candidate>): Candidate {
  return {
    id: "coin",
    mint: "MINT000000000001",
    symbol: null,
    name: null,
    board: "watch",
    lifecycle: "unknown",
    firstKnownAt: "2026-08-24T18:00:00.000000Z",
    lastObservedAt: null,
    rank: null,
    metrics: {
      priceSol: null,
      marketCapUsd: null,
      change5mBps: null,
      ageSeconds: null,
      activity: "unknown",
      quoteSizeSol: null,
      executableExitSol: null,
    },
    attentionReason: "Named by retained observations.",
    socialSummary: "No social source was acquired in this cut.",
    tags: [],
    watched: null,
    episodeId: null,
    evidence: [{
      id: "obs:1",
      sourceId: "pump.fun.http.v1",
      field: "mint",
      evidenceClass: "observed",
      observedAt: null,
      ingestedAt: "2026-08-24T18:00:01.000000Z",
      knownAt: "2026-08-24T18:00:02.000000Z",
      status: "available",
      note: "Named by the mock read.",
    }],
    candles: [],
    ...overrides,
  };
}

describe("true coin age", () => {
  it("is render clock minus the claimed creation clock, in whole seconds", () => {
    expect(trueAgeSeconds(candidate({ createdAtUnixMs: "1000000" }), 1_780_000)).toBe("780");
  });

  it("is null without a creation claim or without a render clock — never a guess", () => {
    expect(trueAgeSeconds(candidate({}), 1_780_000)).toBeNull();
    expect(trueAgeSeconds(candidate({ createdAtUnixMs: "1000000" }), null)).toBeNull();
  });

  it("states zero, not a countdown, when the creation clock is ahead of the render clock", () => {
    expect(trueAgeSeconds(candidate({ createdAtUnixMs: "2000000" }), 1_780_000)).toBe("0");
  });
});

describe("ATH progress", () => {
  it("is the rendered cap over the claimed high, clamped for the bar", () => {
    const halfway = athProgress(candidate({
      athMarketCapUsd: "416800.00",
      metrics: { ...candidate({}).metrics, marketCapUsd: "208400.00" },
    }));
    expect(halfway).toEqual({ ratio: 0.5, aboveClaimedAth: false });
  });

  it("survives the clamp with the above-claimed-high fact intact", () => {
    const above = athProgress(candidate({
      athMarketCapUsd: "100.00",
      metrics: { ...candidate({}).metrics, marketCapUsd: "150.00" },
    }));
    expect(above).toEqual({ ratio: 1, aboveClaimedAth: true });
  });

  it("is null when either figure is absent: no bar is invented from one number", () => {
    expect(athProgress(candidate({ athMarketCapUsd: "100.00" }))).toBeNull();
    expect(athProgress(candidate({ metrics: { ...candidate({}).metrics, marketCapUsd: "1.00" } }))).toBeNull();
  });
});

describe("flow lookup and image gating", () => {
  it("finds a named window and answers null for one the wire does not carry", () => {
    const flowing = candidate({
      flow: [{ window: "1h", volumeSol: "1.0", volumeUsd: "2.0", txns: "3", serverTsUnixMs: "4000" }],
    });
    expect(flowFor(flowing, "1h")?.volumeUsd).toBe("2.0");
    expect(flowFor(flowing, "24h")).toBeNull();
    expect(flowFor(candidate({}), "1h")).toBeNull();
  });

  it("hands an <img> only http(s) and data:image URIs; anything else falls to the monogram", () => {
    expect(loadableImageUri("https://cdn.example/coin.png")).toBe("https://cdn.example/coin.png");
    expect(loadableImageUri("data:image/svg+xml;utf8,<svg/>")).toContain("data:image/");
    expect(loadableImageUri("ipfs://bafyexample")).toBeNull();
    // eslint-disable-next-line no-script-url
    expect(loadableImageUri("javascript:alert(1)")).toBeNull();
    expect(loadableImageUri(undefined)).toBeNull();
  });
});

describe("provider claim titles", () => {
  it("carries the field's own evidence note verbatim when the view names one", () => {
    const withEvidence = candidate({});
    expect(providerClaimTitle(withEvidence, "mint", "Mint"))
      .toBe("Mint: observed (available) — Named by the mock read.");
  });

  it("falls back to the generic labelled-claim sentence, never silence", () => {
    expect(providerClaimTitle(candidate({}), "replyCount", "Claimed replies"))
      .toContain("provider claim carried verbatim");
  });
});

describe("chain reading", () => {
  it("positively claims Solana only from a solana: chainId", () => {
    expect(chainReading(candidate({ chainId: "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp" })))
      .toEqual({ kind: "solana", chainId: "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp" });
  });

  it("reads any other claim as a different venue, family from the namespace verbatim", () => {
    expect(chainReading(candidate({ chainId: "eip155:8453" })))
      .toEqual({ kind: "other", family: "eip155", chainId: "eip155:8453" });
    // A chainId with no namespace separator still yields a truncated verbatim face.
    expect(chainReading(candidate({ chainId: "mysterychain42" })))
      .toEqual({ kind: "other", family: "mysterycha", chainId: "mysterychain42" });
  });

  it("treats an absent chainId as unknown — never assumed Solana, never assumed foreign", () => {
    expect(chainReading(candidate({}))).toEqual({ kind: "unknown" });
  });
});
