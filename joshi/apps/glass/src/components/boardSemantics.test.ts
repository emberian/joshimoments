import { describe, expect, it } from "vitest";

import type { Candidate } from "../contract/v1";
import { mockSnapshots } from "../data/mockSnapshot";
import { applyBoardSort, boardView, DEFAULT_BOARD_SORT } from "./boardSemantics";

/** The witnessed fixture's candidates in served (identity) order, mutable for null cases. */
function served(): Candidate[] {
  return structuredClone(mockSnapshots.witnessed.view.payload.candidates) as Candidate[];
}

function ids(candidates: Candidate[]): string[] {
  return candidates.map((candidate) => candidate.id);
}

describe("board tab semantics", () => {
  it("keeps the served order under All and says that is what it is", () => {
    const ordered = served();
    const view = boardView(ordered, "all");
    expect(ids(view.candidates)).toEqual(ids(ordered));
    expect(view.basis).toMatch(/served order/i);
  });

  it("ranks New by youngest observed age", () => {
    const view = boardView(served(), "new");
    // lilypad 325s, wetpaint 440s, fable 780s are the youngest three in the fixture.
    expect(ids(view.candidates).slice(0, 3)).toEqual(["lilypad", "wetpaint", "fable"]);
    expect(view.basis).toBe("Youngest observed age first.");
  });

  it("ranks Trending by the magnitude of the 5-minute move, either direction", () => {
    const view = boardView(served(), "trending");
    expect(ids(view.candidates).slice(0, 3)).toEqual(["fable", "moss", "orbitfan"]);
    // A deep NEGATIVE move is a large move: copper at -214 bps outranks crashius at +146.
    expect(ids(view.candidates).indexOf("copper")).toBeLessThan(ids(view.candidates).indexOf("crashius"));
    expect(view.basis).toBe("Largest 5-minute move first, either direction.");
  });

  it("sends a candidate without the ranked metric to the back, in served order, and says how many", () => {
    const ordered = served();
    const lilypad = ordered.find((candidate) => candidate.id === "lilypad");
    if (!lilypad) throw new Error("fixture lost lilypad");
    lilypad.metrics.ageSeconds = null;
    const view = boardView(ordered, "new");
    // Not silently rank 0 (which would promote it to the very top as the "youngest"), and
    // not dropped: last, with the absence counted out loud.
    expect(ids(view.candidates).at(-1)).toBe("lilypad");
    expect(view.basis).toBe("Youngest observed age first · 1 without an observed age follow in served order.");
  });

  it("refuses to dress the served order up as a ranking when no candidate carries the metric", () => {
    const ordered = served();
    for (const candidate of ordered) candidate.metrics.change5mBps = null;
    const view = boardView(ordered, "trending");
    expect(ids(view.candidates)).toEqual(ids(ordered));
    expect(view.basis).toMatch(/no coin in this scene carries an observed 5-minute move/i);
    expect(view.basis).toMatch(/served order is shown/i);
  });

  it("filters the category tabs by the served board field and keeps served order", () => {
    const ordered = served();
    const live = boardView(ordered, "live");
    expect(ids(live.candidates)).toEqual(["moss"]);
    expect(live.basis).toMatch(/marks live/i);
    const watch = boardView(ordered, "watch");
    expect(ids(watch.candidates)).toEqual(["crashius", "earthcoin", "radon"]);
    expect(watch.basis).toMatch(/watch board/i);
  });
});

describe("column sort semantics (applyBoardSort)", () => {
  const renderedAtMs = Date.parse(mockSnapshots.witnessed.view.asOf.renderedAt);

  it("is a pure lens: null sort returns the tab view untouched", () => {
    const view = boardView(served(), "all");
    expect(applyBoardSort(view, "all", null, renderedAtMs)).toBe(view);
  });

  it("sorts by claimed 24h volume, exact decimals, absent coins after in prior order", () => {
    const view = applyBoardSort(boardView(served(), "all"), "all", { column: "vol24h", direction: "descending" }, renderedAtMs);
    // Flow carriers in the fixture: fable (x9), moss (x6), radon (x3), wetpaint (x1).
    expect(ids(view.candidates).slice(0, 4)).toEqual(["fable", "moss", "radon", "wetpaint"]);
    // The flow-less coins follow in the tab's (served) order, never dropped, never zeroed.
    expect(ids(view.candidates).slice(4)).toEqual(["copper", "crashius", "earthcoin", "lilypad", "orbitfan", "zorbit"]);
    expect(view.basis).toBe("Sorted by claimed 24h volume (USD), largest first · 6 without a provider-claimed 24h volume follow in prior order.");
  });

  it("sorts TRUE age from the provider creation clock against the scene's render clock", () => {
    const ascending = applyBoardSort(boardView(served(), "all"), "all", { column: "age", direction: "ascending" }, renderedAtMs);
    // Claimed creations in the fixture: wetpaint 18:34:54 is later (younger) than fable
    // 18:29:22, so wetpaint leads the ascending (youngest-first) order.
    expect(ids(ascending.candidates).slice(0, 2)).toEqual(["wetpaint", "fable"]);
    expect(ascending.basis).toContain("youngest coin first");
    // Without a render clock no true age exists for anyone: everything follows in prior
    // order and the basis says so instead of inventing an anchor.
    const unanchored = applyBoardSort(boardView(served(), "all"), "all", { column: "age", direction: "ascending" }, null);
    expect(ids(unanchored.candidates)).toEqual(ids(boardView(served(), "all").candidates));
  });

  it("keeps a category tab's filter clause in front of the sort sentence", () => {
    const view = applyBoardSort(boardView(served(), "watch"), "watch", { column: "mcap", direction: "descending" }, renderedAtMs);
    expect(view.basis).toMatch(/^Only coins on this scene's watch board · Sorted by market cap, largest first/);
    // Still only the watch coins.
    expect(ids(view.candidates).sort()).toEqual(["crashius", "earthcoin", "radon"]);
  });

  it("says out loud that a column sort overrides a sort tab's own rank", () => {
    const view = applyBoardSort(boardView(served(), "trending"), "trending", { column: "mcap", direction: "descending" }, renderedAtMs);
    expect(view.basis).toContain("overrides this tab's own rank");
    expect(ids(view.candidates)[0]).toBe("fable");
  });

  it("compares signed moves as decimals: most negative first under ascending", () => {
    const view = applyBoardSort(boardView(served(), "all"), "all", { column: "move5m", direction: "ascending" }, renderedAtMs);
    expect(ids(view.candidates)[0]).toBe("copper");
    expect(view.basis).toContain("most negative first");
  });
});

describe("the Movers default (DEFAULT_BOARD_SORT)", () => {
  const renderedAtMs = Date.parse(mockSnapshots.witnessed.view.asOf.renderedAt);

  it("leads with claimed 24h volume, then market cap, then |5m|, and states the tiers", () => {
    const view = applyBoardSort(boardView(served(), "all"), "all", DEFAULT_BOARD_SORT, renderedAtMs);
    // Tier 0 — flow carriers by claimed 24h volume: fable (x9), moss (x6), radon (x3),
    // wetpaint (x1). Tier 1 — the flowless by market cap: orbitfan 137000, earthcoin
    // 109830, copper 91360, crashius 78880, zorbit 52000, lilypad 35640. No fixture coin
    // needs tier 2. (zorbit is the multichain coin: movers ranks it like any other — the
    // VENUE SCOPE, a separate lens, is what keeps it off the default board.)
    expect(ids(view.candidates)).toEqual([
      "fable", "moss", "radon", "wetpaint",
      "orbitfan", "earthcoin", "copper", "crashius", "zorbit", "lilypad",
    ]);
    expect(view.basis).toBe(
      "Movers: largest claimed 24h volume first, then flowless coins by market cap, then by 5-minute move.",
    );
  });

  it("falls through to the 5-minute move's magnitude, and to served order for the claimless", () => {
    const ordered = served();
    for (const candidate of ordered) {
      if (candidate.id === "copper") {
        // Copper keeps only its DEEP NEGATIVE 5m move: magnitude ranks it, sign does not sink it.
        candidate.metrics.marketCapUsd = null;
      }
      if (candidate.id === "lilypad") {
        // Lilypad keeps no rankable claim at all and must fall to the back, stated.
        candidate.metrics.marketCapUsd = null;
        candidate.metrics.change5mBps = null;
      }
    }
    const view = applyBoardSort(boardView(ordered, "all"), "all", DEFAULT_BOARD_SORT, renderedAtMs);
    expect(ids(view.candidates)).toEqual([
      "fable", "moss", "radon", "wetpaint",
      "orbitfan", "earthcoin", "crashius", "zorbit",
      "copper",
      "lilypad",
    ]);
    expect(view.basis).toContain("1 without a claimed 24h volume, market cap, or 5-minute move follow in prior order");
  });
});
