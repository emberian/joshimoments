"""The only label in this package: a floor-clearing up-leg begins within k events.

Raw-direction labels do not map to money on a venue whose round trip costs 190-250 bps; a
model that "predicts up" while the move is smaller than the floor predicts a loss. So the
label is defined net of the tape's declared venue floor, with a one-event execution delay
(entry at the price of the event AFTER the decision — you do not trade at the print you just
learned about).

For decision index ``i`` with horizon ``k``::

    entry     = price[i + 1]
    label(i)  = 1  iff  exists j in [i + 2, i + 1 + k] with
                price[j] * 10^4 >= entry * (10^4 + floor_bps)

All price comparisons are exact ``Decimal`` arithmetic. Labels whose window runs off the tape
end are ``None`` — excluded and counted, never imputed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

TEN_THOUSAND = Decimal(10_000)


@dataclass(frozen=True)
class LabelSet:
    """Labels for one coin series at one horizon, with their denominators attached."""

    horizon_k: int
    floor_bps: int
    labels: tuple[int | None, ...]  # index-aligned with the event list
    n_defined: int
    n_positive: int
    n_undefined_tail: int

    @property
    def base_rate(self) -> float | None:
        if self.n_defined == 0:
            return None
        return self.n_positive / self.n_defined


def floor_clearing_labels(
    prices: list[Decimal], horizon_k: int, floor_bps: int
) -> LabelSet:
    """Label every decision index of one time-ordered price series."""
    if horizon_k < 1:
        raise ValueError("horizon_k must be at least 1")
    if floor_bps < 0:
        raise ValueError("floor_bps must be non-negative")
    n = len(prices)
    multiplier = TEN_THOUSAND + Decimal(floor_bps)
    labels: list[int | None] = []
    n_defined = 0
    n_positive = 0
    for i in range(n):
        last_j = i + 1 + horizon_k
        if last_j >= n:
            labels.append(None)
            continue
        entry = prices[i + 1]
        target = entry * multiplier
        hit = 0
        for j in range(i + 2, last_j + 1):
            if prices[j] * TEN_THOUSAND >= target:
                hit = 1
                break
        labels.append(hit)
        n_defined += 1
        n_positive += hit
    return LabelSet(
        horizon_k=horizon_k,
        floor_bps=floor_bps,
        labels=tuple(labels),
        n_defined=n_defined,
        n_positive=n_positive,
        n_undefined_tail=n - n_defined,
    )
