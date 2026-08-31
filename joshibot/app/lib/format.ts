import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const BASE58_ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;

/** The glyph for "no measurement". Never `0`, never blank. */
export const NO_DATA = "—";

export function shortAddress(value: string | null | undefined, lead = 4, tail = 4) {
  if (!value) return NO_DATA;
  if (value.length <= lead + tail + 1) return value;
  return `${value.slice(0, lead)}…${value.slice(-tail)}`;
}

export function decimals(value: number, digits: number) {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function compact(value: number, digits = 1) {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: digits,
  }).format(value);
}

export function usd(value: number, digits = 0) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `$${compact(value, 2)}`;
  return `$${new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value)}`;
}

export function sol(value: number, digits = 4) {
  return `${decimals(value, digits)} SOL`;
}

export function signed(value: number, digits = 2, suffix = "") {
  const body = decimals(Math.abs(value), digits);
  const mark = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${mark}${body}${suffix}`;
}

/** bps are the netmap's native unit; never mix them with the LP report's fractions. */
export function bps(value: number, digits = 1) {
  return `${signed(value, digits)} bps`;
}

/** LP rates arrive as FRACTIONS (0.02 = 2%/day). Percent-typed values must not use this. */
export function fractionAsPct(value: number, digits = 2) {
  return `${decimals(value * 100, digits)}%`;
}

/** Values that are already percents (pnl_pct: 5.0 == 5%). */
export function pct(value: number, digits = 2) {
  return `${decimals(value, digits)}%`;
}

export function lamportsToSol(value: string | number): number | null {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed)) return null;
  return parsed / 1e9;
}

export function relativeAge(iso: string | null | undefined, now: number): string {
  if (!iso) return "never";
  const at = new Date(iso).getTime();
  if (!Number.isFinite(at)) return "unparseable";
  const seconds = Math.round((now - at) / 1000);
  if (seconds < 0) return `${formatSpan(-seconds)} ahead`;
  if (seconds < 2) return "just now";
  return `${formatSpan(seconds)} ago`;
}

export function formatSpan(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

export function hours(value: number): string {
  if (value < 1) return `${Math.round(value * 60)}m`;
  if (value < 48) return `${decimals(value, 1)}h`;
  return `${decimals(value / 24, 1)}d`;
}

/** Absolute UTC stamp, second resolution. Used wherever a clock is displayed. */
export function stampUtc(iso: string | null | undefined): string {
  if (!iso) return NO_DATA;
  const at = new Date(iso);
  if (!Number.isFinite(at.getTime())) return "unparseable";
  return `${at.toISOString().slice(0, 19).replace("T", " ")}Z`;
}

export function timeOnly(iso: string | null | undefined): string {
  if (!iso) return NO_DATA;
  const at = new Date(iso);
  if (!Number.isFinite(at.getTime())) return "??:??:??";
  return at.toISOString().slice(11, 19);
}

export function parseDecimal(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Raw token amounts are decimal strings because a 1e9-supply 6-decimal token is
 * 1e15 raw units, past the f64 exact-integer cliff. Anything that has to be
 * exact goes through BigInt, not Number.
 */
export function rawUnits(value: string | null | undefined): bigint | null {
  if (!value) return null;
  try {
    return BigInt(value);
  } catch {
    return null;
  }
}
