import { afterEach, describe, expect, it, vi } from "vitest";

import { monotonicNanoseconds } from "./useOperatorJournal";

afterEach(() => vi.restoreAllMocks());

describe("browser monotonic command clock", () => {
  it("samples long uptime at exact microseconds before BigInt nanosecond encoding", () => {
    const longUptimeMilliseconds = 10_000_000_000.123;
    vi.spyOn(performance, "now").mockReturnValue(longUptimeMilliseconds);
    const sampledMicroseconds = Math.floor(longUptimeMilliseconds * 1_000);
    expect(Number.isSafeInteger(sampledMicroseconds)).toBe(true);

    const encoded = BigInt(monotonicNanoseconds());
    expect(encoded).toBe(BigInt(sampledMicroseconds) * 1_000n);
    expect(encoded % 1_000n).toBe(0n);
    expect(encoded).toBeGreaterThan(BigInt(Number.MAX_SAFE_INTEGER));
  });

  it("fails rather than rounding beyond the exact microsecond sampling range", () => {
    expect(() => monotonicNanoseconds(Number.MAX_SAFE_INTEGER)).toThrow(/exact microsecond/i);
    expect(() => monotonicNanoseconds(Number.POSITIVE_INFINITY)).toThrow(/finite non-negative/i);
  });
});
