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

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: {},
  ColorType: { Solid: "solid" },
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
  }),
}));
