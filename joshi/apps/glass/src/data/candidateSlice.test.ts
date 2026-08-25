import { afterEach, describe, expect, it, vi } from "vitest";

import { loadCandidateSlice } from "./candidateSlice";

const BASE = new URL("http://127.0.0.1:4173");

const candidate = {
  id: "walk1",
  mint: "WALKmint1111111111111111111111111111111111",
  symbol: "WALK1",
  name: "Parity Walk One",
  board: "trending",
  lifecycle: "bonding",
  firstKnownAt: "2026-08-24T17:55:00.000000Z",
  lastObservedAt: null,
  rank: "1",
  metrics: {
    priceSol: null,
    marketCapUsd: "45120.55",
    change5mBps: "312",
    ageSeconds: "540",
    activity: "two_sided",
    quoteSizeSol: null,
    executableExitSol: null,
  },
  attentionReason: "Slice client test candidate.",
  socialSummary: "No social source was acquired in this cut.",
  tags: [],
  watched: null,
  episodeId: null,
  evidence: [{
    id: "obs:walk1:01",
    sourceId: "pump.fun.http.v1",
    field: "mint",
    evidenceClass: "observed",
    observedAt: null,
    ingestedAt: "2026-08-24T18:00:01.000000Z",
    knownAt: "2026-08-24T18:00:02.000000Z",
    status: "available",
    note: "Named by the test read.",
  }],
  candles: [],
};

const slice = {
  contract: "joshi.glass.candidate_slice",
  schemaVersion: 1,
  sceneId: "scene-live-slicetest",
  viewDigest: `sha256:${"a".repeat(64)}`,
  mode: "witnessed",
  catalogCommit: "3",
  renderedAt: "2026-08-24T18:00:06.000000Z",
  renderedCandidateCount: "300",
  renderedOrdinal: "17",
  candidate,
};

function stubFetch(status: number, body: string) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
    status,
    headers: { "content-type": "application/json" },
  })));
}

describe("candidate slice client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("parses a served slice, keeping the full view digest it is traceable by", async () => {
    stubFetch(200, JSON.stringify(slice));
    const answer = await loadCandidateSlice(BASE, "scene-live-slicetest", "walk1", {});
    expect(answer.state).toBe("sliced");
    if (answer.state !== "sliced") throw new Error("expected a slice");
    expect(answer.slice.viewDigest).toBe(slice.viewDigest);
    expect(answer.slice.candidate.id).toBe("walk1");
    expect(answer.slice.renderedOrdinal).toBe("17");
  });

  /**
   * The core's render-bound statement is load-bearing: an elided candidate remains observed
   * in the catalog, and falling out of render is a bound, never a denial. The client keeps
   * those words instead of collapsing them into an error.
   */
  it("classifies candidate_not_rendered as the render bound, in the core's own words", async () => {
    stubFetch(404, JSON.stringify({
      code: "candidate_not_rendered",
      detail: "this scene renders 300 candidate(s) and none carries that id; an elided candidate remains observed in the catalog — falling out of render is a bound, never a denial",
    }));
    const answer = await loadCandidateSlice(BASE, "scene-live-slicetest", "gone", {});
    expect(answer.state).toBe("render_bound");
    if (answer.state !== "render_bound") throw new Error("expected the render bound");
    expect(answer.detail).toMatch(/a bound, never a denial/);
  });

  it("treats a bare 404 as an older core without the route, never as a failure", async () => {
    stubFetch(404, JSON.stringify({ code: "not_found" }));
    const answer = await loadCandidateSlice(BASE, "scene-live-slicetest", "walk1", {});
    expect(answer.state).toBe("unavailable");
  });

  it("refuses duplicate keys and a wrong contract without throwing at the caller", async () => {
    stubFetch(200, '{"contract":"joshi.glass.candidate_slice","contract":"joshi.glass.candidate_slice"}');
    expect((await loadCandidateSlice(BASE, "s", "c", {})).state).toBe("unavailable");
    stubFetch(200, JSON.stringify({ ...slice, contract: "joshi.glass.view" }));
    expect((await loadCandidateSlice(BASE, "s", "c", {})).state).toBe("unavailable");
  });
});
