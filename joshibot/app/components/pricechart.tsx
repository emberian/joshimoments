import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  PriceScaleMode,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import type { CandleBar } from "@/lib/types";

/**
 * Rendering is delegated to lightweight-charts (canvas, purpose-built for
 * financial series: real time axis, log price scale, crosshair, hit-testing).
 * Nothing here draws a rectangle by hand.
 *
 * The series TYPE is chosen from what the data can actually support. The
 * sentinel's /api/candles is not an OHLC feed — `_bars_from_windows` back-solves
 * at most five prior prices out of DexScreener percentage windows and emits them
 * with o == h == l == c and v == 0. Drawn as candlesticks those become five doji
 * and a flat volume pane, which reads as "a quiet market" when the truth is
 * "we never measured a high, a low, or a volume". So: degenerate bars render as
 * a reconstructed price path with explicit markers, and the candlestick path is
 * used only if a genuine OHLC source ever appears behind the same endpoint.
 */

// Mirrors the theme tokens in globals.css. Canvas needs concrete colors.
const UP = "#3fd07a";
const DOWN = "#f4614f";
const LINE = "#8fd6a8";
const GRID = "rgba(255,255,255,0.05)";
const TEXT = "#8ea394";

export type SeriesShape = "ohlc" | "reconstructed-path";

/** True when every bar is a point (o == h == l == c): not an OHLC series. */
export function shapeOf(bars: CandleBar[]): SeriesShape {
  if (!bars.length) return "reconstructed-path";
  const degenerate = bars.every((bar) => bar.o === bar.h && bar.h === bar.l && bar.l === bar.c);
  return degenerate ? "reconstructed-path" : "ohlc";
}

function priceFormatter(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs === 0) return "0";
  if (abs >= 1) return value.toFixed(4);
  if (abs >= 1e-4) return value.toFixed(8);
  return value.toExponential(4);
}

export type Hover = {
  time: number;
  close: number;
  open: number | null;
  high: number | null;
  low: number | null;
} | null;

export function PriceChart({
  bars,
  shape,
  height = 380,
  onHover,
}: {
  bars: CandleBar[];
  shape: SeriesShape;
  height?: number;
  onHover?: (hover: Hover) => void;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const hoverRef = useRef(onHover);

  // Kept out of render: the chart's crosshair subscription closes over this ref
  // so a new callback identity does not force the chart to be rebuilt.
  useEffect(() => {
    hoverRef.current = onHover;
  }, [onHover]);

  useEffect(() => {
    const element = holder.current;
    if (!element) return;

    const chart = createChart(element, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: TEXT,
        fontFamily: "'IBM Plex Mono', ui-monospace, monospace",
        fontSize: 10,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: GRID },
        horzLines: { color: GRID },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: TEXT, width: 1, style: LineStyle.Dotted, labelBackgroundColor: "#1d2620" },
        horzLine: { color: TEXT, width: 1, style: LineStyle.Dotted, labelBackgroundColor: "#1d2620" },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.1)",
        // Cluster prices routinely span an order of magnitude inside one window.
        mode: PriceScaleMode.Logarithmic,
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.1)",
        timeVisible: true,
        secondsVisible: false,
      },
      localization: { priceFormatter },
      height,
      autoSize: false,
    });
    chartRef.current = chart;

    let series: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
    if (shape === "ohlc") {
      series = chart.addSeries(CandlestickSeries, {
        upColor: UP,
        downColor: DOWN,
        borderUpColor: UP,
        borderDownColor: DOWN,
        wickUpColor: UP,
        wickDownColor: DOWN,
        priceFormat: { type: "custom", formatter: priceFormatter, minMove: 1e-12 },
      });
      series.setData(
        bars.map((bar) => ({
          time: bar.t as UTCTimestamp,
          open: bar.o,
          high: bar.h,
          low: bar.l,
          close: bar.c,
        })),
      );
    } else {
      const line = chart.addSeries(LineSeries, {
        color: LINE,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        priceFormat: { type: "custom", formatter: priceFormatter, minMove: 1e-12 },
        pointMarkersVisible: true,
        crosshairMarkerVisible: true,
      });
      line.setData(bars.map((bar) => ({ time: bar.t as UTCTimestamp, value: bar.c })));
      // Each reconstructed point is a discrete datum, not a sampled path. Mark
      // them so the eye does not read the connecting line as observed movement.
      createSeriesMarkers(
        line,
        bars.map((bar) => ({
          time: bar.t as UTCTimestamp,
          position: "inBar" as const,
          color: LINE,
          shape: "circle" as const,
        })),
      );
      series = line;
    }

    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      const cb = hoverRef.current;
      if (!cb) return;
      if (!param.time || !param.point) {
        cb(null);
        return;
      }
      const data = param.seriesData.get(series);
      if (!data) {
        cb(null);
        return;
      }
      if ("close" in data) {
        cb({
          time: param.time as number,
          close: data.close,
          open: data.open,
          high: data.high,
          low: data.low,
        });
      } else if ("value" in data && typeof data.value === "number") {
        cb({ time: param.time as number, close: data.value, open: null, high: null, low: null });
      }
    });

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) chart.applyOptions({ width: Math.floor(width) });
    });
    observer.observe(element);
    chart.applyOptions({ width: Math.floor(element.clientWidth) });

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, shape, height]);

  return <div ref={holder} className="w-full" style={{ height }} />;
}

/** Formats a crosshair time for the readout strip. */
export function hoverTime(time: number): string {
  return new Date(time * 1000).toISOString().slice(0, 16).replace("T", " ") + "Z";
}

/** Small helper so views can keep the hover readout in local state. */
export function useHover() {
  return useState<Hover>(null);
}

export type { Time };
