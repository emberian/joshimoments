import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  type CandlestickData,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";

import type { Candle, Candidate } from "../contract/v1";
import { unixSecondsToNumber } from "../contract/instant";
import { clock } from "../format";
import { chartInstant, type ChartAnchor } from "../operator/contract";

function toChartData(candle: Candle): CandlestickData<UTCTimestamp> {
  return {
    time: unixSecondsToNumber(candle.timeUnix) as UTCTimestamp,
    open: Number(candle.open),
    high: Number(candle.high),
    low: Number(candle.low),
    close: Number(candle.close),
  };
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
  const first = candles[0];
  const last = candles.at(-1);
  const direction =
    first && last && Number(last.close) > Number(first.open)
      ? "up"
      : first && last && Number(last.close) < Number(first.open)
        ? "down"
        : "flat";

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

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
      },
    });
    chartRef.current = chart;
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#72d6a2",
      downColor: "#ef7d70",
      borderVisible: false,
      wickUpColor: "#72d6a2",
      wickDownColor: "#ef7d70",
      priceFormat: { type: "price", precision: 12, minMove: 0.000000000001 },
    });
    series.setData(candles.map(toChartData));
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
  }, [candidate.id, candles]);

  return (
    <figure className="market-chart">
      <figcaption>
        <span>
          <strong>{candidate.symbol} observed tape</strong>
          {/* The view carries no bar interval, and an empty series is an absence, not a zero. */}
          <small>{candles.length === 0 ? "no price series was observed" : `${candles.length} bars`}</small>
        </span>
        <span className={`direction-chip value-${direction === "up" ? "positive" : direction === "down" ? "negative" : "neutral"}`}>
          {direction} in view
        </span>
      </figcaption>
      <div
        ref={hostRef}
        className="chart-canvas"
        aria-hidden="true"
        data-testid="chart-canvas"
      />
      <p className="chart-summary">
        Text equivalent: {candles.length === 0 ? "no bars are knowable in this lens" : `${candles.length} bars, from ${first ? Number(first.open).toExponential(4) : "—"} to ${last ? Number(last.close).toExponential(4) : "—"} SOL; direction ${direction}`}.
      </p>
      <div className="chart-annotation-actions" role="group" aria-label="Annotate chart with semantic coordinates">
        <button type="button" disabled={!last} onClick={() => {
          if (last) onAnnotate({ anchorKind: "time", at: chartInstant(last.timeUnix) });
        }}>Mark latest time</button>
        <button type="button" disabled={!last} onClick={() => {
          if (last) onAnnotate({
            anchorKind: "point",
            sampleId: `${candidate.id}:${last.timeUnix}`,
            at: chartInstant(last.timeUnix),
          });
        }}>Mark latest point</button>
        <button type="button" disabled={!first || !last} onClick={() => {
          if (first && last) onAnnotate({
            anchorKind: "range",
            startSampleId: `${candidate.id}:${first.timeUnix}`,
            endSampleId: `${candidate.id}:${last.timeUnix}`,
            startAt: chartInstant(first.timeUnix),
            endAt: chartInstant(last.timeUnix),
          });
        }}>Mark visible range</button>
      </div>
      <details className="data-details">
        <summary>Read the latest bars as a table</summary>
        <div className="table-scroll" tabIndex={0}>
          <table>
            <caption>Last eight chart bars for {candidate.symbol}</caption>
            <thead>
              <tr>
                <th scope="col">Observed</th>
                <th scope="col">Open</th>
                <th scope="col">High</th>
                <th scope="col">Low</th>
                <th scope="col">Close</th>
                <th scope="col">Known</th>
                <th scope="col">Annotate</th>
              </tr>
            </thead>
            <tbody>
              {candles.slice(-8).map((candle) => (
                <tr key={candle.timeUnix}>
                  <td>{clock(new Date(unixSecondsToNumber(candle.timeUnix) * 1000).toISOString())}Z</td>
                  <td>{Number(candle.open).toExponential(4)}</td>
                  <td>{Number(candle.high).toExponential(4)}</td>
                  <td>{Number(candle.low).toExponential(4)}</td>
                  <td>{Number(candle.close).toExponential(4)}</td>
                  <td>{clock(candle.knownAt)}Z</td>
                  <td><button type="button" className="table-action" onClick={() => onAnnotate({
                    anchorKind: "point",
                    sampleId: `${candidate.id}:${candle.timeUnix}`,
                    at: chartInstant(candle.timeUnix),
                  })}>Mark point</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
