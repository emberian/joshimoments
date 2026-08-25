import { unixSecondsToNumber } from "../contract/instant";
import type { Candle } from "../contract/v1";
import { candlePath, compareDecimal } from "./candlePath";

/**
 * The compact candle plot a grid card carries when its candidate carries a price path —
 * Ember's explicit ask: candles on the card, not just a closing-price line.
 *
 * Same honesty as `MarketChart`/`sparklineSpec`: the x axis is the served BAR CLOCKS, never
 * the array index, so a silence the provider omitted stays a visible horizontal hole instead
 * of being compressed away; nothing is interpolated into it. The y axis normalizes the served
 * highs and lows to the box; no unit, currency, or interval is stated because the view
 * carries none. Bar tone is decided by exact decimal comparison of close versus open.
 *
 * `null` when the candidate carries no path (the contract serves zero bars or at least two);
 * a glyph is never invented to fill a card.
 */
export type CandleGlyphBar = {
  /** Center x of the bar inside the viewBox. */
  x: number;
  bodyY: number;
  bodyHeight: number;
  wickY1: number;
  wickY2: number;
  tone: "positive" | "negative" | "neutral";
};

export type CandleGlyphSpec = {
  bars: CandleGlyphBar[];
  /** One shared body width, sized from the recovered bar spacing so bars cannot overlap. */
  barWidth: number;
  /** Whole provider-omitted intervals inside the window, for the caption. */
  omittedIntervals: number;
};

export function candleGlyphSpec(
  candles: readonly Candle[],
  width: number,
  height: number,
): CandleGlyphSpec | null {
  if (candles.length < 2) return null;
  const clocks = candles.map((candle) => unixSecondsToNumber(candle.timeUnix));
  const firstClock = clocks[0] ?? 0;
  const lastClock = clocks[clocks.length - 1] ?? 0;
  const span = lastClock - firstClock;
  const lows = candles.map((candle) => Number(candle.low));
  const highs = candles.map((candle) => Number(candle.high));
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const pad = 1;
  const scaleY = (value: number): number =>
    max === min ? height / 2 : pad + (1 - (value - min) / (max - min)) * (height - pad * 2);

  const path = candlePath(candles);
  // Body width from the true spacing share of the window, clamped so a dense window still
  // shows distinct bars and a sparse one does not smear.
  const spacingShare = path.spacingSeconds !== null && span > 0 ? (path.spacingSeconds / span) * width : width / candles.length;
  const barWidth = Math.min(7, Math.max(1, spacingShare * 0.62));

  const bars = candles.map((candle, index) => {
    const x = span === 0 ? width / 2 : ((clocks[index] ?? 0) - firstClock) / span * (width - barWidth) + barWidth / 2;
    const open = scaleY(Number(candle.open));
    const close = scaleY(Number(candle.close));
    const bodyY = Math.min(open, close);
    const bodyHeight = Math.max(0.75, Math.abs(open - close));
    const direction = compareDecimal(candle.close, candle.open);
    return {
      x: Number(x.toFixed(2)),
      bodyY: Number(bodyY.toFixed(2)),
      bodyHeight: Number(bodyHeight.toFixed(2)),
      wickY1: Number(scaleY(Number(candle.high)).toFixed(2)),
      wickY2: Number(scaleY(Number(candle.low)).toFixed(2)),
      tone: direction > 0 ? "positive" as const : direction < 0 ? "negative" as const : "neutral" as const,
    };
  });

  return { bars, barWidth: Number(barWidth.toFixed(2)), omittedIntervals: path.omittedIntervals };
}
