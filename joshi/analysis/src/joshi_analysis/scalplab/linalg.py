"""Tiny pure-Python numerics the zoo shares: standardization, Cholesky, Nelder-Mead.

The locked analysis environment ships no numpy; every matrix here is a list of lists and
every solver is written for the small sizes this package actually uses (feature vectors of
~15, Hawkes parameter vectors of 7).
"""

from __future__ import annotations

import math
from collections.abc import Callable


def standardize_fit(vectors: list[list[float]]) -> tuple[list[float], list[float]]:
    """Per-column mean and std (population), std floored at a tiny epsilon."""
    if not vectors:
        raise ValueError("cannot standardize an empty matrix")
    d = len(vectors[0])
    n = len(vectors)
    means = [sum(v[j] for v in vectors) / n for j in range(d)]
    stds = []
    for j in range(d):
        var = sum((v[j] - means[j]) ** 2 for v in vectors) / n
        stds.append(math.sqrt(var) if var > 1e-24 else 1.0)
    return means, stds


def standardize_apply(
    vectors: list[list[float]], means: list[float], stds: list[float]
) -> list[list[float]]:
    return [[(v[j] - means[j]) / stds[j] for j in range(len(means))] for v in vectors]


def cholesky_solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Solve ``matrix @ x = rhs`` for symmetric positive-definite ``matrix``."""
    n = len(matrix)
    lower = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            acc = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if acc <= 0.0:
                    raise ArithmeticError("matrix is not positive definite")
                lower[i][j] = math.sqrt(acc)
            else:
                lower[i][j] = acc / lower[j][j]
    # forward then backward substitution
    y = [0.0] * n
    for i in range(n):
        y[i] = (rhs[i] - sum(lower[i][k] * y[k] for k in range(i))) / lower[i][i]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (y[i] - sum(lower[k][i] * x[k] for k in range(i + 1, n))) / lower[i][i]
    return x


def nelder_mead(
    objective: Callable[[list[float]], float],
    start: list[float],
    budget: int,
    initial_step: float = 0.5,
) -> tuple[list[float], float]:
    """Minimize ``objective`` with a classic Nelder-Mead simplex under an eval budget."""
    n = len(start)
    evals = 0

    def call(x: list[float]) -> float:
        nonlocal evals
        evals += 1
        value = objective(x)
        return value if math.isfinite(value) else float("inf")

    simplex = [list(start)]
    for i in range(n):
        point = list(start)
        point[i] += initial_step
        simplex.append(point)
    values = [call(p) for p in simplex]
    while evals < budget:
        order = sorted(range(n + 1), key=lambda idx: values[idx])
        simplex = [simplex[idx] for idx in order]
        values = [values[idx] for idx in order]
        centroid = [sum(p[j] for p in simplex[:-1]) / n for j in range(n)]
        worst = simplex[-1]
        reflected = [centroid[j] + (centroid[j] - worst[j]) for j in range(n)]
        r_val = call(reflected)
        if r_val < values[0]:
            expanded = [centroid[j] + 2.0 * (centroid[j] - worst[j]) for j in range(n)]
            e_val = call(expanded)
            if e_val < r_val:
                simplex[-1], values[-1] = expanded, e_val
            else:
                simplex[-1], values[-1] = reflected, r_val
        elif r_val < values[-2]:
            simplex[-1], values[-1] = reflected, r_val
        else:
            contracted = [centroid[j] + 0.5 * (worst[j] - centroid[j]) for j in range(n)]
            c_val = call(contracted)
            if c_val < values[-1]:
                simplex[-1], values[-1] = contracted, c_val
            else:  # shrink toward the best point
                best = simplex[0]
                for i in range(1, n + 1):
                    simplex[i] = [best[j] + 0.5 * (simplex[i][j] - best[j]) for j in range(n)]
                    values[i] = call(simplex[i])
    best_idx = min(range(n + 1), key=lambda idx: values[idx])
    return simplex[best_idx], values[best_idx]
