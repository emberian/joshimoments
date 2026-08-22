import type { Candle } from "../contract/v1";
import { unixSecondsToNumber } from "../contract/instant";

/**
 * What a served candle array actually is, and what a chart is therefore allowed to draw.
 *
 * The bars are **gap-compressed**: the provider omits every interval in which nothing traded, so
 * the array is a price *path* with holes, not a grid. Nothing downstream may treat two adjacent
 * array entries as two adjacent moments. Every value here is arithmetic on the served bar clocks
 * and served decimal strings; none of it is assumed, and none of it is a request argument, since
 * the view carries no interval, no unit and no currency.
 */

/** One stretch in which the provider emitted no bar at all. */
export type CandleGap = {
  /** Index of the bar that follows the silence. */
  index: number;
  fromUnix: number;
  toUnix: number;
  /** Whole spacing-sized intervals the provider omitted between the two bars. */
  missingSlots: number;
  silenceSeconds: number;
};

export type CandlePath = {
  bars: number;
  clocks: number[];
  /**
   * Smallest step between adjacent bar clocks, in seconds, and the divisor of every other step.
   *
   * This is recovered from the served clocks alone. The request's own `interval` argument is not
   * retained anywhere in the view, so the true interval may be a *divisor* of this number and a
   * caption must never state one as fact. `null` when fewer than two bars make a step.
   */
  spacingSeconds: number | null;
  gaps: CandleGap[];
  /** Spacing-sized intervals in which nothing traded, between the oldest and newest bar. */
  omittedIntervals: number;
  /** Spacing-sized intervals the window covers at all, traded or not. */
  totalIntervals: number;
  spanSeconds: number;
  /** Newest bar clock. A market clock: it is not how fresh this feed is. */
  newestBarUnix: number | null;
  oldestBarUnix: number | null;
  /** When the catalog knew the bytes these bars came out of. *This* one is freshness. */
  knownAt: string | null;
  /**
   * Seconds between the newest bar and the instant those bytes became known.
   *
   * On a quiet coin this is arbitrarily large while the read itself is seconds old, so it is
   * market silence and must never be rendered as staleness.
   */
  trailingSilenceSeconds: number | null;
};

function gcd(left: number, right: number): number {
  let a = left;
  let b = right;
  while (b !== 0) {
    const next = a % b;
    a = b;
    b = next;
  }
  return a;
}

export function candlePath(candles: readonly Candle[]): CandlePath {
  const clocks = candles.map((candle) => unixSecondsToNumber(candle.timeUnix));
  const empty: CandlePath = {
    bars: 0,
    clocks: [],
    spacingSeconds: null,
    gaps: [],
    omittedIntervals: 0,
    totalIntervals: 0,
    spanSeconds: 0,
    newestBarUnix: null,
    oldestBarUnix: null,
    knownAt: null,
    trailingSilenceSeconds: null,
  };
  if (clocks.length === 0) return empty;

  let spacing = 0;
  for (let index = 1; index < clocks.length; index += 1) {
    spacing = gcd(spacing, (clocks[index] ?? 0) - (clocks[index - 1] ?? 0));
  }
  const spacingSeconds = spacing > 0 ? spacing : null;

  const gaps: CandleGap[] = [];
  let omittedIntervals = 0;
  if (spacingSeconds !== null) {
    for (let index = 1; index < clocks.length; index += 1) {
      const from = clocks[index - 1] ?? 0;
      const to = clocks[index] ?? 0;
      const slots = Math.round((to - from) / spacingSeconds);
      if (slots > 1) {
        gaps.push({
          index,
          fromUnix: from,
          toUnix: to,
          missingSlots: slots - 1,
          silenceSeconds: to - from,
        });
        omittedIntervals += slots - 1;
      }
    }
  }

  const oldestBarUnix = clocks[0] ?? null;
  const newestBarUnix = clocks.at(-1) ?? null;
  const spanSeconds =
    oldestBarUnix === null || newestBarUnix === null ? 0 : newestBarUnix - oldestBarUnix;
  // A candle array is legal at length 0 and at length >= 2; the contract refuses length 1 because
  // one bar implies an interval it does not have. `knownAt` is uniform across a served window.
  const knownAt = candles.at(-1)?.knownAt ?? null;
  const trailingSilenceSeconds =
    knownAt === null || newestBarUnix === null
      ? null
      : Math.max(0, Math.floor(Date.parse(knownAt) / 1000) - newestBarUnix);

  return {
    bars: clocks.length,
    clocks,
    spacingSeconds,
    gaps,
    omittedIntervals,
    totalIntervals: spacingSeconds === null ? 0 : spanSeconds / spacingSeconds + 1,
    spanSeconds,
    newestBarUnix,
    oldestBarUnix,
    knownAt,
    trailingSilenceSeconds,
  };
}

/**
 * Compare two exact decimal strings without ever building a float.
 *
 * The provider writes prices with up to 28 fractional digits, and it zero-pads `open`/`close`
 * while trimming `high`/`low`, so the same number arrives as two different strings. `Number()`
 * would silently drop digits, and `===` would silently call `"0.10"` and `"0.1"` different. Both
 * mistakes turn into a direction chip that says the wrong thing.
 */
export function compareDecimal(left: string, right: string): number {
  const leftMagnitude = strip(left);
  const rightMagnitude = strip(right);
  // A signed zero is still zero, so the sign only decides an ordering once a value is non-zero.
  const leftSign = isZero(leftMagnitude) ? 0 : left.startsWith("-") ? -1 : 1;
  const rightSign = isZero(rightMagnitude) ? 0 : right.startsWith("-") ? -1 : 1;
  if (leftSign !== rightSign) return leftSign < rightSign ? -1 : 1;
  if (leftSign === 0) return 0;
  const magnitude = compareMagnitude(leftMagnitude, rightMagnitude);
  return leftSign < 0 ? -magnitude : magnitude;
}

function strip(value: string): string {
  return value.startsWith("-") ? value.slice(1) : value;
}

function isZero(value: string): boolean {
  return /^0*(?:\.0*)?$/.test(value);
}

function compareMagnitude(left: string, right: string): number {
  const [leftInteger = "", leftFraction = ""] = left.split(".");
  const [rightInteger = "", rightFraction = ""] = right.split(".");
  const width = Math.max(leftInteger.length, rightInteger.length);
  const integer = leftInteger.padStart(width, "0").localeCompare(rightInteger.padStart(width, "0"));
  if (integer !== 0) return integer < 0 ? -1 : 1;
  const digits = Math.max(leftFraction.length, rightFraction.length);
  const fraction = leftFraction
    .padEnd(digits, "0")
    .localeCompare(rightFraction.padEnd(digits, "0"));
  return fraction === 0 ? 0 : fraction < 0 ? -1 : 1;
}

/** A duration in words, so no caption ever hardcodes an interval name. */
export function describeSeconds(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes < 60) return remainder === 0 ? `${minutes}m` : `${minutes}m ${remainder}s`;
  const hours = Math.floor(minutes / 60);
  const trailingMinutes = minutes % 60;
  return trailingMinutes === 0 ? `${hours}h` : `${hours}h ${trailingMinutes}m`;
}

/** `1234` as `1,234`, so a five-figure silence count is readable at a glance. */
export function groupDigits(value: number): string {
  return value.toLocaleString("en-US");
}
