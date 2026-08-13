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
Passing it is the whole content of the deflation: with the spread set to 1 by convention the expected
maximum is wrong by exactly the factor the term exists to supply. Making it mandatory means
the caller cannot omit it by accident, which is precisely how both audited implementations
lost it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

#: Euler-Mascheroni, as it appears in the expected-maximum expansion.
_GAMMA = 0.5772156649015329


class TrialsError(ValueError):
    """The accounting was asked for something it cannot honestly compute."""


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF, from the standard library.

    This was a hand-rolled Acklam approximation, justified in a docstring as keeping the
    module dependency-free. That justification was false — `statistics` IS the standard
    library — and an adversarial audit measured the approximation's worst absolute error at
    7.36e-09 against a claimed ~1e-9, with no direct test: substituting a version 2% wrong
    survived the whole suite. `NormalDist().inv_cdf` is exact to ~1e-16 and shorter.
    """
    if not 0.0 < p < 1.0:
        raise TrialsError("normal quantile needs p in (0, 1)")
    return NormalDist().inv_cdf(p)


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

    This is the EXACT expression, ``E[max SR]² / target²``. An earlier version shipped
    ``2·ln(N)/target²``, which the paper gives as a loose upper BOUND — it overstated the
    requirement by 52-102% and contradicted this module's own anchor, claiming five years
    supports N=12 when the paper's figure is ~45. Caught by adversarial audit; the test that
    was supposed to protect it merely restated the implementation's own formula.
    """
    if trials < 2:
        raise TrialsError("minimum backtest length needs at least 2 trials")
    if target_sharpe <= 0:
        raise TrialsError("target_sharpe must be positive")
    benchmark = expected_max_sharpe(trials, 1.0)
    return benchmark**2 / target_sharpe**2


def grammar_trials(features: int, literals: int, depth: int) -> int:
    """The certified trial count for a DSL search, from the Lean artifact.

    Falls back to nothing: if the oracle is unavailable this raises rather than guessing,
    because a guessed N silently weakens exactly the correction it feeds.
    """
    from shitcoims_kernel.oracle import LeanOracle

    with LeanOracle() as oracle:
        reply = oracle._ask(f"predcount {features} {literals} {depth}")
    return int(reply)
