"""Multiple-testing accounting, with N taken from the grammar rather than guessed.

Searching a strategy space and reporting the winner's Sharpe is a measurement of the search,
not of the strategy. Bailey, Borwein, López de Prado and Zhu give the scale: after only about
**7 independent configurations** the expected best in-sample Sharpe of 1 corresponds to an
out-of-sample Sharpe of **zero**, and five years of data supports roughly 45.

The correction needs N, the number of trials, and in practice nobody knows it — which is how
this project's own reference material ended up shipping a "deflated Sharpe ratio" that was
`sr / ln(trials)`, a formula from no paper, alongside a second implementation that disagreed
with it. Both of them dropped the cross-trial variance term, which is the term that makes the
deflation scale-correct.

Two things are done differently here.

**N is certified, not estimated.** When the search space is a grammar, N is the cardinality of
the set of terms of bounded depth, and `kernel/Joshi/Dsl.lean` computes it exactly. This module
takes that number from the Lean artifact, so the correction rests on a counted quantity.

**The cross-trial spread is REQUIRED, not defaulted.** `trial_sharpe_sd` has no default value.
Passing it is the whole content of the deflation: with σ set to 1 by convention the expected
maximum is wrong by exactly the factor the term exists to supply. Making it mandatory means
the caller cannot omit it by accident, which is precisely how both audited implementations
lost it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

#: Euler–Mascheroni, as it appears in the expected-maximum expansion.
_GAMMA = 0.5772156649015329


class TrialsError(ValueError):
    """The accounting was asked for something it cannot honestly compute."""


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation, ~1e-9 absolute).

    Hand-rolled to keep this module dependency-free, and accurate enough that the deflation
    is limited by the inputs rather than by the quantile.
    """
    if not 0.0 < p < 1.0:
        raise TrialsError("normal quantile needs p in (0, 1)")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def expected_max_sharpe(trials: int, trial_sharpe_sd: float) -> float:
    """Expected maximum Sharpe from ``trials`` strategies that all have TRUE skill zero.

    The bar a candidate must clear before "skill" is even on the table. Scales with the
    cross-trial spread — which is why that argument is mandatory. Screening a grammar of
    110,880 terms whose Sharpes have unit spread puts the best-looking one near 4.4 with no
    edge whatsoever.
    """
    if trials < 1:
        raise TrialsError("trials must be at least 1")
    if trial_sharpe_sd < 0:
        raise TrialsError("trial_sharpe_sd must not be negative")
    if trials == 1:
        return 0.0
    n = float(trials)
    return trial_sharpe_sd * (
        (1.0 - _GAMMA) * _norm_ppf(1.0 - 1.0 / n)
        + _GAMMA * _norm_ppf(1.0 - 1.0 / (n * math.e))
    )


@dataclass(frozen=True, slots=True)
class Deflated:
    observed_sharpe: float
    expected_max_sharpe: float
    trials: int
    probability: float

    @property
    def survives(self) -> bool:
        """Conventional 95% bar. Reported, never applied silently."""
        return self.probability >= 0.95


def deflated_sharpe(
    *,
    observed_sharpe: float,
    trials: int,
    trial_sharpe_sd: float,
    observations: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> Deflated:
    """Bailey & López de Prado's deflated Sharpe ratio, with the variance term intact.

    Returns the probability that the observed Sharpe exceeds what the search alone would
    produce. ``skew`` and ``kurtosis`` matter because memecoin returns are violently
    non-normal — a right-tailed, fat-tailed return stream inflates a naive Sharpe, and the
    denominator here is what removes that.
    """
    if observations < 2:
        raise TrialsError("deflation needs at least 2 observations")
    benchmark = expected_max_sharpe(trials, trial_sharpe_sd)
    denominator = 1.0 - skew * observed_sharpe + ((kurtosis - 1.0) / 4.0) * observed_sharpe**2
    if denominator <= 0.0:
        raise TrialsError(
            "non-normality correction is non-positive; the moment estimates are inconsistent"
        )
    statistic = (observed_sharpe - benchmark) * math.sqrt(observations - 1) / math.sqrt(denominator)
    return Deflated(
        observed_sharpe=observed_sharpe,
        expected_max_sharpe=benchmark,
        trials=trials,
        probability=_norm_cdf(statistic),
    )


def minimum_backtest_length(trials: int, target_sharpe: float = 1.0) -> float:
    """Years of data needed before an in-sample Sharpe of ``target_sharpe`` means anything.

    The other side of the same coin, and the more useful one when planning a search: it
    answers "how big a search can this much data support" rather than "did my winner survive".
    """
    if trials < 2:
        raise TrialsError("minimum backtest length needs at least 2 trials")
    if target_sharpe <= 0:
        raise TrialsError("target_sharpe must be positive")
    return 2.0 * math.log(trials) / target_sharpe**2


def grammar_trials(features: int, literals: int, depth: int) -> int:
    """The certified trial count for a DSL search, from the Lean artifact.

    Falls back to nothing: if the oracle is unavailable this raises rather than guessing,
    because a guessed N silently weakens exactly the correction it feeds.
    """
    from shitcoims_kernel.oracle import LeanOracle

    with LeanOracle() as oracle:
        reply = oracle._ask(f"predcount {features} {literals} {depth}")
    return int(reply)
