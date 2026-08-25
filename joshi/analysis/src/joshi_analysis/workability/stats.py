"""The A/B split and the window-A candidate statistics (STUDY.md section 4).

The split is the grid panel's declared rule at 1/2: split_instant = earliest venue event time
plus half the event-time span. Window A is strictly before the instant, window B at or after
it; features read A only, outcomes read B only, and a coin whose windows undershoot the
declared minima is INSUFFICIENT, never imputed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import MIN_A_EVENTS, MIN_B_EVENTS, TIERS_SLOTS
from .tiers import decompose, span_hours_of

if TYPE_CHECKING:
    from collections.abc import Sequence

    from joshi_analysis.scalplab.tape import TapeEvent


@dataclass(frozen=True)
class SplitWindows:
    split_instant_us: int
    tape_start_us: int
    tape_end_us: int
    window_a: tuple[TapeEvent, ...]
    window_b: tuple[TapeEvent, ...]
    n_untimed_dropped: int  # events without a venue timestamp cannot be windowed

    @property
    def a_duration_hours(self) -> float:
        """Window A's own duration — the honest rate denominator even for a bursty window."""
        return (self.split_instant_us - self.tape_start_us) / 3_600_000_000

    @property
    def b_duration_hours(self) -> float:
        return (self.tape_end_us - self.split_instant_us) / 3_600_000_000


def split_events(events: Sequence[TapeEvent]) -> SplitWindows | None:
    """Split one coin's events at half the event-time span. None when the span is degenerate."""
    timed = [event for event in events if event.event_time_us is not None]
    if len(timed) < 2:
        return None
    start = min(event.event_time_us for event in timed)  # type: ignore[type-var]
    end = max(event.event_time_us for event in timed)  # type: ignore[type-var]
    if end <= start:
        return None
    split_instant = start + (end - start) // 2
    window_a = tuple(e for e in timed if e.event_time_us < split_instant)  # type: ignore[operator]
    window_b = tuple(e for e in timed if e.event_time_us >= split_instant)  # type: ignore[operator]
    return SplitWindows(
        split_instant_us=split_instant,
        tape_start_us=start,
        tape_end_us=end,
        window_a=window_a,
        window_b=window_b,
        n_untimed_dropped=len(events) - len(timed),
    )


def ols_slope_per_hour(events: Sequence[TapeEvent]) -> float | None:
    """OLS slope of log price on hours since the window start. None below 3 events."""
    points = [
        (event.event_time_us / 3_600_000_000, math.log(float(event.price)))
        for event in events
        if event.event_time_us is not None and event.price > 0
    ]
    if len(points) < 3:
        return None
    t0 = points[0][0]
    xs = [x - t0 for x, _ in points]
    ys = [y for _, y in points]
    n = len(points)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x <= 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return cov / var_x


def window_statistics(
    events: Sequence[TapeEvent], floor_bps: int, duration_hours: float | None = None
) -> dict[str, float | None]:
    """S1-S11 and S13 of one window, keyed by their STUDY.md ids. S12 joins elsewhere.

    ``duration_hours`` is the window's declared duration (RUN note R1: the rate denominator
    is the window's time length, not its events' span — a dead half-window is a zero rate,
    never an absence).
    """
    tiers = decompose(events, floor_bps, TIERS_SLOTS, span_hours=duration_hours)
    span = (
        duration_hours
        if duration_hours is not None and duration_hours > 0
        else span_hours_of(events)
    )
    n = len(events)
    out: dict[str, float | None] = {
        "S1_tier0_legs_ph": tiers.surviving_per_hour_by_tier.get(0),
        "S2_tier2_legs_ph": tiers.surviving_per_hour_by_tier.get(2),
        "S3_tier8_legs_ph": tiers.surviving_per_hour_by_tier.get(8),
        "S4_tier32_legs_ph": tiers.surviving_per_hour_by_tier.get(32),
        "S5_trades_ph": (n / span) if span else None,
        "S11_intra_slot_share": tiers.intra_slot_movement_share,
        "n_events": float(n),
        "span_hours": span,
        "n_clearing_legs": float(tiers.n_clearing_legs),
    }
    traders = {event.trader for event in events if event.trader}
    out["S6_unique_traders_ph"] = (len(traders) / span) if span else None
    out["S7_trader_concentration"] = (len(traders) / n) if n else None
    total_quote = sum(abs(event.quote_signed) for event in events)
    signed_quote = sum(event.quote_signed for event in events)
    out["S8_buy_imbalance"] = float(signed_quote / total_quote) if total_quote > 0 else None
    out["S9_drift_slope_ph"] = ols_slope_per_hour(events)
    prices = [float(event.price) for event in events if event.price > 0]
    out["S10_log_range"] = (
        math.log(max(prices)) - math.log(min(prices)) if len(prices) >= 2 else None
    )
    out["S13_log_mcap_proxy"] = (
        math.log(prices[-1] * 1e9) if prices and prices[-1] > 0 else None
    )
    return out


def outcome_statistics(
    events: Sequence[TapeEvent], floor_bps: int, duration_hours: float | None = None
) -> dict[str, float | None]:
    """O1-O4 of window B, plus the denominators every number carries."""
    tiers = decompose(events, floor_bps, TIERS_SLOTS, span_hours=duration_hours)
    return {
        "O1_tier0_legs_ph": tiers.surviving_per_hour_by_tier.get(0),
        "O2_tier2_legs_ph": tiers.surviving_per_hour_by_tier.get(2),
        "O3_tier8_legs_ph": tiers.surviving_per_hour_by_tier.get(8),
        "O4_tier32_legs_ph": tiers.surviving_per_hour_by_tier.get(32),
        "n_events": float(tiers.n_events),
        "span_hours": tiers.span_hours,
        "n_clearing_legs": float(tiers.n_clearing_legs),
        "intra_slot_share_B": tiers.intra_slot_movement_share,
        "log_range_B": (
            math.log(max(float(e.price) for e in events))
            - math.log(min(float(e.price) for e in events))
            if len(events) >= 2
            else None
        ),
    }


def windows_sufficient(split: SplitWindows) -> bool:
    """RUN note R1: window B needs only a positive duration — a near-empty B is a coin whose
    workability collapsed, which is an OUTCOME (zero rates over B's duration), never an
    insufficiency. Window A must hold enough events to compute features at all."""
    return len(split.window_a) >= MIN_A_EVENTS and split.b_duration_hours > 0


def replay_windows_sufficient(split: SplitWindows) -> bool:
    """The replay arm still needs evaluable events on both sides of the split."""
    return windows_sufficient(split) and len(split.window_b) >= MIN_B_EVENTS
