import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";

import type { Candidate } from "../contract/v1";
import { AttentionFeed } from "./AttentionFeed";

/** A minimal legal candidate, absence-first: every nullable field starts null. */
function boardCandidate(overrides: Partial<Candidate> & { id: string; mint: string }): Candidate {
  return {
    symbol: null,
    name: null,
    board: "watch",
    lifecycle: "unknown",
    firstKnownAt: "2026-08-19T21:48:26.000000Z",
    lastObservedAt: null,
    rank: null,
    metrics: {
      priceSol: null,
      marketCapUsd: null,
      change5mBps: null,
      ageSeconds: null,
      activity: "unknown",
      quoteSizeSol: null,
      executableExitSol: null,
    },
    attentionReason: "Named by retained provider observations.",
    socialSummary: "No social source was acquired in this cut.",
    tags: [],
    watched: null,
    episodeId: null,
    evidence: [{
      id: "obs:test:0",
      sourceId: "helius.http.solana.v1",
      field: "mint",
      evidenceClass: "observed",
      observedAt: "2026-08-19T21:48:26.000000Z",
      ingestedAt: "2026-08-19T21:48:40.000000Z",
      knownAt: "2026-08-19T21:48:41.000000Z",
      status: "available",
      note: "Named by retained getTransaction bytes.",
    }],
    candles: [],
    ...overrides,
  };
}

/** The scene's render clock the age column anchors to: 780 seconds after the claimed birth. */
const RENDERED_AT_MS = 1_800_000_780_000;

const observedCoin = boardCandidate({
  id: "wif",
  mint: "WIFXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
  symbol: "WIF",
  name: "dogwifhat",
  lifecycle: "bonding",
  rank: "1",
  watched: true,
  attentionReason: "Fast rank climb with broad two-sided prints.",
  metrics: {
    priceSol: "0.00000005210",
    marketCapUsd: "208400.00",
    change5mBps: "741",
    ageSeconds: "780",
    activity: "bursting",
    quoteSizeSol: null,
    executableExitSol: null,
  },
  candles: [
    { timeUnix: "1000", knownAt: "2026-08-19T21:48:41.000000Z", open: "0.1", high: "0.2", low: "0.1", close: "0.10", volumeTokens: "10" },
    { timeUnix: "1030", knownAt: "2026-08-19T21:48:41.000000Z", open: "0.1", high: "0.3", low: "0.1", close: "0.20", volumeTokens: "10" },
  ],
  // The parity seam's provider-record fields, hand-authored to the seam contract because the
  // derivation lane may not have landed yet: this board is correct the moment real data flows.
  imageUri: "https://cdn.example.invalid/art/wif.png",
  description: "A dog, but with a hat.",
  replyCount: "412",
  athMarketCapUsd: "416800.00",
  athAtUnixMs: "1799990000000",
  createdAtUnixMs: "1800000000000",
  lastTradeAtUnixMs: String(RENDERED_AT_MS - 4_000),
  verified: true,
  currentlyLive: true,
  chainId: "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
  flow: [
    { window: "1h", volumeSol: "16.8", volumeUsd: "3220.00", txns: "150", traders: "64", serverTsUnixMs: String(RENDERED_AT_MS) },
    // The 24h window states no trader count: the movers document sometimes omits it.
    { window: "24h", volumeSol: "120.5", volumeUsd: "23100.00", txns: "1180", serverTsUnixMs: String(RENDERED_AT_MS) },
  ],
});

const unobservedCoin = boardCandidate({
  id: "14m1ketwD6ikdjxtYnm3jtxVzPD9wXhnu5wYGMTWpump",
  mint: "14m1ketwD6ikdjxtYnm3jtxVzPD9wXhnu5wYGMTWpump",
});

function renderBoard(extra: Partial<ComponentProps<typeof AttentionFeed>> = {}) {
  return render(
    <AttentionFeed
      variant="board"
      candidates={[observedCoin, unobservedCoin]}
      selectedId={observedCoin.id}
      onSelect={() => {}}
      board="all"
      onBoardChange={() => {}}
      density="comfortable"
      focusRequest={0}
      renderedAtUnixMs={RENDERED_AT_MS}
      {...extra}
    />,
  );
}

describe("hunt board rows", () => {
  it("renders the glanceable facts and keeps every absence explicit, never a fake zero", async () => {
    const { container } = renderBoard({ boardBasis: "Served order: the scene's own ranks first, unranked coins after them." });
    await waitFor(() => expect(container.querySelectorAll("[data-candidate-id]").length).toBe(2));

    // The observed coin: real coin art under the seam's exact security attributes, ticker
    // behind its $, name, compact market cap, the claimed ATH with its current-over-high bar
    // (208.4K of 416.8K = 50%), TRUE age from the provider's creation clock against the
    // scene's render clock, signed colored move, the movers-tap volume/trade claims, the
    // claimed replies, and a sparkline because it carries a price path.
    const observedRow = screen.getByRole("option", { name: /\$WIF/ });
    const art = observedRow.querySelector<HTMLImageElement>(".coin-art img");
    expect(art).not.toBeNull();
    expect(art?.getAttribute("src")).toBe("https://cdn.example.invalid/art/wif.png");
    expect(art?.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(art?.getAttribute("crossorigin")).toBe("anonymous");
    expect(art?.getAttribute("loading")).toBe("lazy");
    expect(within(observedRow).getByText("dogwifhat")).toBeInTheDocument();
    expect(within(observedRow).getByText("$208.4K")).toBeInTheDocument();
    expect(within(observedRow).getByText("$416.8K")).toBeInTheDocument();
    expect(observedRow.querySelector<HTMLElement>(".ath-bar > span")?.style.width).toBe("50%");
    expect(within(observedRow).getByText("+7.41%")).toBeInTheDocument();
    expect(within(observedRow).getByText("13m")).toBeInTheDocument();
    expect(within(observedRow).getByText("$3.2K")).toBeInTheDocument();
    expect(within(observedRow).getByText("$23.1K")).toBeInTheDocument();
    expect(within(observedRow).getByText("1.2K")).toBeInTheDocument();
    expect(within(observedRow).getByText("412")).toBeInTheDocument();
    // The 24h window claims no trader count: that sub-absence stays a dash, never a zero.
    expect(within(observedRow).getByText(/24h traders not observed/i)).toBeInTheDocument();
    // The provider's boolean claims are chips with their sentences on hover, and the
    // Solana chain claim is the subtle mark (the loud chip is for OTHER chains).
    expect(within(observedRow).getByText("live")).toBeInTheDocument();
    expect(within(observedRow).getByText("verified")).toBeInTheDocument();
    expect(within(observedRow).getByText("sol").getAttribute("title")).toContain("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp");
    expect(observedRow.querySelector(".sparkline")).not.toBeNull();

    // The unobserved coin: the mint's leading characters stand in without a $, the "no
    // ticker" chip says why, the art box falls back to the monogram (nothing is fetched),
    // and the absent figures are dashes whose words survive for readers and on hover —
    // never a rendered zero, and no sparkline is invented.
    const bareRow = screen.getByRole("option", { name: /14m1ke…/ });
    expect(within(bareRow).getByText(/no ticker/i)).toBeInTheDocument();
    expect(bareRow.querySelector(".coin-art img")).toBeNull();
    expect(bareRow.querySelector(".coin-art-monogram")).not.toBeNull();
    expect(within(bareRow).getByText(/market cap not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/5-minute move not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/provider-claimed creation time not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/claimed all-time-high cap not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/1h volume not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/24h volume not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/24h trades not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/claimed reply count not observed/i)).toBeInTheDocument();
    expect(bareRow.querySelector(".sparkline")).toBeNull();

    // The epistemics collapse to chips with the honest prose one hover away, not deleted:
    // the row's title carries the attention reason AND social sentence VERBATIM (they never
    // render inline — a live derivation's "reason" is a provenance paragraph), and the claims
    // glyph's title carries the field-by-field provenance verbatim.
    expect(observedRow.querySelector(".board-row")?.getAttribute("title"))
      .toBe("Fast rank climb with broad two-sided prints.\nNo social source was acquired in this cut.");
    expect(within(observedRow).queryByText(/fast rank climb/i)).not.toBeInTheDocument();
    const evidenceChip = bareRow.querySelector(".chip-evidence");
    expect(evidenceChip?.getAttribute("title")).toContain("mint: observed (available) — Named by retained getTransaction bytes.");

    // The tab's actual ordering rule is stated in the panel.
    expect(screen.getByText(/served order: the scene's own ranks first/i)).toBeInTheDocument();
  });

  it("collapses the provider's market-cap disagreement to a chip whose hover carries the note verbatim", async () => {
    // The exact live-derivation shape: the paragraph is evidence-note content, never row text.
    const note = "The provider asserts two USD market caps in the same document: "
      + "usd_market_cap=9376478.831686128 (rendered) and market_cap_usd=9381195.728794064 "
      + "(5 basis point(s) apart); neither is averaged and the rendered field is named.";
    const disagreeing = boardCandidate({
      id: "disagree",
      mint: "DISAGREEXXXXXXXXXXXXXXXXXXXXXXXX",
      symbol: "CATE",
      tags: ["coin_metadata_observed", "market_cap_fields_disagree"],
      metrics: { ...observedCoin.metrics, marketCapUsd: "9376478.831686128" },
      evidence: [{
        id: "obs:acq:1:body:claim-market-cap",
        sourceId: "pump.api.product.v1",
        field: "metrics.marketCapUsd",
        evidenceClass: "observed",
        observedAt: null,
        ingestedAt: "2026-08-19T21:48:40.000000Z",
        knownAt: "2026-08-19T21:48:41.000000Z",
        status: "available",
        note,
      }],
    });
    const { container } = renderBoard({ candidates: [disagreeing], selectedId: disagreeing.id });
    await waitFor(() => expect(container.querySelectorAll("[data-candidate-id]").length).toBe(1));

    const row = screen.getByRole("option", { name: /\$CATE/ });
    const chip = within(row).getByText("2 caps differ");
    expect(chip.getAttribute("title")).toBe(note);
    // The paragraph itself never reaches the row face.
    expect(within(row).queryByText(/neither is averaged/i)).not.toBeInTheDocument();
  });

  it("renders the loud advance pill only when newer scenes exist, counting them honestly", async () => {
    const advance = vi.fn();
    const { container, rerender } = renderBoard({
      advanceNotice: { count: 3, derivedAt: "2026-08-22T18:03:00.000000Z", advance },
    });
    await waitFor(() => expect(container.querySelectorAll("[data-candidate-id]").length).toBe(2));

    const pill = screen.getByRole("button", { name: /3 newer scenes — advance/i });
    // The face states the fact that decides whether this board is still worth scanning; the
    // never-swaps-on-its-own assurance rides the notice's hover, verbatim, not a face sentence.
    expect(screen.getByText(/newest derived 18:03 UTC/i)).toBeInTheDocument();
    expect(document.querySelector(".advance-notice")?.getAttribute("title"))
      .toContain("Advancing is your act; this board never swaps on its own.");
    const user = userEvent.setup();
    await user.click(pill);
    expect(advance).toHaveBeenCalledTimes(1);

    // When the feed no longer lists the bound scene, how many are newer is not knowable,
    // and the pill does not claim a number.
    rerender(
      <AttentionFeed
        variant="board"
        candidates={[observedCoin, unobservedCoin]}
        selectedId={observedCoin.id}
        onSelect={() => {}}
        board="all"
        onBoardChange={() => {}}
        density="comfortable"
        focusRequest={0}
        advanceNotice={{ count: null, derivedAt: "2026-08-22T18:03:00.000000Z", advance }}
      />,
    );
    expect(screen.getByRole("button", { name: /newer scenes exist — advance/i })).toBeInTheDocument();
  });

  it("offers each column as a sort button cycling default direction, the opposite, then cleared", async () => {
    const onSortChange = vi.fn();
    const user = userEvent.setup();
    const { container, rerender } = renderBoard({ onSortChange });
    await waitFor(() => expect(container.querySelectorAll("[data-candidate-id]").length).toBe(2));

    // First click: the column's default direction (largest market cap first).
    await user.click(screen.getByRole("button", { name: /^sort by market cap$/i }));
    expect(onSortChange).toHaveBeenLastCalledWith({ column: "mcap", direction: "descending" });

    // With that sort applied, the header states it and the next click flips the direction.
    rerender(
      <AttentionFeed
        variant="board"
        candidates={[observedCoin, unobservedCoin]}
        selectedId={observedCoin.id}
        onSelect={() => {}}
        board="all"
        onBoardChange={() => {}}
        density="comfortable"
        focusRequest={0}
        renderedAtUnixMs={RENDERED_AT_MS}
        onSortChange={onSortChange}
        sort={{ column: "mcap", direction: "descending" }}
      />,
    );
    const active = screen.getByRole("button", { name: /sort by market cap, currently largest first/i });
    expect(active.getAttribute("aria-pressed")).toBe("true");
    await user.click(active);
    expect(onSortChange).toHaveBeenLastCalledWith({ column: "mcap", direction: "ascending" });

    // And from the non-default direction, the third click clears back to the tab's order.
    rerender(
      <AttentionFeed
        variant="board"
        candidates={[observedCoin, unobservedCoin]}
        selectedId={observedCoin.id}
        onSelect={() => {}}
        board="all"
        onBoardChange={() => {}}
        density="comfortable"
        focusRequest={0}
        renderedAtUnixMs={RENDERED_AT_MS}
        onSortChange={onSortChange}
        sort={{ column: "mcap", direction: "ascending" }}
      />,
    );
    await user.click(screen.getByRole("button", { name: /sort by market cap, currently smallest first/i }));
    expect(onSortChange).toHaveBeenLastCalledWith(null);

    // No %-change column beyond the served 5m move exists to sort by: the movers wire
    // asserts no per-window price change, so no header may imply one.
    expect(screen.queryByRole("button", { name: /1h.*%|6h|24h.*%/i })).not.toBeInTheDocument();
  });

  it("renders the image-first grid: art-led cards with candles, flow volume, or a stated dash", async () => {
    // A coin with movers flow but no price path, for the middle branch of the chart slot.
    const flowOnly = boardCandidate({
      id: "flowonly",
      mint: "FLOWONLYXXXXXXXXXXXXXXXXXXXXXXXX",
      symbol: "FLOW",
      description: "Volume but no tape.",
      chainId: "eip155:8453",
      flow: [
        { window: "1h", volumeSol: "5.0", volumeUsd: "900.00", txns: "40", traders: "12", serverTsUnixMs: String(RENDERED_AT_MS) },
      ],
    });
    const { container } = renderBoard({
      candidates: [observedCoin, flowOnly, unobservedCoin],
      layout: "grid",
      onLayoutChange: () => {},
    });
    await waitFor(() => expect(container.querySelectorAll("[data-candidate-id]").length).toBe(3));

    // The rows are still options in the same listbox — the grid changes what a row paints,
    // never the instrumentation architecture.
    expect(container.querySelector("[role='listbox']")).not.toBeNull();
    const wifCard = screen.getByRole("option", { name: /\$WIF/ });
    expect(wifCard.querySelector(".grid-card")).not.toBeNull();
    // The art leads, the thesis is the coin's own line, and CANDLES are plotted on the card.
    expect(wifCard.querySelector(".coin-art[data-size='card'] img")).not.toBeNull();
    expect(within(wifCard).getByText("A dog, but with a hat.")).toBeInTheDocument();
    expect(wifCard.querySelector(".candle-glyph rect")).not.toBeNull();
    expect(within(wifCard).getByText("live")).toBeInTheDocument();

    // Flow-only: no candles are invented; the slot plots claimed volume, labelled as volume.
    const flowCard = screen.getByRole("option", { name: /\$FLOW/ });
    // A non-Solana claim wears the LOUD chain chip on the card: a different venue, outside
    // every Solana-only instrument — never mistakable for a broken Solana coin.
    const chainChip = within(flowCard).getByText("eip155");
    expect(chainChip.getAttribute("title")).toContain("eip155:8453");
    expect(chainChip.getAttribute("title")).toContain("Solana-only");
    expect(flowCard.querySelector(".candle-glyph")).toBeNull();
    expect(flowCard.querySelector(".flow-glyph")).not.toBeNull();
    expect(flowCard.querySelector(".grid-chart")?.getAttribute("data-kind")).toBe("flow");
    expect(within(flowCard).getByText(/no price path was observed/i)).toBeInTheDocument();

    // Neither candles nor flow: the chart slot is a dash with its sentence, and the absent
    // thesis is a dash too — the card fabricates nothing to look full.
    const bareCard = screen.getByRole("option", { name: /14m1ke…/ });
    expect(bareCard.querySelector(".grid-chart")?.getAttribute("data-kind")).toBe("absent");
    expect(within(bareCard).getByText(/price path not observed/i)).toBeInTheDocument();
    expect(within(bareCard).getByText(/thesis not observed/i)).toBeInTheDocument();
    expect(bareCard.querySelector(".coin-art-monogram")).not.toBeNull();
  });

  it("renders the trending strip from served flow and opens a coin with one press", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    const { container } = renderBoard({ trending: [observedCoin], onOpen });
    await waitFor(() => expect(container.querySelectorAll("[data-candidate-id]").length).toBe(2));

    const strip = screen.getByRole("toolbar", { name: /trending by claimed 24-hour volume/i });
    // The basis is stated on the strip itself, as a provider-claim sentence.
    expect(strip.getAttribute("title")).toContain("provider-claimed 24-hour volume");
    const item = within(strip).getByRole("button", { name: /\$WIF/ });
    expect(within(item).getByText("A dog, but with a hat.")).toBeInTheDocument();
    expect(within(item).getByText("$23.1K")).toBeInTheDocument();
    await user.click(item);
    expect(onOpen).toHaveBeenCalledWith("wif");
  });
});
