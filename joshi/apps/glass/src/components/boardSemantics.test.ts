import { describe, expect, it } from "vitest";

import type { Candidate } from "../contract/v1";
import { mockSnapshots } from "../data/mockSnapshot";
import { boardView } from "./boardSemantics";

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
