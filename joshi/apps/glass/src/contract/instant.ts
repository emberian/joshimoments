import { z } from "zod";

const exactUtcInstantPattern = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{6})Z$/;
const wireU64Pattern = /^(0|[1-9][0-9]*)$/;

export const MAX_SUPPORTED_UNIX_SECONDS = 253_402_300_799n;

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

export function isExactUtcInstant(value: string): boolean {
  const match = exactUtcInstantPattern.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  if (month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) return false;
  const daysInMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const maximumDay = daysInMonth[month - 1];
  return maximumDay !== undefined && day >= 1 && day <= maximumDay;
}

export const exactUtcInstantSchema = z
  .string()
  .regex(
    exactUtcInstantPattern,
    "must be a canonical UTC timestamp with six fractional digits",
  )
  .refine(isExactUtcInstant, "must be a valid UTC calendar timestamp");

export const exactUnixSecondsSchema = z
  .string()
  .regex(wireU64Pattern, "must be a non-negative integer string")
  .refine(
    (value) => BigInt(value) <= MAX_SUPPORTED_UNIX_SECONDS,
    `must not exceed supported Unix second ${MAX_SUPPORTED_UNIX_SECONDS}`,
  );

export function unixSecondsToNumber(value: string): number {
  const parsed = exactUnixSecondsSchema.parse(value);
  const seconds = BigInt(parsed);
  const converted = Number(seconds);
  if (!Number.isSafeInteger(converted) || BigInt(converted) !== seconds) {
    throw new Error("Unix seconds cannot be represented as an exact JavaScript integer");
  }
  return converted;
}
