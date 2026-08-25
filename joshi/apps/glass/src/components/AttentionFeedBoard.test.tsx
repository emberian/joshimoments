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
      {...extra}
    />,
  );
}

describe("hunt board rows", () => {
  it("renders the glanceable facts and keeps every absence explicit, never a fake zero", async () => {
    const { container } = renderBoard({ boardBasis: "Served order: the scene's own ranks first, unranked coins after them." });
    await waitFor(() => expect(container.querySelectorAll("[data-candidate-id]").length).toBe(2));

    // The observed coin: ticker behind its $, name, compact market cap, signed colored move,
    // compact age, and a sparkline because it carries a price path.
    const observedRow = screen.getByRole("option", { name: /\$WIF/ });
    expect(within(observedRow).getByText("dogwifhat")).toBeInTheDocument();
    expect(within(observedRow).getByText("$208.4K")).toBeInTheDocument();
    expect(within(observedRow).getByText("+7.41%")).toBeInTheDocument();
    expect(within(observedRow).getByText("13m")).toBeInTheDocument();
    expect(observedRow.querySelector(".sparkline")).not.toBeNull();

    // The unobserved coin: the mint's leading characters stand in without a $, the "no
    // ticker" chip says why, and the absent figures are dashes whose words survive for
    // readers and on hover — never a rendered zero, and no sparkline is invented.
    const bareRow = screen.getByRole("option", { name: /14m1ke…/ });
    expect(within(bareRow).getByText(/no ticker/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/market cap not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/5-minute move not observed/i)).toBeInTheDocument();
    expect(within(bareRow).getByText(/coin age not observed/i)).toBeInTheDocument();
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
});
