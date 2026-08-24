"""Bivariate exponential-kernel Hawkes on the buy and sell streams.

Intensity of stream ``x`` (buy or sell)::

    lambda_x(t) = mu_x + beta * sum_y a_xy * g_y(t)
    g_y(t)      = sum_{t_j^y < t} exp(-beta * (t - t_j^y))

so each kernel ``a_xy * beta * exp(-beta s)`` integrates to ``a_xy`` and the branching matrix
is exactly ``[[a_bb, a_bs], [a_sb, a_ss]]``; its spectral radius is the branching ratio — the
regime dial. Log-likelihood is the standard O(n) recursion; the MLE runs Nelder-Mead in
log-parameter space under a declared evaluation budget. Equal timestamps are dithered by
``+j * HAWKES_TIE_DITHER_S`` in tape order — a declared fabrication a 1-second-precision
polled tape needs and a socket tape rarely triggers.

The probability head (``HawkesClassifier``) maps the two causal log-intensities at each event
to the shared floor-clearing label via the package's logistic fit: the kernel is estimated by
MLE on train coins, the link is calibrated on train labels, and both are applied causally to
a judged coin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .linalg import nelder_mead
from .logit import LogisticModel, fit_logistic
from .vocabulary import HAWKES_EVAL_BUDGET, HAWKES_TIE_DITHER_S, HAWKES_WINDOW_EVENTS

BUY = 0
SELL = 1

Sequence = tuple[list[float], list[int]]  # (strictly increasing seconds, marks)


@dataclass(frozen=True)
class HawkesParams:
    mu_buy: float
    mu_sell: float
    a_buy_buy: float  # effect of past buys on buy intensity
    a_buy_sell: float  # effect of past sells on buy intensity
    a_sell_buy: float
    a_sell_sell: float
    beta: float

    def branching_ratio(self) -> float:
        trace = self.a_buy_buy + self.a_sell_sell
        det = self.a_buy_buy * self.a_sell_sell - self.a_buy_sell * self.a_sell_buy
        disc = trace * trace - 4.0 * det
        if disc < 0.0:  # cannot happen for non-negative entries, kept for arithmetic safety
            return trace / 2.0
        return (trace + math.sqrt(disc)) / 2.0

    def as_dict(self) -> dict:
        return {
            "muBuy": self.mu_buy,
            "muSell": self.mu_sell,
            "aBuyBuy": self.a_buy_buy,
            "aBuySell": self.a_buy_sell,
            "aSellBuy": self.a_sell_buy,
            "aSellSell": self.a_sell_sell,
            "beta": self.beta,
            "branchingRatio": self.branching_ratio(),
        }


def dither_times(times_s: list[float]) -> list[float]:
    """Strictly increasing copy: ties pushed forward by the declared dither, in tape order."""
    out: list[float] = []
    previous = -math.inf
    for t in times_s:
        if t <= previous:
            t = previous + HAWKES_TIE_DITHER_S
        out.append(t)
        previous = t
    return out


def hawkes_loglik(sequence: Sequence, params: HawkesParams) -> float:
    times, marks = sequence
    if not times:
        return 0.0
    mus = (params.mu_buy, params.mu_sell)
    a = (
        (params.a_buy_buy, params.a_buy_sell),
        (params.a_sell_buy, params.a_sell_sell),
    )
    beta = params.beta
    start = times[0]
    horizon = times[-1] - start
    g = [0.0, 0.0]
    previous = start
    loglik = 0.0
    tail = [0.0, 0.0]  # sum over events of (1 - exp(-beta * (T - t_j))) per source stream
    for t, mark in zip(times, marks, strict=True):
        decay = math.exp(-beta * (t - previous))
        g[0] *= decay
        g[1] *= decay
        intensity = mus[mark] + beta * (a[mark][0] * g[0] + a[mark][1] * g[1])
        if intensity <= 0.0:
            return -math.inf
        loglik += math.log(intensity)
        g[mark] += 1.0
        tail[mark] += 1.0 - math.exp(-beta * (times[-1] - t))
        previous = t
    compensator = horizon * (mus[0] + mus[1])
    compensator += (a[0][0] + a[1][0]) * tail[0]  # past buys excite both streams
    compensator += (a[0][1] + a[1][1]) * tail[1]
    return loglik - compensator


@dataclass(frozen=True)
class HawkesFit:
    params: HawkesParams
    loglik: float
    n_events: int
    n_sequences: int


def fit_hawkes(sequences: list[Sequence], budget: int = HAWKES_EVAL_BUDGET) -> HawkesFit:
    """MLE over one or more event sequences (summed log-likelihood, shared parameters)."""
    sequences = [seq for seq in sequences if len(seq[0]) >= 2]
    if not sequences:
        raise ValueError("no sequence with at least two events")
    total_events = sum(len(seq[0]) for seq in sequences)
    total_span = sum(seq[0][-1] - seq[0][0] for seq in sequences)
    base_rate = max(total_events / total_span, 1e-9) if total_span > 0 else 1.0

    def objective(log_params: list[float]) -> float:
        params = _from_log(log_params)
        return -sum(hawkes_loglik(seq, params) for seq in sequences)

    start = [
        math.log(base_rate / 4.0),
        math.log(base_rate / 4.0),
        math.log(0.3),
        math.log(0.1),
        math.log(0.1),
        math.log(0.3),
        math.log(1.0),
    ]
    best, value = nelder_mead(objective, start, budget=budget)
    return HawkesFit(
        params=_from_log(best),
        loglik=-value,
        n_events=total_events,
        n_sequences=len(sequences),
    )


def intensity_features(sequence: Sequence, params: HawkesParams) -> list[list[float]]:
    """Causal ``[log lambda_buy, log lambda_sell]`` at each event instant (pre-event)."""
    times, marks = sequence
    beta = params.beta
    g = [0.0, 0.0]
    previous = times[0] if times else 0.0
    out: list[list[float]] = []
    for t, mark in zip(times, marks, strict=True):
        decay = math.exp(-beta * (t - previous))
        g[0] *= decay
        g[1] *= decay
        lam_buy = params.mu_buy + beta * (params.a_buy_buy * g[0] + params.a_buy_sell * g[1])
        lam_sell = params.mu_sell + beta * (params.a_sell_buy * g[0] + params.a_sell_sell * g[1])
        out.append([math.log(max(lam_buy, 1e-12)), math.log(max(lam_sell, 1e-12))])
        g[mark] += 1.0
        previous = t
    return out


@dataclass(frozen=True)
class WindowBranching:
    start_index: int
    n_events: int
    branching_ratio: float
    beta: float


def windowed_branching(
    sequence: Sequence,
    window: int = HAWKES_WINDOW_EVENTS,
    budget: int = HAWKES_EVAL_BUDGET,
) -> list[WindowBranching]:
    """Refit per non-overlapping window of ``window`` events; the per-window regime dial."""
    times, marks = sequence
    out: list[WindowBranching] = []
    for start in range(0, len(times) - window + 1, window):
        chunk: Sequence = (times[start : start + window], marks[start : start + window])
        fit = fit_hawkes([chunk], budget=budget)
        out.append(
            WindowBranching(
                start_index=start,
                n_events=window,
                branching_ratio=fit.params.branching_ratio(),
                beta=fit.params.beta,
            )
        )
    return out


@dataclass(frozen=True)
class HawkesClassifier:
    kernel: HawkesParams
    head: LogisticModel

    def predict_proba(self, sequence: Sequence, indices: list[int]) -> list[float]:
        features = intensity_features(sequence, self.kernel)
        return self.head.predict_proba([features[i] for i in indices])

    def params(self) -> dict:
        return {
            "family": "hawkes",
            "kernel": self.kernel.as_dict(),
            "head": self.head.params(),
        }


def fit_hawkes_classifier(
    train: list[tuple[Sequence, list[int], list[int]]],
    budget: int = HAWKES_EVAL_BUDGET,
) -> HawkesClassifier:
    """Kernel by MLE, link by logistic fit, both on train coins only.

    ``train`` holds ``(sequence, labeled_indices, labels)`` per train series.
    """
    fit = fit_hawkes([seq for seq, _, _ in train], budget=budget)
    head_vectors: list[list[float]] = []
    head_labels: list[int] = []
    for sequence, indices, labels in train:
        features = intensity_features(sequence, fit.params)
        head_vectors.extend(features[i] for i in indices)
        head_labels.extend(labels)
    head = fit_logistic(head_vectors, head_labels)
    return HawkesClassifier(kernel=fit.params, head=head)


def _from_log(log_params: list[float]) -> HawkesParams:
    clipped = [min(value, 30.0) for value in log_params]
    return HawkesParams(
        mu_buy=math.exp(clipped[0]),
        mu_sell=math.exp(clipped[1]),
        a_buy_buy=math.exp(clipped[2]),
        a_buy_sell=math.exp(clipped[3]),
        a_sell_buy=math.exp(clipped[4]),
        a_sell_sell=math.exp(clipped[5]),
        beta=math.exp(clipped[6]),
    )
