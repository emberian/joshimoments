"""Deterministic, model-free features for the first minutes of a Pump coin.

This module is deliberately advisory.  It converts already-decoded, immutable Pump
events into descriptive statistics; it has no network, wallet, transaction, or
execution dependencies.  Amounts remain in raw on-chain atomic units because token
and quote decimals are not present in every event.  Ratios are therefore useful
within one market, while absolute amounts must not be compared across unlike quote
mints without normalization upstream.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Final, Literal

from shitcoims_intelligence.pump import AdvisoryPumpEvent
from shitcoims_intelligence.pump_layouts import PUMP_AMM_PROGRAM_ID, PUMP_PROGRAM_ID

DEFAULT_MAX_EVENTS: Final = 10_000
HARD_MAX_EVENTS: Final = 100_000
MAX_TIMESTAMP: Final = (1 << 63) - 1


@dataclasses.dataclass(frozen=True, slots=True)
class EarlyTradeObservation:
    """The bounded common denominator of Pump bonding-curve and AMM trades."""

    mint: str
    wallet: str
    timestamp: int
    side: Literal["buy", "sell"]
    quote_amount_atomic: int
    base_amount_atomic: int
    trade_price_atomic: float | None
    curve_price_atomic: float | None
    source_event: Literal["TradeEvent", "BuyEvent", "SellEvent"]
    used_legacy_sol_amount: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class EarlyCoinQuality:
    """Coverage and caveats that must travel with every feature vector."""

    input_event_count: int
    accepted_trade_count: int
    ignored_non_trade_count: int
    ignored_other_mint_count: int
    unattributed_amm_trade_count: int
    legacy_sol_amount_fallback_count: int
    launch_time_basis: Literal["create_event", "create_pool_event", "first_trade"]
    source_event_counts: tuple[tuple[str, int], ...]
    missing_features: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class EarlyCoinFeatures:
    """One immutable descriptive snapshot for one mint and one event-time cutoff."""

    mint: str
    as_of_timestamp: int
    launch_timestamp: int
    age_seconds: int
    first_trade_timestamp: int
    last_trade_timestamp: int
    trade_count: int
    unique_wallet_count: int
    buy_count: int
    sell_count: int
    buy_quote_volume_atomic: int
    sell_quote_volume_atomic: int
    total_quote_volume_atomic: int
    net_quote_flow_atomic: int
    trade_count_imbalance: float
    quote_volume_imbalance: float | None
    wallet_volume_hhi: float | None
    effective_wallet_count: float | None
    top_wallet_quote_share: float | None
    returning_wallet_ratio: float
    median_interarrival_seconds: float | None
    interarrival_cv: float | None
    interarrival_burstiness: float | None
    first_trade_price_atomic: float | None
    last_trade_price_atomic: float | None
    trade_price_velocity_per_second: float | None
    max_trade_price_drawdown: float | None
    first_curve_price_atomic: float | None
    last_curve_price_atomic: float | None
    curve_price_velocity_per_second: float | None
    max_curve_price_drawdown: float | None
    quality: EarlyCoinQuality


def compute_early_coin_features(
    events: Iterable[AdvisoryPumpEvent],
    *,
    mint: str,
    as_of_timestamp: int | None = None,
    amm_mint: str | None = None,
    max_events: int = DEFAULT_MAX_EVENTS,
) -> EarlyCoinFeatures:
    """Compute a bounded feature snapshot from decoded events.

    Pump ``TradeEvent`` and ``CreateEvent`` values carry a mint.  PumpSwap trade
    events do not, so ``amm_mint`` is required before those events can be included.
    Passing it is an assertion made by the transaction collector from account
    context, not an inference made here.

    Events are sorted deterministically by their normalized contents.  No event is
    deduplicated: the decoded Pump schema has no transaction signature/log index,
    and collapsing equal-looking trades could destroy legitimate activity.  The
    caller must deduplicate using its immutable source identity before this layer.
    """

    _validate_nonempty_text(mint, "mint")
    if amm_mint is not None:
        _validate_nonempty_text(amm_mint, "amm_mint")
    if not isinstance(max_events, int) or isinstance(max_events, bool):
        raise TypeError("max_events must be an integer")
    if not 1 <= max_events <= HARD_MAX_EVENTS:
        raise ValueError(f"max_events must be between 1 and {HARD_MAX_EVENTS}")

    materialized: list[AdvisoryPumpEvent] = []
    for event in events:
        if len(materialized) >= max_events:
            raise ValueError(f"input exceeds the max_events boundary of {max_events}")
        if not isinstance(event, AdvisoryPumpEvent):
            raise TypeError("events must contain AdvisoryPumpEvent values only")
        materialized.append(event)

    trades: list[EarlyTradeObservation] = []
    ignored_non_trade = 0
    ignored_other_mint = 0
    unattributed_amm = 0
    legacy_fallbacks = 0
    launch_candidates: list[tuple[int, Literal["create_event", "create_pool_event"]]] = []

    for event in materialized:
        if event.event_name == "CreateEvent":
            event_mint = _required_text(event, "mint")
            if event_mint == mint:
                launch_candidates.append((_required_timestamp(event, "timestamp"), "create_event"))
            else:
                ignored_other_mint += 1
            continue
        if event.event_name == "CreatePoolEvent":
            event_mint = _required_text(event, "base_mint")
            if event_mint == mint:
                launch_candidates.append((_required_timestamp(event, "timestamp"), "create_pool_event"))
            else:
                ignored_other_mint += 1
            continue

        if event.event_name not in {"TradeEvent", "BuyEvent", "SellEvent"}:
            ignored_non_trade += 1
            continue
        if event.program_id == PUMP_AMM_PROGRAM_ID and amm_mint is None:
            unattributed_amm += 1
            continue

        observation = trade_observation_from_event(event, amm_mint=amm_mint)
        if observation.mint != mint:
            ignored_other_mint += 1
            continue
        trades.append(observation)
        legacy_fallbacks += int(observation.used_legacy_sol_amount)

    if not trades:
        raise ValueError(f"no attributed trade events for mint {mint!r}")

    trades.sort(key=_trade_sort_key)
    first_trade_timestamp = trades[0].timestamp
    last_trade_timestamp = trades[-1].timestamp
    if as_of_timestamp is None:
        as_of = last_trade_timestamp
    else:
        as_of = _validate_timestamp(as_of_timestamp, "as_of_timestamp")
        if as_of < last_trade_timestamp:
            raise ValueError("as_of_timestamp cannot be earlier than the last accepted trade")

    eligible_launches = [
        candidate for candidate in launch_candidates if candidate[0] <= first_trade_timestamp
    ]
    if eligible_launches:
        launch_timestamp, launch_basis = min(eligible_launches, key=lambda item: (item[0], item[1]))
    else:
        launch_timestamp, launch_basis = first_trade_timestamp, "first_trade"

    buy_trades = tuple(trade for trade in trades if trade.side == "buy")
    sell_trades = tuple(trade for trade in trades if trade.side == "sell")
    buy_volume = sum(trade.quote_amount_atomic for trade in buy_trades)
    sell_volume = sum(trade.quote_amount_atomic for trade in sell_trades)
    total_volume = buy_volume + sell_volume
    trade_count = len(trades)

    wallet_counts = Counter(trade.wallet for trade in trades)
    wallet_volumes: defaultdict[str, int] = defaultdict(int)
    for trade in trades:
        wallet_volumes[trade.wallet] += trade.quote_amount_atomic

    if total_volume:
        shares = tuple(volume / total_volume for volume in wallet_volumes.values())
        hhi = sum(share * share for share in shares)
        effective_wallets = 1.0 / hhi
        top_share = max(shares)
        volume_imbalance = (buy_volume - sell_volume) / total_volume
    else:
        hhi = effective_wallets = top_share = volume_imbalance = None

    timestamps = tuple(trade.timestamp for trade in trades)
    intervals = tuple(later - earlier for earlier, later in itertools.pairwise(timestamps))
    if intervals:
        interval_median = float(statistics.median(intervals))
        interval_mean = statistics.fmean(intervals)
        interval_stddev = statistics.pstdev(intervals)
        if interval_mean > 0:
            interval_cv = interval_stddev / interval_mean
            burstiness = (interval_stddev - interval_mean) / (interval_stddev + interval_mean)
        else:
            interval_cv = burstiness = None
    else:
        interval_median = interval_cv = burstiness = None

    trade_prices = tuple(
        (trade.timestamp, trade.trade_price_atomic)
        for trade in trades
        if trade.trade_price_atomic is not None
    )
    curve_prices = tuple(
        (trade.timestamp, trade.curve_price_atomic)
        for trade in trades
        if trade.curve_price_atomic is not None
    )
    trade_first, trade_last, trade_velocity, trade_drawdown = _price_features(trade_prices)
    curve_first, curve_last, curve_velocity, curve_drawdown = _price_features(curve_prices)

    missing: set[str] = set()
    if launch_basis == "first_trade":
        missing.add("creation_timestamp")
    if not intervals:
        missing.update({"median_interarrival_seconds", "interarrival_cv", "interarrival_burstiness"})
    elif interval_cv is None:
        missing.update({"interarrival_cv", "interarrival_burstiness"})
    if hhi is None:
        missing.update(
            {
                "quote_volume_imbalance",
                "wallet_volume_hhi",
                "effective_wallet_count",
                "top_wallet_quote_share",
            }
        )
    if trade_first is None:
        missing.update(
            {
                "first_trade_price_atomic",
                "last_trade_price_atomic",
                "trade_price_velocity_per_second",
                "max_trade_price_drawdown",
            }
        )
    elif trade_velocity is None:
        missing.add("trade_price_velocity_per_second")
    if curve_first is None:
        missing.update(
            {
                "first_curve_price_atomic",
                "last_curve_price_atomic",
                "curve_price_velocity_per_second",
                "max_curve_price_drawdown",
            }
        )
    elif curve_velocity is None:
        missing.add("curve_price_velocity_per_second")

    source_counts = Counter(trade.source_event for trade in trades)
    limitations = (
        "atomic amounts are not decimal-normalized and must not be compared across unlike markets",
        "equal-looking events are not deduplicated; dedupe by transaction signature and log index upstream",
        "wallet concentration is address-level and does not identify common ownership "
        "or funded-wallet clusters",
        "features describe observed events only and do not establish predictive power",
    )
    if unattributed_amm:
        limitations += ("PumpSwap trades without collector-supplied mint attribution were excluded",)

    quality = EarlyCoinQuality(
        input_event_count=len(materialized),
        accepted_trade_count=trade_count,
        ignored_non_trade_count=ignored_non_trade,
        ignored_other_mint_count=ignored_other_mint,
        unattributed_amm_trade_count=unattributed_amm,
        legacy_sol_amount_fallback_count=legacy_fallbacks,
        launch_time_basis=launch_basis,
        source_event_counts=tuple(sorted(source_counts.items())),
        missing_features=tuple(sorted(missing)),
        limitations=limitations,
    )

    return EarlyCoinFeatures(
        mint=mint,
        as_of_timestamp=as_of,
        launch_timestamp=launch_timestamp,
        age_seconds=as_of - launch_timestamp,
        first_trade_timestamp=first_trade_timestamp,
        last_trade_timestamp=last_trade_timestamp,
        trade_count=trade_count,
        unique_wallet_count=len(wallet_counts),
        buy_count=len(buy_trades),
        sell_count=len(sell_trades),
        buy_quote_volume_atomic=buy_volume,
        sell_quote_volume_atomic=sell_volume,
        total_quote_volume_atomic=total_volume,
        net_quote_flow_atomic=buy_volume - sell_volume,
        trade_count_imbalance=(len(buy_trades) - len(sell_trades)) / trade_count,
        quote_volume_imbalance=volume_imbalance,
        wallet_volume_hhi=hhi,
        effective_wallet_count=effective_wallets,
        top_wallet_quote_share=top_share,
        returning_wallet_ratio=sum(count > 1 for count in wallet_counts.values()) / len(wallet_counts),
        median_interarrival_seconds=interval_median,
        interarrival_cv=interval_cv,
        interarrival_burstiness=burstiness,
        first_trade_price_atomic=trade_first,
        last_trade_price_atomic=trade_last,
        trade_price_velocity_per_second=trade_velocity,
        max_trade_price_drawdown=trade_drawdown,
        first_curve_price_atomic=curve_first,
        last_curve_price_atomic=curve_last,
        curve_price_velocity_per_second=curve_velocity,
        max_curve_price_drawdown=curve_drawdown,
        quality=quality,
    )


def trade_observation_from_event(
    event: AdvisoryPumpEvent, *, amm_mint: str | None = None
) -> EarlyTradeObservation:
    """Normalize one supported trade event, failing closed on missing attribution."""

    if not isinstance(event, AdvisoryPumpEvent):
        raise TypeError("event must be an AdvisoryPumpEvent")

    if event.program_id == PUMP_PROGRAM_ID and event.event_name == "TradeEvent":
        quote_amount = _required_nonnegative_int(event, "quote_amount")
        legacy_sol = False
        if quote_amount == 0:
            quote_amount = _required_nonnegative_int(event, "sol_amount")
            legacy_sol = quote_amount > 0
        base_amount = _required_nonnegative_int(event, "token_amount")
        virtual_quote = _required_nonnegative_int(event, "virtual_quote_reserves")
        virtual_base = _required_nonnegative_int(event, "virtual_token_reserves")
        return EarlyTradeObservation(
            mint=_required_text(event, "mint"),
            wallet=_required_text(event, "user"),
            timestamp=_required_timestamp(event, "timestamp"),
            side="buy" if _required_bool(event, "is_buy") else "sell",
            quote_amount_atomic=quote_amount,
            base_amount_atomic=base_amount,
            trade_price_atomic=_positive_ratio(quote_amount, base_amount),
            curve_price_atomic=_positive_ratio(virtual_quote, virtual_base),
            source_event="TradeEvent",
            used_legacy_sol_amount=legacy_sol,
        )

    if event.program_id == PUMP_AMM_PROGRAM_ID and event.event_name in {"BuyEvent", "SellEvent"}:
        if amm_mint is None:
            raise ValueError("amm_mint is required because PumpSwap trade events omit the base mint")
        _validate_nonempty_text(amm_mint, "amm_mint")
        is_buy = event.event_name == "BuyEvent"
        quote_field = "quote_amount_in" if is_buy else "quote_amount_out"
        base_field = "base_amount_out" if is_buy else "base_amount_in"
        quote_amount = _required_nonnegative_int(event, quote_field)
        base_amount = _required_nonnegative_int(event, base_field)
        pool_quote = _required_nonnegative_int(event, "pool_quote_token_reserves")
        pool_base = _required_nonnegative_int(event, "pool_base_token_reserves")
        return EarlyTradeObservation(
            mint=amm_mint,
            wallet=_required_text(event, "user"),
            timestamp=_required_timestamp(event, "timestamp"),
            side="buy" if is_buy else "sell",
            quote_amount_atomic=quote_amount,
            base_amount_atomic=base_amount,
            trade_price_atomic=_positive_ratio(quote_amount, base_amount),
            curve_price_atomic=_positive_ratio(pool_quote, pool_base),
            source_event=event.event_name,
        )

    raise ValueError(f"unsupported Pump trade event {event.program_id}:{event.event_name}")


def _trade_sort_key(trade: EarlyTradeObservation) -> tuple[object, ...]:
    return (
        trade.timestamp,
        trade.source_event,
        trade.wallet,
        trade.side,
        trade.quote_amount_atomic,
        trade.base_amount_atomic,
    )


def _price_features(
    samples: tuple[tuple[int, float | None], ...],
) -> tuple[float | None, float | None, float | None, float | None]:
    concrete = tuple((timestamp, price) for timestamp, price in samples if price is not None)
    if not concrete:
        return None, None, None, None
    first_timestamp, first = concrete[0]
    last_timestamp, last = concrete[-1]
    assert first is not None and last is not None
    elapsed = last_timestamp - first_timestamp
    velocity = math.log(last / first) / elapsed if elapsed > 0 else None

    peak = first
    drawdown = 0.0
    for _, price in concrete:
        assert price is not None
        peak = max(peak, price)
        drawdown = max(drawdown, (peak - price) / peak)
    return first, last, velocity, drawdown


def _positive_ratio(numerator: int, denominator: int) -> float | None:
    if numerator <= 0 or denominator <= 0:
        return None
    return numerator / denominator


def _required_nonnegative_int(event: AdvisoryPumpEvent, field: str) -> int:
    value = event.fields.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{event.event_name}.{field} must be a non-negative integer")
    return value


def _required_timestamp(event: AdvisoryPumpEvent, field: str) -> int:
    value = event.fields.get(field)
    return _validate_timestamp(value, f"{event.event_name}.{field}")


def _validate_timestamp(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer Unix timestamp")
    if not 0 <= value <= MAX_TIMESTAMP:
        raise ValueError(f"{field} is outside the supported Unix timestamp range")
    return value


def _required_text(event: AdvisoryPumpEvent, field: str) -> str:
    value = event.fields.get(field)
    if not isinstance(value, str):
        raise TypeError(f"{event.event_name}.{field} must be text")
    _validate_nonempty_text(value, f"{event.event_name}.{field}")
    return value


def _validate_nonempty_text(value: str, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    if not value or len(value) > 128:
        raise ValueError(f"{field} must contain between 1 and 128 characters")


def _required_bool(event: AdvisoryPumpEvent, field: str) -> bool:
    value = event.fields.get(field)
    if not isinstance(value, bool):
        raise TypeError(f"{event.event_name}.{field} must be boolean")
    return value
