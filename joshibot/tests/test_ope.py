"""Tests for off-policy evaluation.

The estimators are standard; what is pinned here is that they refuse to answer when the logs
cannot support an answer, which is where off-policy evaluation usually goes wrong.
"""

from __future__ import annotations

import random

import pytest

from shitcoims_replay.ope import LoggedDecision, OPEError, evaluate, require_overlap


def _uniform_logs(n: int, rewards: dict[str, float], seed: int = 7) -> list[LoggedDecision]:
    """A logging policy that picks uniformly among the actions — perfect overlap."""
    rng = random.Random(seed)
    actions = list(rewards)
    p = 1.0 / len(actions)
    return [
        LoggedDecision(action=(a := rng.choice(actions)), propensity=p, reward=rewards[a])
        for _ in range(n)
    ]


def test_ips_recovers_the_value_of_a_deterministic_target() -> None:
    """The basic guarantee: unbiased under overlap.

    Under a uniform logger over 4 actions, a target that always picks the 3.0-reward action
    should be estimated near 3.0 — from logs where that action was chosen only a quarter of
    the time.
    """
    rewards = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 0.0}
    logs = _uniform_logs(8000, rewards)
    est = evaluate(logs, {"c": 1.0})
    assert est.ips == pytest.approx(3.0, abs=0.15)
    assert est.snips == pytest.approx(3.0, abs=0.05)


def test_snips_is_steadier_than_ips_across_seeds() -> None:
    """Self-normalisation trades a little bias for much less variance."""
    rewards = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 0.0}
    ips, snips = [], []
    for seed in range(12):
        est = evaluate(_uniform_logs(600, rewards, seed=seed), {"c": 1.0})
        ips.append(est.ips)
        snips.append(est.snips)

    def spread(xs: list[float]) -> float:
        mean = sum(xs) / len(xs)
        return (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5

    assert spread(snips) < spread(ips)


def test_effective_sample_size_exposes_an_estimate_resting_on_one_record() -> None:
    """The diagnostic that matters more than the point value.

    One rare action dominating the weights means the estimate comes from a handful of
    decisions, however many rows were fed in.
    """
    logs = [LoggedDecision(action="common", propensity=0.999, reward=1.0) for _ in range(999)]
    logs.append(LoggedDecision(action="rare", propensity=0.001, reward=100.0))
    est = evaluate(logs, {"rare": 1.0})
    assert est.n == 1000
    assert est.effective_sample_size == pytest.approx(1.0, abs=0.01)
    assert est.ess_fraction < 0.01
    assert est.trustworthy is False


def test_good_overlap_is_reported_as_trustworthy() -> None:
    rewards = {"a": 1.0, "b": 2.0}
    est = evaluate(_uniform_logs(2000, rewards), {"a": 0.5, "b": 0.5})
    assert est.ess_fraction > 0.9
    assert est.trustworthy is True


def test_a_zero_propensity_is_refused_at_construction() -> None:
    """An action the logging policy could never take has an infinite importance weight."""
    with pytest.raises(OPEError, match="propensity"):
        LoggedDecision(action="a", propensity=0.0, reward=1.0)
    with pytest.raises(OPEError):
        LoggedDecision(action="a", propensity=1.5, reward=1.0)


def test_a_target_acting_outside_the_logs_is_refused_rather_than_extrapolated() -> None:
    """Off-policy evaluation cannot extrapolate; silently trying is how it lies."""
    logs = _uniform_logs(100, {"a": 1.0, "b": 2.0})
    require_overlap(logs, {"a": 1.0})
    with pytest.raises(OPEError, match="no support"):
        require_overlap(logs, {"never_taken": 1.0})


def test_doubly_robust_is_unbiased_when_the_reward_model_is_wrong() -> None:
    """DR is unbiased if EITHER the model or the propensities are right.

    Here the model is badly wrong and the propensities are exact, so the residual term must
    carry the estimate back to the truth.
    """
    rewards = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 0.0}
    logs = _uniform_logs(8000, rewards)
    wrong_model = {"a": -50.0, "b": -50.0, "c": -50.0, "d": -50.0}
    est = evaluate(logs, {"c": 1.0}, reward_model=wrong_model)
    assert est.doubly_robust == pytest.approx(3.0, abs=0.3)


def test_doubly_robust_without_a_model_equals_ips_rather_than_pretending() -> None:
    """Omitting the model must degrade visibly, not look like a better estimator."""
    logs = _uniform_logs(500, {"a": 1.0, "b": 2.0})
    est = evaluate(logs, {"a": 1.0})
    assert est.doubly_robust == pytest.approx(est.ips)


def test_empty_logs_are_refused() -> None:
    with pytest.raises(OPEError, match="no logged decisions"):
        evaluate([], {"a": 1.0})


def test_a_target_probability_outside_zero_one_is_refused() -> None:
    logs = _uniform_logs(10, {"a": 1.0})
    with pytest.raises(OPEError, match="not a probability"):
        evaluate(logs, {"a": 1.4})
