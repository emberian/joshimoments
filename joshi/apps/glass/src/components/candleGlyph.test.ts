import { describe, expect, it } from "vitest";

import type { Candle } from "../contract/v1";
import { candleGlyphSpec } from "./candleGlyph";

function candle(timeUnix: string, open: string, close: string, high: string, low: string): Candle {
  return { timeUnix, knownAt: "2026-08-24T18:00:05.000000Z", open, high, low, close, volumeTokens: "1" };
}

describe("the grid card's candle glyph", () => {
  it("refuses to invent a glyph for an absent or single-bar path", () => {
    expect(candleGlyphSpec([], 148, 44)).toBeNull();
    expect(candleGlyphSpec([candle("100", "1", "2", "2", "1")], 148, 44)).toBeNull();
  });

  it("plots x by the served bar clocks so a provider-omitted silence stays a visible hole", () => {
    // Bars at t=0,1,2 then a 9-second silence, then t=11: with time-based x the last bar sits
    // far right and the gap is empty space; index-based spacing would fraudulently compress it.
    const bars = [
      candle("100", "1.0", "1.1", "1.2", "0.9"),
      candle("101", "1.1", "1.2", "1.3", "1.0"),
      candle("102", "1.2", "1.0", "1.3", "0.9"),
      candle("111", "1.0", "1.3", "1.4", "0.9"),
    ];
    const spec = candleGlyphSpec(bars, 110, 44);
    if (spec === null) throw new Error("expected a glyph");
    expect(spec.bars).toHaveLength(4);
    const xs = spec.bars.map((bar) => bar.x);
    // Even clock spacing between the first three; then the hole.
    expect(xs[1]! - xs[0]!).toBeCloseTo(xs[2]! - xs[1]!, 1);
    expect(xs[3]! - xs[2]!).toBeCloseTo((xs[1]! - xs[0]!) * 9, 0);
    // The silence is counted, for the caption, exactly as candlePath counts it.
    expect(spec.omittedIntervals).toBe(8);
  });

  it("decides bar tone by exact decimal comparison of close versus open", () => {
    const spec = candleGlyphSpec([
      candle("100", "1.10", "1.1", "1.2", "1.0"), // equal magnitudes spelled differently
      candle("101", "1.0", "1.5", "1.6", "0.9"),
      candle("102", "1.5", "1.2", "1.6", "1.1"),
    ], 148, 44);
    if (spec === null) throw new Error("expected a glyph");
    expect(spec.bars.map((bar) => bar.tone)).toEqual(["neutral", "positive", "negative"]);
  });

  it("keeps every wick and body inside the box and bodies at least visible", () => {
    const spec = candleGlyphSpec([
      candle("100", "1.0", "1.0", "1.0", "1.0"),
      candle("101", "1.0", "1.0", "1.0", "1.0"),
    ], 148, 44);
    if (spec === null) throw new Error("expected a glyph");
    for (const bar of spec.bars) {
      expect(bar.bodyHeight).toBeGreaterThan(0);
      expect(bar.wickY1).toBeGreaterThanOrEqual(0);
      expect(bar.wickY2).toBeLessThanOrEqual(44);
      expect(bar.x).toBeGreaterThanOrEqual(0);
      expect(bar.x).toBeLessThanOrEqual(148);
    }
  });
});
