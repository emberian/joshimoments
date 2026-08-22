import { afterEach, describe, expect, it, vi } from "vitest";

import { LoopbackVenueReadoutSource } from "./client";
import { parseVenueReadoutV1 } from "./contract";

afterEach(() => vi.unstubAllGlobals());

const MINT = "BKdJofyhtW3sBgC8PGuXaawKHmrPjTdzxqaJfSpupump";

/**
 * The exact wire the local core serves for the live bonding curve at finalized slot 440840124.
 *
 * Copied from what `joshi-core`'s own test asserts over the retained provider bytes, so a drift
 * between the two contracts fails here rather than on her screen at three in the morning.
 */
const SERVED = {
  contract: "joshi.glass.venue_readout",
  schemaVersion: 1,
  authority: "read_record_replay_only",
  mint: MINT,
  venueKind: "Pump bonding curve",
  venueKindLabel: "pump_bonding_curve",
  venueAccount: "wrXaYnT8PBRSqigbLL3fTfHN2iYcGHCNfMwaGUKijeW",
  venueBinding: "the curve is the recomputed PDA([\"bonding-curve\", mint], Pump program) at bump 255",
  feeFloorBps: "247",
  feeFloorProbeSol: "0.001000000",
  declaredLiftBps: "800",
  breakEvenClip: {
    smallestSol: "0.000277945",
    largestSol: "0.810409517",
    smallestHurdleBps: "801",
    largestHurdleBps: "801",
  },
  feeTier: {
    marketCapSol: "29.012189574",
    rowOrdinal: "1",
    rowCount: "1",
    thresholdSol: "0.000000000",
    legBps: "125",
    belowFirstThreshold: false,
    next: { absence: "This is the top row. There is no further threshold to cross." },
  },
  pessimisticTierBranch: null,
  stateAge: {
    contextSlot: "440840124",
    requestedCommitment: "finalized",
    chainToReceipt: { absence: "The provider stated no blockTime for this slot." },
    receivedAtUnixMs: "1787371691252",
    clockId: "joshi-repository-fixture-write",
    drift: { absence: "Not measured." },
  },
  declaredCosts: "network fee 7,422 lamports per transaction x 2, declared by the operator",
  unsupported: ["the address list is a declaration, not evidence"],
};

function ok(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("loopback venue readout client", () => {
  it("refuses a non-loopback core origin", () => {
    expect(() => new LoopbackVenueReadoutSource("https://example.com")).toThrow(/loopback/i);
  });

  it("asks the mint's own route, omits ambient credentials, and parses the served contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok(SERVED));
    vi.stubGlobal("fetch", fetchMock);
    const answer = await new LoopbackVenueReadoutSource("http://127.0.0.1:8787").load(MINT);
    expect(answer.state).toBe("measured");
    if (answer.state !== "measured") throw new Error("unreachable");
    expect(answer.readout.feeFloorBps).toBe("247");
    expect(answer.readout.breakEvenClip).toEqual(SERVED.breakEvenClip);
    expect(fetchMock).toHaveBeenCalledWith(
      new URL(`http://127.0.0.1:8787/api/v1/glass/venue-readouts/${MINT}`),
      expect.objectContaining({ credentials: "omit", cache: "no-store" }),
    );
  });

  it("keeps the core's two absences apart instead of collapsing them into one blank", async () => {
    // "Nothing has been measured at all" and "this coin was not covered" are different things to
    // know, and the second must never be printed over the first.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ code: "venue_readouts_not_mounted" }), { status: 404 }),
    ));
    const unmounted = await new LoopbackVenueReadoutSource("http://127.0.0.1:8787").load(MINT);
    expect(unmounted).toEqual({
      state: "absent",
      absence: expect.stringContaining("without a venue account capture") as unknown as string,
    });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ code: "venue_readout_not_measured" }), { status: 404 }),
    ));
    const uncovered = await new LoopbackVenueReadoutSource("http://127.0.0.1:8787").load(MINT);
    expect(uncovered).toEqual({
      state: "absent",
      absence: expect.stringContaining("supports no venue readout for this mint") as unknown as string,
    });
  });

  it("reports an unpaired session as an absence rather than as an unmeasured coin", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ code: "pairing_required" }), { status: 401 }),
    ));
    const answer = await new LoopbackVenueReadoutSource("http://127.0.0.1:8787").load(MINT);
    expect(answer.state).toBe("absent");
    if (answer.state !== "absent") throw new Error("unreachable");
    expect(answer.absence).toMatch(/not paired/i);
    expect(answer.absence).toMatch(/nothing here is a claim about the coin/i);
  });

  it("refuses a served readout whose numbers are not exact decimal strings", async () => {
    // A JSON number here would already have been through a float, and a float loses digits she can
    // lose money on. The contract admits only the exact strings the core rendered.
    const numeric = { ...SERVED, feeFloorProbeSol: 0.001 };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok(numeric)));
    await expect(new LoopbackVenueReadoutSource("http://127.0.0.1:8787").load(MINT)).rejects.toThrow();
  });

  it("refuses a duplicate key rather than letting the last one win silently", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(`{"contract":"joshi.glass.venue_readout","contract":"other"}`, { status: 200 }),
    ));
    await expect(new LoopbackVenueReadoutSource("http://127.0.0.1:8787").load(MINT))
      .rejects.toThrow(/invalid venue readout JSON/i);
  });
});

describe("the served venue readout contract", () => {
  it("admits a break-even refusal as an answer, not as a missing field", () => {
    const refused = {
      ...SERVED,
      breakEvenClip: { refusal: "the fee floor alone exceeds the declared lift at every size" },
    };
    expect(parseVenueReadoutV1(refused).breakEvenClip).toEqual(refused.breakEvenClip);
  });

  it("admits a located tier row with a next threshold, and keeps its direction", () => {
    const near = {
      ...SERVED,
      feeTier: {
        marketCapSol: "42.800000000",
        rowOrdinal: "1",
        rowCount: "25",
        thresholdSol: "0.000000000",
        legBps: "125",
        belowFirstThreshold: false,
        next: {
          rowOrdinal: "2",
          thresholdSol: "420.000000000",
          gapSol: "377.200000000",
          gapBpsOfMarketCap: "88131",
          legBps: "120",
          direction: "cheaper",
        },
      },
    };
    const parsed = parseVenueReadoutV1(near);
    expect("absence" in parsed.feeTier).toBe(false);
    if ("absence" in parsed.feeTier) throw new Error("unreachable");
    expect(parsed.feeTier.rowOrdinal).toBe("1");
    expect("absence" in parsed.feeTier.next).toBe(false);
  });

  it("refuses an empty gap sentence, because an absence with no words is a blank", () => {
    const empty = { ...SERVED, feeTier: { absence: "" } };
    expect(() => parseVenueReadoutV1(empty)).toThrow();
  });
});
