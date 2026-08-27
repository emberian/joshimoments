"""Exponential-kernel Hawkes on the trade-arrival series — the reflexivity gauge.

Model: lambda(t) = mu + eta * beta * sum_{t_i < t} exp(-beta (t - t_i)); the kernel
integrates to eta, so eta IS the branching ratio (expected children per event; eta -> 1
reads as critical/reflexive). Fitted by EM with O(N) recursions (registration v1.4):

    A_i = sum_{j<i} exp(-beta (t_i - t_j))        A_i = e^{-b d}(1 + A_{i-1})
    B_i = sum_{j<i} (t_i - t_j) exp(-beta (...))  B_i = e^{-b d}(B_{i-1} + d (1 + A_{i-1}))

E-step: background responsibility phi_i = mu / lambda_i. M-step: mu' = sum(phi)/T,
eta' = sum(1 - phi)/N (edge correction O(1/(beta*T)) ignored and stated),
beta' = sum(1 - phi) / sum_i eta*beta*B_i/lambda_i (triggered count / triggered lag mass).

The EXCITATION features hx_10/hx_60 use FIXED timescales (split-independent by
construction); the fitted (mu, eta, beta) is a reported finding, never a feature.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from math import exp, log


@dataclass(frozen=True)
class HawkesFit:
    mu: float
    eta: float  # branching ratio
    beta: float
    log_likelihood: float
    poisson_log_likelihood: float
    iterations: int
    n_events: int
    span_s: float

    @property
    def timescale_s(self) -> float:
        return 1.0 / self.beta

    def as_dict(self) -> dict:
        return {
            "mu": self.mu,
            "branchingRatio": self.eta,
            "beta": self.beta,
            "timescaleS": self.timescale_s,
            "logLikelihood": self.log_likelihood,
            "poissonLogLikelihood": self.poisson_log_likelihood,
            "llGainPerEvent": (self.log_likelihood - self.poisson_log_likelihood)
            / self.n_events
            if self.n_events
            else None,
            "iterations": self.iterations,
            "nEvents": self.n_events,
            "spanS": self.span_s,
            "edgeCorrectionNote": "eta M-step uses N in the denominator; the boundary "
            "term is O(1/(beta*span)) and negligible at these timescales",
        }


def _log_likelihood(times: list[float], t0: float, t1: float, mu: float, eta: float,
                    beta: float) -> float:
    ll = 0.0
    a_prev = 0.0
    prev_t = None
    for t in times:
        a = 0.0 if prev_t is None else exp(-beta * (t - prev_t)) * (1.0 + a_prev)
        lam = mu + eta * beta * a
        ll += log(lam)
        a_prev, prev_t = a, t
    comp = mu * (t1 - t0) + eta * sum(1.0 - exp(-beta * (t1 - t)) for t in times)
    return ll - comp


def fit_em(
    times: list[float],
    t0: float,
    t1: float,
    *,
    beta_init: float,
    max_iter: int = 200,
    tol: float = 1e-5,
) -> HawkesFit:
    """One EM run from a given kernel-timescale start; pure, deterministic."""
    n = len(times)
    span = t1 - t0
    mu = 0.5 * n / span
    eta = 0.5
    beta = beta_init
    iterations = 0
    for iterations in range(1, max_iter + 1):  # noqa: B007 — count reported in the fit
        sum_phi = 0.0
        lag_mass = 0.0
        a_prev = b_prev = 0.0
        prev_t = None
        for t in times:
            if prev_t is None:
                a = b = 0.0
            else:
                d = t - prev_t
                decay = exp(-beta * d)
                a = decay * (1.0 + a_prev)
                b = decay * (b_prev + d * (1.0 + a_prev))
            lam = mu + eta * beta * a
            sum_phi += mu / lam
            lag_mass += eta * beta * b / lam
            a_prev, b_prev, prev_t = a, b, t
        triggered = n - sum_phi
        new_mu = sum_phi / span
        new_eta = triggered / n
        new_beta = triggered / lag_mass if lag_mass > 0 else beta
        moved = max(
            abs(new_mu - mu) / max(mu, 1e-12),
            abs(new_eta - eta) / max(eta, 1e-12),
            abs(new_beta - beta) / max(beta, 1e-12),
        )
        mu, eta, beta = new_mu, new_eta, new_beta
        if moved < tol:
            break
    ll = _log_likelihood(times, t0, t1, mu, eta, beta)
    rate = n / span
    ll_poisson = n * log(rate) - n if n else 0.0
    return HawkesFit(mu, eta, beta, ll, ll_poisson, iterations, n, span)


def fit_branching(times: list[float], t0: float, t1: float) -> HawkesFit:
    """The registered protocol: EM from timescale inits {5 s, 60 s}, best LL kept."""
    fits = [fit_em(times, t0, t1, beta_init=1.0 / ts) for ts in (5.0, 60.0)]
    return max(fits, key=lambda f: f.log_likelihood)


class Excitation:
    """Causal S_beta(t) = sum_{t_i < t} exp(-beta (t - t_i)) at a FIXED timescale.

    Precomputes A_i at every event once; a query is then O(log N). Strictly-before
    semantics: an event exactly at t does not contribute to S(t).
    """

    def __init__(self, times: list[float], beta: float) -> None:
        self.times = times
        self.beta = beta
        a = []
        a_prev = 0.0
        prev_t = None
        for t in times:
            a_i = 0.0 if prev_t is None else exp(-beta * (t - prev_t)) * (1.0 + a_prev)
            a.append(a_i)
            a_prev, prev_t = a_i, t
        self._a = a

    def at(self, t: float) -> float:
        k = bisect_left(self.times, t) - 1
        if k < 0:
            return 0.0
        return exp(-self.beta * (t - self.times[k])) * (self._a[k] + 1.0)
