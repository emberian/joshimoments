"""The A/B split, window statistics, fee floors, sampling, and the interaction machinery."""

from decimal import Decimal

from joshi_analysis.scalplab.tape import TapeEvent
from joshi_analysis.workability.budget import BudgetExhausted, Ledger
from joshi_analysis.workability.callout import measure_entry_window
from joshi_analysis.workability.fees import venue_floor
from joshi_analysis.workability.interaction import (
    average_ranks,
    decile_contrast,
    spearman,
    spearman_with_permutation,
)
from joshi_analysis.workability.sample import age_bucket, mcap_bucket, stratify
from joshi_analysis.workability.stats import (
    outcome_statistics,
    split_events,
    window_statistics,
    windows_sufficient,
)

HOUR_US = 3_600_000_000


def event(
    ordinal: int, price: str, time_us: int, side: str = "buy", trader: str = "t"
) -> TapeEvent:
    sign = Decimal(1) if side == "buy" else Decimal(-1)
    return TapeEvent(
        ordinal=ordinal,
        mint="M",
        side=side,
        price=Decimal(price),
        fill_price=None,
        base_signed=sign,
        quote_signed=sign,
        trader=trader,
        venue="pump_amm",
        tx=f"tx{ordinal}",
        slot=100 + ordinal,
        event_time_us=time_us,
        arrival_wall_us=None,
    )


class TestSplit:
    def test_split_at_half_the_event_time_span(self):
        events = [event(i, "1.0", i * HOUR_US) for i in range(4)]  # span 3h, split at 1.5h
        split = split_events(events)
        assert split is not None
        assert split.split_instant_us == HOUR_US + HOUR_US // 2
        assert len(split.window_a) == 2
        assert len(split.window_b) == 2

    def test_degenerate_span_refuses(self):
        events = [event(0, "1.0", 0), event(1, "1.0", 0)]
        assert split_events(events) is None

    def test_sufficiency_gate(self):
        events = [event(i, "1.0", i * 1_000_000) for i in range(60)]
        split = split_events(events)
        assert split is not None
        assert windows_sufficient(split)
        thin = split_events([event(i, "1.0", i * 1_000_000) for i in range(6)])
        assert thin is not None
        assert not windows_sufficient(thin)

    def test_a_dying_coin_is_an_outcome_not_an_insufficiency(self):
        # 30 events in the first minutes, then silence to the tape end: window B holds no
        # events but has a positive duration, so its rates are honest zeros (RUN note R1).
        events = [event(i, "1.0", i * 1_000_000) for i in range(30)]
        events.append(event(30, "1.0", 4 * HOUR_US))
        split = split_events(events)
        assert split is not None
        assert windows_sufficient(split)
        assert len(split.window_b) == 1
        outcomes = outcome_statistics(split.window_b, 250, split.b_duration_hours)
        assert outcomes["O4_tier32_legs_ph"] == 0.0

    def test_duration_denominator_beats_event_span(self):
        # Ten trades in the first minute of a two-hour window: 5 trades/hour, not 600.
        events = [event(i, "1.0", i * 6_000_000) for i in range(10)]
        stats = window_statistics(events, floor_bps=250, duration_hours=2.0)
        assert stats["S5_trades_ph"] == 5.0


class TestWindowStatistics:
    def test_statistics_carry_denominators_and_absences(self):
        events = [
            event(0, "1.00", 0, side="buy", trader="a"),
            event(1, "1.10", HOUR_US // 2, side="buy", trader="b"),
            event(2, "1.05", HOUR_US, side="sell", trader="a"),
        ]
        stats = window_statistics(events, floor_bps=250)
        assert stats["S5_trades_ph"] == 3.0
        assert stats["S6_unique_traders_ph"] == 2.0
        assert stats["S7_trader_concentration"] == 2 / 3
        # 2 buys of 1 quote, 1 sell of 1 quote: imbalance (2-1)/3.
        assert abs(stats["S8_buy_imbalance"] - 1 / 3) < 1e-12
        assert stats["S10_log_range"] is not None and stats["S10_log_range"] > 0
        assert stats["S13_log_mcap_proxy"] is not None

    def test_empty_window_is_absent_not_zero(self):
        stats = window_statistics([], floor_bps=250)
        assert stats["S5_trades_ph"] is None
        assert stats["S8_buy_imbalance"] is None


class TestFees:
    def test_bonding_coin_uses_the_measured_curve_floor(self):
        floor = venue_floor(graduated=False, market_cap_sol=100.0)
        assert floor.round_trip_bps == 247
        assert floor.basis == "curve_measured_m0"

    def test_low_cap_graduated_pool_is_first_row_worst_of_tables(self):
        floor = venue_floor(graduated=True, market_cap_sol=42.8)
        assert floor.round_trip_bps == 250  # 125 bps a leg, both tables' first row

    def test_disagreement_band_takes_the_worse_table(self):
        # At 100 SOL table zero is still on row 0 (125), table one on row 1 (120).
        floor = venue_floor(graduated=True, market_cap_sol=100.0)
        assert floor.round_trip_bps == 250

    def test_absent_cap_is_never_a_cheap_one(self):
        floor = venue_floor(graduated=True, market_cap_sol=None)
        assert floor.round_trip_bps == 250

    def test_above_the_retained_heads_is_clamped_and_labeled(self):
        floor = venue_floor(graduated=True, market_cap_sol=5_000.0)
        assert floor.round_trip_bps == 220  # 110 a leg, last retained row
        assert floor.basis == "tier_worst_of_tables_clamped"


class TestSample:
    def test_buckets(self):
        assert age_bucket(1.0) == "0-6h"
        assert age_bucket(30.0) == "24-48h"
        assert age_bucket(80.0) is None
        assert mcap_bucket(None) == "under_10k"
        assert mcap_bucket(20_000) == "10k_50k"

    def test_stratify_is_deterministic_and_reports_shortfall(self):
        now_ms = 1_700_000_000_000
        rows = [
            {
                "mint": f"mint{i}",
                "created_timestamp": now_ms - (i % 70) * 3_600_000,
                "usd_market_cap": 5_000.0 * (i % 20),
                "complete": i % 2 == 0,
            }
            for i in range(200)
        ]
        first = stratify(rows, now_ms, quota_per_cell=3, seed=7)
        second = stratify(rows, now_ms, quota_per_cell=3, seed=7)
        assert [d.drawn for d in first] == [d.drawn for d in second]
        assert all(len(d.drawn) <= 3 for d in first)
        thin = [d for d in first if d.available < d.quota]
        assert all(d.shortfall == d.quota - d.available for d in thin)

    def test_unaged_rows_are_excluded(self):
        draws = stratify([{"mint": "m", "usd_market_cap": 1.0}], 0, 3, seed=1)
        assert all(not d.drawn for d in draws)


class TestInteraction:
    def test_average_ranks_share_ties(self):
        assert average_ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]

    def test_spearman_on_monotone_data(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert abs(spearman(xs, [x * 2 for x in xs]) - 1.0) < 1e-12
        assert abs(spearman(xs, [-x for x in xs]) + 1.0) < 1e-12

    def test_permutation_p_is_deterministic_under_seed(self):
        xs = [float(i) for i in range(12)]
        ys = [float((i * 7) % 12) for i in range(12)]
        one = spearman_with_permutation(xs, ys, seed=5, permutations=200)
        two = spearman_with_permutation(xs, ys, seed=5, permutations=200)
        assert one == two
        assert one.p_permutation is not None and 0 < one.p_permutation <= 1

    def test_decile_contrast_control_excludes_the_top(self):
        statistic = [float(i) for i in range(30)]
        outcome = [float(i) for i in range(30)]
        contrast = decile_contrast(statistic, outcome, seed=3)
        assert contrast.n_top == 3
        assert contrast.n_control == 3
        assert contrast.median_top == 28.0  # indices 29, 28, 27
        assert contrast.median_control is not None
        assert contrast.median_control < contrast.median_top


class TestBudget:
    def test_refuses_before_spending_past_the_ceiling(self, tmp_path):
        ledger = Ledger(tmp_path, budget=3)
        ledger.reserve(2)
        ledger.record({"phase": "x", "requests": 2})
        ledger.reserve(1)
        ledger.record({"phase": "y", "requests": 1})
        try:
            ledger.reserve(1)
        except BudgetExhausted:
            pass
        else:
            raise AssertionError("a spend past the ceiling was not refused")
        assert ledger.spent() == 3
        assert ledger.by_phase() == {"x": 2, "y": 1}


class TestCalloutMeasure:
    def test_dip_and_wouldquote_arithmetic(self):
        t0 = 1_000_000  # ms
        base = t0 * 1000
        minute_us = 60_000_000
        events = [
            event(0, "1.00", base - 2 * minute_us),  # pre-window, proves entry coverage
            event(1, "1.00", base + minute_us),  # anchor
            event(2, "0.80", base + 5 * minute_us),  # the dip
            event(3, "1.20", base + 20 * minute_us),  # the peak
        ]
        row = measure_entry_window(events, t0, floor_bps=250)
        assert row is not None
        assert row["entry_covered"]
        assert row["dipped_below_anchor"]
        assert abs(row["dip_depth_pct"] + 20.0) < 0.1
        assert row["clears_hurdle_from_anchor"]  # 20% > 2.5%
        assert row["wouldquote_trough_to_peak_pct"] > row["wouldquote_anchor_to_peak_pct"]
        assert row["recovered_in_window"]

    def test_no_in_window_tape_is_none(self):
        events = [event(0, "1.0", 0)]
        assert measure_entry_window(events, t0_ms=10**12, floor_bps=250) is None
