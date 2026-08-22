import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(cleanup);

class ResizeObserverStub implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element): void {
    const height = target.classList.contains("virtual-row")
      ? 156
      : target.classList.contains("chart-canvas")
        ? 308
        : 640;
    const rect = {
      x: 0,
      y: 0,
      width: 440,
      height,
      top: 0,
      right: 440,
      bottom: height,
      left: 0,
      toJSON: () => ({}),
    } satisfies DOMRectReadOnly;
    setTimeout(() => this.callback([{
        target,
        contentRect: rect,
        borderBoxSize: [{ inlineSize: 440, blockSize: height }],
        contentBoxSize: [{ inlineSize: 440, blockSize: height }],
        devicePixelContentBoxSize: [{ inlineSize: 440, blockSize: height }],
      }], this), 0);
  }
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver = ResizeObserverStub;
globalThis.requestAnimationFrame = (callback: FrameRequestCallback) => {
  return window.setTimeout(() => callback(performance.now()), 0);
};
globalThis.cancelAnimationFrame = (id: number) => window.clearTimeout(id);
HTMLElement.prototype.scrollTo = () => undefined;

/**
 * jsdom has no canvas, so the chart library is stubbed. The stub records what it was *asked* to
 * draw, because the honesty of MarketChart lives in exactly that: whether an omitted interval
 * reached the chart as a blank column, and whether a packed series carried its silence strip.
 */
export const chartCalls: {
  series: { kind: string; data: unknown[] }[];
  markers: unknown[][];
} = { series: [], markers: [] };

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: { kind: "candlestick" },
  HistogramSeries: { kind: "histogram" },
  ColorType: { Solid: "solid" },
  createSeriesMarkers: (_series: unknown, markers: unknown[]) => {
    chartCalls.markers.push(markers);
    return { setMarkers: vi.fn() };
  },
  createChart: () => ({
    addSeries: (definition: { kind: string }) => ({
      setData: (data: unknown[]) => {
        chartCalls.series.push({ kind: definition.kind, data });
      },
    }),
    applyOptions: vi.fn(),
    priceScale: () => ({ applyOptions: vi.fn() }),
    remove: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
  }),
}));

afterEach(() => {
  chartCalls.series = [];
  chartCalls.markers = [];
});
