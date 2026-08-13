"""Keyless price and pool-state feeds: DexScreener, GeckoTerminal, and Meteora's DLMM API.

**Two aggregators, always, and never one.** The curl is a *level* statistic living at the scale
of a few hundred bps, and studies/RESULT_circuit_model.md §7.2 measured a median cross-source
disagreement of 105 bps with a maximum of 15,493 bps on exactly these pools — against fee bands
of 186-342 bps. Four hours apart the same instrument gave different verdicts on two of five
cycles. So a single-source residual is not a measurement, and this module returns both sources
so the map can report a cycle as *unresolvable* rather than as an opportunity.

**These quotes carry no chain clock.** An aggregator's price is a last-trade price stamped with
nothing, so it is tagged ``ingest`` and must never be joined to a tape row on time. The map
prints it as "as of fetch", separately from every event-time quantity. The one exception is
Meteora's pool state, which carries ``poolStateUpdatedAtBlockTime`` on the portfolio endpoint —
event time, and used as such.

**What the DLMM endpoint gives us that the study could not get.** ``/pools/{addr}`` serves
``pool_config.base_fee_pct`` and a live ``dynamic_fee_pct``. The study had to *sweep* the DLMM
fee leg from 0.20% to 5.00% because "no keyless endpoint" served it; this one does. It also
serves both vault amounts and both token USD prices, so a DLMM edge's TVL is computable rather
than taken from an aggregator's ``liquidity.usd``. Its own ``tvl`` field reads 0.0 for these
pools (they are flagged ``is_blacklisted`` — pump.fun launchpad), which is exactly the kind of
silent zero this project treats as missing rather than as a measurement.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

USER_AGENT = "joshibot-netmap/0.1 (read-only network map)"
DEXSCREENER_PAIRS = "https://api.dexscreener.com/latest/dex/pairs/solana/"
GECKOTERMINAL_MULTI = "https://api.geckoterminal.com/api/v2/networks/solana/pools/multi/"
METEORA_POOL = "https://dlmm.datapi.meteora.ag/pools/"

SOURCE_DEXSCREENER = "dexscreener"
SOURCE_GECKOTERMINAL = "geckoterminal"
SOURCE_METEORA = "meteora_dlmm_api"

#: A price computed from pool state rather than from an aggregator's last trade: the vault
#: balances the tape recorded (constant product, where `p = y/x` exactly) or the DLMM's active
#: bin. Study §7.3 ends with "what would fix §7: read pool state from chain", and this is that
#: channel — reported, stamped with the slot it came from, and deliberately NOT made primary,
#: because a vault holding unclaimed fees would bias `y/x` and that has not been checked here.
SOURCE_CHAIN = "chain_state"


def http_json(url: str, *, timeout: float = 20.0, tries: int = 3) -> Any | None:
    """GET JSON, or ``None``. Never raises: a dead feed degrades the map, it does not stop it."""

    for attempt in range(tries):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
            if attempt == tries - 1:
                return None
            time.sleep(0.8 * (attempt + 1))
    return None


def _f(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


@dataclass(frozen=True, slots=True)
class PoolQuote:
    """One aggregator's view of one pool. ``price_native`` is base priced in quote units."""

    address: str
    source: str
    price_native: float
    base_mint: str = ""
    quote_mint: str = ""
    base_symbol: str = ""
    quote_symbol: str = ""
    base_price_usd: float = 0.0
    liquidity_usd: float = 0.0
    volume_24h_usd: float = 0.0
    txns_24h: int = 0
    txns_1h: int = 0
    fdv_usd: float = 0.0

    @property
    def usable(self) -> bool:
        return self.price_native > 0 and math.isfinite(self.price_native)


@dataclass(frozen=True, slots=True)
class DlmmState:
    """Meteora's own view of a DLMM pool: the bin geometry, the fee config, and the vaults."""

    address: str
    bin_step: int | None = None
    base_fee_pct: float | None = None
    dynamic_fee_pct: float | None = None
    protocol_fee_pct: float | None = None
    token_x_mint: str = ""
    token_y_mint: str = ""
    token_x_amount: float = 0.0
    token_y_amount: float = 0.0
    token_x_price_usd: float = 0.0
    token_y_price_usd: float = 0.0
    current_price: float = 0.0
    is_blacklisted: bool = False

    @property
    def tvl_usd(self) -> float:
        """TVL computed from the vaults, not read from the API's own ``tvl`` field.

        That field reads 0.0 for these pools while the vault amounts and both token prices are
        populated — a suppressed aggregate, not an empty pool. Computing it keeps a real $800
        edge from rendering as a dead one.
        """

        return self.token_x_amount * self.token_x_price_usd + self.token_y_amount * self.token_y_price_usd


@dataclass(slots=True)
class PriceSnapshot:
    """Everything the price feeds served, with their failures kept rather than smoothed away."""

    fetched_at: str
    clock: str = "ingest — aggregator quotes carry no block time and are never joined on time"
    dexscreener: dict[str, PoolQuote] = field(default_factory=dict)
    geckoterminal: dict[str, PoolQuote] = field(default_factory=dict)
    dlmm: dict[str, DlmmState] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def token_price_usd(self, mint: str) -> tuple[float, str]:
        """Best available USD price for a mint, with the pool it came from.

        "Best" is the deepest pool quoting it, on either source — a thin pool's last trade is a
        fossil, and pricing a node off one would propagate that fossil into every flow number.
        """

        best_price, best_liq, best_from = 0.0, -1.0, ""
        for source_name, table in (
            (SOURCE_DEXSCREENER, self.dexscreener),
            (SOURCE_GECKOTERMINAL, self.geckoterminal),
        ):
            for quote in table.values():
                if quote.base_mint == mint and quote.base_price_usd > 0 and quote.liquidity_usd > best_liq:
                    best_price, best_liq, best_from = (
                        quote.base_price_usd,
                        quote.liquidity_usd,
                        f"{source_name}:{quote.address[:6]}",
                    )
        for state in self.dlmm.values():
            for mint_side, price in (
                (state.token_x_mint, state.token_x_price_usd),
                (state.token_y_mint, state.token_y_price_usd),
            ):
                if mint_side == mint and price > 0 and best_price <= 0:
                    best_price, best_from = price, f"{SOURCE_METEORA}:{state.address[:6]}"
        return best_price, best_from


def _parse_dexscreener(payload: Any) -> dict[str, PoolQuote]:
    out: dict[str, PoolQuote] = {}
    pairs = (payload or {}).get("pairs") if isinstance(payload, dict) else None
    for pair in pairs or []:
        if not isinstance(pair, dict):
            continue
        address = str(pair.get("pairAddress", ""))
        if not address:
            continue
        liquidity = pair.get("liquidity") or {}
        volume = pair.get("volume") or {}
        txns = pair.get("txns") or {}
        h24 = txns.get("h24") or {}
        h1 = txns.get("h1") or {}
        base = pair.get("baseToken") or {}
        quote = pair.get("quoteToken") or {}
        out[address] = PoolQuote(
            address=address,
            source=SOURCE_DEXSCREENER,
            price_native=_f(pair.get("priceNative")),
            base_mint=str(base.get("address", "")),
            quote_mint=str(quote.get("address", "")),
            base_symbol=str(base.get("symbol", "")),
            quote_symbol=str(quote.get("symbol", "")),
            base_price_usd=_f(pair.get("priceUsd")),
            liquidity_usd=_f(liquidity.get("usd")),
            volume_24h_usd=_f(volume.get("h24")),
            txns_24h=int(_f(h24.get("buys")) + _f(h24.get("sells"))),
            txns_1h=int(_f(h1.get("buys")) + _f(h1.get("sells"))),
            fdv_usd=_f(pair.get("fdv")),
        )
    return out


def _gecko_mint(entry: dict[str, Any], side: str) -> str:
    """GeckoTerminal names tokens as ``solana_<mint>`` inside ``relationships``."""

    relationship = ((entry.get("relationships") or {}).get(side) or {}).get("data") or {}
    identifier = str(relationship.get("id", ""))
    return identifier.split("_", 1)[1] if "_" in identifier else ""


def _parse_geckoterminal(payload: Any) -> dict[str, PoolQuote]:
    out: dict[str, PoolQuote] = {}
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    for entry in data or []:
        if not isinstance(entry, dict):
            continue
        attributes = entry.get("attributes") or {}
        address = str(attributes.get("address", ""))
        if not address:
            continue
        transactions = attributes.get("transactions") or {}
        h24 = transactions.get("h24") or {}
        h1 = transactions.get("h1") or {}
        volume = attributes.get("volume_usd") or {}
        out[address] = PoolQuote(
            address=address,
            source=SOURCE_GECKOTERMINAL,
            price_native=_f(attributes.get("base_token_price_quote_token")),
            base_mint=_gecko_mint(entry, "base_token"),
            quote_mint=_gecko_mint(entry, "quote_token"),
            base_price_usd=_f(attributes.get("base_token_price_usd")),
            liquidity_usd=_f(attributes.get("reserve_in_usd")),
            volume_24h_usd=_f(volume.get("h24")),
            txns_24h=int(_f(h24.get("buys")) + _f(h24.get("sells"))),
            txns_1h=int(_f(h1.get("buys")) + _f(h1.get("sells"))),
            fdv_usd=_f(attributes.get("fdv_usd")),
        )
    return out


def _parse_dlmm(payload: Any) -> DlmmState | None:
    if not isinstance(payload, dict) or not payload.get("address"):
        return None
    config = payload.get("pool_config") or {}
    token_x = payload.get("token_x") or {}
    token_y = payload.get("token_y") or {}
    bin_step = config.get("bin_step")
    return DlmmState(
        address=str(payload.get("address")),
        bin_step=int(bin_step) if isinstance(bin_step, (int, float)) else None,
        base_fee_pct=_f(config.get("base_fee_pct")) if config.get("base_fee_pct") is not None else None,
        dynamic_fee_pct=(
            _f(config.get("dynamic_fee_pct"))
            if config.get("dynamic_fee_pct") is not None
            else _f(payload.get("dynamic_fee_pct"))
        ),
        protocol_fee_pct=(
            _f(config.get("protocol_fee_pct")) if config.get("protocol_fee_pct") is not None else None
        ),
        token_x_mint=str(token_x.get("address", "")),
        token_y_mint=str(token_y.get("address", "")),
        token_x_amount=_f(payload.get("token_x_amount")),
        token_y_amount=_f(payload.get("token_y_amount")),
        token_x_price_usd=_f(token_x.get("price")),
        token_y_price_usd=_f(token_y.get("price")),
        current_price=_f(payload.get("current_price")),
        is_blacklisted=bool(payload.get("is_blacklisted")),
    )


def fetch_prices(
    pool_addresses: list[str],
    *,
    dlmm_addresses: list[str] | None = None,
    now: datetime | None = None,
) -> PriceSnapshot:
    """Fetch both aggregators plus DLMM pool state. Any feed may fail; the map says which did."""

    snapshot = PriceSnapshot(fetched_at=(now or datetime.now(UTC)).astimezone(UTC).isoformat())
    if not pool_addresses:
        return snapshot

    for start in range(0, len(pool_addresses), 25):
        chunk = pool_addresses[start : start + 25]
        payload = http_json(DEXSCREENER_PAIRS + ",".join(chunk))
        if payload is None:
            snapshot.errors.append(f"{SOURCE_DEXSCREENER}: no response for {len(chunk)} pools")
            continue
        snapshot.dexscreener.update(_parse_dexscreener(payload))

    for start in range(0, len(pool_addresses), 25):
        chunk = pool_addresses[start : start + 25]
        payload = http_json(GECKOTERMINAL_MULTI + ",".join(chunk))
        if payload is None:
            snapshot.errors.append(f"{SOURCE_GECKOTERMINAL}: no response for {len(chunk)} pools")
            continue
        snapshot.geckoterminal.update(_parse_geckoterminal(payload))

    for address in dlmm_addresses or []:
        state = _parse_dlmm(http_json(METEORA_POOL + address))
        if state is None:
            snapshot.errors.append(f"{SOURCE_METEORA}: no pool state for {address[:8]}")
            continue
        snapshot.dlmm[address] = state

    return snapshot
