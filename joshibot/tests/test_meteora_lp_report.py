"""Tests for the Meteora DLMM dissipation harvest meter.

NO NETWORK. Every fixture below is a recorded/fabricated copy of a real API payload shape
(captured from https://dlmm.datapi.meteora.ag on 2026-08-13), trimmed to the fields the
reporter actually reads. The whole point of separating parsing from fetching in the script is
that these tests can drive the real arithmetic without a socket.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# scripts/ is not a package, so load the module by path rather than inventing an __init__.py
# in a directory of standalone operator tools.
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "meteora_lp_report.py"
_spec = importlib.util.spec_from_file_location("meteora_lp_report", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
mlr = importlib.util.module_from_spec(_spec)
sys.modules["meteora_lp_report"] = mlr
_spec.loader.exec_module(mlr)


# ---------------------------------------------------------------------------------------
# Fixtures: recorded shapes from the live API.
# ---------------------------------------------------------------------------------------

# One entry of `positions[]` from GET /positions/{pool_address}/pnl?user={wallet}
# Recorded from the live weave/nosis position, with round numbers substituted so the expected
# arithmetic below is checkable by hand.
POSITION_RAW = {
    "positionAddress": "42aaKzntryGGgzucpqEGuL4tREx9oWfMFTYSwTiFMPLB",
    "minPrice": "0.4",
    "maxPrice": "1.6",
    "lowerBinId": -33,
    "upperBinId": 1,
    "poolActiveBinId": -20,
    "isOutOfRange": False,
    "poolActivePrice": "0.8",
    "feePerTvl24h": "20.0",
    "isClosed": False,
    "createdAt": 1786600000,
    "closedAt": None,
    "updatedAt": 1786686400,
    "pnlUsd": "37.5",
    "pnlPctChange": "5.0",
    "allTimeDeposits": {"total": {"usd": "750.0", "sol": "9.85"}},
    "allTimeWithdrawals": {"total": {"usd": "0", "sol": "0"}},
    "allTimeFees": {
        "tokenX": {"amount": "76185.37", "usd": "11.0"},
        "tokenY": {"amount": "12202.9", "usd": "4.0"},
        "total": {"usd": "15.0", "sol": "0.19"},
    },
    "unrealizedPnl": {
        "balances": 1000.0,
        "balancesSol": "13.1",
        "balanceTokenX": {"amount": "2996526.8", "usd": "600.0"},
        "balanceTokenY": {"amount": "1433246.4", "usd": "400.0"},
        "unclaimedFeeTokenX": {"amount": "1000.0", "usd": "2.0"},
        "unclaimedFeeTokenY": {"amount": "5881.1", "usd": "3.0"},
        "unclaimedRewardTokenX": {"amount": "0", "usd": "0"},
        "unclaimedRewardTokenY": {"amount": "0", "usd": "0"},
    },
}

# One entry of `pools[]` from GET /portfolio/open?user={wallet}
POOL_CONTEXT = {
    "poolAddress": "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD",
    "binStep": 300,
    "tokenXMint": "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump",
    "tokenYMint": "FPfi9q1AixdUeWQVPFHJMJQ7a43S78dm6UZ4fzN4pump",
    "tokenX": "weave",
    "tokenY": "nosis",
    "outOfRange": False,
    "listPositions": ["42aaKzntryGGgzucpqEGuL4tREx9oWfMFTYSwTiFMPLB"],
}

# GET /portfolio/total?user={wallet}
PORTFOLIO_TOTAL = {
    "totalPnlUsd": "741.2595939071143",
    "totalPnlSol": "10.879508828432733",
    "totalPnlPctChange": "3.3991489481428965",
    "totalClosedPositions": 39,
}

# createdAt + exactly one day, so age_days == 1.0 and the rate arithmetic is exact.
NOW = 1786600000 + 86400


# ---------------------------------------------------------------------------------------
# Scalar coercion.
# ---------------------------------------------------------------------------------------


class TestToFloat:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("1.5", 1.5),
            (1.5, 1.5),
            (2, 2.0),
            ("  3.25  ", 3.25),
            ("1.8759149441802206e-06", 1.8759149441802206e-06),
            ("-214.01", -214.01),
        ],
    )
    def test_parses_numbers_in_both_json_encodings(self, value, expected):
        # The API returns numbers as strings in some fields and as JSON numbers in others.
        assert mlr.to_float(value) == expected

    @pytest.mark.parametrize("value", [None, "", "   ", "abc", {}, [], "n/a"])
    def test_non_numeric_degrades_to_none(self, value):
        assert mlr.to_float(value) is None

    def test_bools_are_not_numbers(self):
        # bool is an int subclass in Python; True must not silently become 1.0 in a USD sum.
        assert mlr.to_float(True) is None
        assert mlr.to_float(False) is None

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf", float("nan"), float("inf")])
    def test_nan_and_infinity_are_rejected(self, value):
        # A single inf would poison every downstream portfolio sum silently.
        assert mlr.to_float(value) is None


class TestDig:
    def test_walks_nested_path(self):
        assert mlr.dig({"a": {"b": {"c": 7}}}, "a", "b", "c") == 7

    def test_missing_key_anywhere_yields_none(self):
        assert mlr.dig({"a": {"b": {}}}, "a", "b", "c") is None
        assert mlr.dig({"a": {}}, "a", "b", "c") is None
        assert mlr.dig({}, "a", "b", "c") is None

    def test_non_dict_midway_yields_none_instead_of_raising(self):
        # A closed position has `unrealizedPnl: null`; walking into it must not explode.
        assert mlr.dig({"a": None}, "a", "b") is None
        assert mlr.dig({"a": 5}, "a", "b") is None


# ---------------------------------------------------------------------------------------
# The in/out-of-range calculation.
# ---------------------------------------------------------------------------------------


class TestIsInRange:
    def test_active_bin_strictly_inside(self):
        assert mlr.is_in_range(-33, 1, -20) is True

    def test_bounds_are_inclusive_at_both_ends(self):
        # A position whose range ends exactly at the active bin still holds liquidity there
        # and is still earning. Treating the ends as exclusive would report a working
        # position as idle.
        assert mlr.is_in_range(-33, 1, -33) is True
        assert mlr.is_in_range(-33, 1, 1) is True

    def test_active_bin_outside_either_side(self):
        assert mlr.is_in_range(-33, 1, -34) is False
        assert mlr.is_in_range(-33, 1, 2) is False

    def test_single_bin_position(self):
        assert mlr.is_in_range(5, 5, 5) is True
        assert mlr.is_in_range(5, 5, 6) is False

    def test_reversed_bounds_are_normalized(self):
        # Defensive: never report "out of range" purely because the bounds arrived swapped.
        assert mlr.is_in_range(1, -33, -20) is True
        assert mlr.is_in_range(1, -33, 99) is False

    def test_negative_bin_ids(self):
        # Real positions live at negative bin ids (weave/SOL sits at [-633, -579]).
        assert mlr.is_in_range(-633, -579, -631) is True
        assert mlr.is_in_range(-633, -579, -700) is False

    @pytest.mark.parametrize(
        ("low", "high", "active"),
        [(None, 1, -20), (-33, None, -20), (-33, 1, None), (None, None, None)],
    )
    def test_missing_inputs_yield_unknown_not_a_guess(self, low, high, active):
        # Guessing "in range" on missing data would report an idle position as earning.
        assert mlr.is_in_range(low, high, active) is None


# ---------------------------------------------------------------------------------------
# Fee-rate arithmetic.
# ---------------------------------------------------------------------------------------


class TestFeeRatePerDay:
    def test_basic_rate(self):
        # $10 of fees on $1000 of value over 1 day == 1%/day.
        assert mlr.fee_rate_per_day(10.0, 1000.0, 1.0) == pytest.approx(0.01)

    def test_rate_scales_inversely_with_age(self):
        # The same fees earned in half the time is twice the daily rate.
        assert mlr.fee_rate_per_day(10.0, 1000.0, 0.5) == pytest.approx(0.02)

    def test_rate_scales_inversely_with_value(self):
        assert mlr.fee_rate_per_day(10.0, 500.0, 1.0) == pytest.approx(0.02)

    def test_short_window_produces_large_but_finite_rate(self):
        # ~3 hours. This is the live case; the rate is real arithmetic but a thin sample.
        assert mlr.fee_rate_per_day(14.4, 752.0, 0.125) == pytest.approx(0.15319, rel=1e-3)

    @pytest.mark.parametrize(
        ("fees", "value", "age"),
        [(None, 1000.0, 1.0), (10.0, None, 1.0), (10.0, 1000.0, None)],
    )
    def test_missing_input_yields_none(self, fees, value, age):
        assert mlr.fee_rate_per_day(fees, value, age) is None

    @pytest.mark.parametrize(("value", "age"), [(0.0, 1.0), (1000.0, 0.0), (-5.0, 1.0), (1000.0, -1.0)])
    def test_zero_or_negative_denominator_yields_none_not_infinity(self, value, age):
        # A brand-new position has age 0. "infinity percent per day" is a worse answer than
        # "unknown", and a ZeroDivisionError would take the whole report down.
        assert mlr.fee_rate_per_day(10.0, value, age) is None

    def test_zero_fees_is_a_real_zero_not_missing(self):
        # A position that has earned nothing must report 0%/day, not "n/a".
        assert mlr.fee_rate_per_day(0.0, 1000.0, 1.0) == 0.0


class TestAnnualized:
    def test_simple_linear_annualization(self):
        assert mlr.annualized(0.01) == pytest.approx(3.65)

    def test_none_propagates(self):
        assert mlr.annualized(None) is None


# ---------------------------------------------------------------------------------------
# Position parsing.
# ---------------------------------------------------------------------------------------


class TestParsePosition:
    @pytest.fixture
    def parsed(self):
        return mlr.parse_position(POSITION_RAW, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)

    def test_identity_and_pair(self, parsed):
        assert parsed.position_address == "42aaKzntryGGgzucpqEGuL4tREx9oWfMFTYSwTiFMPLB"
        assert parsed.pool_address == "QQnW4Zw3Z1PM3FsLxFPW32DodZLLx9S9EbdaA764FFD"
        assert parsed.pair == "weave/nosis"
        assert parsed.is_closed is False

    def test_bin_range_as_prices(self, parsed):
        assert parsed.min_price == 0.4
        assert parsed.max_price == 1.6
        assert parsed.active_price == 0.8
        assert (parsed.lower_bin_id, parsed.upper_bin_id, parsed.active_bin_id) == (-33, 1, -20)

    def test_in_range_is_computed_and_agrees_with_api(self, parsed):
        assert parsed.in_range is True
        assert parsed.range_flag_conflict is False

    def test_token_legs_carry_amount_symbol_and_usd(self, parsed):
        assert parsed.token_x.symbol == "weave"
        assert parsed.token_x.amount == pytest.approx(2996526.8)
        assert parsed.token_x.usd == 600.0
        assert parsed.token_y.symbol == "nosis"
        assert parsed.token_y.usd == 400.0
        assert parsed.token_x.mint == "8PecVcCGs2HphgU5vxoWfqe4XTojaN2LWdy4FvZzpump"

    def test_position_value(self, parsed):
        assert parsed.value_usd == 1000.0
        assert parsed.value_sol == pytest.approx(13.1)

    def test_unclaimed_fees_sum_both_token_legs(self, parsed):
        assert parsed.unclaimed_fees_usd == pytest.approx(5.0)  # 2.0 + 3.0
        assert parsed.unclaimed_fee_x.amount == pytest.approx(1000.0)
        assert parsed.unclaimed_fee_y.amount == pytest.approx(5881.1)

    def test_claimed_and_lifetime_fees_are_distinct_quantities(self, parsed):
        # THE semantic that makes or breaks the number: allTimeFees is fees ALREADY CLAIMED,
        # verified against the claim_fee event log on live positions. Lifetime earned is
        # claimed + unclaimed. Conflating them undercounts every position with pending fees.
        assert parsed.claimed_fees_usd == 15.0
        assert parsed.unclaimed_fees_usd == pytest.approx(5.0)
        assert parsed.lifetime_fees_usd == pytest.approx(20.0)

    def test_capital_flows(self, parsed):
        assert parsed.deposits_usd == 750.0
        assert parsed.withdrawals_usd == 0.0
        assert parsed.pnl_usd == 37.5
        assert parsed.pnl_pct == 5.0

    def test_age_measured_from_creation_to_now(self, parsed):
        assert parsed.age_days == pytest.approx(1.0)

    def test_harvest_rate(self, parsed):
        # lifetime 20.0 / value 1000.0 / 1 day == 2%/day.
        assert parsed.fee_rate_per_day == pytest.approx(0.02)
        assert parsed.fee_rate_annualized == pytest.approx(7.3)

    def test_api_rate_is_normalized_from_percent_to_fraction(self, parsed):
        # The API reports feePerTvl24h as a percent (20.0 == 20%/day); ours is a fraction.
        # Without this normalization the cross-check would be off by 100x.
        assert parsed.api_fee_per_tvl_24h == pytest.approx(0.20)

    def test_day_old_sample_is_not_flagged_thin(self, parsed):
        assert parsed.rate_is_thin is False

    def test_short_sample_is_flagged_thin(self):
        raw = {**POSITION_RAW, "createdAt": NOW - 3600}  # one hour old
        parsed = mlr.parse_position(raw, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        assert parsed.age_days == pytest.approx(1 / 24)
        assert parsed.rate_is_thin is True
        # The rate is still computed -- flagged, not suppressed.
        assert parsed.fee_rate_per_day is not None and parsed.fee_rate_per_day > 0


class TestParsePositionRangeEdgeCases:
    def test_out_of_range_position(self):
        raw = {**POSITION_RAW, "poolActiveBinId": 50, "isOutOfRange": True}
        parsed = mlr.parse_position(raw, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        assert parsed.in_range is False
        assert parsed.range_flag_conflict is False

    def test_conflict_between_our_arithmetic_and_the_api_flag_is_surfaced(self):
        # Active bin is plainly inside [-33, 1] but the API claims out-of-range. We keep our
        # own answer and raise the flag rather than silently picking one.
        raw = {**POSITION_RAW, "poolActiveBinId": -20, "isOutOfRange": True}
        parsed = mlr.parse_position(raw, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        assert parsed.in_range is True
        assert parsed.range_flag_conflict is True

    def test_falls_back_to_api_flag_when_bin_ids_are_absent(self):
        raw = {key: value for key, value in POSITION_RAW.items() if "BinId" not in key}
        raw["isOutOfRange"] = True
        parsed = mlr.parse_position(raw, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        assert parsed.in_range is False
        assert parsed.range_flag_conflict is False

    def test_unknown_when_neither_bins_nor_flag_are_present(self):
        raw = {key: value for key, value in POSITION_RAW.items() if "BinId" not in key}
        raw.pop("isOutOfRange")
        parsed = mlr.parse_position(raw, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        assert parsed.in_range is None


class TestParsePositionMissingFields:
    """The API omits whole blocks in real responses. None of it may raise."""

    def test_empty_payload_produces_an_all_unknown_report(self):
        parsed = mlr.parse_position({}, now_epoch_seconds=NOW)
        assert parsed.position_address is None
        assert parsed.value_usd is None
        assert parsed.unclaimed_fees_usd is None
        assert parsed.lifetime_fees_usd is None
        assert parsed.in_range is None
        assert parsed.fee_rate_per_day is None
        assert parsed.age_days is None

    def test_closed_position_has_no_unrealized_block(self):
        # Recorded shape: the live closed DREGG/nosis position had no `unrealizedPnl` key at
        # all. Reading value/unclaimed fees off it must degrade, not raise.
        raw = {
            "positionAddress": "HQnnNDKQzvYZSjfRrsKDLarg114JoAkqXjM5UfVD7fBe",
            "isClosed": True,
            "createdAt": 1786600000,
            "closedAt": 1786600000 + 43200,  # half a day
            "minPrice": "0.85",
            "maxPrice": "1.35",
            "lowerBinId": -10,
            "upperBinId": 10,
            "poolActiveBinId": 0,
            "isOutOfRange": False,
            "pnlUsd": "-214.01",
            "allTimeDeposits": {"total": {"usd": "500.0"}},
            "allTimeFees": {"total": {"usd": "25.0"}},
        }
        parsed = mlr.parse_position(raw, now_epoch_seconds=NOW)
        assert parsed.is_closed is True
        assert parsed.value_usd is None
        assert parsed.unclaimed_fees_usd is None
        # Lifetime still reports the claimed side rather than collapsing to None.
        assert parsed.lifetime_fees_usd == 25.0
        # Age is measured to the CLOSE time, not to now -- otherwise a position closed long
        # ago would have its rate diluted toward zero by dead time it never traded through.
        assert parsed.age_days == pytest.approx(0.5)
        # With no live value the rate falls back to deposited capital: 25/500/0.5 == 10%/day.
        assert parsed.fee_rate_per_day == pytest.approx(0.10)

    def test_null_valued_fields_are_tolerated(self):
        raw = {
            "positionAddress": "abc",
            "minPrice": None,
            "maxPrice": None,
            "lowerBinId": None,
            "upperBinId": None,
            "poolActiveBinId": None,
            "isOutOfRange": None,
            "feePerTvl24h": None,
            "createdAt": None,
            "allTimeFees": {"total": {"usd": None}},
            "unrealizedPnl": {
                "balances": None,
                "unclaimedFeeTokenX": {"amount": None, "usd": None},
                "unclaimedFeeTokenY": {"amount": None, "usd": None},
            },
        }
        parsed = mlr.parse_position(raw, now_epoch_seconds=NOW)
        assert parsed.value_usd is None
        assert parsed.unclaimed_fees_usd is None
        assert parsed.api_fee_per_tvl_24h is None
        assert parsed.in_range is None

    def test_one_missing_fee_leg_still_reports_the_other(self):
        # Single-sided fee accrual is normal in DLMM; the present leg must survive.
        raw = {
            "unrealizedPnl": {
                "balances": 100.0,
                "unclaimedFeeTokenX": {"usd": "1.75"},
                "unclaimedFeeTokenY": {},
            }
        }
        parsed = mlr.parse_position(raw, now_epoch_seconds=NOW)
        assert parsed.unclaimed_fees_usd == pytest.approx(1.75)

    def test_missing_pool_context_still_parses(self):
        parsed = mlr.parse_position(POSITION_RAW, now_epoch_seconds=NOW)
        assert parsed.pair is None
        assert parsed.pool_address is None
        assert parsed.value_usd == 1000.0  # the numbers still land

    def test_created_in_the_future_does_not_produce_negative_age(self):
        raw = {**POSITION_RAW, "createdAt": NOW + 10_000}
        parsed = mlr.parse_position(raw, now_epoch_seconds=NOW)
        assert parsed.age_days == 0.0
        # A zero denominator must yield unknown, not an exception or an infinity.
        assert parsed.fee_rate_per_day is None


# ---------------------------------------------------------------------------------------
# Portfolio rollup.
# ---------------------------------------------------------------------------------------


def _position(**overrides):
    base = {
        "value_usd": 1000.0,
        "unclaimed_fees_usd": 5.0,
        "claimed_fees_usd": 15.0,
        "lifetime_fees_usd": 20.0,
        "deposits_usd": 750.0,
        "pnl_usd": 37.5,
        "age_days": 1.0,
    }
    base.update(overrides)
    return mlr.PositionReport(**base)


class TestBuildPortfolio:
    def test_sums_across_positions(self):
        report = mlr.build_portfolio("WALLET", [_position(), _position()])
        assert report.total_value_usd == 2000.0
        assert report.total_unclaimed_usd == 10.0
        assert report.total_claimed_usd == 30.0
        assert report.total_lifetime_fees_usd == 40.0
        assert report.total_deposits_usd == 1500.0
        assert report.open_pnl_usd == 75.0

    def test_portfolio_rate_is_value_weighted_not_a_mean_of_rates(self):
        # A tiny, minutes-old position has an astronomical per-position rate. Averaging the
        # rates would let it dominate the portfolio number; weighting by value does not.
        big = _position(value_usd=10_000.0, lifetime_fees_usd=100.0, age_days=10.0)
        tiny = _position(value_usd=1.0, lifetime_fees_usd=1.0, age_days=0.001)
        report = mlr.build_portfolio("WALLET", [big, tiny])
        # Naive mean of per-position rates would be ~500/day; the weighted answer stays sane.
        assert report.portfolio_fee_rate_per_day is not None
        assert report.portfolio_fee_rate_per_day < 0.02

    def test_empty_portfolio_is_all_none_not_an_exception(self):
        report = mlr.build_portfolio("WALLET", [])
        assert report.positions == []
        assert report.total_value_usd is None
        assert report.portfolio_fee_rate_per_day is None

    def test_partial_data_still_rolls_up_the_rest(self):
        report = mlr.build_portfolio("WALLET", [_position(), _position(unclaimed_fees_usd=None)])
        # One position missing a field must not collapse the whole portfolio total.
        assert report.total_unclaimed_usd == 5.0
        assert report.total_value_usd == 2000.0

    def test_realized_pnl_folded_in_from_portfolio_total(self):
        report = mlr.build_portfolio("WALLET", [_position()], portfolio_total=PORTFOLIO_TOTAL)
        assert report.realized_pnl_usd == pytest.approx(741.2595939071143)
        assert report.realized_pnl_sol == pytest.approx(10.879508828432733)
        assert report.closed_position_count == 39

    def test_missing_portfolio_total_is_tolerated(self):
        report = mlr.build_portfolio("WALLET", [_position()], portfolio_total=None)
        assert report.realized_pnl_usd is None
        assert report.closed_position_count is None

    def test_sol_price_read_from_open_envelope(self):
        report = mlr.build_portfolio("WALLET", [_position()], open_total={"solPrice": "76.15"})
        assert report.sol_price_usd == pytest.approx(76.15)


class TestWeightedMeanAge:
    def test_weights_by_value(self):
        positions = [
            mlr.PositionReport(age_days=10.0, value_usd=900.0),
            mlr.PositionReport(age_days=1.0, value_usd=100.0),
        ]
        assert mlr._weighted_mean_age(positions) == pytest.approx(9.1)

    def test_falls_back_to_plain_mean_without_value_weights(self):
        positions = [mlr.PositionReport(age_days=4.0), mlr.PositionReport(age_days=2.0)]
        assert mlr._weighted_mean_age(positions) == pytest.approx(3.0)

    def test_no_ages_at_all(self):
        assert mlr._weighted_mean_age([mlr.PositionReport()]) is None


# ---------------------------------------------------------------------------------------
# Rendering. Must never raise, including on sparse data.
# ---------------------------------------------------------------------------------------


class TestRendering:
    def test_text_report_contains_the_headline_numbers(self):
        parsed = mlr.parse_position(POSITION_RAW, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        report = mlr.build_portfolio("WALLET", [parsed], portfolio_total=PORTFOLIO_TOTAL)
        text = mlr.render_text(report)
        assert "weave/nosis" in text
        assert "IN RANGE" in text
        assert "UNCLAIMED" in text
        assert "$5.00" in text  # unclaimed
        assert "2.00%/day" in text  # harvest rate
        assert "39 closed positions" in text

    def test_out_of_range_is_labelled_idle(self):
        raw = {**POSITION_RAW, "poolActiveBinId": 50, "isOutOfRange": True}
        parsed = mlr.parse_position(raw, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        text = mlr.render_text(mlr.build_portfolio("WALLET", [parsed]))
        assert "OUT OF RANGE" in text

    def test_thin_sample_warning_is_visible(self):
        raw = {**POSITION_RAW, "createdAt": NOW - 3600}
        parsed = mlr.parse_position(raw, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        text = mlr.render_text(mlr.build_portfolio("WALLET", [parsed]))
        assert "THIN SAMPLE" in text

    def test_conflict_warning_is_visible(self):
        raw = {**POSITION_RAW, "isOutOfRange": True}
        parsed = mlr.parse_position(raw, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        text = mlr.render_text(mlr.build_portfolio("WALLET", [parsed]))
        assert "DISAGREES" in text

    def test_empty_portfolio_says_so_plainly(self):
        report = mlr.build_portfolio("EMPTY", [], portfolio_total=PORTFOLIO_TOTAL)
        text = mlr.render_text(report)
        assert "No OPEN DLMM positions found" in text
        assert "39 closed positions" in text

    def test_sparse_position_renders_without_raising(self):
        parsed = mlr.parse_position({}, now_epoch_seconds=NOW)
        text = mlr.render_text(mlr.build_portfolio("WALLET", [parsed]))
        assert "n/a" in text

    def test_json_round_trips(self):
        import json as _json

        parsed = mlr.parse_position(POSITION_RAW, pool_context=POOL_CONTEXT, now_epoch_seconds=NOW)
        report = mlr.build_portfolio("WALLET", [parsed], portfolio_total=PORTFOLIO_TOTAL)
        payload = _json.loads(mlr.render_json(report))
        assert payload["wallet"] == "WALLET"
        assert payload["positions"][0]["pair"] == "weave/nosis"
        assert payload["positions"][0]["unclaimed_fees_usd"] == pytest.approx(5.0)
        assert payload["positions"][0]["token_x"]["symbol"] == "weave"
        assert payload["total_lifetime_fees_usd"] == pytest.approx(20.0)


class TestFormatters:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(None, "n/a"), (0.0, "$0.00"), (1283.8786, "$1,283.88"), (-214.0, "$-214.00")],
    )
    def test_usd(self, value, expected):
        assert mlr._usd(value) == expected

    def test_pct_converts_fraction_to_percent(self):
        assert mlr._pct(0.0950) == "9.50%"
        assert mlr._pct(None) == "n/a"

    def test_num_uses_scientific_notation_for_tiny_prices(self):
        # DLMM prices for memecoin pairs are routinely ~1e-06; fixed-point would print 0.
        assert "e-" in mlr._num(1.8759149441802206e-06)

    def test_num_keeps_zero_readable(self):
        assert mlr._num(0.0) == "0"


# ---------------------------------------------------------------------------------------
# The tool is read-only. This is the property that matters most.
# ---------------------------------------------------------------------------------------


class TestReadOnly:
    def test_no_write_capable_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("solders", "Keypair", "sendTransaction", "signTransaction", "private_key"):
            assert forbidden not in source, f"read-only reporter must not reference {forbidden}"

    def test_only_issues_get_requests(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        assert "method=" not in source  # urllib defaults to GET; nothing overrides it
        assert "data=" not in source  # a request body would make it a POST
