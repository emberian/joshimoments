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


def _balanced_logs(per_action: int, rewards: dict[str, float]) -> list[LoggedDecision]:
    """The same uniform logger, drawn exactly rather than sampled.

    Every estimator below is then a closed-form number instead of a number plus sampling
    noise, so a test can assert the *value* to the last bit rather than a tolerance wide
    enough to hide a formula error. (Falsification found the seeded version of the
    doubly-robust test sitting inside its tolerance for only about a third of seeds — green
    on seed 7 by luck, and unable to say anything sharp even then.)
    """
    p = 1.0 / len(rewards)
    return [
        LoggedDecision(action=action, propensity=p, reward=reward)
        for action, reward in rewards.items()
        for _ in range(per_action)
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

    The model is wrong in a NON-CONSTANT way, and that is the whole point. The previous
    version scored every action at -50.0, and under a constant model the correct
    target-weighted direct term and the bug this test was written for — using the model's
    value for whichever action happened to be LOGGED — are algebraically the same number.
    Reintroducing the bug left this test green. With a model that varies by action the two
    formulas separate: 3.0 against 80.5.
    """
    rewards = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 0.0}
    logs = _balanced_logs(2000, rewards)
    wrong_model = {"a": -50.0, "b": 10.0, "c": -50.0, "d": 200.0}
    est = evaluate(logs, {"c": 1.0}, reward_model=wrong_model)
    assert est.doubly_robust == pytest.approx(3.0, abs=1e-9)
    # The model's own answer for the target action is nowhere near, so the residual — not the
    # model — is what carried the estimate.
    assert wrong_model["c"] == -50.0
    assert est.ips == pytest.approx(3.0, abs=1e-9)


def test_the_direct_term_is_target_weighted_not_the_logged_actions_value() -> None:
    """The bug the DR formula shipped with, pinned where it cannot hide.

    The direct term must be the TARGET-weighted expectation over every action the target
    might take. Computing it per logged action leaves the residual uncorrected, so the
    estimate tracks the reward model's error instead of the truth — and with a stochastic
    target and a model that varies by action the gap is 2.0 against 79.5, not a tolerance
    question.
    """
    rewards = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 0.0}
    logs = _balanced_logs(2000, rewards)
    wrong_model = {"a": -50.0, "b": 10.0, "c": -50.0, "d": 200.0}
    est = evaluate(logs, {"a": 0.5, "c": 0.5}, reward_model=wrong_model)
    # True value of the target policy: 0.5 * 1.0 + 0.5 * 3.0.
    assert est.doubly_robust == pytest.approx(2.0, abs=1e-9)
    # A correct model gives the same answer -- DR is unbiased either way, which is the claim.
    right_model = dict(rewards)
    assert evaluate(logs, {"a": 0.5, "c": 0.5}, reward_model=right_model).doubly_robust == (
        pytest.approx(2.0, abs=1e-9)
    )


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
