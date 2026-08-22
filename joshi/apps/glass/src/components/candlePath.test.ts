import { describe, expect, it } from "vitest";

import type { Candle } from "../contract/v1";
import { candlePath, compareDecimal, describeSeconds } from "./candlePath";

function bar(timeUnix: number, close: string, knownAt = "2026-08-22T01:30:00.000000Z"): Candle {
  return {
    timeUnix: String(timeUnix),
    knownAt,
    open: close,
    high: close,
    low: close,
    close,
    volumeTokens: "1",
  };
}

describe("candlePath", () => {
  it("recovers the bar spacing from the served clocks and never from an assumed interval", () => {
    // Bars at 0s, 60s, 360s: one minute of trading, then four minutes in which nothing traded.
    const path = candlePath([bar(0, "1"), bar(60, "1"), bar(360, "1")]);
    expect(path.spacingSeconds).toBe(60);
    expect(path.bars).toBe(3);
    expect(path.totalIntervals).toBe(7);
    expect(path.omittedIntervals).toBe(4);
    expect(path.gaps).toEqual([
      { index: 2, fromUnix: 60, toUnix: 360, missingSlots: 4, silenceSeconds: 300 },
    ]);
  });

  it("states the spacing as the divisor it is when no two bars are adjacent", () => {
    // Every step is 120s, which proves the interval divides 120s -- not that it is 120s. The
    // caption has to hedge, and this is the shape that forces it to.
    const path = candlePath([bar(0, "1"), bar(120, "1"), bar(240, "1")]);
    expect(path.spacingSeconds).toBe(120);
    expect(path.gaps).toEqual([]);
    expect(path.omittedIntervals).toBe(0);
  });

  it("separates the newest bar clock from the clock at which the bytes were known", () => {
    // The real hazard, from the real tap: the read completed at 01:23:12Z and the newest bar it
    // returned was stamped 01:11:13Z, because the coin simply did not trade for twelve minutes.
    const path = candlePath([
      bar(1_787_360_413, "1", "2026-08-22T01:30:00.000000Z"),
      bar(1_787_361_073, "1", "2026-08-22T01:30:00.000000Z"),
    ]);
    expect(path.newestBarUnix).toBe(1_787_361_073);
    expect(path.knownAt).toBe("2026-08-22T01:30:00.000000Z");
    // Silence measured against the knowledge clock, and reported as silence rather than staleness.
    expect(path.trailingSilenceSeconds).toBe(1_787_362_200 - 1_787_361_073);
  });

  it("reports an empty series as an absence rather than a zero-length flat market", () => {
    const path = candlePath([]);
    expect(path.bars).toBe(0);
    expect(path.spacingSeconds).toBeNull();
    expect(path.newestBarUnix).toBeNull();
    expect(path.omittedIntervals).toBe(0);
  });
});

describe("compareDecimal", () => {
  it("calls the provider's padded and trimmed spellings of one number equal", () => {
    // `open`/`close` arrive zero-padded to 28 fractional digits and `high`/`low` arrive trimmed,
    // so the same price is two different strings. A `!==` here would invent a move.
    expect(compareDecimal("0.0127543073470319645806409668", "0.01275430734703196458064096680")).toBe(0);
    expect(compareDecimal("0.0100", "0.01")).toBe(0);
    expect(compareDecimal("1", "1.000")).toBe(0);
  });

  it("keeps a difference that a float would round away", () => {
    // These two differ in the 28th fractional digit. `Number(a) === Number(b)` is true.
    const left = "0.0127543073470319645806409668";
    const right = "0.0127543073470319645806409669";
    expect(Number(left) === Number(right)).toBe(true);
    expect(compareDecimal(left, right)).toBe(-1);
    expect(compareDecimal(right, left)).toBe(1);
  });

  it("orders across the decimal point and across signs", () => {
    expect(compareDecimal("9.9", "10")).toBe(-1);
    expect(compareDecimal("-1", "1")).toBe(-1);
    expect(compareDecimal("1", "-1")).toBe(1);
    expect(compareDecimal("-2", "-1")).toBe(-1);
    // A signed zero is still zero, and must not order below an unsigned one.
    expect(compareDecimal("-0.0", "0")).toBe(0);
  });
});

describe("describeSeconds", () => {
  it("names a duration without hardcoding an interval", () => {
    expect(describeSeconds(1)).toBe("1s");
    expect(describeSeconds(60)).toBe("1m");
    expect(describeSeconds(660)).toBe("11m");
    expect(describeSeconds(3_690)).toBe("1h 1m");
  });
});
