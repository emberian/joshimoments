"""The dial's measurement arithmetic and the frontier's replay, on synthetic tapes."""

import math
from decimal import Decimal

import pytest

from joshi_analysis.lpdesk.dial import (
    SwapRecord,
    bin_log_width,
    regime_dial,
    sigma2_from_path,
)
from joshi_analysis.lpdesk.frontier import PolicyCell, simulate_policy, sweep


def _record(block_time, end_bin, fee="0.01", volume="100"):
    return SwapRecord(
        block_time=block_time,
        slot=block_time,
        end_bin_id=end_bin,
        fee_quote=Decimal(fee),
        volume_quote=Decimal(volume),
    )


def test_sigma2_is_the_sum_of_squared_log_increments_per_day():
    s = bin_log_width(4)
    path = [(0, 0.0), (3600, 2.0), (7200, 1.0)]
    sigma2, span = sigma2_from_path(path, 4)
    expected = ((2 * s) ** 2 + (1 * s) ** 2) * 86_400 / 7200
    assert span == 7200
    assert math.isclose(sigma2, expected)


def test_sigma2_refuses_paths_it_cannot_measure():
    with pytest.raises(ValueError):
        sigma2_from_path([(0, 1.0)], 4)
    with pytest.raises(ValueError):
        sigma2_from_path([(5, 1.0), (5, 2.0)], 4)


def test_the_dial_is_the_width_free_ratio_of_the_measured_sides():
    tape = [_record(0, 0), _record(43_200, 0, fee="0.5"), _record(86_400, 0, fee="0.5")]
    reading = regime_dial(
        tape,
        bin_step=4,
        sigma2_per_day=1e-4,
        sigma_source="synthetic",
        sigma_window_s=86_400,
        active_bin_tvl_quote=Decimal(1000),
        active_bin_tvl_age_s=5,
    )
    # F = 1.01 quote per day over the window, T_a = 1000.
    assert reading.fee_flow_quote_per_day == Decimal("1.01")
    s = bin_log_width(4)
    assert math.isclose(reading.dial, 4 * 1.01 * s / (1000 * 1e-4))
    # Fee side at width w is F/T_a/(2w+1); loss side is sigma^2/(8*(w+0.5)*s).
    assert math.isclose(reading.fee_side_per_day_at_width[1], 1.01 / 1000 / 3)
    assert math.isclose(reading.loss_side_per_day_at_width[1], 1e-4 / (8 * 1.5 * s))


def test_an_in_band_tape_earns_density_scaled_fees_and_never_recenters():
    tape = [_record(t, 0, fee="1") for t in range(0, 600, 60)]
    tvl = Decimal(1000)
    narrow = simulate_policy(
        tape, PolicyCell(1, 0, 0), bin_step=4, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=tvl, recenter_cost_fraction=Decimal(0),
    )
    wide = simulate_policy(
        tape, PolicyCell(5, 0, 0), bin_step=4, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=tvl, recenter_cost_fraction=Decimal(0),
    )
    assert narrow.recenter_count == 0
    assert wide.recenter_count == 0
    # 9 fee events (the first record seeds the deposit), each crediting
    # own-active-bin-dollars / TVL; the active bin holds 1/(2w+1) of the position.
    assert abs(narrow.fees_quote - Decimal(9) / 3 / tvl) < Decimal("1e-20")
    assert abs(wide.fees_quote - Decimal(9) / 11 / tvl) < Decimal("1e-20")
    assert narrow.fees_quote > wide.fees_quote
    # Price never moved: no inventory shift, final value is the deposit (28-digit context).
    assert abs(narrow.final_value_quote - Decimal(1)) < Decimal("1e-20")
    assert narrow.net_quote == narrow.fees_quote + narrow.final_value_quote - Decimal(1)


def test_a_band_exit_recenters_and_pays_the_declared_cost():
    # Price walks up out of a w=1 band and stays there.
    tape = [_record(0, 0), _record(60, 1), _record(120, 3), _record(180, 3)]
    result = simulate_policy(
        tape, PolicyCell(1, 0, 0), bin_step=4, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=Decimal(1000), recenter_cost_fraction=Decimal("0.001"),
    )
    assert result.recenter_count == 1
    assert result.recenter_times == (120,)
    assert result.recenter_cost_quote > 0
    passive = simulate_policy(
        tape, PolicyCell(1, 0, 0, never_recenter=True), bin_step=4, x_decimals=9,
        y_decimals=6, active_bin_tvl_quote=Decimal(1000),
        recenter_cost_fraction=Decimal("0.001"),
    )
    assert passive.recenter_count == 0


def test_a_dwell_brake_ignores_a_single_wick():
    # Out at t=60, back in at t=120: a 300 s dwell must not recenter.
    tape = [_record(0, 0), _record(60, 5), _record(120, 0), _record(600, 0)]
    braked = simulate_policy(
        tape, PolicyCell(1, 0, 300), bin_step=4, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=Decimal(1000), recenter_cost_fraction=Decimal(0),
    )
    eager = simulate_policy(
        tape, PolicyCell(1, 0, 0), bin_step=4, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=Decimal(1000), recenter_cost_fraction=Decimal(0),
    )
    assert braked.recenter_count == 0
    # Eager pays twice: once chasing the wick, once coming home.
    assert eager.recenter_count == 2


def test_round_trip_through_the_band_realizes_the_conversion_spread():
    # Up through the whole band and back: each crossed bin converts at its own price on
    # the way up and back at the same price on the way down — no loss in this model
    # without a recenter, and the final value returns to the deposit.
    tape = [_record(0, 0), _record(60, 3), _record(120, 0)]
    result = simulate_policy(
        tape, PolicyCell(2, 10, 0), bin_step=100, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=Decimal(10**9), recenter_cost_fraction=Decimal(0),
    )
    assert result.recenter_count == 0
    assert result.final_value_quote.quantize(Decimal("1e-12")) == Decimal(1).quantize(
        Decimal("1e-12")
    )
    # But recentering at the top crystallizes the shift: the recentered run ends lower.
    recentered = simulate_policy(
        tape, PolicyCell(2, 0, 0), bin_step=100, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=Decimal(10**9), recenter_cost_fraction=Decimal(0),
    )
    assert recentered.recenter_count == 2  # once at the top, once coming home
    assert recentered.final_value_quote < result.final_value_quote


def test_the_sweep_carries_baselines_split_and_equivalence_classes():
    tape = [_record(t, (t // 60) % 3, fee="0.2") for t in range(0, 1200, 30)]
    panel = sweep(
        tape, bin_step=4, x_decimals=9, y_decimals=6,
        active_bin_tvl_quote=Decimal(1000), recenter_cost_fraction=Decimal("0.0001"),
        half_widths=(1, 3), exit_tolerances=(0, 8), min_dwells_s=(0,),
    )
    names = [r.cell.name() for r in panel.full_window]
    assert "w3-passive" in names  # the unremovable wide-passive baseline
    assert panel.hodl_5050_net_full is not None  # the unremovable HODL baseline
    assert panel.first_half and panel.second_half  # the declared split
    assert panel.selected_cell in names
    assert "ONE POOL, ONE WINDOW" in panel.honesty["onePoolOneWindow"]
    # w=3 never exits a 0..2 walk; with g=0 and g=8 it behaves identically -> one class.
    flattened = [name for group in panel.equivalence_classes for name in group]
    assert "w3-g0-d0" in flattened and "w3-g8-d0" in flattened
