"""Both-sides calibration, shuffle split, attention gating, and shaped deposits."""

from decimal import Decimal

import pytest

from joshi_analysis.lpdesk.cadence import (
    both_sides_calibration,
    oscillation_rows,
    shuffle_split,
)
from joshi_analysis.lpdesk.dial import SwapRecord
from joshi_analysis.lpdesk.frontier import CusumShaping, PolicyCell, simulate_policy
from joshi_analysis.lpdesk.reconstruct import LedgerEvent, PoolIdentity

IDENTITY = PoolIdentity(
    address="POOL", bin_step=10, token_x_mint="X", token_y_mint="Y",
    reserve_x="RX", reserve_y="RY", x_decimals=9, y_decimals=6, quote_is_y=True,
)


def _triangle_path(period_s=600, amplitude=3, cycles=6, dt=30):
    """A triangle wave in bins: 0 -> +A -> -A -> 0, one full sweep per period."""
    path = []
    total = period_s * cycles
    for t in range(0, total + dt, dt):
        phase = (t % period_s) / period_s
        if phase < 0.25:
            value = amplitude * (phase / 0.25)
        elif phase < 0.75:
            value = amplitude * (1 - (phase - 0.25) / 0.25)
        else:
            value = -amplitude * (1 - (phase - 0.75) / 0.25)
        path.append((t, value))
    return path


def test_both_sides_rate_falls_with_width_and_counts_round_trips():
    path = _triangle_path()
    panels = both_sides_calibration(path, widths=(1, 3, 5), horizons_s=(600, 1800))
    by_width = {p.half_width_bins: p for p in panels}
    # w=1 round-trips every cycle or better; w=5 exceeds the amplitude and never does.
    assert by_width[1].round_trips >= 5
    assert by_width[5].round_trips == 0
    assert by_width[1].round_trips_per_hour > by_width[3].round_trips_per_hour
    assert by_width[5].both_edges_within[1800] == 0.0
    assert by_width[1].both_edges_within[1800] > by_width[1].both_edges_within[600] - 1e-9


def test_both_sides_refuses_paths_it_cannot_measure():
    with pytest.raises(ValueError):
        both_sides_calibration([(0, 1.0)], widths=(1,))


def test_oscillation_rows_report_rms_excursion_in_bins():
    path = _triangle_path()
    rows = oscillation_rows(path, bin_step=10, lags_ms=(60_000, 300_000))
    real = [r for r in rows if "absent" not in r]
    assert real, "the triangle path must yield at least one measurable lag"
    assert all(r["rms_excursion_bins"] > 0 for r in real)


def _event(sig, slot, t, kind, position="P1", **kw):
    base = dict(
        signature=sig, slot=slot, block_time=t, kind=kind, position=position,
        active_id=kw.get("active_id"), x_in=kw.get("x_in", 0), y_in=kw.get("y_in", 0),
        x_out=kw.get("x_out", 0), y_out=kw.get("y_out", 0),
        fee_x=kw.get("fee_x", 0), fee_y=kw.get("fee_y", 0),
        tx_fee_lamports=kw.get("tx_fee_lamports", 0),
        rent_lamports=kw.get("rent_lamports", 0), reconciled=True, note="",
    )
    return LedgerEvent(**base)


def test_shuffle_split_classifies_and_prices_the_two_kinds():
    ledger = [
        # one in-position shuffle: rebalance rows only, at bin 0 (price 1000)
        _event("sig-a", 1, 100, "rebalance", active_id=0,
               x_in=10**9, y_in=0, x_out=10**9, y_out=0, fee_y=2_000_000,
               tx_fee_lamports=5_000),
        # one full exit: withdraw + close
        _event("sig-b", 2, 200, "withdraw", active_id=0, x_out=0, y_out=10**9,
               tx_fee_lamports=7_000),
        _event("sig-b", 2, 200, "close", rent_lamports=-57_000_000),
        # one reopen: create + deposit
        _event("sig-c", 3, 300, "create", rent_lamports=57_000_000),
        _event("sig-c", 3, 300, "deposit", active_id=0, y_in=10**9),
    ]
    split = shuffle_split(ledger, IDENTITY.value_in_quote)
    assert split.shuffle_txs == 1
    assert split.full_exit_txs == 1
    assert split.reopen_txs == 1
    assert split.shuffle_churn_quote == Decimal(1000)  # 1 SOL out at 1000
    assert split.shuffle_inline_fees_quote == Decimal(2)
    assert split.shuffle_tx_fee_lamports == 5_000
    assert split.full_exit_value_quote == Decimal(1000)
    assert split.full_exit_tx_fee_lamports == 7_000
    assert split.rent_cycle_lamports == 0  # the round trip nets to zero


def _record(t, end_bin, fee="0.1"):
    return SwapRecord(block_time=t, slot=t, end_bin_id=end_bin,
                      fee_quote=Decimal(fee), volume_quote=Decimal(0))


def test_attention_gating_defers_the_recenter_to_the_next_tick():
    # Exit at t=100; events at 100, 200, ..., 700. Attention every 600 s.
    tape = [_record(0, 0)] + [_record(t, 5) for t in range(100, 800, 100)]
    watched = simulate_policy(
        tape, PolicyCell(1, 0, 0), bin_step=4, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=Decimal(1000), recenter_cost_fraction=Decimal(0),
    )
    inattentive = simulate_policy(
        tape, PolicyCell(1, 0, 0), bin_step=4, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=Decimal(1000), recenter_cost_fraction=Decimal(0),
        attention_interval_s=600,
    )
    assert watched.recenter_times[0] == 100
    assert inattentive.recenter_times[0] == 600
    assert inattentive.recenter_count <= watched.recenter_count


def test_shaping_withholds_the_adverse_side_and_rides_a_trend_better():
    # A hard uptrend straight through and past the band.
    tape = [_record(0, 0)] + [_record(60 * i, 2 * i) for i in range(1, 12)]
    cell = PolicyCell(3, 10, 0, never_recenter=True)  # no recenters: isolate shaping
    kwargs = dict(bin_step=100, x_decimals=9, y_decimals=6,
                  active_bin_tvl_quote=Decimal(10**9),
                  recenter_cost_fraction=Decimal(0))
    symmetric = simulate_policy(tape, cell, **kwargs)
    shaped = simulate_policy(
        tape, cell, **kwargs, shaping=CusumShaping(k_bins=0.5, h_bins=2.0)
    )
    assert shaped.reshape_count >= 1
    # Withheld base rode the trend instead of being sold at stale bin prices.
    assert shaped.final_value_quote > symmetric.final_value_quote
    # Identity holds for both: net = fees + final - costs - 1.
    for result in (symmetric, shaped):
        assert result.net_quote == (
            result.fees_quote + result.final_value_quote
            - result.recenter_cost_quote - Decimal(1)
        )


def test_shaping_in_chop_stays_symmetric_and_costless():
    tape = [_record(60 * i, i % 2) for i in range(20)]  # 0,1,0,1: no trend
    cell = PolicyCell(3, 8, 0)
    kwargs = dict(bin_step=10, x_decimals=9, y_decimals=6,
                  active_bin_tvl_quote=Decimal(1000),
                  recenter_cost_fraction=Decimal("0.001"))
    symmetric = simulate_policy(tape, cell, **kwargs)
    shaped = simulate_policy(tape, cell, **kwargs, shaping=CusumShaping(0.5, 6.0))
    assert shaped.reshape_count == 0
    assert shaped.fees_quote == symmetric.fees_quote
    assert shaped.final_value_quote == symmetric.final_value_quote
