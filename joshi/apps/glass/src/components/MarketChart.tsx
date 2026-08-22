import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type SeriesMarker,
  type UTCTimestamp,
  type WhitespaceData,
} from "lightweight-charts";

import type { Candle, Candidate } from "../contract/v1";
import { unixSecondsToNumber } from "../contract/instant";
import { candidateSymbol, clock } from "../format";
import { chartInstant, type ChartAnchor } from "../operator/contract";
import {
  candlePath,
  compareDecimal,
  describeSeconds,
  groupDigits,
  type CandlePath,
} from "./candlePath";

/**
 * The one drawing rule this file exists to enforce: **a silence must never look like a flat
 * market.**
 *
 * A served candle array is gap-compressed. The provider omits every interval in which nothing
 * traded, so entry `n` and entry `n+1` can be one second apart or eleven minutes apart, and
 * lightweight-charts places data points at successive *indices* rather than at their clocks. Left
 * alone it therefore draws eleven minutes of absence exactly like one second of quiet trading,
 * which is the difference between a coin Ember can work and one she cannot.
 *
 * Two honest renderings of the same array are offered, and which one is on screen is always
 * stated in words:
 *
 * - **Real time** pads every omitted interval with whitespace points, which reserve a column and
 *   draw nothing. Absence is literally blank and a flat market is literally a row of candles at
 *   one price. This is the default, and it is refused rather than approximated when the padding
 *   would exceed {@link MAX_CHART_POINTS}.
 * - **Bar sequence** packs the bars adjacently so the shape of the wiggle is readable, and pays
 *   for that by drawing an explicit silence strip beneath them plus a marker on every bar that
 *   follows a gap. Nothing in this mode is to scale in time, and the caption says so.
 *
 * Nothing here names a unit. The provider labels its five fields open/high/low/close/volume and
 * states no currency; the view carries no interval and no unit either, so a caption that said
 * "SOL" or "30-second interval" would be inventing both.
 */

/**
 * Ceiling on points handed to the chart, whitespace included.
 *
 * A thousand one-second bars from a coin that traded across three days would need a quarter of a
 * million whitespace columns. Drawing *some* of them would understate the silence, which is the
 * exact lie this component exists to prevent, so the real-time rendering is withdrawn entirely
 * and the caption says why.
 */
const MAX_CHART_POINTS = 20_000;

type ChartMode = "time" | "sequence";

const UP = "#72d6a2";
const DOWN = "#ef7d70";
const SILENCE = "#c8a45c";

function toChartData(candle: Candle): CandlestickData<UTCTimestamp> {
  return {
    time: unixSecondsToNumber(candle.timeUnix) as UTCTimestamp,
    // Pixels are floats whatever we do here, so this is the one place a served decimal becomes a
    // number. It is never rendered back as text: every printed price below is the exact string.
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
  };
}

/** Bars plus a blank column for every interval the provider omitted. */
function timeTrueData(
  candles: readonly Candle[],
  path: CandlePath,
): (CandlestickData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] {
  const spacing = path.spacingSeconds;
  if (spacing === null) return candles.map(toChartData);
  const points: (CandlestickData<UTCTimestamp> | WhitespaceData<UTCTimestamp>)[] = [];
  candles.forEach((candle, index) => {
    const at = unixSecondsToNumber(candle.timeUnix);
    const previous = index === 0 ? null : (path.clocks[index - 1] ?? null);
    if (previous !== null) {
      for (let slot = previous + spacing; slot < at; slot += spacing) {
        points.push({ time: slot as UTCTimestamp });
      }
    }
    points.push(toChartData(candle));
  });
  return points;
}

/** Seconds of silence immediately before each bar; zero where the tape ran continuously. */
function silenceData(
  candles: readonly Candle[],
  path: CandlePath,
): { time: UTCTimestamp; value: number; color: string }[] {
  const spacing = path.spacingSeconds ?? 0;
  return candles.map((candle, index) => {
    const at = unixSecondsToNumber(candle.timeUnix);
    const previous = index === 0 ? null : (path.clocks[index - 1] ?? null);
    const silence = previous === null ? 0 : at - previous - spacing;
    return { time: at as UTCTimestamp, value: Math.max(0, silence), color: SILENCE };
  });
}

function gapMarkers(path: CandlePath): SeriesMarker<UTCTimestamp>[] {
  return path.gaps.map((gap) => ({
    time: gap.toUnix as UTCTimestamp,
    position: "aboveBar" as const,
    color: SILENCE,
    shape: "arrowDown" as const,
    text: `no trade ${describeSeconds(gap.silenceSeconds)}`,
  }));
}

export function MarketChart({
  candidate,
  onAnnotate,
}: {
  candidate: Candidate;
  onAnnotate(anchor: ChartAnchor): void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candles = useMemo(() => candidate.candles, [candidate]);
  const path = useMemo(() => candlePath(candles), [candles]);
  const [requestedMode, setRequestedMode] = useState<ChartMode>("time");

  const first = candles[0];
  const last = candles.at(-1);
  // Exact decimal-string comparison. `Number(a) > Number(b)` would drop digits past the 17th, and
  // `a !== b` would call the provider's padded "0.0100" and its trimmed "0.01" a move.
  const move = first && last ? compareDecimal(last.close, first.open) : 0;
  const direction = !first || !last ? "flat" : move > 0 ? "up" : move < 0 ? "down" : "flat";

  // Withdrawn rather than approximated: a partially padded chart understates the silence.
  const timeTrueIsDrawable =
    path.spacingSeconds !== null && path.bars + path.omittedIntervals <= MAX_CHART_POINTS;
  const mode: ChartMode = requestedMode === "time" && timeTrueIsDrawable ? "time" : "sequence";

  useEffect(() => {
    const host = hostRef.current;
    if (!host || candles.length === 0) return;

    const chart = createChart(host, {
      width: host.clientWidth,
      height: 308,
      layout: {
        background: { type: ColorType.Solid, color: "#101416" },
        textColor: "#a7b1b2",
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "#20292b" },
        horzLines: { color: "#20292b" },
      },
      crosshair: {
        vertLine: { color: "#8aa7a0", labelBackgroundColor: "#2c5550" },
        horzLine: { color: "#8aa7a0", labelBackgroundColor: "#2c5550" },
      },
      rightPriceScale: { borderColor: "#334043" },
      timeScale: {
        borderColor: "#334043",
        timeVisible: true,
        secondsVisible: true,
        // Real-time mode can carry thousands of blank columns; without this the view clamps and
        // silently shows only part of the window, which reads as a shorter silence than there was.
        minBarSpacing: 0.02,
      },
    });
    chartRef.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: { type: "price", precision: 12, minMove: 0.000000000001 },
    });
    series.setData(mode === "time" ? timeTrueData(candles, path) : candles.map(toChartData));

    if (mode === "sequence" && path.gaps.length > 0) {
      // Bars are packed adjacently here, so absence has to be drawn by hand: a strip whose height
      // is how long the market was silent before each bar, plus a marker naming that silence.
      const silence = chart.addSeries(HistogramSeries, {
        priceScaleId: "joshi-silence",
        priceFormat: { type: "volume" },
        color: SILENCE,
      });
      silence.setData(silenceData(candles, path));
      chart
        .priceScale("joshi-silence")
        .applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
      createSeriesMarkers(series, gapMarkers(path));
    }
    chart.timeScale().fitContent();

    const resize = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) chart.applyOptions({ width: Math.floor(entry.contentRect.width) });
    });
    resize.observe(host);

    return () => {
      resize.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candidate.id, candles, path, mode]);

  const symbol = candidateSymbol(candidate.symbol, candidate.mint);

  if (candles.length === 0) {
    return (
      <figure className="market-chart">
        <figcaption>
          <span>
            <strong>{symbol} observed tape</strong>
            {/* An empty series is an absence, not a zero, and not a flat market. */}
            <small>no price series is attached to this coin in this view</small>
          </span>
        </figcaption>
        <div className="empty-state" role="note">
          <strong>No bars are knowable in this lens.</strong>
          <span>
            This is not a claim that nothing traded. It says only that this view carries no price
            series for this coin.
          </span>
        </div>
      </figure>
    );
  }

  const spacing = path.spacingSeconds;
  const spacingWords = spacing === null ? "an unknown step" : describeSeconds(spacing);
  const tradedIntervals = path.bars;
  const silentShare =
    path.totalIntervals > 0 ? Math.round((path.omittedIntervals / path.totalIntervals) * 100) : 0;

  return (
    <figure className="market-chart">
      <figcaption>
        <span>
          <strong>{symbol} observed tape</strong>
          {/*
            Every number in this line is arithmetic on the served bar clocks. The view carries no
            interval argument, so the spacing is stated as what the clocks imply and nothing more.
          */}
          <small>
            {groupDigits(path.bars)} bars · steps are whole multiples of {spacingWords}, the
            smallest observed{" "}
            {spacing === null
              ? ""
              : "(the request's own interval is not carried by this view, so the true interval may divide it)"}
          </small>
        </span>
        <span
          className={`direction-chip value-${direction === "up" ? "positive" : direction === "down" ? "negative" : "neutral"}`}
        >
          {direction === "flat" ? "unchanged" : direction} across window
        </span>
      </figcaption>

      <div className="chart-mode" role="group" aria-label="How the horizontal axis is spaced">
        <button
          type="button"
          aria-pressed={mode === "time"}
          disabled={!timeTrueIsDrawable}
          onClick={() => setRequestedMode("time")}
        >
          Real time
        </button>
        <button
          type="button"
          aria-pressed={mode === "sequence"}
          onClick={() => setRequestedMode("sequence")}
        >
          Bar sequence
        </button>
        <small data-testid="chart-mode-note">
          {mode === "time"
            ? "Horizontal axis is real time. A blank column is an interval in which nothing traded — it is not a flat price."
            : timeTrueIsDrawable
              ? "Horizontal axis is bar sequence. Gaps are NOT to scale; the amber strip below is how long the market was silent before each bar."
              : `Horizontal axis is bar sequence. Real time is withdrawn here: drawing it would need ${groupDigits(path.bars + path.omittedIntervals)} columns, past the ${groupDigits(MAX_CHART_POINTS)} this chart will draw, and a partly drawn silence would understate it. The amber strip below is how long the market was silent before each bar.`}
        </small>
      </div>

      <div ref={hostRef} className="chart-canvas" aria-hidden="true" data-testid="chart-canvas" />

      <p className="chart-summary" data-testid="chart-silence">
        {/*
          Absence stated as a count, not only as a picture. A reader who cannot see the chart gets
          the same fact: how much of this window had no trade in it at all.
        */}
        {path.gaps.length === 0
          ? `Every one of these ${groupDigits(path.bars)} bars is adjacent to the next: the provider omitted no interval inside this window.`
          : `${groupDigits(tradedIntervals)} of ${groupDigits(path.totalIntervals)} ${spacingWords} intervals traded. The provider omitted ${groupDigits(path.omittedIntervals)} of them (${silentShare}% of the window) across ${groupDigits(path.gaps.length)} silences, the longest ${describeSeconds(Math.max(...path.gaps.map((gap) => gap.silenceSeconds)))}. An omitted interval means no trade, never a flat price.`}
      </p>

      <p className="chart-summary" data-testid="chart-clocks">
        {/*
          The two clocks are kept apart on purpose. Bar age is a property of the market; feed
          freshness is a property of us. Collapsing them tells a trader a quiet coin is a broken
          feed, or worse, tells her a broken feed is a quiet coin.
        */}
        Newest bar {path.newestBarUnix === null ? "—" : `${clock(new Date(path.newestBarUnix * 1000).toISOString())}Z`}
        ; this window became knowable at {path.knownAt === null ? "—" : `${clock(path.knownAt)}Z`}
        {path.trailingSilenceSeconds !== null && spacing !== null && path.trailingSilenceSeconds > spacing
          ? `, ${describeSeconds(path.trailingSilenceSeconds)} later. That distance is not staleness. A bar clock is a market clock: on a quiet coin the newest bar is arbitrarily old while the read itself is seconds fresh, and part of this distance is the delay between the read and the commit rather than silence at all. Read this source's freshness from its ingest clock, never from the age of a bar.`
          : "."}
      </p>

      <p className="chart-summary" data-testid="chart-units">
        Prices are the provider's exact decimal strings, shown verbatim in the table below. It
        labels these fields open/high/low/close/volume and states no unit or currency for any of
        them, and this view carries none either, so none is named here. They are provider claims
        about price: not fills, not quotes, not executability.
      </p>

      <div
        className="chart-annotation-actions"
        role="group"
        aria-label="Annotate chart with semantic coordinates"
      >
        <button
          type="button"
          disabled={!last}
          onClick={() => {
            if (last) onAnnotate({ anchorKind: "time", at: chartInstant(last.timeUnix) });
          }}
        >
          Mark latest time
        </button>
        <button
          type="button"
          disabled={!last}
          onClick={() => {
            if (last)
              onAnnotate({
                anchorKind: "point",
                sampleId: `${candidate.id}:${last.timeUnix}`,
                at: chartInstant(last.timeUnix),
              });
          }}
        >
          Mark latest point
        </button>
        <button
          type="button"
          disabled={!first || !last}
          onClick={() => {
            if (first && last)
              onAnnotate({
                anchorKind: "range",
                startSampleId: `${candidate.id}:${first.timeUnix}`,
                endSampleId: `${candidate.id}:${last.timeUnix}`,
                startAt: chartInstant(first.timeUnix),
                endAt: chartInstant(last.timeUnix),
              });
          }}
        >
          Mark visible range
        </button>
      </div>

      <details className="data-details">
        <summary>Read the latest bars as a table</summary>
        <div className="table-scroll" tabIndex={0}>
          <table>
            <caption>
              Last eight chart bars for {symbol}, as the provider wrote them. A “silent before” row
              is time in which nothing traded at all.
            </caption>
            <thead>
              <tr>
                <th scope="col">Observed</th>
                <th scope="col">Silent before</th>
                <th scope="col">Open</th>
                <th scope="col">High</th>
                <th scope="col">Low</th>
                <th scope="col">Close</th>
                <th scope="col">Volume</th>
                <th scope="col">Annotate</th>
              </tr>
            </thead>
            <tbody>
              {candles.slice(-8).map((candle, offset) => {
                const index = candles.length - Math.min(8, candles.length) + offset;
                const at = unixSecondsToNumber(candle.timeUnix);
                const previous = index === 0 ? null : (path.clocks[index - 1] ?? null);
                const silence = previous === null ? null : at - previous - (spacing ?? 0);
                return (
                  <tr key={candle.timeUnix} className={silence ? "row-after-silence" : undefined}>
                    <td>{clock(new Date(at * 1000).toISOString())}Z</td>
                    <td>{silence === null ? "—" : silence > 0 ? describeSeconds(silence) : "none"}</td>
                    {/* Verbatim. `Number(x).toExponential(4)` here would print a price the bytes do not contain. */}
                    <td className="exact-decimal">{candle.open}</td>
                    <td className="exact-decimal">{candle.high}</td>
                    <td className="exact-decimal">{candle.low}</td>
                    <td className="exact-decimal">{candle.close}</td>
                    <td className="exact-decimal">{candle.volumeTokens}</td>
                    <td>
                      <button
                        type="button"
                        className="table-action"
                        onClick={() =>
                          onAnnotate({
                            anchorKind: "point",
                            sampleId: `${candidate.id}:${candle.timeUnix}`,
                            at: chartInstant(candle.timeUnix),
                          })
                        }
                      >
                        Mark point
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
