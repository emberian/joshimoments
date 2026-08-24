"""Logistic regression, the declared stand-in for gradient-boosted trees.

The locked environment ships neither xgboost nor lightgbm nor sklearn, and this package adds
no heavy dependencies; the registration therefore declares an L2-regularized logistic
regression on the same shared feature vectors. Fit by IRLS (Newton) with a Cholesky solve —
deterministic, a couple of dozen iterations, no learning-rate folklore.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .linalg import cholesky_solve, standardize_apply, standardize_fit
from .vocabulary import LOGIT_L2, LOGIT_MAX_ITER, LOGIT_TOL

_CLIP = 1e-9


@dataclass(frozen=True)
class LogisticModel:
    means: tuple[float, ...]
    stds: tuple[float, ...]
    weights: tuple[float, ...]  # per standardized feature
    bias: float
    iterations: int
    converged: bool

    def predict_proba(self, vectors: list[list[float]]) -> list[float]:
        standardized = standardize_apply(vectors, list(self.means), list(self.stds))
        out = []
        for row in standardized:
            z = self.bias + sum(w * x for w, x in zip(self.weights, row, strict=True))
            out.append(_sigmoid(z))
        return out

    def params(self) -> dict:
        return {
            "family": "logit",
            "means": list(self.means),
            "stds": list(self.stds),
            "weights": list(self.weights),
            "bias": self.bias,
            "l2": LOGIT_L2,
            "iterations": self.iterations,
            "converged": self.converged,
        }


def fit_logistic(
    vectors: list[list[float]],
    labels: list[int],
    l2: float = LOGIT_L2,
    max_iter: int = LOGIT_MAX_ITER,
    tol: float = LOGIT_TOL,
) -> LogisticModel:
    if len(vectors) != len(labels) or not vectors:
        raise ValueError("vectors and labels must be non-empty and aligned")
    means, stds = standardize_fit(vectors)
    x = standardize_apply(vectors, means, stds)
    d = len(means)
    beta = [0.0] * (d + 1)  # weights then bias
    iterations = 0
    converged = False
    for _ in range(max_iter):
        iterations += 1
        gradient = [0.0] * (d + 1)
        hessian = [[0.0] * (d + 1) for _ in range(d + 1)]
        for row, label in zip(x, labels, strict=True):
            z = beta[d] + sum(beta[j] * row[j] for j in range(d))
            p = _sigmoid(z)
            p = min(max(p, _CLIP), 1.0 - _CLIP)
            residual = label - p
            s = p * (1.0 - p)
            for j in range(d):
                gradient[j] += residual * row[j]
                hj = s * row[j]
                for k in range(j + 1):
                    hessian[j][k] += hj * row[k]
                hessian[d][j] += s * row[j]
            gradient[d] += residual
            hessian[d][d] += s
        for j in range(d):  # L2 on weights, never on the bias
            gradient[j] -= l2 * beta[j]
            hessian[j][j] += l2
        for j in range(d + 1):  # mirror the lower triangle
            for k in range(j + 1, d + 1):
                hessian[j][k] = hessian[k][j]
        for j in range(d + 1):
            hessian[j][j] += 1e-10
        try:
            delta = cholesky_solve(hessian, gradient)
        except ArithmeticError:
            break
        for j in range(d + 1):
            beta[j] += delta[j]
        if max(abs(v) for v in delta) < tol:
            converged = True
            break
    return LogisticModel(
        means=tuple(means),
        stds=tuple(stds),
        weights=tuple(beta[:d]),
        bias=beta[d],
        iterations=iterations,
        converged=converged,
    )


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)
