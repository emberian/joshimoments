"""Tests for multiple-testing accounting.

The reference implementations this replaces were wrong in two specific ways — an invented
`sr / ln(trials)` formula, and a dropped cross-trial variance term — so the tests pin the
behaviours those bugs would violate.
"""

from __future__ import annotations

import math

import pytest

from shitcoims_replay.trials import (
    TrialsError,
    deflated_sharpe,
    expected_max_sharpe,
    grammar_trials,
    minimum_backtest_length,
)


def test_the_expected_maximum_grows_with_the_size_of_the_search() -> None:
    """Screening more zero-skill strategies produces a better-looking winner. That is the point."""
    values = [expected_max_sharpe(n, 1.0) for n in (10, 100, 1_000, 10_000, 100_000)]
    assert values == sorted(values)
    # Published reference points: ~2.5 at 100 trials, ~3.9 at 10k, ~4.4 at 100k.
    assert 2.3 < values[1] < 2.7
    assert 3.7 < values[3] < 4.1
    assert 4.2 < values[4] < 4.6


def test_the_cross_trial_spread_scales_the_benchmark_linearly() -> None:
    """The term BOTH audited implementations dropped.

    Without it the expected maximum is wrong by exactly the factor it supplies, which is why
    the argument is mandatory rather than defaulted.
    """
    base = expected_max_sharpe(1_000, 1.0)
    assert expected_max_sharpe(1_000, 2.0) == pytest.approx(2.0 * base)
    assert expected_max_sharpe(1_000, 0.5) == pytest.approx(0.5 * base)
    assert expected_max_sharpe(1_000, 0.0) == 0.0


def test_trial_sharpe_sd_has_no_default_and_must_be_supplied() -> None:
    """Making it mandatory is how the term stops getting lost."""
    with pytest.raises(TypeError):
        expected_max_sharpe(1_000)  # type: ignore[call-arg]


def test_a_single_trial_needs_no_deflation() -> None:
    assert expected_max_sharpe(1, 1.0) == 0.0


def test_a_winner_below_the_search_benchmark_does_not_survive() -> None:
    """A Sharpe of 2 from a 110,880-term grammar is worse than nothing."""
    result = deflated_sharpe(
        observed_sharpe=2.0,
        trials=110_880,
        trial_sharpe_sd=1.0,
        observations=500,
    )
    assert result.expected_max_sharpe > 2.0
    assert result.probability < 0.5
    assert result.survives is False


def test_a_genuinely_large_edge_still_survives_a_large_search() -> None:
    """The correction must be able to pass something, or it is just a rejection machine."""
    result = deflated_sharpe(
        observed_sharpe=8.0,
        trials=110_880,
        trial_sharpe_sd=1.0,
        observations=2_000,
    )
    assert result.probability > 0.95
    assert result.survives is True


def test_fat_tails_reduce_the_deflated_probability() -> None:
    """Memecoin returns are violently non-normal, and that inflates a naive Sharpe."""
    normal = deflated_sharpe(
        observed_sharpe=3.0, trials=100, trial_sharpe_sd=1.0, observations=500
    )
    fat = deflated_sharpe(
        observed_sharpe=3.0, trials=100, trial_sharpe_sd=1.0, observations=500,
        skew=-1.2, kurtosis=9.0,
    )
    assert fat.probability < normal.probability


def test_minimum_backtest_length_matches_the_published_scale() -> None:
    """After ~7 independent configurations an in-sample Sharpe of 1 means an OOS Sharpe of 0."""
    assert minimum_backtest_length(7, 1.0) == pytest.approx(2.0 * math.log(7))
    assert 3.5 < minimum_backtest_length(7, 1.0) < 4.5
    # Five years supports roughly 45 configurations at a target Sharpe of 1.
    assert 4.5 < minimum_backtest_length(45, 1.0) < 8.0
    # A larger search demands more data, monotonically.
    lengths = [minimum_backtest_length(n) for n in (10, 100, 1_000)]
    assert lengths == sorted(lengths)


def test_the_trial_count_comes_from_the_lean_artifact() -> None:
    """N is COUNTED, not estimated — the whole reason the search space is a grammar.

    Skips ONLY when the oracle is genuinely missing. An earlier version caught every
    exception, so a wrong count was reported as a skip rather than a failure — a test that
    hides the bug it exists to catch, which is worse than no test.
    """
    from shitcoims_kernel import OracleUnavailable

    try:
        counted = grammar_trials(8, 4, 1)
        base = grammar_trials(8, 4, 0)
    except OracleUnavailable as exc:
        pytest.skip(f"lean oracle unavailable: {exc}")
    assert counted == 110_880
    assert base == 144


def test_impossible_inputs_are_refused_rather_than_returned() -> None:
    with pytest.raises(TrialsError):
        expected_max_sharpe(0, 1.0)
    with pytest.raises(TrialsError):
        expected_max_sharpe(10, -1.0)
    with pytest.raises(TrialsError):
        deflated_sharpe(
            observed_sharpe=1.0, trials=10, trial_sharpe_sd=1.0, observations=1
        )
    with pytest.raises(TrialsError):
        minimum_backtest_length(1)
