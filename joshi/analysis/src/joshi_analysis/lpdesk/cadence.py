"""Attention, oscillation, and the operator's two conjectures, measured on retained bytes.

Three questions from the operator, each answered from the already-retained path and bodies
rather than from a model where a measurement exists:

* **Both-sides calibration.** "The narrow regime is calibrated such that we hit ~both sides
  of the bin decently often." That is a CLAIM TO CHECK: a two-sided round trip (the active
  bin touching both edges of the band) converts inventory out and back at the same bin
  prices, netting the shift toward zero — the regime where narrow actually works. This
  module measures, per width: round trips per hour on the retained path, and the fraction
  of band placements that see both edges within a horizon. The oracle path is a
  time-weighted AVERAGE bin per interval, so touch rates measured on it are FLOORS —
  intra-interval excursions are averaged away.
* **Oscillation scale.** The signature instrument (Definition P2, reused verbatim from
  :mod:`joshi_analysis.signature`) gives sigma^2(tau) on the same path; the RMS excursion
  in bins at each lag says what width one oscillation spans at each holding time.
* **Shuffle versus recenter.** Her recenters come in two mechanical kinds — in-position
  ``RebalanceLiquidity`` (the position account survives; no rent moves) and full
  close/reopen (withdraw, close, create, deposit; rent round-trips). The ledger already
  carries every one, reconciled to the atom; this module splits them and prices each kind.

Nothing here opens a socket. Every number carries its window and its floor/ceiling nature.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from joshi_analysis.signature import signature_wall

from .layouts import bin_price_ratio
from .reconstruct import LedgerEvent

__all__ = [
    "BothSidesPanel",
    "ShuffleSplit",
    "both_sides_calibration",
    "cluster_by_gap",
    "fine_path_from_swaps",
    "oscillation_rows",
    "shuffle_split",
]


def cluster_by_gap(records, max_gap_s: int = 300) -> list[list]:
    """Splits time-ordered records into contiguous clusters at gaps over ``max_gap_s``.

    A retention log grown across sessions holds windows hours apart; any statistic that
    integrates over time must see one contiguous window, never a gap pretending to be
    quiet time.
    """
    ordered = sorted(records, key=lambda r: (r.block_time, r.slot))
    clusters: list[list] = []
    for record in ordered:
        if clusters and record.block_time - clusters[-1][-1].block_time <= max_gap_s:
            clusters[-1].append(record)
        else:
            clusters.append([record])
    return clusters


def fine_path_from_swaps(records) -> list[tuple[float, float]]:
    """A floor-free ``(t, bin)`` path from swap events, start and end bin per swap.

    Each swap contributes its start bin then its end bin (epsilon-offset in time to keep
    order under sorting), so the path covers every bin the swap itself traversed. What
    it still cannot see: nothing — within the covered window every trade that moved the
    price is on it; between retained windows there is no path at all, and the caller
    must not bridge.
    """
    path: list[tuple[float, float]] = []
    for index, record in enumerate(sorted(records, key=lambda r: (r.block_time, r.slot))):
        base = float(record.block_time) + index * 1e-6
        if record.start_bin_id is not None:
            path.append((base, float(record.start_bin_id)))
        path.append((base + 5e-7, float(record.end_bin_id)))
    return path


@dataclass(frozen=True)
class BothSidesPanel:
    """Two-sided-touch measurement for one width on one retained path."""

    half_width_bins: int
    round_trips: int  # completed both-edge cycles walking the whole path
    round_trips_per_hour: float
    median_round_trip_s: float | None
    #: fraction of rolling band placements whose both edges are touched within each horizon
    both_edges_within: dict[int, float]
    placements: int

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def both_sides_calibration(
    path: list[tuple[int, float]],
    *,
    widths: tuple[int, ...],
    horizons_s: tuple[int, ...] = (300, 900, 1800, 3600),
) -> list[BothSidesPanel]:
    """Measures both-edge touch behaviour per width on a ``(unix_s, bin)`` path.

    Touch is ``bin >= center + w`` / ``bin <= center - w`` (edge bins count). Round trips
    walk the path renewal-style: a band centered at the current bin, advanced to wherever
    the second edge is hit, then re-centered there — the maximum-rate recenter-on-round-trip
    schedule the path supports. Rolling placements start a fresh band at every observation
    and ask whether both edges are seen within each horizon.
    """
    if len(path) < 3:
        raise ValueError("a touch measurement needs at least three path points")
    ordered = sorted(path)
    span_s = ordered[-1][0] - ordered[0][0]
    if span_s <= 0:
        raise ValueError("a touch measurement needs positive time span")
    panels = []
    for width in widths:
        # Renewal walk for round trips.
        trips = 0
        durations: list[int] = []
        center = ordered[0][1]
        started = ordered[0][0]
        hit_high = hit_low = False
        for at, value in ordered[1:]:
            if value >= center + width:
                hit_high = True
            if value <= center - width:
                hit_low = True
            if hit_high and hit_low:
                trips += 1
                durations.append(at - started)
                center = value
                started = at
                hit_high = hit_low = False
        # Rolling placements per horizon.
        rates: dict[int, float] = {}
        for horizon in horizons_s:
            wins = 0
            placements = 0
            for i, (at, value) in enumerate(ordered):
                if at + horizon > ordered[-1][0]:
                    break
                placements += 1
                high = low = False
                for later, later_value in ordered[i + 1 :]:
                    if later - at > horizon:
                        break
                    if later_value >= value + width:
                        high = True
                    if later_value <= value - width:
                        low = True
                    if high and low:
                        wins += 1
                        break
            rates[horizon] = wins / placements if placements else float("nan")
        durations.sort()
        panels.append(
            BothSidesPanel(
                half_width_bins=width,
                round_trips=trips,
                round_trips_per_hour=trips * 3600 / span_s,
                median_round_trip_s=(
                    float(durations[len(durations) // 2]) if durations else None
                ),
                both_edges_within=rates,
                placements=len(ordered),
            )
        )
    return panels


def oscillation_rows(
    path: list[tuple[int, float]],
    bin_step: int,
    lags_ms: tuple[int, ...] = (60_000, 120_000, 300_000, 900_000, 1_800_000, 3_600_000),
) -> list[dict]:
    """sigma^2(tau) via the P2 signature instrument, plus RMS excursion in bins per lag.

    Bars are ``(ms, Decimal price)`` built from the path's bins; the signature rising with
    tau reads as net positive serial dependence (trend), falling as net mean reversion —
    the same sentence the instrument carries everywhere else in this repo.
    """
    bars = [(t * 1000, _bin_price(bin_step, b)) for t, b in sorted(path)]
    step = Decimal(10_000 + bin_step) / Decimal(10_000)
    rows = []
    for lag_ms, variogram, signature, pairs in signature_wall(bars, lags_ms):
        if variogram is None:
            rows.append({"lag_s": lag_ms // 1000, "absent": "no qualifying pair"})
            continue
        mean_price = sum(price for _, price in bars) / len(bars)
        rms_rel = float((variogram / (mean_price * mean_price)).sqrt())
        rms_bins = rms_rel / float(step.ln())
        rows.append(
            {
                "lag_s": lag_ms // 1000,
                "sigma2_per_s": float(signature),
                "rms_excursion_bins": rms_bins,
                "pairs": pairs,
            }
        )
    return rows


def _bin_price(bin_step: int, bin_id: float) -> Decimal:
    whole = int(bin_id // 1)
    frac = Decimal(str(bin_id - whole))
    base = bin_price_ratio(bin_step, whole)
    step = Decimal(10_000 + bin_step) / Decimal(10_000)
    # fractional bins from the oracle TWA: linear interpolation on the log grid
    return base * (1 + (step - 1) * frac)


@dataclass
class ShuffleSplit:
    """Her recenter transactions, split by mechanical kind and priced from the ledger."""

    shuffle_txs: int  # in-position RebalanceLiquidity: the position account survives
    shuffle_churn_quote: Decimal  # value withdrawn+redeposited inside shuffles
    shuffle_inline_fees_quote: Decimal
    shuffle_tx_fee_lamports: int
    full_exit_txs: int  # withdraw (+claim+close): the position ends
    full_exit_value_quote: Decimal
    full_exit_tx_fee_lamports: int
    reopen_txs: int  # create (+deposit): a successor position begins
    rent_cycle_lamports: int  # rent out at creates plus rent back at closes, net
    note: str

    def as_dict(self) -> dict:
        out = {}
        for key, value in self.__dict__.items():
            out[key] = str(value) if isinstance(value, Decimal) else value
        return out


def shuffle_split(ledger: list[LedgerEvent], quote_of_pair) -> ShuffleSplit:
    """Classifies every recenter transaction in the ledger and prices each kind.

    ``quote_of_pair(x_atoms, y_atoms, bin_id) -> Decimal`` is the pool's own valuation
    function (:meth:`PoolIdentity.value_in_quote`). A transaction is one kind by what its
    rows state: rebalance rows with no close row is an in-position shuffle; withdraw+close
    ends a position; create(+deposit) begins one. The kinds differ in COST STRUCTURE (rent
    round-trip, transaction count), not in path exposure — the shift is the path's doing.
    """
    by_signature: dict[str, list[LedgerEvent]] = {}
    for event in ledger:
        by_signature.setdefault(event.signature, []).append(event)
    shuffle_txs = 0
    shuffle_churn = Decimal(0)
    shuffle_fees = Decimal(0)
    shuffle_lamports = 0
    full_exit_txs = 0
    full_exit_value = Decimal(0)
    full_exit_lamports = 0
    reopen_txs = 0
    rent_cycle = 0
    last_bin: int | None = None
    for _, rows in sorted(by_signature.items(), key=lambda kv: kv[1][0].slot):
        kinds = {r.kind for r in rows}
        tx_bin = next((r.active_id for r in rows if r.active_id is not None), last_bin)
        if tx_bin is not None:
            last_bin = tx_bin
        tx_fee = sum(r.tx_fee_lamports for r in rows)
        rent_cycle += sum(r.rent_lamports for r in rows)
        if "rebalance" in kinds and "close" not in kinds:
            shuffle_txs += 1
            shuffle_lamports += tx_fee
            for r in rows:
                if r.kind != "rebalance" or tx_bin is None:
                    continue
                shuffle_churn += quote_of_pair(r.x_out, r.y_out, tx_bin)
                if r.fee_x or r.fee_y:
                    shuffle_fees += quote_of_pair(r.fee_x, r.fee_y, tx_bin)
        elif "withdraw" in kinds or "close" in kinds:
            full_exit_txs += 1
            full_exit_lamports += tx_fee
            for r in rows:
                if r.kind == "withdraw" and tx_bin is not None:
                    full_exit_value += quote_of_pair(r.x_out, r.y_out, tx_bin)
        elif "create" in kinds or "deposit" in kinds:
            reopen_txs += 1
    return ShuffleSplit(
        shuffle_txs=shuffle_txs,
        shuffle_churn_quote=shuffle_churn,
        shuffle_inline_fees_quote=shuffle_fees,
        shuffle_tx_fee_lamports=shuffle_lamports,
        full_exit_txs=full_exit_txs,
        full_exit_value_quote=full_exit_value,
        full_exit_tx_fee_lamports=full_exit_lamports,
        reopen_txs=reopen_txs,
        rent_cycle_lamports=rent_cycle,
        note=(
            "kinds differ in cost structure, not path exposure: a shuffle keeps the "
            "position account (no rent motion, one transaction), a full recenter "
            "round-trips rent across two-plus transactions; the inventory shift belongs "
            "to the path either way"
        ),
    )
