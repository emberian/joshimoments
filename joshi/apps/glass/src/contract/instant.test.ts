import { describe, expect, it } from "vitest";

import {
  exactUnixSecondsSchema,
  exactUtcInstantSchema,
  isExactUtcInstant,
  MAX_SUPPORTED_UNIX_SECONDS,
  unixSecondsToNumber,
} from "./instant";

describe("exact UTC wire calendar validation", () => {
  it.each([
    "2024-02-29T23:59:59.123456Z",
    "2000-02-29T00:00:00.000000Z",
    "2026-12-31T18:42:18.000001Z",
  ])("accepts exact valid instant %s without losing microdigits", (value) => {
    expect(isExactUtcInstant(value)).toBe(true);
    expect(exactUtcInstantSchema.parse(value)).toBe(value);
  });

  it.each([
    "2023-02-29T18:42:18.123456Z",
    "1900-02-29T18:42:18.123456Z",
    "2026-02-30T18:42:18.123456Z",
    "2026-02-31T18:42:18.123456Z",
    "2026-13-01T18:42:18.123456Z",
    "2026-01-00T18:42:18.123456Z",
    "2026-01-01T24:00:00.123456Z",
    "2026-01-01T23:60:00.123456Z",
    "2026-01-01T23:59:60.123456Z",
  ])("rejects impossible calendar instant %s instead of normalizing it", (value) => {
    expect(isExactUtcInstant(value)).toBe(false);
    expect(() => exactUtcInstantSchema.parse(value)).toThrow(/calendar timestamp/i);
  });

  it("bounds Unix seconds to the same four-digit UTC calendar and converts through BigInt", () => {
    const maximum = MAX_SUPPORTED_UNIX_SECONDS.toString();
    expect(exactUnixSecondsSchema.parse(maximum)).toBe(maximum);
    expect(unixSecondsToNumber(maximum)).toBe(253_402_300_799);
    expect(() => exactUnixSecondsSchema.parse("253402300800")).toThrow(/must not exceed/i);
    expect(() => exactUnixSecondsSchema.parse("18446744073709551615")).toThrow(/must not exceed/i);
  });
});
