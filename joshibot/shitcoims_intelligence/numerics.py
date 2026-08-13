"""Numeric kernels the roommate stack actually earned.

Reimplemented here — no roommate crate import. Units are 0..1 unless noted.
These are the pieces I skipped earlier: holder concentration, BH-FDR, DSR.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

EULER_GAMMA = 0.5772156649015329


@dataclass(frozen=True, slots=True)
class Concentration:
    holders: int
    top1: float
    top10: float
    top20: float
    gini: float
    hhi: float
    nakamoto: int
    median: float
    mean: float


def gini(values: Sequence[float]) -> float:
    xs = sorted(value for value in values if value > 0)
    n = len(xs)
    total = sum(xs)
    if n == 0 or total <= 0:
        return 0.0
    weighted = sum((index + 1) * value for index, value in enumerate(xs))
    return (2.0 * weighted) / (n * total) - (n + 1.0) / n


def hhi(values: Sequence[float]) -> float:
    xs = [value for value in values if value > 0]
    total = sum(xs)
    if total <= 0:
        return 0.0
    return sum((value / total) ** 2 for value in xs)


def nakamoto(values: Sequence[float], *, threshold: float = 0.5) -> int:
    xs = sorted((value for value in values if value > 0), reverse=True)
    total = sum(xs)
    if total <= 0:
        return 0
    acc = 0.0
    for index, value in enumerate(xs, 1):
        acc += value
        if acc >= threshold * total:
            return index
    return len(xs)


def concentration(balances: Sequence[float]) -> Concentration:
    xs = sorted((value for value in balances if value > 0), reverse=True)
    n = len(xs)
    total = sum(xs)
    if n == 0 or total <= 0:
        return Concentration(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0)

    def top(count: int) -> float:
        return sum(xs[:count]) / total

    return Concentration(
        holders=n,
        top1=top(1),
        top10=top(10),
        top20=top(20),
        gini=gini(xs),
        hhi=hhi(xs),
        nakamoto=nakamoto(xs),
        median=xs[n // 2],
        mean=total / n,
    )


def holder_veto(conc: Concentration) -> bool:
    """Serial-rug shape: one wallet or a tiny cabal owns the float."""

    if conc.holders == 0:
        return False
    return conc.top1 >= 0.35 or conc.nakamoto == 1 or conc.hhi >= 0.40


def benjamini_hochberg(p_values: Sequence[float], *, q: float = 0.05) -> tuple[bool, ...]:
    """BH FDR discoveries. Rejects the largest i with p_(i) <= (i/m) q."""

    m = len(p_values)
    if m == 0:
        return ()
    if not 0 < q < 1:
        raise ValueError("q must be in (0, 1)")
    ordered = sorted(enumerate(float(p) for p in p_values), key=lambda item: item[1])
    cutoff = -1
    for rank, (_, p_value) in enumerate(ordered, 1):
        if p_value <= (rank / m) * q:
            cutoff = rank
    keep = [False] * m
    for rank, (index, _) in enumerate(ordered, 1):
        if rank <= cutoff:
            keep[index] = True
    return tuple(keep)


def deflated_sharpe(
    observed: float,
    *,
    trials: int,
    n_obs: int,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
) -> dict[str, float | bool]:
    """Bailey-Lopez de Prado DSR, simplified. trials=1 leaves Sharpe untouched."""

    if trials < 1 or n_obs < 2:
        return {
            "observed_sharpe": observed,
            "deflated_sharpe": observed,
            "expected_max_sharpe": 0.0,
            "is_significant": False,
        }
    n = float(trials)
    expected_max = 0.0
    if n > 1:
        log_n = math.log(n)
        expected_max = math.sqrt(2.0 * log_n) * (1.0 - EULER_GAMMA)
        tail = 2.0 * log_n - math.log(4.0 * math.pi)
        if tail > 0:
            expected_max += EULER_GAMMA * math.sqrt(tail)
    variance_term = (
        1.0 - skewness * observed + (excess_kurtosis + 2.0) / 4.0 * observed * observed
    ) / n_obs
    se = math.sqrt(max(variance_term, 1e-12))
    deflated = (observed - expected_max) / se
    return {
        "observed_sharpe": observed,
        "deflated_sharpe": deflated,
        "expected_max_sharpe": expected_max,
        "is_significant": deflated > 1.645,
    }
