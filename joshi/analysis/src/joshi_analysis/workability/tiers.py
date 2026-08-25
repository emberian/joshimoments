"""The tier-latency decomposition of one window of one coin's tape (STUDY.md section 3).

Slot = the first 12 digits of ``slotIndexId`` (already parsed by the scalplab loader into
``TapeEvent.slot``). The price path is decomposed into alternating monotone legs (a pivot at
every direction reversal; equal prices extend nothing), an up-leg clears the floor iff
``peak * 10^4 >= trough * (10^4 + floor_bps)`` in exact ``Decimal`` arithmetic, and a leg
survives latency tier delta iff entering at the first event at least delta slots after the
trough (same-slot for delta = 0) still leaves a floor-clearing rise to the leg's peak.

Movement shares split the total absolute log-price movement into the part printed WITHIN
slots — unreachable to any actor slower than same-slot inclusion — and the part printed
across slot boundaries.

Every rate is per hour of venue event time; a window whose event-time span is zero has no
rate, which is reported as ``None`` and never as zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from joshi_analysis.scalplab.tape import TapeEvent

TEN_THOUSAND = Decimal(10_000)
SAME_SLOT_TIER = 0


@dataclass(frozen=True)
class UpLeg:
    """One trough-to-peak monotone leg of the window's price path."""

    trough_index: int
    peak_index: int
    trough_price: Decimal
    peak_price: Decimal

    def clears(self, floor_bps: int) -> bool:
        return self.peak_price * TEN_THOUSAND >= self.trough_price * (
            TEN_THOUSAND + Decimal(floor_bps)
        )


@dataclass(frozen=True)
class TierDecomposition:
    """The window's workability numbers, with their denominators attached."""

    n_events: int
    span_hours: float | None  # None when the venue timestamps span zero time
    n_up_legs: int
    n_clearing_legs: int
    clearing_legs_per_hour: float | None
    # tier delta (slots) -> count of clearing legs surviving that entry delay
    surviving_by_tier: dict[int, int]
    surviving_per_hour_by_tier: dict[int, float | None]
    # legs whose events carry no slot; unavailable at every tier and counted, never dropped
    n_legs_without_slot: int
    intra_slot_movement_share: float | None  # None when total movement is zero
    total_abs_log_movement: float


def pivots(prices: Sequence[Decimal]) -> list[int]:
    """Indices of the path's alternating extremes, endpoints included.

    Between consecutive returned indices the path is monotone (non-strict: equal prices
    extend the current run and never pivot). A run of equal extreme prices pivots at its
    FIRST index, so a tier delay is measured from the earliest instant the extreme printed —
    the conservative reading for an observer's reaction clock.
    """
    if not prices:
        return []
    out = [0]
    direction = 0
    extreme = 0
    for index in range(1, len(prices)):
        if prices[index] == prices[extreme]:
            continue
        step = 1 if prices[index] > prices[extreme] else -1
        if direction == 0 or step == direction:
            direction = step
            extreme = index
        else:
            out.append(extreme)
            direction = step
            extreme = index
    if extreme != out[-1]:
        out.append(extreme)
    return out


def up_legs(prices: Sequence[Decimal]) -> list[UpLeg]:
    """Every trough-to-peak leg between consecutive pivots."""
    marks = pivots(prices)
    legs = []
    for lower, upper in pairwise(marks):
        if prices[upper] > prices[lower]:
            legs.append(
                UpLeg(
                    trough_index=lower,
                    peak_index=upper,
                    trough_price=prices[lower],
                    peak_price=prices[upper],
                )
            )
    return legs


def _entry_index(events: Sequence[TapeEvent], leg: UpLeg, tier_slots: int) -> int | None:
    """First event a tier-delayed actor could enter at, or None when the leg is unavailable.

    Entry must land strictly after the trough and at or before the peak; delta = 0 requires
    the SAME slot as the trough (the co-located bound), delta >= 1 requires
    ``slot >= trough_slot + delta``. An event without a slot can never be an entry.
    """
    trough_slot = events[leg.trough_index].slot
    if trough_slot is None:
        return None
    for index in range(leg.trough_index + 1, leg.peak_index + 1):
        slot = events[index].slot
        if slot is None:
            continue
        if tier_slots == SAME_SLOT_TIER:
            if slot == trough_slot:
                return index
            if slot > trough_slot:
                return None  # the slot closed before anyone else printed in it
        elif slot >= trough_slot + tier_slots:
            return index
    return None


def leg_survives(events: Sequence[TapeEvent], leg: UpLeg, tier_slots: int, floor_bps: int) -> bool:
    """Does a floor-clearing rise remain after the tier's entry delay?"""
    entry = _entry_index(events, leg, tier_slots)
    if entry is None:
        return False
    entry_price = events[entry].price
    return leg.peak_price * TEN_THOUSAND >= entry_price * (TEN_THOUSAND + Decimal(floor_bps))


def movement_shares(events: Sequence[TapeEvent]) -> tuple[float | None, float]:
    """(intra-slot share of total |dlog price|, total |dlog price|). Share None when total 0."""
    total = 0.0
    intra = 0.0
    for previous, current in pairwise(events):
        move = abs(math.log(float(current.price)) - math.log(float(previous.price)))
        total += move
        if previous.slot is not None and previous.slot == current.slot:
            intra += move
    if total <= 0.0:
        return None, 0.0
    return intra / total, total


def span_hours_of(events: Sequence[TapeEvent]) -> float | None:
    """Venue event-time span in hours; None when absent or degenerate."""
    times = [e.event_time_us for e in events if e.event_time_us is not None]
    if len(times) < 2:
        return None
    span = (max(times) - min(times)) / 3_600_000_000
    return span if span > 0 else None


def decompose(
    events: Sequence[TapeEvent],
    floor_bps: int,
    tiers: Sequence[int] = (0, 2, 8, 32),
    span_hours: float | None = None,
) -> TierDecomposition:
    """The full section-3 decomposition of one window.

    ``span_hours`` is the window's own duration when the caller declares one (a time-split
    window has a defined duration even when it holds few events — a dead window's rate is an
    honest zero over that duration, never an absence); otherwise the events' own time span.
    """
    prices = [event.price for event in events]
    legs = up_legs(prices)
    clearing = [leg for leg in legs if leg.clears(floor_bps)]
    span = span_hours if span_hours is not None and span_hours > 0 else span_hours_of(events)
    surviving: dict[int, int] = {}
    for tier in tiers:
        surviving[tier] = sum(
            1 for leg in clearing if leg_survives(events, leg, tier, floor_bps)
        )
    without_slot = sum(1 for leg in clearing if events[leg.trough_index].slot is None)
    share, total_movement = movement_shares(events)

    def rate(count: int) -> float | None:
        return count / span if span is not None else None

    return TierDecomposition(
        n_events=len(events),
        span_hours=span,
        n_up_legs=len(legs),
        n_clearing_legs=len(clearing),
        clearing_legs_per_hour=rate(len(clearing)),
        surviving_by_tier=surviving,
        surviving_per_hour_by_tier={tier: rate(count) for tier, count in surviving.items()},
        n_legs_without_slot=without_slot,
        intra_slot_movement_share=share,
        total_abs_log_movement=total_movement,
    )
