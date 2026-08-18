from __future__ import annotations

from dataclasses import replace

import pytest

from joshi_analysis.wave6_routed_shadow import (
    Direction,
    DlmmBinEdge,
    DlmmFeePolicy,
    DlmmMathRefusal,
    ExactArithmeticError,
    FixedBin,
    FlowOrigin,
    ProtocolQuoteRefusal,
    PumpFeeSchedule,
    SourceCut,
    canonical_bytes,
    decimal_atoms,
    dlmm_dynamic_fee_rate,
    dlmm_fee_from_gross,
    dlmm_fee_from_net,
    dlmm_price_q64,
    dlmm_protocol_fee,
    pump_curve_buy_exact_base_out,
    pump_curve_sell_exact_base_in,
    pumpswap_buy_exact_base_out,
    pumpswap_sell_exact_base_in,
)
from joshi_analysis.wave6_routed_shadow.arithmetic import Q64
from joshi_analysis.wave6_routed_shadow.contracts import ExactQuote, QuoteLeg, QuoteRefusal

SOURCE_CUT = SourceCut("cut:101", 101, "profile:v1", "topology:1")


def test_pump_formulas_match_pinned_rounding_boundaries() -> None:
    fees = PumpFeeSchedule(lp_bps=0, protocol_bps=100, creator_bps=50)
    buy = pump_curve_buy_exact_base_out(
        base_out=100,
        virtual_base=1000,
        virtual_quote=500,
        real_base=800,
        fees=fees,
    )
    assert (buy.raw_quote_atoms, buy.input_atoms, buy.output_atoms) == (56, 58, 100)
    assert (buy.protocol_fee_atoms, buy.creator_fee_atoms) == (1, 1)

    exact_division = pump_curve_buy_exact_base_out(
        base_out=500,
        virtual_base=1000,
        virtual_quote=500,
        real_base=800,
        fees=fees,
    )
    assert exact_division.raw_quote_atoms == 501
    assert exact_division.input_atoms == 510

    sell = pump_curve_sell_exact_base_in(
        base_in=100,
        virtual_base=1000,
        virtual_quote=500,
        real_quote=400,
        fees=fees,
    )
    assert (sell.raw_quote_atoms, sell.output_atoms) == (45, 43)


def test_pumpswap_signed_reserve_and_real_vault_boundary_are_exact() -> None:
    quote = pumpswap_buy_exact_base_out(
        base_out=100,
        base_reserve=1000,
        raw_quote_reserve=2000,
        virtual_quote_reserve=-200,
        fees=PumpFeeSchedule(lp_bps=30, protocol_bps=20, creator_bps=10),
    )
    assert (quote.raw_quote_atoms, quote.input_atoms) == (200, 203)

    sell = pumpswap_sell_exact_base_in(
        base_in=100,
        base_reserve=1000,
        raw_quote_reserve=100,
        virtual_quote_reserve=1011,
        fees=PumpFeeSchedule(lp_bps=100, protocol_bps=0, creator_bps=0),
    )
    assert (sell.raw_quote_atoms, sell.lp_fee_atoms, sell.output_atoms) == (101, 2, 99)

    with pytest.raises(ProtocolQuoteRefusal, match="creator_fee_applicability_unknown"):
        pumpswap_sell_exact_base_in(
            base_in=100,
            base_reserve=1000,
            raw_quote_reserve=2000,
            virtual_quote_reserve=0,
            fees=PumpFeeSchedule(lp_bps=30, protocol_bps=20, creator_bps=None),
        )


def test_dlmm_price_and_dynamic_fee_match_pinned_vectors() -> None:
    assert dlmm_price_q64(-25_904, 1) == 1_383_501_207_885_697_265
    rate = dlmm_dynamic_fee_rate(
        base_factor=10_000,
        bin_step=20,
        base_fee_power_factor=1,
        variable_fee_control=7_500,
        volatility_accumulator=10_000,
    )
    assert rate == 20_003_000
    assert dlmm_fee_from_net(1_000_000, rate) == 20_412
    assert dlmm_fee_from_gross(1_000_000, rate) == 20_003
    assert dlmm_protocol_fee(20_003, 1_000) == 2_000

    with pytest.raises(DlmmMathRefusal, match="exponent_out_of_range"):
        dlmm_price_q64(0x80_000, 1)
    with pytest.raises(DlmmMathRefusal, match="arithmetic_overflow"):
        dlmm_dynamic_fee_rate(
            base_factor=1,
            bin_step=1,
            base_fee_power_factor=255,
            variable_fee_control=0,
            volatility_accumulator=0,
        )

    with pytest.raises(ProtocolQuoteRefusal, match="outside_u64"):
        pump_curve_sell_exact_base_in(
            base_in=2**64,
            virtual_base=1000,
            virtual_quote=500,
            real_quote=400,
            fees=PumpFeeSchedule(0, 0, 0),
        )


def test_nonlinear_bins_are_finite_and_state_dependent() -> None:
    edge = DlmmBinEdge(
        edge_id="ghost",
        schedule_id="schedule:nonlinear",
        state_id="state:0",
        asset_x="X",
        asset_y="Y",
        active_bin_id=0,
        fee_policy=DlmmFeePolicy(0, 0),
        bins=(
            FixedBin(-1, Q64, 0, 100),
            FixedBin(0, 2 * Q64, 0, 100),
        ),
        source_cut=SOURCE_CUT,
    )
    quote = edge.quote(Direction.X_TO_Y, 100)
    assert isinstance(quote, ExactQuote)
    assert quote.output_atoms == 150
    assert [(leg.segment_id, leg.input_atoms, leg.output_atoms) for leg in quote.legs] == [
        ("0", 50, 100),
        ("-1", 50, 50),
    ]

    updated = edge.apply(quote, FlowOrigin.EXTERNAL)
    assert updated.inventory().x_atoms == 100
    assert updated.inventory().y_atoms == 50
    refusal = updated.quote(Direction.X_TO_Y, 100)
    assert isinstance(refusal, QuoteRefusal)
    assert refusal.reason == "insufficient_finite_capacity"

    dormant = edge.with_active_bin(-2, "state:dormant").quote(Direction.X_TO_Y, 1)
    assert isinstance(dormant, QuoteRefusal)
    assert dormant.reason == "insufficient_finite_capacity"


def test_state_digest_alone_cannot_authorize_a_forged_quote_transition() -> None:
    edge = DlmmBinEdge(
        edge_id="ghost",
        schedule_id="schedule:forgery",
        state_id="state:forgery",
        asset_x="X",
        asset_y="Y",
        active_bin_id=0,
        fee_policy=DlmmFeePolicy(0, 0),
        bins=(FixedBin(0, Q64, 0, 500),),
        source_cut=SOURCE_CUT,
    )
    quote = edge.quote(Direction.X_TO_Y, 1)
    assert isinstance(quote, ExactQuote)
    forged = replace(
        quote,
        output_atoms=400,
        legs=(QuoteLeg("0", quote.trade_input_atoms, 400),),
    )
    assert forged.pre_state_digest == edge.state_digest
    with pytest.raises(ValueError, match="recomputation"):
        edge.apply(forged, FlowOrigin.EXTERNAL)
    assert edge.inventory().y_atoms == 500


def test_wire_atoms_and_artifacts_refuse_implicit_decimal_or_float_coercion() -> None:
    assert decimal_atoms(str(2**63 + 7)) == 2**63 + 7
    with pytest.raises(ExactArithmeticError):
        decimal_atoms("01")
    with pytest.raises(ExactArithmeticError):
        decimal_atoms("1.0")
    with pytest.raises(ExactArithmeticError):
        canonical_bytes({"not_exact": 1.5})

    first = canonical_bytes({"z": 2**80, "a": 1})
    second = canonical_bytes({"a": 1, "z": 2**80})
    assert first == second == b'{"a":"1","z":"1208925819614629174706176"}'
