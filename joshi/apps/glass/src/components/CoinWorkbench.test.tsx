import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Candidate } from "../contract/v1";
import { CoinWorkbench } from "./CoinWorkbench";

const MINT = "HgBRWfYxEfvPhtqkaeymCQtHCrKE46qQ43pKe8HCpump";

function evidenceRow(id: string, field: string, evidenceClass: Candidate["evidence"][number]["evidenceClass"]) {
  return {
    id,
    sourceId: "pump.api.product.v1",
    field,
    evidenceClass,
    observedAt: null,
    ingestedAt: "2026-08-22T01:23:12.331589Z",
    knownAt: "2026-08-22T01:30:00.000000Z",
    status: "available" as const,
    note: "Provider claim copied from the retained read; see the source panel for the sentence.",
  };
}

/** A candidate the live surface now actually derives: every number a labelled provider claim. */
const observed: Candidate = {
  id: MINT,
  mint: MINT,
  symbol: "FAUCAT",
  name: "FAUCAT",
  board: "watch",
  lifecycle: "unknown",
  firstKnownAt: "2026-08-22T01:23:12.331589Z",
  lastObservedAt: "2026-08-22T01:23:12.331589Z",
  rank: "1",
  metrics: {
    priceSol: "0.0127875704036029988601137368",
    marketCapUsd: "2540.9742079027883",
    change5mBps: "44",
    ageSeconds: "408",
    activity: "unknown",
    quoteSizeSol: null,
    executableExitSol: null,
  },
  attentionReason: "Carries 8 evidence rows. Ticker, name and market cap are provider claims.",
  socialSummary: "No social source was acquired in this cut.",
  tags: ["coin_metadata_observed", "market_cap_from_usd_market_cap"],
  watched: false,
  episodeId: null,
  evidence: [
    evidenceRow("obs:acq:1:body:change-5m", "metrics.change5mBps", "derived"),
    evidenceRow("obs:acq:1:body:claim-market-cap", "metrics.marketCapUsd", "observed"),
    evidenceRow("obs:acq:1:body:claim-symbol", "symbol", "observed"),
    evidenceRow("obs:acq:1:body:price-close", "metrics.priceSol", "derived"),
  ],
  candles: [],
};

const unobserved: Candidate = {
  ...observed,
  symbol: null,
  name: null,
  metrics: {
    ...observed.metrics,
    priceSol: null,
    marketCapUsd: null,
    change5mBps: null,
  },
  tags: ["chain_observed", "no_price_observed", "ticker_unobserved"],
  evidence: [evidenceRow("obs:chain:1", "mint", "observed")],
};

describe("coin workbench provenance", () => {
  it("renders every provider claim with its class, source, and knowledge clock", () => {
    render(
      <CoinWorkbench candidate={observed} episode={undefined} socialEvents={[]} onAnnotate={() => {}} />,
    );
    // Identity: a real ticker renders behind `$`, with where and when it was read.
    expect(screen.getByRole("heading", { name: /\$FAUCAT/ })).toBeInTheDocument();
    expect(
      screen.getByText(/ticker and name: observed · pump\.api\.product\.v1 · known 01:30:00Z/i),
    ).toBeInTheDocument();
    // Each metric card carries the claim's lineage and age beside the number itself.
    expect(
      screen.getAllByText(/derived · pump\.api\.product\.v1 · known 01:30:00Z/i).length,
    ).toBeGreaterThan(0);
    // Twice: once beside the market cap, once in the identity provenance line above.
    expect(
      screen.getAllByText(/observed · pump\.api\.product\.v1 · known 01:30:00Z$/i),
    ).toHaveLength(2);
    // The five-minute move states its lineage too, instead of a bare tape adjective.
    expect(screen.getByText("+0.44%")).toBeInTheDocument();
  });

  it("keeps absence explicit when the view carries no claims", () => {
    render(
      <CoinWorkbench candidate={unobserved} episode={undefined} socialEvents={[]} onAnnotate={() => {}} />,
    );
    // No placeholder ticker: the mint's leading characters, never behind `$`.
    expect(screen.getByRole("heading", { name: /HgBRWf…/ })).toBeInTheDocument();
    expect(screen.getByText(/no name in this view/i)).toBeInTheDocument();
    expect(screen.queryByText(/ticker and name:/i)).not.toBeInTheDocument();
    expect(screen.getByText(/no price was observed in this view/i)).toBeInTheDocument();
    expect(screen.getByText(/no market cap was observed in this view/i)).toBeInTheDocument();
    // An underived move renders as its absence, described by the activity the view does carry.
    expect(screen.getAllByText(/not observed/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/unknown tape/i)).toBeInTheDocument();
  });
});
