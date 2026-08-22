import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Candidate, Candle } from "../contract/v1";
import { chartCalls } from "../test/setup";
import { MarketChart } from "./MarketChart";

const KNOWN_AT = "2026-08-22T01:30:00.000000Z";

function bar(timeUnix: number, price: string): Candle {
  return {
    timeUnix: String(timeUnix),
    knownAt: KNOWN_AT,
    open: price,
    high: price,
    low: price,
    close: price,
    volumeTokens: "125.65372292213",
  };
}

function candidate(candles: Candle[]): Candidate {
  return {
    id: "HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump",
    mint: "HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump",
    symbol: null,
    name: null,
    board: "watch",
    lifecycle: "unknown",
    firstKnownAt: KNOWN_AT,
    lastObservedAt: KNOWN_AT,
    rank: "1",
    metrics: {
      priceSol: null,
      marketCapUsd: null,
      change5mBps: null,
      ageSeconds: null,
      activity: "unknown",
      quoteSizeSol: null,
      executableExitSol: null,
    },
    attentionReason: "Derived from one retained candle window.",
    socialSummary: "No social source was acquired in this cut.",
    tags: ["gap_compressed_path"],
    watched: false,
    episodeId: null,
    evidence: [
      {
        id: "obs:acq:body",
        sourceId: "pump.api.product.v1",
        field: "candles",
        evidenceClass: "observed",
        observedAt: null,
        ingestedAt: KNOWN_AT,
        knownAt: KNOWN_AT,
        status: "available",
        note: "Bars copied byte-for-byte out of a retained provider body.",
      },
    ],
    candles,
  };
}

/** A market that traded every second for six seconds and never moved. */
const FLAT = [0, 1, 2, 3, 4, 5].map((offset) => bar(1_787_352_000 + offset, "0.0100"));

/** The same six bars, except the market went silent for ten seconds in the middle. */
const WITH_SILENCE = [
  bar(1_787_352_000, "0.0100"),
  bar(1_787_352_001, "0.0100"),
  bar(1_787_352_002, "0.0100"),
  bar(1_787_352_012, "0.0100"),
  bar(1_787_352_013, "0.0100"),
  bar(1_787_352_014, "0.0100"),
];

async function draw(candles: Candle[]) {
  await act(async () => {
    render(<MarketChart candidate={candidate(candles)} onAnnotate={vi.fn()} />);
  });
}

describe("MarketChart", () => {
  it("draws an omitted interval as a blank column, so absence cannot look like a flat market", async () => {
    await draw(WITH_SILENCE);
    const drawn = chartCalls.series.find((entry) => entry.kind === "candlestick");
    // Six real bars plus nine blank columns for the nine seconds that carried no trade at all.
    // A whitespace point has a time and no prices, so the chart reserves the column and draws
    // nothing in it.
    expect(drawn?.data).toHaveLength(15);
    const blanks = (drawn?.data ?? []).filter(
      (point) => !Object.hasOwn(point as object, "close"),
    );
    expect(blanks).toHaveLength(9);

    // The same shape said in words for a reader who cannot see the canvas.
    expect(screen.getByTestId("chart-silence")).toHaveTextContent(
      "6 of 15 1s intervals traded",
    );
    expect(screen.getByTestId("chart-silence")).toHaveTextContent("omitted 9 of them (60% of the window)");
    expect(screen.getByTestId("chart-silence")).toHaveTextContent("longest 10s");
    expect(screen.getByTestId("chart-silence")).toHaveTextContent(
      "An omitted interval means no trade, never a flat price",
    );
  });

  it("draws a genuinely flat market as unbroken bars with no blank column at all", async () => {
    await draw(FLAT);
    const drawn = chartCalls.series.find((entry) => entry.kind === "candlestick");
    expect(drawn?.data).toHaveLength(6);
    expect(
      (drawn?.data ?? []).filter((point) => !Object.hasOwn(point as object, "close")),
    ).toHaveLength(0);
    expect(screen.getByTestId("chart-silence")).toHaveTextContent(
      "the provider omitted no interval inside this window",
    );
    // Flat is a direction the bytes support, and it is named as unchanged rather than as absent.
    expect(screen.getByText("unchanged across window")).toBeInTheDocument();
  });

  it("pays for packed bars with an explicit silence strip and a marker on every gap", async () => {
    await draw(WITH_SILENCE);
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Bar sequence" }));
    });
    expect(chartCalls.series.some((entry) => entry.kind === "histogram")).toBe(true);
    expect(chartCalls.markers.at(-1)).toEqual([
      expect.objectContaining({ text: "no trade 10s" }),
    ]);
    expect(screen.getByTestId("chart-mode-note")).toHaveTextContent("Gaps are NOT to scale");
  });

  it("states the bar spacing from the clocks and names no interval, unit or currency", async () => {
    await draw(WITH_SILENCE);
    const caption = screen.getByText(/steps are whole multiples of/);
    expect(caption).toHaveTextContent("6 bars");
    expect(caption).toHaveTextContent("steps are whole multiples of 1s, the smallest observed");
    expect(caption).toHaveTextContent("the true interval may divide it");

    // The exact regression this component was rewritten for: a caption that named a unit and an
    // interval the bytes never carried.
    const figure = screen.getByRole("figure");
    expect(figure.textContent).not.toMatch(/\bSOL\b/);
    expect(figure.textContent).not.toMatch(/fixture bars/);
    expect(figure.textContent).not.toMatch(/30-second/);
    expect(screen.getByTestId("chart-units")).toHaveTextContent("states no unit or currency");
  });

  it("keeps the newest bar clock apart from how fresh the feed is", async () => {
    await draw(WITH_SILENCE);
    const clocks = screen.getByTestId("chart-clocks");
    expect(clocks).toHaveTextContent("Newest bar 22:40:14Z");
    expect(clocks).toHaveTextContent("this window became knowable at 01:30:00Z");
    expect(clocks).toHaveTextContent("That distance is not staleness");
    expect(clocks).toHaveTextContent("never from the age of a bar");
  });

  it("prints the provider's exact decimal strings and never a float of them", async () => {
    const exact = "0.0127543073470319645806409668";
    await draw([bar(1_787_352_000, exact), bar(1_787_352_001, exact)]);
    await act(async () => {
      await userEvent.click(screen.getByText("Read the latest bars as a table"));
    });
    const table = screen.getByRole("table");
    expect(within(table).getAllByText(exact).length).toBeGreaterThan(0);
    // What the old table printed for that price. Twenty-four digits of it were simply gone.
    expect(table.textContent).not.toContain(Number(exact).toExponential(4));
  });

  it("renders an empty series as an absence and draws no chart at all", async () => {
    await draw([]);
    expect(chartCalls.series).toHaveLength(0);
    expect(screen.getByText("No bars are knowable in this lens.")).toBeInTheDocument();
    expect(screen.queryByTestId("chart-canvas")).not.toBeInTheDocument();
    expect(screen.getByText(/not a claim that nothing traded/)).toBeInTheDocument();
  });
});
