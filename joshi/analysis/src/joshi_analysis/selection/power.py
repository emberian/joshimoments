"""How many marked decisions before this question is answerable at all.

The operator has run zero sessions. So the honest first output of this lane is not a
result, it is a REQUIREMENT: the number of decisions that have to exist before the
instrument can distinguish skill from chance. That number is a deliverable, and it is what
stops the first ten holds from being over-read.

Three numbers, and the gap between them is the point.

  N_scored   scored scenes needed for the DISCRIMINATION test (S1). Small.
  N_scored   scored scenes needed for the ECONOMIC test (S3). An order of magnitude larger,
             because it is a mean of heavy-tailed returns rather than a bounded rank.
  N_marked   decisions that have to be MADE to yield that many scored ones, given that most
             mints go unobserved after the act.

S1: RANK
--------
Under the null the chosen set is a uniformly random m-subset of the scene's k scored
candidates, so its mean normalised rank has mean 0.5 and variance

    Var = (k + 1)(k - m) / (12 m (k - 1)^2)

which for the common case m = 1 is (k + 1) / (12 (k - 1)). The rank statistic is bounded, so
the normal approximation is well behaved and

    N = (z_{alpha/2} + z_beta)^2 * Var / delta^2

is honest here. Ties would reduce the variance slightly, making these figures conservative.

S3: RETURN
----------
    N = (z_alpha + z_beta)^2 * sigma^2 / delta^2

with sigma the standard deviation of per-scene log return. This is where the requirement
gets expensive and where the normal approximation gets shaky: pump-cohort forward returns
are violently heavy-tailed (LIFECYCLE_FINDINGS measured a median event-resolution drawdown
of 0.182 log against a p90 of 0.974 log, and a median post-callout move around 17%), so the
true requirement is LARGER than the normal figure, not smaller. These N are a LOWER BOUND.
The instrument's own S3 test is a sign test for that reason.

YIELD
-----
The gap between decisions made and decisions scored is not a rounding error. The corpus
lifecycle work measured that 77.1% of mints have three or fewer minute-bars in their first
hour, and a scene is only scored when the chosen candidate AND at least one passed candidate
both carry a baseline price and a forward observation in the horizon band. Until a real
session measures the yield, treat it as unknown and read the yield-adjusted column as a
sensitivity, not a forecast.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .preregistration import ALPHA, PRIMARY_HORIZON_SECONDS, TARGET_POWER

#: Standard normal quantiles. Hardcoded so this package needs no scipy.
Z_ALPHA_TWO_SIDED_05 = 1.959964
Z_ALPHA_ONE_SIDED_05 = 1.644854
Z_POWER_80 = 0.841621

#: Plug-in for the per-scene log-return dispersion, used ONLY for the S3 requirement.
#: This is a plug-in from the bonding-curve corpus (analysis/corpus/LIFECYCLE_FINDINGS.md),
#: NOT a measurement of the dispersion of hunt-scene candidates -- no such measurement
#: exists yet, because no hunt session has been run. Replace it with the measured value
#: as soon as one has been.
ASSUMED_SCENE_RETURN_SD_LOG = 0.60


def null_rank_variance(k: int, m: int = 1) -> float:
    """Var of the mean normalised rank of m chosen out of k, under no skill. No ties."""
    if k < 2 or m < 1 or m >= k:
        return 0.0
    return (k + 1) * (k - m) / (12.0 * m * (k - 1) ** 2)


def scenes_needed_for_rank_shift(
    delta: float, k: int = 8, m: int = 1, power: float = TARGET_POWER, alpha: float = ALPHA
) -> int:
    """Scored scenes needed to detect a mean-normalised-rank shift of `delta` from 0.5."""
    if delta <= 0:
        raise ValueError("delta must be positive")
    if not (alpha == ALPHA and power == TARGET_POWER):
        raise ValueError("alpha/power are pre-registered; changing them is not supported")
    var = null_rank_variance(k, m)
    if var == 0.0:
        raise ValueError(f"a choice set of k={k} with m={m} chosen carries no counterfactual")
    return math.ceil((Z_ALPHA_TWO_SIDED_05 + Z_POWER_80) ** 2 * var / delta**2)


def scenes_needed_for_net_return(
    delta_log: float,
    sd_log: float = ASSUMED_SCENE_RETURN_SD_LOG,
    power: float = TARGET_POWER,
    alpha: float = ALPHA,
) -> int:
    """Scored scenes needed to show a mean net log return of `delta_log` exceeds zero.

    One-sided: the only question is whether the edge clears the floor. LOWER BOUND -- the
    normal approximation understates the requirement on heavy-tailed returns.
    """
    if delta_log <= 0:
        raise ValueError("delta_log must be positive")
    if not (alpha == ALPHA and power == TARGET_POWER):
        raise ValueError("alpha/power are pre-registered; changing them is not supported")
    return math.ceil((Z_ALPHA_ONE_SIDED_05 + Z_POWER_80) ** 2 * sd_log**2 / delta_log**2)


def detectable_rank_shift(n_scored: int, k: int = 8, m: int = 1) -> float:
    """Inverse: the smallest rank shift `n_scored` scenes could detect at 80% power."""
    if n_scored < 1:
        return float("inf")
    var = null_rank_variance(k, m)
    if var == 0.0:
        return float("inf")
    return (Z_ALPHA_TWO_SIDED_05 + Z_POWER_80) * math.sqrt(var / n_scored)


@dataclass(frozen=True, slots=True)
class PowerRow:
    effect: float
    scenes_needed: int
    decisions_needed_at_yield: dict[float, int]


@dataclass(frozen=True, slots=True)
class PowerStatementV1:
    schema: str
    horizon_seconds: int
    choice_set_size: int
    chosen_per_scene: int
    assumed_return_sd_log: float
    yields: tuple[float, ...]
    s1_rows: tuple[PowerRow, ...]
    s3_rows: tuple[PowerRow, ...]
    n_scored_now: int
    detectable_now: float

    def to_json_obj(self) -> dict[str, object]:
        def rows(rs: Sequence[PowerRow]) -> list[dict[str, object]]:
            return [
                {
                    "effect": r.effect,
                    "scoredScenesNeeded": r.scenes_needed,
                    "decisionsNeededAtYield": {
                        str(y): n for y, n in r.decisions_needed_at_yield.items()
                    },
                }
                for r in rs
            ]

        return {
            "schema": self.schema,
            "horizonSeconds": self.horizon_seconds,
            "choiceSetSize": self.choice_set_size,
            "chosenPerScene": self.chosen_per_scene,
            "assumedReturnSdLog": self.assumed_return_sd_log,
            "yields": list(self.yields),
            "s1DiscriminationRankShift": rows(self.s1_rows),
            "s3TradeableNetLogReturn": rows(self.s3_rows),
            "nScoredNow": self.n_scored_now,
            "detectableRankShiftNow": self.detectable_now,
        }


def power_statement(
    n_scored_now: int = 0,
    k: int = 8,
    m: int = 1,
    sd_log: float = ASSUMED_SCENE_RETURN_SD_LOG,
    yields: Sequence[float] = (1.0, 0.5, 0.25),
    horizon_seconds: int = PRIMARY_HORIZON_SECONDS,
) -> PowerStatementV1:
    rank_effects = (0.05, 0.10, 0.15, 0.20, 0.25)
    return_effects = (0.02, 0.05, 0.10, 0.20)

    def row(needed: int, effect: float) -> PowerRow:
        return PowerRow(
            effect=effect,
            scenes_needed=needed,
            decisions_needed_at_yield={y: math.ceil(needed / y) for y in yields},
        )

    return PowerStatementV1(
        schema="joshi.selection.power.v1",
        horizon_seconds=horizon_seconds,
        choice_set_size=k,
        chosen_per_scene=m,
        assumed_return_sd_log=sd_log,
        yields=tuple(yields),
        s1_rows=tuple(row(scenes_needed_for_rank_shift(d, k, m), d) for d in rank_effects),
        s3_rows=tuple(row(scenes_needed_for_net_return(d, sd_log), d) for d in return_effects),
        n_scored_now=n_scored_now,
        detectable_now=detectable_rank_shift(n_scored_now, k, m),
    )


def render_power_statement(stmt: PowerStatementV1) -> str:
    lines: list[str] = []
    lines.append("HOW MANY DECISIONS BEFORE THIS QUESTION IS ANSWERABLE")
    lines.append("=" * 72)
    lines.append(
        f"Assumes a choice set of {stmt.choice_set_size} with {stmt.chosen_per_scene} marked "
        f"per scene, alpha={ALPHA}, power={TARGET_POWER}, horizon {stmt.horizon_seconds}s."
    )
    lines.append("")
    lines.append("S1  DISCRIMINATION -- can we tell her pick from a coin drawn at random?")
    lines.append("    effect = shift in mean normalised rank away from the 0.500 null.")
    lines.append("    0.10 means her pick sits at the 60th percentile of its scene, not the 50th.")
    lines.append("")
    header = f"    {'shift':>7}  {'scored scenes':>14}" + "".join(
        f"  {'decisions @ ' + f'{y:.0%}' + ' yield':>24}" for y in stmt.yields
    )
    lines.append(header)
    for r in stmt.s1_rows:
        cells = "".join(f"  {r.decisions_needed_at_yield[y]:>24}" for y in stmt.yields)
        lines.append(f"    {r.effect:>7.2f}  {r.scenes_needed:>14}{cells}")
    lines.append("")
    lines.append("S3  TRADEABLE EDGE -- is the pick worth trading, net of the fee floor?")
    lines.append(
        "    effect = mean net log return per scene. sd assumed "
        f"{stmt.assumed_return_sd_log:.2f} log"
    )
    lines.append("    (plug-in from the bonding-curve corpus, NOT measured on hunt scenes).")
    lines.append("    These are a LOWER BOUND: heavy tails make the real requirement larger.")
    lines.append("")
    lines.append(header.replace("shift", "  net"))
    for r in stmt.s3_rows:
        cells = "".join(f"  {r.decisions_needed_at_yield[y]:>24}" for y in stmt.yields)
        lines.append(f"    {r.effect:>7.2f}  {r.scenes_needed:>14}{cells}")
    lines.append("")
    lines.append("THE GAP BETWEEN THE TWO TABLES IS THE FINDING.")
    lines.append(
        "    Showing she picks well is cheap. Showing it is worth trading is roughly an"
    )
    lines.append(
        "    order of magnitude more expensive, because a bounded rank is easy to measure"
    )
    lines.append(
        "    and a heavy-tailed return is not. Budget for the second number, not the first."
    )
    lines.append("")
    if stmt.n_scored_now < 1:
        lines.append(
            f"    Scored scenes available today: {stmt.n_scored_now}. No effect of any size is"
        )
        lines.append("    detectable. Nothing about selection skill can be claimed either way.")
    else:
        lines.append(
            f"    Scored scenes available today: {stmt.n_scored_now}. Smallest rank shift these"
        )
        lines.append(
            f"    could detect at 80% power: {stmt.detectable_now:.3f}"
            f" (the null itself is 0.500)."
        )
    return "\n".join(lines)
