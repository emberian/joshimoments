"""Shadow scalper — the throughput-and-loss-bound loop, in shadow mode.

The reframe this module encodes: entry selection here is a *liveness check*, not a
forecast. ~15 new tokens/min exist; covering the desk's obligations needs ~300
profitable scalps/day at ~1.4% selectivity. The binding constraints are friction
(U-shaped in size, optimum B* = sqrt(priority * Y)), a clock-enforced exit (a
time-box, which noise cannot trip, instead of a stop, which noise trips in
minutes), and a proved exposure bound (the envelope).

Everything is logged with its propensity at decision time, conforming to
``shitcoims_tape.schema.PropensityRecord`` (interface #8), so the shadow tape is
a designed experiment scoreable by ``shitcoims_replay.ope`` — including the
candidates we rejected, which cost nothing to track in shadow and buy the
selection-vs-luck decomposition on day one.

Shadow marking is deliberately pessimistic: entries fill at the NEXT observation
after the decision, exits at the FIRST observation after the deadline. A shadow
return computed this way is a floor, not a flatter.
"""

from shitcoims_scalper.policy import (
    Decision,
    DrawnThresholds,
    JitterRanges,
    ScalperPolicy,
    optimal_size_lamports,
    round_trip_friction,
)
from shitcoims_scalper.book import Book, CircuitBreaker, DeadlineHeap
from shitcoims_scalper.shadow import ShadowMarker, curve_buy, curve_sell

__all__ = [
    "Book",
    "CircuitBreaker",
    "DeadlineHeap",
    "Decision",
    "DrawnThresholds",
    "JitterRanges",
    "ScalperPolicy",
    "ShadowMarker",
    "curve_buy",
    "curve_sell",
    "optimal_size_lamports",
    "round_trip_friction",
]
