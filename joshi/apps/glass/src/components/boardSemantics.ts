import type { Candidate } from "../contract/v1";
import type { BoardFilter } from "./AttentionFeed";

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
