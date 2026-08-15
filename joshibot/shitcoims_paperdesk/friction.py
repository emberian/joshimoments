"""One friction model, shared by all three books, every constant MEASURED.

The cross-book comparison is only a comparison if the books pay the same tolls. That is
the whole reason this module exists as a single object rather than three sets of defaults
drifting apart in three call sites -- which is exactly how the earlier studies ended up
incomparable (``lp_strategy`` in USD at a 1.44% taker fee, the shadow scalper in lamports
at an assumed 1.00% swap fee and a priority fee 14x too high).

PROVENANCE OF EVERY NUMBER HERE
-------------------------------
* ``PRIORITY_FEE_LAMPORTS = 35_000`` -- ``studies/RESULT_execution_landing.md`` put the
  real network fee on a transaction shaped like ours at 21,000-53,000 lamports. The
  shadow scalper had 500,000 hard-coded, which oversized every clip by ~4x because
  ``B* = sqrt(priority * Y)``. ``scripts/sim2real.py`` over the cluster tape reports a
  median paid fee of 55,000 lamports across 2,937 real swaps (p10 6,600, p90 1,005,000):
  the median includes the 5,000-lamport base fee and a long tail of priority auctions, so
  35,000 remains the honest central estimate for an unhurried transaction.
* ``EFFECTIVE_TAKE_BPS`` -- measured per pool by ``scripts/sim2real.py``, which predicts
  each real swap's output from the PRE reserves under a zero-fee constant product and
  reads the shortfall. DREGG/SOL and SOLVE/SOL come back at 20 bps; nosis/SOL at ~407;
  weave/SOL at ~909. Those last two are not "the pool fee" -- they are the whole
  effective take including router skim, and they are what a taker actually pays.
* ``BONDING_CURVE_TAKE_BPS = 100`` -- pump.fun's published 1% curve fee. Kept separate
  from the pool table because a pre-graduation mint is a different venue.
* ``PUMPSWAP_LP_FEE`` / ``PUMPSWAP_TAKER_FEE`` / ``GAS_PER_REBUILD_SOL`` /
  ``PROTOCOL_FEE_SHARE`` are imported from ``studies.lp_strategy`` rather than restated,
  so the toll book and the study that derived the LP identity cannot drift apart.

A $2.45 clip pays ~2.4% round trip. That is the number the operator has been carrying in
their head, and ``round_trip_friction`` reproduces it because it is the same formula.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from shitcoims_scalper.policy import (
    LAMPORTS_PER_SOL,
    optimal_size_lamports,
    round_trip_friction,
)

# Reused, never restated: the LP-side constants belong to the study that derived them.
from studies.lp_strategy import (
    GAS_PER_REBUILD_SOL,
    PROTOCOL_FEE_SHARE,
    PUMPSWAP_LP_FEE,
    PUMPSWAP_TAKER_FEE,
)

__all__ = [
    "BONDING_CURVE_TAKE_BPS",
    "EFFECTIVE_TAKE_BPS",
    "GAS_PER_REBUILD_SOL",
    "LAMPORTS_PER_SOL",
    "PRIORITY_FEE_LAMPORTS",
    "PROTOCOL_FEE_SHARE",
    "PUMPSWAP_LP_FEE",
    "PUMPSWAP_TAKER_FEE",
    "Friction",
    "optimal_size_lamports",
    "round_trip_friction",
]

#: Measured by ``scripts/sim2real.py`` against the cluster tape, 2026-08-14. Median of the
#: constant-product shortfall per pool label. DLMM pools are absent by construction: a
#: bin-walk fill is not a function of vault totals, so constant product cannot predict it.
EFFECTIVE_TAKE_BPS: Final[dict[str, int]] = {
    "DREGG/SOL": 20,
    "SOLVE/SOL": 20,
    "nosis/SOL": 407,
    "weave/SOL": 909,
}

#: pump.fun bonding curve, pre-graduation. The published 1%.
BONDING_CURVE_TAKE_BPS: Final[int] = 100

#: ``studies/RESULT_execution_landing.md``; see module docstring for why not 500,000.
PRIORITY_FEE_LAMPORTS: Final[int] = 35_000


@dataclass(frozen=True, slots=True)
class Friction:
    """The tolls, identical across books by construction.

    Passed by value into every book so that no book can quietly get a cheaper world than
    another. ``take_bps_for`` is the only place a venue-specific number enters, and it
    falls back to the bonding-curve rate rather than to zero: an unknown venue must cost
    *something*, or the desk will preferentially "discover" edges on venues it cannot
    price.
    """

    priority_fee_lamports: int = PRIORITY_FEE_LAMPORTS
    #: Impact ceiling: refuse entries above ~2% of the pool's SOL side (PROGRAM.md 1.4).
    rho_max_bps: int = 200
    #: A candidate whose optimal size cannot beat this round-trip cost is not actionable
    #: at any threshold, so the check folds into the logged verdict rather than sitting
    #: outside it as an invisible filter.
    max_round_trip: float = 0.05
    gas_per_rebuild_lamports: int = int(GAS_PER_REBUILD_SOL * LAMPORTS_PER_SOL)

    def take_bps_for(self, label: str | None) -> int:
        """Effective take in bps for a venue label, measured where we have measured it."""
        if label is None:
            return BONDING_CURVE_TAKE_BPS
        return EFFECTIVE_TAKE_BPS.get(label, BONDING_CURVE_TAKE_BPS)

    def size_lamports(self, pool_sol_lamports: int, *, bankroll_cap_lamports: int) -> int:
        """B* = sqrt(priority * Y), capped by pool impact and by the book's bankroll."""
        return optimal_size_lamports(
            pool_sol_lamports,
            priority_fee_lamports=self.priority_fee_lamports,
            rho_max_bps=self.rho_max_bps,
            bankroll_cap_lamports=bankroll_cap_lamports,
        )

    def round_trip(self, size_lamports: int, pool_sol_lamports: int, *, take_bps: int) -> float:
        """Fractional round-trip cost: two takes, two priority fees, impact both ways."""
        return round_trip_friction(
            size_lamports,
            pool_sol_lamports,
            swap_fee_bps=take_bps,
            priority_fee_lamports=self.priority_fee_lamports,
        )

    def affordable(self, size_lamports: int, pool_sol_lamports: int, *, take_bps: int) -> bool:
        if size_lamports <= 0 or pool_sol_lamports <= 0:
            return False
        return self.round_trip(size_lamports, pool_sol_lamports, take_bps=take_bps) <= (
            self.max_round_trip
        )
