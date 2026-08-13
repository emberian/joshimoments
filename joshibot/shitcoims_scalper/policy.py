"""The scalper's decision policy: a jittered liveness filter with logged propensities.

Two layers of deliberate randomisation, both logged at decision time:

1. **Threshold jitter** — every cutoff is drawn per-decision from a small range. A
   deterministic filter cannot answer "what if it were looser?"; a jittered one makes
   every nearby filter a counterfactual policy that OPE can score.
2. **The epsilon flip** — with probability ``explore_eps`` we act *against* the filter
   verdict (admit a reject / skip a pass). Every candidate therefore has nonzero
   propensity for both actions, which is exactly the condition
   ``shitcoims_replay.ope`` needs for identification. The propensity of the action
   actually taken is logged, never reconstructed.

Sizing is the friction optimum derived in PROGRAM.md: round-trip cost
``swap_fee + 2*priority/B + 2*B/Y`` is U-shaped in B and minimised at
``B* = sqrt(priority * Y)``, capped by the pool-impact ceiling ``rho_max * Y``
(§1.4: refuse entries above ~2% of the pool's SOL side) and by the bankroll cap.

No floats touch money: lamports are ints throughout. Floats appear only in
probabilities and reported ratios.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from typing import Any, Mapping

LAMPORTS_PER_SOL = 1_000_000_000

POLICY_ID = "scalper-shadow-v1"


@dataclass(frozen=True, slots=True)
class JitterRanges:
    """Uniform ranges each threshold is drawn from, per decision.

    Defaults encode the "three-second glance": young enough to still be moving,
    old enough to not be a pure snipe, recently traded, and a pool deep enough
    that the friction optimum B* is worth the priority fee.
    """

    min_age_s: tuple[float, float] = (20.0, 90.0)
    max_age_s: tuple[float, float] = (900.0, 3600.0)
    max_trade_recency_s: tuple[float, float] = (5.0, 30.0)
    min_sol_in_curve: tuple[float, float] = (5.0, 15.0)  # SOL units
    hold_seconds: tuple[float, float] = (180.0, 420.0)

    def draw(self, rng: random.Random) -> "DrawnThresholds":
        u = rng.uniform
        return DrawnThresholds(
            min_age_s=u(*self.min_age_s),
            max_age_s=u(*self.max_age_s),
            max_trade_recency_s=u(*self.max_trade_recency_s),
            min_sol_in_curve=u(*self.min_sol_in_curve),
            hold_seconds=u(*self.hold_seconds),
        )


@dataclass(frozen=True, slots=True)
class DrawnThresholds:
    min_age_s: float
    max_age_s: float
    max_trade_recency_s: float
    min_sol_in_curve: float
    hold_seconds: float

    def to_json(self) -> dict[str, float]:
        return {
            "min_age_s": self.min_age_s,
            "max_age_s": self.max_age_s,
            "max_trade_recency_s": self.max_trade_recency_s,
            "min_sol_in_curve": self.min_sol_in_curve,
            "hold_seconds": self.hold_seconds,
        }


def liveness_verdict(features: Mapping[str, float], t: DrawnThresholds) -> bool:
    """The formalised glance. Five comparisons on one snapshot; no forecast anywhere."""
    return (
        t.min_age_s <= features["age_s"] <= t.max_age_s
        and features["trade_recency_s"] <= t.max_trade_recency_s
        and features["sol_in_curve"] >= t.min_sol_in_curve
    )


def optimal_size_lamports(
    pool_sol_lamports: int,
    *,
    priority_fee_lamports: int,
    rho_max_bps: int = 200,
    bankroll_cap_lamports: int,
) -> int:
    """B* = sqrt(priority * Y), capped by pool impact and bankroll. Integer lamports."""
    if pool_sol_lamports <= 0:
        return 0
    b_star = math.isqrt(priority_fee_lamports * pool_sol_lamports)
    rho_cap = pool_sol_lamports * rho_max_bps // 10_000
    return max(0, min(b_star, rho_cap, bankroll_cap_lamports))


def round_trip_friction(
    size_lamports: int,
    pool_sol_lamports: int,
    *,
    swap_fee_bps: int,
    priority_fee_lamports: int,
) -> float:
    """Fractional round-trip cost: two swap fees + two priority fees + impact both ways."""
    if size_lamports <= 0 or pool_sol_lamports <= 0:
        return float("inf")
    return (
        2 * swap_fee_bps / 10_000
        + 2 * priority_fee_lamports / size_lamports
        + 2 * size_lamports / pool_sol_lamports
    )


@dataclass(frozen=True, slots=True)
class Decision:
    """One decision over one candidate snapshot, counterfactual-ready.

    ``propensity`` is the probability of the action actually taken, under this
    policy, given the drawn thresholds — logged here at decision time because it
    is not reconstructible later (the whole point of interface #8).
    """

    decision_id: str
    decided_at: str
    mint: str
    action: str  # "enter" | "skip"
    verdict_pass: bool
    explored: bool
    propensity: float
    thresholds: DrawnThresholds
    features: dict[str, float]
    size_lamports: int
    deadline_unix: float
    features_sha256: str

    def propensity_record_json(self) -> dict[str, Any]:
        """Conforms to shitcoims_tape.schema.PropensityRecord.to_json()."""
        return {
            "decision_id": self.decision_id,
            "decided_at": self.decided_at,
            "policy_id": POLICY_ID,
            "action": self.action,
            "propensity": self.propensity,
            "features_sha256": self.features_sha256,
            "envelope_verdict": "shadow",
            "mint": self.mint,
        }


class ScalperPolicy:
    """Draw thresholds, apply the glance, flip with epsilon, size, and log."""

    def __init__(
        self,
        *,
        ranges: JitterRanges | None = None,
        explore_eps: float = 0.05,
        swap_fee_bps: int = 100,
        priority_fee_lamports: int = 500_000,
        rho_max_bps: int = 200,
        bankroll_cap_lamports: int = LAMPORTS_PER_SOL // 2,
        max_friction: float = 0.05,
        seed: int | None = None,
    ) -> None:
        if not 0.0 < explore_eps < 0.5:
            raise ValueError("explore_eps must be in (0, 0.5)")
        self.ranges = ranges or JitterRanges()
        self.explore_eps = explore_eps
        self.swap_fee_bps = swap_fee_bps
        self.priority_fee_lamports = priority_fee_lamports
        self.rho_max_bps = rho_max_bps
        self.bankroll_cap_lamports = bankroll_cap_lamports
        self.max_friction = max_friction
        self.rng = random.Random(seed)

    def decide(
        self, *, mint: str, features: Mapping[str, float], now_unix: float, decided_at: str
    ) -> Decision:
        thresholds = self.ranges.draw(self.rng)
        verdict = liveness_verdict(features, thresholds)

        pool_lamports = int(features["sol_in_curve"] * LAMPORTS_PER_SOL)
        size = optimal_size_lamports(
            pool_lamports,
            priority_fee_lamports=self.priority_fee_lamports,
            rho_max_bps=self.rho_max_bps,
            bankroll_cap_lamports=self.bankroll_cap_lamports,
        )
        friction = round_trip_friction(
            size,
            pool_lamports,
            swap_fee_bps=self.swap_fee_bps,
            priority_fee_lamports=self.priority_fee_lamports,
        )
        # A candidate whose optimal size cannot beat max_friction is not actionable at any
        # threshold; fold that into the verdict so it is part of the logged policy.
        actionable = size > 0 and friction <= self.max_friction
        verdict = verdict and actionable

        flip = self.rng.random() < self.explore_eps
        enter = verdict != flip  # XOR: act against the verdict on an epsilon flip
        p_enter = (1.0 - self.explore_eps) if verdict else self.explore_eps
        propensity = p_enter if enter else 1.0 - p_enter

        feat = {k: float(v) for k, v in sorted(features.items())}
        digest = hashlib.sha256(
            json.dumps(feat, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

        return Decision(
            decision_id=f"{mint[:8]}-{int(now_unix * 1000)}",
            decided_at=decided_at,
            mint=mint,
            action="enter" if enter else "skip",
            verdict_pass=verdict,
            explored=flip,
            propensity=propensity,
            thresholds=thresholds,
            features=feat,
            size_lamports=size if enter else 0,
            deadline_unix=now_unix + thresholds.hold_seconds,
            features_sha256=digest,
        )
