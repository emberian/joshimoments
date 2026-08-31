"""The degree-preserving null, REUSED from the code that validated the shipped instrument.

This module deliberately contains no randomisation of its own. ``studies.operator_crime.
_curveball`` is the Strona et al. trade that holds every row degree and every column degree
of a bipartite incidence exactly fixed; it is the null behind ``graph.json``'s
``curveball_null_mean = 0.0075``, behind ``cluster_map``'s 300-pair territory test, and
behind ``RESULT_svn_cotrading.md`` section 5's demonstration that a popularity-only null
validates ~99 false edges per world on data with zero planted coordination while this one
deletes 100% of them.

Writing a second curveball here would be exactly the mirror this project keeps paying for:
a lane reconstructs an interface from prose, verifies against its own reconstruction, and
ships something that is green in a scratchpad. So this file is an ADAPTER -- ``Assoc`` in,
``Assoc`` out, with the trade itself imported.

MIXING BUDGET. ``cluster_map`` uses ``20 * n_rows`` trades per draw and ``operator_crime``
uses ``5 * n_rows``. Both are cited; this lane defaults to ``20 * n_rows`` (the stricter of
the two) and records the multiplier in every artifact, because a null that was not mixed is
a null that reports the observed value back to you.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from dregg_d4m.assoc import Assoc

TRADES_PER_ROW = 20


def randomise(a: Assoc, rng: np.random.Generator, *, trades_per_row: int = TRADES_PER_ROW) -> Assoc:
    """One degree-preserving draw. Row keys, column keys, every row degree and every column
    degree are identical to the input; only WHICH cell is filled changes."""

    from studies.operator_crime import _curveball  # the null this repo already paid for

    rows = a.row_sets()
    randomised = _curveball(rows, trades_per_row * max(len(rows), 1), rng)
    return Assoc.from_row_sets(randomised, a.row, a.col)


@dataclass(frozen=True, slots=True)
class NullResult:
    """An observed statistic against its curveball distribution."""

    observed: float
    draws: tuple[float, ...]
    trades_per_row: int
    seed: int

    @property
    def mean(self) -> float:
        return float(np.mean(self.draws)) if self.draws else float("nan")

    @property
    def p95(self) -> float:
        return float(np.quantile(self.draws, 0.95)) if self.draws else float("nan")

    @property
    def p_value(self) -> float:
        """One-sided empirical p: share of draws at least as extreme as observed. Floored at
        ``1 / (B + 1)`` in the REPORT, never below -- see RESULT_svn_cotrading section 4.2 on
        why an empirical p cannot be thresholded past its own floor."""

        if not self.draws:
            return float("nan")
        return float(np.mean(np.asarray(self.draws) >= self.observed))

    @property
    def p_floor(self) -> float:
        return 1.0 / (len(self.draws) + 1)

    @property
    def ratio(self) -> float:
        m = self.mean
        return float(self.observed / m) if m else float("inf")

    @property
    def z(self) -> float:
        arr = np.asarray(self.draws, dtype=float)
        sd = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
        return float((self.observed - arr.mean()) / sd) if sd > 0 else float("nan")

    def to_json(self) -> dict[str, Any]:
        return {
            "observed": self.observed,
            "null_mean": self.mean,
            "null_p95": self.p95,
            "null_sd": float(np.std(self.draws, ddof=1)) if len(self.draws) > 1 else 0.0,
            "p_empirical": self.p_value,
            "p_floor": self.p_floor,
            "ratio_over_null": self.ratio,
            "z": self.z,
            "draws": len(self.draws),
            "trades_per_row": self.trades_per_row,
            "seed": self.seed,
        }


def against_null(
    a: Assoc,
    statistic: Callable[[Assoc], float],
    *,
    draws: int,
    seed: int,
    trades_per_row: int = TRADES_PER_ROW,
    progress: Callable[[int], None] | None = None,
) -> NullResult:
    """Compute ``statistic`` on ``a`` and on ``draws`` degree-preserving randomisations.

    Each draw restarts from the OBSERVED incidence rather than continuing one chain, which is
    what ``cluster_map`` does; a continued chain gives correlated draws and an optimistic
    tail."""

    rng = np.random.default_rng(seed)
    observed = float(statistic(a))
    out: list[float] = []
    for i in range(draws):
        out.append(float(statistic(randomise(a, rng, trades_per_row=trades_per_row))))
        if progress is not None:
            progress(i + 1)
    return NullResult(observed, tuple(out), trades_per_row, seed)


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson 95% interval. Used everywhere a rate is reported, because a rate with no
    interval is a number pretending to be evidence."""

    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mean_jaccard_over_pairs(a: Assoc, pairs: Sequence[tuple[int, int]]) -> float:
    """Mean Jaccard over a FIXED list of row-index pairs.

    The pair list is an argument, not derived from ``a``, so the same pairs are scored on the
    observed incidence and on every randomisation -- which is what makes the comparison a
    null on the STRUCTURE rather than on the sampling."""

    if not pairs:
        return float("nan")
    sets = a.row_sets()
    total = 0.0
    for i, j in pairs:
        left, right = sets[i], sets[j]
        union = len(left | right)
        if union:
            total += len(left & right) / union
    return total / len(pairs)
