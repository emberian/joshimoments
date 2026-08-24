import { describe, expect, it } from "vitest";

import type { Candle } from "../contract/v1";
import { SPARKLINE_WIDTH, sparklineSpec } from "./sparkline";

function candle(timeUnix: string, close: string): Candle {
  return {
    timeUnix,
    knownAt: "2026-08-19T21:48:41.000000Z",
    open: close,
    high: close,
    low: close,
    close,
    volumeTokens: "1000",
  };
}

describe("board sparkline", () => {
  it("draws nothing for a candidate without a price path", () => {
    // The contract serves zero candles or at least two; neither shape is a path to invent.
    expect(sparklineSpec([])).toBeNull();
  });

  it("plots x by the served bar clocks, not by array index", () => {
    // Three bars: two adjacent, then a long silence. Index spacing would put the middle
    // point at half the width and silently stretch the silent stretch into nothing.
    const spec = sparklineSpec([
      candle("1000", "0.10"),
      candle("1030", "0.20"),
      candle("1600", "0.30"),
    ]);
    if (!spec) throw new Error("expected a path");
    const xs = spec.points.split(" ").map((point) => Number(point.split(",")[0]));
    expect(xs[0]).toBe(0);
    expect(xs[1]).toBeCloseTo(((1030 - 1000) / 600) * SPARKLINE_WIDTH, 1);
    expect(xs[2]).toBeCloseTo(SPARKLINE_WIDTH, 1);
  });

  it("decides tone by exact decimal comparison of first and last closes", () => {
    const up = sparklineSpec([candle("0", "0.10"), candle("30", "0.20")]);
    const down = sparklineSpec([candle("0", "0.20"), candle("30", "0.10")]);
    // The provider zero-pads one field and trims another, so "0.10" and "0.1" are the same
    // number; float subtraction is not consulted and neither is string equality.
    const flat = sparklineSpec([candle("0", "0.10"), candle("30", "0.1")]);
    expect(up?.tone).toBe("positive");
    expect(down?.tone).toBe("negative");
    expect(flat?.tone).toBe("neutral");
  });
});
