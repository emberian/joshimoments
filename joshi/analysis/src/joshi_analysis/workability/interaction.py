"""The interaction test: rank statistics against outcomes, with the multiplicity stated.

Spearman rank correlation with average ranks for ties, permutation p-values from a seeded
generator, and the decile contrast (top decile by statistic vs a seeded random control).
Pure Python, deterministic under its declared seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

PERMUTATIONS = 10_000


def average_ranks(values: list[float]) -> list[float]:
    """1-based ranks, ties sharing their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        upper = index
        while upper + 1 < len(order) and values[order[upper + 1]] == values[order[index]]:
            upper += 1
        mean_rank = (index + upper) / 2 + 1
        for position in range(index, upper + 1):
            ranks[order[position]] = mean_rank
        index = upper + 1
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return cov / (var_x**0.5 * var_y**0.5)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rho; None when either side is degenerate or n < 3."""
    if len(xs) != len(ys):
        raise ValueError("paired samples must have equal length")
    return _pearson(average_ranks(xs), average_ranks(ys))


@dataclass(frozen=True)
class CorrelationResult:
    n: int
    rho: float | None
    p_permutation: float | None  # two-sided, None when rho is None
    n_permutations: int


def spearman_with_permutation(
    xs: list[float], ys: list[float], seed: int, permutations: int = PERMUTATIONS
) -> CorrelationResult:
    """Two-sided permutation p for Spearman rho, shuffling y under a seeded generator."""
    rho = spearman(xs, ys)
    if rho is None:
        return CorrelationResult(n=len(xs), rho=None, p_permutation=None, n_permutations=0)
    generator = random.Random(seed)
    shuffled = list(ys)
    at_least = 0
    for _ in range(permutations):
        generator.shuffle(shuffled)
        draw = spearman(xs, shuffled)
        if draw is not None and abs(draw) >= abs(rho):
            at_least += 1
    return CorrelationResult(
        n=len(xs),
        rho=rho,
        p_permutation=(at_least + 1) / (permutations + 1),
        n_permutations=permutations,
    )


@dataclass(frozen=True)
class DecileContrast:
    n_top: int
    n_control: int
    median_top: float | None
    median_control: float | None
    difference: float | None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def decile_contrast(
    statistic: list[float], outcome: list[float], seed: int
) -> DecileContrast:
    """Median outcome of the top decile by statistic vs a seeded random control of equal n.

    The control is drawn from the coins OUTSIDE the top decile, without replacement, so the
    contrast is selection-vs-not rather than selection-vs-including-itself.
    """
    if len(statistic) != len(outcome):
        raise ValueError("paired samples must have equal length")
    n = len(statistic)
    top_n = max(1, n // 10)
    order = sorted(range(n), key=lambda i: statistic[i], reverse=True)
    top = order[:top_n]
    rest = order[top_n:]
    generator = random.Random(seed)
    control = generator.sample(rest, min(top_n, len(rest))) if rest else []
    median_top = median([outcome[i] for i in top])
    median_control = median([outcome[i] for i in control])
    return DecileContrast(
        n_top=len(top),
        n_control=len(control),
        median_top=median_top,
        median_control=median_control,
        difference=(
            median_top - median_control
            if median_top is not None and median_control is not None
            else None
        ),
    )
