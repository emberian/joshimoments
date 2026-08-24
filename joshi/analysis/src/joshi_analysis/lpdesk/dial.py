"""The regime dial: fee intensity versus realized variance, from the pool's own tape.

Fees scale with traded volume; adverse selection scales with sigma^2. For a marginal LP
holding a uniform band of half-width ``w`` bins:

* a dollar in the active bin earns ``F / T_a`` per unit time, where ``F`` is the pool's fee
  flow and ``T_a`` the active bin's liquidity — so a dollar of the band earns
  ``F / (T_a * (2w+1))`` while the band contains the active bin;
* the same dollar bleeds inventory-conversion loss at approximately
  ``sigma^2 / (8 * (w + 1/2) * s)`` per unit time, where ``s = ln(1 + bin_step/10^4)`` is
  one bin's log-width — the standard uniform-band loss-versus-rebalancing rate, a MODEL
  whose formula is named here and rendered with every reading.

Both sides scale as ``1/w``, so their ratio is width-free at first order:

    DIAL = fee_side / loss_side  ~=  4 * F * s / (T_a * sigma^2)

DIAL > 1 says the moment pays any width and the width choice is governed by recenter costs
and discreteness (the frontier's business); DIAL < 1 says narrow LPing is currently paying
for its flow. ``F`` and ``sigma^2`` are measured on stated windows; ``T_a`` is one account
read with its age attached. Nothing here is a forecast; the history series says how fast
past moments decayed, not how this one will.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise

__all__ = ["DialReading", "SwapRecord", "bin_log_width", "regime_dial", "sigma2_from_path"]


@dataclass(frozen=True)
class SwapRecord:
    """One swap from the retained tape: when, where the price ended, what fee it paid."""

    block_time: int
    slot: int
    end_bin_id: int
    fee_quote: Decimal  # the swap's fee valued in display quote units at its own end bin
    volume_quote: Decimal  # amount_in valued the same way


@dataclass(frozen=True)
class DialReading:
    """One dial evaluation with every input's window and age attached."""

    window_start_unix: int
    window_end_unix: int
    swap_count: int
    fee_flow_quote_per_day: Decimal
    volume_quote_per_day: Decimal
    sigma2_per_day: float  # realized variance of log price, per day
    sigma_source: str
    sigma_window_s: int
    active_bin_tvl_quote: Decimal
    active_bin_tvl_age_s: int
    bin_step: int
    dial: float  # 4 * F * s / (T_a * sigma^2); width-free first-order gauge
    fee_side_per_day_at_width: dict[int, float]
    loss_side_per_day_at_width: dict[int, float]
    model_note: str

    def as_dict(self) -> dict:
        out = {}
        for key, value in self.__dict__.items():
            out[key] = str(value) if isinstance(value, Decimal) else value
        return out


def bin_log_width(bin_step: int) -> float:
    return math.log1p(bin_step / 10_000)


def sigma2_from_path(path: list[tuple[int, float]], bin_step: int) -> tuple[float, int]:
    """Realized variance per day from a ``(unix_s, bin_id)`` path, and its window length.

    The sum of squared log-price increments over the path's span. Bin ids may be fractional
    (a time-weighted average bin from the oracle is not an integer). No interpolation: the
    increments are between the observations that exist, and sparse observation UNDERSTATES
    the variance of a mean-reverting path — stated by the caller's ``sigma_source``.
    """
    if len(path) < 2:
        raise ValueError("a variance needs at least two path points")
    ordered = sorted(path)
    span_s = ordered[-1][0] - ordered[0][0]
    if span_s <= 0:
        raise ValueError("a variance needs a path with positive time span")
    s = bin_log_width(bin_step)
    total = 0.0
    for (_, bin_a), (_, bin_b) in pairwise(ordered):
        step = (bin_b - bin_a) * s
        total += step * step
    return total * 86_400 / span_s, span_s


def regime_dial(
    swaps: list[SwapRecord],
    *,
    bin_step: int,
    sigma2_per_day: float,
    sigma_source: str,
    sigma_window_s: int,
    active_bin_tvl_quote: Decimal,
    active_bin_tvl_age_s: int,
    widths: tuple[int, ...] = (1, 2, 3, 5, 8, 13, 21, 34),
) -> DialReading:
    """Evaluates the dial over one contiguous retained swap window."""
    if not swaps:
        raise ValueError("no swaps: the dial cannot read an empty window")
    ordered = sorted(swaps, key=lambda r: (r.block_time, r.slot))
    start = ordered[0].block_time
    end = ordered[-1].block_time
    span_s = max(end - start, 1)
    fees = sum((r.fee_quote for r in ordered), Decimal(0))
    volume = sum((r.volume_quote for r in ordered), Decimal(0))
    per_day = Decimal(86_400) / Decimal(span_s)
    fee_flow = fees * per_day
    if active_bin_tvl_quote <= 0:
        raise ValueError("active bin TVL must be positive to normalize the fee side")
    s = bin_log_width(bin_step)
    fee_side = {}
    loss_side = {}
    for width in widths:
        fee_side[width] = float(fee_flow / active_bin_tvl_quote) / (2 * width + 1)
        loss_side[width] = sigma2_per_day / (8 * (width + 0.5) * s)
    dial = (
        4.0 * float(fee_flow) * s / (float(active_bin_tvl_quote) * sigma2_per_day)
        if sigma2_per_day > 0
        else float("inf")
    )
    return DialReading(
        window_start_unix=start,
        window_end_unix=end,
        swap_count=len(ordered),
        fee_flow_quote_per_day=fee_flow,
        volume_quote_per_day=volume * per_day,
        sigma2_per_day=sigma2_per_day,
        sigma_source=sigma_source,
        sigma_window_s=sigma_window_s,
        active_bin_tvl_quote=active_bin_tvl_quote,
        active_bin_tvl_age_s=active_bin_tvl_age_s,
        bin_step=bin_step,
        dial=dial,
        fee_side_per_day_at_width=fee_side,
        loss_side_per_day_at_width=loss_side,
        model_note=(
            "loss side is the uniform-band model sigma^2/(8*(w+1/2)*s); fee side assumes "
            "fee flow accrues to the active bin whose TVL is one account read; the dial is "
            "their width-free ratio 4*F*s/(T_a*sigma^2). Models, named; the frontier does "
            "the exact arithmetic."
        ),
    )
