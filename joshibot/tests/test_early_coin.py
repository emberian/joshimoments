from __future__ import annotations

import dataclasses
import math

import pytest

from shitcoims_intelligence.early_coin import (
    HARD_MAX_EVENTS,
    compute_early_coin_features,
    trade_observation_from_event,
)
from shitcoims_intelligence.pump import AdvisoryPumpEvent, PumpSchemaProvenance
from shitcoims_intelligence.pump_layouts import PUMP_AMM_PROGRAM_ID, PUMP_PROGRAM_ID

MINT = "mint-1"


def _event(program_id: str, event_name: str, **fields: object) -> AdvisoryPumpEvent:
    return AdvisoryPumpEvent(
        program_id=program_id,
        event_name=event_name,
        fields=fields,  # type: ignore[arg-type]
        provenance=PumpSchemaProvenance(
            repository="test",
            commit="test",
            idl_path="test",
            idl_sha256="0" * 64,
            discriminator_hex="0" * 16,
        ),
    )


def _pump_trade(
    timestamp: int,
    wallet: str,
    *,
    is_buy: bool,
    quote: int,
    base: int = 100,
    curve_quote: int = 100,
    curve_base: int = 100,
    mint: str = MINT,
) -> AdvisoryPumpEvent:
    return _event(
        PUMP_PROGRAM_ID,
        "TradeEvent",
        mint=mint,
        user=wallet,
        timestamp=timestamp,
        is_buy=is_buy,
        quote_amount=quote,
        sol_amount=quote,
        token_amount=base,
        virtual_quote_reserves=curve_quote,
        virtual_token_reserves=curve_base,
    )


def _amm_trade(
    event_name: str,
    timestamp: int,
    wallet: str,
    *,
    quote: int,
    base: int,
) -> AdvisoryPumpEvent:
    common = {
        "timestamp": timestamp,
        "user": wallet,
        "pool_quote_token_reserves": 400,
        "pool_base_token_reserves": 200,
    }
    if event_name == "BuyEvent":
        common.update(quote_amount_in=quote, base_amount_out=base)
    else:
        common.update(quote_amount_out=quote, base_amount_in=base)
    return _event(PUMP_AMM_PROGRAM_ID, event_name, **common)


def test_model_free_features_are_exact_and_event_time_based() -> None:
    create = _event(PUMP_PROGRAM_ID, "CreateEvent", mint=MINT, timestamp=90)
    # Intentionally unordered: output cannot depend on arrival order.
    events = [
        _pump_trade(130, "wallet-b", is_buy=False, quote=200, curve_quote=50),
        create,
        _pump_trade(100, "wallet-a", is_buy=True, quote=100, curve_quote=100),
        _pump_trade(110, "wallet-a", is_buy=True, quote=300, curve_quote=200),
    ]

    result = compute_early_coin_features(events, mint=MINT, as_of_timestamp=150)

    assert (result.launch_timestamp, result.age_seconds) == (90, 60)
    assert (result.first_trade_timestamp, result.last_trade_timestamp) == (100, 130)
    assert (result.trade_count, result.unique_wallet_count) == (3, 2)
    assert (result.buy_count, result.sell_count) == (2, 1)
    assert result.buy_quote_volume_atomic == 400
    assert result.sell_quote_volume_atomic == 200
    assert result.total_quote_volume_atomic == 600
    assert result.net_quote_flow_atomic == 200
    assert result.trade_count_imbalance == pytest.approx(1 / 3)
    assert result.quote_volume_imbalance == pytest.approx(1 / 3)
    assert result.wallet_volume_hhi == pytest.approx(5 / 9)
    assert result.effective_wallet_count == pytest.approx(1.8)
    assert result.top_wallet_quote_share == pytest.approx(2 / 3)
    assert result.returning_wallet_ratio == pytest.approx(0.5)
    assert result.median_interarrival_seconds == 15
    assert result.interarrival_cv == pytest.approx(1 / 3)
    assert result.interarrival_burstiness == pytest.approx(-0.5)
    assert (result.first_trade_price_atomic, result.last_trade_price_atomic) == (1.0, 2.0)
    assert result.trade_price_velocity_per_second == pytest.approx(math.log(2) / 30)
    assert result.max_trade_price_drawdown == pytest.approx(1 / 3)
    assert (result.first_curve_price_atomic, result.last_curve_price_atomic) == (1.0, 0.5)
    assert result.curve_price_velocity_per_second == pytest.approx(math.log(0.5) / 30)
    assert result.max_curve_price_drawdown == pytest.approx(0.75)
    assert result.quality.launch_time_basis == "create_event"
    assert result.quality.source_event_counts == (("TradeEvent", 3),)
    assert result.quality.missing_features == ()


def test_feature_snapshot_and_decoded_inputs_are_immutable_and_deterministic() -> None:
    first = _pump_trade(100, "b", is_buy=True, quote=100)
    second = _pump_trade(100, "a", is_buy=False, quote=200)
    one = compute_early_coin_features([first, second], mint=MINT)
    two = compute_early_coin_features([second, first], mint=MINT)

    assert one == two
    with pytest.raises(dataclasses.FrozenInstanceError):
        one.trade_count = 99  # type: ignore[misc]
    with pytest.raises(TypeError):
        first.fields["user"] = "changed"  # type: ignore[index]


def test_missingness_is_explicit_for_sparse_or_zero_amount_activity() -> None:
    result = compute_early_coin_features(
        [_pump_trade(100, "wallet-a", is_buy=True, quote=0, base=0, curve_quote=0)],
        mint=MINT,
    )

    assert result.quality.launch_time_basis == "first_trade"
    assert result.age_seconds == 0
    assert result.quote_volume_imbalance is None
    assert result.wallet_volume_hhi is None
    assert result.first_trade_price_atomic is None
    assert result.first_curve_price_atomic is None
    assert result.returning_wallet_ratio == 0
    assert result.quality.legacy_sol_amount_fallback_count == 0
    assert {
        "creation_timestamp",
        "median_interarrival_seconds",
        "wallet_volume_hhi",
        "first_trade_price_atomic",
        "first_curve_price_atomic",
    }.issubset(result.quality.missing_features)


def test_legacy_sol_amount_fallback_is_visible() -> None:
    event = _pump_trade(100, "wallet", is_buy=True, quote=50)
    fields = dict(event.fields)
    fields["quote_amount"] = 0
    legacy = _event(PUMP_PROGRAM_ID, "TradeEvent", **fields)

    result = compute_early_coin_features([legacy], mint=MINT)

    assert result.total_quote_volume_atomic == 50
    assert result.quality.legacy_sol_amount_fallback_count == 1


def test_amm_trades_require_explicit_collector_mint_attribution() -> None:
    buy = _amm_trade("BuyEvent", 100, "wallet-a", quote=200, base=100)
    sell = _amm_trade("SellEvent", 110, "wallet-b", quote=75, base=50)
    pump = _pump_trade(90, "wallet-c", is_buy=True, quote=10)

    excluded = compute_early_coin_features([pump, buy, sell], mint=MINT)
    included = compute_early_coin_features([pump, buy, sell], mint=MINT, amm_mint=MINT)

    assert excluded.trade_count == 1
    assert excluded.quality.unattributed_amm_trade_count == 2
    assert included.trade_count == 3
    assert included.quality.source_event_counts == (
        ("BuyEvent", 1),
        ("SellEvent", 1),
        ("TradeEvent", 1),
    )
    observation = trade_observation_from_event(buy, amm_mint=MINT)
    assert (observation.side, observation.trade_price_atomic, observation.curve_price_atomic) == (
        "buy",
        2.0,
        2.0,
    )
    with pytest.raises(ValueError, match="amm_mint is required"):
        trade_observation_from_event(buy)


def test_filtering_and_quality_counts_do_not_hide_scope_loss() -> None:
    other = _pump_trade(95, "other-wallet", is_buy=True, quote=1, mint="other-mint")
    complete = _event(PUMP_PROGRAM_ID, "CompleteEvent", mint=MINT, timestamp=105)

    result = compute_early_coin_features(
        [other, complete, _pump_trade(100, "wallet", is_buy=True, quote=10)], mint=MINT
    )

    assert result.quality.input_event_count == 3
    assert result.quality.accepted_trade_count == 1
    assert result.quality.ignored_other_mint_count == 1
    assert result.quality.ignored_non_trade_count == 1


def test_equal_looking_events_are_not_unsafely_deduplicated() -> None:
    event = _pump_trade(100, "wallet", is_buy=True, quote=10)

    result = compute_early_coin_features([event, event], mint=MINT)

    assert result.trade_count == 2
    assert any("not deduplicated" in item for item in result.quality.limitations)


def test_strict_boundaries_and_invalid_cutoffs_fail_closed() -> None:
    trade = _pump_trade(100, "wallet", is_buy=True, quote=10)

    with pytest.raises(ValueError, match="max_events"):
        compute_early_coin_features([trade, trade], mint=MINT, max_events=1)
    with pytest.raises(ValueError, match="between 1"):
        compute_early_coin_features([trade], mint=MINT, max_events=HARD_MAX_EVENTS + 1)
    with pytest.raises(ValueError, match="earlier"):
        compute_early_coin_features([trade], mint=MINT, as_of_timestamp=99)
    with pytest.raises(ValueError, match="no attributed"):
        compute_early_coin_features([], mint=MINT)
    with pytest.raises(TypeError, match="AdvisoryPumpEvent"):
        compute_early_coin_features([object()], mint=MINT)  # type: ignore[list-item]


def test_unsupported_event_program_pair_fails_closed() -> None:
    fake = _event(PUMP_PROGRAM_ID, "BuyEvent", timestamp=100)
    with pytest.raises(ValueError, match="unsupported Pump trade event"):
        trade_observation_from_event(fake)
