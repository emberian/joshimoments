import type { Candidate } from "../contract/v1";
import type { BoardFilter } from "./AttentionFeed";
import { compareDecimal } from "./candlePath";
import { flowFor, trueAgeSeconds } from "./candidateFacts";

/**
 * What each board tab ACTUALLY does to the served candidate list, stated so the order on
 * screen is never mistaken for a market fact the scene did not serve.
 *
 * Two kinds of tab exist and they are deliberately different things:
 *
 * - The SORT tabs (`new`, `trending`) rank every served candidate by a metric the scene
 *   carries: observed age for New, the magnitude of the 5-minute move for Trending. A
 *   candidate the view states no such metric for is never silently treated as zero (which
 *   would promote it) and never dropped (which would hide a served coin): it follows the
 *   ranked ones in served order, and the basis line says how many did. When NO candidate
 *   carries the metric there is nothing to rank by, and the tab says so instead of dressing
 *   the served order up as a ranking.
 *
 * - The CATEGORY tabs (`live`, `callouts`, `watch`) filter to the candidates whose served
 *   `board` field makes that claim — a producer statement, not a client inference — and keep
 *   the served order within the category.
 *
 * Both are pure functions of one immutable scene's frozen display order, so within a scene a
 * tab's order can never change underneath the operator; only her own tab switch, or the
 * explicit acceptance of a re-served order, reorders anything.
 */
export type BoardView = {
  candidates: Candidate[];
  /** The sort or filter rule this tab applied, in words, for rendering next to the tabs. */
  basis: string;
};

function magnitude(value: string): bigint {
  const parsed = BigInt(value);
  return parsed < 0n ? -parsed : parsed;
}

/**
 * Rank by one served metric, ascending or descending, with metric-less candidates AFTER the
 * ranked ones in their served order. `Array.prototype.sort` is stable, so candidates whose
 * metric ties also keep their served order.
 */
function rankedByMetric(
  ordered: readonly Candidate[],
  metric: (candidate: Candidate) => string | null,
  direction: "ascending" | "descending",
): { candidates: Candidate[]; carrying: number; absent: number } {
  const carrying = ordered.filter((candidate) => metric(candidate) !== null);
  const absent = ordered.filter((candidate) => metric(candidate) === null);
  const sorted = [...carrying].sort((left, right) => {
    const leftValue = magnitude(metric(left) ?? "0");
    const rightValue = magnitude(metric(right) ?? "0");
    if (leftValue === rightValue) return 0;
    const ascending = leftValue < rightValue ? -1 : 1;
    return direction === "ascending" ? ascending : -ascending;
  });
  return { candidates: [...sorted, ...absent], carrying: carrying.length, absent: absent.length };
}

function sortBasis(
  ranking: { carrying: number; absent: number },
  ranked: string,
  metricAbsence: string,
  nothingToRank: string,
): string {
  if (ranking.carrying === 0) return nothingToRank;
  if (ranking.absent === 0) return `${ranked}.`;
  return `${ranked} · ${ranking.absent} without ${metricAbsence} follow in served order.`;
}

function categoryView(ordered: readonly Candidate[], board: Candidate["board"], basis: string): BoardView {
  return { candidates: ordered.filter((candidate) => candidate.board === board), basis };
}

export function boardView(ordered: readonly Candidate[], board: BoardFilter): BoardView {
  switch (board) {
    case "all":
      return {
        candidates: [...ordered],
        basis: "Served order: the scene's own ranks first, unranked coins after them.",
      };
    case "new": {
      const ranking = rankedByMetric(ordered, (candidate) => candidate.metrics.ageSeconds, "ascending");
      return {
        candidates: ranking.candidates,
        basis: sortBasis(
          ranking,
          "Youngest observed age first",
          "an observed age",
          "No coin in this scene carries an observed age, so there is no newness to rank by; served order is shown.",
        ),
      };
    }
    case "trending": {
      const ranking = rankedByMetric(ordered, (candidate) => candidate.metrics.change5mBps, "descending");
      return {
        candidates: ranking.candidates,
        basis: sortBasis(
          ranking,
          "Largest 5-minute move first, either direction",
          "an observed move",
          "No coin in this scene carries an observed 5-minute move, so there is no trend to rank by; served order is shown.",
        ),
      };
    }
    case "live":
      return categoryView(ordered, "live", "Only coins this scene's board marks live · served order.");
    case "callouts":
      return categoryView(ordered, "callouts", "Only coins a callout source named in this scene · served order.");
    case "watch":
      return categoryView(ordered, "watch", "Only coins on this scene's watch board · served order.");
  }
}

/**
 * The table's column sort: one more PURE lens over the tab's output, same discipline as the
 * tabs themselves. A clicked header ranks by exactly one served metric, compared as exact
 * decimals (never floats); a candidate the view states no such metric for follows the ranked
 * ones in the order the tab produced — never treated as zero, never dropped — and the basis
 * line says what happened, including that a column sort overrides a sort tab's own rank.
 * The columns are the ones the parity seam actually carries: there is deliberately no
 * per-window %-change column, because the movers wire asserts no per-window price change.
 */
export type SortColumnId =
  | "movers"
  | "age"
  | "mcap"
  | "ath"
  | "move5m"
  | "vol1h"
  | "vol24h"
  | "txns24h"
  | "traders24h"
  | "replies";

export type SortDirection = "descending" | "ascending";

export type BoardSort = { column: SortColumnId; direction: SortDirection };

type SortColumn = {
  /** The metric as an exact decimal string, or null when this view does not carry it. */
  metric(candidate: Candidate, renderedAtUnixMs: number | null): string | null;
  /** What the metric is, for the basis sentence's absence clause. */
  noun: string;
  /** The basis words for each direction, so the sentence states the actual order. */
  words: Record<SortDirection, string>;
  /** The direction the first click applies — the one the column's readers actually want. */
  defaultDirection: SortDirection;
};

export const SORT_COLUMNS: Record<SortColumnId, SortColumn> = {
  /**
   * The DEFAULT hunt order — pump's Movers shape, over what the wire actually serves. A
   * TIERED sort, not one metric: coins carrying a claimed 24h volume rank first (largest
   * first), coins without flow follow by market cap, then by 5-minute move magnitude, and
   * coins with none of these keep served order at the back. It exists because the raw served
   * order leads a real scene with no-ticker all-dash rows while the coins with data sit
   * buried; a default must lead with what a hunter can actually read. `metric` here only
   * answers "does any tier claim exist" (for the absent split); the tier ordering itself is
   * the special case in `applyBoardSort`.
   */
  movers: {
    metric: (candidate) =>
      flowFor(candidate, "24h")?.volumeUsd
        ?? candidate.metrics.marketCapUsd
        ?? candidate.metrics.change5mBps,
    noun: "a claimed 24h volume, market cap, or 5-minute move",
    words: {
      descending: "largest claimed 24h volume first, then flowless coins by market cap, then by 5-minute move",
      ascending: "smallest claimed 24h volume first, then flowless coins by market cap, then by 5-minute move (each smallest-first)",
    },
    defaultDirection: "descending",
  },
  age: {
    metric: (candidate, renderedAtUnixMs) => trueAgeSeconds(candidate, renderedAtUnixMs),
    noun: "a provider-claimed creation time",
    words: { ascending: "youngest coin first", descending: "oldest coin first" },
    defaultDirection: "ascending",
  },
  mcap: {
    metric: (candidate) => candidate.metrics.marketCapUsd,
    noun: "an observed market cap",
    words: { descending: "largest first", ascending: "smallest first" },
    defaultDirection: "descending",
  },
  ath: {
    metric: (candidate) => candidate.athMarketCapUsd ?? null,
    noun: "a provider-claimed all-time-high cap",
    words: { descending: "largest first", ascending: "smallest first" },
    defaultDirection: "descending",
  },
  move5m: {
    metric: (candidate) => candidate.metrics.change5mBps,
    noun: "an observed 5-minute move",
    words: { descending: "most positive first", ascending: "most negative first" },
    defaultDirection: "descending",
  },
  vol1h: {
    metric: (candidate) => flowFor(candidate, "1h")?.volumeUsd ?? null,
    noun: "a provider-claimed 1h volume",
    words: { descending: "largest first", ascending: "smallest first" },
    defaultDirection: "descending",
  },
  vol24h: {
    metric: (candidate) => flowFor(candidate, "24h")?.volumeUsd ?? null,
    noun: "a provider-claimed 24h volume",
    words: { descending: "largest first", ascending: "smallest first" },
    defaultDirection: "descending",
  },
  txns24h: {
    metric: (candidate) => flowFor(candidate, "24h")?.txns ?? null,
    noun: "a provider-claimed 24h trade count",
    words: { descending: "most trades first", ascending: "fewest trades first" },
    defaultDirection: "descending",
  },
  traders24h: {
    metric: (candidate) => flowFor(candidate, "24h")?.traders ?? null,
    noun: "a provider-claimed 24h trader count",
    words: { descending: "most traders first", ascending: "fewest traders first" },
    defaultDirection: "descending",
  },
  replies: {
    metric: (candidate) => candidate.replyCount ?? null,
    noun: "a provider-claimed reply count",
    words: { descending: "most replies first", ascending: "fewest replies first" },
    defaultDirection: "descending",
  },
};

/** What each column is called in the basis sentence. */
const SORT_COLUMN_PHRASE: Record<SortColumnId, string> = {
  movers: "movers",
  age: "true coin age",
  mcap: "market cap",
  ath: "claimed all-time-high cap",
  move5m: "5-minute move",
  vol1h: "claimed 1h volume (USD)",
  vol24h: "claimed 24h volume (USD)",
  txns24h: "claimed 24h trades",
  traders24h: "claimed 24h traders",
  replies: "claimed replies",
};

/** The filter clause a category tab keeps in front of a column sort's own sentence. */
const CATEGORY_CLAUSE: Partial<Record<BoardFilter, string>> = {
  live: "Only coins this scene's board marks live · ",
  callouts: "Only coins a callout source named in this scene · ",
  watch: "Only coins on this scene's watch board · ",
};

/** The board's landing order: the Movers-shaped tiered default, headed and clearable. */
export const DEFAULT_BOARD_SORT: BoardSort = { column: "movers", direction: "descending" };

/**
 * The movers tier for one candidate: which claim ranks it and the exact decimal it ranks by.
 * Tier 0 claimed 24h volume, tier 1 market cap, tier 2 the 5-minute move's MAGNITUDE (a deep
 * dump is as alive as a pump — the same reading Trending uses). Null: no tier claim at all.
 */
function moversTier(candidate: Candidate): { tier: number; value: string } | null {
  const volume = flowFor(candidate, "24h")?.volumeUsd;
  if (volume !== undefined) return { tier: 0, value: volume };
  if (candidate.metrics.marketCapUsd !== null) return { tier: 1, value: candidate.metrics.marketCapUsd };
  if (candidate.metrics.change5mBps !== null) {
    return { tier: 2, value: candidate.metrics.change5mBps.replace(/^-/, "") };
  }
  return null;
}

export function applyBoardSort(
  view: BoardView,
  board: BoardFilter,
  sort: BoardSort | null,
  renderedAtUnixMs: number | null,
): BoardView {
  if (sort === null) return view;
  const column = SORT_COLUMNS[sort.column];
  const carrying = view.candidates.filter((candidate) => column.metric(candidate, renderedAtUnixMs) !== null);
  const absent = view.candidates.filter((candidate) => column.metric(candidate, renderedAtUnixMs) === null);
  const sorted = sort.column === "movers"
    ? [...carrying].sort((left, right) => {
        const a = moversTier(left);
        const b = moversTier(right);
        if (a === null || b === null) return 0; // unreachable: carrying implies a tier claim
        if (a.tier !== b.tier) return a.tier - b.tier;
        const order = compareDecimal(a.value, b.value);
        return sort.direction === "ascending" ? order : -order;
      })
    : [...carrying].sort((left, right) => {
        const order = compareDecimal(
          column.metric(left, renderedAtUnixMs) ?? "0",
          column.metric(right, renderedAtUnixMs) ?? "0",
        );
        return sort.direction === "ascending" ? order : -order;
      });
  const sentence = sort.column === "movers"
    ? `Movers: ${column.words[sort.direction]}`
    : `Sorted by ${SORT_COLUMN_PHRASE[sort.column]}, ${column.words[sort.direction]}`;
  const absence = absent.length === 0 ? "" : ` · ${absent.length} without ${column.noun} follow in prior order`;
  const override = board === "new" || board === "trending" ? " (overrides this tab's own rank)" : "";
  return {
    candidates: [...sorted, ...absent],
    basis: `${CATEGORY_CLAUSE[board] ?? ""}${sentence}${absence}${override}.`,
  };
}
