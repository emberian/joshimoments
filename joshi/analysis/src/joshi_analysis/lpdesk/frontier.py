"""The recenter-policy frontier: a declared ensemble replayed over one retained tape.

The LP cousin of the grid ensemble in ``crates/joshi-liquidity/src/grid.rs``, keeping its
vocabulary and its honesty:

* **Declared axes with reasons.** Half-width in bins (narrow earns density, exits often),
  exit-tolerance in bins past the band edge (recenter eagerly or let it breathe), and
  minimum out-of-band dwell seconds (a cadence brake). No cell is special-cased.
* **Unremovable baselines.** HODL 50/50 (no LP at all) and the widest-band-never-recenter
  cell are built by the same replay and cannot be omitted from the panel.
* **Costs inside every cell.** Each recenter converts the whole band at the tape's own bin
  prices (the inventory shift is realized by the arithmetic, not estimated) and pays the
  operator's own measured per-recenter transaction cost as a fraction of position value.
* **Behaviour identity is computed.** Cells whose recenter sequences are identical on this
  tape collapse into one stated equivalence class.
* **The time split is declared and never random.** Selection happens on the first half by a
  rule fixed in this file; the held-out half renders beside it.

The fee-capture model is named in :mod:`.vocabulary` and rendered on the panel: a cell earns
``swap_fee * (own active-bin dollars / measured active-bin TVL)``, competitor liquidity held
constant because the tape does not carry it. All position arithmetic is ``Decimal``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .dial import SwapRecord
from .layouts import bin_price_ratio
from .vocabulary import (
    AUTHOR_KNOWLEDGE,
    FEE_CAPTURE_MODEL,
    ONE_POOL_ONE_WINDOW_FITS_NOTHING,
)

__all__ = ["FrontierPanel", "PolicyCell", "PolicyResult", "simulate_policy", "sweep"]


@dataclass(frozen=True)
class PolicyCell:
    half_width_bins: int  # w: band is [center-w, center+w]
    exit_tolerance_bins: int  # g: recenter when |active-center| > w+g ...
    min_dwell_s: int  # ... continuously for at least this long
    never_recenter: bool = False

    def name(self) -> str:
        if self.never_recenter:
            return f"w{self.half_width_bins}-passive"
        return f"w{self.half_width_bins}-g{self.exit_tolerance_bins}-d{self.min_dwell_s}"


@dataclass(frozen=True)
class PolicyResult:
    cell: PolicyCell
    fees_quote: Decimal  # per 1.0 of committed quote
    final_value_quote: Decimal  # band liquidated at the last event's price
    recenter_cost_quote: Decimal
    net_quote: Decimal  # fees + final value - costs - 1.0
    net_vs_hodl_quote: Decimal  # net minus the HODL 50/50 baseline's own net
    recenter_count: int
    time_in_band_s: int
    window_s: int
    recenter_times: tuple[int, ...]

    def as_dict(self) -> dict:
        out = {"cell": self.cell.name()}
        for key, value in self.__dict__.items():
            if key == "cell":
                continue
            out[key] = str(value) if isinstance(value, Decimal) else value
        return out


def _price(bin_step: int, bin_id: int, x_decimals: int, y_decimals: int) -> Decimal:
    return bin_price_ratio(bin_step, bin_id) * Decimal(10) ** (x_decimals - y_decimals)


def simulate_policy(
    tape: list[SwapRecord],
    cell: PolicyCell,
    *,
    bin_step: int,
    x_decimals: int,
    y_decimals: int,
    active_bin_tvl_quote: Decimal,
    recenter_cost_fraction: Decimal,
) -> PolicyResult:
    """Replays one policy over the tape with 1.0 quote of committed capital.

    The band is uniform in value at deposit: each of the ``2w+1`` bins gets an equal quote
    slice; bins above the center hold base priced at the deposit instant's active bin,
    bins below hold quote, the center bin half and half. As the active id moves, bins left
    strictly below it convert to quote and bins left strictly above convert to base, each
    at its own bin price; the new active bin keeps what the crossing left it. A full round
    trip through the band restores the deposit exactly under this model — losses appear
    only when a recenter crystallizes the converted inventory, which is the thing being
    measured. Recentering liquidates every bin at the current active bin's price, pays
    ``recenter_cost_fraction``, and redeposits.
    """
    if not tape:
        raise ValueError("an empty tape cannot be replayed")
    ordered = sorted(tape, key=lambda r: (r.block_time, r.slot))
    w = cell.half_width_bins
    slots = 2 * w + 1

    def price_of(bin_id: int) -> Decimal:
        return _price(bin_step, bin_id, x_decimals, y_decimals)

    def deposit(center: int, capital: Decimal) -> dict[int, tuple[Decimal, Decimal]]:
        # Base is priced at the CURRENT active bin, so the deposit's NAV equals the
        # committed capital at the deposit instant.
        slice_quote = capital / slots
        current = price_of(center)
        band: dict[int, tuple[Decimal, Decimal]] = {}
        for j in range(center - w, center + w + 1):
            if j < center:
                band[j] = (slice_quote, Decimal(0))
            elif j > center:
                band[j] = (Decimal(0), slice_quote / current)
            else:
                band[j] = (slice_quote / 2, slice_quote / 2 / current)
        return band

    def band_value(band: dict[int, tuple[Decimal, Decimal]], at_bin: int) -> Decimal:
        p = price_of(at_bin)
        return sum((u + s * p for u, s in band.values()), Decimal(0))

    start_bin = ordered[0].end_bin_id
    center = start_bin
    band = deposit(center, Decimal(1))
    fees = Decimal(0)
    costs = Decimal(0)
    recenter_times: list[int] = []
    time_in_band = 0
    out_since: int | None = None
    prev_bin = start_bin
    prev_time = ordered[0].block_time

    for record in ordered[1:]:
        active = record.end_bin_id
        # 1. time accounting for the interval just ended, at the previous active bin
        if center - w <= prev_bin <= center + w:
            time_in_band += record.block_time - prev_time
        # 2. convert bins the move left behind, each at its own price: bins strictly
        # below the new active hold only quote, strictly above only base; the new active
        # bin keeps whatever the crossing left it (the mixed bin of the model).
        if active > prev_bin:
            for j in range(prev_bin, active):
                if j in band:
                    u, s = band[j]
                    band[j] = (u + s * price_of(j), Decimal(0))
        elif active < prev_bin:
            for j in range(active + 1, prev_bin + 1):
                if j in band:
                    u, s = band[j]
                    band[j] = (Decimal(0), s + u / price_of(j))
        # 3. fee credit while the active bin is inside the band
        if center - w <= active <= center + w:
            u, s = band[active]
            own_dollars = u + s * price_of(active)
            fees += record.fee_quote * own_dollars / active_bin_tvl_quote
        # 4. recenter trigger
        if not cell.never_recenter:
            outside = abs(active - center) > w + cell.exit_tolerance_bins
            if outside and out_since is None:
                out_since = record.block_time
            if not outside:
                out_since = None
            if out_since is not None and record.block_time - out_since >= cell.min_dwell_s:
                value = band_value(band, active)
                cost = value * recenter_cost_fraction
                costs += cost
                center = active
                band = deposit(center, value - cost)
                recenter_times.append(record.block_time)
                out_since = None
        prev_bin = active
        prev_time = record.block_time

    final_value = band_value(band, prev_bin)
    net = fees + final_value - costs - Decimal(1)
    p0 = price_of(start_bin)
    p1 = price_of(prev_bin)
    hodl_net = (Decimal(1) / 2 + Decimal(1) / 2 * p1 / p0) - Decimal(1)
    window_s = ordered[-1].block_time - ordered[0].block_time
    return PolicyResult(
        cell=cell,
        fees_quote=fees,
        final_value_quote=final_value,
        recenter_cost_quote=costs,
        net_quote=net,
        net_vs_hodl_quote=net - hodl_net,
        recenter_count=len(recenter_times),
        time_in_band_s=time_in_band,
        window_s=window_s,
        recenter_times=tuple(recenter_times),
    )


@dataclass
class FrontierPanel:
    """The whole surface, both halves, the baselines, and its own caveats."""

    axes: dict
    full_window: list[PolicyResult]
    first_half: list[PolicyResult]
    second_half: list[PolicyResult]
    selected_cell: str  # chosen on the first half by the fixed rule
    selected_second_half_net: Decimal | None
    hodl_5050_net_full: Decimal
    equivalence_classes: list[list[str]]
    honesty: dict

    def as_dict(self) -> dict:
        return {
            "axes": self.axes,
            "fullWindow": [r.as_dict() for r in self.full_window],
            "firstHalf": [r.as_dict() for r in self.first_half],
            "secondHalf": [r.as_dict() for r in self.second_half],
            "selectedCell": self.selected_cell,
            "selectedSecondHalfNet": (
                str(self.selected_second_half_net)
                if self.selected_second_half_net is not None
                else None
            ),
            "hodl5050NetFull": str(self.hodl_5050_net_full),
            "equivalenceClasses": self.equivalence_classes,
            "honesty": self.honesty,
        }


#: Selection, fixed here so it cannot be re-fit: on the FIRST half only, the cell with the
#: greatest net; ties toward wider band, then fewer recenters — bigger, calmer moves.
def _select(results: list[PolicyResult]) -> PolicyResult:
    return max(
        results,
        key=lambda r: (r.net_quote, r.cell.half_width_bins, -r.recenter_count),
    )


def sweep(
    tape: list[SwapRecord],
    *,
    bin_step: int,
    x_decimals: int,
    y_decimals: int,
    active_bin_tvl_quote: Decimal,
    recenter_cost_fraction: Decimal,
    half_widths: tuple[int, ...] = (1, 2, 3, 5, 8, 13, 21, 34),
    exit_tolerances: tuple[int, ...] = (0, 2, 8),
    min_dwells_s: tuple[int, ...] = (0, 60, 300),
) -> FrontierPanel:
    """Runs the declared ensemble plus the unremovable baselines over the tape."""
    cells = [
        PolicyCell(w, g, d)
        for w in half_widths
        for g in exit_tolerances
        for d in min_dwells_s
    ]
    cells.append(PolicyCell(max(half_widths), 0, 0, never_recenter=True))

    def run(window: list[SwapRecord]) -> list[PolicyResult]:
        return [
            simulate_policy(
                window,
                cell,
                bin_step=bin_step,
                x_decimals=x_decimals,
                y_decimals=y_decimals,
                active_bin_tvl_quote=active_bin_tvl_quote,
                recenter_cost_fraction=recenter_cost_fraction,
            )
            for cell in cells
        ]

    ordered = sorted(tape, key=lambda r: (r.block_time, r.slot))
    midpoint = len(ordered) // 2
    full = run(ordered)
    first = run(ordered[:midpoint]) if midpoint >= 2 else []
    second = run(ordered[midpoint:]) if len(ordered) - midpoint >= 2 else []

    selected = _select(first) if first else _select(full)
    selected_second = None
    if second:
        for result in second:
            if result.cell == selected.cell:
                selected_second = result.net_quote

    by_behaviour: dict[tuple, list[str]] = {}
    for result in full:
        by_behaviour.setdefault(result.recenter_times, []).append(result.cell.name())
    classes = [names for names in by_behaviour.values() if len(names) > 1]

    p0 = _price(bin_step, ordered[0].end_bin_id, x_decimals, y_decimals)
    p1 = _price(bin_step, ordered[-1].end_bin_id, x_decimals, y_decimals)
    hodl_net = (Decimal(1) / 2 + Decimal(1) / 2 * p1 / p0) - Decimal(1)

    return FrontierPanel(
        axes={
            "halfWidthBins": list(half_widths),
            "halfWidthReason": "narrow earns fee density and exits often; wide the reverse",
            "exitToleranceBins": list(exit_tolerances),
            "exitToleranceReason": "recenter eagerly at the edge, or let excursions breathe",
            "minDwellS": list(min_dwells_s),
            "minDwellReason": "a cadence brake so one wick does not churn the band",
            "recenterCostFraction": str(recenter_cost_fraction),
            "activeBinTvlQuote": str(active_bin_tvl_quote),
        },
        full_window=full,
        first_half=first,
        second_half=second,
        selected_cell=selected.cell.name(),
        selected_second_half_net=selected_second,
        hodl_5050_net_full=hodl_net,
        equivalence_classes=classes,
        honesty={
            "onePoolOneWindow": ONE_POOL_ONE_WINDOW_FITS_NOTHING,
            "feeCaptureModel": FEE_CAPTURE_MODEL,
            "authorKnowledge": AUTHOR_KNOWLEDGE,
            "selectionRule": (
                "on the FIRST half only: greatest net; ties toward wider band, then fewer "
                "recenters; the held-out number is the only out-of-window claim"
            ),
        },
    )
