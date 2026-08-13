from __future__ import annotations

from decimal import Decimal

from .config import RugConfig
from .domain import (
    PUMP_MINT_AUTHORITY,
    ExitQuote,
    MintSafety,
    PoolSnapshot,
    RugSignal,
    TokenHolding,
)
from .storage import StateStore


class RugDetector:
    def __init__(self, config: RugConfig, state: StateStore):
        self.config = config
        self.state = state

    def pinned_pair(self, mint: str) -> str | None:
        baseline = self.state.get("pool_baselines", mint, default={})
        return str(baseline["pair_address"]) if baseline.get("pair_address") else None

    def assess(
        self,
        *,
        holding: TokenHolding,
        pool: PoolSnapshot | None,
        mint_safety: MintSafety | None,
        quote: ExitQuote | None,
    ) -> RugSignal:
        previous_pool = self.state.get("pool_baselines", holding.mint, default={})
        previous_supply = self.state.get("supply_baselines", holding.mint)
        previous_quote = self.state.get("quote_baselines", holding.mint)

        liquidity_drop: Decimal | None = None
        if pool is not None and previous_pool.get("reserve_value") is not None:
            prior = Decimal(str(previous_pool["reserve_value"]))
            same_pair = pool.pair_address == previous_pool.get("pair_address")
            same_unit = pool.reserve_unit == previous_pool.get("reserve_unit")
            current = pool.reserve_value
            if prior > 0 and same_pair and same_unit:
                liquidity_drop = max(Decimal(0), (Decimal(1) - current / prior) * 100)

        supply_growth: Decimal | None = None
        if mint_safety is not None and previous_supply is not None and int(previous_supply) > 0:
            supply_growth = (
                Decimal(mint_safety.supply) / Decimal(int(previous_supply)) - Decimal(1)
            ) * 100

        quote_collapse: Decimal | None = None
        if quote is not None and previous_quote is not None:
            previous_unit = Decimal(str(previous_quote))
            current_unit = quote.unit_price_sol(holding)
            if previous_unit > 0:
                quote_collapse = max(Decimal(0), (Decimal(1) - current_unit / previous_unit) * 100)

        if (
            mint_safety is not None
            and mint_safety.mint_authority is not None
            and mint_safety.mint_authority != PUMP_MINT_AUTHORITY
            and supply_growth is not None
            and supply_growth >= Decimal(str(self.config.mint_supply_growth_pct))
        ):
            return RugSignal(
                True,
                f"mint supply grew {supply_growth:.2f}% while mint authority is active",
                liquidity_drop,
                supply_growth,
                False,
            )

        active_mint_with_drop = (
            mint_safety is not None
            and mint_safety.mint_authority is not None
            and mint_safety.mint_authority != PUMP_MINT_AUTHORITY
            and liquidity_drop is not None
            and liquidity_drop >= Decimal(str(self.config.active_mint_liquidity_drop_pct))
        )
        drained = (
            liquidity_drop is not None
            and liquidity_drop >= Decimal(str(self.config.liquidity_drop_pct))
        )
        # Missing provider data is UNKNOWN, not ZERO. A provider outage can
        # degrade protection and alert loudly, but can never become rug evidence.
        exit_door_collapsed = quote_collapse is not None and quote_collapse >= Decimal(
            str(self.config.quote_collapse_pct)
        )
        if (drained or active_mint_with_drop) and exit_door_collapsed:
            qualifier = " with active mint authority" if active_mint_with_drop else ""
            return RugSignal(
                True,
                f"primary pool reserve fell {liquidity_drop:.2f}%{qualifier}",
                liquidity_drop,
                supply_growth,
                True,
            )
        return RugSignal(False, None, liquidity_drop, supply_growth, False)

    def record(
        self,
        *,
        holding: TokenHolding,
        pool: PoolSnapshot | None,
        mint_safety: MintSafety | None,
        quote: ExitQuote | None,
    ) -> None:
        if pool is not None:
            self.state.set(
                "pool_baselines",
                holding.mint,
                value={
                    "pair_address": pool.pair_address,
                    "dex_id": pool.dex_id,
                    "reserve_value": str(pool.reserve_value),
                    "reserve_unit": pool.reserve_unit,
                    "liquidity_usd": str(pool.liquidity_usd),
                    "observed_at": pool.observed_at.isoformat(),
                },
            )
        if mint_safety is not None:
            self.state.set("supply_baselines", holding.mint, value=mint_safety.supply)
        if quote is not None:
            self.state.set(
                "quote_baselines", holding.mint, value=str(quote.unit_price_sol(holding))
            )
