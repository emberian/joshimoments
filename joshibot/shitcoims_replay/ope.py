"""Off-policy evaluation: what a different policy would have earned on our own logs.

This is what turns the desk's trading from a cost into an instrument. Every action taken under
a logged propensity is a small randomised experiment, so a candidate policy can be scored
against decisions that were actually made — no simulator fidelity assumption, no market-impact
guess, just reweighting outcomes we really observed.

It only works if the propensity was recorded AT DECISION TIME, which is why
``PropensityRecord`` exists in the tape contract and why it refuses a zero propensity: an
action the logging policy could never have taken carries an infinite importance weight, and no
estimator can recover from that.

The three estimators here trade bias against variance, and the honest default is to report all
three plus the diagnostic:

- **IPS** is unbiased under overlap, and has ruinous variance when weights are large.
- **SNIPS** self-normalises, trading a little bias for far less variance. Usually the one to
  read.
- **DR** adds a reward model; it is unbiased if EITHER the model or the propensities are right,
  which is why it is worth the extra moving part.

The diagnostic matters more than any of them. **Effective sample size** says how many of the
logged decisions actually informed the estimate — a thousand records with one dominant weight
is an estimate from one record, and reporting its point value without that fact is how off-
policy evaluation produces confident nonsense.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class OPEError(ValueError):
    """The logs cannot support the requested estimate. Always fail closed."""


@dataclass(frozen=True, slots=True)
class LoggedDecision:
    """One decision taken by the logging policy, with the outcome it produced.

    ``propensity`` is the probability the LOGGING policy assigned to the action it took.
    Recovering it after the fact is impossible, which is the whole reason it is logged.
    """

    action: str
    propensity: float
    reward: float

    def __post_init__(self) -> None:
        if not 0.0 < self.propensity <= 1.0:
            raise OPEError(
                "propensity must be in (0, 1]; a zero-propensity action carries an "
                "infinite importance weight and no estimator can recover from it"
            )


@dataclass(frozen=True, slots=True)
class Estimate:
    """A value estimate with the diagnostics needed to know whether to believe it."""

    ips: float
    snips: float
    doubly_robust: float
    effective_sample_size: float
    n: int
    max_weight: float

    @property
    def ess_fraction(self) -> float:
        return self.effective_sample_size / self.n if self.n else 0.0

    @property
    def trustworthy(self) -> bool:
        """A deliberately blunt gate: below 10% effective sample the point value is theatre."""
        return self.ess_fraction >= 0.10


def evaluate(
    logs: Sequence[LoggedDecision],
    target_probability: dict[str, float] | None = None,
    *,
    reward_model: dict[str, float] | None = None,
) -> Estimate:
    """Estimate the value of a target policy from decisions made under a logging policy.

    ``target_probability`` maps an action to the probability the TARGET policy would assign
    it. A deterministic candidate is just a mapping with a single 1.0 — the common case.

    ``reward_model`` is the doubly-robust component: an expected reward per action, fitted
    elsewhere. Omitted, DR degenerates to IPS, and the returned value says so by equalling it
    rather than by pretending to be something better.
    """
    if not logs:
        raise OPEError("no logged decisions to evaluate")
    target = target_probability or {}
    model = reward_model or {}

    # The direct-method term is the TARGET-weighted expected reward over every action it
    # might take, not the model's value for whichever action happened to be logged. Getting
    # that wrong leaves the residual uncorrected and the estimate tracks the model's error
    # rather than the truth -- caught here by a test with a deliberately absurd model.
    direct = sum(target.get(action, 0.0) * model.get(action, 0.0) for action in target)

    weights: list[float] = []
    weighted_rewards: list[float] = []
    dr_terms: list[float] = []

    for record in logs:
        probability = target.get(record.action, 0.0)
        if probability < 0.0 or probability > 1.0:
            raise OPEError(f"target probability for {record.action!r} is not a probability")
        weight = probability / record.propensity
        weights.append(weight)
        weighted_rewards.append(weight * record.reward)
        baseline = model.get(record.action, 0.0)
        # Direct method plus the importance-weighted residual: if the model is right the
        # residual vanishes, and if the propensities are right the weighting carries it.
        dr_terms.append(direct + weight * (record.reward - baseline))

    n = len(logs)
    total_weight = sum(weights)
    ips = sum(weighted_rewards) / n
    snips = (sum(weighted_rewards) / total_weight) if total_weight > 0 else 0.0
    doubly_robust = sum(dr_terms) / n

    squared = sum(w * w for w in weights)
    ess = (total_weight**2 / squared) if squared > 0 else 0.0

    return Estimate(
        ips=ips,
        snips=snips,
        doubly_robust=doubly_robust,
        effective_sample_size=ess,
        n=n,
        max_weight=max(weights) if weights else 0.0,
    )


def require_overlap(logs: Sequence[LoggedDecision], target_probability: dict[str, float]) -> None:
    """Refuse to evaluate a target that acts where the logging policy never did.

    Off-policy evaluation cannot extrapolate. If the target puts weight on an action the logs
    never contain, the estimate is silently about a different policy than the one asked about
    — so this raises instead, which is the difference between a bounded answer and a confident
    wrong one.
    """
    seen = {record.action for record in logs}
    unsupported = [
        action for action, probability in target_probability.items()
        if probability > 0.0 and action not in seen
    ]
    if unsupported:
        raise OPEError(
            f"target policy acts where the logs have no support: {sorted(unsupported)}"
        )
