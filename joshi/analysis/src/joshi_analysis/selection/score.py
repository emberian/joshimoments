"""The three pre-registered statistics, with nulls that are valid at small N.

S1  DISCRIMINATION  -- mean normalised within-scene rank of the chosen candidates.
S2  WITHIN-SCENE EXCESS -- chosen mean log return minus passed mean log return.
S3  TRADEABLE EDGE  -- chosen mean log return minus the round-trip fee floor.

See `preregistration.py` for why there are three and why S1 rather than S2 is primary.
The short version: rank is bounded and has an exact null, log returns on this cohort are
heavy-tailed enough that a mean test is decided by one scene; and S1/S2 answer "does she
pick well" while only S3 answers "was it worth doing". A large S1 with a negative S3 is
SKILL WITHOUT A TRADEABLE EDGE, and the verdict says exactly that.

Ranks are midranks under ties. S1's null is an exact permutation of which m-subset of each
scene's k scored candidates was chosen, which handles ties correctly with no correction.
The closed-form variance used by the power calculator assumes no ties; that assumption is
stated where it is used and is not relied on for any p-value.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from .outcomes import EventOutcomeV1
from .preregistration import (
    ALPHA,
    BOOTSTRAP_DRAWS,
    DEFAULT_FEE_FLOOR_BPS,
    PERMUTATION_DRAWS,
    PERMUTATION_SEED,
)

VERDICT_UNDERPOWERED = "underpowered_no_verdict"
VERDICT_NO_EVIDENCE = "no_evidence_of_selection_skill"
VERDICT_SKILL_NO_EDGE = "skill_without_a_tradeable_edge"
VERDICT_SKILL_AND_EDGE = "skill_and_an_edge_clearing_the_fee_floor"
VERDICT_ADVERSE = "evidence_of_adverse_selection"


def fee_floor_log_cost(bps: int = DEFAULT_FEE_FLOOR_BPS) -> float:
    """Round-trip fee floor as a positive log cost. 247 bps -> 0.0250 log."""
    return -math.log(1.0 - bps / 10_000.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def midranks(values: Sequence[float]) -> list[float]:
    """1-based midranks, ascending: rank 1 is the WORST return, rank k the best.

    So a normalised rank near 1.0 means the operator picked the mover.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for t in range(i, j + 1):
            ranks[order[t]] = shared
        i = j + 1
    return ranks


@dataclass(frozen=True, slots=True)
class SceneStatistic:
    """One scene's contribution. The scene is the independent unit, not the act."""

    event_id: str
    scene_id: str
    k_scored: int
    m_chosen: int
    #: Mean normalised rank of the chosen candidates. 0.5 under the null.
    mean_normalised_rank: float
    chosen_mean_log_return: float
    passed_mean_log_return: float

    @property
    def within_scene_excess(self) -> float:
        return self.chosen_mean_log_return - self.passed_mean_log_return

    def net_of_fee(self, fee_log: float) -> float:
        return self.chosen_mean_log_return - fee_log

    def null_rank_variance(self) -> float:
        """Var of mean normalised rank under H0, no ties: (k+1)(k-m) / (12 m (k-1)^2)."""
        k, m = self.k_scored, self.m_chosen
        if k < 2 or m < 1 or m >= k:
            return 0.0
        return (k + 1) * (k - m) / (12.0 * m * (k - 1) ** 2)


def scene_statistic(outcome: EventOutcomeV1) -> SceneStatistic | None:
    """Reduce one scored event to its per-scene statistic. None if not scored."""
    if not outcome.is_scored:
        return None
    scored = outcome.scored_candidates
    k = len(scored)
    chosen = [c for c in scored if c.was_chosen]
    passed = [c for c in scored if not c.was_chosen]
    if k < 2 or not chosen or not passed:
        return None
    returns = [c.log_return for c in scored]
    assert all(r is not None for r in returns)
    ranks = midranks([float(r) for r in returns])  # type: ignore[arg-type]
    normalised = [(r - 1.0) / (k - 1.0) for r in ranks]
    chosen_idx = [i for i, c in enumerate(scored) if c.was_chosen]
    return SceneStatistic(
        event_id=outcome.event_id,
        scene_id=outcome.scene_id,
        k_scored=k,
        m_chosen=len(chosen),
        mean_normalised_rank=sum(normalised[i] for i in chosen_idx) / len(chosen_idx),
        chosen_mean_log_return=sum(float(c.log_return) for c in chosen) / len(chosen),  # type: ignore[arg-type]
        passed_mean_log_return=sum(float(c.log_return) for c in passed) / len(passed),  # type: ignore[arg-type]
    )


def _permutation_p_two_sided(scenes: Sequence[SceneStatistic], draws: int, seed: int) -> float:
    """Exact-in-the-limit permutation p for S1. Valid at any N, including N = 1.

    Under H0 the chosen set of each scene is a uniformly random m-subset of its k scored
    candidates, independently across scenes. Resample that directly.
    """
    if not scenes:
        return float("nan")
    observed = abs(sum(s.mean_normalised_rank for s in scenes) / len(scenes) - 0.5)
    rng = random.Random(seed)
    grids = [[(r - 1.0) / (s.k_scored - 1.0) for r in range(1, s.k_scored + 1)] for s in scenes]
    at_least = 0
    for _ in range(draws):
        total = 0.0
        for scene, grid in zip(scenes, grids, strict=True):
            picked = rng.sample(grid, scene.m_chosen)
            total += sum(picked) / scene.m_chosen
        if abs(total / len(scenes) - 0.5) >= observed - 1e-12:
            at_least += 1
    return (1 + at_least) / (draws + 1)


def _bootstrap_ci(
    values: Sequence[float], draws: int, seed: int, alpha: float
) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(draws))
    lo = means[max(0, int(draws * alpha / 2) - 1)]
    hi = means[min(draws - 1, int(draws * (1 - alpha / 2)))]
    return (lo, hi)


def _binom_tail_ge(k: int, n: int, p: float = 0.5) -> float:
    """P[X >= k] for X ~ Binomial(n, p). Exact, stdlib only."""
    if n == 0:
        return float("nan")
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def sign_test_greater(values: Sequence[float]) -> tuple[int, int, float]:
    """One-sided sign test for a positive centre. Returns (positives, non-zero N, p).

    Robust to the heavy tails that make a mean test on memecoin returns untrustworthy.
    """
    non_zero = [v for v in values if v != 0.0]
    n = len(non_zero)
    positives = sum(1 for v in non_zero if v > 0)
    return positives, n, _binom_tail_ge(positives, n)


@dataclass(frozen=True, slots=True)
class SelectionScoreV1:
    """The full scored result at one horizon, with every absence accounted for."""

    horizon_seconds: int
    fee_floor_bps: int
    n_events: int
    n_scored: int
    absence_reasons: dict[str, int]

    s1_mean_normalised_rank: float
    s1_null: float
    s1_permutation_p: float
    s1_normal_p: float

    s2_mean_excess_log: float
    s2_ci: tuple[float, float]
    s2_sign_positives: int
    s2_sign_n: int
    s2_sign_p: float

    s3_mean_net_log: float
    s3_ci: tuple[float, float]
    s3_sign_positives: int
    s3_sign_n: int
    s3_sign_p: float

    verdict: str
    verdict_note: str
    scenes: tuple[SceneStatistic, ...]

    def to_json_obj(self) -> dict[str, object]:
        return {
            "horizonSeconds": self.horizon_seconds,
            "feeFloorBps": self.fee_floor_bps,
            "nEvents": self.n_events,
            "nScored": self.n_scored,
            "absenceReasons": dict(sorted(self.absence_reasons.items())),
            "s1": {
                "name": "discrimination: mean normalised within-scene rank of the chosen",
                "value": self.s1_mean_normalised_rank,
                "null": self.s1_null,
                "permutationP": self.s1_permutation_p,
                "normalApproxP": self.s1_normal_p,
            },
            "s2": {
                "name": "within-scene excess log return (chosen minus passed)",
                "value": self.s2_mean_excess_log,
                "bootstrapCi": list(self.s2_ci),
                "signPositives": self.s2_sign_positives,
                "signN": self.s2_sign_n,
                "signP": self.s2_sign_p,
            },
            "s3": {
                "name": "tradeable edge net of the round-trip fee floor",
                "value": self.s3_mean_net_log,
                "bootstrapCi": list(self.s3_ci),
                "signPositives": self.s3_sign_positives,
                "signN": self.s3_sign_n,
                "signP": self.s3_sign_p,
            },
            "verdict": self.verdict,
            "verdictNote": self.verdict_note,
        }


def score(
    outcomes: Sequence[EventOutcomeV1],
    horizon_seconds: int,
    fee_floor_bps: int = DEFAULT_FEE_FLOOR_BPS,
    permutation_draws: int = PERMUTATION_DRAWS,
    bootstrap_draws: int = BOOTSTRAP_DRAWS,
    seed: int = PERMUTATION_SEED,
    alpha: float = ALPHA,
) -> SelectionScoreV1:
    """Score every event at one horizon. Absences are counted, never dropped."""
    absence: dict[str, int] = {}
    scenes: list[SceneStatistic] = []
    for outcome in outcomes:
        stat = scene_statistic(outcome)
        if stat is None:
            absence[outcome.status] = absence.get(outcome.status, 0) + 1
            continue
        scenes.append(stat)

    n_events = len(outcomes)
    n_scored = len(scenes)
    fee_log = fee_floor_log_cost(fee_floor_bps)
    nan = float("nan")

    if n_scored == 0:
        return SelectionScoreV1(
            horizon_seconds=horizon_seconds,
            fee_floor_bps=fee_floor_bps,
            n_events=n_events,
            n_scored=0,
            absence_reasons=absence,
            s1_mean_normalised_rank=nan,
            s1_null=0.5,
            s1_permutation_p=nan,
            s1_normal_p=nan,
            s2_mean_excess_log=nan,
            s2_ci=(nan, nan),
            s2_sign_positives=0,
            s2_sign_n=0,
            s2_sign_p=nan,
            s3_mean_net_log=nan,
            s3_ci=(nan, nan),
            s3_sign_positives=0,
            s3_sign_n=0,
            s3_sign_p=nan,
            verdict=VERDICT_UNDERPOWERED,
            verdict_note=(
                f"{n_events} reconstructed selection event(s), 0 with a measurable outcome "
                f"at {horizon_seconds}s. No statistic is defined on zero scored scenes. "
                "This is an absence of measurement, not a measurement of no effect."
            ),
            scenes=(),
        )

    s1 = sum(s.mean_normalised_rank for s in scenes) / n_scored
    s1_var = sum(s.null_rank_variance() for s in scenes) / (n_scored**2)
    s1_normal_p = (
        2.0 * (1.0 - _norm_cdf(abs(s1 - 0.5) / math.sqrt(s1_var))) if s1_var > 0 else nan
    )
    s1_perm_p = _permutation_p_two_sided(scenes, permutation_draws, seed)

    excess = [s.within_scene_excess for s in scenes]
    net = [s.net_of_fee(fee_log) for s in scenes]
    s2 = sum(excess) / n_scored
    s3 = sum(net) / n_scored
    s2_pos, s2_n, s2_p = sign_test_greater(excess)
    s3_pos, s3_n, s3_p = sign_test_greater(net)

    verdict, note = _verdict(n_scored, s1, s1_perm_p, s2, s3, s3_p, alpha, fee_floor_bps)

    return SelectionScoreV1(
        horizon_seconds=horizon_seconds,
        fee_floor_bps=fee_floor_bps,
        n_events=n_events,
        n_scored=n_scored,
        absence_reasons=absence,
        s1_mean_normalised_rank=s1,
        s1_null=0.5,
        s1_permutation_p=s1_perm_p,
        s1_normal_p=s1_normal_p,
        s2_mean_excess_log=s2,
        s2_ci=_bootstrap_ci(excess, bootstrap_draws, seed, alpha),
        s2_sign_positives=s2_pos,
        s2_sign_n=s2_n,
        s2_sign_p=s2_p,
        s3_mean_net_log=s3,
        s3_ci=_bootstrap_ci(net, bootstrap_draws, seed + 1, alpha),
        s3_sign_positives=s3_pos,
        s3_sign_n=s3_n,
        s3_sign_p=s3_p,
        verdict=verdict,
        verdict_note=note,
        scenes=tuple(scenes),
    )


def _verdict(
    n_scored: int,
    s1: float,
    s1_p: float,
    s2: float,
    s3: float,
    s3_p: float,
    alpha: float,
    fee_bps: int,
) -> tuple[str, str]:
    """Turn the three statistics into one sentence that cannot be misread as a green light."""
    from .power import scenes_needed_for_rank_shift

    if math.isnan(s1_p) or s1_p > alpha:
        needed = scenes_needed_for_rank_shift(0.10, k=8)
        if n_scored < needed:
            return (
                VERDICT_UNDERPOWERED,
                f"{n_scored} scored scene(s). At a choice set of 8 this design needs about "
                f"{needed} scored scenes to detect a mean-rank shift of 0.10 at 80% power, "
                f"so a null result here is what an underpowered instrument looks like and "
                f"is not evidence that no skill exists.",
            )
        return (
            VERDICT_NO_EVIDENCE,
            f"{n_scored} scored scenes, mean normalised rank {s1:.3f} against a null of "
            f"0.500 (permutation p={s1_p:.3f}). The chosen candidate is not distinguishable "
            f"from a candidate drawn at random out of the same scene.",
        )
    if s1 < 0.5:
        return (
            VERDICT_ADVERSE,
            f"Mean normalised rank {s1:.3f} is significantly BELOW the 0.500 null "
            f"(permutation p={s1_p:.3f}) over {n_scored} scored scenes: the chosen candidate "
            f"underperforms the ones passed over. This is a real finding and it is negative.",
        )
    if s3 <= 0 or s3_p > alpha:
        return (
            VERDICT_SKILL_NO_EDGE,
            f"Mean normalised rank {s1:.3f} vs a 0.500 null (permutation p={s1_p:.3f}) over "
            f"{n_scored} scored scenes, and a within-scene excess of {s2:+.4f} log. But net "
            f"of the {fee_bps} bps round-trip fee floor the chosen candidate returns "
            f"{s3:+.4f} log (sign-test p={s3_p:.3f}). SKILL WITHOUT A TRADEABLE EDGE: she "
            f"picks the best coin in the room, and the room does not pay for the trade. An "
            f"edge smaller than the fee floor is not an edge. Do not read S1 as a signal to "
            f"trade on.",
        )
    return (
        VERDICT_SKILL_AND_EDGE,
        f"Mean normalised rank {s1:.3f} vs a 0.500 null (permutation p={s1_p:.3f}) over "
        f"{n_scored} scored scenes, within-scene excess {s2:+.4f} log, and {s3:+.4f} log net "
        f"of the {fee_bps} bps round-trip fee floor (sign-test p={s3_p:.3f}). The fee floor "
        f"is fees ONLY: it excludes price impact at the operator's clip, the 11-13 s "
        f"chain-to-receipt state age, and the spread actually crossed. Real cost is higher "
        f"than this floor, so treat a small positive S3 as not yet demonstrated.",
    )
