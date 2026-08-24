import { unixSecondsToNumber } from "../contract/instant";
import type { Candle } from "../contract/v1";
import { compareDecimal } from "./candlePath";

export const SPARKLINE_WIDTH = 64;
export const SPARKLINE_HEIGHT = 18;

/**
 * The tiny price-path glyph a board row carries when its candidate carries a price path.
 *
 * What it claims is exactly the served closes, plotted against the served BAR CLOCKS — the
 * x axis is time, not array index, because the served array is gap-compressed (see
 * `candlePath.ts`): the provider omits every interval in which nothing traded, and spacing
 * points evenly by index would silently stretch a silent hour into the width of a busy
 * minute. The y axis is normalized to the window's own min and max; no unit, currency, or
 * interval is stated because the view carries none.
 *
 * `null` when the candidate carries no path: the contract serves zero candles or at least
 * two, and a path is never invented to fill the shape. The tone is decided by exact decimal
 * comparison of the first and last served closes, never by float subtraction.
 */
export type SparklineSpec = {
  /** SVG polyline points inside the `SPARKLINE_WIDTH` x `SPARKLINE_HEIGHT` viewBox. */
  points: string;
  /** Direction of last close versus first close, by exact decimal comparison. */
  tone: "positive" | "negative" | "neutral";
};

export function sparklineSpec(candles: readonly Candle[]): SparklineSpec | null {
  if (candles.length < 2) return null;
  const clocks = candles.map((candle) => unixSecondsToNumber(candle.timeUnix));
  const closes = candles.map((candle) => Number(candle.close));
  const firstClock = clocks[0] ?? 0;
  const lastClock = clocks[clocks.length - 1] ?? 0;
  const span = lastClock - firstClock;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const pad = 1.5;
  const points = closes
    .map((close, index) => {
      const x = span === 0 ? 0 : (((clocks[index] ?? 0) - firstClock) / span) * SPARKLINE_WIDTH;
      const y = max === min
        ? SPARKLINE_HEIGHT / 2
        : pad + (1 - (close - min) / (max - min)) * (SPARKLINE_HEIGHT - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const firstClose = candles[0]?.close ?? "0";
  const lastClose = candles[candles.length - 1]?.close ?? "0";
  const direction = compareDecimal(lastClose, firstClose);
  return { points, tone: direction > 0 ? "positive" : direction < 0 ? "negative" : "neutral" };
}
